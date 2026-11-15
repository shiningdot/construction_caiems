# CAICS / CAIEMS release package

Reproduction package for:

> A Causation Extraction Pipeline for Construction Accidents Based on the CAICS Coding System
> Sun Tianhao et al., submitted to *Expert Systems with Applications*

## Contents

```
release/
├── LICENSE                      MIT (code)
├── DATA_LICENSE                 CC BY 4.0 (released data)
├── DATA_DICTIONARY.md           schema and masking rules
├── data/
│   ├── caiems_public.db         de-identified snapshot: 2,601 accidents, 15,838 cause codes
│   └── snapshot_report.json     row counts and residual-PII scan
└── on_request/                  not part of the public release; see PUBLISH_MANIFEST.md
    └── corpus/                  public statutes, category cards, standards manifest
```

Core code lives in the project repository: <https://github.com/shiningdot/construction_agent> (MIT).
Prompt templates and experiment/evaluation scripts are provided on request.
The release accompanies the manuscript. Requests for the controlled-access materials (reference labels, prompt templates, experiment and evaluation scripts) go to suntianhao@njtech.edu.cn.

## What is public and what is not

| Item | Status | Notes |
|---|---|---|
| Core runtime code (`rag/`, `hfacs.py`, `config.py`, `llm_client.py`) | Public | MIT |
| Prompt templates, prompt-construction code, evaluation and figure scripts | On request | Authors' design; sent for non-commercial academic verification |
| Accident database snapshot (structured attributes + codes + masked evidence) | Public | CC BY 4.0, de-identified |
| Laws and regulations (318 clauses), category cards | On request | Rebuildable from official sources; card set sent on request |
| GB/GB/T standard full texts | Not redistributed | Identified by number and title |
| Third-party news, textbook cases, investigation report texts | Not redistributed | Copyright; raw texts removed from the snapshot |
| 300-case expert annotation set | Controlled access | Data-use agreement; apply to the corresponding author |

The 300-case annotation set is the human reference standard used for evaluation.
It is not openly released: it records cell-level judgements by three named experts,
and open release would both expose the annotators and remove the held-out status of the
benchmark. Requests for non-commercial academic verification go to suntianhao@njtech.edu.cn and are reviewed by the
annotators and the authors' institution.

## Reproducing the reported results

The release ships **code and the de-identified database only**. Intermediate experiment
outputs (per-case model predictions, evaluation JSONs, bootstrap dumps under
`experiments/`) are not published, so metrics that depend on a particular model run
cannot be recomputed from the release alone; they are recomputed by re-running the
model calls with the prompts and model versions in the manuscript.

What can be recomputed from the release without model access:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Retrieval-side checks require the corpus subset (available on request)
python -m construction_agent.rag stats

# Figure and mining scripts are provided on request; they read the released database.
```

With the 300-case reference labels (controlled access, see below) and model access, the
coding metrics in Tables 3 and C.1–C.2 are reproduced by the scripts in
`scripts/golden_s1/` at the temperature and model versions of Table B.1.

## Snapshot caveats

- Row counts refer to the snapshot used in the manuscript (2,601 accidents, 15,838 codes).
  Earlier working snapshots (2,623 / 16,323) are superseded and not released.
- Evidence fields are masked: identity-card and phone numbers, company names, and named
  individuals were replaced with `[ID]`, `[PHONE]`, `[UNIT]`, `[PERSON]`.
- Free-text report bodies, source URLs, project and contractor names are removed;
  only structured attributes and cause codes remain.

## License

Code: MIT (see `LICENSE`). Released data: CC BY 4.0 (see `DATA_LICENSE`).
