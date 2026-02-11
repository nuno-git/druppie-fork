/**
 * HITLQuestionMessage - Read-only question bubble with agent-specific styling
 *
 * Shows the question text and optional choice buttons (for multiple-choice).
 * User answers via the main input bar or by clicking a choice button.
 * When answered, shows both the question and the user's answer.
 */

import React from 'react'
import { HelpCircle, CheckCircle, Loader2 } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { getAgentConfig, getAgentMessageColors } from '../../utils/agentConfig'

const HITLQuestionMessage = ({ question, onChoiceSelect, isAnswering, answered = false, userAnswer = null }) => {
  // Get agent configuration and colors
  const agentId = question.agent_id || 'unknown'
  const agentConfig = getAgentConfig(agentId)
  const AgentIcon = agentConfig.icon
  const colors = getAgentMessageColors(agentConfig.color)

  const hasOptions = question.choices && question.choices.length > 0

  // Answered view — just show the question (answer is rendered as a separate chat bubble)
  if (answered) {
    return (
      <div className="flex justify-start mb-4">
        <div
          className={`max-w-[85%] rounded-2xl px-4 py-3 rounded-bl-none shadow-sm border ${colors.bg} ${colors.border}`}
        >
          <div className="flex items-start space-x-3">
            <div className={`w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0 ${colors.bg} border ${colors.border}`}>
              <AgentIcon className={`w-5 h-5 ${colors.accent}`} />
            </div>
            <div className="flex-1 min-w-0">
              <div className={`text-xs font-semibold mb-1 ${colors.accent} flex items-center gap-2`}>
                <span>{agentConfig.name} Agent</span>
                <CheckCircle className="w-3 h-3 text-green-500" />
                <span className="font-normal text-gray-500">asked:</span>
              </div>
              <div className={`text-sm ${colors.text} markdown-content`}>
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{question.question}</ReactMarkdown>
              </div>
            </div>
          </div>
        </div>
      </div>
    )
  }

  // Pending question — read-only bubble with optional choice buttons
  return (
    <div className="flex justify-start mb-4">
      <div
        className={`max-w-[85%] rounded-2xl px-4 py-3 rounded-bl-none shadow-sm border ${colors.bg} ${colors.border}`}
      >
        <div className="flex items-start space-x-3">
          <div className={`w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0 ${colors.bg} border ${colors.border}`}>
            <AgentIcon className={`w-5 h-5 ${colors.accent}`} />
          </div>
          <div className="flex-1 min-w-0">
            <div className={`text-xs font-semibold mb-1 ${colors.accent} flex items-center gap-2`}>
              <span>{agentConfig.name} Agent</span>
              <HelpCircle className="w-3 h-3" />
              <span className="font-normal text-gray-500">asks:</span>
            </div>
            <div className={`text-sm font-medium mb-2 ${colors.text} markdown-content`}>
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{question.question}</ReactMarkdown>
            </div>

            {question.context && (
              <div className={`text-xs mb-3 ${colors.accent} opacity-80 markdown-content`}>
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{question.context}</ReactMarkdown>
              </div>
            )}

            {/* Choice buttons — clicking directly answers */}
            {hasOptions && (
              <div className="space-y-2">
                {question.choices.map((option, index) => (
                  <button
                    key={index}
                    onClick={() => onChoiceSelect?.(option)}
                    disabled={isAnswering}
                    className={`w-full text-left px-3 py-2 rounded-lg border transition-colors text-sm bg-white ${colors.text} border-gray-200 hover:border-current hover:${colors.bg} disabled:opacity-50 disabled:cursor-not-allowed`}
                  >
                    {isAnswering ? (
                      <span className="flex items-center gap-2">
                        <Loader2 className="w-3 h-3 animate-spin" />
                        {option}
                      </span>
                    ) : (
                      option
                    )}
                  </button>
                ))}
              </div>
            )}

          </div>
        </div>
      </div>
    </div>
  )
}

export default HITLQuestionMessage
