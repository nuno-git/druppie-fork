/**
 * EscalationHistoryList - Read-only list of escalation events for a session.
 * Rendered near the BA / Architect HITL cards.
 */

import { useQuery } from '@tanstack/react-query'
import { Loader2, History } from 'lucide-react'
import { getEscalationHistory } from '../../services/api'

const EVENT_LABELS = {
  ba_hitl_entered: { label: 'BA review started', tone: 'bg-amber-100 text-amber-800' },
  ba_hitl_iterate: { label: 'BA iterate', tone: 'bg-blue-100 text-blue-800' },
  ba_hitl_sticky_reenter: { label: 'Re-entered BA review (sticky)', tone: 'bg-amber-100 text-amber-800' },
  ba_hitl_ready: { label: 'BA marked ready', tone: 'bg-green-100 text-green-800' },
  ba_hitl_escalate: { label: 'BA escalated to architect', tone: 'bg-purple-100 text-purple-800' },
  architect_hitl_entered: { label: 'Architect review started', tone: 'bg-indigo-100 text-indigo-800' },
  architect_hitl_approve: { label: 'Architect approved', tone: 'bg-green-100 text-green-800' },
  architect_hitl_reject_to_ba: { label: 'Architect rejected → back to BA', tone: 'bg-amber-100 text-amber-800' },
  architect_hitl_reject_terminate: { label: 'Architect rejected → terminated', tone: 'bg-red-100 text-red-800' },
  session_terminated: { label: 'Session terminated', tone: 'bg-gray-200 text-gray-800' },
}

const formatTime = (iso) => {
  if (!iso) return ''
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString()
}

const shortId = (uuid) => (uuid ? String(uuid).slice(0, 8) : '')

const EscalationHistoryList = ({ sessionId }) => {
  const { data, isLoading, error } = useQuery({
    queryKey: ['escalation-history', sessionId],
    queryFn: () => getEscalationHistory(sessionId),
    enabled: !!sessionId,
  })

  const items = data?.items || []

  if (isLoading) {
    return (
      <div className="border border-gray-200 rounded-2xl shadow-sm px-4 py-3 bg-white flex items-center gap-2 text-sm text-gray-500">
        <Loader2 className="w-3.5 h-3.5 animate-spin" />
        Loading escalation history…
      </div>
    )
  }

  if (error) {
    return null
  }

  if (items.length === 0) {
    return null
  }

  return (
    <div className="border border-gray-200 rounded-2xl shadow-sm px-4 py-3 bg-white">
      <div className="flex items-center gap-2 mb-2">
        <History className="w-3.5 h-3.5 text-gray-500" />
        <p className="text-xs font-semibold uppercase tracking-wider text-gray-500">Escalation history</p>
      </div>
      <ol className="space-y-2">
        {items.map((ev) => {
          const meta = EVENT_LABELS[ev.event_type] || { label: ev.event_type, tone: 'bg-gray-100 text-gray-700' }
          return (
            <li key={ev.id} className="flex flex-col gap-1">
              <div className="flex flex-wrap items-center gap-2">
                <span className={`text-[10px] font-medium uppercase tracking-wider px-1.5 py-0.5 rounded ${meta.tone}`}>
                  {meta.label}
                </span>
                {typeof ev.rejection_count_at_event === 'number' && ev.rejection_count_at_event > 0 && (
                  <span className="text-[10px] text-gray-500">rejections: {ev.rejection_count_at_event}</span>
                )}
                <span className="ml-auto text-[11px] text-gray-400">{formatTime(ev.created_at)}</span>
              </div>
              {ev.feedback && (
                <p className="text-xs text-gray-600 break-words">{ev.feedback}</p>
              )}
              {ev.actor_user_id && (
                <p className="text-[10px] text-gray-400">by {shortId(ev.actor_user_id)}</p>
              )}
            </li>
          )
        })}
      </ol>
    </div>
  )
}

export default EscalationHistoryList
