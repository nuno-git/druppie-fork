/**
 * HITLQuestionMessage - Displays an agent's HITL question as a chat message with agent-specific styling
 * Shows input form when pending, shows Q&A history when answered
 */

import React, { useState } from 'react'
import { HelpCircle, Loader2, Send, CheckCircle } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { getAgentConfig, getAgentMessageColors } from '../../utils/agentConfig'

const HITLQuestionMessage = ({ question, onAnswer, isAnswering, answered = false, userAnswer = null }) => {
  const [selectedOption, setSelectedOption] = useState(null)
  const [customAnswer, setCustomAnswer] = useState('')

  // Get agent configuration and colors
  const agentId = question.agent_id || 'unknown'
  const agentConfig = getAgentConfig(agentId)
  const AgentIcon = agentConfig.icon
  const colors = getAgentMessageColors(agentConfig.color)

  const hasOptions = question.choices && question.choices.length > 0

  const handleSubmit = () => {
    const answer = selectedOption || customAnswer
    if (answer.trim()) {
      onAnswer(question.id, answer, selectedOption)
    }
  }

  // If already answered, show read-only view
  if (answered) {
    return (
      <div className="flex justify-start mb-4">
        <div
          className={`max-w-[85%] rounded-2xl px-4 py-3 rounded-bl-none shadow-sm border ${colors.bg} ${colors.border}`}
        >
          <div className="flex items-start space-x-3">
            {/* Agent Icon */}
            <div className={`w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0 ${colors.bg} border ${colors.border}`}>
              <AgentIcon className={`w-5 h-5 ${colors.accent}`} />
            </div>

            <div className="flex-1 min-w-0">
              {/* Agent Name Header */}
              <div className={`text-xs font-semibold mb-1 ${colors.accent} flex items-center gap-2`}>
                <span>{agentConfig.name} Agent</span>
                <CheckCircle className="w-3 h-3 text-green-500" />
                <span className="font-normal text-gray-500">asked:</span>
              </div>

              {/* Question Text */}
              <div className={`text-sm mb-2 ${colors.text} markdown-content`}>
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{question.question}</ReactMarkdown>
              </div>

              {/* Show the answer that was given */}
              {userAnswer && (
                <div className="mt-2 pt-2 border-t border-gray-200">
                  <div className="text-xs text-gray-500 mb-1">Your answer:</div>
                  <div className="text-sm text-gray-800 bg-white px-3 py-2 rounded-lg border border-gray-200">
                    {userAnswer}
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    )
  }

  // Pending question - show input form
  return (
    <div className="flex justify-start mb-4">
      <div
        className={`max-w-[85%] rounded-2xl px-4 py-3 rounded-bl-none shadow-sm border ${colors.bg} ${colors.border}`}
      >
        <div className="flex items-start space-x-3">
          {/* Agent Icon */}
          <div className={`w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0 ${colors.bg} border ${colors.border}`}>
            <AgentIcon className={`w-5 h-5 ${colors.accent}`} />
          </div>

          <div className="flex-1 min-w-0">
            {/* Agent Name Header */}
            <div className={`text-xs font-semibold mb-1 ${colors.accent} flex items-center gap-2`}>
              <span>{agentConfig.name} Agent</span>
              <HelpCircle className="w-3 h-3" />
              <span className="font-normal text-gray-500">asks:</span>
            </div>

            {/* Question Text */}
            <div className={`text-sm font-medium mb-2 ${colors.text} markdown-content`}>
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{question.question}</ReactMarkdown>
            </div>

            {/* Context if provided */}
            {question.context && (
              <div className={`text-xs mb-3 ${colors.accent} opacity-80 markdown-content`}>
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{question.context}</ReactMarkdown>
              </div>
            )}

            {/* Options as clickable buttons */}
            {hasOptions && (
              <div className="space-y-2 mb-3">
                {question.choices.map((option, index) => (
                  <button
                    key={index}
                    onClick={() => {
                      setSelectedOption(option)
                      setCustomAnswer('')
                    }}
                    className={`w-full text-left px-3 py-2 rounded-lg border transition-colors text-sm ${
                      selectedOption === option
                        ? `${colors.bg} ${colors.accent} border-current font-medium`
                        : `bg-white ${colors.text} border-gray-200 hover:${colors.border}`
                    }`}
                  >
                    {option}
                  </button>
                ))}
              </div>
            )}

            {/* Custom answer input */}
            <div className="mb-3">
              <input
                type="text"
                value={customAnswer}
                onChange={(e) => {
                  setCustomAnswer(e.target.value)
                  setSelectedOption(null)
                }}
                placeholder={hasOptions ? "Or type a custom answer..." : "Type your answer..."}
                className={`w-full px-3 py-2 border rounded-lg focus:ring-2 focus:ring-offset-1 text-sm bg-white ${colors.border} focus:ring-current`}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && (selectedOption || customAnswer.trim())) {
                    handleSubmit()
                  }
                }}
              />
            </div>

            {/* Submit button */}
            <button
              onClick={handleSubmit}
              disabled={isAnswering || (!selectedOption && !customAnswer.trim())}
              className={`flex items-center gap-2 px-4 py-2 rounded-lg disabled:opacity-50 disabled:cursor-not-allowed transition-colors focus:outline-none focus:ring-2 focus:ring-offset-2 text-white ${
                agentConfig.color === 'indigo' ? 'bg-indigo-600 hover:bg-indigo-700 focus:ring-indigo-500' :
                agentConfig.color === 'purple' ? 'bg-purple-600 hover:bg-purple-700 focus:ring-purple-500' :
                agentConfig.color === 'blue' ? 'bg-blue-600 hover:bg-blue-700 focus:ring-blue-500' :
                agentConfig.color === 'green' ? 'bg-green-600 hover:bg-green-700 focus:ring-green-500' :
                agentConfig.color === 'orange' ? 'bg-orange-600 hover:bg-orange-700 focus:ring-orange-500' :
                agentConfig.color === 'teal' ? 'bg-teal-600 hover:bg-teal-700 focus:ring-teal-500' :
                'bg-gray-600 hover:bg-gray-700 focus:ring-gray-500'
              }`}
              aria-label="Submit answer"
            >
              {isAnswering ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" aria-hidden="true" />
                  Submitting...
                </>
              ) : (
                <>
                  <Send className="w-4 h-4" aria-hidden="true" />
                  Reply
                </>
              )}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

export default HITLQuestionMessage
