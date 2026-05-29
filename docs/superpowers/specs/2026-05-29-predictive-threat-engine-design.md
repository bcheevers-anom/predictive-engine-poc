# Predictive Threat Engine — Design Spec
**Date:** 2026-05-29
**Status:** Approved for implementation
**Build approach:** Option A — strict build-plan fidelity (§3 repo structure)
**Scope:** Full PoC P0–P4 with review gates after each phase

---

## 1. Goal

Build a batch pipeline that reads ThreatStream **read-only**, freezes a parameterised corpus, runs an LLM Conversion Layer to extract industry/company/tool/tactic signal into a normalised schema, runs a Python prediction engine over that schema, and serves explainable forecasts through a React/FastAPI demo UI.

This is a **proof of concept**. The primary feasibility question is whether the LLM conversion layer can mine usable signal from unstructured blobs at sufficient quality to power better-than-chance forecasts.

---

## 2. Credentials and Secrets

- **ThreatStream:** `TS_API_USER=bcheevers@ilamona.com`, `TS_API_KEY` from `creds.txt`
- **AWS Bedrock:** profile `staging`, region `us-east-1` (AWS SSO)
- **Anthropic:** no key present — Bedrock is the default backend
- **P0 action:** write `.env` from `creds.txt`, delete `creds.txt`, add `.env` and `creds.txt` to `.gitignore` before first commit
- Pre-signed Snapshot S3 URLs are treated as secrets: never logged, never persisted

---

## 3. Architecture

One-directional batch pipeline. Each stage writes a durable artifact; stages re-run independently.

```
[1] Gateway — read-only ThreatStream REST + Snapshot; LLM (Bedrock/Anthropic); cost
        ↓
[2] Frozen corpus — data/frozen/<batch_id>/*.parquet
    Parameterised: --from, --to, --feeds
    Multiple corpora can coexist; each has run_id + config_hash
        ↓
[3] Conversion Layer
    Pass 1: Discovery  → data/coverage/<batch_id>.json
    Pass 2: Extraction → data/schema/<batch_id>.parquet
        ↓
[4] Feature store — data/features/<batch_id>/*.parquet (duckdb-queryable, tier-aware)
        ↓
[5] Prediction engine — data/models/<batch_id>/ (models + eval reports)
        ↓
[6] FastAPI → React demo UI
        ↑ provenance + cost thread through every stage
```

**Re-batch:** the frozen corpus is parameterised by date window and feed list. The dev panel UI and `pte ingest` CLI both accept `--from`, `--to`, `--feeds`. Each run produces a new `batch_id` so multiple corpora coexist. The full pipeline (ingest → convert → features → train → evaluate) re-runs over the selected batch.

**Headline frozen batch:** 2025-01-01 to 2026-05-01, all available feeds, all sectors. The discovery pass surfaces which sectors have enough extracted data to support a forecast.

---

## 4. Repository Structure

Follows build plan §3 exactly.

```
pte/
├── .env                          # gitignored — TS + AWS + Anthropic creds
├── .gitignore
├── README.md
├── pyproject.toml
├── login_bedrock.bat / .sh
├── config/
│   ├── default.yaml              # endpoints, rate limits, horizons, tier policy, seeds
│   ├── feeds.yaml                # per-feed quirks
│   ├── models.yaml               # task -> model map per backend
│   ├── pricing.yaml              # $/token per model per backend
│   └── tasks.yaml                # task defs, metrics, baselines, gates
├── src/pte/
│   ├── gateway/
│   │   ├── threatstream.py       # read-only REST + Snapshot
│   │   ├── snapshot.py
│   │   ├── rate_limit.py
│   │   ├── llm_client.py         # one interface; bedrock|anthropic
│   │   └── cost.py
│   ├── ingest/
│   │   ├── frozen_batch.py       # parameterised ingest → parquet
│   │   └── raw_store.py
│   ├── convert/
│   │   ├── pipeline.py
│   │   ├── discovery.py          # Pass 1: coverage report
│   │   ├── extraction.py         # Pass 2: schema-constrained
│   │   ├── tier1_clean.py
│   │   ├── tier2_parsers/
│   │   │   ├── registry.py
│   │   │   ├── gti_campaign_timeline.py
│   │   │   └── mandiant_actor_assoc.py
│   │   ├── normalize_tags.py
│   │   ├── refang.py
│   │   ├── quarantine.py
│   │   └── confidence.py
│   ├── skills/
│   │   ├── blob_discovery/SKILL.md
│   │   ├── entity_extraction/SKILL.md
│   │   ├── relationship_parse/SKILL.md
│   │   ├── tag_normalise/SKILL.md
│   │   └── narrative/SKILL.md
│   ├── schema/
│   │   ├── models.py             # PTEEntity, SRO, Finding, Provenance, tiers
│   │   └── tiers.py              # authoritative per-field tier map
│   ├── features/
│   │   ├── build.py
│   │   └── store.py
│   ├── predict/
│   │   ├── base.py               # Task ABC
│   │   ├── t1_vuln_exploit.py
│   │   ├── t2_tool_tactic.py
│   │   ├── t2_industry.py
│   │   ├── t3_company.py
│   │   ├── trends.py
│   │   └── baselines.py
│   ├── evaluate/
│   │   ├── splits.py
│   │   ├── metrics.py
│   │   └── report.py
│   ├── explain/
│   │   ├── contributions.py
│   │   └── narrative.py
│   ├── common/
│   │   ├── provenance.py
│   │   ├── logging.py
│   │   └── errors.py
│   └── cli.py
├── api/
│   ├── main.py
│   └── routes/
│       ├── forecast.py
│       ├── trends.py
│       ├── devpanel.py           # re-batch trigger, cost, coverage
│       └── evidence.py
├── web/                          # React + Vite + Recharts
│   └── src/...
├── tests/                        # TC-001..017 + recorded fixtures
├── prompts/                      # versioned prompt text
└── data/                         # gitignored entirely
    ├── raw/
    ├── frozen/
    ├── schema/
    ├── coverage/
    ├── features/
    ├── models/
    └── snapshots/
```

---

## 5. Core Components

### Gateway

- `threatstream.py`: async httpx; cursor pagination via `meta.next`; single-object GET for `description` bodies; read-only guard — only GET and POST-snapshot verbs compiled in; `full_count=1` for true counts; never uses capped 10,000 live count
- `snapshot.py`: POST→poll→download; sha256 per chunk; respects 1-hour pre-signed URL TTL; max 3 concurrent per org; `json_v2` or `stix` format
- `rate_limit.py`: token-bucket + exponential backoff on 429
- `llm_client.py`: `LLM_BACKEND` env var selects `bedrock` (default) or `anthropic`; Bedrock uses boto3 with SSO profile `staging`/`us-east-1`, fails fast with clear message if no session; tiered model selection from `config/models.yaml`:
  - Strong: `us.anthropic.claude-opus-4-8` — discovery + industry/company extraction
  - Mid: `us.anthropic.claude-sonnet-4-6` — narrative generation
  - Fast: `us.anthropic.claude-haiku-4-5-20251001` — tag normalisation + templated cleanup
- `cost.py`: token counting per call; pricing from `config/pricing.yaml`; per-batch rollup; estimate before large run, actuals after

### Ingest

- `frozen_batch.py`: CLI args `--from`, `--to`, `--feeds`, `--format`; writes parquet to `data/frozen/<batch_id>/`; provenance records run_id, config_hash, date window, feed list, record counts

### Conversion Layer

Five skills; deterministic-first; only three LLM-heavy:

| Skill | Type | Purpose |
|---|---|---|
| `blob_discovery` | LLM (strong model) | Profile sampled blobs → coverage report |
| `entity_extraction` | LLM (strong model) | Extract industry/company/geo/tool/tactic → schema |
| `relationship_parse` | Deterministic + light LLM | GTI campaign timelines + Mandiant actor tables → SROs |
| `tag_normalise` | Deterministic + small LLM fallback | Canonicalise dialects; exclude workflow tags |
| `narrative` | LLM (mid model) | Faithful plain-language reasoning from Finding |

Tiers: `OBSERVED` (clean JSON scalars) → `LLM_EXTRACTED` (blobs) → `DERIVED` (computed features).
Every LLM extraction uses schema-constrained structured output bound to Pydantic models.
Failures → `quarantine.py` (bucketed + counted), never silently dropped.

### Schema

Pydantic v2 `PTEEntity` with all fields from build plan §11. Every field carries one tier (enforced by `tiers.py`). Every record carries `Provenance` (run_id, config_hash, endpoint, tier, skill_version).

Industry and company are first-class fields. STIX IDs preserved verbatim. SROs carry attribution scope + extraction confidence. Do not synthesise SROs from empty structured association arrays.

### Features

Tier-aware parquet tables queryable via DuckDB. Sibling metadata table records column tiers. Each prediction task declares `accepted_tiers` — columns outside accepted set excluded, not silently used.

Special handling:
- `retina_confidence`: MNAR — conditioned on feed + missingness flag; never blind-imputed
- `expiration_ts`: feed-segmented (10-yr placeholder feeds vs realistic horizons)
- Count-cap correction: Snapshot/`full_count` true counts used for any window the live cap would distort
- Time features: source→TS ingestion lag, indicator age, registration age, recency buckets

### Prediction Engine

`Task` ABC: `fit / predict / explain / evaluate`; declares `accepted_tiers`, `baselines`, `metric`, `horizon`, `aql_port_idiom`.

AQL-family algorithms only (scikit-learn / statsmodels):
`IsolationForest`, `RandomForest`, `LogisticRegression`, `LinearRegression`, `DecisionTreeRegressor`, `DBSCAN`, `KMeans`, `ARIMA`. Anything outside requires written **ENGINEERING REVIEW** justification.

| Task | Algorithm | Metric | Baseline |
|---|---|---|---|
| T1 Vuln Exploitation | LogisticRegression / RandomForest | PR-AUC + **lift over EPSS** | EPSS-only + frequency |
| T2 Tool/Tactic Trend | ARIMA / LinearRegression | directional acc, MAE | previous-period |
| T2-Industry (headline) | RandomForest / LogisticRegression | top-k accuracy | sector-frequency |
| T3 Company | ranking; conditional on coverage | per coverage | "not supported + why" if sparse |
| Targeting uptick | ARIMA | MAE | previous-period |

### Evaluate

Time-based train/test; rolling-window; backtest. Never random-split temporal data. Baselines: chance, frequency/most-common, previous-period persistence. Calibration: isotonic regression + ECE. A task is displayed only if it beats its strongest baseline on the pre-registered metric over the time split.

### Explain + API + Web

- `contributions.py`: feature importance / SHAP-style per Finding
- `narrative.py`: Skill 5 — faithful narrative; rejects any claim absent from structured Finding
- FastAPI routes: `forecast`, `trends`, `evidence`, `devpanel`
- Unsupported queries (sparse company coverage) return explicit "not supported + why", never a fabrication

---

## 6. React UI — Forecast Screen

The UI is **algorithm-aware**. Each Finding response includes a `viz_type` field derived from the algorithm used. The primary model output graph switches on `viz_type`:

| `viz_type` | Primary graph |
|---|---|
| `timeseries` (ARIMA / LinearRegression) | Historical trend + forecast window + confidence band (widening into horizon) |
| `classification` (RandomForest / LogisticRegression / DecisionTreeRegressor) | Predicted probability distribution + feature importance bar chart |
| `anomaly` (IsolationForest / DensityFunction) | Anomaly score distribution with threshold line |
| `cluster` (DBSCAN / KMeans) | 2D cluster scatter plot (PCA projection if >2 features) |

**Always shown regardless of algorithm:**
- Ranked forecast list with calibrated confidence scores
- Plain-language reasoning narrative (Skill 5, faithfulness-checked)
- Feature-contribution horizontal bar chart (top N drivers)
- Calibration / reliability curve
- Evidence trail with clickable source IDs + extraction confidence + tier labels
- Honesty layer: hover tooltips showing reliability basis, coverage %, missing data, what was excluded

**Industry × tool co-occurrence heatmap** — shown for T2-Industry task.

**Dev/config panel:**
- Date window picker + feed selector → triggers re-batch
- Cost estimate before run, actuals after
- Coverage report viewer (per-dimension presence rates + quarantine counts)
- Batch selector (switch between existing frozen corpora)

All graphs via Recharts.

---

## 7. Data Flow and Tier Enforcement

Every record moving between stages carries `tier` and `validation_status`. The feature store's sibling metadata table records the tier of every column. Tasks declare `accepted_tiers` — features outside the accepted set are excluded, not silently used. This means:

- T1 (OBSERVED CVSS/EPSS) runs even if conversion layer quality is poor
- T2-Industry degrades gracefully when extraction coverage is thin, and reports exactly why
- T3 company returns "not supported + why" rather than a low-confidence fabrication

---

## 8. Error Handling

Typed exceptions in `common/errors.py`:

| Exception | Behaviour |
|---|---|
| `AuthError` | Fail fast: "run `aws sso login --profile staging`" |
| `RateLimitError` | Exponential backoff + retry |
| `SnapshotError` | Re-request snapshot (expired URL or `errors` status) |
| `CursorDriftError` | Log + resume from last valid cursor |
| `ParseError` | Quarantine + flag template as drifted |
| `ValidationError` | Quarantine + count; never silently dropped |
| `LLMError` | Retry once then quarantine |

Stages checkpoint progress — a failed mid-run resumes rather than restarts.
No exception swallowed silently anywhere in the pipeline.

---

## 9. Testing Strategy

`pytest` throughout. Unit tests per module. Integration tests use **recorded fixtures only** — no live ThreatStream or LLM calls in CI.

Golden fixtures:
- `eventostotales.com` — CrowdStrike mal_domain
- `210.16.168.11` — Threatfox C2, retina_confidence populated, detail2/status conflict
- `gtjzsj.com` — GTI false-positive with `bifocals_deactivated_on` in detail2
- TEMP.Hermit actor HTML — Mandiant actor with full STIX graph in description
- GTI campaign timeline — dated events with raw IOCs + per-event TTPs
- `CVE-2026-48522` — vulnerability with CVSS + EPSS
- Two EDR AQL scripts — OCSF Detection Finding shape reference

Key test cases:
- **TC-003**: read-only guard — no PATCH/PUT/DELETE paths callable
- **TC-005**: every LLM extraction failure quarantined + counted
- **TC-006**: every field carries exactly one tier
- **TC-008**: T1 beats EPSS-only + frequency on PR-AUC over time split
- **TC-009**: T2-Industry top-k beats sector-frequency on held-out window
- **TC-011**: narrative faithfulness — claim absent from Finding → test failure
- **TC-015**: secrets hygiene — log output scanned for credential-shaped strings

---

## 10. Phase Review Gates

| Gate | Pass condition |
|---|---|
| **P0** scaffold + gateway + ingest | TC-001/002/003/013/014/015 green; live snapshot completes with sha256 verified; `.env` written, `creds.txt` deleted |
| **P1** conversion discovery + Tier-1 | TC-004/005/006/007 green; coverage report emits with per-dimension presence + quarantine counts |
| **P2** entity extraction + Tier-2 parsers | Extraction quarantine rate < 20% on fixture set; STIX IDs well-formed; relationship SROs produced from GTI + Mandiant fixtures |
| **P3** predict + evaluate | T1 lifts over EPSS; T2-Industry beats sector-frequency top-k; calibration reported; all tasks gated behind eval pass |
| **P4** explain + UI | All TC-001..017 green; algorithm-aware graphs render correctly for each viz_type; faithfulness test passes; dev panel re-batch works; honesty tooltips visible |

---

## 11. Open Engineering Questions (carry forward)

| ID | Question |
|---|---|
| OQ-2 | Snapshot cadence / how many historical snapshots exist — affects backtest time slices |
| OQ-3 | Ratify per-task accuracy targets (PoC pass bar) |
| OQ-5 | Does the "Managing Threat Model Associations" endpoint return edges as JSON (read)? Would reduce Tier-2 parsing work |

OQ-1 (model IDs) and OQ-4 (date range / sector) resolved in design.

---

*End of spec. Build approach: Option A (strict build-plan fidelity). Next step: writing-plans skill to produce the implementation plan.*
