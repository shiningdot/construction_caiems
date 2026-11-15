# 发布清单（Public release manifest）

原则：**只公开「脱敏数据库 + 主要代码」。** 细粒度代码、完整数据与实验产物不随包发布，
研究者可邮件联系作者获取。分三档：

- **A 公开**：随 GitHub 仓库发布（论文尚未投稿，暂不申请 DOI）。
- **B 索取**：不公开分发，邮件（suntianhao@njtech.edu.cn）申请后按需提供（非商业学术用途）。
- **C 不发布**：含个人信息、第三方全文或密钥，任何情况下都不提供原文。

## A 公开

### A1 核心运行代码（不含提示设计）

| 路径 | 说明 |
|---|---|
| `construction_agent/rag/{__init__,__main__,bm25,cards,context,retriever,tokenize}.py` | BM25 + 类目卡 + 上下文组装 |
| `construction_agent/hfacs.py` | 5 层 19 类定义 |
| `construction_agent/config.py`、`llm_client.py` | 配置与模型调用封装（不含密钥） |

### A2 数据与元数据

脱敏数据库与说明文档见 A4/A5。

### A3 （空）

提示模板、提示构建、评测脚本、图表与挖掘脚本均不公开，见 B 档。

### A4 数据

| 路径 | 说明 |
|---|---|
| `release/data/caiems_public.db` | 脱敏数据库：2,601 事故 / 15,838 编码 / 57 枚举 |
| `release/data/snapshot_report.json` | 行数与掩码扫描 |

### A5 元数据

`LICENSE`、`DATA_LICENSE`、`README.md`、`DATA_DICTIONARY.md`、`.env.example`、`requirements.txt`。

## B 索取（邮件申请，非商业学术用途）

| 内容 | 为什么不公开 |
|---|---|
| 提示设计相关：`construction_agent/extraction/step1_basic_extractor.py`、`step2_caics_encoder.py`（内嵌系统提示）、`scripts/golden_s1/prompts/`、`prompt_build.py`、`s5_layers.py`、`experiments/experiment_6strategies/run_S*.py` | 属作者自己的提示设计，不公开 |
| 评测与出图脚本：`scripts/golden_s1/bootstrap_*.py`、`agreement_kappa.py`、`apply_*`、`scripts/rag_eval_*.py`、`scripts/build_coding_eval_set.py`、`scripts/figs/`、`scripts/figkit/`、`scripts/ch5_basic_mining.py` | 中间过程脚本，按需提供 |
| 完整管道模块：`construction_agent/{extraction 其余,collector,search,review,web,evaluation,output,utils,models,database,versions}` | 应用与运维代码，与论文结论无关 |
| `scripts/` 顶层其余约 180 个脚本（`apply_*_docx`、`rewrite_*`、`check_25xx`、迁移与审计脚本）与 `scripts/golden_s1/` 其余约 80 个一次性分析脚本 | 细粒度工具与一次性分析，颗粒度过细，逐份公开无助于复现 |
| 检索语料子集：`release/corpus/`（公开条文 318 条 + 19 张类目卡 + 文档清单 + GB 题录） | 属“详细数据”；法规可自行从官方渠道获取，类目卡可索取 |
| 300 条专家标注集 `experiments/golden_standard/gt_manual/` | 受标注协议约束，需标注专家与单位同意 |
| 逐案模型输出与评测 JSON（`experiments/**`） | 含原文片段与中间结果 |
| 原库 `data/caiems_v2.db` 的未脱敏版本 | 含个人信息与第三方原文 |

## C 不发布

| 内容 | 原因 |
|---|---|
| `accidents.raw_text`、`search_enriched_text`、第三方新闻/教材/调查报告全文 | 版权 + 个人信息 |
| `data/images/`、`asset/ebook/` | 肖像与版权；电子书来源未授权 |
| GB/GB/T 标准全文 | 标准版权；只给编号与名称 |
| `.env*`（除 `.env.example`）、备份、会话记录 | 密钥 |

## 与声明的对应

两稿声明写的是：代码公开、脱敏数据库公开、专家标注集受数据使用协议管理、
第三方全文与标准全文不再分发。清单中的 B 档（细粒度代码与详细数据）对应
声明里“可向通讯作者申请”的口径，不改变声明的真实性。

发布前检查：

1. `git check-ignore .env.bak-20260921` 返回已忽略。
2. 公开树中不得出现 `experiments/`、`gt_manual`、`caiems_v2.db`、`.env`、`corpus/` 原目录。
3. `caiems_public.db` 行数为 2,601 / 15,838 / 57。
4. 干净 clone 后跑通 `python -m construction_agent.rag stats` 与 `python scripts/figs/fig3_dataset.py`。
5. 打 tag 并推送公开仓库；DOI 待论文录用后再申请并补入声明。
