"""中文分词（bigram）+ 受保护术语抽取。

为什么不用 jieba：
- 依赖不可控（两边 Python 环境不一致），且法规文本里真正决定命中率的是
  「第三十九条」「GB 6441」「F2」这类**术语整体**，分词器反而会把它们切碎。
- 词典词（临边洞口、危大工程、超过一定规模）在 bigram 下天然被覆盖，
  且 bigram 对未登录词（新条号、新工法名）没有 OOV 问题。

两类 token：
1. 保护片段 PROTECTED —— 编码（M1/F2/T2/H1）、标准号（GB 6441—2025、GB/T 13861）、
   法规号（国务院令第393号、建办质〔2018〕31号）、条号（第三十九条）。
   整体保留，归一化后作为单 token。
2. 普通中文 —— 先按停用字切成短语，短语内生成 bigram（长度 1 的短语保留单字）。

否定词（未/无/不/非/禁止）**不进停用表**：它们是 CAICS 编码的核心信号
（"无人监管"→M1、"未系安全带"→F4），停掉等于把最重要的特征删了。
"""

from __future__ import annotations

import re
import unicodedata

# ── 受保护术语 ──────────────────────────────────────────────────

# CAICS 编码：M/F/T/H/C + 1..4。前后不能紧邻字母数字，避免把 "F25" 当 F2
_CAICS_RE = re.compile(r"(?<![A-Za-z0-9])([MFTHC][1-5])(?![0-9])")

# 标准号：GB 6441—2025 / GB/T 13861-2022 / JGJ 80—2016 / GB 55034-2022
_STD_RE = re.compile(
    r"((?:GB|GBT|JGJ|CJJ|JG|DB|ISO|EN)(?:\s*/\s*T)?)\s*(\d{2,5})"
    r"(?:\s*[—\-－]\s*(\d{4}))?",
    re.IGNORECASE,
)

# 法规号：国务院令第393号 / 住建部令第37号 / 建办质〔2018〕31号 / 安监总局令第77号
_DECREE_RE = re.compile(
    r"([\u4e00-\u9fff]{2,12}(?:令|公告|通知)?)"
    r"(?:第\s*)?([〔\[\(]?\d{4}[〕\]\)]?\s*)?第?\s*(\d{1,4})\s*号"
)

# 条号：第三条 / 第三十九条 / 第 14 条 / 4.1.1 式条款
_CLAUSE_CN_RE = re.compile(r"第([一二三四五六七八九十百零〇两]{1,6})条")
_CLAUSE_NUM_RE = re.compile(r"(?<![\d.])(\d{1,2}(?:\.\d{1,2}){1,3})(?![\d.])")

# 中文连续串（含常见全角标点会被切掉）
_CJK_RUN_RE = re.compile(r"[\u4e00-\u9fff]+")

# 停用字：只放虚词与高频连接成分，**不含否定词**
STOP_CHARS = set(
    "的了着过是在和与及或等对为从到被将把因由于也都而其该这那有个之以并且但却就又很更最"
    "会能可要应需此者所则如若并同仍已经还再才只仅每各某本上下中间时候后前内外边处当"
)

# 单字 token 的最小 IDF 保护：这些单字在中文里信息量高，允许单独成 token
KEEP_SINGLE = set("坍塌坠落触电火灾爆炸中毒窒息溺伤死埋压滑移沉降倾斜断裂失稳超载漏水淹")


def normalize(text: str) -> str:
    """全角转半角、统一破折号、压缩空白。不改动中文本身。"""
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("—", "-").replace("–", "-").replace("－", "-")
    text = re.sub(r"[ \t\u3000]+", " ", text)
    return text.strip()


def _norm_std(m: re.Match) -> str:
    prefix = m.group(1).replace(" ", "").upper()
    num = m.group(2)
    year = m.group(3)
    # GB/T 13861 与 GBT13861 归一
    if prefix == "GB/T":
        prefix = "GBT"
    return f"{prefix.lower()}{num}" + (f"_{year}" if year else "")


def extract_protected(text: str) -> list[str]:
    """抽取受保护术语（已归一化）。供索引/查询共用，保证两侧口径一致。"""
    text = normalize(text)
    out: list[str] = []

    for m in _CAICS_RE.finditer(text):
        out.append(m.group(1).upper())

    for m in _STD_RE.finditer(text):
        out.append(_norm_std(m))

    for m in _DECREE_RE.finditer(text):
        number = m.group(3)
        # 只保留「令/通知/公告」型的法规号，避免把「2024年18条」误当法规号
        head = m.group(1)
        if any(k in head for k in ("令", "通知", "公告", "规定", "办法")):
            out.append(f"decree{number}")

    for m in _CLAUSE_CN_RE.finditer(text):
        out.append(f"clause{m.group(1)}")

    return out


def _split_stop(run: str) -> list[str]:
    """按停用字把中文长串切成短语。"""
    parts, buf = [], []
    for ch in run:
        if ch in STOP_CHARS:
            if buf:
                parts.append("".join(buf))
                buf = []
        else:
            buf.append(ch)
    if buf:
        parts.append("".join(buf))
    return parts


def tokenize(text: str, *, keep_single: bool = True) -> list[str]:
    """返回 token 列表（可重复，重复即词频）。"""
    if not text:
        return []

    protected = extract_protected(text)
    tokens: list[str] = list(protected)

    for run in _CJK_RUN_RE.findall(normalize(text)):
        for part in _split_stop(run):
            n = len(part)
            if n == 1:
                if keep_single and part in KEEP_SINGLE:
                    tokens.append(part)
                continue
            # bigram：覆盖所有双字组合，词典词天然被包含
            for i in range(n - 1):
                tokens.append(part[i:i + 2])
            # 三字以上的专名额外保留首尾组合，提升「超过一定规模」这类长术语权重
            if n >= 3:
                for i in range(n - 2):
                    tokens.append(part[i:i + 3])

    # 数字/拉丁串（工期、层数、米数）保留，规范阈值检索要用
    for m in re.finditer(r"[A-Za-z]{2,}|\d+(?:\.\d+)?", normalize(text)):
        s = m.group(0).lower()
        if not re.fullmatch(r"[mfthc][1-4]", s):  # 已由 protected 处理
            tokens.append(s)

    return tokens


def tokenize_query(text: str) -> list[str]:
    """查询侧分词。当前与文档侧一致，留出后续加权/扩展的接口。"""
    return tokenize(text)
