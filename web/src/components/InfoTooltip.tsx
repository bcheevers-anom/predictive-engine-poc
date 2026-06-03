import React, { useState, useRef, useEffect } from 'react'

interface Props {
  text: string
  children?: React.ReactNode
}

export default function InfoTooltip({ text, children }: Props) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  return (
    <span ref={ref} style={{ position: 'relative', display: 'inline-block' }}>
      <button
        onClick={() => setOpen(o => !o)}
        style={{
          background: 'none', border: 'none', cursor: 'pointer',
          color: '#1976d2', fontSize: 13, padding: '0 2px',
          fontWeight: 700, lineHeight: 1,
        }}
        aria-label="More information"
      >
        {children || 'ⓘ'}
      </button>
      {open && (
        <div style={{
          position: 'absolute', top: '100%', left: 0, zIndex: 100,
          background: 'white', border: '1px solid #ddd', borderRadius: 6,
          padding: '10px 12px', width: 280, fontSize: 13, color: '#333',
          boxShadow: '0 4px 16px rgba(0,0,0,0.12)', lineHeight: 1.5,
        }}>
          {text}
        </div>
      )}
    </span>
  )
}
