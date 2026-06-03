import React, { useState } from 'react'

interface Provenance {
  model_type?: string
  extraction_model?: string
  feature_tier?: string
  train_rows?: number | null
  holdout_rows?: number | null
  industries_evaluated?: number | null
  aql_port_idiom?: string
}

interface Props { provenance: Provenance }

export default function ModelProvenancePanel({ provenance }: Props) {
  const [open, setOpen] = useState(false)

  return (
    <div style={{ marginTop: 8 }}>
      <button
        onClick={() => setOpen(o => !o)}
        style={{
          background: 'none', border: '1px solid #ddd', borderRadius: 4,
          padding: '4px 12px', fontSize: 12, cursor: 'pointer', color: '#555',
        }}
      >
        {open ? '▲' : '▼'} Model details
      </button>
      {open && (
        <div style={{
          marginTop: 8, padding: 14, background: '#fafafa',
          border: '1px solid #eee', borderRadius: 6, fontSize: 13,
        }}>
          <table style={{ borderCollapse: 'collapse', width: '100%' }}>
            <tbody>
              {[
                ['Model type', provenance.model_type],
                ['Features extracted by', provenance.extraction_model],
                ['Feature data tier', provenance.feature_tier],
                ['Training data', provenance.train_rows != null ? `${provenance.train_rows.toLocaleString()} entity-sector-tool rows` : null],
                ['Test data (holdout)', provenance.holdout_rows != null ? `${provenance.holdout_rows.toLocaleString()} rows (final week)` : null],
                ['Sectors evaluated', provenance.industries_evaluated != null ? `${provenance.industries_evaluated} sectors` : null],
              ].filter(([, v]) => v).map(([label, value]) => (
                <tr key={label as string}>
                  <td style={{ color: '#888', paddingRight: 16, paddingBottom: 6, verticalAlign: 'top', whiteSpace: 'nowrap' }}>
                    {label}
                  </td>
                  <td style={{ paddingBottom: 6, color: '#333' }}>{value}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {provenance.aql_port_idiom && (
            <details style={{ marginTop: 8 }}>
              <summary style={{ cursor: 'pointer', color: '#888', fontSize: 12 }}>
                AQL port idiom (engineering reference)
              </summary>
              <pre style={{ marginTop: 4, background: '#f0f0f0', padding: 8, borderRadius: 4, fontSize: 11, overflow: 'auto' }}>
                {provenance.aql_port_idiom}
              </pre>
            </details>
          )}
        </div>
      )}
    </div>
  )
}
