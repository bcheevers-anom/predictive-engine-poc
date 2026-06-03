# Forecast Screen v2 — Design Spec

**Date:** 2026-06-03  
**Status:** Approved  
**Scope:** ForecastScreen.tsx redesign + two new API endpoints. No changes to backend models, data pipeline, or Dev Panel.

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
| `web/src/components/ForecastScreen.tsx` | Modify — new layout, metric cards, chart integration |
| `api/routes/forecast.py` | Modify — add `/api/trends` and `/api/tool-info` endpoints |
| `web/src/types/api.ts` | Modify — add `TrendsResponse` type |

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
