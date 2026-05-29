# Claude Code Software Requirements and Implementation Instructions
# Predictive Threat Engine for Anomali ThreatStream

| Field | Value |
|---|---|
| **Companion to** | PRD: Predictive Threat Engine for Anomali ThreatStream v0.2 (docx) |
| **Audience** | Claude Code (build agent) + engineers |
| **Status** | Draft build plan — proof of concept |
| **Date** | 29 May 2026 |
| **Grounding** | Stage-1 Data Schema & Access Reference; AQL Help JSON; two working AQL ML scripts (EDR Cross-Host Spread, train + score); Observability PRD (structure benchmark) |

Label vocabulary: **ASSUMPTION**, **RISK**, **NEEDS CLARIFICATION**, **MVP**, **FUTURE PHASE**, **ENGINEERING REVIEW**, **PRODUCT DECISION**, **DATA LIMITATION**.

> **This is a proof of concept.** Engineering will later build a refined, ThreatStream-integrated system. The PoC's job is to prove feasibility and de-risk the hard parts (chiefly: can the conversion layer mine industry/company/tool/tactic signal out of the unstructured blobs at usable quality?). Build for clarity and reproducibility, not production scale.

---

## 1. Implementation Goal

Build a batch pipeline that (1) reads ThreatStream **read-only** via REST + Snapshot into a **frozen corpus**, (2) runs an **LLM Conversion Layer** that first **discovers** what industry/company/tool/tactic signal exists in the unstructured blobs (a coverage report) and then **extracts** it into a normalised, reliability-tiered, STIX-inspired schema, (3) runs a **Python prediction engine** over that schema for a defined set of forecasting tasks with a time-respecting evaluation harness, and (4) serves explainable, evidence-rich forecasts through a **React/FastAPI demo UI**.

**Non-negotiables for Claude Code:**
- ThreatStream is **read-only**. Never issue a write.
- Never treat `LLM_EXTRACTED` data as equal to `OBSERVED` data; every field carries a tier + extraction confidence.
- Never present an inferred indicator-to-entity edge as a deterministic join (none exists).
- Never use the live-search capped count (10,000 / approximate) as a true count.
- Prediction runs in **Python**, constrained to **AQL's algorithm families**; anything outside needs written justification (**ENGINEERING REVIEW**).
- Every LLM extraction returns **schema-constrained structured output**; validation failures are **quarantined and counted**, never silently dropped.
- Explainability is first-class, for a layperson and a technical user; narratives must be faithful (no claim absent from the structured object).

---

## 2. Assumed Inputs and Constraints

- **Access:** REST API only for ingestion (`/api/v2/intelligence/`, `/api/v1/threat_model_search/`, single-object GETs) + Snapshot bulk. Auth header `Authorization: apikey <email>:<api_key>`. **AQL search (`tsquery`/`metasearch`) is unavailable** — confirmed in Stage-1. We may query the API freely within reasonable rate limits. *(ASSUMPTION A-1.)*
- **AQL ML** works only as single linear pipes over already-indexed OCSF data (see the two EDR scripts), with no orchestration/validation. So it is **not** the PoC's prediction runtime; it is the **porting target** for engineering.
- **Models:** Claude via **AWS Bedrock**, auth via **AWS SSO** (profile `staging`, region `us-east-1`, both config-overridable). **Anthropic API-key fallback** behind one switch. Tiered models per task. **No SuperAPI** — the brief's reference is treated simply as "we may call the ThreatStream API freely"; there is no separate component.
- **Stack (ASSUMPTION, ENGINEERING REVIEW):** Python 3.12; `httpx` (async REST), `boto3` (Bedrock), `anthropic` (fallback), `pydantic` v2 (schemas + validation), `duckdb`/`parquet` (frozen store + feature store), `scikit-learn` + `statsmodels` (the AQL-equivalent algorithms), `pytest`; **FastAPI** backend, **React + Vite + Recharts** frontend.

---

## 3. Proposed Repository Structure

```
pte/
├── README.md
├── pyproject.toml
├── login_bedrock.bat / login_bedrock.sh   # aws sso login --profile staging
├── config/
│   ├── default.yaml          # endpoints, rate limits, horizons, tier policy, seeds
│   ├── feeds.yaml            # per-feed quirks (retina, expiration, tag dialects)
│   ├── models.yaml           # task -> model map, per backend (bedrock | anthropic)
│   ├── pricing.yaml          # public $/token per model per backend (verify at build)
│   └── tasks.yaml            # predictive task defs, metrics, baselines, gates
├── src/pte/
│   ├── gateway/
│   │   ├── threatstream.py   # read-only REST client (cursor + single-object)
│   │   ├── snapshot.py       # async bulk export + sha256 verify
│   │   ├── rate_limit.py
│   │   ├── llm_client.py     # ONE interface; bedrock|anthropic backends
│   │   └── cost.py           # token counting + pricing -> per-batch estimate
│   ├── ingest/
│   │   ├── frozen_batch.py   # pull -> frozen parquet corpus (parameterised)
│   │   └── raw_store.py
│   ├── convert/              # LLM CONVERSION LAYER
│   │   ├── pipeline.py       # orchestrates discovery -> extraction, tiered
│   │   ├── discovery.py      # PASS 1: profile blobs -> coverage report
│   │   ├── extraction.py     # PASS 2: blobs -> schema (schema-constrained)
│   │   ├── tier1_clean.py    # deterministic JSON -> schema
│   │   ├── tier2_parsers/    # per-feed/per-type HTML parser registry
│   │   │   ├── registry.py
│   │   │   ├── gti_campaign_timeline.py
│   │   │   └── mandiant_actor_assoc.py
│   │   ├── normalize_tags.py # dialects + workflow-tag exclusion
│   │   ├── refang.py
│   │   ├── quarantine.py     # failed-validation bucket + counts
│   │   └── confidence.py     # extraction confidence
│   ├── skills/               # Claude SKILL.md packages (see §10)
│   │   ├── blob_discovery/SKILL.md
│   │   ├── entity_extraction/SKILL.md
│   │   ├── relationship_parse/SKILL.md
│   │   ├── tag_normalise/SKILL.md
│   │   └── narrative/SKILL.md
│   ├── schema/
│   │   ├── models.py         # pydantic: PTEEntity, SRO, Finding, tiers, provenance
│   │   └── tiers.py
│   ├── features/
│   │   ├── build.py          # tier-aware feature tables
│   │   └── store.py
│   ├── predict/
│   │   ├── base.py           # Task ABC: fit/predict/explain/evaluate
│   │   ├── t1_vuln_exploit.py
│   │   ├── t2_tool_tactic.py
│   │   ├── t2_industry.py    # headline
│   │   ├── t3_company.py     # conditional on coverage
│   │   ├── trends.py
│   │   └── baselines.py
│   ├── evaluate/
│   │   ├── splits.py         # time-based / rolling-window
│   │   ├── metrics.py        # PR-AUC, top-k, F1, MAE/MAPE, calibration
│   │   └── report.py
│   ├── explain/
│   │   ├── contributions.py  # feature importance / SHAP-style
│   │   └── narrative.py      # faithful narrative (Skill: narrative)
│   ├── common/{provenance.py, logging.py, errors.py}
│   └── cli.py
├── api/                      # FastAPI
│   ├── main.py
│   └── routes/{forecast.py, trends.py, devpanel.py, evidence.py}
├── web/                      # React + Vite + Recharts
│   └── src/...               # one forecast screen + dev/config panel
├── tests/                    # TC-001..017
├── data/                     # gitignored: raw/ snapshots/ frozen/ features/ models/ coverage/
└── prompts/                  # versioned prompt text referenced by skills
```

---

## 4. System Architecture

One-directional batch pipeline; each stage writes a durable artifact so stages re-run independently.

```
[1 Gateway: read-only ThreatStream + Bedrock/Anthropic LLM + cost]
        v
[2 Ingest -> FROZEN CORPUS (parquet)]            (parameterised: date window / feeds)
        v
[3 Conversion Layer]
        Pass 1 DISCOVERY  -> coverage report (what's in the blobs)
        Pass 2 EXTRACTION -> normalised schema (tiered; schema-constrained; quarantine)
        v
[4 Normalised schema store]  ->  [5 Feature store (tier-aware)]
        v
[6 Python prediction engine]  (AQL-family algorithms only)
        v
[7 FastAPI]  ->  [8 React explainable demo UI + dev/config panel]
        ||  provenance + audit log + cost thread through every stage  ||
```

Principles: deterministic-before-LLM; frozen + reproducible + seeded; every artifact provenance-tagged; tier-aware everywhere; LLM output always schema-validated then quarantined-on-failure; read-only upstream.

---

## 5. Core Modules

| Module | Responsibility | MVP/Phase |
|---|---|---|
| Gateway | One choke point: read-only ThreatStream REST + Snapshot; LLM (Bedrock SSO / Anthropic key) behind one interface; rate-limit, retry, audit, cost estimate. | MVP |
| Ingest | Pull to a frozen, parameterised parquet corpus. | MVP |
| Conversion | Discovery (coverage report) + Extraction (schema), tiered, schema-constrained, quarantine. | MVP |
| Skills | 5 Claude skills; 3 LLM-heavy (discovery, extraction, narrative), 2 mostly-deterministic (relationship parse, tag normalise). | MVP |
| Schema | Pydantic entities, SROs, Finding, tiers, provenance. | MVP |
| Features | Tier-aware feature tables. | MVP |
| Predict | Task ABC + T1, T2, T2-Industry, T3(conditional) + trends + baselines. | MVP |
| Evaluate | Time splits, metrics, calibration, baselines, report + gates. | MVP |
| Explain | Feature contributions + faithful narrative. | MVP |
| API + Web | FastAPI + React one-screen demo + dev/config panel (re-batch, cost). | MVP |

---

## 6. ThreatStream Data Access Layer

Read-only. Implement in `gateway/`.

- **Observables:** `GET /api/v2/intelligence/`, cursor pagination via `meta.next` (`search_after=<sort_ts>,<id>`).
- **Entities:** `GET /api/v1/threat_model_search/?model_type=<t>` for lists; **always fetch full single-object** `GET /api/v1/<type>/<id>/` for the `description` body (lists omit it). Prefer `tags_v2`.
- **True counts:** Snapshot or `full_count=1`; never trust the capped live count (TC-002).
- **Snapshot bulk:** `POST /api/v1/snapshot/` -> poll `GET /api/v1/snapshot/<id>/` to `completed`; download S3 chunks; verify `sha256sum`; download inside the pre-signed-URL TTL; use `json_v2` or `stix`; chunk via `chunk_ioc_count` (<=250k) or `chunk_size` (<=200MB); <=3 concurrent/org.
- **Failure modes:** expired URL; snapshot `errors`; cursor drift; 429; single-object 404; `/associations/` returns 400/404 — do **not** treat it as a join.

**Read-only guard:** the client exposes only GET / POST-snapshot; no PATCH/PUT/DELETE/tag-write paths are implemented (TC-003).

---

## 7. AQL Strategy (porting target, not runtime)

AQL search is unavailable, and AQL ML runs only as single pipes over indexed OCSF data — so we do **not** run prediction in ThreatStream. Instead:

- The Python engine is **constrained to the algorithm families AQL exposes**: `IsolationForest`, `RandomForest`, `LogisticRegression`, `LinearRegression`, `DecisionTreeRegressor`, `DBSCAN`, `KMeans`, `ARIMA`, `DensityFunction`, plus `predict`/`score`/`fit` semantics. These are scikit-learn / statsmodels under the hood, so Python reproduces them faithfully.
- Each task records the **AQL idiom it ports to** (`fit <Algo> ... into '<model>'` then `apply <model>`), using the two EDR scripts as the reference pattern (field extraction -> ratio/scale transforms -> `fit ... into` -> `apply`). This is what lets engineering re-implement the PoC natively.
- Anything outside the AQL family (e.g. gradient boosting, survival models) requires a written justification block flagged **ENGINEERING REVIEW** so the divergence is explicit.

---

## 8. LLM / Model Integration Layer

`gateway/llm_client.py` exposes one interface; `LLM_BACKEND` selects `bedrock` (default) or `anthropic`.

- **Bedrock:** boto3 `bedrock-runtime`, credentials from the AWS SSO session/profile chain (profile `staging`, region `us-east-1`, config-overridable). If no valid session, fail fast with: "No AWS session — run `aws sso login --profile staging`."
- **Anthropic fallback:** `anthropic` SDK with key from env/secrets.
- **Tiered models** (`config/models.yaml`, per backend, since Bedrock model IDs ≠ Anthropic model strings):
  - strong model -> discovery pass + industry/company extraction (semantic judgement)
  - fast/cheap model -> tag normalisation + templated cleanup (high volume, low ambiguity)
  - mid model -> narrative generation
- **Structured output:** all extraction calls use tool-use / JSON-schema-constrained output bound to a Pydantic model.
- **Cost (`gateway/cost.py`):** count input/output tokens per call, multiply by `config/pricing.yaml`, roll up per batch; surface an **estimate before** a large run and **actuals after**, backend-aware (TC-014). **ENGINEERING REVIEW:** verify public prices and enabled Bedrock model IDs at build (OQ-1).

---

## 9. LLM Conversion Layer

Two passes, tiered, over the frozen corpus. One-off but **parameterised** (re-runnable over a chosen date window / feed set from the dev panel).

### Pass 1 — Discovery (coverage report)
- **Purpose:** answer "we don't know what's in the blobs." Sample `description` HTML + tipreport bodies across feeds/entity types; have the LLM surface and **count** industry, company/`identity--`, tool, tactic, technique, and date signal.
- **Output:** `data/coverage/<batch>.json` — per feed/type: presence rate and mean extraction confidence for each dimension, plus quarantine counts. This **gates** which dimensions/sectors the prediction layer will forecast (and is a PoC deliverable in its own right).

### Pass 2 — Extraction
- **Tier 1 (deterministic, no LLM):** observable scalars; vulnerability CVSS/EPSS; malware `capabilities[]`/`malware_types[]`/`is_family`; envelope fields. Malware HTML duplicates JSON — use JSON.
- **Tier 2 (parser registry + light LLM cleanup):** GTI campaign timelines (dated events, refanged IOCs, per-event TTPs) and Mandiant actor associations (STIX-ID edges + attribution scope). Start with these two templates.
- **Tier 3 (LLM, schema-constrained):** industry/company/geo/tool/tactic extraction from free-text and inconsistent blobs — the new flagship extraction. Tipreport deep extraction is **FUTURE PHASE** beyond a starter.

Cross-cutting: `normalize_tags` (canonicalise dialects; exclude workflow tags), `refang` (before any matching), `confidence` (extraction confidence ≠ intel confidence), `quarantine` (validation failures bucketed + counted), `provenance` (source feed/endpoint/tier/skill version/run_id), evidence-trail preservation (source IDs for click-through).

---

## 10. Claude Skills and Agent Design

**Five skills; deterministic-first; only three LLM-heavy.** (Rationale: malware HTML duplicates clean JSON; actor/campaign HTML follows stable templates; only free-text industry/company/tool/tactic and narrative truly need an LLM. A skill-per-entity zoo adds cost and nondeterminism for no gain.)

For each: Purpose / Inputs / Outputs / Responsibilities / Validation / Failure modes / Confidence / OCSF-STIX / Downstream / Phase.

### Skill 1 — `blob_discovery` (LLM-heavy) — MVP
- **Purpose:** profile sampled blobs; produce the coverage report. **Outputs:** per-dimension presence + confidence counts. **Validation:** counts reconcile with sample size. **Failure:** unparseable sample -> logged, excluded, counted. **Downstream:** gates every extraction-dependent task.

### Skill 2 — `entity_extraction` (LLM-heavy) — MVP
- **Purpose:** extract industry/company/geo/tool/tactic/technique into the schema. **Outputs:** schema-constrained objects, tier `LLM_EXTRACTED` + extraction confidence + source IDs. **Validation:** Pydantic; STIX IDs well-formed; refanged IOCs regex-valid. **Failure:** quarantine + count. **STIX/OCSF:** identity/location/attack-pattern refs; Finding evidence. **Downstream:** T2-Industry, T3, trends.

### Skill 3 — `relationship_parse` (deterministic + light LLM) — MVP
- **Purpose:** parse GTI campaign timelines and Mandiant actor tables into structured events/SROs. **Validation:** dates ISO; TTPs match `T\d{4}(\.\d{3})?`; scope in enum. **Failure:** template drift -> quarantine + flag for a new template. **Downstream:** T2, trends; Phase-2 graph.

### Skill 4 — `tag_normalise` (deterministic + small LLM fallback) — MVP
- **Purpose:** canonicalise family/tool/tactic tag dialects; exclude workflow tags (`Ilamona_send_to_*`, `PIR*`). **Failure:** unknown -> "unmapped" bucket, never dropped. **Downstream:** all extracted-dimension features.

### Skill 5 — `narrative` (LLM, mid model) — MVP
- **Purpose:** render a plain-language reasoning message from a Finding. **Validation:** faithfulness — reject any claim absent from the structured object (TC-011). **Downstream:** explainability UI.

---

## 11. Normalised Predictive Schema

Pydantic v2. Every field carries a `tier`; each record carries `provenance`. Industry and company are **first-class**.

```yaml
PTEEntity:
  entity_id: str               # OBSERVED
  stix_id: str|null            # OBSERVED (preserve verbatim, incl. identity-- for company)
  entity_type: enum            # OBSERVED
  source_feed: str             # OBSERVED
  source_confidence: int|null  # OBSERVED
  observed_ts/created_ts/modified_ts: dt|null  # OBSERVED
  first_seen/last_seen: dt|null               # OBSERVED / DERIVED
  actor/campaign/malware/tool: ref|null        # OBSERVED(entity) / LLM_EXTRACTED(edge)
  tactic/technique: str|null                   # OBSERVED(attackpattern) / LLM_EXTRACTED(HTML) / EXTERNAL(ATT&CK)
  observable: obj|null         # OBSERVED
  indicator_type: str|null     # OBSERVED (itype)
  industry: list|null          # OBSERVED(entity, sparse) / LLM_EXTRACTED(blobs)   <-- first-class
  company: ref|null            # LLM_EXTRACTED(blobs) / UNVALIDATED                 <-- first-class, conditional
  geography: obj|null          # OBSERVED(IP) / LLM_EXTRACTED(entity)
  severity/confidence: enum/int|null   # OBSERVED
  tags: list                   # DERIVED (normalised; workflow tags excluded)
  relationships: list[SRO]     # LLM_EXTRACTED (carry match/attribution confidence)
  evidence: list               # DERIVED (source ids, counts, scores) -> explainability trail
  provenance: obj              # DERIVED (endpoint, tier, skill_version, run_id, config_hash)
  llm_extraction_confidence: float|null  # LLM_EXTRACTED
  validation_status: enum      # ok | quarantined | unmapped
  features: obj|null           # DERIVED (predictive features)
```

The authoritative per-field tier map lives in `schema/tiers.py` and is enforced (TC-006).

---

## 12. OCSF Findings Mapping

PTE output = OCSF **Finding**-shaped envelope. The two EDR scripts confirm ThreatStream's OCSF `Detection Finding` shape (`category_name="Findings"`, `class_name="Detection Finding"`, `metadata.product.vendor_name`, `finding_info.*`, `severity_id`, `confidence_id`) and are the native-port idiom.

| OCSF Finding | PTE source |
|---|---|
| title / type_name | task + dimension (e.g. "Sector Threat Forecast — Oil & Gas") |
| severity / confidence | task severity + calibrated confidence |
| time / start/end | forecast window |
| evidence / observables | source IDs, STIX IDs, counts, scores (tier-tagged) |
| finding_info / analytic | task id, model version, baseline, metric, **AQL port idiom** |
| unmapped | free-text/fuzzy content, marked DERIVED / LLM_EXTRACTED |

---

## 13. STIX Mapping

STIX-inspired, not strict. Entity types -> SDOs (threat-actor, campaign, malware, tool, indicator, observed-data, attack-pattern, **identity** [company], location, report). Inferred edges -> SROs with `attribution_scope` + extraction confidence. Preserve source STIX IDs verbatim. Do **not** synthesise SROs from the empty structured association arrays — only from parsed HTML / extracted edges.

---

## 14. Feature Store Design

Parquet in `data/features/`, queried via duckdb. One table per family (`observable_features`, `vulnerability_features`, `industry_tool_cooccur`, `trends_<dim>`). Each column carries a tier in a sibling metadata table; tasks declare accepted tiers (TC-006). Handle MNAR `retina_confidence` (condition on feed + missingness flag; never blind-impute) and feed-segmented `expiration_ts`. Time features: source->TS ingestion lag, indicator age, registration age, recency buckets. Count-cap correction uses Snapshot/`full_count` counts for any window the live cap would distort.

---

## 15. Predictive Task Definitions

Common `Task` ABC: `fit / predict / explain / evaluate`; declares `accepted_tiers`, `baselines`, `metric`, `horizon`, `aql_port_idiom`. Full definitions in PRD §15.3 and `config/tasks.yaml`.

| Task | Question | Basis | Algorithm (AQL family) | Metric / baseline |
|---|---|---|---|---|
| **T1** Vulnerability Exploitation | What/when: CVE exploited within H | Clean EPSS/CVSS/tags | LogisticRegression / RandomForest | PR-AUC, top-k; **lift over EPSS** + frequency |
| **T2** Tool/Tactic Trend+Forecast | Tools/tactics rising; usage over time | Extracted | ARIMA / LinearRegression | directional acc, MAE; previous-period |
| **T2-Industry** (headline) | Who: tools/tactics sector S faces next | Extracted + coverage-gated | RandomForest / LogisticRegression on industry×tool co-occurrence | **top-k**; sector-frequency baseline; coverage reported |
| **T3** Company Relevance | Who: which companies | Extracted | ranking; conditional | per coverage; else "not supported + why" |
| Targeting uptick (support) | Sector likely to see more activity | Extracted series | ARIMA | MAE; previous-period |

Each task: emits calibrated confidence + reliability basis; is gated behind its evaluation pass before display (TC-008/009); T1's success metric is **lift over EPSS** (avoid circularity, R-2).

---

## 16. Evaluation Framework

Time-based train/test; rolling-window; backtest — never random-split temporal data. Baselines always: chance, frequency/most-common, previous-period persistence. Metrics by type: classification -> ROC/PR-AUC, F1, top-k; temporal -> MAE/MAPE; all -> calibration (reliability curve / ECE). A task is shown only if it beats its strongest baseline on the pre-registered metric over the time split, reproducibly. `evaluate/report.py` writes a per-task report (metric, baseline deltas, calibration, sample sizes, **coverage** for extracted tasks) to `data/models/reports/`.

---

## 17. Query and Answer Layer

FastAPI routes wrap the engine. `forecast` (select industry/CVE set/family/window -> task), `trends`, `evidence` (resolve an evidence ID -> source object), `devpanel` (trigger re-batch; return cost estimate/actuals; show coverage report). Unsupported questions (sparsely-covered company) return an explicit "not supported + why" (TC-012), never a fabrication. Free-text routing is **FUTURE PHASE**; MVP is structured selection.

---

## 18. Analyst-/Customer-Facing Output Format

React single screen + dev/config panel. For a selected dimension it renders: the forecast (ranked), the **plain-language reasoning** (Skill 5, faithfulness-checked), the **evidence trail** (clickable source IDs + extraction confidence), the **feature-contribution graph**, the **time-series graph** with forecast window + confidence band, the **industry×tool co-occurrence** graph, and the **honesty layer** via hover tooltips (reliability basis, coverage, what was missing). Layperson and technical legible. Graphs via Recharts.

---

## 19. Confidence and Explainability

Every output: what / when (window) / who (with "not supported" where coverage is thin) / evidence (IDs + provenance) / drivers (feature contributions) / missing data / calibrated confidence + reliability basis / monitor-next (PRD §14). Confidence is calibrated and reported (TC-010). The narrative never exceeds the structured object (TC-011).

---

## 20. Data Quality and Validation

Pydantic validation at every tier boundary; failures -> `validation_status=quarantined`, logged, counted in the coverage report (TC-005), never silently dropped. A `data_quality` scorer tracks per-feed/type extraction success, quarantine rate, retina coverage per feed (G6), detail2/status conflict rate (G7). These metrics **gate** which features/dimensions are used.

---

## 21. Logging, Auditability, and Provenance

Structured JSON logs (`common/logging.py`): every gateway call (timestamp, endpoint, status, run_id — **no secrets, no SSO tokens, no pre-signed URLs**), every extraction (object id, tier, skill version), every model run (version, config_hash, metrics), every batch cost. `common/provenance.py` stamps run_id + version chain on every artifact (TC-015, reproducibility TC-016).

---

## 22. Error Handling

Typed exceptions (`common/errors.py`): `AuthError` (incl. "run SSO login"), `RateLimitError` (backoff+retry), `SnapshotError` (expired URL / errors -> re-request), `CursorDriftError`, `ParseError` (-> quarantine + flag template), `ValidationError` (-> quarantine), `LLMError` (retry then quarantine). Stages checkpoint and resume. No exception swallowed silently.

---

## 23. Security and Secrets Handling

ThreatStream creds, AWS SSO sessions, Bedrock creds, Anthropic key: env / SSO chain / secrets store only; never in code, logs, output, or git (`data/` gitignored). Pre-signed Snapshot URLs are secrets (1h TTL), never persisted. Org-scoped to 2956; ThreatStream read-only. TLP fields preserved; strict output-TLP enforcement is production work, out of PoC scope (PRODUCT DECISION). Secrets-hygiene test (TC-015).

---

## 24. Configuration Management

YAML in `config/`: `default.yaml` (endpoints, rate limits, horizons, tier policy, seeds), `feeds.yaml`, `models.yaml` (task->model per backend), `pricing.yaml`, `tasks.yaml`. Resolved config (with `config_hash`) recorded in provenance (reproducibility TC-016). The dev panel can override date window / feed set for a re-batch (TC-017).

---

## 25. Testing Strategy

`pytest`, mirroring PRD §20 (TC-001..017). Unit tests per module; integration tests for full ingest->convert->feature->predict->explain on **recorded fixtures** (no live ThreatStream/LLM in CI). Golden fixtures from Stage-1 observed samples (`eventostotales.com`; Threatfox `210.16.168.11` with conflicting detail2/status; GTI falsepos `gtjzsj.com`; actor TEMP.Hermit HTML; a GTI campaign timeline; `CVE-2026-48522`) plus the two EDR scripts as the OCSF-shape reference. Evaluation-gate tests (TC-008/009) run on held-out time slices.

---

## 26. Local Development Instructions

1. `python -m venv .venv && source .venv/bin/activate`
2. `pip install -e .` (add `--break-system-packages` in constrained envs)
3. Log in to Bedrock: run `login_bedrock.bat` / `.sh` (`aws sso login --profile staging`). Or set `LLM_BACKEND=anthropic` + `ANTHROPIC_API_KEY`.
4. Set `TS_API_USER` / `TS_API_KEY`.
5. `pte ingest --snapshot --filter 'status="active"' --from 2025-11-01 --to 2026-05-01 --format json_v2`  → frozen corpus
6. `pte convert --discover`  → coverage report;  `pte convert --extract`  → schema
7. `pte features build`
8. `pte train t1 && pte evaluate t1` ; `pte train t2-industry && pte evaluate t2-industry`
9. `uvicorn api.main:app` + `cd web && npm run dev` → open the demo; use the dev panel to re-batch / view cost.
CI runs `pytest` against recorded fixtures only.

---

## 27. Implementation Phases

| Phase | Deliverable |
|---|---|
| P0 scaffold | Repo, config, gateway (read-only TS + Snapshot + LLM Bedrock/Anthropic + cost), logging, schema, frozen-batch ingest. TC-001/002/003/013/014/015. |
| P1 conversion | Discovery pass + coverage report; Tier-1 clean; tag normalise; quarantine. TC-004/005/006/007. |
| P2 extraction | `entity_extraction` (industry/company/tool/tactic); Tier-2 starter parsers. |
| P3 predict+eval | T1, T2, T2-Industry, T3(conditional), trends, baselines, eval harness, calibration. TC-008/009/010. |
| P4 explain+UI | Contributions, faithful narrative, FastAPI, React screen + dev/config panel, graphs, tooltips. TC-011/012/016/017. |
| P5 FUTURE | Tipreport deep extraction; entity resolution; actor/campaign forecasting; AQL native port; production UI. |

---

## 28. Claude Code Task Breakdown

1. Scaffold repo + config (`default/feeds/models/pricing/tasks.yaml`) + login scripts.
2. `gateway`: read-only ThreatStream, snapshot+sha256, `llm_client` (bedrock|anthropic), `cost`, rate-limit, audit.
3. `ingest/frozen_batch` (parameterised) + raw store.
4. `schema/models` + `tiers` + provenance; enforce tier map.
5. `convert/discovery` + coverage report; `tier1_clean`; `normalize_tags`; `refang`; `quarantine`; `confidence`.
6. `skills/*` SKILL.md (5) + versioned prompts.
7. `convert/extraction` (schema-constrained) + `tier2_parsers` (GTI campaign, Mandiant actor).
8. `features/build` (+ MNAR, count-cap) + store.
9. `predict`: base, baselines, t1, t2, t2_industry, t3, trends — each with `aql_port_idiom`.
10. `evaluate`: splits, metrics, calibration, report + gates.
11. `explain`: contributions + narrative; `api` (FastAPI routes); `web` (React screen + dev panel).
12. Tests TC-001..017 + recorded fixtures.
13. (FUTURE) tipreport extraction, entity resolution, AQL native port.

---

## 29. Acceptance Criteria

- AC-1: ThreatStream accessed read-only; no write ever issued (TC-003).
- AC-2: Snapshot verified end-to-end with sha256 + true count (TC-001); capped count never used (TC-002).
- AC-3: Discovery pass emits a coverage report with per-dimension presence + quarantine counts (TC-004).
- AC-4: Every LLM extraction is schema-constrained; failures quarantined + counted (TC-005); every field carries one tier (TC-006).
- AC-5: T1 beats EPSS-only + frequency on PR-AUC over a time split, reproducibly (TC-008).
- AC-6: T2-Industry top-k beats sector-frequency on a held-out window; coverage reported (TC-009); calibration reported (TC-010).
- AC-7: Every output has reasoning + evidence (IDs) + graphs + honesty layer; narrative faithful (TC-011).
- AC-8: Sparsely-covered company query returns "not supported + why" (TC-012).
- AC-9: Bedrock SSO + Anthropic fallback both work behind one interface (TC-013); per-batch cost estimated/recorded (TC-014).
- AC-10: No secrets/SSO tokens/URLs in logs or output (TC-015); reproducible (TC-016); dev-panel re-batch works (TC-017).

---

## 30. Example Input and Output Formats

**Input (campaign description blob, abridged) → `entity_extraction` skill → schema-constrained object:**
```json
{"entity_type":"campaign","stix_id":"campaign--...","industry":["Oil and Gas"],
 "company":[{"name":"<org>","stix_id":"identity--...","tier":"LLM_EXTRACTED","extraction_confidence":0.62}],
 "tool":["Cobalt Strike"],"tactic":["TA0008 Lateral Movement"],"technique":["T1021.002"],
 "evidence":[{"source_id":"campaign--...","ts":"2026-03-...","tier":"LLM_EXTRACTED"}],
 "validation_status":"ok","llm_extraction_confidence":0.66}
```

**Output (T2-Industry, Finding-shaped, abridged):**
```json
{"finding":{"title":"Sector Threat Forecast — Oil & Gas","type_name":"PTE/T2-Industry",
  "severity":"high","confidence":0.68,"time_window":{"start":"2026-06-01","end":"2026-09-01"}},
 "prediction":{"industry":"Oil and Gas","top_tools":["Cobalt Strike","Mimikatz","PsExec"],
  "top_tactics":["Lateral Movement","Credential Access"],"horizon":"next quarter"},
 "evidence":[{"campaign":"campaign--...","tool":"Cobalt Strike","tier":"LLM_EXTRACTED","confidence":0.62}],
 "drivers":["industry×tool co-occurrence last 6m","upward trend in Cobalt Strike use"],
 "coverage":{"industry":"Oil and Gas","extracted_campaigns":9,"confidence_mean":0.6,
   "note":"Retail too sparse to forecast this batch"},
 "missing_data":["company-level signal sparse for this sector"],
 "reliability_basis":"LLM_EXTRACTED (industry/tool) + DERIVED (trend)",
 "calibration":{"method":"isotonic","ece":0.05},
 "baselines":{"sector_frequency_topk":0.41},
 "metric":{"name":"top-3 accuracy","value":0.67},
 "monitor_next":"watch for new Oil & Gas campaigns introducing novel tooling",
 "aql_port_idiom":"... | fit RandomForest ... into 'pte_t2_industry' ; ... | apply pte_t2_industry",
 "provenance":{"run_id":"...","model_version":"t2ind-0.1","config_hash":"..."}}
```

---

## 31. Open Engineering Questions

| ID | Question |
|---|---|
| OQ-1 | Which Claude model IDs are enabled on the staging Bedrock account, and current public prices, for accurate cost estimation. |
| OQ-2 | What snapshot cadence / how many historical snapshots exist, to build time-respecting backtests. |
| OQ-3 | Ratify per-task success metrics/targets (accuracy vs PR-AUC vs top-k; PoC pass bar). |
| OQ-4 | Which feeds + date range for the headline frozen batch; is there a guaranteed demo sector (e.g. Oil & Gas) that must show well? |
| OQ-5 | Can the documented "Managing Threat Model Associations" endpoint return edges as JSON (read)? Would shrink Tier-2 parsing (G12). |

---

## Suggested Prompts / Implementation Instructions for Claude Code

Use these as kickoff prompts, one phase at a time, each grounded in the sections above:

1. *"Scaffold the `pte` repo per §3. Implement `gateway/llm_client.py` with one interface and two backends — `bedrock` (boto3, AWS SSO profile `staging`/`us-east-1`, fail-fast with a 'run aws sso login' message) and `anthropic` (key from env) — selected by `LLM_BACKEND`. Add `gateway/cost.py` reading `config/pricing.yaml`. No secrets in code."*
2. *"Implement the read-only ThreatStream client and Snapshot bulk export per §6, with sha256 verification and the read-only guard (no write verbs). Tests TC-001/002/003 against recorded fixtures."*
3. *"Implement the conversion discovery pass per §9 Pass 1 and the 5 skills per §10. Discovery must emit `data/coverage/<batch>.json`. All extraction calls use schema-constrained structured output bound to the §11 Pydantic models; failures go to `quarantine` and are counted. Tests TC-004/005/006/007."*
4. *"Implement T1 and T2-Industry per §15 using only AQL-family algorithms, each recording its `aql_port_idiom`. Build the evaluation harness per §16 with time-based splits and the named baselines; T1's metric is lift over EPSS. Tests TC-008/009/010."*
5. *"Build the FastAPI backend and React/Recharts demo per §17–§19: one forecast screen (reasoning, evidence trail with clickable IDs, contribution graph, time-series + co-occurrence graphs, honesty tooltips) and a dev/config panel that re-triggers a batch over a chosen date/feed set and shows estimated + actual cost. Narrative must be faithfulness-checked. Tests TC-011/012/016/017."*

---

## 32. Session Design Decisions (29 May 2026)

The following decisions were made during the initial Claude Code design session and are authoritative for the build. They extend or clarify the sections above.

### 32.1 Resolved Open Engineering Questions

| OQ | Resolution |
|---|---|
| OQ-1 | All three cross-region inference profile IDs confirmed enabled on `staging` Bedrock account: `us.anthropic.claude-opus-4-8` (strong), `us.anthropic.claude-sonnet-4-6` (mid), `us.anthropic.claude-haiku-4-5-20251001` (fast). These are the model IDs to use in `config/models.yaml`. Verify public pricing at build time and populate `config/pricing.yaml`. |
| OQ-4 | **Date range:** 2025-01-01 to 2026-05-01. **Feeds:** all available feeds; exclude only feeds that the discovery pass identifies as producing zero usable signal. **Sectors:** all sectors — no single guaranteed demo sector. The discovery pass surfaces which sectors have sufficient coverage to forecast; T2-Industry reports coverage per sector and degrades gracefully for thin ones. |

OQ-2, OQ-3, OQ-5 remain open for engineering confirmation.

### 32.2 Credentials and Secrets Bootstrap (P0)

- **ThreatStream:** `TS_API_USER=bcheevers@ilamona.com`, `TS_API_KEY` is in `creds.txt` at repo root
- **AWS Bedrock:** SSO profile `staging`, region `us-east-1`; login via `login_bedrock.bat` / `login_bedrock.sh`
- **Anthropic:** no `ANTHROPIC_API_KEY` present — Bedrock is the default backend (`LLM_BACKEND=bedrock`)
- **P0 bootstrap sequence (mandatory, before first commit):**
  1. Read credentials from `creds.txt`
  2. Write `.env` with `TS_API_USER`, `TS_API_KEY`, `AWS_PROFILE=staging`, `AWS_REGION=us-east-1`
  3. Delete `creds.txt`
  4. Add `.env`, `creds.txt`, and `data/` to `.gitignore`
  5. Verify no credential-shaped strings appear in any committed file (TC-015)

### 32.3 Build Scope and Review Gates

**Full PoC P0–P4 with a mandatory human review gate after each phase before proceeding.**

| Gate | Trigger | Pass condition |
|---|---|---|
| **P0** | After scaffold + gateway + ingest | TC-001/002/003/013/014/015 green; live Snapshot completes with sha256 verified; `.env` written, `creds.txt` deleted, nothing sensitive in git |
| **P1** | After conversion discovery + Tier-1 | TC-004/005/006/007 green; coverage report emits with per-dimension presence rates + quarantine counts per feed/type |
| **P2** | After entity extraction + Tier-2 parsers | Extraction quarantine rate < 20% on fixture set; STIX IDs well-formed; SROs produced from GTI campaign + Mandiant actor fixtures |
| **P3** | After predict + evaluate | T1 lifts over EPSS on held-out time split; T2-Industry beats sector-frequency top-k on held-out window; calibration curve reported; all tasks gated behind eval pass before display |
| **P4** | After explain + UI | All TC-001..017 green; algorithm-aware graphs render correctly; faithfulness test passes; dev-panel re-batch works end-to-end; honesty tooltips visible |

P5 (tipreport deep extraction, entity resolution, AQL native port, production UI) is explicitly out of PoC scope.

### 32.4 React UI — Algorithm-Aware Graphs (extends §18)

The forecast screen is **algorithm-aware**. Each Finding response includes a `viz_type` field derived from the algorithm recorded in `aql_port_idiom` / model metadata. The primary model output graph switches on `viz_type`. This means if a task's algorithm changes between runs, the UI adapts automatically.

| `viz_type` | Primary graph rendered |
|---|---|
| `timeseries` — ARIMA, LinearRegression | Historical trend line + forecast window + confidence band (band widens into horizon) |
| `classification` — RandomForest, LogisticRegression, DecisionTreeRegressor | Predicted probability distribution + feature importance horizontal bar chart |
| `anomaly` — IsolationForest, DensityFunction | Anomaly score distribution with threshold line |
| `cluster` — DBSCAN, KMeans | 2D cluster scatter plot (PCA projection if > 2 features) |

**Always shown regardless of `viz_type`:**
- Ranked forecast list with calibrated confidence scores
- Plain-language reasoning narrative (Skill 5, faithfulness-checked against structured Finding)
- Feature-contribution horizontal bar chart (top N drivers, SHAP-style)
- Calibration / reliability curve (isotonic, ECE reported)
- Clickable evidence trail (source IDs + extraction confidence + tier labels)
- Honesty layer hover tooltips: reliability basis, coverage %, missing data, what was excluded and why

**Additional graphs for specific tasks:**
- T2-Industry: industry × tool co-occurrence heatmap (always shown alongside primary graph)
- All trend tasks: time-series graph with forecast window + confidence band (shown even when primary graph is classification-type, since trends are computed separately)

All graphs implemented via **Recharts**.

### 32.5 Re-batch Flow (extends §17 and §24)

The frozen corpus is parameterised. Multiple corpora coexist in `data/frozen/`, each tagged with a `batch_id` derived from `run_id` + `config_hash` of the date window and feed list.

**CLI:** `pte ingest --from <date> --to <date> --feeds <list|all>` triggers a new batch.

**Dev panel UI:** date-range picker + feed multi-select → "Run batch" button → shows cost estimate before confirming → triggers ingest → conversion → features → train → evaluate pipeline for the new batch → shows actuals cost on completion.

**Batch selector:** the dev panel also exposes a dropdown to switch between existing frozen corpora without re-ingesting, so analysts can compare forecasts across different time windows.

The full downstream pipeline (convert → features → train → evaluate) re-runs automatically when a new batch is triggered from the dev panel, unless the user explicitly selects "ingest only".

### 32.6 Ingest Date Range Update

The build plan's §26 example uses `--from 2025-11-01`. The headline frozen batch for this PoC uses:

```
pte ingest --snapshot --filter 'status="active"' --from 2025-01-01 --to 2026-05-01 --format json_v2
```

This wider window (16 months) gives the time-series tasks (T2, ARIMA) more historical data for training and the rolling-window backtest a meaningful held-out period.

*End of Document 2.*
