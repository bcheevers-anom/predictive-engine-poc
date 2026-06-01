import React from 'react'

interface Props { ece?: number }

export default function CalibrationCurve({ ece }: Props) {
  return (
    <div style={{ padding: '8px 16px', background: '#f5f5f5', borderRadius: 4, fontSize: 13 }}>
      Calibration ECE: {ece != null ? ece.toFixed(3) : 'not available'}
      {ece != null && ece < 0.1 && ' (well-calibrated)'}
      {ece != null && ece >= 0.1 && ' (moderate calibration error)'}
    </div>
  )
}
