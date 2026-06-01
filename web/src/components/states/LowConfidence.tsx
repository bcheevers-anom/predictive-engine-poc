import React, { ReactNode } from 'react'

export default function LowConfidence({ children }: { children: ReactNode }) {
  return (
    <div>
      <div style={{ padding: '8px 16px', background: '#fff3e0', border: '1px solid #ef6c00', borderRadius: 4, marginBottom: 12 }}>
        Low confidence — directional only
      </div>
      <div style={{ opacity: 0.75 }}>{children}</div>
    </div>
  )
}
