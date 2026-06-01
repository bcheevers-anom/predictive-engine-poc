# Predictive Threat Engine — PoC

A batch intelligence pipeline for Anomali ThreatStream that extracts signal from unstructured entity descriptions, builds predictive models using AQL-family algorithms, and serves explainable forecasts through a React/FastAPI demo UI.

> **This is a proof of concept.** Its job is to prove feasibility and de-risk the LLM conversion layer before engineering builds a production version. ThreatStream is accessed **read-only**. Nothing writes back.

---

## What it does

```
ThreatStream (read-only REST + Snapshot)
        │
        ▼
Frozen corpus (Parquet)  ←── sha256-verified, parameterised by date window
        │
        ▼
LLM Conversion Layer
  Pass 1 — Discovery: what signal exists in the blobs? (coverage report)
  Pass 2 — Extraction: industry / company / tool / tactic → structured schema
  + Deduplication: L1 exact (value,type) · L2 alias map · L3 LLM adjudication
        │
        ▼
Tier-aware Feature Store (Parquet)
        │
        ▼
Prediction Engine  (AQL-family algorithms only)
  T1  Vulnerability exploitation risk  (RandomForest · PR-AUC vs EPSS)
  T2  Tool/tactic trends               (ARIMA-equivalent · MAE)
  T2-Industry  Sector targeting forecast (co-occurrence top-k vs sector-freq)
  T3  Company relevance                (conditional on coverage)
        │
        ▼
FastAPI + React/Recharts demo UI
  · Algorithm-aware graphs (classification / timeseries / anomaly / cluster)
  · Feature-contribution bars · Honesty tooltips · Evidence click-through
  · Degraded states: no_model / insufficient_coverage / low_confidence / sparse_evidence
  · Dev panel: re-batch over any date window, see cost estimates
```

---

## Quick-start

### Prerequisites

| Requirement | Version |
|---|---|
| Python | 3.12+ |
| Node.js | 18+ (for the React UI) |
| AWS CLI | configured with SSO profile `staging` in `us-east-1` |
| Git | any recent |

### 1 — Clone and set up Python

```bash
git clone https://github.com/bcheevers-anom/predictive-engine-poc.git
cd predictive-engine-poc

python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/Mac:
source .venv/bin/activate

pip install -e ".[dev]"
```

### 2 — Configure credentials

Create `.env` at the repo root (never committed):

```
TS_API_USER=<your-threatstream-email>
TS_API_KEY=<your-threatstream-api-key>
AWS_PROFILE=staging
AWS_REGION=us-east-1
LLM_BACKEND=bedrock
```

> **Anthropic fallback:** add `ANTHROPIC_API_KEY=<key>` and set `LLM_BACKEND=anthropic` if Bedrock is unavailable.

### 3 — Log in to AWS Bedrock

```bash
# Windows:
login_bedrock.bat
# Linux/Mac:
./login_bedrock.sh
```

This runs `aws sso login --profile staging`. If you see `No AWS session — run aws sso login --profile staging` at any point, re-run this.

### 4 — Run the test suite

```bash
pytest tests/ -v
```

Expected: **52 tests pass** (all against recorded fixtures and mocked LLM/HTTP — no live calls).

### 5 — Set up the React UI

```bash
cd web
npm install
cd ..
```

---

## Running the full pipeline

> **Cost note:** the LLM extraction pass (Pass 2) calls Claude Opus 4.8 for entity extraction and Claude Haiku for tag normalisation. On a 1-month corpus the cost depends on entity count and description length. Run `pte convert --discover` first to see the coverage report before committing to a full extraction run. The dev panel shows a cost estimate before executing.

### Step-by-step (example: 1 month, 3w train / 1w eval)

```bash
# 1. Ingest — pull a frozen snapshot corpus
pte ingest --from 2026-05-01 --to 2026-06-01

# The command prints the batch_id on completion, e.g.:
# Batch complete: a1b2c3d4-f5e6g7h8
# Use that ID in every subsequent command.
export BATCH=<your-batch-id>

# 2. Discovery pass — understand what signal exists in the blobs
#    Writes: data/coverage/<batch>/discovery_*.json
pte convert --discover --batch-id $BATCH

# 3. Extraction pass — LLM extraction into the schema
#    Writes: data/schema/<batch>/extracted_entities.json
#            data/schema/<batch>/quarantine.json
pte convert --extract --batch-id $BATCH

# 4. Build feature store
#    Writes: data/features/<batch>/vulnerability_features.parquet
#            data/features/<batch>/industry_tool_cooccur.parquet
pte features build --batch-id $BATCH

# 5. Train and evaluate models
#    T1: vulnerability exploitation (3w train, 1w holdout)
pte train t1 --batch-id $BATCH
pte evaluate t1 --batch-id $BATCH

#    T2-Industry: sector threat forecast (3w train, 1w holdout)
pte train t2-industry --batch-id $BATCH
pte evaluate t2-industry --batch-id $BATCH

# 6. Start the API server
uvicorn api.main:app --reload

# 7. (new terminal) Start the React dev server
cd web && npm run dev
# Open http://localhost:5173
```

The UI will prompt you to select a batch in the Dev Panel. Pick the batch ID from step 1 and click **Get Forecast**.

### Adjusting the train/eval split

The default holdout is 30 days (set in `config/default.yaml` → `eval.holdout_period`). For a 3w-train / 1w-eval split on a 1-month corpus, the default is already correct — the last 7 days are held out.

To change it:

```yaml
# config/default.yaml
eval:
  holdout_period: 7d   # 1 week held out
```

---

## Configuration reference

All tuneable values live in `config/`. Edit before running; values are hashed into `provenance.config_hash` for reproducibility.

| File | Controls |
|---|---|
| `config/default.yaml` | ThreatStream endpoint, LLM concurrency + rate limits, dedup thresholds, holdout period, UI confidence floors |
| `config/feeds.yaml` | Per-feed quirks (tag dialects, which feeds have campaign timelines) |
| `config/models.yaml` | Task → model mapping per backend (Bedrock model IDs) |
| `config/pricing.yaml` | $/1M tokens per model — verify at build time against current AWS/Anthropic prices |
| `config/tasks.yaml` | Predictive task definitions: algorithm, AQL port idiom, metric, baselines, accepted tiers |

### Key knobs

```yaml
# config/default.yaml

llm:
  max_concurrency: 8        # worker pool size — raise after sizing calibration
  bedrock:
    tpm_limit: 100000       # tokens/min — check your Bedrock quota

eval:
  holdout_period: 7d        # hold-out tail for time-based backtest

ui:
  min_coverage: 0.10        # below this → "insufficient coverage" state
  min_confidence: 0.40      # below this → "low confidence" banner
```

---

## Data tiers

Every field in the schema carries one of these tiers. The system enforces them at every boundary.

| Tier | Meaning |
|---|---|
| `OBSERVED` | Directly from ThreatStream structured fields — treat as ground truth |
| `DERIVED` | Computed deterministically from OBSERVED (counts, timestamps, tags after normalisation) |
| `LLM_EXTRACTED` | Extracted by Claude from unstructured HTML/text — never treated as OBSERVED |
| `EXTERNAL` | From a reference source outside ThreatStream (e.g. MITRE ATT&CK) |
| `UNVALIDATED` | Not yet classified |

T1 (vulnerability) uses only `OBSERVED`/`DERIVED`. T2-Industry and T3 accept `LLM_EXTRACTED` because they depend on the conversion layer. Feature store reads are gated by each task's `accepted_tiers`.

---

## Project layout

```
pte/
├── config/              YAML configuration (endpoint, models, pricing, tasks)
├── src/pte/
│   ├── gateway/         ThreatStream REST client · Snapshot · LLM client · cost · rate limiter
│   ├── ingest/          Frozen batch runner · raw store
│   ├── schema/          Pydantic models (PTEEntity, SRO, Finding) · tier policy
│   ├── dedup/           L1 exact · L2 alias map · L3 LLM adjudication · merge
│   ├── convert/         Discovery pass · extraction · Tier-1 clean · Tier-2 parsers
│   ├── skills/          SKILL.md definitions for 6 LLM skills + prompts/
│   ├── features/        Tier-aware parquet feature store · builder
│   ├── predict/         Task ABC · T1/T2/T2-Industry/T3/Trends · baselines
│   ├── evaluate/        Time splits · PR-AUC/top-k/ECE metrics · report writer
│   └── explain/         Feature contributions · faithful narrative (TC-011)
├── api/                 FastAPI routes (forecast / trends / evidence / devpanel)
├── web/                 React + Vite + Recharts frontend
├── prompts/             Versioned LLM prompt text referenced by skills
├── tests/               52 pytest tests + golden fixtures (no live calls)
└── data/                (gitignored) raw/ snapshots/ frozen/ features/ models/
```

---

## What the tests cover (and what they don't)

The 52-test suite covers:

- Gateway: rate limiter, worker pool, SHA-256 verification, read-only guard, cost tracker
- Schema: PTEEntity/SRO/Finding construction, tier policy enforcement
- Dedup: L1 exact keying, L2 alias resolution (APT29 aliases), L3 confidence routing
- Convert: refang, tag normalisation (workflow tag exclusion), quarantine, confidence, Tier-1 cleaner, discovery pass, entity extraction, GTI/Mandiant Tier-2 parsers
- Features: parquet write/read, tier filtering
- Prediction: baselines, time splits, T1 PR-AUC vs EPSS, T2-Industry top-k
- Evaluate: PR-AUC, top-k accuracy, ECE
- Explain: feature contributions, narrative faithfulness retry
- API: forecast endpoint status codes

**They do not cover:**
- Live ThreatStream API calls (all HTTP is mocked)
- Live Bedrock/Anthropic LLM calls (all LLM returns are mocked)
- End-to-end pipeline on real data
- UI rendering in a browser

The P0–P4 review gates in `docs/superpowers/plans/` define the live acceptance criteria that need to pass before this is considered PoC-complete.

---

## Secrets and data hygiene

- **Never commit `.env`** — it's gitignored. The API key and AWS profile live there only.
- **`data/` is gitignored** — the frozen corpus, extracted schema, features, and models all write to local disk only.
- **No pre-signed URLs are ever logged** — the gateway filters them from structured logs.
- **Full-disk encryption** should be enabled on the host (BitLocker on Windows, FileVault on Mac) since the corpus may contain TLP-restricted intelligence.

---

## Troubleshooting

**`No AWS session — run aws sso login --profile staging`**
Run `login_bedrock.bat` (Windows) or `./login_bedrock.sh` (Linux/Mac) and try again. Sessions expire every 8 hours.

**`ModuleNotFoundError: No module named 'pte'`**
Make sure you installed in editable mode: `pip install -e ".[dev]"` with the venv active.

**Snapshot times out or returns errors**
The Snapshot API can take 10–30 minutes for large corpora. The poller waits up to 1 hour by default. If it errors, check the ThreatStream org quota (max 3 concurrent snapshot downloads per org).

**Cost looks high in the dev panel**
The discovery pass (Pass 1) uses Claude Opus 4.8 to profile blobs. Consider reducing the sample size or running discovery on a subset of feeds first. The LLM extraction pass is the expensive one — run discovery first, check coverage, then decide whether to proceed.

**`Calibration ECE: not available` in the UI**
The model hasn't been evaluated yet for that batch. Run `pte evaluate t2-industry --batch-id <id>`.

**`This forecast hasn't been generated for the current batch yet`**
Run the full pipeline (steps 5–6 above) for the selected batch ID before querying the UI.

---

## Open questions before production

| ID | Question |
|---|---|
| OQ-2 | How many historical snapshots exist? How far back can the time series go? |
| OQ-3 | Agreed pass bar for T1 (PR-AUC lift) and T2-Industry (top-k accuracy)? |
| OQ-5 | Does the ThreatStream Associations endpoint return edges as JSON (read-only)? Would reduce Tier-2 parsing scope. |
| OQ-7 | Are Amazon Titan Text Embeddings enabled on the staging Bedrock account? (Used for L3 dedup blocking; falls back to local sentence-transformer if not.) |

---

## Non-negotiables

These constraints are enforced in code, not just convention:

1. **ThreatStream is read-only.** The client exposes no write methods (TC-003).
2. **`LLM_EXTRACTED` is never treated as `OBSERVED`.** `TierPolicy` is checked at every feature store read.
3. **The capped live count (10k) is never used as a true count.** Only Snapshot `total_count` or `full_count=1` REST calls.
4. **Every LLM extraction is schema-constrained.** Validation failures go to quarantine, never silently dropped.
5. **Prediction uses AQL-family algorithms only.** Every task records its `aql_port_idiom` for the engineering port.
6. **Narrative faithfulness is checked.** The narrative generator retries once if `faithfulness_checked=False` (TC-011).
7. **Dedup is a correctness requirement.** All downstream counts use canonical records / `distinct_event_count`, not raw source counts.
