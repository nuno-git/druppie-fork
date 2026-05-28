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
// 'Layered'           — Motivation/Business/Application/Technology
//                       stacked top-to-bottom; realize-stack points up.
// 'ApplicationCooperation' — peer components side-by-side, horizontal
//                       flow with shared services in the middle.
// 'Organization'      — actors/roles in a chart-like hierarchy.
// 'InformationStructure' — data-object composition tree, top-down.
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
    'elk.direction': 'RIGHT',
    'elk.spacing.nodeNode': '60',
    'elk.layered.spacing.nodeNodeBetweenLayers': '90',
    'elk.layered.nodePlacement.strategy': 'NETWORK_SIMPLEX',
    'elk.partitioning.activate': 'false',
  },
  Organization: {
    'elk.direction': 'DOWN',
    'elk.spacing.nodeNode': '40',
    'elk.layered.spacing.nodeNodeBetweenLayers': '60',
    'elk.layered.nodePlacement.strategy': 'BRANDES_KOEPF',
    'elk.partitioning.activate': 'false',
  },
  InformationStructure: {
    'elk.direction': 'DOWN',
    'elk.spacing.nodeNode': '40',
    'elk.layered.spacing.nodeNodeBetweenLayers': '50',
    'elk.layered.nodePlacement.strategy': 'BRANDES_KOEPF',
    'elk.partitioning.activate': 'false',
  },
}

const DEFAULT_VIEWPOINT = 'Layered'

function buildElkGraph({ nodes, edges, viewpoint }) {
  const recipe = VIEWPOINT_RECIPES[viewpoint] || VIEWPOINT_RECIPES[DEFAULT_VIEWPOINT]
  const partitioningOn = recipe['elk.partitioning.activate'] === 'true'
  return {
    id: 'root',
    layoutOptions: {
      'elk.algorithm': 'layered',
      'elk.edgeRouting': 'ORTHOGONAL',
      'elk.padding': '[top=20,left=20,bottom=20,right=20]',
      'elk.spacing.edgeNode': '30',
      ...recipe,
    },
    children: nodes.map((n) => {
      const node = {
        id: n.id,
        width: n.w > 0 ? n.w : DEFAULT_NODE_W,
        height: n.h > 0 ? n.h : DEFAULT_NODE_H,
        layoutOptions: {},
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
    }),
    edges: edges.map((e) => ({
      id: e.id,
      sources: [e.source],
      targets: [e.target],
    })),
  }
}

app.get('/health', (_req, res) => res.status(200).json({ status: 'ok' }))

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
    const laidOut = (result.children || []).map((c) => ({
      id: c.id,
      x: Math.round(c.x ?? 0),
      y: Math.round(c.y ?? 0),
      w: Math.round(c.width ?? DEFAULT_NODE_W),
      h: Math.round(c.height ?? DEFAULT_NODE_H),
    }))
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
