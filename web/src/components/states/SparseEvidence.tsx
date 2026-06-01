import React, { ReactNode } from 'react'

export default function SparseEvidence({ count, children }: { count: number; children: ReactNode }) {
  return (
    <div>
      {count < 5 && (
        <div style={{ padding: '6px 12px', background: '#e3f2fd', borderRadius: 4, marginBottom: 8, fontSize: 13 }}>
          Based on {count} source{count !== 1 ? 's' : ''} — interpret with caution
        </div>
      )}
      {children}
    </div>
  )
}
