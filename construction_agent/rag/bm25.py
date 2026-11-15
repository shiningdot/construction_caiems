"""BM25 倒排索引（纯标准库）。

只负责数学，不关心文档长什么样：文档以 `[(token, weight), ...]` 传入，
字段权重（正文/标题/别名）由上层 retriever 决定。这样同一套索引既能索引
法规条文，也能索引类目卡，不必写两套。

默认参数 k1=1.5, b=0.75 是 BM25 常规取值；法规条文长度差异大（第 5 条 20 字
vs 第 40 条 400 字），b 不宜再高，否则长条文被过度惩罚——危大工程清单恰恰
是长条文。
"""

from __future__ import annotations

import heapq
import math
from collections import Counter, defaultdict
from typing import Iterable, Sequence

DEFAULT_K1 = 1.5
DEFAULT_B = 0.75


class BM25Index:
    """不可变倒排索引。构建一次，查询多次。"""

    __slots__ = ("k1", "b", "n", "avgdl", "postings", "doc_len")

    def __init__(
        self,
        docs: Sequence[Iterable[tuple[str, float]]],
        *,
        k1: float = DEFAULT_K1,
        b: float = DEFAULT_B,
    ) -> None:
        self.k1 = k1
        self.b = b
        self.n = len(docs)

        postings: dict[str, dict[int, float]] = defaultdict(dict)
        doc_len: list[float] = []

        for i, toks in enumerate(docs):
            tf: Counter[str] = Counter()
            dl = 0.0
            for tok, w in toks:
                tf[tok] += w
                dl += w
            doc_len.append(dl)
            for tok, w in tf.items():
                postings[tok][i] = w

        self.postings = dict(postings)
        self.doc_len = doc_len
        self.avgdl = (sum(doc_len) / self.n) if self.n else 0.0

    # ── 查询 ──────────────────────────────────────────────

    def idf(self, token: str) -> float:
        df = len(self.postings.get(token, ()))
        if df == 0:
            return 0.0
        return math.log(1.0 + (self.n - df + 0.5) / (df + 0.5))

    def score(
        self,
        query_tokens: Sequence[str],
        *,
        allowed: Sequence[bool] | None = None,
    ) -> list[float]:
        """返回每个文档的 BM25 分数（与索引同序）。

        allowed: 长度 = n 的布尔表，False 的文档记 0（预过滤，省掉后置过滤的
        打分浪费；语料 1k 级其实无所谓，但过滤逻辑放这里能让 top-k 正确）。
        """
        scores = [0.0] * self.n
        if not self.n or not query_tokens:
            return scores

        qtf = Counter(query_tokens)
        k1, b, avgdl = self.k1, self.b, self.avgdl

        for tok, q_count in qtf.items():
            plist = self.postings.get(tok)
            if not plist:
                continue
            idf = self.idf(tok)
            if idf <= 0:
                continue
            w_q = 1.0 + math.log(q_count)  # 查询词重复给轻度加成
            for i, tf in plist.items():
                if allowed is not None and not allowed[i]:
                    continue
                dl = self.doc_len[i]
                denom = tf + k1 * (1.0 - b + b * dl / avgdl) if avgdl else tf + k1
                scores[i] += idf * w_q * (tf * (k1 + 1.0)) / denom

        return scores

    def top_k(
        self,
        query_tokens: Sequence[str],
        k: int,
        *,
        allowed: Sequence[bool] | None = None,
        min_score: float = 0.0,
    ) -> list[tuple[int, float]]:
        """返回 [(doc_idx, score)]，按分数降序，最多 k 条。"""
        scores = self.score(query_tokens, allowed=allowed)
        # 只取正分，避免把全 0 的文档当命中返回（会污染 abstain 判定）
        cand = ((i, s) for i, s in enumerate(scores) if s > min_score)
        return heapq.nlargest(k, cand, key=lambda x: x[1])

    # ── 诊断 ──────────────────────────────────────────────

    def stats(self) -> dict:
        return {
            "docs": self.n,
            "vocab": len(self.postings),
            "avg_doc_len": round(self.avgdl, 1),
        }

    def explain(self, query_tokens: Sequence[str], doc_idx: int, top: int = 8) -> list[tuple[str, float]]:
        """逐词解释某文档的得分构成，排查「为什么没检索到」时用。"""
        k1, b, avgdl = self.k1, self.b, self.avgdl
        dl = self.doc_len[doc_idx]
        out = []
        for tok in dict.fromkeys(query_tokens):
            tf = self.postings.get(tok, {}).get(doc_idx, 0.0)
            if not tf:
                continue
            denom = tf + k1 * (1.0 - b + b * dl / avgdl) if avgdl else tf + k1
            out.append((tok, self.idf(tok) * (tf * (k1 + 1.0)) / denom))
        return sorted(out, key=lambda x: -x[1])[:top]
