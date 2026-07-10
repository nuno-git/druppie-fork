/**
 * ArchitectHitlCard - Human review card shown when session.status === 'paused_architect_hitl'.
 *
 * Approve continues the architect; reject requires choosing where to send it
 * next: back to BA HITL ('ba_hitl') or terminate ('terminate').
 */

import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Loader2, CheckCircle2, XCircle, CornerUpLeft, Ban } from 'lucide-react'
import { submitArchitectHitl, ARCHITECT_REJECT_NEXT } from '../../services/api'
import { useAuth } from '../../App'

const ROLES_THAT_CAN_ACT = ['architect', 'admin']

const BTN = 'inline-flex items-center justify-center gap-1.5 px-3 py-1.5 text-sm font-medium rounded-lg text-white transition-colors disabled:opacity-50 disabled:cursor-not-allowed'

const ArchitectHitlCard = ({ sessionId, session }) => {
  const queryClient = useQueryClient()
  const { user } = useAuth()
  const [showReject, setShowReject] = useState(false)

  const userRoles = user?.roles || []
  const isAdmin = userRoles.includes('admin')
  const canAct = isAdmin || userRoles.some((r) => ROLES_THAT_CAN_ACT.includes(r))

  const mutation = useMutation({
    mutationFn: (payload) => submitArchitectHitl(sessionId, payload),
    onSuccess: () => {
      setShowReject(false)
      queryClient.invalidateQueries({ queryKey: ['session', sessionId] })
      queryClient.invalidateQueries({ queryKey: ['escalation-history', sessionId] })
    },
  })

  const pending = mutation.isPending

  const rejectWith = (nextOnReject) => {
    if (!ARCHITECT_REJECT_NEXT.includes(nextOnReject) || pending) return
    mutation.mutate({ decision: 'reject', next_on_reject: nextOnReject })
  }

  if (!canAct) {
    return (
      <div className="border border-indigo-200 rounded-2xl shadow-sm px-4 py-3.5 bg-indigo-50">
        <div className="flex items-center gap-2 mb-1">
          <XCircle className="w-4 h-4 text-indigo-600 flex-shrink-0" />
          <p className="text-sm font-medium text-indigo-800">Architect review pending</p>
        </div>
        <p className="text-xs text-indigo-700 ml-6">Waiting for an authorised architect to approve or reject.</p>
      </div>
    )
  }

  return (
    <div className="border border-indigo-200 rounded-2xl shadow-sm px-4 py-3.5 bg-indigo-50">
      <div className="flex items-center gap-2 mb-1">
        <XCircle className="w-4 h-4 text-indigo-600 flex-shrink-0" />
        <p className="text-sm font-medium text-indigo-800">Architect review</p>
      </div>
      <p className="text-xs text-indigo-700 mb-3 ml-6">
        Approve to let the architect continue, or reject and choose where it goes next.
      </p>

      {showReject ? (
        <div className="ml-6 space-y-2">
          <p className="text-sm text-indigo-800">Reject — send where?</p>
          <div className="flex flex-wrap items-center gap-2">
            <button
              onClick={() => rejectWith('ba_hitl')}
              disabled={pending}
              className={`${BTN} bg-amber-600 hover:bg-amber-700`}
            >
              {pending ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <CornerUpLeft className="w-3.5 h-3.5" />}
              Back to BA review
            </button>
            <button
              onClick={() => rejectWith('terminate')}
              disabled={pending}
              className={`${BTN} bg-red-600 hover:bg-red-700`}
            >
              <Ban className="w-3.5 h-3.5" />
              Terminate session
            </button>
            <button
              onClick={() => setShowReject(false)}
              disabled={pending}
              className="px-3 py-1.5 text-sm text-gray-600 hover:text-gray-800 transition-colors"
            >
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <div className="ml-6 flex flex-wrap items-center gap-2">
          <button
            onClick={() => !pending && mutation.mutate({ decision: 'approve' })}
            disabled={pending}
            className={`${BTN} bg-green-600 hover:bg-green-700`}
          >
            {pending ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <CheckCircle2 className="w-3.5 h-3.5" />}
            Approve
          </button>
          <button
            onClick={() => setShowReject(true)}
            disabled={pending}
            className={`${BTN} bg-red-600 hover:bg-red-700`}
          >
            <XCircle className="w-3.5 h-3.5" />
            Reject
          </button>
        </div>
      )}

      {mutation.isError && (
        <p className="ml-6 mt-2 text-xs text-red-600">
          {mutation.error?.message || 'Action failed'}
        </p>
      )}
    </div>
  )
}

export default ArchitectHitlCard
