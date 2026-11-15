# CAICS / CAIEMS — paper release

Code and de-identified data accompanying:

> A Causation Extraction Pipeline for Construction Accidents Based on the CAICS Coding System
> Sun Tianhao et al.

## What this repository contains

- `construction_agent/hfacs.py` — CAICS taxonomy (5 layers, 19 categories)
- `construction_agent/rag/` — BM25 retrieval layer with category cards and context assembly
- `construction_agent/config.py`, `llm_client.py` — configuration and model-client utilities
- `release/data/caiems_public.db` — de-identified database snapshot (2,601 accidents, 15,838 cause codes)
- `release/README.md`, `release/DATA_DICTIONARY.md` — data description and schema

## What is not published

Prompt templates, prompt-construction code, evaluation scripts, experiment and figure
scripts, the 300-case expert annotation set, raw third-party report texts, and full texts
of GB/GB/T standards. Requests for non-commercial academic verification:
**suntianhao@njtech.edu.cn**.

See `release/PUBLISH_MANIFEST.md` for the full public / on-request / never-publish split.

## Licenses

Code: MIT (`LICENSE`). Released data: CC BY 4.0 (`DATA_LICENSE`).
