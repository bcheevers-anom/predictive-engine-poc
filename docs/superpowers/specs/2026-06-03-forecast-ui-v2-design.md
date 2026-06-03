# Forecast Screen v2 — Design Spec

**Date:** 2026-06-03  
**Status:** Approved  
**Scope:** ForecastScreen.tsx redesign + two new API endpoints + extended ML metrics in the evaluate() backend. No changes to the data pipeline or Dev Panel.

---

## Goal

Make the forecast screen usable by a non-technical stakeholder. Lead with actionable output (top predicted tools), explain accuracy in plain English, and show a trend chart that puts the prediction in historical context.

---

## Layout

```
┌─────────────────────────────────────────────────────────────┐
│  Sector: [Financial Services ▼]          [Get Forecast]     │
├──────────────────────┬──────────────────────────────────────┤
│  Prediction          │  Best simple guess                   │
│  accuracy            │                                      │
│  13%  ⓘ             │  27%                                 │
│  [blue card]         │  Just picking the most common tools  │
│                      │  [grey/purple card]                  │
├──────────────────────┴──────────────────────────────────────┤
│  ⚠ Directional only — this model doesn't yet outperform     │
│  a simple frequency guess on this dataset.                  │
│  [yellow banner — only shown when passes_gate=False]        │
├─────────────────────────────────────────────────────────────┤
│  Tool activity — Financial Services (May 2026)              │
│  [stacked area chart — see chart spec below]                │
├─────────────────────────────────────────────────────────────┤
│  Top predicted tools for this sector:                       │
│  [POWERSTATS ×25 ⓘ]  [PowerShell ×24 ⓘ]  [Ngrok ×22 ⓘ]  │
├─────────────────────────────────────────────────────────────┤
│  Sector coverage heatmap  /  AQL idiom (collapsed)          │
└─────────────────────────────────────────────────────────────┘
```

---

## Metric Cards

Two cards side by side at the top.

**Left — Prediction accuracy**
- Value: `top_k_accuracy` from the model report, shown as percentage (e.g. "13%")
- Background: light blue (`#e3f2fd`)
- Label: "Prediction accuracy"
- ⓘ tooltip text: *"Out of every 10 tools we predicted would target this sector, about [N] actually appeared in the following week's threat reports."* (N = round(top_k_accuracy × 10))

**Right — Best simple guess**
- Value: `sector_frequency_baseline_top_k` from the model report, shown as percentage (e.g. "27%")
- Background: light grey/purple (`#f3e5f5`)
- Label: "Best simple guess"
- Sub-label: "Just picking the most common tools"
- No ⓘ needed — the label is self-explanatory

Both cards sit in a flex row, equal width.

---

## Directional-Only Banner

Shown only when `passes_gate === false`.

```
⚠  Directional only — this model doesn't yet outperform a simple frequency
   guess on this dataset. Predictions show the right direction but should
   not be treated as firm.
```

Yellow background (`#fff8e1`), amber border (`#f9a825`), rounded corners. Sits between the metric cards and the chart.

When `passes_gate === true`: banner is not rendered. No other UI change.

---

## Trend Chart

**Type:** Stacked area chart (Recharts `AreaChart`)  
**Data source:** `/api/trends?batch_id=&industry=` (new endpoint — see API section)  
**X-axis:** Week labels (e.g. "May 1", "May 8", "May 15", "May 22", "May 29")  
**Y-axis:** Number of threat reports mentioning that tool  
**Series:** Top 5 tools for the selected sector by total count  
**Visual treatment:**
- Training period (weeks before holdout): normal opacity areas
- Holdout period (final week): lighter opacity + vertical dashed line at the boundary labelled "Holdout week"
- Legend below chart with tool names and colours

The holdout boundary date comes from `gate_note` in the forecast response (already returned by the API, format: `"time-split: ..., holdout_start=2026-05-25, ..."`).

---

## Tool Prediction Chips

Below the chart. Rendered as pill-shaped chips in a flex row.

Each chip shows: `{tool name} × {count}` plus a ⓘ icon.  
Clicking ⓘ opens an `InfoTooltip` with a one-sentence plain-English description of the tool.

Tool descriptions come from `/api/tool-info?tool=` (new endpoint — see API section). If no description is found, the tooltip shows: *"A tool or malware family observed in threat intelligence reports."*

**Maximum 5 chips** to avoid overflow. If more exist, show a "Show more" link.

---

## InfoTooltip Component

New reusable component: `web/src/components/InfoTooltip.tsx`

- Props: `text: string`, `children: ReactNode`
- Click to open, click anywhere outside to close
- Positioned absolutely below the trigger element
- Max width 280px, white background, shadow, rounded corners
- Plain text only (no markdown rendering needed)
- Used by: metric card ⓘ, tool chip ⓘ

Replaces the existing `HonestyTooltip` component where appropriate.

---

## New API Endpoints

### GET `/api/trends`

**Params:** `batch_id`, `industry`, `data_dir` (default "data"), `top_n` (default 5)

**Logic:**
1. Read `industry_tool_cooccur` feature table for the batch
2. Filter to rows where `industry == industry` param and `tool` is non-empty
3. Group by (week of `created_ts`, tool) — count rows per group
4. Return top `top_n` tools by total count across all weeks
5. Return weekly series for each of those tools

**Response:**
```json
{
  "weeks": ["2026-05-01", "2026-05-08", "2026-05-15", "2026-05-22", "2026-05-29"],
  "series": [
    {"tool": "POWERSTATS", "counts": [8, 6, 5, 4, 2]},
    {"tool": "PowerShell", "counts": [5, 7, 6, 4, 2]},
    ...
  ],
  "holdout_start": "2026-05-25"
}
```

`holdout_start` is extracted from `t2ind_report.json` eval_note for this batch.

### GET `/api/tool-info`

**Params:** `tool` (tool name string)

**Logic:** Static lookup dict in the route file. Keys are lowercase tool names. Returns description if found, otherwise a generic fallback.

**Initial lookup dict (extend as needed):**
```python
{
  "powershell": "Microsoft's scripting language, frequently abused by attackers to run commands and download malware without triggering antivirus.",
  "cobalt strike": "Commercial penetration testing tool widely used by attackers as a command-and-control framework after gaining initial access.",
  "mimikatz": "A credential-dumping tool that extracts passwords and tokens from Windows memory.",
  "lockbit": "A ransomware family that encrypts victim files and demands payment — one of the most prolific ransomware groups globally.",
  "ngrok": "A tunnelling tool that creates temporary public URLs — used legitimately by developers, abused by attackers to bypass firewalls.",
  "anydesk": "Remote desktop software — legitimate tool sometimes abused by attackers to maintain persistent access.",
  "impacket": "A Python library for network protocols, used by attackers for lateral movement and credential theft.",
  "powerstats": "A PowerShell-based backdoor associated with Iranian threat actors, used for command-and-control.",
  "powgoop": "A PowerShell downloader associated with Iranian state-linked threat actors.",
}
```

Matching is case-insensitive. If the tool name contains a known name as a substring, use that match.

---

## Files to Create / Modify

| File | Change |
|---|---|
| `web/src/components/InfoTooltip.tsx` | Create — reusable tooltip component |
| `web/src/components/graphs/ToolTrendChart.tsx` | Create — stacked area chart |
| `web/src/components/MetricsGrid.tsx` | Create — grid of ML metric cards with ⓘ explainers |
| `web/src/components/ModelProvenancePanel.tsx` | Create — collapsible model details panel |
| `web/src/components/ForecastScreen.tsx` | Modify — new layout: metric cards, chart, metrics grid, provenance |
| `api/routes/forecast.py` | Modify — add `/api/trends` and `/api/tool-info`; extend forecast response with all metrics |
| `src/pte/predict/t2_industry.py` | Modify — compute precision@k, recall@k, F1@k, MAP, NDCG@k in evaluate() |
| `src/pte/evaluate/metrics.py` | Modify — add `precision_at_k`, `recall_at_k`, `f1_at_k`, `mean_average_precision`, `ndcg_at_k` functions |
| `web/src/types/api.ts` | Modify — add `TrendsResponse`, `MetricsReport` types |

---

## Extended ML Metrics (backend + UI)

### Why T2-Industry is a ranking model, not a classifier

T2-Industry predicts a ranked list of tools for a sector. Standard binary classification metrics (F1, AUROC, precision/recall as single numbers) don't directly apply, but their ranking equivalents do — and are arguably more informative for this use case.

### Metrics to compute and show

The `t2_industry.evaluate()` method must be extended to compute and store all of the following in `t2ind_report.json`. The forecast API must pass them through. The UI must render each with a plain-English ⓘ explainer.

| Metric | Display name | Tooltip (Option B plain-English tone) |
|---|---|---|
| `top_k_accuracy` | Prediction accuracy | "Out of every 10 tools we predicted would target this sector, about N actually appeared in the following week's threat reports." |
| `precision_at_k` | Precision | "Of the tools we flagged, what fraction were genuinely seen in that sector? High precision = fewer false alarms." |
| `recall_at_k` | Recall | "Of all the tools that actually appeared, what fraction did we catch? High recall = fewer missed threats." |
| `f1_at_k` | F1 score | "The balance between precision and recall — a single number that penalises both missing threats and false alarms equally." |
| `mean_average_precision` | Average precision (MAP) | "Measures whether the most important tools are ranked highest, not just whether they appear somewhere in our top-10 list. Higher is better." |
| `ndcg_at_k` | Ranking quality (NDCG) | "Rewards predicting the most common threats at the top of the list. A score of 1.0 would mean perfect ranking." |
| `coverage_recall` | Sector coverage | "The fraction of sectors we can forecast at all — sectors with fewer than 5 training examples are skipped." |
| `sector_frequency_baseline_top_k` | Simple guess | "Just picking the most common tools overall, ignoring which sector we're forecasting." |
| `lift_over_baseline` | Lift vs simple guess | "How much better (or worse) the model is compared to the simple guess. Positive = model adds value." |

### Definitions for ranking metrics (Precision@k, Recall@k, F1@k, MAP, NDCG@k)

All metrics use k=3 (top-3 predictions) to match the current top_k_accuracy evaluation.

**Precision@3** = (tools predicted that appeared in holdout) ÷ 3  
**Recall@3** = (tools predicted that appeared in holdout) ÷ (total unique tools in holdout for that sector)  
**F1@3** = 2 × (P@3 × R@3) / (P@3 + R@3)  
**MAP** = mean over all evaluated sectors of average precision per sector  
**NDCG@3** = discounted cumulative gain at 3, using holdout tool frequency as relevance weights  

All are averaged across the 60 evaluated industries.

### Model provenance panel

Below the metrics, a collapsible "Model details" section showing:
- **Model type:** Co-occurrence frequency ranking (top-k)
- **AQL port idiom:** the full idiom string (already in report)
- **Training data:** N rows, date range (from eval_note)
- **Holdout data:** N rows, holdout start date
- **Industries evaluated:** 60
- **Extraction model:** Claude Opus 4.8 via AWS Bedrock (LLM that produced the training features)
- **Feature tier:** LLM_EXTRACTED (industry/tool pairs from actor and campaign descriptions)

This makes it explicit that the predictions are downstream of an LLM extraction step, and what that model was.

### UI layout for metrics

A grid of metric cards below the tool chips. Two rows of 4:

```
┌──────────┬──────────┬──────────┬──────────┐
│ Precision│  Recall  │    F1    │   MAP    │
│  0.13 ⓘ  │  0.08 ⓘ  │  0.10 ⓘ  │  0.11 ⓘ  │
├──────────┼──────────┼──────────┼──────────┤
│  NDCG@3  │  Lift    │Coverage  │ Baseline │
│  0.09 ⓘ  │ -0.13 ⓘ  │  60 sec  │  0.27 ⓘ  |
└──────────┴──────────┴──────────┴──────────┘
```

Each card: metric name, value, ⓘ InfoTooltip with plain-English explanation. Colour coding:
- Green tint if metric > baseline equivalent
- Red tint if metric < baseline equivalent  
- Grey if no baseline comparison available

The grid is labelled: **"Model performance details"** with a subtitle: *"All metrics evaluated on the held-out week (May 25–31, 2026) — data the model never saw during training."*

---

## What Does Not Change

- Dev Panel, batch selector, DevPanel.tsx
- Coverage heatmap (`CooccurrenceHeatmap.tsx`)
- Evidence trail (`EvidenceTrail.tsx`)
- All backend models, feature store, extraction pipeline
- Sector dropdown logic (already working)
- `passes_gate` computation — only its UI presentation changes

---

## Self-Review

1. **Placeholder scan:** No TBDs. Tool info dict has real entries. Chart data format is concrete.
2. **Internal consistency:** `holdout_start` is parsed from `gate_note` in both the trend chart and the existing banner — consistent source.
3. **Scope:** Single screen change + 2 API endpoints + 2 new components. Tight.
4. **Ambiguity:** "Top 5 tools" is defined by total count across all weeks, not by last-week count — explicit.
