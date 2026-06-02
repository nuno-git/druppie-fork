// Druppie layout-service — server-side ELK for ArchiMate views.
//
// The module-archimate writer calls POST /layout with a graph spec
// derived from a view (nodes + edges + per-node ArchiMate layer hint
// + per-node "fixed" flag + optional viewpoint). We translate that
// into ELK's input format with viewpoint-aware options, run the
// layered algorithm, then return laid-out coordinates back. The
// writer patches them into the .archimate XML before serialising.
//
// Everything is in-memory and stateless: ELK is deterministic, so
// callers can rely on identical input producing identical output.

import express from 'express'
import ELKMod from 'elkjs/lib/elk.bundled.js'

const ELK = ELKMod.default || ELKMod
const elk = new ELK()
const app = express()
app.use(express.json({ limit: '5mb' }))

// ArchiMate semantic layers map to ELK partition indices so the rendered
// plate keeps Motivation on top, then Business → Application → Technology
// (canonical ArchiMate stack). Cross-layer ("Other") and unknowns are
// placed between Business and Application to avoid pinning them somewhere
// arbitrary that breaks the visual hierarchy.
const LAYER_PARTITION = {
  Motivation: 0,
  Business: 1,
  Other: 2,
  Application: 3,
  Technology: 4,
}

const DEFAULT_NODE_W = 120
const DEFAULT_NODE_H = 55

// Per-viewpoint ELK option recipes. Picked from EA practitioner
// guidance (Wierda, BiZZdesign, Open Group sample viewpoints) — each
// viewpoint has a canonical layout shape that ELK won't infer on its
// own. The default falls back to Layered.
//
// All viewpoints partition by ArchiMate layer and lay out top-to-bottom
// (DOWN), so every plate keeps the canonical Motivation → Business →
// Application → Technology stack in clean horizontal bands — matching the
// Rijnland tekenafspraken and avoiding the overlapping-colour-band result
// that topology-only layouts produced.
//
// 'Layered'           — generic cross-layer stack.
// 'ApplicationCooperation' — app components + their actors/infra, banded.
// 'Organization'      — actors/roles, banded.
// 'InformationStructure' — data-object composition, banded.
const VIEWPOINT_RECIPES = {
  Layered: {
    'elk.direction': 'DOWN',
    'elk.spacing.nodeNode': '50',
    'elk.layered.spacing.nodeNodeBetweenLayers': '70',
    'elk.layered.nodePlacement.strategy': 'BRANDES_KOEPF',
    'elk.layered.nodePlacement.bk.fixedAlignment': 'BALANCED',
    'elk.partitioning.activate': 'true',
  },
  ApplicationCooperation: {
    'elk.direction': 'DOWN',
    'elk.spacing.nodeNode': '60',
    'elk.layered.spacing.nodeNodeBetweenLayers': '90',
    'elk.layered.nodePlacement.strategy': 'BRANDES_KOEPF',
    'elk.layered.nodePlacement.bk.fixedAlignment': 'BALANCED',
    'elk.partitioning.activate': 'true',
  },
  Organization: {
    'elk.direction': 'DOWN',
    'elk.spacing.nodeNode': '40',
    'elk.layered.spacing.nodeNodeBetweenLayers': '60',
    'elk.layered.nodePlacement.strategy': 'BRANDES_KOEPF',
    'elk.partitioning.activate': 'true',
  },
  InformationStructure: {
    'elk.direction': 'DOWN',
    'elk.spacing.nodeNode': '40',
    'elk.layered.spacing.nodeNodeBetweenLayers': '50',
    'elk.layered.nodePlacement.strategy': 'BRANDES_KOEPF',
    'elk.partitioning.activate': 'true',
  },
}

const DEFAULT_VIEWPOINT = 'Layered'

// Build a single ELK child-node object (without nesting wired yet —
// callers attach the `children` array if any).
function buildElkNode(n, { partitioningOn }) {
  const node = {
    id: n.id,
    width: n.w > 0 ? n.w : DEFAULT_NODE_W,
    height: n.h > 0 ? n.h : DEFAULT_NODE_H,
    layoutOptions: {
      // Children of a compound node inherit the layered algorithm too,
      // so siblings inside a composition stack are laid out cleanly.
      'elk.algorithm': 'layered',
    },
  }
  const partition = LAYER_PARTITION[n.layer]
  if (partitioningOn && partition !== undefined) {
    node.layoutOptions['elk.partitioning.partition'] = String(partition)
  }
  if (n.fixed && n.x >= 0 && n.y >= 0) {
    node.x = n.x
    node.y = n.y
    node.layoutOptions['elk.position'] = `(${n.x},${n.y})`
  }
  return node
}

// Visual nesting: when a node carries `parent: <other-id>`, ELK treats
// it as a child of that parent (compound graph). Edges between the
// parent and child are dropped because the nesting *is* the
// relationship. Parents auto-size to contain their children.
function buildElkGraph({ nodes, edges, viewpoint }) {
  const recipe = VIEWPOINT_RECIPES[viewpoint] || VIEWPOINT_RECIPES[DEFAULT_VIEWPOINT]
  const partitioningOn = recipe['elk.partitioning.activate'] === 'true'

  const nodesById = new Map(nodes.map((n) => [n.id, n]))
  const childrenByParent = new Map()
  const rootNodes = []
  for (const n of nodes) {
    if (n.parent && nodesById.has(n.parent)) {
      const list = childrenByParent.get(n.parent) || []
      list.push(n)
      childrenByParent.set(n.parent, list)
    } else {
      rootNodes.push(n)
    }
  }

  function attachChildren(elkNode, sourceNode) {
    const kids = childrenByParent.get(sourceNode.id)
    if (!kids || !kids.length) return
    elkNode.children = kids.map((k) => {
      const child = buildElkNode(k, { partitioningOn })
      attachChildren(child, k)
      return child
    })
    // Compound nodes need their own layout config; let ELK size them
    // around their children with comfortable padding.
    elkNode.layoutOptions = {
      ...elkNode.layoutOptions,
      'elk.padding': '[top=30,left=15,bottom=15,right=15]',
      'elk.spacing.nodeNode': '20',
    }
    // Drop the fixed size — let ELK compute the bounding box.
    delete elkNode.width
    delete elkNode.height
  }

  // Edges that cross a nesting boundary in the same direction as the
  // composition (parent → child) are redundant with the visual nesting
  // and would draw an ugly diamond inside the parent. Strip them.
  const compositionPairs = new Set()
  for (const n of nodes) {
    if (n.parent) compositionPairs.add(`${n.parent}->${n.id}`)
  }
  const filteredEdges = edges.filter(
    (e) => !compositionPairs.has(`${e.source}->${e.target}`)
            && !compositionPairs.has(`${e.target}->${e.source}`)
  )

  return {
    id: 'root',
    layoutOptions: {
      'elk.algorithm': 'layered',
      'elk.edgeRouting': 'ORTHOGONAL',
      'elk.padding': '[top=20,left=20,bottom=20,right=20]',
      'elk.spacing.edgeNode': '30',
      'elk.hierarchyHandling': 'INCLUDE_CHILDREN',
      ...recipe,
    },
    children: rootNodes.map((n) => {
      const node = buildElkNode(n, { partitioningOn })
      attachChildren(node, n)
      return node
    }),
    edges: filteredEdges.map((e) => ({
      id: e.id,
      sources: [e.source],
      targets: [e.target],
    })),
  }
}

app.get('/health', (_req, res) => res.status(200).json({ status: 'ok' }))

// ELK returns child coordinates relative to their parent. The writer
// wants flat absolute positions, so we walk the tree and accumulate
// offsets. Compound parents stay in the result because the renderer
// draws them as background rectangles for the visual nesting.
function flattenElkResult(elkNodes, offsetX = 0, offsetY = 0, out = []) {
  for (const c of elkNodes || []) {
    const x = Math.round((c.x ?? 0) + offsetX)
    const y = Math.round((c.y ?? 0) + offsetY)
    out.push({
      id: c.id,
      x,
      y,
      w: Math.round(c.width ?? DEFAULT_NODE_W),
      h: Math.round(c.height ?? DEFAULT_NODE_H),
    })
    if (c.children && c.children.length) {
      flattenElkResult(c.children, x, y, out)
    }
  }
  return out
}

app.post('/layout', async (req, res) => {
  try {
    const { nodes, edges, viewpoint } = req.body || {}
    if (!Array.isArray(nodes) || !Array.isArray(edges)) {
      return res.status(400).json({
        error: 'Request body must include nodes:[] and edges:[]',
      })
    }
    const graph = buildElkGraph({ nodes, edges, viewpoint })
    const result = await elk.layout(graph)
    const laidOut = flattenElkResult(result.children)
    res.json({ success: true, nodes: laidOut, viewpoint: viewpoint || DEFAULT_VIEWPOINT })
  } catch (err) {
    console.error('layout_failed', err)
    res.status(500).json({
      success: false,
      error: err.message || String(err),
    })
  }
})

const port = Number(process.env.PORT || 8090)
app.listen(port, '0.0.0.0', () => {
  console.log(`layout-service listening on :${port}`)
})
