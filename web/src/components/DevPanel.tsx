import React, { useState, useEffect } from 'react'
import { BatchInfo } from '../types/api'

interface Props { onBatchSelected: (id: string) => void }

export default function DevPanel({ onBatchSelected }: Props) {
  const [fromDate, setFromDate] = useState('2025-01-01')
  const [toDate, setToDate] = useState('2026-05-01')
  const [feeds, setFeeds] = useState('')
  const [ingestOnly, setIngestOnly] = useState(false)
  const [batches, setBatches] = useState<BatchInfo[]>([])
  const [status, setStatus] = useState<string | null>(null)
  const [selectedBatch, setSelectedBatch] = useState<string>('')

  const loadBatches = async () => {
    try {
      const resp = await fetch('/api/devpanel/batches')
      const data = await resp.json()
      setBatches(data.batches || [])
    } catch {}
  }

  useEffect(() => { loadBatches() }, [])

  const triggerBatch = async () => {
    setStatus('Starting batch...')
    try {
      const resp = await fetch('/api/devpanel/batch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ from_date: fromDate, to_date: toDate, feeds: feeds ? feeds.split(',') : null, ingest_only: ingestOnly }),
      })
      setStatus(`Pipeline started: ${JSON.stringify(await resp.json())}`)
      setTimeout(loadBatches, 3000)
    } catch {
      setStatus('Error starting batch.')
    }
  }

  return (
    <div>
      <h2 style={{ fontSize: 16, marginBottom: 16 }}>Dev Panel</h2>
      <div style={{ marginBottom: 24 }}>
        <h3 style={{ fontSize: 14 }}>Select Existing Batch</h3>
        <select value={selectedBatch} onChange={e => { setSelectedBatch(e.target.value); onBatchSelected(e.target.value) }} style={{ width: '100%', padding: '6px 8px' }}>
          <option value="">-- select a batch --</option>
          {batches.map(b => <option key={b.batch_id} value={b.batch_id}>{b.batch_id} ({b.from_date} to {b.to_date}, {b.total_deduplicated?.toLocaleString()} records)</option>)}
        </select>
      </div>
      <div style={{ background: '#f9f9f9', padding: 16, borderRadius: 8 }}>
        <h3 style={{ fontSize: 14, marginTop: 0 }}>Run New Batch</h3>
        <div style={{ display: 'grid', gap: 12 }}>
          <label>From date: <input type="date" value={fromDate} onChange={e => setFromDate(e.target.value)} /></label>
          <label>To date: <input type="date" value={toDate} onChange={e => setToDate(e.target.value)} /></label>
          <label>Feeds (comma-separated, blank=all): <input value={feeds} onChange={e => setFeeds(e.target.value)} placeholder="all" /></label>
          <label><input type="checkbox" checked={ingestOnly} onChange={e => setIngestOnly(e.target.checked)} /> Ingest only (skip convert/train)</label>
          <button onClick={triggerBatch} style={{ padding: '8px 20px', background: '#1976d2', color: 'white', border: 'none', borderRadius: 4, cursor: 'pointer' }}>Run Batch</button>
        </div>
        {status && <p style={{ marginTop: 12, fontSize: 13, color: '#555' }}>{status}</p>}
      </div>
    </div>
  )
}
