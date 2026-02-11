/**
 * HITLQuestionMessage - Question bubble matching the agent message layout
 *
 * Uses the same icon-outside + name header pattern as agent messages.
 * Shows the question text and optional choice buttons (for multiple-choice).
 * When answered, shows the question with a green check.
 */

import { Loader2 } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { getAgentConfig, getAgentMessageColors } from '../../utils/agentConfig'

const HITLQuestionMessage = ({ question, onChoiceSelect, isAnswering, answered = false }) => {
  const agentId = question.agent_id || 'unknown'
  const agentConfig = getAgentConfig(agentId)
  const AgentIcon = agentConfig.icon
  const colors = getAgentMessageColors(agentConfig.color)

  const hasOptions = question.choices && question.choices.length > 0

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
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{question.question}</ReactMarkdown>
        </div>

        {question.context && !answered && (
          <div className="mt-1 text-xs text-gray-500 markdown-content">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{question.context}</ReactMarkdown>
          </div>
        )}

        {hasOptions && !answered && (
          <div className="mt-2 space-y-1.5">
            {question.choices.map((option, index) => (
              <button
                key={index}
                onClick={() => onChoiceSelect?.(option)}
                disabled={isAnswering}
                className="w-full text-left px-3 py-2 rounded-lg border border-gray-200 bg-white text-sm text-gray-700 hover:border-gray-300 hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
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
  )
}

export default HITLQuestionMessage
