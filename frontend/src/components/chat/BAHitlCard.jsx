/**
 * BAHitlCard - Human review card shown when session.status === 'paused_ba_hitl'.
 *
 * After the architect rejects an FD N times, a business analyst reviews it here.
 * Actions: iterate (with feedback), ready, escalate (gated on a post-HITL
 * rejection), terminate (with confirm). Modeled on InlineApproval / HITLQuestionMessage.
 */

import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Loader2, MessageSquarePlus, CheckCircle2, ArrowUpCircle, Ban, ShieldCheck, AlertTriangle, FileText } from 'lucide-react'
import { submitBaHitl } from '../../services/api'
import { useAuth } from '../../App'
import { FilePreviewModal } from './ApprovalCard'

const ROLES_THAT_CAN_ACT = ['business_analyst', 'admin']

const BTN = 'inline-flex items-center justify-center gap-1.5 px-3 py-1.5 text-sm font-medium rounded-lg text-white transition-colors disabled:opacity-50 disabled:cursor-not-allowed'

const findFdContent = (session) => {
  if (!session?.timeline) return null
  for (let i = session.timeline.length - 1; i >= 0; i--) {
    const ar = session.timeline[i].agent_run
    if (!ar?.llm_calls) continue
    for (const llm of ar.llm_calls) {
      for (const tc of (llm.tool_calls || [])) {
        const name = tc.tool_name || ''
        if (name === 'make_design' || name.endsWith(':make_design')) {
          const args = tc.arguments || {}
          if (args.path && args.content) {
            return [{ path: args.path, content: args.content }]
          }
        }
      }
    }
  }
  return null
}

const BAHitlCard = ({ sessionId, session }) => {
  const queryClient = useQueryClient()
  const { user } = useAuth()
  const [feedback, setFeedback] = useState('')
  const [showIterate, setShowIterate] = useState(false)
  const [confirmTerminate, setConfirmTerminate] = useState(false)
  const [confirmEscalate, setConfirmEscalate] = useState(false)
  const [confirmReady, setConfirmReady] = useState(false)
  const [showFdPreview, setShowFdPreview] = useState(false)
  const [terminateReason, setTerminateReason] = useState('')

  const userRoles = user?.roles || []
  const isOwner = !!session?.user_id && session.user_id === user?.id
  const canAct = isOwner || userRoles.some((r) => ROLES_THAT_CAN_ACT.includes(r))

  const postHitlRejections = session?.fd_post_hitl_rejection_count ?? 0
  const escalationMode = !!session?.fd_escalation_mode
  const canEscalate = postHitlRejections >= 1
  const fdFiles = findFdContent(session)

  const mutation = useMutation({
    mutationFn: (payload) => submitBaHitl(sessionId, payload),
    onSuccess: () => {
      setFeedback('')
      setShowIterate(false)
      setConfirmTerminate(false)
      setConfirmEscalate(false)
      setConfirmReady(false)
      setTerminateReason('')
      queryClient.invalidateQueries({ queryKey: ['session', sessionId] })
      queryClient.invalidateQueries({ queryKey: ['escalation-history', sessionId] })
    },
  })

  const pending = mutation.isPending

  const submitIterate = () => {
    const trimmed = feedback.trim()
    if (!trimmed || pending) return
    mutation.mutate({ decision: 'iterate', feedback: trimmed })
  }

  if (!canAct) {
    return (
      <div className="border border-amber-200 rounded-2xl shadow-sm px-4 py-3.5 bg-amber-50">
        <div className="flex items-center gap-2 mb-1">
          <ShieldCheck className="w-4 h-4 text-amber-600 flex-shrink-0" />
          <p className="text-sm font-medium text-amber-800">Business analyst review pending</p>
        </div>
        <p className="text-xs text-amber-700 ml-6">
          Waiting for an authorised reviewer{postHitlRejections > 0 ? ` · ${postHitlRejections} post-review rejection${postHitlRejections === 1 ? '' : 's'}` : ''}
          {escalationMode ? ' · escalation mode on' : ''}
        </p>
      </div>
    )
  }

  return (
    <div className="border border-amber-200 rounded-2xl shadow-sm px-4 py-3.5 bg-amber-50">
      <div className="flex items-center gap-2 mb-1">
        <ShieldCheck className="w-4 h-4 text-amber-600 flex-shrink-0" />
        <p className="text-sm font-medium text-amber-800">Business analyst review</p>
        <span className="ml-auto text-[10px] font-medium uppercase tracking-wider px-1.5 py-0.5 rounded border border-amber-300 bg-amber-100 text-amber-800">
          {postHitlRejections} post-review rejection{postHitlRejections === 1 ? '' : 's'}
          {escalationMode ? ' · escalated' : ''}
        </span>
      </div>
      <p className="text-xs text-amber-700 mb-3 ml-6">
        Iterate with the BA agent, mark the FD ready, escalate to a human architect, or terminate.
      </p>

      {showIterate && (
        <div className="ml-6 mb-3">
          <div className="flex items-end gap-2 border border-amber-300 rounded-lg px-3 py-2 bg-white focus-within:border-amber-400 transition-colors">
            <textarea
              value={feedback}
              onChange={(e) => setFeedback(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey && !pending) {
                  e.preventDefault()
                  submitIterate()
                }
              }}
              placeholder="Feedback for the next BA iteration…"
              rows={2}
              disabled={pending}
              className="flex-1 resize-y bg-transparent outline-none text-sm leading-6 min-w-0 max-h-[200px]"
              aria-label="BA iteration feedback"
            />
            <button
              onClick={submitIterate}
              disabled={!feedback.trim() || pending}
              className="flex-shrink-0 px-3 py-1.5 rounded-lg bg-amber-600 text-white text-sm font-medium hover:bg-amber-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              {pending ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : 'Send'}
            </button>
            <button
              onClick={() => { setShowIterate(false); setFeedback('') }}
              disabled={pending}
              className="flex-shrink-0 px-3 py-1.5 text-sm text-gray-600 hover:text-gray-800 transition-colors"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {confirmTerminate ? (
        <div className="ml-6 space-y-2">
          <div className="flex items-center gap-2">
            <AlertTriangle className="w-4 h-4 text-red-600 flex-shrink-0" />
            <span className="text-sm text-red-700">Terminate permanently?</span>
          </div>
          <textarea
            value={terminateReason}
            onChange={(e) => setTerminateReason(e.target.value)}
            placeholder="Reason for termination (the session owner will see this)…"
            rows={2}
            disabled={pending}
            className="w-full resize-y border border-red-300 rounded-lg px-3 py-2 bg-white outline-none text-sm leading-6 focus:border-red-400 transition-colors"
            aria-label="Termination reason"
          />
          <div className="flex items-center gap-2">
            <button
              onClick={() => !pending && mutation.mutate({ decision: 'terminate', feedback: terminateReason.trim() || undefined })}
              disabled={pending}
              className={`${BTN} bg-red-600 hover:bg-red-700`}
            >
              {pending ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Ban className="w-3.5 h-3.5" />}
              Confirm terminate
            </button>
            <button
              onClick={() => { setConfirmTerminate(false); setTerminateReason('') }}
              disabled={pending}
              className="px-3 py-1.5 text-sm text-gray-600 hover:text-gray-800 transition-colors"
            >
              Cancel
            </button>
          </div>
        </div>
      ) : confirmEscalate ? (
        <div className="ml-6 space-y-2">
          <div className="flex items-center gap-2">
            <ArrowUpCircle className="w-4 h-4 text-purple-600 flex-shrink-0" />
            <span className="text-sm text-purple-700">Escalate to a human architect?</span>
          </div>
          <p className="text-xs text-purple-600 ml-6">
            The session will pause for architect review. An architect (architect role) will need to approve or reject the design before the session can continue.
          </p>
          <div className="flex items-center gap-2">
            <button
              onClick={() => !pending && mutation.mutate({ decision: 'escalate' })}
              disabled={pending}
              className={`${BTN} bg-purple-600 hover:bg-purple-700`}
            >
              {pending ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <ArrowUpCircle className="w-3.5 h-3.5" />}
              Confirm escalate
            </button>
            <button
              onClick={() => setConfirmEscalate(false)}
              disabled={pending}
              className="px-3 py-1.5 text-sm text-gray-600 hover:text-gray-800 transition-colors"
            >
              Cancel
            </button>
          </div>
        </div>
      ) : confirmReady ? (
        <div className="ml-6 space-y-2">
          <div className="flex items-center gap-2">
            <CheckCircle2 className="w-4 h-4 text-green-600 flex-shrink-0" />
            <span className="text-sm text-green-700">Mark the FD as ready for the architect?</span>
          </div>
          <p className="text-xs text-green-600 ml-6">
            The architect agent will review the functional design and either approve it (creating a technical design) or give feedback.
          </p>
          <div className="flex items-center gap-2">
            <button
              onClick={() => !pending && mutation.mutate({ decision: 'ready' })}
              disabled={pending}
              className={`${BTN} bg-green-600 hover:bg-green-700`}
            >
              {pending ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <CheckCircle2 className="w-3.5 h-3.5" />}
              Confirm ready
            </button>
            <button
              onClick={() => setConfirmReady(false)}
              disabled={pending}
              className="px-3 py-1.5 text-sm text-gray-600 hover:text-gray-800 transition-colors"
            >
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <div className="ml-6 flex flex-wrap items-center gap-2">
          {fdFiles && (
            <button
              onClick={() => setShowFdPreview(true)}
              disabled={pending}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium rounded-lg border border-amber-300 bg-white text-amber-800 hover:bg-amber-100 transition-colors disabled:opacity-50"
            >
              <FileText className="w-3.5 h-3.5" />
              View FD
            </button>
          )}
          {!showIterate && (
            <button
              onClick={() => setShowIterate(true)}
              disabled={pending}
              className={`${BTN} bg-blue-600 hover:bg-blue-700`}
            >
              <MessageSquarePlus className="w-3.5 h-3.5" />
              Iterate
            </button>
          )}
          {!showIterate && (
            <>
              <button
                onClick={() => setConfirmReady(true)}
                disabled={pending}
                className={`${BTN} bg-green-600 hover:bg-green-700`}
              >
                <CheckCircle2 className="w-3.5 h-3.5" />
                Ready
              </button>
              <button
                onClick={() => setConfirmEscalate(true)}
                disabled={pending || !canEscalate}
                title={canEscalate ? 'Escalate to a human architect' : 'Available after the architect rejects the revised FD once'}
                className={`${BTN} bg-purple-600 hover:bg-purple-700`}
              >
                <ArrowUpCircle className="w-3.5 h-3.5" />
                Escalate
              </button>
              <button
                onClick={() => setConfirmTerminate(true)}
                disabled={pending}
                className={`${BTN} bg-red-600 hover:bg-red-700`}
              >
                <Ban className="w-3.5 h-3.5" />
                Terminate
              </button>
            </>
          )}
        </div>
      )}

      {!canEscalate && !confirmTerminate && (
        <p className="ml-6 mt-2 text-xs text-amber-700/80">
          Escalate becomes available once the architect has rejected the revised FD.
        </p>
      )}

      {mutation.isError && (
        <p className="ml-6 mt-2 text-xs text-red-600">
          {mutation.error?.message || 'Action failed'}
        </p>
      )}

      {showFdPreview && fdFiles && (
        <FilePreviewModal files={fdFiles} onClose={() => setShowFdPreview(false)} />
      )}
    </div>
  )
}

export default BAHitlCard
