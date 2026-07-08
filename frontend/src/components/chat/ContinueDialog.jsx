import { useState, useMemo, useCallback } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { PlayCircle, Loader2, ChevronRight, ChevronDown, CornerDownRight } from 'lucide-react'
import { getResumableRuns, resumeSession } from '../../services/api'
import { getAgentConfig, getAgentMessageColors } from '../../utils/agentConfig'

const AgentNode = ({ node, depth, contexts, onContextChange, expandedPrompts, onTogglePrompt, disabled }) => {
  const config = getAgentConfig(node.agent_id)
  const colors = getAgentMessageColors(config.color)
  const AgentIcon = config.icon
  const isParent = node.children.length > 0
  const isExpanded = expandedPrompts[node.id]

  return (
    <div>
      <div className={`rounded p-2.5 ${depth === 0 ? 'bg-gray-50 border border-gray-200' : ''} ${depth > 0 ? 'bg-white' : ''}`}>
        <div className="flex items-center gap-1.5 px-1 mb-1.5" style={{ paddingLeft: `${0.5 + depth * 1.25}rem` }}>
          {depth > 0 && <CornerDownRight className="w-3 h-3 text-gray-300 flex-shrink-0" />}
          <AgentIcon className={`w-3.5 h-3.5 flex-shrink-0 ${colors.accent}`} />
          <span className={`text-xs font-medium ${colors.accent}`}>{config.name}</span>
          {isParent && (
            <span className="text-[9px] text-gray-400 bg-gray-100 px-1.5 py-0.5 rounded-full">
              resumes after children
            </span>
          )}
          {node.planned_prompt && (
            <button
              onClick={() => onTogglePrompt(node.id)}
              className="ml-auto text-gray-400 hover:text-gray-600 transition-colors"
              title={isExpanded ? 'Hide prompt' : 'Show prompt'}
            >
              {isExpanded
                ? <ChevronDown className="w-3.5 h-3.5" />
                : <ChevronRight className="w-3.5 h-3.5" />}
            </button>
          )}
        </div>
        {isExpanded && node.planned_prompt && (
          <pre className="text-[10px] font-mono text-gray-500 bg-white border border-gray-100 rounded p-2 mb-2 max-h-32 overflow-y-auto whitespace-pre-wrap" style={{ marginLeft: `${0.5 + depth * 1.25}rem` }}>{node.planned_prompt}</pre>
        )}
        <textarea
          value={contexts[node.id] || ''}
          onChange={(e) => onContextChange(node.id, e.target.value)}
          disabled={disabled}
          placeholder={isParent ? "Optional context — injected after children finish…" : "Optional context…"}
          rows={2}
          className="w-full text-xs font-mono bg-white border border-gray-200 rounded p-2 resize-y focus:outline-none focus:ring-1 focus:ring-green-400 focus:border-green-400 disabled:opacity-50"
        />
      </div>
      {node.children.map(child => (
        <AgentNode
          key={child.id}
          node={child}
          depth={depth + 1}
          contexts={contexts}
          onContextChange={onContextChange}
          expandedPrompts={expandedPrompts}
          onTogglePrompt={onTogglePrompt}
          disabled={disabled}
        />
      ))}
    </div>
  )
}

const ContinueDialog = ({ sessionId, onClose }) => {
  const queryClient = useQueryClient()
  const [contexts, setContexts] = useState({})
  const [expandedPrompts, setExpandedPrompts] = useState({})

  const { data: resumableData, isLoading } = useQuery({
    queryKey: ['resumable', sessionId],
    queryFn: () => getResumableRuns(sessionId),
    enabled: !!sessionId,
    staleTime: 0,
  })

  const runs = resumableData?.runs || []

  const resumeMutation = useMutation({
    mutationFn: () => {
      const filtered = {}
      for (const [id, text] of Object.entries(contexts)) {
        if (text.trim()) filtered[id] = text.trim()
      }
      return resumeSession(sessionId, Object.keys(filtered).length > 0 ? filtered : null)
    },
    onSuccess: () => {
      queryClient.refetchQueries({ queryKey: ['session', sessionId] })
      queryClient.invalidateQueries({ queryKey: ['sessions'] })
      onClose()
    },
  })

  const tree = useMemo(() => {
    const byId = {}
    const roots = []
    for (const run of runs) {
      byId[run.id] = { ...run, children: [] }
    }
    for (const run of Object.values(byId)) {
      if (run.parent_run_id && byId[run.parent_run_id]) {
        byId[run.parent_run_id].children.push(run)
      } else {
        roots.push(run)
      }
    }
    return roots
  }, [runs])

  const togglePrompt = useCallback((runId) =>
    setExpandedPrompts(prev => ({ ...prev, [runId]: !prev[runId] })), [])

  const handleContextChange = useCallback((runId, value) =>
    setContexts(prev => ({ ...prev, [runId]: value })), [])

  return (
    <>
      <div className="fixed inset-0 bg-black/30 z-30" onClick={onClose} />
      <div className="fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 z-40 bg-white rounded-lg shadow-2xl border border-gray-200 p-5 w-[34rem] max-h-[85vh] overflow-y-auto">
        <div className="flex items-center gap-2 mb-3">
          <PlayCircle className="w-5 h-5 text-green-600" />
          <h3 className="text-sm font-semibold text-gray-900">Continue session</h3>
        </div>

        {isLoading && (
          <div className="flex items-center gap-2 py-8 justify-center">
            <Loader2 className="w-4 h-4 animate-spin text-gray-400" />
            <span className="text-sm text-gray-500">Loading paused agents…</span>
          </div>
        )}

        {!isLoading && runs.length > 0 && (
          <div className="mb-4">
            <p className="text-xs text-gray-500 mb-3">
              All agents will resume. Leaf agents run immediately — parent agents continue after their children finish. Add optional context to any agent.
            </p>
            <div className="space-y-1">
              {tree.map(node => (
                <AgentNode
                  key={node.id}
                  node={node}
                  depth={0}
                  contexts={contexts}
                  onContextChange={handleContextChange}
                  expandedPrompts={expandedPrompts}
                  onTogglePrompt={togglePrompt}
                  disabled={resumeMutation.isPending}
                />
              ))}
            </div>
          </div>
        )}

        {resumeMutation.isError && (
          <div className="mb-3 bg-red-50 border border-red-200 rounded p-2 text-xs text-red-700">
            Resume failed: {resumeMutation.error?.message || 'Unknown error'}
          </div>
        )}

        <div className="flex justify-end gap-2">
          <button
            onClick={onClose}
            disabled={resumeMutation.isPending}
            className="px-3 py-1.5 text-sm text-gray-600 rounded-md hover:bg-gray-100 transition-colors disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            onClick={(e) => { e.preventDefault(); resumeMutation.mutate() }}
            disabled={resumeMutation.isPending || isLoading}
            className="px-3 py-1.5 text-sm font-medium bg-green-600 text-white rounded-md hover:bg-green-700 disabled:opacity-50 transition-colors flex items-center gap-1.5"
          >
            {resumeMutation.isPending ? (
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
            ) : (
              <PlayCircle className="w-3.5 h-3.5" />
            )}
            Continue all
          </button>
        </div>
      </div>
    </>
  )
}

export default ContinueDialog
