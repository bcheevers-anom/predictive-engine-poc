import React, { useState, useEffect } from 'react'
import { ForecastResponse } from '../types/api'
import InsufficientCoverage from './states/InsufficientCoverage'
import LowConfidence from './states/LowConfidence'
import NoModelYet from './states/NoModelYet'
import SparseEvidence from './states/SparseEvidence'
import FeatureContributions from './graphs/FeatureContributions'
import ClassificationGraph from './graphs/ClassificationGraph'
import TimeSeriesGraph from './graphs/TimeSeriesGraph'
import CooccurrenceHeatmap from './graphs/CooccurrenceHeatmap'
import CalibrationCurve from './graphs/CalibrationCurve'
import HonestyTooltip from './HonestyTooltip'
import EvidenceTrail from './EvidenceTrail'

const MIN_CONFIDENCE = 0.40

interface Props { batchId: string }

export default function ForecastScreen({ batchId }: Props) {
  const [industry, setIndustry] = useState('Oil and Gas')
  const [loading, setLoading] = useState(false)
  const [data, setData] = useState<ForecastResponse | null>(null)
  const [error, setError] = useState<string | null>(null)

  const fetchForecast = async () => {
    if (!batchId) return
    setLoading(true)
    setError(null)
    try {
      const resp = await fetch(`/api/forecast?industry=${encodeURIComponent(industry)}&batch_id=${batchId}`)
      setData(await resp.json())
    } catch {
      setError('Failed to load forecast.')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { if (batchId) fetchForecast() }, [batchId])

  if (!batchId) return <p style={{ color: '#888' }}>Select a batch in the Dev Panel to view forecasts.</p>

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 16, marginBottom: 24 }}>
        <label>Industry: <input value={industry} onChange={e => setIndustry(e.target.value)} style={{ marginLeft: 8, padding: '4px 8px' }} /></label>
        <button onClick={fetchForecast} disabled={loading} style={{ padding: '6px 18px' }}>{loading ? 'Loading...' : 'Get Forecast'}</button>
      </div>
      {error && <p style={{ color: 'red' }}>{error}</p>}
      {data?.status === 'no_model' && <NoModelYet message={data.message} hint={data.hint} />}
      {data?.status === 'insufficient_coverage' && <InsufficientCoverage dimension={industry} found={data.message} />}
      {data?.status === 'not_supported' && <p style={{ color: '#888' }}>{data.reason}</p>}
      {data?.status === 'ok' && data.finding && (() => {
        const conf = data.finding.confidence
        const prediction = data.prediction || []
        const evidence: any[] = []
        const coverage = data.coverage || {}
        const isLowConfidence = conf < MIN_CONFIDENCE

        const Content = () => (
          <div style={{ display: 'grid', gap: 24 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              <div>
                <h2 style={{ margin: 0 }}>{data.finding!.title}</h2>
                <p style={{ color: '#555', marginTop: 4 }}>Confidence: {(conf * 100).toFixed(0)}%</p>
              </div>
              <HonestyTooltip reliabilityBasis="LLM_EXTRACTED (industry/tool) + DERIVED (trend)" coverage={coverage} />
            </div>
            <SparseEvidence count={evidence.length}><EvidenceTrail evidence={evidence} batchId={batchId} /></SparseEvidence>
            {data.finding!.viz_type === 'classification' && prediction.length > 0 && <ClassificationGraph data={prediction} />}
            {data.finding!.viz_type === 'timeseries' && <TimeSeriesGraph data={[]} />}
            {data.feature_contributions && data.feature_contributions.length > 0 && <FeatureContributions contributions={data.feature_contributions} />}
            {Object.keys(coverage).length > 0 && <CooccurrenceHeatmap coverage={coverage} />}
            <CalibrationCurve />
            {data.aql_port_idiom && (
              <details style={{ fontSize: 12, color: '#888' }}>
                <summary>AQL port idiom</summary>
                <pre style={{ marginTop: 4, background: '#f5f5f5', padding: 8, borderRadius: 4 }}>{data.aql_port_idiom}</pre>
              </details>
            )}
          </div>
        )
        return isLowConfidence ? <LowConfidence><Content /></LowConfidence> : <Content />
      })()}
    </div>
  )
}
