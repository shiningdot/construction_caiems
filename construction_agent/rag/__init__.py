"""建筑施工事故致因 RAG 检索包。

设计约束（很重要，改动前先读）：
1. **只用标准库**。项目主 venv 在 WSL 内、桌面侧 Python 是干净的，两边都要能跑，
   所以不引入 jieba / rank_bm25 / numpy。中文用 bigram 切分，靠 IDF 压噪声。
2. **不做向量检索**。语料是法规条文 + 类目卡，规模 1k 级，区分度来自精确术语
   （条号、编码、标准号）而非语义相似度；编码命中必须能硬压过语义相近。
3. **检索结果必须可溯源**。每个命中带 chunk_id / 条号 / 生效日期，编码结果里落引用，
   否则 RAG 只是给 LLM 灌了一段无出处的文字，审稿人会直接打回。

对外入口：
    from construction_agent.rag import Retriever, build_coding_context
"""

from __future__ import annotations

from .bm25 import BM25Index
from .cards import CAICS_CARDS, get_card, load_cards
from .context import RagContext, build_coding_context
from .retriever import Hit, Retriever
from .tokenize import tokenize

__all__ = [
    "BM25Index",
    "CAICS_CARDS",
    "Hit",
    "RagContext",
    "Retriever",
    "build_coding_context",
    "get_card",
    "load_cards",
    "tokenize",
]
