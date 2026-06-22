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

// --- NORA / IEC-62443 trust-level colours (Rijnland tekenafspraken) ---
// A Beveiligingsdomein (security zone) or a security Constraint carries a
// trust level and is coloured by the NORA beschouwingsmodel instead of the
// standard Motivation purple, so reviewers read the zone's trust at a glance.
// Hexes follow the green-for-trusted ordering seen in the tekenafspraken and
// can be tuned to an exact NORA palette later.
export const TRUST_COLORS = {
  'niet-vertrouwd': '#F4B6B6',
  'semi-vertrouwd': '#A6D785',
  'vertrouwd': '#F6D365',
  'zeer-vertrouwd': '#6FB04A',
}

// Detect a NORA trust level from an element's stereotype, trust-level
// property, or name. Returns '' when none is present.
export function trustLevelOf(el) {
  if (!el) return ''
  const hay = `${el.trustLevel || ''} ${el.name || ''}`.toLowerCase()
  for (const level of Object.keys(TRUST_COLORS)) {
    if (hay.includes(level)) return level
  }
  return ''
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

// --- ArchiMate shape + icon vocabulary --------------------------------------
// Mirrors svg_export.py 1:1 so the Gitea preview and the in-app viewer look
// identical. Box shape varies by ArchiMate category (service=stadium,
// behaviour=rounded, grouping=dashed, structure=square) and a small standard
// type-icon sits top-right — making element types and the Rijnland
// "ownership decides the shape" rule visible at a glance.
const SERVICE_TYPES = new Set(['BusinessService', 'ApplicationService', 'TechnologyService'])
const BEHAVIOR_TYPES = new Set([
  'BusinessProcess', 'BusinessFunction', 'BusinessInteraction', 'BusinessEvent',
  'ApplicationFunction', 'ApplicationInteraction', 'ApplicationProcess',
  'ApplicationEvent', 'TechnologyFunction', 'TechnologyProcess',
  'TechnologyInteraction', 'TechnologyEvent',
])
const MOTIVATION_TYPES = new Set([
  'Stakeholder', 'Driver', 'Assessment', 'Goal', 'Outcome', 'Principle',
  'Requirement', 'Constraint', 'Meaning', 'Value',
])
const GROUPING_TYPES = new Set(['Grouping', 'Location'])

export function nodeRadius(elType, h) {
  if (SERVICE_TYPES.has(elType)) return { rx: Math.max(4, h / 2), dashed: false }
  if (BEHAVIOR_TYPES.has(elType)) return { rx: 10, dashed: false }
  if (MOTIVATION_TYPES.has(elType)) return { rx: 9, dashed: false }
  if (GROUPING_TYPES.has(elType)) return { rx: 4, dashed: true }
  return { rx: 2, dashed: false }
}

function iconKind(t) {
  if (t === 'ApplicationCollaboration' || t === 'BusinessCollaboration' || t === 'TechnologyCollaboration') return 'collab'
  if (t === 'ApplicationComponent') return 'component'
  if (t === 'BusinessActor') return 'actor'
  if (t === 'BusinessRole' || t === 'Stakeholder') return 'role'
  if (SERVICE_TYPES.has(t)) return 'service'
  if (t.endsWith('Interface')) return 'interface'
  if (t.endsWith('Process')) return 'process'
  if (t.endsWith('Function')) return 'function'
  if (t.endsWith('Event')) return 'event'
  if (t === 'DataObject' || t === 'BusinessObject') return 'object'
  if (t === 'Artifact') return 'artifact'
  if (t === 'Node') return 'node'
  if (t === 'Device') return 'device'
  if (t === 'SystemSoftware') return 'syssoft'
  if (t === 'Driver') return 'driver'
  if (t === 'Goal' || t === 'Outcome') return 'goal'
  if (t === 'Principle') return 'principle'
  if (t === 'Requirement') return 'requirement'
  if (t === 'Constraint') return 'constraint'
  if (t === 'Plateau') return 'plateau'
  return ''
}

export function typeIconSVG(elType, ix, iy) {
  const kind = iconKind(elType)
  if (!kind) return ''
  const s = 'fill="none" stroke="#555" stroke-width="1.1"'
  const sf = 'fill="#fff" stroke="#555" stroke-width="1.1"'
  switch (kind) {
    case 'component':
      return `<rect x="${ix + 3}" y="${iy}" width="11" height="14" ${sf}/>`
        + `<rect x="${ix}" y="${iy + 2}" width="5" height="3.5" ${sf}/>`
        + `<rect x="${ix}" y="${iy + 8}" width="5" height="3.5" ${sf}/>`
    case 'collab':
      return `<circle cx="${ix + 5}" cy="${iy + 7}" r="4.5" ${s}/>`
        + `<circle cx="${ix + 10}" cy="${iy + 7}" r="4.5" ${s}/>`
    case 'actor':
      return `<circle cx="${ix + 7}" cy="${iy + 2}" r="2.2" ${s}/>`
        + `<line x1="${ix + 7}" y1="${iy + 4}" x2="${ix + 7}" y2="${iy + 10}" ${s}/>`
        + `<line x1="${ix + 2}" y1="${iy + 6}" x2="${ix + 12}" y2="${iy + 6}" ${s}/>`
        + `<line x1="${ix + 7}" y1="${iy + 10}" x2="${ix + 3}" y2="${iy + 14}" ${s}/>`
        + `<line x1="${ix + 7}" y1="${iy + 10}" x2="${ix + 11}" y2="${iy + 14}" ${s}/>`
    case 'role':
      return `<circle cx="${ix + 9}" cy="${iy + 7}" r="4" ${s}/>`
        + `<line x1="${ix + 1}" y1="${iy + 4}" x2="${ix + 1}" y2="${iy + 10}" ${s}/>`
        + `<line x1="${ix + 1}" y1="${iy + 7}" x2="${ix + 5}" y2="${iy + 7}" ${s}/>`
    case 'service':
      return `<rect x="${ix}" y="${iy + 3}" width="15" height="9" rx="4.5" ry="4.5" ${s}/>`
    case 'interface':
      return `<line x1="${ix}" y1="${iy + 7}" x2="${ix + 7}" y2="${iy + 7}" ${s}/>`
        + `<circle cx="${ix + 10}" cy="${iy + 7}" r="3.2" ${s}/>`
    case 'process':
      return `<path d="M ${ix} ${iy + 3} L ${ix + 8} ${iy + 3} L ${ix + 8} ${iy} L ${ix + 14} ${iy + 7} L ${ix + 8} ${iy + 14} L ${ix + 8} ${iy + 11} L ${ix} ${iy + 11} Z" ${s}/>`
    case 'function':
      return `<path d="M ${ix + 7} ${iy} L ${ix + 14} ${iy + 5} L ${ix + 11} ${iy + 14} L ${ix + 3} ${iy + 14} L ${ix} ${iy + 5} Z" ${s}/>`
    case 'event':
      return `<path d="M ${ix} ${iy + 2} L ${ix + 10} ${iy + 2} L ${ix + 14} ${iy + 7} L ${ix + 10} ${iy + 12} L ${ix} ${iy + 12} L ${ix + 3} ${iy + 7} Z" ${s}/>`
    case 'object':
      return `<rect x="${ix}" y="${iy + 1}" width="14" height="12" ${s}/>`
        + `<line x1="${ix}" y1="${iy + 5}" x2="${ix + 14}" y2="${iy + 5}" ${s}/>`
    case 'artifact':
      return `<path d="M ${ix + 1} ${iy} L ${ix + 9} ${iy} L ${ix + 13} ${iy + 4} L ${ix + 13} ${iy + 14} L ${ix + 1} ${iy + 14} Z" ${s}/>`
        + `<path d="M ${ix + 9} ${iy} L ${ix + 9} ${iy + 4} L ${ix + 13} ${iy + 4}" ${s}/>`
    case 'node':
      return `<rect x="${ix}" y="${iy + 4}" width="10" height="10" ${s}/>`
        + `<path d="M ${ix} ${iy + 4} L ${ix + 4} ${iy} L ${ix + 14} ${iy} L ${ix + 10} ${iy + 4}" ${s}/>`
        + `<path d="M ${ix + 10} ${iy + 14} L ${ix + 14} ${iy + 10} L ${ix + 14} ${iy}" ${s}/>`
    case 'device':
      return `<rect x="${ix + 1}" y="${iy + 1}" width="12" height="8" rx="1.5" ${s}/>`
        + `<path d="M ${ix - 1} ${iy + 13} L ${ix + 15} ${iy + 13} L ${ix + 12} ${iy + 9} L ${ix + 2} ${iy + 9} Z" ${s}/>`
    case 'syssoft':
      return `<ellipse cx="${ix + 7}" cy="${iy + 4}" rx="6.5" ry="3" ${s}/>`
        + `<path d="M ${ix + 0.5} ${iy + 4} L ${ix + 0.5} ${iy + 10}" ${s}/>`
        + `<path d="M ${ix + 13.5} ${iy + 4} L ${ix + 13.5} ${iy + 10}" ${s}/>`
        + `<path d="M ${ix + 0.5} ${iy + 10} A 6.5 3 0 0 0 ${ix + 13.5} ${iy + 10}" ${s}/>`
    case 'driver':
      return `<circle cx="${ix + 7}" cy="${iy + 7}" r="6" ${s}/>`
        + `<circle cx="${ix + 7}" cy="${iy + 7}" r="1.6" ${s}/>`
        + `<line x1="${ix + 7}" y1="${iy + 1}" x2="${ix + 7}" y2="${iy + 13}" ${s}/>`
        + `<line x1="${ix + 1}" y1="${iy + 7}" x2="${ix + 13}" y2="${iy + 7}" ${s}/>`
    case 'goal':
      return `<circle cx="${ix + 7}" cy="${iy + 7}" r="6" ${s}/>`
        + `<circle cx="${ix + 7}" cy="${iy + 7}" r="2.5" ${s}/>`
    case 'principle':
      return `<circle cx="${ix + 7}" cy="${iy + 7}" r="6" ${s}/>`
        + `<line x1="${ix + 7}" y1="${iy + 3}" x2="${ix + 7}" y2="${iy + 11}" ${s}/>`
        + `<line x1="${ix + 7}" y1="${iy + 3}" x2="${ix + 4.5}" y2="${iy + 6}" ${s}/>`
        + `<line x1="${ix + 7}" y1="${iy + 3}" x2="${ix + 9.5}" y2="${iy + 6}" ${s}/>`
    case 'requirement':
      return `<path d="M ${ix + 3} ${iy + 1} L ${ix + 14} ${iy + 1} L ${ix + 11} ${iy + 13} L ${ix} ${iy + 13} Z" ${s}/>`
    case 'constraint':
      return `<path d="M ${ix + 3} ${iy + 1} L ${ix + 14} ${iy + 1} L ${ix + 11} ${iy + 13} L ${ix} ${iy + 13} Z" ${s}/>`
        + `<line x1="${ix + 2}" y1="${iy + 7}" x2="${ix + 12}" y2="${iy + 7}" ${s}/>`
    case 'plateau':
      return `<rect x="${ix}" y="${iy + 1}" width="14" height="3" ${sf}/>`
        + `<rect x="${ix}" y="${iy + 6}" width="14" height="3" ${sf}/>`
        + `<rect x="${ix}" y="${iy + 11}" width="14" height="3" ${sf}/>`
    default:
      return ''
  }
}

// Point where the line from box-centre (cx,cy) toward (tx,ty) exits the box.
function borderPoint(cx, cy, w, h, tx, ty) {
  const dx = tx - cx
  const dy = ty - cy
  if (dx === 0 && dy === 0) return [cx, cy]
  const sx = dx ? (w / 2) / Math.abs(dx) : Infinity
  const sy = dy ? (h / 2) / Math.abs(dy) : Infinity
  const sc = Math.min(sx, sy)
  return [cx + dx * sc, cy + dy * sc]
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

  // Map propertyDefinition id -> name, so we can read back the Rijnland
  // `stereotype` / `trust-level` markers written by writer._add_property_marker.
  const propDefName = new Map()
  const propDefsSection = findLocal(root, 'propertyDefinitions')
  if (propDefsSection) {
    for (const pd of findAllLocal(propDefsSection, 'propertyDefinition')) {
      propDefName.set(attr(pd, 'identifier'), textOf(pd, 'name'))
    }
  }
  const readProp = (el, propName) => {
    const props = findLocal(el, 'properties')
    if (!props) return ''
    for (const p of findAllLocal(props, 'property')) {
      if (propDefName.get(attr(p, 'propertyDefinitionRef')) === propName) {
        return (textOf(p, 'value') || '').trim()
      }
    }
    return ''
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
        stereotype: readProp(el, 'stereotype'),
        trustLevel: readProp(el, 'trust-level'),
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
            // ELK's orthogonal routing, persisted server-side by writer.py.
            bendpoints: findAllLocal(c, 'bendpoint').map((b) => ({
              x: parseInt(attr(b, 'x') || '0', 10),
              y: parseInt(attr(b, 'y') || '0', 10),
            })),
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
      // DOWN to match the server-side layout-service so the in-browser
      // fallback produces the same canonical Motivation→…→Technology stack.
      'elk.direction': 'DOWN',
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

function lineEdgeSegments(srcNode, tgtNode, elkEdge, conn) {
  // Prefer the orthogonal routing persisted server-side (writer.py) — the
  // canonical source once layout-service has run.
  if (conn && conn.bendpoints && conn.bendpoints.length >= 2) {
    return conn.bendpoints.map((b) => [b.x, b.y])
  }
  // Then in-browser ELK-routed sections (legacy / fallback layout path).
  if (elkEdge && elkEdge.sections && elkEdge.sections.length) {
    const points = []
    for (const sec of elkEdge.sections) {
      points.push([sec.startPoint.x, sec.startPoint.y])
      for (const bp of sec.bendPoints || []) points.push([bp.x, bp.y])
      points.push([sec.endPoint.x, sec.endPoint.y])
    }
    return points
  }
  // Last resort: straight line, clipped to both box borders so the
  // arrowhead lands on the edge instead of hiding under the target.
  const scx = srcNode.x + srcNode.w / 2
  const scy = srcNode.y + srcNode.h / 2
  const tcx = tgtNode.x + tgtNode.w / 2
  const tcy = tgtNode.y + tgtNode.h / 2
  const start = borderPoint(scx, scy, srcNode.w, srcNode.h, tcx, tcy)
  const end = borderPoint(tcx, tcy, tgtNode.w, tgtNode.h, scx, scy)
  return [start, end]
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

  // Layer bands — a full-width horizontal stripe per ArchiMate layer. Every
  // band spans the whole canvas width and only varies in y, so they read as
  // clean Motivation → Business → Application → Technology stripes instead of
  // the ragged per-layer bounding boxes we drew before. A faded uppercase
  // caption sits in the band's top padding.
  const layerYRanges = new Map()
  for (const n of view.nodes) {
    const el = model.elements.get(n.elementRef)
    const layer = el?.layer || 'Unknown'
    if (layer === 'Unknown' || layer === 'Other') continue
    const y = n.y + offsetY
    const yr = layerYRanges.get(layer)
    if (!yr) layerYRanges.set(layer, [y, y + n.h])
    else { yr[0] = Math.min(yr[0], y); yr[1] = Math.max(yr[1], y + n.h) }
  }
  const bandLeft = PAD - 8
  const bandW = (width - 2 * PAD) + 16
  const BAND_ORDER = { Motivation: 0, Strategy: 1, Business: 2, Application: 3, Technology: 4, Physical: 5, Implementation: 6 }
  const bandXML = Array.from(layerYRanges.entries())
    .sort((a, b) => (BAND_ORDER[a[0]] ?? 9) - (BAND_ORDER[b[0]] ?? 9))
    .map(([layer, [ly, ry]]) => {
      const fill = LAYER_COLORS[layer] || '#FFFFFF'
      return `<rect x="${bandLeft}" y="${ly - 14}" width="${bandW}" height="${ry - ly + 28}"
              rx="6" ry="6" fill="${fill}" fill-opacity="0.18" stroke="none" />`
        + `<text x="${bandLeft + 8}" y="${ly - 4}" font-family="Segoe UI, sans-serif" font-size="9" font-weight="bold" letter-spacing="1" fill="#888" fill-opacity="0.7">${escapeXml(layer.toUpperCase())}</text>`
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
    // NORA exception: a security zone / security Constraint is coloured by its
    // trust level, not by the standard layer colour (Rijnland tekenafspraken).
    const trust = trustLevelOf(el)
    const isSecurity = el?.stereotype === 'Beveiligingsdomein' || el?.type === 'Constraint'
    const fill = (trust && isSecurity)
      ? TRUST_COLORS[trust]
      : (LAYER_COLORS[layer] || LAYER_COLORS.Unknown)
    const name = el?.name || '(unnamed)'
    const stereotype = el?.stereotype || ''
    const elType = el?.type || ''
    const isNew = highlight.has(n.elementRef) || highlight.has(n.id)
    const isContainer = containerIds.has(n.id)
    const stroke = isNew ? '#1d4ed8' : '#444'
    const strokeWidth = isNew ? 2.5 : 1.2
    const { rx, dashed } = nodeRadius(elType, n.h)
    const nodeDash = dashed ? ' stroke-dasharray="6,4"' : ''
    // Type icon top-right; fall back to the single-letter layer badge.
    const icon = typeIconSVG(elType, n.x + offsetX + n.w - 21, n.y + offsetY + 5)
    const corner = icon
      || `<text x="${n.x + offsetX + n.w - 8}" y="${n.y + offsetY + 14}" font-family="Segoe UI, sans-serif" font-size="10" font-weight="bold" fill="#888" text-anchor="end">${escapeXml(LAYER_LETTER[layer] || '')}</text>`
    const accent = isNew ? `<rect x="${n.x + offsetX - 3}" y="${n.y + offsetY - 3}" width="${n.w + 6}" height="${n.h + 6}" rx="10" fill="none" stroke="#1d4ed8" stroke-width="1" stroke-dasharray="3,3" opacity="0.7"/>` : ''
    // Leave room on the right so a long centred label doesn't run under the icon.
    const labelX = isContainer ? n.x + offsetX + 12 : n.x + offsetX + (n.w - 18) / 2
    // Nudge the name down when a «stereotype» line sits above it, so the two
    // don't collide inside the box.
    const baseY = isContainer ? n.y + offsetY + 16 : n.y + offsetY + n.h / 2 + 4
    const labelY = stereotype && !isContainer ? baseY + 6 : baseY
    const stereoY = isContainer ? n.y + offsetY + 30 : labelY - 12
    const labelAnchor = isContainer ? 'start' : 'middle'
    const labelWeight = isContainer ? 'bold' : 'normal'
    const stereoXML = stereotype
      ? `<text x="${labelX}" y="${stereoY}" font-family="Segoe UI, sans-serif" font-size="9" font-style="italic" fill="#555" text-anchor="${labelAnchor}">«${escapeXml(stereotype)}»</text>`
      : ''
    return `
      ${accent}
      <g class="am-node" data-element-id="${escapeXml(n.elementRef)}">
        <rect x="${n.x + offsetX}" y="${n.y + offsetY}" width="${n.w}" height="${n.h}"
              rx="${rx}" ry="${rx}" fill="${fill}" stroke="${stroke}" stroke-width="${strokeWidth}"${nodeDash} />
        ${corner}
        ${stereoXML}
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

  const labelParts = []
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
    const points = lineEdgeSegments(src, tgt, elkEdge, c)
    const placed = points.map(([px, py]) => [px + offsetX, py + offsetY])
    const polyPoints = placed.map(([px, py]) => `${px},${py}`).join(' ')
    const dasharray = style.line === 'dashed' ? '5,4' : ''
    const markerStart = style.startMarker ? `marker-start="url(#${idPrefix}-${style.startMarker})"` : ''
    const markerEnd = style.endMarker ? `marker-end="url(#${idPrefix}-${style.endMarker})"` : ''
    const isNew = highlight.has(c.relationshipRef) || highlight.has(c.id)
    const stroke = isNew ? '#1d4ed8' : '#222'
    const strokeWidth = isNew ? 2 : 1.2
    // Edge label (relationship name) at the polyline midpoint, on a faint
    // backplate so it stays legible where it crosses a band.
    const relName = rel?.name || ''
    if (relName) {
      const [lx, ly] = placed[Math.floor(placed.length / 2)]
      const tw = relName.length * 5.4 + 6
      labelParts.push(
        `<rect x="${lx - tw / 2}" y="${ly - 7}" width="${tw}" height="13" rx="2" fill="#fff" fill-opacity="0.72" stroke="none" />`
        + `<text x="${lx}" y="${ly + 3}" font-family="Segoe UI, sans-serif" font-size="9" fill="#444" text-anchor="middle">${escapeXml(relName)}</text>`
      )
    }
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
    ${labelParts.join('')}
  </svg>`
}
