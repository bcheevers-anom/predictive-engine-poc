import React from 'react'
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip,
  Legend, ReferenceLine, ResponsiveContainer,
} from 'recharts'
import { TrendsResponse } from '../../types/api'

const COLOURS = ['#1976d2', '#e53935', '#388e3c', '#f57c00', '#7b1fa2']

interface Props {
  data: TrendsResponse
  industry: string
}

export default function ToolTrendChart({ data, industry }: Props) {
  if (!data.weeks.length || !data.series.length) {
    return <p style={{ color: '#aaa', fontSize: 13 }}>No trend data available for {industry}.</p>
  }

  const chartData = data.weeks.map((week, i) => {
    const row: Record<string, string | number> = { week }
    data.series.forEach(s => { row[s.tool] = s.counts[i] ?? 0 })
    return row
  })

  return (
    <div>
      <h3 style={{ fontSize: 14, marginBottom: 4 }}>
        Tool activity — {industry}
      </h3>
      <p style={{ fontSize: 12, color: '#888', marginBottom: 8 }}>
        Each area shows how often a tool appeared in threat reports per week.
        {data.holdout_start && (
          <span> The shaded region (from {data.holdout_start}) is the <strong>held-out test week</strong> — data the model never saw during training.</span>
        )}
      </p>
      <ResponsiveContainer width="100%" height={240}>
        <AreaChart data={chartData} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
          <XAxis dataKey="week" tick={{ fontSize: 11 }} />
          <YAxis tick={{ fontSize: 11 }} />
          <Tooltip
            formatter={(value: number, name: string) => [`${value} reports`, name]}
            labelFormatter={(label) => `Week of ${label}`}
          />
          <Legend wrapperStyle={{ fontSize: 12 }} />
          {data.holdout_start && (
            <ReferenceLine
              x={data.holdout_start}
              stroke="#f44336"
              strokeDasharray="4 4"
              label={{ value: 'Holdout', fontSize: 11, fill: '#f44336' }}
            />
          )}
          {data.series.map((s, i) => (
            <Area
              key={s.tool}
              type="monotone"
              dataKey={s.tool}
              stackId="1"
              stroke={COLOURS[i % COLOURS.length]}
              fill={COLOURS[i % COLOURS.length]}
              fillOpacity={0.6}
            />
          ))}
        </AreaChart>
      </ResponsiveContainer>
    </div>
  )
}
