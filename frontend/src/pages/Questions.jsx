/**
 * Questions Page
 *
 * Lists pending HITL and ask_expert questions the current user can answer.
 * Mirrors the Approvals (Tasks) page layout but for the Question framework.
 *
 * Auth model:
 *   - Regular HITL question (no expert_role): only the session owner can answer.
 *   - ask_expert question (expert_role set): any user with that role can answer
 *     (the session owner cannot, unless they happen to hold the role too).
 *   - Admin can answer everything.
 *
 * Answering an expert question resumes the session in the background; the
 * session detail page picks up the new state on the next poll.
 */

import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import {
  HelpCircle,
  CheckCircle,
  Loader2,
  Send,
  X,
  MessageSquare,
  User,
  Clock,
  AlertCircle,
} from 'lucide-react'
import { getPendingQuestions, answerQuestion } from '../services/api'
import { useAuth } from '../App'
import { useToast } from '../components/Toast'
import PageHeader from '../components/shared/PageHeader'

const formatAgentName = (agentId) => {
  if (!agentId) return null
  return agentId
    .replace(/_agent$/i, '')
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase())
}

const QuestionCard = ({ question, onSubmit, isSubmitting }) => {
  const [selectedIndices, setSelectedIndices] = useState(new Set())
  const [freeText, setFreeText] = useState('')
  const [showFreeText, setShowFreeText] = useState(false)

  const hasChoices = Array.isArray(question.choices) && question.choices.length > 0
  const isExpertQuestion = !!question.expert_role
  const ownerName = question.session_owner_username

  const toggleChoice = (idx) => {
    setSelectedIndices((prev) => {
      const next = new Set(prev)
      if (next.has(idx)) next.delete(idx)
      else next.add(idx)
      return next
    })
  }

  const submitChoices = () => {
    if (selectedIndices.size === 0) return
    const indices = [...selectedIndices].sort((a, b) => a - b)
    const answerText = indices
      .map((i) => question.choices[i]?.text || question.choices[i])
      .join(', ')
    onSubmit(question.id, answerText, indices)
  }

  const submitFreeText = () => {
    const trimmed = freeText.trim()
    if (!trimmed) return
    onSubmit(question.id, trimmed, null)
  }

  return (
    <div
      className={`bg-white rounded-xl border p-4 ${
        isExpertQuestion ? 'border-purple-200' : 'border-gray-100'
      }`}
    >
      <div className="flex items-start justify-between gap-4">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <HelpCircle
              className={`w-4 h-4 flex-shrink-0 ${
                isExpertQuestion ? 'text-purple-500' : 'text-blue-500'
              }`}
            />
            {isExpertQuestion ? (
              <span className="px-2 py-0.5 bg-purple-100 text-purple-700 text-xs rounded-full font-medium">
                Expert: {question.expert_role}
              </span>
            ) : (
              <span className="px-2 py-0.5 bg-blue-100 text-blue-700 text-xs rounded-full font-medium">
                Session question
              </span>
            )}
            {question.agent_id && (
              <span className="text-xs text-gray-400">
                from {formatAgentName(question.agent_id)}
              </span>
            )}
          </div>
          <p className="mt-2 text-sm text-gray-800 whitespace-pre-wrap">
            {question.question}
          </p>
          <div className="mt-2 flex items-center gap-3 text-xs text-gray-500 flex-wrap">
            {question.session_title && (
              <span className="truncate max-w-[20rem]">
                Session: <span className="text-gray-700">{question.session_title}</span>
              </span>
            )}
            {ownerName && (
              <span className="flex items-center gap-1">
                <User className="w-3 h-3" />
                Started by {ownerName}
              </span>
            )}
            {question.created_at && (
              <span className="flex items-center gap-1">
                <Clock className="w-3 h-3" />
                {new Date(question.created_at).toLocaleString()}
              </span>
            )}
            {question.session_id && (
              <Link
                to={`/chat?session=${question.session_id}`}
                className="text-blue-600 hover:text-blue-800 hover:underline flex items-center gap-1"
              >
                <MessageSquare className="w-3 h-3" />
                Open conversation
              </Link>
            )}
          </div>
        </div>
      </div>

      {hasChoices && !showFreeText && (
        <div className="mt-3 space-y-1.5">
          {question.choices.map((choice, idx) => {
            const text = choice?.text ?? choice
            const isSelected = selectedIndices.has(idx)
            return (
              <button
                key={idx}
                onClick={() => toggleChoice(idx)}
                disabled={isSubmitting}
                className={`w-full text-left px-3 py-2 rounded-lg border text-sm transition-colors disabled:opacity-50 ${
                  isSelected
                    ? 'border-blue-400 bg-blue-50 text-blue-800'
                    : 'border-gray-200 bg-white text-gray-700 hover:border-gray-300 hover:bg-gray-50'
                }`}
              >
                {text}
              </button>
            )
          })}
          <button
            onClick={() => setShowFreeText(true)}
            disabled={isSubmitting}
            className="w-full text-left px-3 py-2 rounded-lg border border-dashed border-gray-300 bg-gray-50 text-sm text-gray-500 hover:border-gray-400 hover:bg-gray-100 hover:text-gray-700 disabled:opacity-50 transition-colors"
          >
            Other (type your answer)
          </button>
          <button
            onClick={submitChoices}
            disabled={selectedIndices.size === 0 || isSubmitting}
            className="w-full px-3 py-2 rounded-lg bg-gray-900 text-white text-sm font-medium hover:bg-gray-700 disabled:opacity-30 transition-colors"
          >
            {isSubmitting ? (
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

      {(showFreeText || !hasChoices) && (
        <div className="mt-3 space-y-2">
          <div className="flex items-end gap-2 border border-gray-200 rounded-lg px-3 py-2 bg-white focus-within:border-gray-300 transition-colors">
            <textarea
              value={freeText}
              onChange={(e) => setFreeText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey && !isSubmitting) {
                  e.preventDefault()
                  submitFreeText()
                }
              }}
              placeholder="Type your answer..."
              rows={2}
              disabled={isSubmitting}
              className="flex-1 resize-none bg-transparent outline-none text-sm leading-6 min-w-0"
            />
            <button
              onClick={submitFreeText}
              disabled={!freeText.trim() || isSubmitting}
              className="flex-shrink-0 p-1.5 rounded-lg bg-gray-900 text-white hover:bg-gray-700 disabled:opacity-30 transition-colors"
            >
              {isSubmitting ? (
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
              ) : (
                <Send className="w-3.5 h-3.5" />
              )}
            </button>
          </div>
          {showFreeText && hasChoices && (
            <button
              onClick={() => {
                setShowFreeText(false)
                setFreeText('')
              }}
              disabled={isSubmitting}
              className="flex items-center gap-1 text-xs text-gray-400 hover:text-gray-600 transition-colors"
            >
              <X className="w-3 h-3" />
              Back to options
            </button>
          )}
        </div>
      )}
    </div>
  )
}

const Questions = () => {
  const { user } = useAuth()
  const queryClient = useQueryClient()
  const toast = useToast()

  const {
    data,
    isLoading,
    isError,
    error,
    refetch,
  } = useQuery({
    queryKey: ['pending-questions'],
    queryFn: getPendingQuestions,
    refetchInterval: 5000,
  })

  const answerMutation = useMutation({
    mutationFn: ({ questionId, answer, selectedChoices }) =>
      answerQuestion(questionId, answer, selectedChoices),
    onSuccess: () => {
      queryClient.invalidateQueries(['pending-questions'])
      queryClient.invalidateQueries(['pending-questions-count'])
      toast.success('Answer submitted', 'The session will resume shortly.')
    },
    onError: (err) => {
      toast.error('Could not submit answer', err.message || 'Please try again.')
    },
  })

  const handleSubmit = (questionId, answer, selectedChoices) => {
    answerMutation.mutate({ questionId, answer, selectedChoices })
  }

  const items = data?.items || []

  // Group by expert vs HITL — experts on top, then session-owner questions
  const expertItems = items.filter((q) => q.expert_role)
  const hitlItems = items.filter((q) => !q.expert_role)

  return (
    <div className="space-y-6">
      <PageHeader
        title="Pending Questions"
        subtitle="Answer questions sent to you by agents — for sessions you own or as an expert."
      >
        <div className="flex items-center gap-2">
          <span className="text-sm text-gray-500">Your roles:</span>
          {user?.roles?.slice(0, 4).map((role) => (
            <span
              key={role}
              className="px-2 py-1 bg-blue-100 text-blue-700 text-xs rounded-full"
            >
              {role}
            </span>
          ))}
        </div>
      </PageHeader>

      {isLoading ? (
        <div className="flex items-center justify-center h-32">
          <Loader2 className="w-6 h-6 animate-spin text-blue-500" />
        </div>
      ) : isError ? (
        <div className="flex flex-col items-center justify-center h-64 text-red-500">
          <AlertCircle className="w-12 h-12 mb-2" />
          <p className="text-lg font-medium">Failed to load questions</p>
          <p className="text-sm text-red-400">{error?.message || 'Unknown error'}</p>
          <button
            onClick={() => refetch()}
            className="mt-4 px-4 py-2 bg-blue-500 text-white rounded-lg hover:bg-blue-600"
          >
            Retry
          </button>
        </div>
      ) : items.length === 0 ? (
        <div className="text-center py-16 bg-white rounded-xl border border-gray-100">
          <CheckCircle className="w-10 h-10 text-green-400 mx-auto mb-3" />
          <h3 className="text-base font-medium text-gray-700">All caught up</h3>
          <p className="text-gray-400 text-sm mt-1">
            No pending questions for you right now.
          </p>
        </div>
      ) : (
        <div className="space-y-8">
          {expertItems.length > 0 && (
            <div>
              <h2 className="text-lg font-semibold mb-4 flex items-center">
                <HelpCircle className="w-5 h-5 mr-2 text-purple-500" />
                Expert questions
                <span className="ml-2 px-2 py-0.5 bg-purple-100 text-purple-700 text-sm rounded-full">
                  {expertItems.length}
                </span>
              </h2>
              <div className="grid gap-4">
                {expertItems.map((q) => (
                  <QuestionCard
                    key={q.id}
                    question={q}
                    onSubmit={handleSubmit}
                    isSubmitting={answerMutation.isPending}
                  />
                ))}
              </div>
            </div>
          )}
          {hitlItems.length > 0 && (
            <div>
              <h2 className="text-lg font-semibold mb-4 flex items-center">
                <HelpCircle className="w-5 h-5 mr-2 text-blue-500" />
                Your sessions
                <span className="ml-2 px-2 py-0.5 bg-blue-100 text-blue-700 text-sm rounded-full">
                  {hitlItems.length}
                </span>
              </h2>
              <div className="grid gap-4">
                {hitlItems.map((q) => (
                  <QuestionCard
                    key={q.id}
                    question={q}
                    onSubmit={handleSubmit}
                    isSubmitting={answerMutation.isPending}
                  />
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export default Questions
