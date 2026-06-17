/**
 * ContinueDialog - Shows paused agent tree with optional context input before resuming.
 *
 * Fetches /sessions/{id}/resumable, displays tree of paused runs,
 * lets user optionally add context message, then resumes.
 */
import { useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { PlayCircle, Loader2, ChevronRight } from 'lucide-react'
import { getResumableRuns, resumeSession } from '../../services/api'
import { getAgentConfig, getAgentMessageColors } from '../../utils/agentConfig'

const ContinueDialog = ({ sessionId, onClose }) => {
  const queryClient = useQueryClient()
  const [context, setContext] = useState('')
  const [selectedLeafId, setSelectedLeafId] = useState(null)

  const { data: resumableData, isLoading } = useQuery({
    queryKey: ['resumable', sessionId],
    queryFn: () => getResumableRuns(sessionId),
    enabled: !!sessionId,
    staleTime: 0,
  })

  const runs = resumableData?.runs || []
  const leafIds = resumableData?.leaf_ids || []

  // Auto-select first leaf when data loads
  useEffect(() => {
    if (leafIds.length === 1) setSelectedLeafId(leafIds[0])
  }, [leafIds])

  const resumeMutation = useMutation({
    mutationFn: () => {
      const ctx = context.trim() || null
      const target = selectedLeafId || (leafIds.length === 1 ? leafIds[0] : null)
      return resumeSession(sessionId, ctx, target)
    },
    onSuccess: () => {
      queryClient.refetchQueries({ queryKey: ['session', sessionId] })
      queryClient.invalidateQueries({ queryKey: ['sessions'] })
      onClose()
    },
  })

  const handleSubmit = (e) => {
    e.preventDefault()
    resumeMutation.mutate()
  }

  return (
    <>
      <div className="fixed inset-0 bg-black/30 z-30" onClick={onClose} />
      <div className="fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 z-40 bg-white rounded-lg shadow-2xl border border-gray-200 p-5 w-[32rem]">
        {/* Header */}
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

        {/* Paused agents tree */}
        {!isLoading && runs.length > 0 && (
          <div className="mb-4">
            <label className="block text-xs font-medium text-gray-500 mb-2">
              {leafIds.length > 1 ? 'Select agent to resume' : 'Paused agents'}
            </label>
            <div className="space-y-1 max-h-48 overflow-y-auto bg-gray-50 border border-gray-200 rounded p-2">
              {runs.map((run) => {
                const config = getAgentConfig(run.agent_id)
                const colors = getAgentMessageColors(config.color)
                const AgentIcon = config.icon
                const selectable = run.is_leaf && leafIds.length > 1
                const isSelected = selectedLeafId === run.id
                return (
                  <div
                    key={run.id}
                    onClick={selectable ? () => setSelectedLeafId(isSelected ? null : run.id) : undefined}
                    className={`flex items-center gap-1.5 px-2 py-1 rounded text-xs ${
                      selectable ? 'cursor-pointer hover:bg-white' : ''
                    } ${isSelected ? 'bg-green-50 ring-1 ring-green-300' : ''}`}
                    style={{ paddingLeft: `${0.5 + run.depth * 1.2}rem` }}
                  >
                    {run.depth > 0 && (
                      <ChevronRight className="w-3 h-3 text-gray-300 flex-shrink-0" />
                    )}
                    <AgentIcon className={`w-3.5 h-3.5 flex-shrink-0 ${colors.accent}`} />
                    <span className={`font-medium ${colors.accent}`}>{config.name}</span>
                    {!run.is_leaf && (
                      <span className="text-gray-400 ml-1">(parent)</span>
                    )}
                    {run.is_leaf && leafIds.length <= 1 && (
                      <span className="text-green-600 ml-auto text-[10px]">will resume</span>
                    )}
                    {isSelected && (
                      <span className="text-green-600 ml-auto text-[10px]">selected</span>
                    )}
                  </div>
                )
              })}
            </div>
          </div>
        )}

        {/* Context textarea */}
        <div className="mb-4">
          <label className="block text-xs font-medium text-gray-500 mb-1">
            Additional context (optional)
          </label>
          <textarea
            value={context}
            onChange={(e) => setContext(e.target.value)}
            disabled={resumeMutation.isPending}
            placeholder="Add context or instructions for the agent…"
            rows={3}
            className="w-full text-xs font-mono bg-gray-50 border border-gray-200 rounded p-2.5 resize-y focus:outline-none focus:ring-1 focus:ring-green-400 focus:border-green-400 disabled:opacity-50"
          />
          <p className="text-[10px] text-gray-400 mt-1">
            Injected as a system message before the agent continues.
          </p>
        </div>

        {/* Error */}
        {resumeMutation.isError && (
          <div className="mb-3 bg-red-50 border border-red-200 rounded p-2 text-xs text-red-700">
            Resume failed: {resumeMutation.error?.message || 'Unknown error'}
          </div>
        )}

        {/* Actions */}
        <div className="flex justify-end gap-2">
          <button
            onClick={onClose}
            disabled={resumeMutation.isPending}
            className="px-3 py-1.5 text-sm text-gray-600 rounded-md hover:bg-gray-100 transition-colors disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            onClick={handleSubmit}
            disabled={resumeMutation.isPending || isLoading || (leafIds.length > 1 && !selectedLeafId)}
            className="px-3 py-1.5 text-sm font-medium bg-green-600 text-white rounded-md hover:bg-green-700 disabled:opacity-50 transition-colors flex items-center gap-1.5"
          >
            {resumeMutation.isPending ? (
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
            ) : (
              <PlayCircle className="w-3.5 h-3.5" />
            )}
            Continue
          </button>
        </div>
      </div>
    </>
  )
}

export default ContinueDialog
