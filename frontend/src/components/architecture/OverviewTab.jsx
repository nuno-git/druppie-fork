import { useState, useRef, useEffect, useCallback } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  Bot, Server, Shield, Activity, Monitor, Database, GitBranch, Lock,
  Code, Box, User, ArrowRight, X, Layers, Globe, Wrench
} from 'lucide-react'
import AskArchitectFooter from './AskArchitectFooter'
import { getArchitectureAgents, getMCPServers, getStatus } from '../../services/api'

// =============================================================================
// STAT CARD
// =============================================================================

const StatCard = ({ title, value, icon: Icon, color }) => (
  <div className="bg-white rounded-xl border border-gray-100 p-6 transition-all">
    <div className="flex items-center justify-between">
      <div>
        <p className="text-sm text-gray-400 font-medium">{title}</p>
        <p className="text-3xl font-semibold mt-1">{value}</p>
      </div>
      <div className={`w-10 h-10 rounded-lg flex items-center justify-center ${color} bg-opacity-10`}>
        <Icon className={`w-5 h-5 ${color.replace('bg-', 'text-')}`} />
      </div>
    </div>
  </div>
)

// =============================================================================
// HIGH-LEVEL ARCHITECTURE - GROUPED VIEW
// =============================================================================

const NODE_TYPES = {
  frontend: { bg: 'bg-emerald-50', border: 'border-emerald-200', iconBg: 'bg-emerald-100', text: 'text-emerald-700', ring: 'ring-emerald-300' },
  backend:  { bg: 'bg-sky-50', border: 'border-sky-200', iconBg: 'bg-sky-100', text: 'text-sky-700', ring: 'ring-sky-300' },
  group:    { bg: 'bg-blue-50', border: 'border-blue-200', iconBg: 'bg-blue-100', text: 'text-blue-700', ring: 'ring-blue-300' },
  mcp:      { bg: 'bg-purple-50', border: 'border-purple-200', iconBg: 'bg-purple-100', text: 'text-purple-700', ring: 'ring-purple-300' },
  infra:    { bg: 'bg-slate-50', border: 'border-slate-200', iconBg: 'bg-slate-100', text: 'text-slate-600', ring: 'ring-slate-300' },
  gate:     { bg: 'bg-red-50', border: 'border-red-200', iconBg: 'bg-red-100', text: 'text-red-600', ring: 'ring-red-300' },
}

// Static infrastructure nodes (these don't change via core updates)
const STATIC_NODES = [
  { id: 'user', label: 'Gebruiker', subtitle: 'Browser', icon: User, type: 'frontend', row: 0, col: 1 },
  { id: 'frontend', label: 'Frontend', subtitle: 'React 18 / Vite / Tailwind CSS', icon: Monitor, type: 'frontend', row: 1, col: 0, status: true,
    detail: { tech: 'React 18, React Router v6, TanStack Query, Tailwind CSS, Lucide Icons, Mermaid, Keycloak.js', description: 'Single-page applicatie met real-time chat, approval workflows, project management en deze architectuurpagina.' } },
  { id: 'keycloak', label: 'Keycloak', subtitle: 'OAuth 2.0 / OIDC / JWT', icon: Lock, type: 'infra', row: 1, col: 2, status: true,
    detail: { tech: 'Keycloak 24.0, JWT Bearer tokens, OIDC', description: 'Authenticatie en autorisatie. Rollen: admin, architect, developer, business_analyst, user. Silent SSO, automatic token refresh.' } },
  { id: 'backend', label: 'Backend API', subtitle: 'Python / FastAPI / SQLAlchemy', icon: Server, type: 'backend', row: 2, col: 1, status: true,
    detail: { tech: 'Python 3.12, FastAPI, SQLAlchemy, Pydantic, LiteLLM, structlog, httpx', description: 'Layered architecture: API Routes → Services → Repositories → Domain Models. Orchestreert de volledige agent pipeline.' } },
  // Row 3: agents, approval, mcp-servers (dynamic subtitles)
  { id: 'approval', label: 'Approval Gate', subtitle: 'Human-in-the-Loop governance', icon: Shield, type: 'gate', row: 3, col: 1,
    detail: { description: 'Layered approval systeem: globale defaults (mcp_config.yaml) + agent-specifieke overrides. Tool calls pauzeren tot een geautoriseerde gebruiker goedkeurt. Role-based access control.' } },
  // Row 4: infra
  { id: 'db', label: 'PostgreSQL', subtitle: 'Database / SQLAlchemy ORM', icon: Database, type: 'infra', row: 4, col: 0, status: true,
    detail: { tech: 'PostgreSQL 15, SQLAlchemy ORM, Pydantic domain models', description: 'Sessions, agent runs, tool calls, approvals, projects, deployments. Summary/Detail naming pattern.' } },
  { id: 'gitea', label: 'Gitea', subtitle: 'Git repository hosting', icon: GitBranch, type: 'infra', row: 4, col: 1, status: true,
    detail: { tech: 'Gitea 1.21, REST API', description: 'Hosted git repositories voor agent-gegenereerde projecten. Elke project krijgt een eigen repo met branches, PRs en code review.' } },
  { id: 'sandbox', label: 'Sandbox', subtitle: 'Isolated Docker containers', icon: Box, type: 'infra', row: 4, col: 2, status: true,
    detail: { tech: 'Open-Inspect fork, OpenCode, Docker-in-Docker', description: 'Control plane (:8787) + Manager (:8000) + per-task containers. Fire-and-forget met webhook callback. Resource limits enforced.' } },
]

// Build dynamic nodes from API data
const buildNodes = (agents, mcpServers) => {
  const agentNames = agents.map(a => a.name).join(', ')
  const serverNames = mcpServers.map(s => s.name || s.id).join(', ')
  const serverPorts = mcpServers.map(s => s.url?.match(/:(\d+)/)?.[0] || '').filter(Boolean).join(', ')

  return [
    ...STATIC_NODES,
    { id: 'agents', label: 'Agent Pipeline', subtitle: `${agents.length} agents`, icon: Bot, type: 'group', row: 3, col: 0,
      detail: { description: `${agentNames}. Zie de Agents tab voor de volledige workflow.` } },
    { id: 'mcp-servers', label: 'MCP Servers', subtitle: `${mcpServers.length} servers`, icon: Wrench, type: 'mcp', row: 3, col: 2, status: mcpServers.some(s => s.status === 'healthy'),
      detail: { tech: 'Python / FastMCP, JSON-RPC over HTTP', description: `${serverNames}. Elke tool call wordt gelogd en kan approval vereisen.` } },
  ]
}

const CONNECTIONS = [
  { from: 'user', to: 'frontend', color: '#10b981' },
  { from: 'frontend', to: 'keycloak', color: '#64748b', label: 'JWT auth' },
  { from: 'frontend', to: 'backend', color: '#0ea5e9', label: 'REST API' },
  { from: 'backend', to: 'keycloak', color: '#64748b', label: 'token verify' },
  { from: 'backend', to: 'agents', color: '#3b82f6', label: 'orchestratie' },
  { from: 'agents', to: 'mcp-servers', color: '#8b5cf6', label: 'tool calls' },
  { from: 'agents', to: 'approval', color: '#ef4444', dashed: true, label: 'approval check' },
  { from: 'approval', to: 'user', color: '#ef4444', dashed: true, label: 'HITL' },
  { from: 'backend', to: 'db', color: '#64748b' },
  { from: 'agents', to: 'gitea', color: '#64748b', label: 'code repos' },
  { from: 'agents', to: 'sandbox', color: '#64748b', label: 'coding tasks' },
]

const ROW_LABELS = {
  0: null,
  1: 'Presentatie & Security',
  2: 'API Layer',
  3: 'Orchestratie & Governance',
  4: 'Infrastructuur',
}

// =============================================================================
// ARCH NODE COMPONENT
// =============================================================================

const ArchNode = ({ node, isHovered, isDimmed, onHover, onClick }) => {
  const s = NODE_TYPES[node.type]
  return (
    <div
      data-node-id={node.id}
      onMouseEnter={() => onHover(node.id)}
      onMouseLeave={() => onHover(null)}
      onClick={() => onClick(node)}
      className={`
        group relative cursor-pointer select-none
        rounded-xl border ${s.border} ${s.bg} p-4
        transition-all duration-200 ease-out
        hover:shadow-lg hover:-translate-y-0.5
        ${isDimmed ? 'opacity-20 scale-[0.97]' : ''}
        ${isHovered ? `shadow-lg ring-2 ring-offset-1 ${s.ring}` : ''}
      `}
    >
      {node.status && (
        <span className="absolute -top-1 -right-1 flex h-2.5 w-2.5">
          <span className="absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-75 animate-ping" />
          <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-green-500" />
        </span>
      )}
      <div className="flex items-center gap-3">
        <div className={`w-10 h-10 rounded-lg ${s.iconBg} flex items-center justify-center flex-shrink-0 transition-transform duration-200 group-hover:scale-110`}>
          <node.icon className={`w-5 h-5 ${s.text}`} />
        </div>
        <div className="min-w-0">
          <div className="text-sm font-semibold text-gray-900">{node.label}</div>
          <div className="text-xs text-gray-500 leading-tight">{node.subtitle}</div>
        </div>
      </div>
    </div>
  )
}

// =============================================================================
// CONNECTION LINES (SVG)
// =============================================================================

const CSS = `
@keyframes flowDash { to { stroke-dashoffset: -20; } }
.arch-line { stroke-dasharray: 6 4; animation: flowDash 1s linear infinite; }
.arch-line-hl { stroke-dasharray: 6 4; animation: flowDash 0.5s linear infinite; filter: drop-shadow(0 0 2px currentColor); }
.arch-line-dim { opacity: 0.05; }
@keyframes slideIn { from { transform: translateX(100%); } to { transform: translateX(0); } }
.animate-slideIn { animation: slideIn 0.25s ease-out; }
`

const ConnectionLines = ({ connections, hoveredNode, containerRef }) => {
  const [paths, setPaths] = useState([])

  const compute = useCallback(() => {
    if (!containerRef.current) return
    const c = containerRef.current
    const rect = c.getBoundingClientRect()

    setPaths(connections.map(conn => {
      const fromEl = c.querySelector(`[data-node-id="${conn.from}"]`)
      const toEl = c.querySelector(`[data-node-id="${conn.to}"]`)
      if (!fromEl || !toEl) return null

      const fr = fromEl.getBoundingClientRect()
      const tr = toEl.getBoundingClientRect()
      const x1 = fr.left + fr.width / 2 - rect.left
      const y1 = fr.top + fr.height - rect.top
      const x2 = tr.left + tr.width / 2 - rect.left
      const y2 = tr.top - rect.top

      const dy = Math.abs(y2 - y1)
      const cp = Math.min(dy * 0.4, 50)
      const d = dy < 10
        ? `M ${x1} ${y1} C ${(x1+x2)/2} ${y1}, ${(x1+x2)/2} ${y2}, ${x2} ${y2}`
        : `M ${x1} ${y1} C ${x1} ${y1 + cp}, ${x2} ${y2 - cp}, ${x2} ${y2}`

      return { ...conn, d }
    }).filter(Boolean))
  }, [connections, containerRef])

  useEffect(() => {
    compute()
    window.addEventListener('resize', compute)
    return () => window.removeEventListener('resize', compute)
  }, [compute])

  useEffect(() => { const t = setTimeout(compute, 50); return () => clearTimeout(t) }, [hoveredNode, compute])

  const cls = (conn) => {
    if (!hoveredNode) return 'arch-line'
    return (conn.from === hoveredNode || conn.to === hoveredNode) ? 'arch-line-hl' : 'arch-line-dim'
  }

  return (
    <svg className="absolute inset-0 w-full h-full pointer-events-none" style={{ zIndex: 0 }}>
      <defs>
        <marker id="arr" markerWidth="6" markerHeight="5" refX="6" refY="2.5" orient="auto">
          <polygon points="0 0, 6 2.5, 0 5" fill="#94a3b8" opacity="0.5" />
        </marker>
      </defs>
      {paths.map((p, i) => (
        <g key={i}>
          <path d={p.d} fill="none" stroke={p.color} strokeWidth={hoveredNode && (p.from === hoveredNode || p.to === hoveredNode) ? 2.5 : 1.5} className={cls(p)} markerEnd="url(#arr)" />
          {hoveredNode && (p.from === hoveredNode || p.to === hoveredNode) && (
            <circle r="3" fill={p.color} opacity="0.8">
              <animateMotion dur="1.8s" repeatCount="indefinite" path={p.d} />
            </circle>
          )}
          {/* Label on highlighted connection */}
          {hoveredNode && (p.from === hoveredNode || p.to === hoveredNode) && p.label && (() => {
            // Find midpoint from the path for label placement
            return null // Labels shown via tooltip on hover, not inline, to keep it clean
          })()}
        </g>
      ))}
    </svg>
  )
}

// =============================================================================
// DETAIL PANEL
// =============================================================================

const DetailPanel = ({ node, nodes, connections, onClose }) => {
  if (!node) return null
  const s = NODE_TYPES[node.type]

  return (
    <div className="fixed inset-y-0 right-0 w-80 bg-white shadow-2xl border-l border-gray-200 z-50 animate-slideIn overflow-y-auto">
      <div className="p-5">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2.5">
            <div className={`w-9 h-9 rounded-lg ${s.iconBg} flex items-center justify-center`}>
              <node.icon className={`w-4.5 h-4.5 ${s.text}`} />
            </div>
            <div>
              <h3 className="text-sm font-semibold text-gray-900">{node.label}</h3>
              <p className="text-xs text-gray-500">{node.subtitle}</p>
            </div>
          </div>
          <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-gray-100">
            <X className="w-4 h-4 text-gray-400" />
          </button>
        </div>

        {node.status && (
          <div className="flex items-center gap-2 mb-4 px-2.5 py-2 bg-green-50 rounded-lg">
            <span className="w-2 h-2 rounded-full bg-green-500" />
            <span className="text-xs text-green-700 font-medium">Healthy</span>
          </div>
        )}

        {node.detail?.description && (
          <div className="mb-4">
            <h4 className="text-xs font-medium text-gray-400 uppercase tracking-wide mb-1.5">Beschrijving</h4>
            <p className="text-sm text-gray-600 leading-relaxed">{node.detail.description}</p>
          </div>
        )}

        {node.detail?.tech && (
          <div className="mb-4">
            <h4 className="text-xs font-medium text-gray-400 uppercase tracking-wide mb-1.5">Technologie Stack</h4>
            <div className="flex flex-wrap gap-1">
              {node.detail.tech.split(', ').map(t => (
                <span key={t} className="px-2 py-0.5 text-xs bg-gray-100 text-gray-700 rounded font-mono">{t}</span>
              ))}
            </div>
          </div>
        )}

        <div>
          <h4 className="text-xs font-medium text-gray-400 uppercase tracking-wide mb-1.5">Verbindingen</h4>
          <div className="space-y-1">
            {connections.filter(c => c.from === node.id || c.to === node.id).map((c, i) => {
              const otherId = c.from === node.id ? c.to : c.from
              const other = nodes.find(n => n.id === otherId)
              return (
                <div key={i} className="flex items-center gap-2 text-xs text-gray-600 py-1">
                  <ArrowRight className="w-3 h-3 text-gray-400" />
                  <span className="font-medium">{other?.label || otherId}</span>
                  {c.label && <span className="text-gray-400 italic">- {c.label}</span>}
                </div>
              )
            })}
          </div>
        </div>
      </div>
    </div>
  )
}

// =============================================================================
// INTERACTIVE DIAGRAM (accepts dynamic nodes)
// =============================================================================

const InteractiveDiagram = ({ nodes, connections }) => {
  const containerRef = useRef(null)
  const [hoveredNode, setHoveredNode] = useState(null)
  const [selectedNode, setSelectedNode] = useState(null)

  const isConnected = (nodeId) => {
    if (!hoveredNode) return null
    if (nodeId === hoveredNode) return true
    return connections.some(c =>
      (c.from === hoveredNode && c.to === nodeId) ||
      (c.to === hoveredNode && c.from === nodeId)
    )
  }

  // Only render connections where both endpoints exist
  const nodeIds = new Set(nodes.map(n => n.id))
  const validConnections = connections.filter(c => nodeIds.has(c.from) && nodeIds.has(c.to))

  const rows = {}
  nodes.forEach(n => { if (!rows[n.row]) rows[n.row] = []; rows[n.row].push(n) })

  return (
    <div className="relative">
      <style>{CSS}</style>
      <div ref={containerRef} className="relative">
        <ConnectionLines connections={validConnections} hoveredNode={hoveredNode} containerRef={containerRef} />
        <div className="relative z-10 space-y-8 py-2">
          {Object.entries(rows).sort(([a], [b]) => a - b).map(([row, rowNodes]) => (
            <div key={row}>
              {ROW_LABELS[row] && (
                <div className="text-[10px] font-medium text-gray-400 uppercase tracking-widest mb-2 pl-1">{ROW_LABELS[row]}</div>
              )}
              <div className="grid grid-cols-3 gap-4">
                {Array.from({ length: 3 }).map((_, col) => {
                  const node = rowNodes.find(n => n.col === col)
                  if (!node) return <div key={col} />
                  const conn = isConnected(node.id)
                  return <ArchNode key={node.id} node={node} isHovered={conn === true} isDimmed={conn === false} onHover={setHoveredNode} onClick={setSelectedNode} />
                })}
              </div>
            </div>
          ))}
        </div>
      </div>

      {selectedNode && (
        <>
          <div className="fixed inset-0 bg-black/10 z-40" onClick={() => setSelectedNode(null)} />
          <DetailPanel node={selectedNode} nodes={nodes} connections={validConnections} onClose={() => setSelectedNode(null)} />
        </>
      )}
    </div>
  )
}

// =============================================================================
// OVERVIEW TAB
// =============================================================================

const CATEGORY_COLORS = {
  system: { bg: 'bg-blue-50', text: 'text-blue-700', dot: 'bg-blue-500' },
  execution: { bg: 'bg-green-50', text: 'text-green-700', dot: 'bg-green-500' },
  quality: { bg: 'bg-amber-50', text: 'text-amber-700', dot: 'bg-amber-500' },
  deployment: { bg: 'bg-purple-50', text: 'text-purple-700', dot: 'bg-purple-500' },
}

const OverviewTab = () => {
  const { data: agentsData } = useQuery({ queryKey: ['architecture-agents'], queryFn: getArchitectureAgents })
  const { data: mcpData } = useQuery({ queryKey: ['architecture-mcp-servers'], queryFn: getMCPServers })
  const { data: statusData } = useQuery({ queryKey: ['api-status'], queryFn: getStatus })

  const agents = agentsData?.agents || []
  const mcpServers = Array.isArray(mcpData) ? mcpData : (mcpData?.servers || [])
  const systemHealthy = statusData ? (statusData.keycloak && statusData.database && statusData.llm) : false

  const agentsByCategory = agents.reduce((acc, a) => { const c = a.category || 'execution'; if (!acc[c]) acc[c] = []; acc[c].push(a); return acc }, {})
  const categoryLabels = { system: 'System', execution: 'Execution', quality: 'Quality', deployment: 'Deployment' }

  return (
    <div className="space-y-8">
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        <StatCard title="Agents" value={agents.length} icon={Bot} color="bg-blue-500" />
        <StatCard title="MCP Servers" value={mcpServers.length} icon={Server} color="bg-purple-500" />
        <StatCard title="Rollen" value={5} icon={Shield} color="bg-amber-500" />
        <StatCard title="Systeem Status" value={statusData ? (systemHealthy ? 'Healthy' : 'Degraded') : '...'} icon={Activity} color={systemHealthy ? 'bg-green-500' : 'bg-red-500'} />
      </div>

      {/* Interactive Architecture Diagram */}
      <div className="p-[1px] rounded-xl bg-gradient-to-br from-blue-200 via-purple-100 to-emerald-200">
        <div className="bg-white rounded-xl overflow-hidden">
          <div className="px-6 pt-5 pb-2 border-b border-gray-100">
            <h2 className="text-sm font-medium text-gray-400 uppercase tracking-wide">Systeem Architectuur</h2>
            <p className="text-xs text-gray-400 mt-0.5">Hover over componenten om verbindingen te zien. Klik voor details en technologie stack.</p>
          </div>
          <div className="relative p-6" style={{ backgroundImage: 'radial-gradient(circle, #e5e7eb 0.5px, transparent 0.5px)', backgroundSize: '20px 20px' }}>
            <InteractiveDiagram nodes={buildNodes(agents, mcpServers)} connections={CONNECTIONS} />
          </div>
          <div className="flex flex-wrap items-center gap-5 px-6 py-3 border-t border-gray-100 bg-gray-50/50">
            {[
              { color: 'bg-emerald-500', label: 'Frontend' },
              { color: 'bg-sky-500', label: 'Backend' },
              { color: 'bg-blue-500', label: 'Agent Pipeline' },
              { color: 'bg-purple-500', label: 'MCP Servers' },
              { color: 'bg-slate-400', label: 'Infrastructuur' },
              { color: 'bg-red-500', label: 'Governance' },
            ].map(item => (
              <div key={item.label} className="flex items-center gap-1.5 text-xs text-gray-500">
                <span className={`w-2 h-2 rounded-full ${item.color}`} />
                {item.label}
              </div>
            ))}
            <div className="flex items-center gap-1.5 text-xs text-gray-500">
              <span className="flex h-2.5 w-2.5"><span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-green-400 animate-ping opacity-75" /></span>
              Live status
            </div>
          </div>
        </div>
      </div>

      {/* Quick Reference */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="bg-white rounded-xl border border-gray-100 p-6">
          <h2 className="text-sm font-medium text-gray-400 uppercase tracking-wide mb-4">Agent Categorieën</h2>
          <div className="space-y-4">
            {Object.entries(categoryLabels).map(([cat, label]) => {
              const catAgents = agentsByCategory[cat] || []
              const colors = CATEGORY_COLORS[cat]
              return (
                <div key={cat}>
                  <div className="flex items-center gap-2 mb-1.5">
                    <div className={`w-2 h-2 rounded-full ${colors.dot}`} />
                    <span className="text-sm font-medium text-gray-900">{label}</span>
                    <span className="text-xs text-gray-400">{catAgents.length} agents</span>
                  </div>
                  <div className="flex flex-wrap gap-1 ml-4">
                    {catAgents.map(a => (
                      <span key={a.id} className={`px-2 py-0.5 text-xs rounded ${colors.bg} ${colors.text}`}>{a.name}</span>
                    ))}
                  </div>
                </div>
              )
            })}
          </div>
        </div>

        <div className="bg-white rounded-xl border border-gray-100 p-6">
          <h2 className="text-sm font-medium text-gray-400 uppercase tracking-wide mb-4">MCP Servers</h2>
          <div className="space-y-3">
            {mcpServers.map(server => (
              <div key={server.id} className="flex items-center gap-3 p-2 rounded-lg hover:bg-gray-50 transition-colors">
                <div className={`w-2 h-2 rounded-full flex-shrink-0 ${server.status === 'healthy' ? 'bg-green-500' : 'bg-red-500'}`} />
                <div className="flex-1 min-w-0">
                  <span className="text-sm font-medium text-gray-900">{server.name}</span>
                  <span className="text-xs text-gray-400 ml-2">{server.url?.match(/:(\d+)/)?.[0] || ''}</span>
                </div>
                <span className={`text-xs px-2 py-0.5 rounded-full ${server.status === 'healthy' ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'}`}>
                  {server.status}
                </span>
              </div>
            ))}
            {mcpServers.length === 0 && <p className="text-sm text-gray-400">Laden...</p>}
          </div>
        </div>
      </div>

      <AskArchitectFooter />
    </div>
  )
}

export default OverviewTab
