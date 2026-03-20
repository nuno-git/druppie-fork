/**
 * HITLQuestionMessage - Question bubble matching the agent message layout
 *
 * Uses the same icon-outside + name header pattern as agent messages.
 * Shows the question text and optional choice buttons (for multiple-choice).
 * When answered, shows the question with a green check.
 *
 * When `question.allowOther` is truthy and the question has choices,
 * an extra "Other" button is rendered below the choices. Clicking it
 * replaces the buttons with a textarea for a free-text answer.
 */

import { useState, useRef, useEffect } from 'react'
import { Loader2, Send, X } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { getAgentConfig, getAgentMessageColors } from '../../utils/agentConfig'
import { chatMarkdownComponents } from './ChatHelpers'

const HITLQuestionMessage = ({ question, onChoiceSelect, onSubmitChoices, isAnswering, answered = false }) => {
  const agentId = question.agent_id || 'unknown'
  const agentConfig = getAgentConfig(agentId)
  const AgentIcon = agentConfig.icon
  const colors = getAgentMessageColors(agentConfig.color)

  const hasOptions = question.choices && question.choices.length > 0

  const [selectedIndices, setSelectedIndices] = useState(new Set())
  const [showFreeText, setShowFreeText] = useState(false)
  const [freeText, setFreeText] = useState('')
  const freeTextRef = useRef(null)

  useEffect(() => {
    if (showFreeText && freeTextRef.current) {
      freeTextRef.current.focus()
    }
  }, [showFreeText])

  const handleToggleChoice = (index) => {
    setSelectedIndices((prev) => {
      const next = new Set(prev)
      if (next.has(index)) {
        next.delete(index)
      } else {
        next.add(index)
      }
      return next
    })
  }

  const handleSubmitChoices = () => {
    if (selectedIndices.size === 0) return
    const indices = [...selectedIndices].sort((a, b) => a - b)
    const answerText = indices.map((i) => question.choices[i]).join(', ')
    onSubmitChoices?.({ indices, answerText })
  }

  const handleFreeTextSubmit = () => {
    const trimmed = freeText.trim()
    if (!trimmed) return
    onChoiceSelect?.(trimmed)
  }

  return (
    <div className="group">
      <div className="flex items-center gap-2 mb-1.5">
        <div className={`w-6 h-6 rounded-full flex items-center justify-center flex-shrink-0 ${colors.bg} border ${colors.border}`}>
          <AgentIcon className={`w-3.5 h-3.5 ${colors.accent}`} />
        </div>
        <span className={`text-sm font-medium ${colors.accent}`}>{agentConfig.name}</span>
      </div>
      <div className="pl-8">
        <div className="text-sm text-gray-800 leading-relaxed markdown-content">
          <ReactMarkdown remarkPlugins={[remarkGfm]} components={chatMarkdownComponents}>{question.question}</ReactMarkdown>
        </div>

        {question.context && !answered && (
          <div className="mt-1 text-xs text-gray-500 markdown-content">
            <ReactMarkdown remarkPlugins={[remarkGfm]} components={chatMarkdownComponents}>{question.context}</ReactMarkdown>
          </div>
        )}

        {hasOptions && !answered && !showFreeText && (
          <div className="mt-2 space-y-1.5">
            {question.choices.map((option, index) => {
              const isSelected = selectedIndices.has(index)
              return (
                <button
                  key={index}
                  onClick={() => handleToggleChoice(index)}
                  disabled={isAnswering}
                  className={`w-full text-left px-3 py-2 rounded-lg border text-sm transition-colors disabled:opacity-50 disabled:cursor-not-allowed ${
                    isSelected
                      ? 'border-blue-400 bg-blue-50 text-blue-800'
                      : 'border-gray-200 bg-white text-gray-700 hover:border-gray-300 hover:bg-gray-50'
                  }`}
                >
                  {option}
                </button>
              )
            })}
            {question.allowOther && (
              <button
                onClick={() => setShowFreeText(true)}
                disabled={isAnswering}
                className="w-full text-left px-3 py-2 rounded-lg border border-dashed border-gray-300 bg-gray-50 text-sm text-gray-500 hover:border-gray-400 hover:bg-gray-100 hover:text-gray-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              >
                Other (type your answer)
              </button>
            )}
            <button
              onClick={handleSubmitChoices}
              disabled={selectedIndices.size === 0 || isAnswering}
              className="w-full px-3 py-2 rounded-lg bg-gray-900 text-white text-sm font-medium hover:bg-gray-700 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
            >
              {isAnswering ? (
                <span className="flex items-center justify-center gap-2">
                  <Loader2 className="w-3 h-3 animate-spin" />
                  Submitting…
                </span>
              ) : (
                `Submit${selectedIndices.size > 0 ? ` (${selectedIndices.size})` : ''}`
              )}
            </button>
          </div>
        )}

        {showFreeText && !answered && (
          <div className="mt-2 space-y-2">
            <div className="flex items-end gap-2 border border-gray-200 rounded-lg px-3 py-2 bg-white focus-within:border-gray-300 transition-colors">
              <textarea
                ref={freeTextRef}
                value={freeText}
                onChange={(e) => setFreeText(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey && !isAnswering) {
                    e.preventDefault()
                    handleFreeTextSubmit()
                  }
                }}
                placeholder="Type your answer..."
                rows={2}
                disabled={isAnswering}
                className="flex-1 resize-none bg-transparent outline-none text-sm leading-6 min-w-0"
              />
              <button
                onClick={handleFreeTextSubmit}
                disabled={!freeText.trim() || isAnswering}
                className="flex-shrink-0 p-1.5 rounded-lg bg-gray-900 text-white hover:bg-gray-700 disabled:opacity-30 transition-colors"
              >
                {isAnswering ? (
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                ) : (
                  <Send className="w-3.5 h-3.5" />
                )}
              </button>
            </div>
            <button
              onClick={() => { setShowFreeText(false); setFreeText('') }}
              disabled={isAnswering}
              className="flex items-center gap-1 text-xs text-gray-400 hover:text-gray-600 transition-colors"
            >
              <X className="w-3 h-3" />
              Back to options
            </button>
          </div>
        )}
      </div>
    </div>
  )
}

export default HITLQuestionMessage
