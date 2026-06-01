import React from 'react'

interface Evidence { source_id: string; tier: string; confidence?: number }

export default function EvidenceTrail({ evidence, batchId }: { evidence: Evidence[]; batchId: string }) {
  return (
    <div>
      <h3 style={{ fontSize: 14, marginBottom: 8 }}>Evidence Trail ({evidence.length} source{evidence.length !== 1 ? 's' : ''})</h3>
      {evidence.length === 0 && <p style={{ color: '#888', fontSize: 13 }}>No evidence sources recorded.</p>}
      <ul style={{ listStyle: 'none', padding: 0, margin: 0 }}>
        {evidence.map((e, i) => (
          <li key={i} style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '4px 0', borderBottom: '1px solid #f0f0f0', fontSize: 13 }}>
            <a href={`/api/evidence/${e.source_id}?batch_id=${batchId}`} target="_blank" rel="noreferrer" style={{ color: '#1976d2' }}>{e.source_id}</a>
            <span style={{ padding: '2px 6px', background: '#e3f2fd', borderRadius: 3, fontSize: 11 }}>{e.tier}</span>
            {e.confidence != null && <span style={{ color: '#888' }}>{(e.confidence * 100).toFixed(0)}% confidence</span>}
          </li>
        ))}
      </ul>
    </div>
  )
}
