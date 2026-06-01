import React from 'react'
import { LineChart, Line, XAxis, YAxis, Tooltip, CartesianGrid, ReferenceLine } from 'recharts'

interface Props {
  data: { date: string; value: number }[]
  forecastStart?: string
}

export default function TimeSeriesGraph({ data, forecastStart }: Props) {
  return (
    <div>
      <h3 style={{ fontSize: 14, marginBottom: 8 }}>Trend + Forecast</h3>
      <LineChart width={600} height={280} data={data}>
        <CartesianGrid strokeDasharray="3 3" />
        <XAxis dataKey="date" />
        <YAxis />
        <Tooltip />
        <Line type="monotone" dataKey="value" stroke="#1976d2" dot={false} />
        {forecastStart && <ReferenceLine x={forecastStart} stroke="#ef6c00" strokeDasharray="4 4" label="Forecast" />}
      </LineChart>
    </div>
  )
}
