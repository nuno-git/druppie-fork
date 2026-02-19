/**
 * AnnotationBar - Compact debug strip for agent messages in Annotated mode
 *
 * Shows tool pills with status, token count, duration, and an expand toggle.
 * Expanding reveals full LLM call detail inline via AnnotationDetail.
 */

import { useMemo, useState } from 'react'
import { ChevronDown, ChevronUp } from 'lucide-react'
import { formatToolName } from '../../utils/agentConfig'
import { formatTokens, formatDuration } from '../../utils/tokenUtils'
import AnnotationDetail from './AnnotationDetail'

const AnnotationBar = ({ run }) => {
  const [expanded, setExpanded] = useState(false)

  const { toolSummary, totalTokens, duration } = useMemo(() => {
    const toolMap = new Map()

    run.llm_calls?.forEach((llm) => {
      llm.tool_calls?.forEach((tc) => {
        if (tc.tool_name?.includes('hitl_ask')) return
        if (tc.approval) return
        const name = formatToolName(tc.tool_name)
        if (!toolMap.has(name)) {
          toolMap.set(name, { name, count: 0, failed: false })
        }
        const entry = toolMap.get(name)
        entry.count++
        if (tc.status === 'failed') entry.failed = true
      })
    })

    const toolSummary = [...toolMap.values()]
    const totalTokens = run.token_usage?.total_tokens || 0

    let duration = null
    if (run.started_at && run.completed_at) {
      duration = new Date(run.completed_at) - new Date(run.started_at)
    } else {
      const total =
        run.llm_calls?.reduce((sum, llm) => sum + (llm.duration_ms || 0), 0) || 0
      if (total > 0) duration = total
    }

    return { toolSummary, totalTokens, duration }
  }, [run])

  const llmCount = run.llm_calls?.length || 0
  const hasContent = toolSummary.length > 0 || totalTokens > 0 || llmCount > 0
  if (!hasContent) return null

  return (
    <div>
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center gap-2 text-xs text-gray-400 hover:text-gray-600 transition-colors py-1 px-1 rounded hover:bg-gray-50"
      >
        <div className="flex items-center gap-2 flex-wrap flex-1 min-w-0">
          {toolSummary.slice(0, 6).map((tool, i) => (
            <span key={i} className="inline-flex items-center gap-0.5 flex-shrink-0">
              <span className="text-gray-300">&rarr;</span>
              <span className={tool.failed ? 'text-red-500' : 'text-gray-500'}>
                {tool.name}
              </span>
              {tool.count > 1 && (
                <span className="text-gray-300">&times;{tool.count}</span>
              )}
              {!tool.failed && <span className="text-green-500">&check;</span>}
              {tool.failed && <span className="text-red-500">&times;</span>}
            </span>
          ))}
          {toolSummary.length > 6 && (
            <span className="text-gray-300 flex-shrink-0">
              +{toolSummary.length - 6} more
            </span>
          )}
        </div>
        <div className="flex items-center gap-1.5 flex-shrink-0 ml-auto">
          {totalTokens > 0 && <span>{formatTokens(totalTokens)} tok</span>}
          {duration != null && totalTokens > 0 && <span>&middot;</span>}
          {duration != null && <span>{formatDuration(duration)}</span>}
          {expanded ? (
            <ChevronUp className="w-3 h-3" />
          ) : (
            <ChevronDown className="w-3 h-3" />
          )}
        </div>
      </button>
      {expanded && <AnnotationDetail run={run} />}
    </div>
  )
}

export default AnnotationBar
