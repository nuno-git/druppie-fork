/**
 * HITLQuestionMessage - Question bubble matching the agent message layout
 *
 * Uses the same icon-outside + name header pattern as agent messages.
 * Shows the question text and optional choice buttons (for multiple-choice).
 * When answered, shows the question with a green check.
 *
 * When `question.allowOther` is truthy and the question has choices,
 * a free-text textarea is shown below the choices. The user can select
 * choices AND type a custom answer — both are submitted together.
 */

import { useState, useRef, useEffect } from 'react'
import { Loader2, Send, ChevronDown, ChevronUp } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { getAgentConfig, getAgentMessageColors } from '../../utils/agentConfig'
import { chatMarkdownComponents } from './ChatHelpers'

const HITLQuestionMessage = ({ question, onSubmitAnswer, isAnswering, answered = false, hideAgentHeader = false, allowComment = false, singleSelect = false }) => {
  const agentId = question.agent_id || 'unknown'
  const agentConfig = getAgentConfig(agentId)
  const AgentIcon = agentConfig.icon
  const colors = getAgentMessageColors(agentConfig.color)

  const hasOptions = question.choices && question.choices.length > 0

  const [selectedIndices, setSelectedIndices] = useState(new Set())
  const [freeText, setFreeText] = useState('')
  const [comment, setComment] = useState('')
  const [showFreeText, setShowFreeText] = useState(false)
  const freeTextRef = useRef(null)
  const plainTextRef = useRef(null)

  const autoResize = (ref) => {
    const el = ref?.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = Math.min(el.scrollHeight, 200) + 'px'
  }

  useEffect(() => {
    if (showFreeText && freeTextRef.current) {
      freeTextRef.current.focus()
    }
  }, [showFreeText])

  useEffect(() => {
    autoResize(hasOptions ? freeTextRef : plainTextRef)
  }, [freeText, hasOptions])

  const handleToggleChoice = (index) => {
    setSelectedIndices((prev) => {
      if (singleSelect) {
        return prev.has(index) ? new Set() : new Set([index])
      }
      const next = new Set(prev)
      if (next.has(index)) {
        next.delete(index)
      } else {
        next.add(index)
      }
      return next
    })
  }

  const canSubmit = selectedIndices.size > 0 || freeText.trim().length > 0

  const handleSubmit = () => {
    if (!canSubmit) return
    const indices = [...selectedIndices].sort((a, b) => a - b)
    const choiceTexts = indices.map((i) => question.choices[i])
    const custom = freeText.trim()

    const parts = [...choiceTexts]
    if (custom) parts.push(custom)
    let answerText = parts.join(', ')

    const commentText = comment.trim()
    if (commentText) {
      answerText += `\n\nComment: ${commentText}`
    }

    onSubmitAnswer?.({
      indices: indices.length > 0 ? indices : null,
      answerText,
      customText: custom || null,
    })
  }

  const submitLabel = () => {
    const count = selectedIndices.size + (freeText.trim() ? 1 : 0)
    if (count === 0) return 'Submit'
    return `Submit (${count})`
  }

  return (
    <div className="group">
      {!hideAgentHeader && (
        <div className="flex items-center gap-2 mb-1.5">
          <div className={`w-6 h-6 rounded-full flex items-center justify-center flex-shrink-0 ${colors.bg} border ${colors.border}`}>
            <AgentIcon className={`w-3.5 h-3.5 ${colors.accent}`} />
          </div>
          <span className={`text-sm font-medium ${colors.accent}`}>{agentConfig.name}</span>
        </div>
      )}
      <div className="pl-8">
        <div className="text-sm text-gray-800 leading-relaxed markdown-content">
          <ReactMarkdown remarkPlugins={[remarkGfm]} components={chatMarkdownComponents}>{question.question}</ReactMarkdown>
        </div>

        {question.context && !answered && (
          <div className="mt-1 text-xs text-gray-500 markdown-content">
            <ReactMarkdown remarkPlugins={[remarkGfm]} components={chatMarkdownComponents}>{question.context}</ReactMarkdown>
          </div>
        )}

        {hasOptions && !answered && (
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

            {question.allowOther && !showFreeText && (
              <button
                onClick={() => setShowFreeText(true)}
                disabled={isAnswering}
                className="w-full text-left px-3 py-2 rounded-lg border border-dashed border-gray-300 bg-gray-50 text-sm text-gray-500 hover:border-gray-400 hover:bg-gray-100 hover:text-gray-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center gap-1.5"
              >
                <ChevronDown className="w-3.5 h-3.5" />
                Add a custom answer
              </button>
            )}

            {question.allowOther && showFreeText && (
              <div className="space-y-1.5">
                <button
                  onClick={() => { setShowFreeText(false); setFreeText('') }}
                  disabled={isAnswering}
                  className="flex items-center gap-1 text-xs text-gray-400 hover:text-gray-600 transition-colors"
                >
                  <ChevronUp className="w-3 h-3" />
                  Hide custom answer
                </button>
                <div className="flex items-end gap-2 border border-gray-200 rounded-lg px-3 py-2 bg-white focus-within:border-gray-300 transition-colors">
                  <textarea
                    ref={freeTextRef}
                    value={freeText}
                    onChange={(e) => setFreeText(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' && !e.shiftKey && !isAnswering) {
                        e.preventDefault()
                        handleSubmit()
                      }
                    }}
                    placeholder="Type your answer..."
                    rows={2}
                    disabled={isAnswering}
                    className="flex-1 resize-y bg-transparent outline-none text-sm leading-6 min-w-0 max-h-[200px]"
                  />
                </div>
              </div>
            )}

            {allowComment && !answered && (
              <div className="mt-3 space-y-1.5">
                <label className="text-xs font-medium text-gray-500">Add a comment (optional)</label>
                <textarea
                  value={comment}
                  onChange={(e) => setComment(e.target.value)}
                  placeholder="Explain your reasoning..."
                  className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-200 focus:border-blue-300 resize-none bg-white"
                  rows={2}
                />
              </div>
            )}

            <button
              onClick={handleSubmit}
              disabled={!canSubmit || isAnswering}
              className="w-full px-3 py-2 rounded-lg bg-gray-900 text-white text-sm font-medium hover:bg-gray-700 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
            >
              {isAnswering ? (
                <span className="flex items-center justify-center gap-2">
                  <Loader2 className="w-3 h-3 animate-spin" />
                  Submitting…
                </span>
              ) : (
                submitLabel()
              )}
            </button>
          </div>
        )}

        {/* Questions without choices — free-text only */}
        {!hasOptions && !answered && (
          <div className="mt-2">
            <div className="flex items-end gap-2 border border-gray-200 rounded-lg px-3 py-2 bg-white focus-within:border-gray-300 transition-colors">
              <textarea
                ref={plainTextRef}
                value={freeText}
                onChange={(e) => setFreeText(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey && !isAnswering) {
                    e.preventDefault()
                    handleSubmit()
                  }
                }}
                placeholder="Type your answer..."
                rows={2}
                disabled={isAnswering}
                className="flex-1 resize-y bg-transparent outline-none text-sm leading-6 min-w-0 max-h-[200px]"
              />
              <button
                onClick={handleSubmit}
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
            {hasOptions && (
              <button
                onClick={() => { setShowFreeText(false); setFreeText('') }}
                disabled={isAnswering}
                className="flex items-center gap-1 text-xs text-gray-400 hover:text-gray-600 transition-colors"
              >
                <X className="w-3 h-3" />
                Back to options
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

export default HITLQuestionMessage
