# Data dictionary — caiems_public.db

De-identified snapshot of the CAICS accident database.

- Accidents: 2,601 (`accidents`)
- Cause codes: 15,838 (`caics_causes`)
- Enumeration definitions: 57 (`enum_definitions`)
- Encoding: UTF-8, SQLite 3

## accidents

| Column | Type | Description |
|---|---|---|
| id | TEXT | Stable record identifier (same as the one used in the manuscript) |
| publish_date | TEXT | Publication date of the source report |
| date | TEXT | Accident date (YYYY-MM-DD) |
| accident_time | TEXT | Time of day (HH:MM), nullable |
| province / city / district | TEXT | Administrative location |
| weather | TEXT | Weather at the time, nullable |
| project_type | TEXT | Project type (8-value enumeration) |
| building_structure | TEXT | Structural system (12-value enumeration) |
| construction_phase | TEXT | Construction phase (8-value enumeration) |
| work_task | TEXT | Work task (11-value enumeration) |
| work_task_enum | TEXT | Normalised work-task value |
| contractor_type | TEXT | Contractor type (5-value enumeration) |
| accident_type | TEXT | Accident type (12-value enumeration) |
| severity | TEXT | Severity by death toll (4 levels) |
| deaths / injuries / trapped_count | INTEGER | Casualty counts (NULL when not reported) |
| direct_economic_loss | REAL | Direct economic loss, 10^4 CNY |
| collapse_subtype | TEXT | Collapse subtype (only for collapses) |
| fall_height | REAL | Fall height in metres (only for falls) |
| equipment_involved | TEXT | Equipment enumeration |
| material_involved | TEXT | Material enumeration |
| worker_type | TEXT | Trade of the casualties |
| report_type | TEXT | Source genre: news / investigation / government bulletin / textbook |
| text_type | TEXT | Text classification (single / multi / other) |
| classification_verdict | TEXT | Classifier decision |
| classification_confidence | REAL | Classifier confidence |
| source_count | INTEGER | Number of sources merged into this record |

Removed from the public snapshot: title, source URLs and names, detailed location,
project / developer / contractor / supervision-company names, direct cause free text,
summary, raw report text, enriched text, crawl and pipeline timing fields.

## caics_causes

| Column | Type | Description |
|---|---|---|
| accident_id | TEXT | Foreign key to `accidents.id` |
| code | TEXT | CAICS code (M1–M5, F1–F4, T1–T4, H1–H4, C1–C2) |
| name | TEXT | Category name |
| evidence | TEXT | Supporting span, masked |
| inference | TEXT | Inference rationale, masked |
| evidence_quality | TEXT | `direct_quote` / `indirect_infer` / `weak_infer` |
| sort_order | INTEGER | Order within the record |

## enum_definitions

| Column | Type | Description |
|---|---|---|
| enum_type | TEXT | Enumeration family |
| code | TEXT | Value code |
| name | TEXT | Value label |
| definition | TEXT | Definition |
| decision_rule | TEXT | Assignment rule |
| sort_order | INTEGER | Display order |

## Masking rules

Applied to `evidence` and `inference`:

| Pattern | Replacement |
|---|---|
| 18-digit identity-card numbers | `[ID]` |
| 11-digit mobile numbers | `[PHONE]` |
| Company names (`…有限公司`, `…集团`, `…公司`) | `[UNIT]` |
| Titles with names (`…经理`, `…总工`, `…班长`) | `[PERSON]` |
| `某某` / `某` / `姓××` / `王#翔` style names | `[PERSON]` |

Residual scans report 0 identity-card numbers, 0 phone numbers, and only generic
mentions of “company” (no company names) in the released evidence fields.

## Not included

- Raw third-party report texts and source links (copyright, personal data).
- GB/GB/T standard full texts; see `corpus/standards_manifest.json`.
- The 300-case expert annotation set (controlled access, see README).
