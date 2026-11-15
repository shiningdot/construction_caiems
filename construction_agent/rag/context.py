"""把检索结果组装成编码用的上下文片段。

两个约束决定了这里的设计：
1. **预算**。Step2 的输入本来就只有几百字事故文本，塞 6000 字法条会稀释注意力，
   实测反而掉点。默认 2200 字：4 张卡（约 1000 字）+ 4 条依据（约 900 字）。
2. **可审计**。每段依据都带 [R1] 这样的编号，编码结果里回填 chunk_id，
   这样「为什么记 F2」能追到具体条号，而不是一句「模型认为」。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .cards import CAICS_ORDER, render_card, sort_codes
from .retriever import Hit, Retriever

# 事故文本前段通常只有「时间地点」，因果分析常在中后段（直接原因/间接原因）。
# 因此 query 优先取原因段，再用开头兜底；取全文会被「善后处置」「领导批示」稀释。
QUERY_HEAD = 200
QUERY_CAUSE_WINDOW = 400
QUERY_MAX = 800
DEFAULT_BUDGET = 2400

# 卡片选择走 BM25，H1/H3、M1/M2 这类边界对不一定能被选中；但它们是本任务
# 最稳定的误差来源（H3→H1、M2→M1 替代最多）。两张卡都没进上下文时，
# 直接把边界规则补位注入，避免「改了规则但模型根本没看到」。
ALWAYS_BOUNDARY_PAIRS = (("H1", "H3"), ("M1", "M2"))


def _pair_rule(cards: dict, a: str, b: str) -> str:
    """取 a/b 两卡之间的边界规则（任一侧声明即可）。"""
    for code, other in ((a, b), (b, a)):
        card = cards.get(code) or {}
        for item in (card.get("taxonomy") or {}).get("boundary", []):
            if item.get("with") == other and item.get("rule"):
                return item["rule"]
    return ""


@dataclass
class RagContext:
    text: str = ""
    citations: list[dict] = field(default_factory=list)
    codes: list[str] = field(default_factory=list)
    hits: list[Hit] = field(default_factory=list)
    chars: int = 0

    @property
    def empty(self) -> bool:
        return not self.text.strip()

    def citation_ids(self) -> list[str]:
        return [c["chunk_id"] for c in self.citations]


_CAUSE_MARK_RE = re.compile(r"直接原因|间接原因|事故原因|主要原因|原因分析")


def _cause_snippet(text: str) -> str:
    """截取原因段（首次命中处往前 80 字、往后 QUERY_CAUSE_WINDOW 字）。

    调查报告的原因分析往往在中后段，只取开头会漏掉「立杆间距」「连墙件」
    这类真正决定编码的术语；找不到原因标记时返回空串，由开头兜底。
    """
    m = _CAUSE_MARK_RE.search(text)
    if not m:
        return ""
    start = max(0, m.start() - 80)
    end = min(len(text), m.start() + QUERY_CAUSE_WINDOW)
    return re.sub(r"\s+", " ", text[start:end]).strip()


def _signals(text: str, basic_info: dict | None) -> list[str]:
    """从事故文本 + Step1 结果里提取检索线索（不改动原文）。"""
    bits: list[str] = []
    if basic_info:
        for k in ("accident_type", "work_task", "project_type", "equipment", "material"):
            v = basic_info.get(k)
            if v and isinstance(v, str):
                bits.append(v)

    text = text or ""
    cause = _cause_snippet(text)
    head = re.sub(r"\s+", " ", text)[:QUERY_HEAD]
    if cause:
        bits.append(cause)
    bits.append(head)
    return [" ".join(b for b in bits if b)[:QUERY_MAX]]


def build_coding_context(
    accident_text: str,
    basic_info: dict | None = None,
    *,
    retriever: Retriever | None = None,
    codes: list[str] | None = None,
    top_k: int = 5,
    card_limit: int = 4,
    budget_chars: int = DEFAULT_BUDGET,
    include_statutes: bool = True,
    only_current: bool = True,
) -> RagContext:
    """构造「判定要点 + 规范依据」两段式上下文。

    codes: 已知/待复核的编码（如边界复核场景传入 ["F2","T2"]），给了就直取对应卡。
    """
    r = retriever or Retriever.from_default()
    query = " ".join(_signals(accident_text, basic_info))

    # ── 类目卡 ──────────────────────────────────────────
    card_codes: list[str] = []
    if codes:
        card_codes = [c.upper() for c in codes if c.upper() in r.cards]
    else:
        card_codes = [c["taxonomy"]["code"] for c in r.card_by_signal(accident_text, card_limit)]

    cards = r.cards_for(card_codes)[:card_limit]

    # ── 规范依据 ────────────────────────────────────────
    hits: list[Hit] = []
    if include_statutes and query:
        statute_types = ["statute_article", "standard_clause", "hazard_criterion", "accident_type"]

        # 1) 定向：只在该类目卡声明过的 legal_basis 里排序。
        #    这是「本类目据以判定的条文」，比按事故文本泛检准——
        #    泛检会被「监理」「施工」这类高频词带偏到罚则条款上。
        preferred: list[str] = []
        for card in cards:
            preferred.extend(card["taxonomy"].get("legal_basis", []))
        if preferred:
            hits = r.search(query, top_k=top_k,
                            filters={"chunk_type": statute_types, "only_current": only_current},
                            only_ids=set(preferred))

        # 2) 补足：卡片没覆盖到（如 T4 无直接依据）时回退泛检
        if len(hits) < top_k:
            seen = {h.chunk_id for h in hits}
            extra = r.search(query, top_k=top_k * 2,
                             filters={"chunk_type": statute_types, "only_current": only_current})
            hits += [h for h in extra if h.chunk_id not in seen][: top_k - len(hits)]

        hits = [h for h in hits if h.chunk_type != "taxonomy_class"][:top_k]

    # ── 组装 ────────────────────────────────────────────
    parts: list[str] = []
    chars = 0

    # 边界规则补位：仅在两张卡都未被选中时注入，避免与卡片正文重复。
    selected = set(card_codes)
    boundary_segs: list[str] = []
    for a, b in ALWAYS_BOUNDARY_PAIRS:
        if a in selected or b in selected:
            continue
        rule = _pair_rule(r.cards, a, b)
        if rule:
            boundary_segs.append(f"{a}/{b}：{rule}")

    if cards or boundary_segs:
        block = ["【CAICS 判定要点】"]
        if boundary_segs:
            seg = "【必守边界】" + "；".join(boundary_segs)
            block.append(seg)
            chars += len(seg)
        shown = set()
        for card in cards:
            tax = card["taxonomy"]
            seg = render_card(tax["code"])
            if chars + len(seg) > budget_chars * 0.55:
                break
            block.append(seg)
            shown.add(tax["code"])
            chars += len(seg)

        # 未展开的类目必须列一行。实测只给 4 张卡时，模型的注意力会锁在卡上，
        # 把 H1/M1/T2 这些没展开的层整体漏掉（R 掉 0.12）。
        rest = [c for c in CAICS_ORDER if c not in shown and c in r.cards]
        if rest:
            names = "｜".join(f"{c} {r.cards[c]['taxonomy']['name']}" for c in rest)
            line = f"【其余类目（未展开，仍须按原文判断）】{names}"
            if chars + len(line) <= budget_chars:
                block.append(line)
                chars += len(line)

        if len(block) > 1:
            parts.append("\n".join(block))

    citations: list[dict] = []
    if hits:
        block = ["【规范依据】（引用时写编号，如 [R1]）"]
        for i, h in enumerate(hits, 1):
            snippet = re.sub(r"\s+", " ", h.text).strip()
            if len(snippet) > 420:
                snippet = snippet[:420] + "…"
            line = f"[R{i}] {h.citation}：{snippet}"
            if chars + len(line) > budget_chars:
                break
            block.append(line)
            chars += len(line)
            citations.append({
                "ref": f"R{i}",
                "chunk_id": h.chunk_id,
                "doc_id": h.doc_id,
                "clause": h.clause,
                "attachment": h.attachment,
                "citation": h.citation,
                "effective_date": h.effective_date,
                "score": round(h.score, 3),
            })
        if len(block) > 1:
            parts.append("\n".join(block))

    return RagContext(
        text="\n\n".join(parts),
        citations=citations,
        codes=sort_codes([c["taxonomy"]["code"] for c in cards]),
        hits=hits,
        chars=chars,
    )


def build_boundary_context(
    code_a: str,
    code_b: str,
    *,
    retriever: Retriever | None = None,
    budget_chars: int = 1200,
) -> str:
    """只给两张卡的边界规则。用于「这两个码怎么分」的复核/问答场景。"""
    r = retriever or Retriever.from_default()
    out = []
    for c in sort_codes([code_a, code_b]):
        seg = render_card(c)
        if seg:
            out.append(seg)
    text = "\n\n".join(out)
    return text[:budget_chars]
