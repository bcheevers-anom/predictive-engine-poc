import React, { useState, useEffect } from 'react'
import { ForecastResponse } from '../types/api'
import InsufficientCoverage from './states/InsufficientCoverage'
import LowConfidence from './states/LowConfidence'
import NoModelYet from './states/NoModelYet'
import SparseEvidence from './states/SparseEvidence'
import FeatureContributions from './graphs/FeatureContributions'
import ClassificationGraph from './graphs/ClassificationGraph'
import CooccurrenceHeatmap from './graphs/CooccurrenceHeatmap'
import CalibrationCurve from './graphs/CalibrationCurve'
import HonestyTooltip from './HonestyTooltip'
import EvidenceTrail from './EvidenceTrail'

const MIN_CONFIDENCE = 0.40

interface Props { batchId: string }

export default function ForecastScreen({ batchId }: Props) {
  const [industries, setIndustries] = useState<string[]>([])
  const [industryCoverage, setIndustryCoverage] = useState<Record<string, number>>({})
  const [industry, setIndustry] = useState('')
  const [loading, setLoading] = useState(false)
  const [data, setData] = useState<ForecastResponse | null>(null)
  const [error, setError] = useState<string | null>(null)

  // Load industry list when batch changes
  useEffect(() => {
    if (!batchId) return
    setData(null)
    setIndustries([])
    setIndustry('')
    fetch(`/api/industries?batch_id=${batchId}&min_count=5`)
      .then(r => r.json())
      .then(d => {
        const list: string[] = d.industries || []
        setIndustries(list)
        setIndustryCoverage(d.coverage || {})
        if (list.length > 0) setIndustry(list[0])
      })
      .catch(() => {})
  }, [batchId])

  const fetchForecast = async () => {
    if (!batchId || !industry) return
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

  if (!batchId) return (
    <div style={{ padding: 32, color: '#888', textAlign: 'center' }}>
      <p style={{ fontSize: 16 }}>Select a batch in the Dev Panel to view forecasts.</p>
    </div>
  )

  return (
    <div>
      {/* Controls */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 24, flexWrap: 'wrap' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <label htmlFor="industry-select" style={{ fontWeight: 600, whiteSpace: 'nowrap' }}>Sector:</label>
          {industries.length > 0 ? (
            <select
              id="industry-select"
              value={industry}
              onChange={e => setIndustry(e.target.value)}
              style={{ padding: '6px 10px', minWidth: 220, borderRadius: 4, border: '1px solid #ccc', fontSize: 14 }}
            >
              {industries.map(ind => (
                <option key={ind} value={ind}>
                  {ind} ({industryCoverage[ind] ?? 0} entities)
                </option>
              ))}
            </select>
          ) : (
            <span style={{ color: '#aaa', fontSize: 13 }}>No industries loaded yet</span>
          )}
        </div>
        <button
          onClick={fetchForecast}
          disabled={loading || !industry}
          style={{
            padding: '6px 20px', background: industry ? '#1976d2' : '#ccc',
            color: 'white', border: 'none', borderRadius: 4, cursor: industry ? 'pointer' : 'not-allowed',
            fontSize: 14, fontWeight: 600,
          }}
        >
          {loading ? 'Loading...' : 'Get Forecast'}
        </button>
        {industries.length > 0 && (
          <span style={{ fontSize: 12, color: '#888' }}>{industries.length} sectors with signal</span>
        )}
      </div>

      {error && <p style={{ color: 'red' }}>{error}</p>}

      {data?.status === 'no_model' && <NoModelYet message={data.message} hint={data.hint} />}
      {data?.status === 'not_supported' && <p style={{ color: '#888' }}>{data.reason}</p>}

      {data?.status === 'ok' && data.finding && (() => {
        const conf = data.finding.confidence
        const prediction = data.prediction || []
        const evidence: any[] = []
        const coverage = data.coverage || {}
        const passeGate = (data as any).passes_gate
        const gateNote = (data as any).gate_note || ''
        const baseline = (data as any).baselines?.sector_frequency_top_k ?? 0
        const isLowConfidence = conf < MIN_CONFIDENCE

        const GateBanner = () => !passeGate ? (
          <div style={{
            padding: '10px 16px', background: '#fff8e1', border: '1px solid #f9a825',
            borderRadius: 6, marginBottom: 16, fontSize: 13,
          }}>
            <strong>Directional only</strong> — model accuracy ({(conf * 100).toFixed(1)}%) does not beat the
            frequency baseline ({(baseline * 100).toFixed(1)}%) on the held-out week.
            {gateNote && <span style={{ color: '#777', marginLeft: 8 }}>({gateNote})</span>}
          </div>
        ) : null

        const Content = () => (
          <div style={{ display: 'grid', gap: 24 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
              <div>
                <h2 style={{ margin: 0, fontSize: 18 }}>{data.finding!.title}</h2>
                <div style={{ display: 'flex', gap: 16, marginTop: 6, fontSize: 13, color: '#555' }}>
                  <span>Top-k accuracy: <strong>{(conf * 100).toFixed(1)}%</strong></span>
                  <span>Baseline: <strong>{(baseline * 100).toFixed(1)}%</strong></span>
                  <span style={{ color: conf > baseline ? '#2e7d32' : '#c62828' }}>
                    {conf > baseline ? '▲' : '▼'} {Math.abs((conf - baseline) * 100).toFixed(1)}% vs baseline
                  </span>
                </div>
              </div>
              <HonestyTooltip
                reliabilityBasis="LLM_EXTRACTED (industry/tool) + DERIVED (trend)"
                coverage={coverage}
              />
            </div>

            <GateBanner />

            {prediction.length > 0 && (
              <div>
                <h3 style={{ fontSize: 14, marginBottom: 8 }}>
                  Top predicted tools for <em>{industry}</em>
                </h3>
                <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                  {prediction.map((p: any, i: number) => (
                    <div key={i} style={{
                      padding: '6px 14px', background: '#e3f2fd', borderRadius: 20,
                      fontSize: 13, fontWeight: 500,
                    }}>
                      {p.tool} <span style={{ color: '#888', fontWeight: 400 }}>({p.count})</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
            {prediction.length === 0 && (
              <p style={{ color: '#888', fontSize: 13 }}>
                No tool predictions available for <em>{industry}</em> — try a sector with higher coverage.
              </p>
            )}

            <SparseEvidence count={evidence.length}>
              <EvidenceTrail evidence={evidence} batchId={batchId} />
            </SparseEvidence>

            {Object.keys(coverage).length > 0 && (
              <div>
                <h3 style={{ fontSize: 14, marginBottom: 8 }}>Sector coverage (entities extracted)</h3>
                <CooccurrenceHeatmap coverage={coverage} />
              </div>
            )}

            {data.feature_contributions && data.feature_contributions.length > 0 && (
              <FeatureContributions contributions={data.feature_contributions} />
            )}

            <CalibrationCurve />

            {(data as any).aql_port_idiom && (
              <details style={{ fontSize: 12, color: '#888' }}>
                <summary style={{ cursor: 'pointer' }}>AQL port idiom (engineering reference)</summary>
                <pre style={{ marginTop: 4, background: '#f5f5f5', padding: 8, borderRadius: 4, overflow: 'auto' }}>
                  {(data as any).aql_port_idiom}
                </pre>
              </details>
            )}
          </div>
        )
        return isLowConfidence ? <LowConfidence><Content /></LowConfidence> : <Content />
      })()}
    </div>
  )
}
