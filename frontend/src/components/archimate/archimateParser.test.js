/**
 * Unit tests for the ArchiMate parser, layout, and SVG renderer.
 *
 * Covers AC3 from the Archimate-end-to-end story:
 *   "TD-viewer rendert de ArchiMate-blocks als interactieve SVG, zowel
 *    voor views met bestaande geometrie (WILMA) als voor nieuw gegenereerde
 *    views (auto-layout via ELK)."
 */

import { describe, it, expect, beforeAll } from 'vitest'
import { JSDOM } from 'jsdom'
import {
  parseEmbedSpec,
  parseArchimateXML,
  viewHasGeometry,
  computeLayout,
  renderViewToSVG,
  LAYER_COLORS,
} from './archimateParser'

beforeAll(() => {
  // archimateParser relies on the global DOMParser. Vitest's jsdom
  // environment provides one when configured, but make explicit here
  // so the test is robust to environment changes.
  if (typeof globalThis.DOMParser === 'undefined') {
    globalThis.DOMParser = new JSDOM().window.DOMParser
  }
})

const SAMPLE_XML_WITH_GEOMETRY = `<?xml version="1.0" encoding="UTF-8"?>
<model xmlns="http://www.opengroup.org/xsd/archimate/3.0/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" identifier="id-test">
  <name xml:lang="en">Test</name>
  <elements>
    <element identifier="el-1" xsi:type="BusinessActor"><name xml:lang="en">Customer</name></element>
    <element identifier="el-2" xsi:type="ApplicationComponent"><name xml:lang="en">Portal</name></element>
    <element identifier="el-3" xsi:type="DataObject"><name xml:lang="en">Customer Data</name></element>
  </elements>
  <relationships>
    <relationship identifier="r-1" source="el-2" target="el-1" xsi:type="Serving"/>
    <relationship identifier="r-2" source="el-2" target="el-3" xsi:type="Access"/>
  </relationships>
  <views>
    <diagrams>
      <view identifier="v-1" xsi:type="Diagram">
        <name xml:lang="en">Context</name>
        <node identifier="n-1" elementRef="el-1" x="100" y="50" w="120" h="55"/>
        <node identifier="n-2" elementRef="el-2" x="320" y="50" w="120" h="55"/>
        <node identifier="n-3" elementRef="el-3" x="320" y="200" w="120" h="55"/>
        <connection identifier="c-1" relationshipRef="r-1" source="n-2" target="n-1"/>
        <connection identifier="c-2" relationshipRef="r-2" source="n-2" target="n-3"/>
      </view>
    </diagrams>
  </views>
</model>`

const SAMPLE_XML_NO_GEOMETRY = `<?xml version="1.0" encoding="UTF-8"?>
<model xmlns="http://www.opengroup.org/xsd/archimate/3.0/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <name xml:lang="en">Auto</name>
  <elements>
    <element identifier="el-1" xsi:type="BusinessActor"><name xml:lang="en">A</name></element>
    <element identifier="el-2" xsi:type="ApplicationComponent"><name xml:lang="en">B</name></element>
  </elements>
  <relationships>
    <relationship identifier="r-1" source="el-2" target="el-1" xsi:type="Serving"/>
  </relationships>
  <views>
    <diagrams>
      <view identifier="v-1" xsi:type="Diagram">
        <name xml:lang="en">Auto</name>
        <node identifier="n-1" elementRef="el-1" x="0" y="0" w="0" h="0"/>
        <node identifier="n-2" elementRef="el-2" x="0" y="0" w="0" h="0"/>
        <connection identifier="c-1" relationshipRef="r-1" source="n-2" target="n-1"/>
      </view>
    </diagrams>
  </views>
</model>`

describe('parseEmbedSpec', () => {
  it('parses a well-formed view-id + file block', () => {
    const spec = parseEmbedSpec('view-id: abc-123\nfile: docs/architecture.archimate')
    expect(spec).toEqual({ viewId: 'abc-123', file: 'docs/architecture.archimate' })
  })

  it('tolerates extra whitespace and key=value form', () => {
    const spec = parseEmbedSpec('  view-id  =  abc-123  \n  file  :  docs/a.archimate  ')
    expect(spec.viewId).toBe('abc-123')
    expect(spec.file).toBe('docs/a.archimate')
  })

  it('defaults file when only view-id is present', () => {
    const spec = parseEmbedSpec('view-id: abc-123')
    expect(spec.file).toBe('docs/architecture.archimate')
  })

  it('returns null when view-id is missing', () => {
    expect(parseEmbedSpec('file: docs/architecture.archimate')).toBeNull()
    expect(parseEmbedSpec('')).toBeNull()
    expect(parseEmbedSpec(null)).toBeNull()
  })
})

describe('parseArchimateXML', () => {
  it('parses elements, relationships, and views from Open Exchange XML', () => {
    const model = parseArchimateXML(SAMPLE_XML_WITH_GEOMETRY)
    expect(model.elements.size).toBe(3)
    expect(model.relationships.size).toBe(2)
    expect(model.views.size).toBe(1)

    const customer = model.elements.get('el-1')
    expect(customer.name).toBe('Customer')
    expect(customer.type).toBe('BusinessActor')
    expect(customer.layer).toBe('Business')

    const portal = model.elements.get('el-2')
    expect(portal.layer).toBe('Application')

    const view = model.views.get('v-1')
    expect(view.name).toBe('Context')
    expect(view.nodes).toHaveLength(3)
    expect(view.connections).toHaveLength(2)
    expect(view.nodes[0]).toMatchObject({ x: 100, y: 50, w: 120, h: 55 })
  })

  it('throws a clear error on invalid XML', () => {
    expect(() => parseArchimateXML('not xml at all')).toThrow(/Invalid ArchiMate XML|Expected <model>/)
  })
})

describe('viewHasGeometry', () => {
  it('returns true for views with non-zero coordinates', () => {
    const model = parseArchimateXML(SAMPLE_XML_WITH_GEOMETRY)
    expect(viewHasGeometry(model.views.get('v-1'))).toBe(true)
  })

  it('returns false for views with all-zero coordinates', () => {
    const model = parseArchimateXML(SAMPLE_XML_NO_GEOMETRY)
    expect(viewHasGeometry(model.views.get('v-1'))).toBe(false)
  })
})

describe('computeLayout', () => {
  it('passes a fully-positioned view through unchanged', async () => {
    const model = parseArchimateXML(SAMPLE_XML_WITH_GEOMETRY)
    const view = model.views.get('v-1')
    const originalPositions = view.nodes.map((n) => ({ id: n.id, x: n.x, y: n.y }))

    const laidOut = await computeLayout(view)
    for (const original of originalPositions) {
      const after = laidOut.nodes.find((n) => n.id === original.id)
      expect(after.x).toBe(original.x)
      expect(after.y).toBe(original.y)
    }
  })

  it('computes fresh coordinates for a view without geometry (AC3)', async () => {
    const model = parseArchimateXML(SAMPLE_XML_NO_GEOMETRY)
    const view = model.views.get('v-1')
    const laidOut = await computeLayout(view)
    expect(laidOut._layoutComputed).toBe(true)
    // After layout, both nodes must have non-zero positions and non-zero size
    for (const n of laidOut.nodes) {
      expect(n.w).toBeGreaterThan(0)
      expect(n.h).toBeGreaterThan(0)
      // ELK places at least one node away from (0,0) — the cluster should
      // not collapse on the origin.
    }
    const distinctPositions = new Set(laidOut.nodes.map((n) => `${n.x},${n.y}`))
    expect(distinctPositions.size).toBe(laidOut.nodes.length)
  })
})

describe('renderViewToSVG', () => {
  it('renders element names and layer colors', () => {
    const model = parseArchimateXML(SAMPLE_XML_WITH_GEOMETRY)
    const view = model.views.get('v-1')
    const svg = renderViewToSVG(view, model)

    expect(svg).toContain('<svg ')
    expect(svg).toContain('Customer')
    expect(svg).toContain('Portal')
    expect(svg).toContain('Customer Data')
    // Layer colors for Business and Application must appear
    expect(svg).toContain(LAYER_COLORS.Business)
    expect(svg).toContain(LAYER_COLORS.Application)
    // Marker definitions
    expect(svg).toMatch(/marker-end="url\(#am-[^"]+-arrow-/)
  })

  it('applies delta-highlight accent to identifiers in highlightIds (task #16)', () => {
    const model = parseArchimateXML(SAMPLE_XML_WITH_GEOMETRY)
    const view = model.views.get('v-1')
    const svg = renderViewToSVG(view, model, {
      highlightIds: new Set(['el-2']),  // pretend "Portal" was just added
    })
    // Accent stroke color = #1d4ed8 (Tailwind blue-700)
    expect(svg).toContain('#1d4ed8')
    // A bare render without highlights does not contain that color
    const plain = renderViewToSVG(view, model)
    expect(plain).not.toContain('#1d4ed8')
  })

  it('renders an empty-view placeholder when there are no elements', () => {
    const xml = SAMPLE_XML_WITH_GEOMETRY.replace(/<node[^/]*\/>/g, '').replace(/<connection[^/]*\/>/g, '')
    const model = parseArchimateXML(xml)
    const view = model.views.get('v-1')
    const svg = renderViewToSVG(view, model)
    expect(svg).toContain('View has no elements')
  })
})
