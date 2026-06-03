import { describe, it, expect, beforeAll } from 'vitest'
import { render } from '@testing-library/react'
import ChartBlock, { parseSpec } from './ChartBlock'

// recharts ResponsiveContainer depends on ResizeObserver, which jsdom does not
// provide. A no-op shim is enough for the smoke checks we do below — we don't
// need to assert on the SVG contents, only that the chart frame renders.
beforeAll(() => {
  if (typeof globalThis.ResizeObserver === 'undefined') {
    globalThis.ResizeObserver = class {
      observe() {}
      unobserve() {}
      disconnect() {}
    }
  }
})

describe('parseSpec', () => {
  it('parses a valid bar chart spec', () => {
    const code = JSON.stringify({
      type: 'bar',
      title: 'Sales',
      data: [{ x: 'A', y: 10 }, { x: 'B', y: 20 }],
    })
    const result = parseSpec(code)
    expect(result.error).toBeUndefined()
    expect(result.spec.type).toBe('bar')
    expect(result.spec.data).toHaveLength(2)
  })

  it('returns an error for malformed JSON', () => {
    const result = parseSpec('not json')
    expect(result.error).toMatch(/Invalid chart JSON/)
  })

  it('returns an error for unsupported chart type', () => {
    const code = JSON.stringify({ type: 'histogram', data: [{ x: 1, y: 1 }] })
    const result = parseSpec(code)
    expect(result.error).toMatch(/Unsupported chart type: histogram/)
  })

  it('returns an error when data is missing', () => {
    const code = JSON.stringify({ type: 'bar', title: 'oops' })
    const result = parseSpec(code)
    expect(result.error).toMatch(/non-empty "data" array/)
  })

  it('returns an error when data is empty', () => {
    const code = JSON.stringify({ type: 'bar', data: [] })
    const result = parseSpec(code)
    expect(result.error).toMatch(/non-empty "data" array/)
  })

  it('accepts every single-series chart type', () => {
    const types = ['bar', 'line', 'area', 'horizontal_bar', 'scatter', 'pie', 'donut', 'treemap', 'funnel']
    for (const type of types) {
      const code = JSON.stringify({ type, data: [{ x: 1, y: 2, name: 'x', value: 2 }] })
      const result = parseSpec(code)
      expect(result.error, `type=${type}`).toBeUndefined()
    }
  })

  it('requires non-empty series for multi-series chart types', () => {
    const code = JSON.stringify({
      type: 'stacked_bar',
      data: [{ x: 'A', Q1: 1, Q2: 2 }],
    })
    const result = parseSpec(code)
    expect(result.error).toMatch(/requires a non-empty "series" array/)
  })

  it('accepts multi-series chart types with valid series', () => {
    const types = ['stacked_bar', 'grouped_bar', 'stacked_area', 'multi_line']
    for (const type of types) {
      const code = JSON.stringify({
        type,
        series: [{ key: 'Q1', label: 'Q1' }, { key: 'Q2', label: 'Q2' }],
        data: [{ x: 'A', Q1: 1, Q2: 2 }],
      })
      const result = parseSpec(code)
      expect(result.error, `type=${type}`).toBeUndefined()
    }
  })
})

describe('ChartBlock', () => {
  it('renders the error UI for malformed JSON without crashing', () => {
    const { getByText, container } = render(<ChartBlock code="not json" />)
    expect(getByText(/chart could not be rendered/i)).toBeTruthy()
    // The raw code should be shown so the user/agent can debug
    expect(container.textContent).toContain('not json')
  })

  it('renders the error UI for unsupported chart type', () => {
    const code = JSON.stringify({ type: 'mystery', data: [{ x: 1, y: 1 }] })
    const { getByText } = render(<ChartBlock code={code} />)
    expect(getByText(/Unsupported chart type: mystery/i)).toBeTruthy()
  })

  it('renders the chart frame with title for a valid spec', () => {
    const code = JSON.stringify({
      type: 'bar',
      title: 'Quarterly revenue',
      data: [{ x: 'Q1', y: 100 }, { x: 'Q2', y: 150 }],
    })
    const { getByText } = render(<ChartBlock code={code} />)
    expect(getByText('Quarterly revenue')).toBeTruthy()
  })

  it('falls back to a default label when title is empty', () => {
    const code = JSON.stringify({
      type: 'line',
      data: [{ x: 1, y: 1 }, { x: 2, y: 4 }],
    })
    const { getByText } = render(<ChartBlock code={code} />)
    expect(getByText('chart')).toBeTruthy()
  })

  it('renders horizontal_bar without crashing', () => {
    const code = JSON.stringify({
      type: 'horizontal_bar',
      title: 'Top categories',
      data: [{ x: 'Very long Dutch category name', y: 9230 }, { x: 'Short', y: 100 }],
    })
    const { getByText } = render(<ChartBlock code={code} />)
    expect(getByText('Top categories')).toBeTruthy()
  })

  it('renders treemap without crashing', () => {
    const code = JSON.stringify({
      type: 'treemap',
      title: 'Distribution',
      data: [{ name: 'A', value: 100 }, { name: 'B', value: 50 }],
    })
    const { getByText } = render(<ChartBlock code={code} />)
    expect(getByText('Distribution')).toBeTruthy()
  })

  it('renders stacked_bar with multiple series', () => {
    const code = JSON.stringify({
      type: 'stacked_bar',
      title: 'Sales by quarter',
      series: [
        { key: 'Q1', label: 'Q1' },
        { key: 'Q2', label: 'Q2' },
      ],
      data: [
        { x: 'A', Q1: 10, Q2: 15 },
        { x: 'B', Q1: 5, Q2: 8 },
      ],
    })
    const { getByText } = render(<ChartBlock code={code} />)
    expect(getByText('Sales by quarter')).toBeTruthy()
  })

  it('renders multi_line', () => {
    const code = JSON.stringify({
      type: 'multi_line',
      title: 'Trend',
      series: [{ key: 'a', label: 'A' }, { key: 'b', label: 'B' }],
      data: [
        { x: 1, a: 5, b: 8 },
        { x: 2, a: 6, b: 7 },
      ],
    })
    const { getByText } = render(<ChartBlock code={code} />)
    expect(getByText('Trend')).toBeTruthy()
  })
})
