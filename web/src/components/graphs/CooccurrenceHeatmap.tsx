import React from 'react'

interface Props { coverage: Record<string, number> }

export default function CooccurrenceHeatmap({ coverage }: Props) {
  const entries = Object.entries(coverage).sort((a, b) => b[1] - a[1])
  const max = Math.max(...entries.map(e => e[1]), 1)
  return (
    <div>
      <h3 style={{ fontSize: 14, marginBottom: 8 }}>Industry Coverage</h3>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
        {entries.map(([ind, count]) => (
          <div key={ind} style={{
            padding: '6px 12px', borderRadius: 4,
            background: `rgba(25, 118, 210, ${0.1 + 0.8 * (count / max)})`,
            color: count / max > 0.5 ? 'white' : 'black', fontSize: 13,
          }}>
            {ind}: {count}
          </div>
        ))}
      </div>
    </div>
  )
}
