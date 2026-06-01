import React from 'react'
import { BarChart, Bar, XAxis, YAxis, Tooltip } from 'recharts'

interface Props {
  contributions: { feature: string; importance: number; normalised: number }[]
}

export default function FeatureContributions({ contributions }: Props) {
  return (
    <div>
      <h3 style={{ fontSize: 14, marginBottom: 8 }}>Feature Contributions</h3>
      <BarChart width={400} height={200} data={contributions} layout="vertical">
        <XAxis type="number" domain={[0, 1]} tickFormatter={(v: number) => `${(v * 100).toFixed(0)}%`} />
        <YAxis type="category" dataKey="feature" width={120} />
        <Tooltip formatter={(v: number) => `${(v * 100).toFixed(1)}%`} />
        <Bar dataKey="normalised" fill="#1976d2" />
      </BarChart>
    </div>
  )
}
