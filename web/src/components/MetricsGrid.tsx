import React from 'react'
import InfoTooltip from './InfoTooltip'

interface MetricCardProps {
  label: string
  value: number | null | undefined
  tooltip: string
  baseline?: number | null
  format?: 'percent' | 'decimal' | 'count'
}

function MetricCard({ label, value, tooltip, baseline, format = 'percent' }: MetricCardProps) {
  const fmt = (v: number | null | undefined) => {
    if (v == null) return '—'
    if (format === 'percent') return `${(v * 100).toFixed(1)}%`
    if (format === 'count') return String(Math.round(v))
    return v.toFixed(3)
  }

  const isGood = value != null && baseline != null ? value > baseline : null
  const bg = isGood === true ? '#e8f5e9' : isGood === false ? '#fce4ec' : '#f5f5f5'
  const valueColor = isGood === true ? '#2e7d32' : isGood === false ? '#c62828' : '#333'

  return (
    <div style={{
      background: bg, borderRadius: 8, padding: '12px 14px',
      display: 'flex', flexDirection: 'column', gap: 4,
    }}>
      <div style={{ fontSize: 11, color: '#666', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.04em' }}>
        {label} <InfoTooltip text={tooltip} />
      </div>
      <div style={{ fontSize: 22, fontWeight: 700, color: valueColor }}>
        {fmt(value)}
      </div>
      {baseline != null && (
        <div style={{ fontSize: 11, color: '#888' }}>
          Baseline: {fmt(baseline)}
        </div>
      )}
    </div>
  )
}

interface Props {
  metrics: {
    precision_at_k?: number | null
    recall_at_k?: number | null
    f1_at_k?: number | null
    map_score?: number | null
    ndcg_at_k?: number | null
    top_k_accuracy?: number | null
    baseline_top_k?: number | null
    lift_over_baseline?: number | null
  }
  holdoutLabel?: string
}

export default function MetricsGrid({ metrics, holdoutLabel }: Props) {
  const b = metrics.baseline_top_k ?? undefined

  return (
    <div>
      <div style={{ marginBottom: 8 }}>
        <h3 style={{ fontSize: 14, margin: 0 }}>Model performance details</h3>
        <p style={{ fontSize: 12, color: '#888', margin: '4px 0 0' }}>
          All metrics evaluated on {holdoutLabel || 'the held-out test week'} — data the model never saw during training.
          {b != null && ` Green = beats the simple baseline (${(b * 100).toFixed(1)}%). Red = does not.`}
        </p>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 10 }}>
        <MetricCard
          label="Prediction accuracy"
          value={metrics.top_k_accuracy}
          tooltip="Out of every 10 tools we predicted would target this sector, about this many actually appeared in the test week's threat reports."
          baseline={b}
        />
        <MetricCard
          label="Precision"
          value={metrics.precision_at_k}
          tooltip="Of the tools we flagged as likely threats, what fraction were genuinely seen in this sector during the test week? High precision means fewer false alarms."
          baseline={b}
        />
        <MetricCard
          label="Recall"
          value={metrics.recall_at_k}
          tooltip="Of all the tools that actually appeared in this sector during the test week, what fraction did we successfully predict? High recall means fewer missed threats."
        />
        <MetricCard
          label="F1 score"
          value={metrics.f1_at_k}
          tooltip="The balance between precision and recall — a single number that penalises both missing threats and raising false alarms equally. 1.0 would be perfect."
        />
        <MetricCard
          label="Avg precision (MAP)"
          value={metrics.map_score}
          tooltip="Measures whether the most important tools are ranked highest in our predictions, not just whether they appear somewhere in the top 3. Higher is better."
          baseline={b}
        />
        <MetricCard
          label="Ranking quality (NDCG)"
          value={metrics.ndcg_at_k}
          tooltip="Rewards putting the most frequently seen threats at the top of our prediction list. A score of 1.0 would mean perfect ranking of threats by severity."
        />
        <MetricCard
          label="Lift vs baseline"
          value={metrics.lift_over_baseline}
          tooltip="How much better or worse the model is compared to simply predicting the most common tools overall. Positive means the model adds value beyond a naive guess."
          format="decimal"
        />
        <MetricCard
          label="Simple baseline"
          value={b}
          tooltip="The accuracy achieved by just predicting the most common tools overall, ignoring which sector we are forecasting. The model should aim to beat this."
        />
      </div>
    </div>
  )
}
