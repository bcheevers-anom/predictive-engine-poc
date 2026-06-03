import React, { useState } from 'react'
import ForecastScreen from './components/ForecastScreen'
import DevPanel from './components/DevPanel'

export default function App() {
  const [tab, setTab] = useState<'forecast' | 'devpanel'>('forecast')
  const [batchId, setBatchId] = useState<string>('')

  return (
    <div style={{ fontFamily: 'system-ui, sans-serif', maxWidth: 1200, margin: '0 auto', padding: 24 }}>
      <h1 style={{ fontSize: 22, marginBottom: 4 }}>Predictive Threat Engine</h1>
      <nav style={{ marginBottom: 24, borderBottom: '1px solid #ddd' }}>
        <button onClick={() => setTab('forecast')} style={{ marginRight: 16, fontWeight: tab === 'forecast' ? 700 : 400 }}>Forecast</button>
        <button onClick={() => setTab('devpanel')} style={{ fontWeight: tab === 'devpanel' ? 700 : 400 }}>Dev Panel</button>
      </nav>
      {/* Keep both mounted so ForecastScreen loads industries as soon as batch is selected */}
      <div style={{ display: tab === 'forecast' ? 'block' : 'none' }}>
        <ForecastScreen batchId={batchId} />
      </div>
      <div style={{ display: tab === 'devpanel' ? 'block' : 'none' }}>
        <DevPanel onBatchSelected={(id) => { setBatchId(id); setTab('forecast') }} />
      </div>
    </div>
  )
}
