/**
 * QuestionCard - Displays a question from an agent with input options
 */

import React, { useState } from 'react'
import { HelpCircle, Loader2, Send } from 'lucide-react'

const QuestionCard = ({ question, onAnswer, isAnswering }) => {
  const [selectedOption, setSelectedOption] = useState(null)
  const [customAnswer, setCustomAnswer] = useState('')
  const hasOptions = question.options && question.options.length > 0

  const handleSubmit = () => {
    const answer = selectedOption || customAnswer
    if (answer.trim()) {
      onAnswer(question.id, answer)
    }
  }

  return (
    <div className="mt-3 bg-purple-50 rounded-lg border border-purple-200 p-4">
      <div className="flex items-start gap-3">
        <div className="p-2 bg-purple-100 rounded-full">
          <HelpCircle className="w-5 h-5 text-purple-600" />
        </div>
        <div className="flex-1">
          <div className="text-sm font-medium text-purple-900 mb-1">
            Agent needs your input
          </div>
          <div className="text-purple-800 font-medium mb-2">
            {question.question}
          </div>
          {question.context && (
            <div className="text-sm text-purple-600 mb-3">
              {question.context}
            </div>
          )}

          {/* Options as clickable buttons */}
          {hasOptions && (
            <div className="space-y-2 mb-3">
              {question.options.map((option, index) => (
                <button
                  key={index}
                  onClick={() => {
                    setSelectedOption(option)
                    setCustomAnswer('')
                  }}
                  className={`w-full text-left px-4 py-2 rounded-lg border transition-colors ${
                    selectedOption === option
                      ? 'bg-purple-600 text-white border-purple-600'
                      : 'bg-white text-purple-800 border-purple-200 hover:border-purple-400'
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
              className="w-full px-3 py-2 border border-purple-200 rounded-lg focus:ring-2 focus:ring-purple-500 focus:border-transparent text-sm"
            />
          </div>

          {/* Submit button */}
          <button
            onClick={handleSubmit}
            disabled={isAnswering || (!selectedOption && !customAnswer.trim())}
            className="flex items-center gap-2 px-4 py-2 bg-purple-600 text-white rounded-lg hover:bg-purple-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors focus:outline-none focus:ring-2 focus:ring-purple-500 focus:ring-offset-2"
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
                Submit Answer
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  )
}

export default QuestionCard
