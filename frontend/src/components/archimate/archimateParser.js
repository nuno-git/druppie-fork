/**
 * ArchiMate Open Exchange XML parser and renderer helpers.
 *
 * Pure functions only — no React, no DOM beyond DOMParser. Keeps the
 * ArchimateBlock component focused on lifecycle and lets us unit-test
 * the parsing / layout / SVG logic in isolation.
 */

const ARCHIMATE_NS = 'http://www.opengroup.org/xsd/archimate/3.0/'
const XSI_NS = 'http://www.w3.org/2001/XMLSchema-instance'

// --- Layer colors (Open Group standard with slight contrast tuning) ---
export const LAYER_COLORS = {
  Business: '#FFFFB5',
  Application: '#B5FFFF',
  Technology: '#C9E7B7',
  Motivation: '#CCCCFF',
  Strategy: '#F5DEAA',
  Implementation: '#FFE0E0',
  Physical: '#C9E7B7',
  Other: '#F0F0F0',
  Unknown: '#FFFFFF',
}

// --- Layer letter (Wierda / Open Group convention) ---
// Single-letter badge in the top-right corner so the reader can identify
// the layer without relying solely on colour. Replaces the old 4-char
// truncated type-name ("Acto" / "Inte" / "Comp") which was unreadable.
export const LAYER_LETTER = {
  Business: 'B',
  Application: 'A',
  Technology: 'T',
  Motivation: 'M',
  Strategy: 'S',
  Implementation: 'I',
  Physical: 'P',
}

// --- Element type → layer (must match writer.py / module.py LAYER_MAP) ---
export const ELEMENT_LAYER = {
  // Business
  BusinessActor: 'Business', BusinessRole: 'Business', BusinessCollaboration: 'Business',
  BusinessInterface: 'Business', BusinessProcess: 'Business', BusinessFunction: 'Business',
  BusinessInteraction: 'Business', BusinessEvent: 'Business', BusinessService: 'Business',
  BusinessObject: 'Business', Contract: 'Business', Representation: 'Business', Product: 'Business',
  // Application
  ApplicationComponent: 'Application', ApplicationCollaboration: 'Application',
  ApplicationInterface: 'Application', ApplicationFunction: 'Application',
  ApplicationInteraction: 'Application', ApplicationProcess: 'Application',
  ApplicationEvent: 'Application', ApplicationService: 'Application', DataObject: 'Application',
  // Technology
  Node: 'Technology', Device: 'Technology', SystemSoftware: 'Technology',
  TechnologyCollaboration: 'Technology', TechnologyInterface: 'Technology', Path: 'Technology',
  CommunicationNetwork: 'Technology', TechnologyFunction: 'Technology',
  TechnologyProcess: 'Technology', TechnologyInteraction: 'Technology',
  TechnologyEvent: 'Technology', TechnologyService: 'Technology', Artifact: 'Technology',
  // Motivation
  Stakeholder: 'Motivation', Driver: 'Motivation', Assessment: 'Motivation',
  Goal: 'Motivation', Outcome: 'Motivation', Principle: 'Motivation',
  Requirement: 'Motivation', Constraint: 'Motivation', Meaning: 'Motivation', Value: 'Motivation',
  // Strategy
  Capability: 'Strategy', Resource: 'Strategy', CourseOfAction: 'Strategy', ValueStream: 'Strategy',
  // Implementation & Migration
  WorkPackage: 'Implementation', Deliverable: 'Implementation',
  ImplementationEvent: 'Implementation', Plateau: 'Implementation', Gap: 'Implementation',
  // Physical
  Equipment: 'Physical', Facility: 'Physical', DistributionNetwork: 'Physical', Material: 'Physical',
  // Other
  Grouping: 'Other', Location: 'Other', Junction: 'Other',
}

// --- Connection visual style per relationship type ---
export const CONNECTION_STYLE = {
  Composition:    { line: 'solid',  startMarker: 'diamond-filled', endMarker: null },
  Aggregation:    { line: 'solid',  startMarker: 'diamond-open',   endMarker: null },
  Assignment:     { line: 'solid',  startMarker: 'circle-filled',  endMarker: 'circle-filled' },
  Realization:    { line: 'dashed', startMarker: null,             endMarker: 'triangle-open' },
  Serving:        { line: 'solid',  startMarker: null,             endMarker: 'arrow-open' },
  Access:         { line: 'dashed', startMarker: null,             endMarker: 'arrow-filled' },
  Triggering:     { line: 'solid',  startMarker: null,             endMarker: 'arrow-filled' },
  Flow:           { line: 'dashed', startMarker: null,             endMarker: 'arrow-filled' },
  Specialization: { line: 'solid',  startMarker: null,             endMarker: 'triangle-open' },
  Influence:      { line: 'dashed', startMarker: null,             endMarker: 'arrow-open' },
  Association:    { line: 'solid',  startMarker: null,             endMarker: null },
}

// --- Spec parsing -----------------------------------------------------------

/**
 * Parse the body of a ```archimate code-block.
 *
 * Expected format (Q4 decision: View-ID referentie):
 *
 *     view-id: <uuid>
 *     file: docs/architecture.archimate
 *
 * Whitespace tolerant, key order flexible. Returns null on missing view-id.
 */
export function parseEmbedSpec(code) {
  if (!code) return null
  const spec = {}
  for (const line of code.split('\n')) {
    const m = /^\s*([a-zA-Z_-]+)\s*[:=]\s*(.+?)\s*$/.exec(line)
    if (!m) continue
    spec[m[1].trim().toLowerCase()] = m[2].trim()
  }
  if (!spec['view-id']) return null
  return {
    viewId: spec['view-id'],
    file: spec.file || 'docs/architecture.archimate',
  }
}

// --- XML parsing ------------------------------------------------------------

function attr(el, name, ns = null) {
  return ns ? el.getAttributeNS(ns, name) : el.getAttribute(name)
}

function findLocal(parent, localName) {
  for (const child of parent.children) {
    if (child.localName === localName) return child
  }
  return null
}

function findAllLocal(parent, localName) {
  const out = []
  for (const child of parent.children) {
    if (child.localName === localName) out.push(child)
  }
  return out
}

function textOf(parent, localName) {
  const node = findLocal(parent, localName)
  return node && node.textContent ? node.textContent.trim() : ''
}

/**
 * Parse an ArchiMate Open Exchange XML string into a normalized model.
 *
 * Returns { elements: Map<id, {type,name,layer}>,
 *           relationships: Map<id, {type,source,target,name,accessType}>,
 *           views: Map<id, {name, nodes: [...], connections: [...]}> }.
 *
 * Throws on malformed input.
 */
export function parseArchimateXML(xmlString) {
  const doc = new DOMParser().parseFromString(xmlString, 'application/xml')
  const parserError = doc.querySelector('parsererror')
  if (parserError) throw new Error('Invalid ArchiMate XML: ' + parserError.textContent.trim())

  const root = doc.documentElement
  if (!root || root.localName !== 'model') {
    throw new Error('Expected <model> root element, got <' + (root?.localName || 'null') + '>')
  }

  const elements = new Map()
  const elsSection = findLocal(root, 'elements')
  if (elsSection) {
    for (const el of findAllLocal(elsSection, 'element')) {
      const id = attr(el, 'identifier')
      const type = attr(el, 'type', XSI_NS) || 'Unknown'
      elements.set(id, {
        id,
        type,
        name: textOf(el, 'name'),
        layer: ELEMENT_LAYER[type] || 'Unknown',
      })
    }
  }

  const relationships = new Map()
  const relsSection = findLocal(root, 'relationships')
  if (relsSection) {
    for (const rel of findAllLocal(relsSection, 'relationship')) {
      const id = attr(rel, 'identifier')
      relationships.set(id, {
        id,
        type: attr(rel, 'type', XSI_NS) || 'Unknown',
        source: attr(rel, 'source'),
        target: attr(rel, 'target'),
        accessType: attr(rel, 'accessType'),
        name: textOf(rel, 'name'),
      })
    }
  }

  const views = new Map()
  const viewsSection = findLocal(root, 'views')
  if (viewsSection) {
    const diagrams = findLocal(viewsSection, 'diagrams')
    if (diagrams) {
      for (const view of findAllLocal(diagrams, 'view')) {
        const id = attr(view, 'identifier')
        const nodes = []
        const connections = []
        for (const n of findAllLocal(view, 'node')) {
          nodes.push({
            id: attr(n, 'identifier'),
            elementRef: attr(n, 'elementRef'),
            x: parseInt(attr(n, 'x') || '0', 10),
            y: parseInt(attr(n, 'y') || '0', 10),
            w: parseInt(attr(n, 'w') || '120', 10),
            h: parseInt(attr(n, 'h') || '55', 10),
          })
        }
        for (const c of findAllLocal(view, 'connection')) {
          connections.push({
            id: attr(c, 'identifier'),
            relationshipRef: attr(c, 'relationshipRef'),
            source: attr(c, 'source'),
            target: attr(c, 'target'),
          })
        }
        views.set(id, {
          id,
          name: textOf(view, 'name'),
          documentation: textOf(view, 'documentation'),
          nodes,
          connections,
        })
      }
    }
  }

  return { elements, relationships, views }
}

// --- Auto-layout via elkjs --------------------------------------------------

/**
 * Returns true when at least one node has a non-zero (x, y) — used as a
 * cheap signal for "view has geometry, render directly".
 */
export function viewHasGeometry(view) {
  return view.nodes.some((n) => (n.x > 0 || n.y > 0) && (n.w > 0 && n.h > 0))
}

/**
 * Compute auto-layout for a view that lacks geometry. In the current
 * pipeline the server-side layout-service runs on every save_model, so
 * positions are present in the .archimate XML the browser fetches and
 * this short-circuit is the hot path. The in-browser elkjs path stays
 * as a fallback for legacy files written before layout-service existed,
 * and for any view where the server fallback (layout-service down)
 * left some nodes at (0, 0).
 *
 * Pre-existing positions are honored — nodes with valid (x, y, w, h)
 * are pinned via 'org.eclipse.elk.position'. New nodes get fresh
 * coordinates.
 *
 * Returns a new view object with updated coordinates; does not mutate.
 */
export async function computeLayout(view) {
  if (viewHasGeometry(view) && view.nodes.every((n) => n.x > 0 && n.y > 0)) {
    return view  // fully laid out already (server-side ELK has run)
  }

  // Lazy-load elkjs only when auto-layout is actually needed
  const ELKMod = await import('elkjs/lib/elk.bundled.js')
  const ELK = ELKMod.default || ELKMod
  const elk = new ELK()

  const graph = {
    id: 'root',
    layoutOptions: {
      'elk.algorithm': 'layered',
      'elk.direction': 'RIGHT',
      'elk.spacing.nodeNode': '60',
      'elk.layered.spacing.nodeNodeBetweenLayers': '70',
      'elk.spacing.edgeNode': '30',
      'elk.layered.nodePlacement.strategy': 'BRANDES_KOEPF',
      'elk.edgeRouting': 'ORTHOGONAL',
      'elk.padding': '[top=20,left=20,bottom=20,right=20]',
    },
    children: view.nodes.map((n) => {
      const hasPos = n.x > 0 && n.y > 0
      const node = {
        id: n.id,
        width: n.w > 0 ? n.w : 120,
        height: n.h > 0 ? n.h : 55,
      }
      if (hasPos) {
        node.x = n.x
        node.y = n.y
        node.layoutOptions = {
          'elk.position': `(${n.x},${n.y})`,
        }
      }
      return node
    }),
    edges: view.connections
      .filter((c) => c.source && c.target)
      .map((c) => ({ id: c.id, sources: [c.source], targets: [c.target] })),
  }

  const result = await elk.layout(graph)
  const positionsById = new Map(
    (result.children || []).map((c) => [c.id, c])
  )

  return {
    ...view,
    nodes: view.nodes.map((n) => {
      const r = positionsById.get(n.id)
      if (!r) return n
      return {
        ...n,
        x: Math.round(r.x ?? n.x),
        y: Math.round(r.y ?? n.y),
        w: Math.round(r.width ?? n.w),
        h: Math.round(r.height ?? n.h),
      }
    }),
    _layoutComputed: true,
    _elkResult: result,
  }
}

// --- SVG rendering ----------------------------------------------------------

function escapeXml(s) {
  return String(s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&apos;')
}

function lineEdgeSegments(srcNode, tgtNode, elkEdge) {
  // Prefer ELK-routed sections (orthogonal bendpoints) if present
  if (elkEdge && elkEdge.sections && elkEdge.sections.length) {
    const points = []
    for (const sec of elkEdge.sections) {
      points.push([sec.startPoint.x, sec.startPoint.y])
      for (const bp of sec.bendPoints || []) points.push([bp.x, bp.y])
      points.push([sec.endPoint.x, sec.endPoint.y])
    }
    return points
  }
  // Fallback: straight line center-to-center, clipped to box edges
  const sx = srcNode.x + srcNode.w / 2
  const sy = srcNode.y + srcNode.h / 2
  const tx = tgtNode.x + tgtNode.w / 2
  const ty = tgtNode.y + tgtNode.h / 2
  return [[sx, sy], [tx, ty]]
}

function markerDefs(idPrefix) {
  // Define all marker variants we need; the consumer references them via marker-end/start
  return `
    <defs>
      <marker id="${idPrefix}-arrow-filled" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto">
        <path d="M 0 0 L 10 5 L 0 10 z" fill="#222" />
      </marker>
      <marker id="${idPrefix}-arrow-open" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto">
        <path d="M 0 0 L 10 5 L 0 10" fill="none" stroke="#222" stroke-width="1.2" />
      </marker>
      <marker id="${idPrefix}-triangle-open" viewBox="0 0 12 12" refX="11" refY="6" markerWidth="10" markerHeight="10" orient="auto">
        <path d="M 0 0 L 12 6 L 0 12 z" fill="#fff" stroke="#222" stroke-width="1.2" />
      </marker>
      <marker id="${idPrefix}-diamond-filled" viewBox="0 0 12 12" refX="1" refY="6" markerWidth="10" markerHeight="10" orient="auto">
        <path d="M 0 6 L 6 0 L 12 6 L 6 12 z" fill="#222" />
      </marker>
      <marker id="${idPrefix}-diamond-open" viewBox="0 0 12 12" refX="1" refY="6" markerWidth="10" markerHeight="10" orient="auto">
        <path d="M 0 6 L 6 0 L 12 6 L 6 12 z" fill="#fff" stroke="#222" stroke-width="1.2" />
      </marker>
      <marker id="${idPrefix}-circle-filled" viewBox="0 0 8 8" refX="4" refY="4" markerWidth="6" markerHeight="6" orient="auto">
        <circle cx="4" cy="4" r="3" fill="#222" />
      </marker>
    </defs>
  `
}

/**
 * Render a (laid-out) view to an SVG string with ArchiMate notation.
 *
 * @param view  parsed view from parseArchimateXML, after computeLayout()
 * @param model parsed model (for element name/type lookups)
 * @param opts  { highlightIds?: Set<string> } — ids to render with delta accent
 */
export function renderViewToSVG(view, model, opts = {}) {
  const highlight = opts.highlightIds || new Set()
  const PAD = 20

  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity
  for (const n of view.nodes) {
    minX = Math.min(minX, n.x)
    minY = Math.min(minY, n.y)
    maxX = Math.max(maxX, n.x + n.w)
    maxY = Math.max(maxY, n.y + n.h)
  }
  if (!isFinite(minX)) {
    return `<svg xmlns="http://www.w3.org/2000/svg" width="240" height="80">
      <text x="20" y="40" font-family="sans-serif" font-size="13" fill="#888">View has no elements</text>
    </svg>`
  }
  const width = maxX - minX + 2 * PAD
  const height = maxY - minY + 2 * PAD
  const offsetX = PAD - minX
  const offsetY = PAD - minY

  const idPrefix = `am-${view.id?.slice(-8) || Math.random().toString(36).slice(2, 8)}`

  // Layer bands — subtle background per ArchiMate layer so the reader
  // spots the canonical stack (Motivation top → Business → Application
  // → Technology) at a glance. Drawn before nodes and edges so they
  // paint on top.
  const layerBboxes = new Map()
  for (const n of view.nodes) {
    const el = model.elements.get(n.elementRef)
    const layer = el?.layer || 'Unknown'
    if (layer === 'Unknown' || layer === 'Other') continue
    const x = n.x + offsetX
    const y = n.y + offsetY
    const bb = layerBboxes.get(layer)
    if (!bb) {
      layerBboxes.set(layer, [x, y, x + n.w, y + n.h])
    } else {
      bb[0] = Math.min(bb[0], x)
      bb[1] = Math.min(bb[1], y)
      bb[2] = Math.max(bb[2], x + n.w)
      bb[3] = Math.max(bb[3], y + n.h)
    }
  }
  const bandXML = Array.from(layerBboxes.entries())
    .map(([layer, [lx, ly, rx, ry]]) => {
      const fill = LAYER_COLORS[layer] || '#FFFFFF'
      const bw = rx - lx + 36
      const bh = ry - ly + 28
      return `<rect x="${lx - 18}" y="${ly - 14}" width="${bw}" height="${bh}"
              rx="6" ry="6" fill="${fill}" fill-opacity="0.18" stroke="none" />`
    })
    .join('')

  // Containers: any node whose bbox fully encloses at least one other
  // node is treated as a visual parent. Its label moves to a header
  // strip at the top — centring it would overlap the children's labels.
  const containerIds = new Set()
  for (const a of view.nodes) {
    for (const b of view.nodes) {
      if (a.id === b.id) continue
      if (a.x <= b.x && a.y <= b.y
          && a.x + a.w >= b.x + b.w
          && a.y + a.h >= b.y + b.h) {
        containerIds.add(a.id)
        break
      }
    }
  }

  // Element nodes
  const nodeXML = view.nodes.map((n) => {
    const el = model.elements.get(n.elementRef)
    const layer = el?.layer || 'Unknown'
    const fill = LAYER_COLORS[layer] || LAYER_COLORS.Unknown
    const name = el?.name || '(unnamed)'
    const layerLetter = LAYER_LETTER[layer] || ''
    const isNew = highlight.has(n.elementRef) || highlight.has(n.id)
    const isContainer = containerIds.has(n.id)
    const stroke = isNew ? '#1d4ed8' : '#444'
    const strokeWidth = isNew ? 2.5 : 1.2
    const accent = isNew ? `<rect x="${n.x + offsetX - 3}" y="${n.y + offsetY - 3}" width="${n.w + 6}" height="${n.h + 6}" rx="10" fill="none" stroke="#1d4ed8" stroke-width="1" stroke-dasharray="3,3" opacity="0.7"/>` : ''
    const labelX = isContainer ? n.x + offsetX + 12 : n.x + offsetX + n.w / 2
    const labelY = isContainer ? n.y + offsetY + 16 : n.y + offsetY + n.h / 2 + 4
    const labelAnchor = isContainer ? 'start' : 'middle'
    const labelWeight = isContainer ? 'bold' : 'normal'
    return `
      ${accent}
      <g class="am-node" data-element-id="${escapeXml(n.elementRef)}">
        <rect x="${n.x + offsetX}" y="${n.y + offsetY}" width="${n.w}" height="${n.h}"
              rx="3" ry="3" fill="${fill}" stroke="${stroke}" stroke-width="${strokeWidth}" />
        <text x="${n.x + offsetX + n.w - 8}" y="${n.y + offsetY + 14}" font-family="Segoe UI, sans-serif" font-size="10" font-weight="bold" fill="#888" text-anchor="end">${escapeXml(layerLetter)}</text>
        <text x="${labelX}" y="${labelY}" font-family="Segoe UI, sans-serif" font-size="11" font-weight="${labelWeight}" fill="#222" text-anchor="${labelAnchor}">${escapeXml(name)}</text>
      </g>
    `
  }).join('')

  // Connections
  const nodeById = new Map(view.nodes.map((n) => [n.id, n]))
  const elkEdgesById = new Map(
    (view._elkResult?.edges || []).map((e) => [e.id, e])
  )

  // Skip composition/aggregation connections when the visual nesting
  // already expresses the relationship (one node's bbox contains the
  // other). Otherwise we'd draw a diamond pointing inside its own parent.
  const contains = (a, b) =>
    a.x <= b.x && a.y <= b.y && a.x + a.w >= b.x + b.w && a.y + a.h >= b.y + b.h

  const connXML = view.connections.map((c) => {
    const rel = model.relationships.get(c.relationshipRef)
    const src = nodeById.get(c.source)
    const tgt = nodeById.get(c.target)
    if (!src || !tgt) return ''
    if (rel?.type === 'Composition' || rel?.type === 'Aggregation') {
      if (contains(src, tgt) || contains(tgt, src)) return ''
    }
    const style = CONNECTION_STYLE[rel?.type] || CONNECTION_STYLE.Association
    const elkEdge = elkEdgesById.get(c.id)
    const points = lineEdgeSegments(src, tgt, elkEdge)
    const polyPoints = points
      .map(([px, py]) => `${px + offsetX},${py + offsetY}`)
      .join(' ')
    const dasharray = style.line === 'dashed' ? '5,4' : ''
    const markerStart = style.startMarker ? `marker-start="url(#${idPrefix}-${style.startMarker})"` : ''
    const markerEnd = style.endMarker ? `marker-end="url(#${idPrefix}-${style.endMarker})"` : ''
    const isNew = highlight.has(c.relationshipRef) || highlight.has(c.id)
    const stroke = isNew ? '#1d4ed8' : '#222'
    const strokeWidth = isNew ? 2 : 1.2
    return `
      <polyline class="am-connection" data-relationship-id="${escapeXml(c.relationshipRef)}"
        points="${polyPoints}" fill="none"
        stroke="${stroke}" stroke-width="${strokeWidth}"
        ${dasharray ? `stroke-dasharray="${dasharray}"` : ''}
        ${markerStart} ${markerEnd} />
    `
  }).join('')

  return `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}">
    ${markerDefs(idPrefix)}
    ${bandXML}
    ${connXML}
    ${nodeXML}
  </svg>`
}
