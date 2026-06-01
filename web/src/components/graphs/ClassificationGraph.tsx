import React from 'react'
import { BarChart, Bar, XAxis, YAxis, Tooltip, CartesianGrid } from 'recharts'

interface Props {
  data: { tool?: string; count?: number }[]
}

export default function ClassificationGraph({ data }: Props) {
  const chartData = data.map(d => ({ name: d.tool || '', count: d.count || 0 }))
  return (
    <div>
      <h3 style={{ fontSize: 14, marginBottom: 8 }}>Predicted Top Tools / Tactics</h3>
      <BarChart width={500} height={250} data={chartData}>
        <CartesianGrid strokeDasharray="3 3" />
        <XAxis dataKey="name" />
        <YAxis />
        <Tooltip />
        <Bar dataKey="count" fill="#e53935" />
      </BarChart>
    </div>
  )
}
