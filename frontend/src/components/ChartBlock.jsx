import { useMemo } from 'react'
import { AlertTriangle } from 'lucide-react'
import {
  BarChart, Bar,
  LineChart, Line,
  AreaChart, Area,
  PieChart, Pie, Cell,
  ScatterChart, Scatter,
  Treemap,
  FunnelChart, Funnel, LabelList,
  XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
} from 'recharts'

const XY_TYPES = new Set(['bar', 'line', 'area', 'horizontal_bar', 'scatter'])
const NAME_VALUE_TYPES = new Set(['pie', 'donut', 'treemap', 'funnel'])
const MULTI_SERIES_TYPES = new Set(['stacked_bar', 'grouped_bar', 'stacked_area', 'multi_line'])
const SUPPORTED_TYPES = new Set([...XY_TYPES, ...NAME_VALUE_TYPES, ...MULTI_SERIES_TYPES])

const PALETTE = [
  '#3b82f6', '#22c55e', '#f59e0b', '#ef4444', '#8b5cf6',
  '#06b6d4', '#ec4899', '#84cc16', '#14b8a6', '#f97316',
]
const seriesColor = (i) => PALETTE[i % PALETTE.length]

const formatCompact = (value) => {
  if (value == null || typeof value !== 'number') return value
  const abs = Math.abs(value)
  if (abs >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`
  if (abs >= 1_000) return `${(value / 1_000).toFixed(1)}K`
  return Number.isInteger(value) ? value.toString() : value.toFixed(1)
}

const getFormatter = (spec) =>
  spec?.number_format === 'compact' ? formatCompact : undefined

export { formatCompact }

export const parseSpec = (code) => {
  let parsed
  try {
    parsed = JSON.parse(code)
  } catch (err) {
    return { error: `Invalid chart JSON: ${err.message}` }
  }
  if (!parsed || typeof parsed !== 'object') {
    return { error: 'Chart spec must be a JSON object' }
  }
  if (!SUPPORTED_TYPES.has(parsed.type)) {
    return { error: `Unsupported chart type: ${parsed.type}` }
  }
  if (!Array.isArray(parsed.data) || parsed.data.length === 0) {
    return { error: 'Chart spec is missing a non-empty "data" array' }
  }
  if (MULTI_SERIES_TYPES.has(parsed.type) && (!Array.isArray(parsed.series) || parsed.series.length === 0)) {
    return { error: `Chart type ${parsed.type} requires a non-empty "series" array` }
  }
  return { spec: parsed }
}

const ChartError = ({ message, code }) => (
  <div className="my-3 rounded-lg overflow-hidden border border-amber-200">
    <div className="flex items-center gap-2 px-3 py-1.5 bg-amber-50 border-b border-amber-100 text-xs text-amber-700">
      <AlertTriangle className="w-3.5 h-3.5" />
      <span>chart could not be rendered — {message}</span>
    </div>
    <pre className="p-3 bg-gray-900 text-gray-100 text-xs overflow-x-auto whitespace-pre font-mono leading-relaxed">
      {code}
    </pre>
  </div>
)

const ChartFrame = ({ title, height = 320, children }) => (
  <div className="my-3 rounded-lg overflow-hidden border border-gray-200 bg-white">
    <div className="flex items-center justify-between px-3 py-1.5 bg-gray-100 border-b border-gray-200">
      <span className="text-xs font-medium text-gray-600">{title || 'chart'}</span>
    </div>
    <div className="p-3" style={{ width: '100%', height }}>
      <ResponsiveContainer width="100%" height="100%">
        {children}
      </ResponsiveContainer>
    </div>
  </div>
)

const xLabelProp = (label) =>
  label ? { value: label, position: 'insideBottom', offset: -4 } : undefined
const yLabelProp = (label) =>
  label ? { value: label, angle: -90, position: 'insideLeft' } : undefined

const renderXY = (spec) => {
  const { type, data, x_label, y_label } = spec
  const fmt = getFormatter(spec)
  const longestXLabel = data.reduce((m, d) => Math.max(m, String(d.x ?? '').length), 0)
  const needsRotation = type !== 'horizontal_bar' && type !== 'scatter' && longestXLabel > 10
  const bottomMargin = needsRotation ? 60 : (x_label ? 20 : 5)
  const margin = { top: 10, right: 20, left: 10, bottom: bottomMargin }
  const xTickProps = needsRotation
    ? { fontSize: 11, angle: -45, textAnchor: 'end' }
    : { fontSize: 12 }
  const tooltipFmt = fmt ? { formatter: (v) => fmt(v) } : {}

  const xInterval = data.length > 20 ? Math.ceil(data.length / 15) - 1 : 0

  if (type === 'bar') {
    return (
      <BarChart data={data} margin={margin}>
        <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
        <XAxis dataKey="x" tick={xTickProps} interval={xInterval} label={xLabelProp(x_label)} />
        <YAxis tick={{ fontSize: 12 }} tickFormatter={fmt} label={yLabelProp(y_label)} />
        <Tooltip {...tooltipFmt} />
        <Bar dataKey="y" fill={PALETTE[0]} />
      </BarChart>
    )
  }
  if (type === 'horizontal_bar') {
    const maxLabelLen = data.reduce((m, d) => Math.max(m, String(d.x).length), 0)
    const yWidth = Math.min(220, 8 + maxLabelLen * 6.5)
    return (
      <BarChart data={data} layout="vertical" margin={{ top: 10, right: 20, left: 10, bottom: 5 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
        <XAxis type="number" tick={{ fontSize: 12 }} tickFormatter={fmt} label={xLabelProp(y_label)} />
        <YAxis type="category" dataKey="x" tick={{ fontSize: 12 }} width={yWidth} />
        <Tooltip {...tooltipFmt} />
        <Bar dataKey="y" fill={PALETTE[0]} />
      </BarChart>
    )
  }
  if (type === 'line') {
    return (
      <LineChart data={data} margin={margin}>
        <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
        <XAxis dataKey="x" tick={xTickProps} interval={xInterval} label={xLabelProp(x_label)} />
        <YAxis tick={{ fontSize: 12 }} tickFormatter={fmt} label={yLabelProp(y_label)} />
        <Tooltip {...tooltipFmt} />
        <Line type="monotone" dataKey="y" stroke={PALETTE[0]} strokeWidth={2} dot={false} />
      </LineChart>
    )
  }
  if (type === 'area') {
    return (
      <AreaChart data={data} margin={margin}>
        <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
        <XAxis dataKey="x" tick={xTickProps} interval={xInterval} label={xLabelProp(x_label)} />
        <YAxis tick={{ fontSize: 12 }} tickFormatter={fmt} label={yLabelProp(y_label)} />
        <Tooltip {...tooltipFmt} />
        <Area type="monotone" dataKey="y" stroke={PALETTE[0]} fill={PALETTE[0]} fillOpacity={0.3} />
      </AreaChart>
    )
  }
  // scatter
  return (
    <ScatterChart margin={margin}>
      <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
      <XAxis dataKey="x" type="number" tick={{ fontSize: 12 }} tickFormatter={fmt} label={xLabelProp(x_label)} />
      <YAxis dataKey="y" type="number" tick={{ fontSize: 12 }} tickFormatter={fmt} label={yLabelProp(y_label)} />
      <Tooltip cursor={{ strokeDasharray: '3 3' }} {...tooltipFmt} />
      <Scatter data={data} fill={PALETTE[0]} />
    </ScatterChart>
  )
}

const TreemapContent = ({ x, y, width, height, name, value, fill, index }) => {
  const bg = fill || seriesColor(index || 0)
  if (width < 4 || height < 4) return null
  const fmtVal = typeof value === 'number' ? formatCompact(value) : value
  const showLabel = width >= 40 && height >= 24
  const maxChars = Math.floor(width / 7)
  return (
    <g>
      <rect x={x} y={y} width={width} height={height} fill={bg} stroke="#fff" strokeWidth={2} rx={2} />
      {showLabel && (
        <>
          <text x={x + width / 2} y={y + height / 2 - 7} textAnchor="middle" fill="#fff" fontSize={12} fontWeight={500}>
            {String(name).length > maxChars ? String(name).slice(0, maxChars - 1) + '…' : name}
          </text>
          <text x={x + width / 2} y={y + height / 2 + 9} textAnchor="middle" fill="#ffffffcc" fontSize={11}>
            {fmtVal}
          </text>
        </>
      )}
    </g>
  )
}

const renderNameValue = (spec) => {
  const { type, data } = spec
  const fmt = getFormatter(spec)
  if (type === 'pie' || type === 'donut') {
    const innerRadius = type === 'donut' ? 60 : 0
    const hasMany = data.length > 6
    const labelFn = hasMany
      ? ({ percent }) => percent >= 0.05 ? `${(percent * 100).toFixed(0)}%` : ''
      : ({ name, percent }) => {
          if (percent < 0.05) return ''
          const short = name.length > 18 ? name.slice(0, 16) + '…' : name
          return `${short} ${(percent * 100).toFixed(0)}%`
        }
    return (
      <PieChart margin={{ top: 20, right: 20, bottom: 20, left: 20 }}>
        <Pie
          data={data}
          dataKey="value"
          nameKey="name"
          cx="50%"
          cy="50%"
          outerRadius={hasMany ? 80 : 90}
          innerRadius={innerRadius}
          label={labelFn}
          labelLine={!hasMany}
        >
          {data.map((_, idx) => (
            <Cell key={idx} fill={seriesColor(idx)} />
          ))}
        </Pie>
        <Tooltip formatter={fmt} />
        <Legend wrapperStyle={{ fontSize: 12 }} />
      </PieChart>
    )
  }
  if (type === 'treemap') {
    return (
      <Treemap
        data={data}
        dataKey="value"
        nameKey="name"
        stroke="#fff"
        fill={PALETTE[0]}
        content={<TreemapContent />}
      >
        {data.map((_, idx) => (
          <Cell key={idx} fill={seriesColor(idx)} />
        ))}
      </Treemap>
    )
  }
  // funnel
  return (
    <FunnelChart>
      <Tooltip />
      <Funnel data={data} dataKey="value" nameKey="name" isAnimationActive>
        <LabelList position="right" dataKey="name" />
        {data.map((_, idx) => (
          <Cell key={idx} fill={seriesColor(idx)} />
        ))}
      </Funnel>
    </FunnelChart>
  )
}

const renderMultiSeries = (spec) => {
  const { type, data, series, x_label, y_label } = spec
  const fmt = getFormatter(spec)
  const seriesKeys = series.map((s) => (typeof s === 'string' ? s : s.key))
  const seriesLabel = (s, i) => (typeof series[i] === 'string' ? s : series[i].label || s)
  const longestXLabel = data.reduce((m, d) => Math.max(m, String(d.x ?? '').length), 0)
  const needsRotation = longestXLabel > 10
  const bottomMargin = needsRotation ? 60 : (x_label ? 20 : 5)
  const margin = { top: 10, right: 20, left: 10, bottom: bottomMargin }
  const xTickProps = needsRotation
    ? { fontSize: 11, angle: -45, textAnchor: 'end' }
    : { fontSize: 12 }
  const tooltipFmt = fmt ? { formatter: (v) => fmt(v) } : {}

  const xInterval = data.length > 20 ? Math.ceil(data.length / 15) - 1 : 0

  if (type === 'stacked_bar' || type === 'grouped_bar') {
    const stackProps = type === 'stacked_bar' ? { stackId: 'a' } : {}
    return (
      <BarChart data={data} margin={margin}>
        <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
        <XAxis dataKey="x" tick={xTickProps} interval={xInterval} label={xLabelProp(x_label)} />
        <YAxis tick={{ fontSize: 12 }} tickFormatter={fmt} label={yLabelProp(y_label)} />
        <Tooltip {...tooltipFmt} />
        <Legend />
        {seriesKeys.map((key, i) => (
          <Bar key={key} dataKey={key} name={seriesLabel(key, i)} fill={seriesColor(i)} {...stackProps} />
        ))}
      </BarChart>
    )
  }
  if (type === 'stacked_area') {
    return (
      <AreaChart data={data} margin={margin}>
        <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
        <XAxis dataKey="x" tick={xTickProps} interval={xInterval} label={xLabelProp(x_label)} />
        <YAxis tick={{ fontSize: 12 }} tickFormatter={fmt} label={yLabelProp(y_label)} />
        <Tooltip {...tooltipFmt} />
        <Legend />
        {seriesKeys.map((key, i) => (
          <Area
            key={key}
            type="monotone"
            dataKey={key}
            name={seriesLabel(key, i)}
            stackId="a"
            stroke={seriesColor(i)}
            fill={seriesColor(i)}
            fillOpacity={0.6}
          />
        ))}
      </AreaChart>
    )
  }
  // multi_line
  return (
    <LineChart data={data} margin={margin}>
      <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
      <XAxis dataKey="x" tick={xTickProps} interval={xInterval} label={xLabelProp(x_label)} />
      <YAxis tick={{ fontSize: 12 }} tickFormatter={fmt} label={yLabelProp(y_label)} />
      <Tooltip {...tooltipFmt} />
      <Legend />
      {seriesKeys.map((key, i) => (
        <Line
          key={key}
          type="monotone"
          dataKey={key}
          name={seriesLabel(key, i)}
          stroke={seriesColor(i)}
          strokeWidth={2}
          dot={false}
        />
      ))}
    </LineChart>
  )
}

const renderChart = (spec) => {
  if (XY_TYPES.has(spec.type)) return renderXY(spec)
  if (NAME_VALUE_TYPES.has(spec.type)) return renderNameValue(spec)
  return renderMultiSeries(spec)
}

const frameHeight = (type, dataLen) => {
  if (type === 'horizontal_bar') return Math.min(700, Math.max(220, 28 * dataLen + 60))
  if (type === 'pie' || type === 'donut') return dataLen > 6 ? 420 : 380
  if (type === 'treemap') return Math.min(500, Math.max(360, 20 * dataLen))
  if (type === 'funnel') return 360
  if (dataLen > 15) return 400
  return 320
}

const ChartBlock = ({ code }) => {
  const parsed = useMemo(() => parseSpec(code), [code])

  if (parsed.error) {
    return <ChartError message={parsed.error} code={code} />
  }

  const { spec } = parsed
  return (
    <ChartFrame title={spec.title} height={frameHeight(spec.type, spec.data.length)}>
      {renderChart(spec)}
    </ChartFrame>
  )
}

export default ChartBlock
