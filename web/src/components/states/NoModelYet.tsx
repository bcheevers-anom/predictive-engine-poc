import React from 'react'

export default function NoModelYet({ message, hint }: { message?: string; hint?: string }) {
  return (
    <div style={{ padding: 24, background: '#f5f5f5', border: '1px solid #ccc', borderRadius: 8 }}>
      <strong>{message || "This forecast hasn't been generated for the current batch yet."}</strong>
      {hint && <p style={{ marginTop: 8, color: '#555' }}>{hint}</p>}
    </div>
  )
}
