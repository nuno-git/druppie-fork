import { useState, useRef, useEffect, useCallback } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  Bot, ChevronDown, ChevronRight, Cpu, Zap, GitBranch, Layers, FileText,
  Code, Wrench, TestTube, Rocket, MessageSquare, ArrowRight, X, Shield,
  RefreshCw, Settings
} from 'lucide-react'
import AskArchitectFooter from './AskArchitectFooter'
import { getArchitectureAgents, getArchitectureWorkflow } from '../../services/api'

// =============================================================================
// WORKFLOW DIAGRAM - Full agent pipeline
// =============================================================================

const NODE_TYPES = {
  system:     { bg: 'bg-blue-50', border: 'border-blue-200', iconBg: 'bg-blue-100', text: 'text-blue-700', ring: 'ring-blue-300' },
  execution:  { bg: 'bg-green-50', border: 'border-green-200', iconBg: 'bg-green-100', text: 'text-green-700', ring: 'ring-green-300' },
  quality:    { bg: 'bg-amber-50', border: 'border-amber-200', iconBg: 'bg-amber-100', text: 'text-amber-700', ring: 'ring-amber-300' },
  deployment: { bg: 'bg-purple-50', border: 'border-purple-200', iconBg: 'bg-purple-100', text: 'text-purple-700', ring: 'ring-purple-300' },
  special:    { bg: 'bg-rose-50', border: 'border-rose-200', iconBg: 'bg-rose-100', text: 'text-rose-700', ring: 'ring-rose-300' },
}

// Known agent positions in the workflow diagram.
// Agents from the API that match these IDs get placed at the specified row/col.
// Agents that don't match any known ID get auto-placed in an "Extra" row.
const KNOWN_POSITIONS = {
  router:              { row: 0, col: 1, icon: GitBranch },
  planner:             { row: 1, col: 1, icon: Layers },
  business_analyst:    { row: 2, col: 0, icon: FileText },
  architect:           { row: 2, col: 2, icon: Layers },
  builder_planner:     { row: 3, col: 0, icon: Settings },
  update_core_builder: { row: 3, col: 2, icon: RefreshCw },
  test_builder:        { row: 4, col: 0, icon: TestTube },
  builder:             { row: 4, col: 1, icon: Code },
  test_executor:       { row: 4, col: 2, icon: TestTube },
  deployer:            { row: 5, col: 0, icon: Rocket },
  developer:           { row: 5, col: 1, icon: Code },
  summarizer:          { row: 5, col: 2, icon: MessageSquare },
  reviewer:            { row: 5, col: 2, icon: Shield }, // shares slot with summarizer if both exist
}

const CATEGORY_TO_TYPE = {
  system: 'system',
  execution: 'execution',
  quality: 'quality',
  deployment: 'deployment',
}

// Build flow nodes dynamically from API agent data
const buildFlowNodes = (agents) => {
  const nodes = []
  const usedPositions = new Set()
  let extraRow = 6
  let extraCol = 0

  agents.forEach(agent => {
    const known = KNOWN_POSITIONS[agent.id]
    let row, col, icon

    if (known) {
      const posKey = `${known.row}:${known.col}`
      if (!usedPositions.has(posKey)) {
        row = known.row
        col = known.col
        usedPositions.add(posKey)
      } else {
        // Position conflict - place in extra row
        row = extraRow
        col = extraCol
        extraCol++
        if (extraCol >= 3) { extraCol = 0; extraRow++ }
      }
      icon = known.icon
    } else {
      // Unknown agent - auto-place in extra row
      row = extraRow
      col = extraCol
      icon = Bot
      extraCol++
      if (extraCol >= 3) { extraCol = 0; extraRow++ }
    }

    nodes.push({
      id: agent.id,
      label: agent.name,
      subtitle: agent.description?.substring(0, 50) + (agent.description?.length > 50 ? '...' : ''),
      icon,
      type: CATEGORY_TO_TYPE[agent.category] || 'execution',
      row,
      col,
    })
  })

  return nodes
}

// Connections are loaded dynamically from the API via getArchitectureWorkflow()

const FLOW_ROW_LABELS = {
  0: 'Intake',
  1: 'Orchestratie',
  2: 'Design Loop',
  3: 'Planning',
  4: 'TDD Loop',
  5: 'Executie & Deployment',
  6: 'Extra Agents',
}

const CSS = `
@keyframes flowDash { to { stroke-dashoffset: -20; } }
.flow-line { stroke-dasharray: 6 4; animation: flowDash 1s linear infinite; }
.flow-line-hl { stroke-dasharray: 6 4; animation: flowDash 0.5s linear infinite; filter: drop-shadow(0 0 2px currentColor); }
.flow-line-dim { opacity: 0.05; }
@keyframes slideIn { from { transform: translateX(100%); } to { transform: translateX(0); } }
.animate-slideIn { animation: slideIn 0.25s ease-out; }
`

const FlowNode = ({ node, isHovered, isDimmed, onHover, onClick }) => {
  const s = NODE_TYPES[node.type]
  return (
    <div
      data-node-id={node.id}
      onMouseEnter={() => onHover(node.id)}
      onMouseLeave={() => onHover(null)}
      onClick={() => onClick(node.id)}
      className={`
        group relative cursor-pointer select-none
        rounded-xl border ${s.border} ${s.bg} p-3
        transition-all duration-200 ease-out
        hover:shadow-lg hover:-translate-y-0.5
        ${isDimmed ? 'opacity-20 scale-[0.97]' : ''}
        ${isHovered ? `shadow-lg ring-2 ring-offset-1 ${s.ring}` : ''}
      `}
    >
      <div className="flex items-center gap-2.5">
        <div className={`w-8 h-8 rounded-lg ${s.iconBg} flex items-center justify-center flex-shrink-0 transition-transform duration-200 group-hover:scale-110`}>
          <node.icon className={`w-4 h-4 ${s.text}`} />
        </div>
        <div className="min-w-0">
          <div className="text-xs font-semibold text-gray-900 truncate">{node.label}</div>
          <div className="text-[10px] text-gray-500 truncate leading-tight">{node.subtitle}</div>
        </div>
      </div>
    </div>
  )
}

const FlowConnections = ({ connections, hoveredNode, containerRef }) => {
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
    if (!hoveredNode) return 'flow-line'
    return (conn.from === hoveredNode || conn.to === hoveredNode) ? 'flow-line-hl' : 'flow-line-dim'
  }

  return (
    <svg className="absolute inset-0 w-full h-full pointer-events-none" style={{ zIndex: 0 }}>
      <defs>
        <marker id="flow-arr" markerWidth="6" markerHeight="5" refX="6" refY="2.5" orient="auto">
          <polygon points="0 0, 6 2.5, 0 5" fill="#94a3b8" opacity="0.5" />
        </marker>
      </defs>
      {paths.map((p, i) => (
        <g key={i}>
          <path d={p.d} fill="none" stroke={p.color} strokeWidth={hoveredNode && (p.from === hoveredNode || p.to === hoveredNode) ? 2.5 : 1.5} className={cls(p)} markerEnd="url(#flow-arr)" />
          {hoveredNode && (p.from === hoveredNode || p.to === hoveredNode) && (
            <circle r="3" fill={p.color} opacity="0.8">
              <animateMotion dur="1.8s" repeatCount="indefinite" path={p.d} />
            </circle>
          )}
        </g>
      ))}
    </svg>
  )
}

const AgentWorkflowDiagram = ({ agents, connections, onSelectAgent }) => {
  const containerRef = useRef(null)
  const [hoveredNode, setHoveredNode] = useState(null)

  const flowNodes = buildFlowNodes(agents)

  // Only render connections where both endpoints exist in the current nodes
  const nodeIds = new Set(flowNodes.map(n => n.id))
  const validConnections = connections.filter(c => nodeIds.has(c.from) && nodeIds.has(c.to))

  const isConnected = (nodeId) => {
    if (!hoveredNode) return null
    if (nodeId === hoveredNode) return true
    return validConnections.some(c =>
      (c.from === hoveredNode && c.to === nodeId) ||
      (c.to === hoveredNode && c.from === nodeId)
    )
  }

  const rows = {}
  flowNodes.forEach(n => { if (!rows[n.row]) rows[n.row] = []; rows[n.row].push(n) })

  return (
    <div className="p-[1px] rounded-xl bg-gradient-to-br from-blue-200 via-amber-100 to-purple-200">
      <div className="bg-white rounded-xl overflow-hidden">
        <div className="px-6 pt-5 pb-2 border-b border-gray-100">
          <h2 className="text-sm font-medium text-gray-400 uppercase tracking-wide">Agent Workflow</h2>
          <p className="text-xs text-gray-400 mt-0.5">Hover om verbindingen te zien. Klik op een agent om details te bekijken.</p>
        </div>
        <div className="relative p-6" style={{ backgroundImage: 'radial-gradient(circle, #e5e7eb 0.5px, transparent 0.5px)', backgroundSize: '20px 20px' }}>
          <style>{CSS}</style>
          <div ref={containerRef} className="relative">
            <FlowConnections connections={validConnections} hoveredNode={hoveredNode} containerRef={containerRef} />
            <div className="relative z-10 space-y-6 py-2">
              {Object.entries(rows).sort(([a], [b]) => a - b).map(([row, nodes]) => (
                <div key={row}>
                  <div className="text-[10px] font-medium text-gray-400 uppercase tracking-widest mb-2 pl-1">{FLOW_ROW_LABELS[row]}</div>
                  <div className="grid grid-cols-3 gap-3">
                    {Array.from({ length: 3 }).map((_, col) => {
                      const node = nodes.find(n => n.col === col)
                      if (!node) return <div key={col} />
                      const conn = isConnected(node.id)
                      return <FlowNode key={node.id} node={node} isHovered={conn === true} isDimmed={conn === false} onHover={setHoveredNode} onClick={onSelectAgent} />
                    })}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
        {/* Legend */}
        <div className="flex flex-wrap items-center gap-5 px-6 py-3 border-t border-gray-100 bg-gray-50/50">
          {[
            { color: 'bg-blue-500', label: 'System' },
            { color: 'bg-green-500', label: 'Execution' },
            { color: 'bg-amber-500', label: 'Quality' },
            { color: 'bg-purple-500', label: 'Deployment' },
            { color: 'bg-rose-500', label: 'Core Update' },
          ].map(item => (
            <div key={item.label} className="flex items-center gap-1.5 text-xs text-gray-500">
              <span className={`w-2 h-2 rounded-full ${item.color}`} />
              {item.label}
            </div>
          ))}
          <div className="flex items-center gap-1.5 text-xs text-gray-500">
            <svg width="20" height="6"><line x1="0" y1="3" x2="20" y2="3" stroke="#f59e0b" strokeWidth="1.5" strokeDasharray="4 3" /></svg>
            Feedback / retry
          </div>
        </div>
      </div>
    </div>
  )
}

// =============================================================================
// AGENT CARDS (below the workflow)
// =============================================================================

const CATEGORY_COLORS = {
  system: { bg: 'bg-blue-50', text: 'text-blue-700' },
  execution: { bg: 'bg-green-50', text: 'text-green-700' },
  quality: { bg: 'bg-amber-50', text: 'text-amber-700' },
  deployment: { bg: 'bg-purple-50', text: 'text-purple-700' },
}

const CATEGORIES = ['all', 'system', 'execution', 'quality', 'deployment']
const CATEGORY_LABELS = { all: 'Alle', system: 'System', execution: 'Execution', quality: 'Quality', deployment: 'Deployment' }

const AgentCard = ({ agent, isHighlighted }) => {
  const [expanded, setExpanded] = useState(false)
  const colors = CATEGORY_COLORS[agent.category] || CATEGORY_COLORS.execution

  return (
    <div
      id={`agent-card-${agent.id}`}
      className={`bg-white rounded-xl border p-5 transition-all ${
        isHighlighted
          ? 'border-blue-300 ring-2 ring-blue-200 shadow-md'
          : 'border-gray-100 hover:border-gray-200 hover:shadow-sm'
      }`}
    >
      <div className="flex items-center justify-between mb-2">
        <span className={`px-2 py-0.5 text-xs rounded-full ${colors.bg} ${colors.text}`}>{agent.category}</span>
      </div>
      <h3 className="text-base font-semibold text-gray-900">{agent.name}</h3>
      <p className="text-sm text-gray-500 mt-1 line-clamp-2">{agent.description}</p>

      <div className="flex flex-wrap gap-1 mt-3">
        {agent.mcps.map(mcp => (
          <span key={mcp} className="px-2 py-0.5 bg-gray-100 text-gray-600 rounded text-xs">{mcp}</span>
        ))}
      </div>

      <div className="flex items-center justify-between mt-3 pt-3 border-t border-gray-50">
        <div className="flex items-center gap-4 text-xs text-gray-400">
          <span className="flex items-center gap-1"><Cpu className="w-3 h-3" />{agent.llm_profile}</span>
          <span className="flex items-center gap-1"><Zap className="w-3 h-3" />{agent.max_iterations} iter</span>
        </div>
        <button onClick={() => setExpanded(!expanded)} className="text-xs text-blue-600 hover:text-blue-700 flex items-center gap-0.5">
          {expanded ? 'Minder' : 'Meer'}
          {expanded ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
        </button>
      </div>

      {expanded && (
        <div className="mt-3 pt-3 border-t border-gray-100 space-y-3">
          {agent.skills.length > 0 && (
            <div>
              <span className="text-xs font-medium text-gray-400 uppercase">Skills</span>
              <div className="flex flex-wrap gap-1 mt-1">
                {agent.skills.map(skill => (
                  <span key={skill} className="px-2 py-0.5 bg-blue-50 text-blue-700 rounded text-xs">{skill}</span>
                ))}
              </div>
            </div>
          )}
          {agent.extra_builtin_tools.length > 0 && (
            <div>
              <span className="text-xs font-medium text-gray-400 uppercase">Builtin Tools</span>
              <div className="flex flex-wrap gap-1 mt-1">
                {agent.extra_builtin_tools.map(tool => (
                  <span key={tool} className="px-2 py-0.5 bg-purple-50 text-purple-700 rounded text-xs">{tool}</span>
                ))}
              </div>
            </div>
          )}
          {Object.keys(agent.mcp_tool_access || {}).length > 0 && (
            <div>
              <span className="text-xs font-medium text-gray-400 uppercase">MCP Tool Toegang</span>
              <div className="mt-1 space-y-1">
                {Object.entries(agent.mcp_tool_access).map(([mcp, tools]) => (
                  <div key={mcp} className="text-xs">
                    <span className="font-medium text-gray-700">{mcp}:</span>{' '}
                    <span className="text-gray-500">{tools ? tools.join(', ') : 'alle tools'}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
          {Object.keys(agent.approval_overrides || {}).length > 0 && (
            <div>
              <span className="text-xs font-medium text-gray-400 uppercase">Approval Overrides</span>
              <div className="mt-1 space-y-0.5">
                {Object.entries(agent.approval_overrides).map(([key, override]) => (
                  <div key={key} className="text-xs flex items-center gap-2">
                    <span className="font-mono text-gray-600">{key}</span>
                    {override.requires_approval ? (
                      <span className="px-1.5 py-0.5 bg-amber-50 text-amber-700 rounded">approval: {override.required_role || 'any'}</span>
                    ) : (
                      <span className="px-1.5 py-0.5 bg-green-50 text-green-700 rounded">auto-approved</span>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}
          <div>
            <span className="text-xs font-medium text-gray-400 uppercase">LLM Configuratie</span>
            <div className="grid grid-cols-2 gap-x-4 gap-y-1 mt-1 text-xs text-gray-600">
              <span>Profiel: <span className="font-medium">{agent.llm_profile}</span></span>
              <span>Temperature: <span className="font-medium">{agent.temperature}</span></span>
              <span>Max tokens: <span className="font-medium">{agent.max_tokens.toLocaleString()}</span></span>
              <span>Max iterations: <span className="font-medium">{agent.max_iterations}</span></span>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

// =============================================================================
// AGENTS TAB
// =============================================================================

const AgentsTab = () => {
  const [filter, setFilter] = useState('all')
  const [highlightedAgent, setHighlightedAgent] = useState(null)

  const { data, isLoading } = useQuery({
    queryKey: ['architecture-agents'],
    queryFn: getArchitectureAgents,
  })

  const { data: workflowData } = useQuery({
    queryKey: ['architecture-workflow'],
    queryFn: getArchitectureWorkflow,
  })

  const agents = data?.agents || []
  const filtered = filter === 'all' ? agents : agents.filter(a => a.category === filter)

  // Map API workflow connections to the format the diagram expects, with fallback
  const apiConnections = (workflowData?.connections || []).map(c => ({
    from: c.from_agent,
    to: c.to_agent,
    label: c.label,
    color: c.color,
    dashed: c.dashed,
  }))
  const workflowConnections = apiConnections

  const handleSelectAgent = (agentId) => {
    if (!agentId) return
    setHighlightedAgent(agentId)
    // Scroll to the agent card
    setTimeout(() => {
      const el = document.getElementById(`agent-card-${agentId}`)
      if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' })
    }, 100)
    // Clear highlight after 3 seconds
    setTimeout(() => setHighlightedAgent(null), 3000)
  }

  return (
    <div className="space-y-8">
      {/* Workflow diagram */}
      <AgentWorkflowDiagram agents={agents} connections={workflowConnections} onSelectAgent={handleSelectAgent} />

      {/* Filter bar */}
      <div className="flex flex-wrap gap-2">
        {CATEGORIES.map(cat => (
          <button
            key={cat}
            onClick={() => setFilter(cat)}
            className={`px-3 py-1.5 text-xs font-medium rounded-full transition-colors ${
              filter === cat
                ? 'bg-blue-100 text-blue-700 ring-1 ring-blue-200'
                : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
            }`}
          >
            {CATEGORY_LABELS[cat]}
            {cat !== 'all' && <span className="ml-1 text-gray-400">{agents.filter(a => a.category === cat).length}</span>}
          </button>
        ))}
      </div>

      {/* Agent cards grid */}
      {isLoading ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="bg-white rounded-xl border border-gray-100 p-5 animate-pulse">
              <div className="h-4 bg-gray-200 rounded w-16 mb-3" />
              <div className="h-5 bg-gray-200 rounded w-32 mb-2" />
              <div className="h-4 bg-gray-100 rounded w-full mb-1" />
              <div className="h-4 bg-gray-100 rounded w-3/4" />
            </div>
          ))}
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {filtered.map(agent => (
            <AgentCard key={agent.id} agent={agent} isHighlighted={highlightedAgent === agent.id} />
          ))}
        </div>
      )}

      {!isLoading && filtered.length === 0 && (
        <div className="text-center py-12">
          <Bot className="w-12 h-12 text-gray-300 mx-auto mb-3" />
          <p className="text-gray-500">Geen agents gevonden in deze categorie.</p>
        </div>
      )}

      <AskArchitectFooter />
    </div>
  )
}

export default AgentsTab
