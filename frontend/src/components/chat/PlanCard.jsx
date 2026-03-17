/**
 * PlanCard - Displays the builder_plan.md created by the builder_planner agent.
 *
 * Props: { content: string } — the raw markdown content of builder_plan.md
 */

import { useState, useMemo } from 'react'
import { ClipboardList, ChevronDown, ChevronRight } from 'lucide-react'

/** Parse markdown into top-level ## sections */
const parseSections = (markdown) => {
  const sections = []
  const lines = markdown.split('\n')
  let current = null

  for (const line of lines) {
    const match = line.match(/^##\s+(.+)/)
    if (match) {
      if (current) sections.push(current)
      current = { title: match[1].trim(), lines: [] }
    } else if (current) {
      current.lines.push(line)
    }
  }
  if (current) sections.push(current)

  return sections.map((s) => ({
    title: s.title,
    body: s.lines.join('\n').trim(),
  }))
}

const PlanCard = ({ content }) => {
  const [isExpanded, setIsExpanded] = useState(false)

  const sections = useMemo(() => content ? parseSections(content) : [], [content])

  if (!sections.length) return null

  return (
    <div className="rounded-xl border bg-gray-50 border-gray-200 border-l-4 border-l-indigo-400 transition-all">
      {/* Header */}
      <div className="px-4 pt-3 pb-2">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <ClipboardList className="w-4 h-4 text-indigo-500" />
            <span className="text-sm font-medium text-gray-800">
              Builder Plan
            </span>
          </div>
          <button
            onClick={() => setIsExpanded(!isExpanded)}
            className="flex items-center gap-1 text-xs text-gray-400 hover:text-gray-600 transition-colors"
          >
            {isExpanded ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />}
            {isExpanded ? 'Collapse' : 'Details'}
          </button>
        </div>

        {/* Summary line: section names */}
        <div className="mt-1.5 flex items-center gap-1 text-xs text-gray-500 flex-wrap">
          {sections.map((s, i) => (
            <span key={i} className="flex items-center gap-1">
              {i > 0 && <span className="text-gray-300">&middot;</span>}
              <span>{s.title}</span>
            </span>
          ))}
        </div>
      </div>

      {/* Expanded: section contents */}
      {isExpanded && (
        <div className="px-4 pb-3 border-t border-gray-200">
          <div className="mt-2 space-y-3">
            {sections.map((s, i) => (
              <div key={i}>
                <h4 className="text-xs font-semibold text-gray-700">{s.title}</h4>
                <pre className="mt-1 text-xs text-gray-500 whitespace-pre-wrap break-words font-sans leading-relaxed">
                  {s.body}
                </pre>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

export default PlanCard
