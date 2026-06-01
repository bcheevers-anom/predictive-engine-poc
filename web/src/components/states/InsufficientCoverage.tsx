import React from 'react'

interface Props { dimension: string; found?: string }

export default function InsufficientCoverage({ dimension, found }: Props) {
  return (
    <div style={{ padding: 24, background: '#fff8e1', border: '1px solid #f9a825', borderRadius: 8 }}>
      <strong>Not enough extracted signal to forecast {dimension} in this batch.</strong>
      {found && <p style={{ marginTop: 8, color: '#555' }}>{found}</p>}
      <p style={{ marginTop: 8, color: '#555' }}>Suggestion: try a wider time window or a different sector in the Dev Panel.</p>
    </div>
  )
}
