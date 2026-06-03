import React, { useState, useEffect } from 'react'
import { TrendsResponse } from '../types/api'
import InfoTooltip from './InfoTooltip'
import ToolTrendChart from './graphs/ToolTrendChart'
import MetricsGrid from './MetricsGrid'
import ModelProvenancePanel from './ModelProvenancePanel'
import NoModelYet from './states/NoModelYet'
import CooccurrenceHeatmap from './graphs/CooccurrenceHeatmap'
import EvidenceTrail from './EvidenceTrail'
import SparseEvidence from './states/SparseEvidence'

interface Props { batchId: string }

export default function ForecastScreen({ batchId }: Props) {
  const [industries, setIndustries] = useState<string[]>([])
  const [industryCoverage, setIndustryCoverage] = useState<Record<string, number>>({})
  const [industry, setIndustry] = useState('')
  const [industriesLoading, setIndustriesLoading] = useState(false)
  const [loading, setLoading] = useState(false)
  const [data, setData] = useState<any>(null)
  const [trends, setTrends] = useState<TrendsResponse | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!batchId) return
    setData(null); setTrends(null); setIndustries([]); setIndustry('')
    setIndustriesLoading(true)
    fetch(`/api/industries?batch_id=${batchId}&min_count=5`)
      .then(r => r.json())
      .then(d => {
        const list: string[] = d.industries || []
        setIndustries(list)
        setIndustryCoverage(d.coverage || {})
        if (list.length > 0) setIndustry(list[0])
      })
      .catch(() => {})
      .finally(() => setIndustriesLoading(false))
  }, [batchId])

  const fetchForecast = async () => {
    if (!batchId || !industry) return
    setLoading(true); setError(null); setTrends(null)
    try {
      const [forecastResp, trendsResp] = await Promise.all([
        fetch(`/api/forecast?industry=${encodeURIComponent(industry)}&batch_id=${batchId}`),
        fetch(`/api/trends?industry=${encodeURIComponent(industry)}&batch_id=${batchId}`),
      ])
      setData(await forecastResp.json())
      setTrends(await trendsResp.json())
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
    <div style={{ display: 'grid', gap: 24 }}>
      {/* Controls */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
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
                <option key={ind} value={ind}>{ind} ({industryCoverage[ind] ?? 0} entities)</option>
              ))}
            </select>
          ) : (
            <span style={{ color: '#aaa', fontSize: 13 }}>{industriesLoading ? 'Loading sectors...' : 'No sectors loaded'}</span>
          )}
        </div>
        <button
          onClick={fetchForecast}
          disabled={loading || industriesLoading || !industry}
          style={{
            padding: '6px 20px',
            background: (!loading && !industriesLoading && industry) ? '#1976d2' : '#ccc',
            color: 'white', border: 'none', borderRadius: 4,
            cursor: (!loading && !industriesLoading && industry) ? 'pointer' : 'not-allowed',
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

      {data?.status === 'ok' && (() => {
        const acc: number = data.top_k_accuracy ?? 0
        const baseline: number = data.baselines?.sector_frequency_top_k ?? 0
        const prediction: { tool: string; count: number }[] = data.prediction || []
        const metrics = data.metrics || {}
        const provenance = data.provenance || {}
        const coverage = data.coverage || {}
        const passes: boolean = data.passes_gate

        const holdoutMatch = (data.gate_note || '').match(/holdout_start=(\d{4}-\d{2}-\d{2})/)
        const holdoutLabel = holdoutMatch
          ? `the held-out test week (from ${holdoutMatch[1]})`
          : 'the held-out test week'

        return (
          <>
            {/* Metric cards */}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
              <div style={{ background: '#e3f2fd', borderRadius: 8, padding: '14px 16px' }}>
                <div style={{ fontSize: 11, color: '#666', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.04em' }}>
                  Prediction accuracy{' '}
                  <InfoTooltip text={`Out of every 10 tools we predicted would target this sector, about ${Math.round(acc * 10)} actually appeared in the test week's threat reports.`} />
                </div>
                <div style={{ fontSize: 28, fontWeight: 700, color: acc > baseline ? '#2e7d32' : '#c62828', marginTop: 4 }}>
                  {(acc * 100).toFixed(1)}%
                </div>
              </div>
              <div style={{ background: '#f3e5f5', borderRadius: 8, padding: '14px 16px' }}>
                <div style={{ fontSize: 11, color: '#666', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.04em' }}>
                  Best simple guess
                </div>
                <div style={{ fontSize: 28, fontWeight: 700, color: '#555', marginTop: 4 }}>
                  {(baseline * 100).toFixed(1)}%
                </div>
                <div style={{ fontSize: 12, color: '#888', marginTop: 2 }}>Just picking the most common tools</div>
              </div>
            </div>

            {/* Directional-only banner */}
            {!passes && (
              <div style={{ padding: '10px 16px', background: '#fff8e1', border: '1px solid #f9a825', borderRadius: 6, fontSize: 13 }}>
                <strong>Directional only</strong> — this model doesn't yet outperform a simple frequency guess on this dataset.
                Predictions show the right direction but should not be treated as firm.
              </div>
            )}

            {/* Top predicted tools */}
            {prediction.length > 0 && (
              <div>
                <h3 style={{ fontSize: 14, marginBottom: 8 }}>
                  Top predicted tools for <em>{industry}</em>
                </h3>
                <ToolChips tools={prediction} />
              </div>
            )}
            {prediction.length === 0 && (
              <p style={{ color: '#888', fontSize: 13 }}>No tool predictions available for <em>{industry}</em> — try a sector with higher coverage.</p>
            )}

            {/* Stacked area trend chart */}
            {trends && <ToolTrendChart data={trends} industry={industry} />}

            {/* Full metrics grid */}
            <MetricsGrid
              metrics={{ ...metrics, baseline_top_k: baseline, lift_over_baseline: acc - baseline }}
              holdoutLabel={holdoutLabel}
            />

            {/* Coverage heatmap */}
            {Object.keys(coverage).length > 0 && (
              <div>
                <h3 style={{ fontSize: 14, marginBottom: 8 }}>Sector coverage (entities extracted)</h3>
                <CooccurrenceHeatmap coverage={coverage} />
              </div>
            )}

            {/* Model provenance */}
            <ModelProvenancePanel provenance={{ ...provenance }} />
          </>
        )
      })()}
    </div>
  )
}

function ToolChips({ tools }: { tools: { tool: string; count: number }[] }) {
  const [descriptions, setDescriptions] = useState<Record<string, string>>({})

  useEffect(() => {
    tools.forEach(({ tool }) => {
      if (descriptions[tool]) return
      fetch(`/api/tool-info?tool=${encodeURIComponent(tool)}`)
        .then(r => r.json())
        .then(d => setDescriptions(prev => ({ ...prev, [tool]: d.description })))
        .catch(() => {})
    })
  }, [tools])

  return (
    <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
      {tools.slice(0, 5).map(({ tool, count }) => (
        <div key={tool} style={{
          padding: '6px 12px', background: '#e3f2fd', borderRadius: 20,
          fontSize: 13, fontWeight: 500, display: 'flex', alignItems: 'center', gap: 6,
        }}>
          {tool} <span style={{ color: '#888', fontWeight: 400 }}>x{count}</span>
          {descriptions[tool] && <InfoTooltip text={descriptions[tool]} />}
        </div>
      ))}
    </div>
  )
}
