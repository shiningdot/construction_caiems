"""检索门面：BM25 + 结构化过滤 + 编码/文号精确加权。

排序不是纯 BM25。法规检索的实际情况是：
- 用户问「F2 和 T2 怎么分」，必须先出 F2/T2 两张卡，而不是文本里恰好出现「失稳」的条文；
- 问「超过一定规模的模板工程」，31 号文**附件 2**（8m）必须压过附件 1（5m），
  两者文本相似度极高，纯 BM25 分差只有 1e1 量级，会互相挤掉；
- 问「37 号令怎么说」，文号是确定信号，不该参与相似度竞争。

因此打分 = BM25 × 结构化系数。系数全部写在 `_boost()` 里，改行为改那一处即可。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Iterable, Sequence

from .bm25 import BM25Index
from .cards import CAICS_CARDS, CAICS_ORDER, load_cards
from .tokenize import extract_protected, normalize, tokenize

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CHUNKS = ROOT / "corpus" / "chunks.jsonl"
DEFAULT_CARDS = ROOT / "corpus" / "concept_cards.jsonl"

# 字段权重：正文为主，别名词与标题只做补充
FIELD_WEIGHTS = {"text": 1.0, "keywords": 0.9, "title": 0.5, "clause": 0.3}

# intent → 应优先的 chunk_type
INTENT_TYPES = {
    "definition": {"taxonomy_class": 1.45, "theory_concept": 1.35, "standard_clause": 1.1},
    "boundary": {"taxonomy_class": 1.6, "theory_concept": 1.2},
    "compliance": {"statute_article": 1.4, "standard_clause": 1.3, "hazard_criterion": 1.25},
    "measure": {"measure": 1.5, "statute_article": 1.2, "standard_clause": 1.15},
    "statistics": {"stats_fact": 1.6, "accident_type": 1.3},
    "analogy": {"case_card": 1.5, "case_narrative": 1.3},
    "causal_chain": {"case_card": 1.3, "taxonomy_class": 1.2},
    "version_check": {"statute_article": 1.2, "standard_clause": 1.2},
}


@dataclass
class Hit:
    chunk_id: str
    doc_id: str
    chunk_type: str
    text: str
    score: float
    clause: str | None = None
    source_name: str = ""
    attachment: str | None = None
    effective_date: str | None = None
    expire_date: str | None = None
    code: str | None = None          # taxonomy_class 的 CAICS 码
    reasons: list[str] = field(default_factory=list)

    @property
    def citation(self) -> str:
        """一句可读出处，直接进 prompt / 报表。"""
        name = self.source_name or self.doc_id
        parts = [f"《{name}》"]
        if self.clause:
            parts.append(f"{self.clause}")
        if self.attachment:
            parts.append(f"（{self.attachment}）")
        return "".join(parts)

    def to_dict(self) -> dict:
        return {
            "chunk_id": self.chunk_id,
            "doc_id": self.doc_id,
            "chunk_type": self.chunk_type,
            "clause": self.clause,
            "attachment": self.attachment,
            "score": round(self.score, 4),
            "citation": self.citation,
            "code": self.code,
            "reasons": self.reasons,
        }


def _load_jsonl(p: Path) -> list[dict]:
    if not p.exists():
        return []
    rows = []
    with p.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _doc_tokens(chunk: dict) -> list[tuple[str, float]]:
    """把一条知识单元摊成 (token, weight)。"""
    toks: list[tuple[str, float]] = []
    for tok in tokenize(chunk.get("text", "")):
        toks.append((tok, FIELD_WEIGHTS["text"]))

    src = chunk.get("source") or {}
    for tok in tokenize(src.get("name", "")):
        toks.append((tok, FIELD_WEIGHTS["title"]))

    clause = (chunk.get("validity") or {}).get("clause")
    if clause:
        for tok in tokenize(str(clause)):
            toks.append((tok, FIELD_WEIGHTS["clause"]))

    for kw in (chunk.get("retrieval") or {}).get("keywords", []):
        for tok in tokenize(kw):
            toks.append((tok, FIELD_WEIGHTS["keywords"]))

    # 分类卡把编码本身也索引一次，方便「M1 是什么」这类直查
    code = (chunk.get("taxonomy") or {}).get("code")
    if code:
        toks.append((code, FIELD_WEIGHTS["keywords"]))

    return toks


class Retriever:
    """语料 + 类目卡的统一检索器。构造一次约 0.2s，之后每次查询 ms 级。"""

    def __init__(
        self,
        chunks_path: str | Path | None = None,
        cards_path: str | Path | None = None,
        *,
        today: date | None = None,
    ) -> None:
        self.chunks_path = Path(chunks_path) if chunks_path else DEFAULT_CHUNKS
        self.cards_path = Path(cards_path) if cards_path else DEFAULT_CARDS
        self.today = today or date.today()

        self.cards = load_cards(self.cards_path) or CAICS_CARDS
        rows = _load_jsonl(self.chunks_path)
        # 卡片单独存，也进索引（短文档在 BM25 里天然占优，正是想要的）
        card_rows = list(self.cards.values())
        seen = {r["chunk_id"] for r in rows}
        self.docs: list[dict] = rows + [c for c in card_rows if c["chunk_id"] not in seen]

        self.index = BM25Index([_doc_tokens(d) for d in self.docs])
        self._by_id = {d["chunk_id"]: d for d in self.docs}

    # ── 公共 API ──────────────────────────────────────────

    @classmethod
    def from_default(cls, **kw) -> "Retriever":
        return cls(**kw)

    def get(self, chunk_id: str) -> dict | None:
        return self._by_id.get(chunk_id)

    def search(
        self,
        query: str,
        top_k: int = 6,
        *,
        filters: dict | None = None,
        intent: str | None = None,
        min_score: float = 0.0,
        only_ids: set[str] | None = None,
    ) -> list[Hit]:
        """only_ids 给定时只在这些 chunk 里排序（用于按类目卡的 legal_basis 定向取证）。"""
        if not query.strip():
            return []

        allowed = [
            self._match(d, filters) and (only_ids is None or d["chunk_id"] in only_ids)
            for d in self.docs
        ]
        if not any(allowed):
            return []

        qtokens = tokenize(query)
        raw = self.index.score(qtokens, allowed=allowed)

        q_codes = {t.upper() for t in extract_protected(query) if re.fullmatch(r"[MFTHC][1-5]", t)}
        q_docnums = {t for t in extract_protected(query) if t.startswith(("decree", "gb", "gbt", "jgj", "cjj", "clause"))}

        scored: list[tuple[float, int, list[str]]] = []
        for i, base in enumerate(raw):
            if base <= 0:
                continue
            boost, reasons = self._boost(self.docs[i], q_codes, q_docnums, query, intent)
            final = base * boost
            if final > min_score:
                scored.append((final, i, reasons))

        scored.sort(key=lambda x: -x[0])
        out: list[Hit] = []
        for final, i, reasons in scored[:top_k]:
            out.append(self._to_hit(self.docs[i], final, reasons))
        return out

    def cards_for(self, codes: Iterable[str]) -> list[dict]:
        """按 CAICS 码直取概念卡，按层序返回。"""
        want = set(c.upper() for c in codes)
        return [self.cards[c] for c in CAICS_ORDER if c in want and c in self.cards]

    def card_by_signal(self, text: str, limit: int = 4) -> list[dict]:
        """按文本信号挑卡片（走同一套 BM25，不维护第二套匹配逻辑）。

        卡片文本本身是 cue 的集合，IDF 会自然压掉「施工」「作业」这类通用词，
        留下「珍珠岩」「涌水涌沙」「临边防护」这种真正有区分度的信号。
        """
        hits = self.search(text[:400], top_k=limit,
                           filters={"chunk_type": ["taxonomy_class"]})
        out = []
        for h in hits:
            card = self.cards.get(h.code or "")
            if card:
                out.append(card)
        return out

    def stats(self) -> dict:
        by_type: dict[str, int] = {}
        for d in self.docs:
            by_type[d.get("chunk_type", "?")] = by_type.get(d.get("chunk_type", "?"), 0) + 1
        return {**self.index.stats(), "by_type": by_type, "cards": len(self.cards)}

    # ── 内部 ──────────────────────────────────────────────

    def _match(self, chunk: dict, filters: dict | None) -> bool:
        if not filters:
            return True

        for key in ("doc_id", "chunk_type", "language", "jurisdiction"):
            want = filters.get(key)
            if want is None:
                continue
            wants = [want] if isinstance(want, str) else list(want)
            if chunk.get(key) not in wants:
                return False

        val = chunk.get("validity") or {}
        att = filters.get("attachment")
        if att is not None and val.get("attachment") != att:
            return False

        as_of = filters.get("as_of")
        if as_of:
            eff = val.get("effective_date")
            exp = val.get("expire_date")
            if eff and eff > str(as_of):
                return False
            if exp and exp < str(as_of):
                return False

        if filters.get("only_current"):
            exp = val.get("expire_date")
            if exp and exp < self.today.isoformat():
                return False

        return True

    def _boost(
        self,
        chunk: dict,
        q_codes: set[str],
        q_docnums: set[str],
        query: str,
        intent: str | None,
    ) -> tuple[float, list[str]]:
        boost = 1.0
        reasons: list[str] = []

        # 1) 编码精确命中：问 F2 就必须先出 F2 卡
        code = (chunk.get("taxonomy") or {}).get("code")
        if code and code in q_codes:
            boost *= 3.2
            reasons.append(f"编码命中 {code}")
        elif q_codes and chunk.get("chunk_type") == "taxonomy_class":
            # 同层邻接卡给一点加成，方便模型对照边界
            if code and code[0] in {c[0] for c in q_codes}:
                boost *= 1.15
                reasons.append("同层类目卡")

        # 2) 文号/标准号命中
        if q_docnums:
            doc_id = normalize(chunk.get("doc_id", "")).lower().replace("-", "")
            src = normalize((chunk.get("source") or {}).get("name", "")).lower()
            for t in q_docnums:
                if t.startswith("decree"):
                    # decree393 → 命中 doc_id 含 393
                    if t[6:] and t[6:] in doc_id:
                        boost *= 1.8
                        reasons.append(f"文号命中 {t[6:]}号")
                        break
                elif t.startswith("clause"):
                    # 查询抽出的是「十四」，chunk 里存的是「第十四条」或 3.5.9，
                    # 用包含关系而不是等值，否则条号直查永远不生效
                    clause = str((chunk.get("validity") or {}).get("clause") or "")
                    num = t[6:]
                    # 「第二十四条」contains「十四」，包含匹配会把 24/34 条一起顶上来。
                    # 抽出条号数字做等值比较，才是真正的条号直查。
                    m = re.match(r"^第(.+?)条$", clause)
                    clause_num = m.group(1) if m else clause
                    if num and num == clause_num:
                        boost *= 2.5
                        reasons.append(f"条号命中 第{num}条")
                        break
                elif t.split("_")[0] in doc_id or t.split("_")[0] in src:
                    boost *= 1.6
                    reasons.append(f"标准号命中 {t}")
                    break

        # 3) intent → 类型
        if intent and intent in INTENT_TYPES:
            w = INTENT_TYPES[intent].get(chunk.get("chunk_type"))
            if w:
                boost *= w
                reasons.append(f"intent={intent}")

        # 4) 危大工程附件 1/2 分离（31 号文的已知陷阱）
        att = (chunk.get("validity") or {}).get("attachment")
        if att and "建办质" in chunk.get("doc_id", ""):
            if re.search(r"超过一定规模|专家论证|8m|18m|50m|150m", query):
                boost *= 1.6 if att == "附件2" else 0.75
                reasons.append(f"{att} 优先（超规模语义）")
            elif re.search(r"危大工程范围|危险性较大|5m|10m|24m", query):
                boost *= 1.4 if att == "附件1" else 0.85
                reasons.append(f"{att} 优先（危大范围语义）")

        # 5) 失效文件降权而非剔除：需要时仍可召回过期版本做版本对比
        exp = (chunk.get("validity") or {}).get("expire_date")
        if exp and exp < self.today.isoformat():
            boost *= 0.6
            reasons.append("已失效")

        return boost, reasons

    @staticmethod
    def _to_hit(chunk: dict, score: float, reasons: list[str]) -> Hit:
        val = chunk.get("validity") or {}
        return Hit(
            chunk_id=chunk["chunk_id"],
            doc_id=chunk.get("doc_id", ""),
            chunk_type=chunk.get("chunk_type", ""),
            text=chunk.get("text", ""),
            score=score,
            clause=val.get("clause"),
            source_name=(chunk.get("source") or {}).get("name", ""),
            attachment=val.get("attachment"),
            effective_date=val.get("effective_date"),
            expire_date=val.get("expire_date"),
            code=(chunk.get("taxonomy") or {}).get("code"),
            reasons=reasons,
        )
