/**
 * ContinueDialog - Shows paused agents with optional per-agent context input.
 *
 * Fetches /sessions/{id}/resumable, displays each leaf agent with a textarea.
 * All agents resume on confirm — no selection.
 */
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { PlayCircle, Loader2, ChevronRight } from 'lucide-react'
import { getResumableRuns, resumeSession } from '../../services/api'
import { getAgentConfig, getAgentMessageColors } from '../../utils/agentConfig'

const ContinueDialog = ({ sessionId, onClose }) => {
  const queryClient = useQueryClient()
  const [contexts, setContexts] = useState({})

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

  const leafRuns = runs.filter(r => r.is_leaf)

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

        {!isLoading && leafRuns.length > 0 && (
          <div className="mb-4">
            <p className="text-xs text-gray-500 mb-3">
              All {leafRuns.length} agent{leafRuns.length !== 1 ? 's' : ''} will resume. Add optional context below any agent.
            </p>
            <div className="space-y-3">
              {leafRuns.map((run) => {
                const config = getAgentConfig(run.agent_id)
                const colors = getAgentMessageColors(config.color)
                const AgentIcon = config.icon
                return (
                  <div key={run.id} className="bg-gray-50 border border-gray-200 rounded p-2.5">
                    <div className="flex items-center gap-1.5 px-1 mb-1.5" style={{ paddingLeft: `${0.5 + run.depth * 1.0}rem` }}>
                      {run.depth > 0 && <ChevronRight className="w-3 h-3 text-gray-300 flex-shrink-0" />}
                      <AgentIcon className={`w-3.5 h-3.5 flex-shrink-0 ${colors.accent}`} />
                      <span className={`text-xs font-medium ${colors.accent}`}>{config.name}</span>
                    </div>
                    <textarea
                      value={contexts[run.id] || ''}
                      onChange={(e) => setContexts(prev => ({ ...prev, [run.id]: e.target.value }))}
                      disabled={resumeMutation.isPending}
                      placeholder="Optional context…"
                      rows={2}
                      className="w-full text-xs font-mono bg-white border border-gray-200 rounded p-2 resize-y focus:outline-none focus:ring-1 focus:ring-green-400 focus:border-green-400 disabled:opacity-50"
                    />
                  </div>
                )
              })}
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
