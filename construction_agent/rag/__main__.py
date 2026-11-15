"""命令行入口：

    python -m construction_agent.rag search "模板支架坍塌算 F2 还是 T2" --top 5
    python -m construction_agent.rag card F2
    python -m construction_agent.rag context --file accident.txt
    python -m construction_agent.rag stats

设计给两类人用：
- 标注/复核时手动查依据（search / card）；
- 排查「为什么没检索到」（search --debug 打印逐词贡献）。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .context import build_coding_context
from .retriever import Retriever


def _print_hits(hits, debug: bool = False) -> None:
    if not hits:
        print("（无命中）")
        return
    for i, h in enumerate(hits, 1):
        head = f"{i:>2}. [{h.score:6.2f}] {h.chunk_id}  {h.citation}"
        if h.code:
            head += f"  «{h.code}»"
        print(head)
        body = " ".join(h.text.split())
        print("    " + (body[:180] + ("…" if len(body) > 180 else "")))
        if debug and h.reasons:
            print("    ↳ " + "; ".join(h.reasons))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser("construction_agent.rag")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("search", help="检索语料")
    s.add_argument("query")
    s.add_argument("--top", type=int, default=6)
    s.add_argument("--intent", default=None)
    s.add_argument("--doc-id", default=None)
    s.add_argument("--attachment", default=None)
    s.add_argument("--json", action="store_true")
    s.add_argument("--debug", action="store_true")

    c = sub.add_parser("card", help="查看 CAICS 概念卡")
    c.add_argument("code")

    x = sub.add_parser("context", help="为事故文本生成编码上下文")
    x.add_argument("--file", required=True)
    x.add_argument("--codes", default=None, help="逗号分隔，如 F2,T2")
    x.add_argument("--budget", type=int, default=2400)

    sub.add_parser("stats", help="语料与索引统计")

    args = ap.parse_args(argv)
    r = Retriever.from_default()

    if args.cmd == "stats":
        print(json.dumps(r.stats(), ensure_ascii=False, indent=2))
        return 0

    if args.cmd == "card":
        card = r.cards.get(args.code.upper())
        if not card:
            print(f"未找到编码 {args.code}；可用：{', '.join(sorted(r.cards))}")
            return 1
        tax = card["taxonomy"]
        print(f"{tax['code']} {tax['name']}（{tax['layer']} 层·{tax['layer_name']}）")
        print(f"\n【定义】{tax['definition']}")
        print(f"\n【命中信号】{'；'.join(tax['cues'])}")
        print(f"\n【不适用】{'；'.join(tax['exclusions'])}")
        for b in tax.get("boundary", []):
            print(f"\n【与 {b['with']} 的边界】{b['rule']}")
        print(f"\n【典型证据】{'；'.join(tax['typical_evidence'])}")
        print(f"\n【法规依据】{', '.join(tax['legal_basis']) or '（无）'}")
        return 0

    if args.cmd == "context":
        text = Path(args.file).read_text(encoding="utf-8")
        codes = [c.strip() for c in args.codes.split(",")] if args.codes else None
        ctx = build_coding_context(text, codes=codes, budget_chars=args.budget)
        print(ctx.text or "（空上下文）")
        print(f"\n--- {ctx.chars} 字符 / 卡片 {ctx.codes} / 引用 {len(ctx.citations)} 条 ---")
        return 0

    filters = {}
    if args.doc_id:
        filters["doc_id"] = args.doc_id
    if args.attachment:
        filters["attachment"] = args.attachment
    hits = r.search(args.query, top_k=args.top, filters=filters or None, intent=args.intent)
    if args.json:
        print(json.dumps([h.to_dict() for h in hits], ensure_ascii=False, indent=2))
    else:
        _print_hits(hits, debug=args.debug)
    return 0


if __name__ == "__main__":
    sys.exit(main())
