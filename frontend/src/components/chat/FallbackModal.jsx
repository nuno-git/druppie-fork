/**
 * FallbackModal - popup dialog when a provider is unavailable and a fallback exists.
 *
 * Shown as a centered modal overlay instead of inline in the conversation.
 * The user picks "Switch this agent", "Switch all agents", or "Cancel";
 * the answer goes through the same question-answer API as regular HITL questions.
 */

import { AlertTriangle, ArrowRight, Loader2 } from 'lucide-react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { answerQuestion } from '../../services/api'

const translations = {
  en: {
    title: 'Provider unavailable',
    subtitle: 'A fallback model is available',
    configured: 'Configured',
    fallback: 'Fallback',
    switchSingle: 'Switch this agent',
    switchAll: 'Switch all agents',
    cancel: 'Cancel request',
    switching: 'Switching...',
  },
  nl: {
    title: 'Provider niet beschikbaar',
    subtitle: 'Een terugvalmodel is beschikbaar',
    configured: 'Geconfigureerd',
    fallback: 'Terugval',
    switchSingle: 'Deze agent omzetten',
    switchAll: 'Alle agents omzetten',
    cancel: 'Verzoek annuleren',
    switching: 'Omzetten...',
  },
}

const FallbackModal = ({ tc, sessionId, language }) => {
  const queryClient = useQueryClient()
  const t = translations[language] || translations.en

  const primary = tc.arguments?._primary || 'unknown'
  const fallback = tc.arguments?._fallback || 'unknown'
  const choices = (tc.arguments?.choices || []).map(c =>
    typeof c === 'string' ? c : c.text || String(c),
  )

  const answerMut = useMutation({
    mutationFn: ({ answer, selectedChoices }) =>
      answerQuestion(tc.question_id, answer, selectedChoices),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['session', sessionId] })
    },
    onError: () => {},
  })

  const handleAcceptSingle = () => {
    answerMut.mutate({
      answer: choices[0] || `Yes, switch to ${fallback}`,
      selectedChoices: [0],
    })
  }

  const handleAcceptAll = () => {
    answerMut.mutate({
      answer: choices[1] || 'Yes, switch all agents to fallback',
      selectedChoices: [1],
    })
  }

  const handleDecline = () => {
    answerMut.mutate({
      answer: choices[2] || 'No, cancel this request',
      selectedChoices: [2],
    })
  }

  if (answerMut.isSuccess) return null

  const busy = answerMut.isPending

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm">
      <div className="bg-white rounded-2xl shadow-xl w-full max-w-md mx-4 overflow-hidden">
        {/* Header */}
        <div className="flex items-center gap-3 px-5 pt-5 pb-3">
          <div className="w-10 h-10 rounded-full bg-amber-100 flex items-center justify-center flex-shrink-0">
            <AlertTriangle className="w-5 h-5 text-amber-600" />
          </div>
          <div className="flex-1 min-w-0">
            <h3 className="text-base font-semibold text-gray-900">{t.title}</h3>
            <p className="text-sm text-gray-500 mt-0.5">{t.subtitle}</p>
          </div>
        </div>

        {/* Body */}
        <div className="px-5 pb-4">
          <div className="flex items-center gap-3 py-3 px-4 rounded-xl bg-gray-50 border border-gray-100">
            <div className="text-center flex-1 min-w-0">
              <div className="text-xs text-gray-400 mb-1">{t.configured}</div>
              <div className="text-sm font-mono font-medium text-red-600 truncate">{primary}</div>
            </div>
            <ArrowRight className="w-4 h-4 text-gray-300 flex-shrink-0" />
            <div className="text-center flex-1 min-w-0">
              <div className="text-xs text-gray-400 mb-1">{t.fallback}</div>
              <div className="text-sm font-mono font-medium text-emerald-600 truncate">{fallback}</div>
            </div>
          </div>
        </div>

        {/* Actions */}
        <div className="flex flex-col gap-2 px-5 pb-5">
          <div className="flex gap-3">
            <button
              onClick={handleAcceptSingle}
              disabled={busy}
              className="flex-1 px-4 py-2.5 rounded-xl bg-gray-900 text-sm font-medium text-white hover:bg-gray-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center justify-center gap-2"
            >
              {busy ? (
                <>
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  {t.switching}
                </>
              ) : (
                t.switchSingle
              )}
            </button>
            <button
              onClick={handleAcceptAll}
              disabled={busy}
              className="flex-1 px-4 py-2.5 rounded-xl bg-gray-900 text-sm font-medium text-white hover:bg-gray-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center justify-center gap-2"
            >
              {busy ? (
                <>
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  {t.switching}
                </>
              ) : (
                t.switchAll
              )}
            </button>
          </div>
          <button
            onClick={handleDecline}
            disabled={busy}
            className="w-full px-4 py-2 rounded-xl border border-gray-200 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {t.cancel}
          </button>
          {answerMut.isError && (
            <p className="text-xs text-red-600 text-center mt-1">
              Something went wrong — please try again
            </p>
          )}
        </div>
      </div>
    </div>
  )
}

export default FallbackModal
