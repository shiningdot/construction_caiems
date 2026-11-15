"""CAICS 类目概念卡加载与索引。

概念卡是**确定性知识**，不走相似度：编码结果里出现 F2，就应该直接把 F2 卡原文给
模型看，而不是拿「F2 是什么」去和 847 条法规抢 BM25 排名。所以这里提供
`by_code` 直取，retriever 在排序后又用它对命中项加权。

卡片文件由 scripts/build_concept_cards.py 生成，改内容请改那个脚本，
不要手改 jsonl —— 否则下次重新生成会覆盖。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

DEFAULT_CARDS = Path(__file__).resolve().parents[2] / "corpus" / "concept_cards.jsonl"

# 19 类编码的确定顺序（M→F→T→H→C，层内按号）。用于 prompt 里稳定排序，
# 避免每次检索顺序抖动影响模型判断。
CAICS_ORDER = [
    "M1", "M2", "M3", "M4", "M5",
    "F1", "F2", "F3", "F4",
    "T1", "T2", "T3", "T4",
    "H1", "H2", "H3", "H4",
    "C1", "C2",
]


def load_cards(path: str | Path | None = None) -> dict[str, dict]:
    """返回 {code: chunk}。文件缺失时返回空 dict（RAG 关闭也能跑）。"""
    p = Path(path) if path else DEFAULT_CARDS
    if not p.exists():
        return {}
    out: dict[str, dict] = {}
    with p.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            card = json.loads(line)
            code = (card.get("taxonomy") or {}).get("code")
            if code:
                out[code] = card
    return out


CAICS_CARDS: dict[str, dict] = load_cards()


def get_card(code: str) -> dict | None:
    return CAICS_CARDS.get(code.upper())


def sort_codes(codes: Iterable[str]) -> list[str]:
    """按 CAICS 层次顺序排序，未知编码排在最后并按字母序。"""
    known = [c for c in CAICS_ORDER if c in set(codes)]
    unknown = sorted(set(codes) - set(known))
    return known + unknown


def render_card(code: str, *, max_chars: int = 460, with_exclusions: bool = False) -> str:
    """把一张卡压成 prompt 片段。

    **默认不带【不适用】**。实测带排除项会让模型整体收缩编码（R 掉 0.19、P 不动），
    因为「不适用」在人看来是复核提示，在模型看来是抑制指令。排除项留给复核界面用
    （CLI card 命令走完整 text，不受这里影响）。
    """
    card = CAICS_CARDS.get(code)
    if not card:
        return ""
    tax = card["taxonomy"]

    head = f"{tax['code']} {tax['name']}（{tax['layer']} 层·{tax['layer_name']}）\n"
    head += f"【定义】{tax['definition']}\n"
    cues = "；".join(tax.get("cues", [])[:5])
    if cues:
        head += f"【命中信号】{cues}\n"
    boundary = "；".join(f"与 {b['with']}：{b['rule']}" for b in tax.get("boundary", []))
    if boundary:
        head += f"【边界】{boundary}"
    if with_exclusions and tax.get("exclusions"):
        head += "\n【不适用】" + "；".join(tax["exclusions"])
    return head[:max_chars] + ("…" if len(head) > max_chars else "")
