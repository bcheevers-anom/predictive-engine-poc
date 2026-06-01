import React, { useState } from 'react'

interface Props {
  reliabilityBasis: string
  coverage: Record<string, number>
  missingData?: string[]
}

export default function HonestyTooltip({ reliabilityBasis, coverage, missingData }: Props) {
  const [open, setOpen] = useState(false)
  return (
    <div style={{ position: 'relative', display: 'inline-block' }}>
      <button onClick={() => setOpen(!open)} style={{ fontSize: 12, color: '#666', background: 'none', border: '1px solid #ccc', borderRadius: 4, padding: '2px 8px', cursor: 'pointer' }}>
        How confident is this?
      </button>
      {open && (
        <div style={{ position: 'absolute', top: '100%', left: 0, zIndex: 10, background: 'white', border: '1px solid #ccc', borderRadius: 8, padding: 16, width: 320, boxShadow: '0 2px 12px rgba(0,0,0,0.15)' }}>
          <strong>Reliability basis:</strong> {reliabilityBasis}
          {missingData && missingData.length > 0 && <p style={{ marginTop: 8 }}><strong>Missing data:</strong> {missingData.join(', ')}</p>}
          <button onClick={() => setOpen(false)} style={{ marginTop: 8, fontSize: 11, color: '#666', background: 'none', border: 'none', cursor: 'pointer' }}>Close</button>
        </div>
      )}
    </div>
  )
}
