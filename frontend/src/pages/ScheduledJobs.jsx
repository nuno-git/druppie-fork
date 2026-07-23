/**
 * Scheduled Jobs Page
 *
 * Cron job definitions and their run history. Moved out of the Approvals
 * (Tasks) page into its own tab so scheduling lives separately from approvals.
 *
 * Layout (top → bottom):
 *   1. Header with a manual refresh.
 *   2. Summary stats (totals / enabled / approval-gated / agents).
 *   3. Job definition cards (enabled first), each with pause/resume,
 *      next-run time and its own recent-run strip.
 *   4. Collapsible, status-filterable global run history. Rows expand to
 *      show logs and LLM usage from the run-detail endpoint.
 */

import React, { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import {
  CheckCircle, XCircle, Clock, Shield, AlertCircle, Loader2, MessageSquare,
  Bot, ExternalLink, ChevronDown, ChevronRight, CalendarClock, Play, RefreshCw,
  Ban, Zap, Users, History, ListChecks, Pause, Timer, Cpu,
} from 'lucide-react'
import { getJobRun, getJobRuns, getJobs, triggerJob, pauseJob, resumeJob } from '../services/api'
import { useToast } from '../components/Toast'
import PageHeader from '../components/shared/PageHeader'
import EmptyState from '../components/shared/EmptyState'

const ACTIVE_STATUSES = ['completed', 'failed', 'rejected', 'cancelled']

const activeRunPolling = (query) => {
  const latestItems = query.state.data?.items || []
  const hasActive = latestItems.some((r) => !ACTIVE_STATUSES.includes(r.status))
  return hasActive ? 5000 : false
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const STATUS_CONFIG = {
  completed: { label: 'Completed', icon: CheckCircle, cls: 'bg-green-50 text-green-700 ring-green-600/20' },
  failed: { label: 'Failed', icon: XCircle, cls: 'bg-red-50 text-red-700 ring-red-600/20' },
  rejected: { label: 'Rejected', icon: XCircle, cls: 'bg-red-50 text-red-700 ring-red-600/20' },
  cancelled: { label: 'Cancelled', icon: Ban, cls: 'bg-gray-100 text-gray-600 ring-gray-500/20' },
  running: { label: 'Running', icon: Loader2, cls: 'bg-blue-50 text-blue-700 ring-blue-600/20', spin: true },
  waiting_approval: { label: 'Waiting Approval', icon: Shield, cls: 'bg-amber-50 text-amber-700 ring-amber-600/20' },
  pending: { label: 'Pending', icon: Clock, cls: 'bg-gray-100 text-gray-600 ring-gray-500/20' },
}

const StatusBadge = ({ status }) => {
  const cfg = STATUS_CONFIG[status] || {
    label: status || 'Unknown', icon: Clock, cls: 'bg-gray-100 text-gray-600 ring-gray-500/20',
  }
  const Icon = cfg.icon
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 text-xs font-medium rounded-full ring-1 ring-inset whitespace-nowrap ${cfg.cls}`}>
      <Icon className={`w-3 h-3 ${cfg.spin ? 'animate-spin' : ''}`} />
      {cfg.label}
    </span>
  )
}

// Filter options for the run-history section (server-side via ?status=).
const RUN_FILTERS = [
  { value: null, label: 'All' },
  { value: 'completed', label: 'Completed' },
  { value: 'running', label: 'Running' },
  { value: 'waiting_approval', label: 'Waiting Approval' },
  { value: 'failed', label: 'Failed' },
  { value: 'rejected', label: 'Rejected' },
]

const CRON_DOW = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']
const CRON_MACROS = {
  '@yearly': 'Yearly', '@annually': 'Yearly', '@monthly': 'Monthly',
  '@weekly': 'Weekly', '@daily': 'Daily', '@midnight': 'Daily at midnight', '@hourly': 'Hourly',
}

// Turn a cron expression into a plain-English phrase for the common cases.
// Returns null when the pattern is too complex, so callers can fall back to
// rendering the raw expression.
const humanizeCron = (expr) => {
  if (!expr || typeof expr !== 'string') return null
  const s = expr.trim()
  if (CRON_MACROS[s]) return CRON_MACROS[s]

  const parts = s.split(/\s+/)
  if (parts.length < 5) return null
  const [min, hour, dom, mon, dow] = parts
  const pad = (n) => String(n).padStart(2, '0')
  const isNum = (v) => /^\d+$/.test(v)
  const anyDate = dom === '*' && mon === '*'

  if (min === '*' && hour === '*' && anyDate && dow === '*') return 'Every minute'

  const everyMin = min.match(/^\*\/(\d+)$/)
  if (everyMin && hour === '*' && anyDate && dow === '*') return `Every ${everyMin[1]} minutes`

  const everyHour = hour.match(/^\*\/(\d+)$/)
  if (isNum(min) && everyHour && anyDate && dow === '*') return `Every ${everyHour[1]} hours`

  if (isNum(min) && hour === '*' && anyDate && dow === '*') return `Hourly at :${pad(min)}`

  if (isNum(min) && isNum(hour)) {
    const at = `${pad(hour)}:${pad(min)}`
    if (anyDate && dow === '*') return `Daily at ${at}`
    if (dom === '*' && mon === '*' && isNum(dow)) return `Weekly on ${CRON_DOW[Number(dow) % 7]} at ${at}`
    if (isNum(dom) && mon === '*' && dow === '*') return `Monthly on day ${dom} at ${at}`
  }
  return null
}

// "3h ago" for past dates, "in 3h" for future ones (e.g. next_run_at).
const formatRelativeTime = (dateStr) => {
  if (!dateStr) return null
  const then = new Date(dateStr).getTime()
  if (Number.isNaN(then)) return null
  const future = then > Date.now()
  const sec = Math.abs(Math.round((Date.now() - then) / 1000))
  const fmt = (v, unit) => (future ? `in ${v}${unit}` : `${v}${unit} ago`)
  if (sec < 60) return future ? 'in <1m' : 'just now'
  const min = Math.round(sec / 60)
  if (min < 60) return fmt(min, 'm')
  const hr = Math.round(min / 60)
  if (hr < 24) return fmt(hr, 'h')
  const day = Math.round(hr / 24)
  if (day < 30) return fmt(day, 'd')
  const mo = Math.round(day / 30)
  if (mo < 12) return fmt(mo, 'mo')
  return fmt(Math.round(mo / 12), 'y')
}

const formatDuration = (ms) => {
  if (ms == null || Number.isNaN(ms) || ms < 0) return null
  const sec = Math.round(ms / 1000)
  if (sec < 60) return `${sec}s`
  const min = Math.floor(sec / 60)
  if (min < 60) return `${min}m ${sec % 60}s`
  return `${Math.floor(min / 60)}h ${min % 60}m`
}

// ---------------------------------------------------------------------------
// Small presentational pieces
// ---------------------------------------------------------------------------

const StatCard = ({ icon: Icon, label, value, tone }) => (
  <div className="bg-white rounded-xl border border-gray-100 p-4 flex items-center gap-3">
    <div className={`w-10 h-10 rounded-lg flex items-center justify-center flex-shrink-0 ${tone}`}>
      <Icon className="w-5 h-5" />
    </div>
    <div className="min-w-0">
      <div className="text-2xl font-bold text-gray-900 leading-none">{value}</div>
      <div className="text-xs text-gray-500 mt-1 truncate">{label}</div>
    </div>
  </div>
)

const CronSchedule = ({ schedule }) => {
  const human = humanizeCron(schedule)
  return (
    <span className="inline-flex items-center gap-1.5" title={schedule}>
      <Clock className="w-3.5 h-3.5 text-gray-400" />
      {human ? (
        <>
          <span className="text-gray-600">{human}</span>
          <code className="font-mono text-gray-400">{schedule}</code>
        </>
      ) : (
        <code className="font-mono text-gray-600">{schedule}</code>
      )}
    </span>
  )
}

const SessionLinks = ({ sessionId, showInspect = false }) => (
  <>
    <Link
      to={`/chat?session=${sessionId}`}
      className="inline-flex items-center gap-1 text-blue-600 hover:text-blue-800 hover:underline"
    >
      <MessageSquare className="w-3 h-3" />
      Session
    </Link>
    {showInspect && (
      <Link
        to={`/chat?session=${sessionId}&mode=inspect`}
        className="inline-flex items-center gap-1 text-indigo-600 hover:text-indigo-800 hover:underline"
      >
        <ExternalLink className="w-3 h-3" />
        Inspect
      </Link>
    )}
  </>
)

// ---------------------------------------------------------------------------
// Job definition card
// ---------------------------------------------------------------------------

const JobCard = ({ job, onTrigger, isTriggering, onToggleEnabled, isToggling }) => {
  const { data: runsResponse, isLoading: runsLoading } = useQuery({
    queryKey: ['jobRuns', job.id],
    queryFn: () => getJobRuns(job.id, null, 1, 5),
    refetchInterval: activeRunPolling,
  })
  const jobRuns = runsResponse?.items || []

  return (
    <div className="bg-white rounded-xl border border-gray-100 p-4 hover:border-gray-200 transition-colors">
      <div className="flex items-start justify-between gap-4">
        <div className="flex items-start gap-3 flex-1 min-w-0">
          <div className={`w-9 h-9 rounded-lg flex items-center justify-center flex-shrink-0 ${job.enabled ? 'bg-blue-50 text-blue-600' : 'bg-gray-100 text-gray-400'}`}>
            <CalendarClock className="w-5 h-5" />
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <h3 className="font-medium text-gray-900 truncate">{job.name}</h3>
              <span className={`inline-flex items-center gap-1 px-2 py-0.5 text-xs font-medium rounded-full ${job.enabled ? 'bg-green-50 text-green-700' : 'bg-gray-100 text-gray-500'}`}>
                <span className={`w-1.5 h-1.5 rounded-full ${job.enabled ? 'bg-green-500' : 'bg-gray-400'}`} />
                {job.enabled ? 'Enabled' : 'Disabled'}
              </span>
              {job.approval_required && (
                <span className="inline-flex items-center gap-1 px-2 py-0.5 bg-amber-50 text-amber-700 text-xs font-medium rounded-full">
                  <Shield className="w-3 h-3" />
                  Approval{job.required_role ? ` · ${job.required_role}` : ''}
                </span>
              )}
            </div>
            {job.description && (
              <p className="text-gray-500 text-sm mt-1">{job.description}</p>
            )}
            <div className="flex items-center gap-x-4 gap-y-1 mt-2 text-xs text-gray-500 flex-wrap">
              <CronSchedule schedule={job.schedule} />
              <span className="inline-flex items-center gap-1.5">
                <Bot className="w-3.5 h-3.5 text-gray-400" />
                {job.agent_id}
              </span>
              {job.last_triggered_at && (
                <span className="inline-flex items-center gap-1.5" title={new Date(job.last_triggered_at).toLocaleString()}>
                  <History className="w-3.5 h-3.5 text-gray-400" />
                  Last run {formatRelativeTime(job.last_triggered_at)}
                </span>
              )}
              {job.enabled && job.next_run_at && (
                <span className="inline-flex items-center gap-1.5 text-blue-600 font-medium" title={new Date(job.next_run_at).toLocaleString()}>
                  <CalendarClock className="w-3.5 h-3.5" />
                  Next run {formatRelativeTime(job.next_run_at)}
                </span>
              )}
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2 flex-shrink-0">
          <button
            onClick={() => onToggleEnabled(job)}
            disabled={isToggling}
            title={job.enabled ? 'Pause the schedule (stops triggering)' : 'Resume the schedule'}
            className="px-3 py-1.5 text-sm font-medium text-gray-700 bg-white border border-gray-200 rounded-lg hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-1.5 transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2"
          >
            {isToggling ? (
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
            ) : job.enabled ? (
              <Pause className="w-3.5 h-3.5" />
            ) : (
              <Play className="w-3.5 h-3.5" />
            )}
            {job.enabled ? 'Pause' : 'Resume'}
          </button>
          <button
            onClick={() => onTrigger(job.id)}
            disabled={isTriggering}
            className="px-3 py-1.5 text-sm font-medium bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:bg-gray-300 disabled:cursor-not-allowed flex items-center gap-1.5 transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2"
          >
            {isTriggering ? (
              <><Loader2 className="w-3.5 h-3.5 animate-spin" />Triggering…</>
            ) : (
              <><Play className="w-3.5 h-3.5" />Run Now</>
            )}
          </button>
        </div>
      </div>

      <div className="mt-4 pt-3 border-t border-gray-100">
        <p className="text-xs font-medium text-gray-500 mb-2">Recent runs</p>
        {runsLoading ? (
          <div className="flex items-center gap-2 text-xs text-gray-400">
            <Loader2 className="w-3 h-3 animate-spin" />
            Loading runs…
          </div>
        ) : jobRuns.length === 0 ? (
          <p className="text-xs text-gray-400">No runs yet.</p>
        ) : (
          <div className="space-y-1.5">
            {jobRuns.map((run) => (
              <div key={run.id} className="flex items-center gap-3 text-xs">
                <StatusBadge status={run.status} />
                <span className="text-gray-400">{run.trigger_type}</span>
                {run.started_at && (
                  <span className="text-gray-400" title={new Date(run.started_at).toLocaleString()}>
                    {formatRelativeTime(run.started_at)}
                  </span>
                )}
                {run.error_message && (
                  <span className="text-red-500 truncate max-w-[220px]" title={run.error_message}>
                    {run.error_message}
                  </span>
                )}
                {run.session_id && (
                  <span className="ml-auto flex items-center gap-3">
                    <SessionLinks sessionId={run.session_id} />
                  </span>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Global run-history row (expandable: logs + LLM usage from the detail endpoint)
// ---------------------------------------------------------------------------

const UsageStat = ({ icon: Icon, label, value, title, warn }) => (
  <span
    className={`inline-flex items-center gap-1.5 px-2 py-1 text-xs rounded-lg ${warn ? 'bg-amber-50 text-amber-700' : 'bg-gray-50 text-gray-600'}`}
    title={title}
  >
    <Icon className="w-3 h-3" />
    <span className="font-medium">{value}</span>
    {label}
  </span>
)

const RunRow = ({ run, jobName }) => {
  const [expanded, setExpanded] = useState(false)
  const { data: detail, isLoading: detailLoading } = useQuery({
    queryKey: ['jobRun', run.id],
    queryFn: () => getJobRun(run.id),
    enabled: expanded,
  })
  const duration = run.started_at && run.completed_at
    ? formatDuration(new Date(run.completed_at) - new Date(run.started_at))
    : null
  const usage = detail?.usage

  return (
    <div className="bg-white rounded-lg border border-gray-100 hover:border-gray-200 transition-colors">
      <div
        role="button"
        tabIndex={0}
        onClick={() => setExpanded(!expanded)}
        onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setExpanded(!expanded) } }}
        aria-expanded={expanded}
        className="p-4 cursor-pointer focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-inset rounded-lg"
      >
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              {expanded ? (
                <ChevronDown className="w-4 h-4 text-gray-400 flex-shrink-0" />
              ) : (
                <ChevronRight className="w-4 h-4 text-gray-400 flex-shrink-0" />
              )}
              <span className="font-medium text-gray-900">{jobName || 'Unknown job'}</span>
              <StatusBadge status={run.status} />
              <span className="inline-flex items-center gap-1 px-2 py-0.5 bg-purple-50 text-purple-600 text-xs font-medium rounded-full">
                <Bot className="w-3 h-3" />
                {run.trigger_type || 'scheduled'}
              </span>
              {duration && (
                <span className="inline-flex items-center gap-1 text-xs text-gray-500">
                  <Timer className="w-3 h-3" />
                  {duration}
                </span>
              )}
            </div>
            {run.error_message && (
              <p className="text-red-500 text-sm mt-2 line-clamp-2">{run.error_message}</p>
            )}
            {run.status === 'rejected' && run.rejection_reason && (
              <p className="text-red-500 text-sm mt-2 line-clamp-2">Reason: {run.rejection_reason}</p>
            )}
            <div className="flex items-center gap-4 mt-2 text-xs text-gray-500 flex-wrap">
              {run.started_at && (
                <span className="inline-flex items-center gap-1" title={new Date(run.started_at).toLocaleString()}>
                  <Clock className="w-3 h-3" />
                  Started {formatRelativeTime(run.started_at)}
                </span>
              )}
              {run.completed_at && (
                <span className="inline-flex items-center gap-1" title={new Date(run.completed_at).toLocaleString()}>
                  <CheckCircle className="w-3 h-3" />
                  Finished {formatRelativeTime(run.completed_at)}
                </span>
              )}
            </div>
          </div>
          {run.session_id && (
            <div className="flex items-center gap-3 text-xs" onClick={(e) => e.stopPropagation()}>
              <SessionLinks sessionId={run.session_id} showInspect />
            </div>
          )}
        </div>
      </div>

      {expanded && (
        <div className="border-t border-gray-100 px-4 py-3 space-y-3">
          {detailLoading ? (
            <div className="flex items-center gap-2 text-xs text-gray-400">
              <Loader2 className="w-3 h-3 animate-spin" />
              Loading run details…
            </div>
          ) : (
            <>
              {usage && (
                <div className="flex items-center gap-2 flex-wrap">
                  <UsageStat icon={Cpu} label="LLM calls" value={usage.llm_calls} />
                  <UsageStat
                    icon={Zap}
                    label="tokens"
                    value={usage.total_tokens?.toLocaleString()}
                    title={`${usage.prompt_tokens?.toLocaleString()} prompt + ${usage.completion_tokens?.toLocaleString()} completion`}
                  />
                  {usage.duration_ms != null && (
                    <UsageStat icon={Timer} label="LLM time" value={formatDuration(usage.duration_ms)} />
                  )}
                  {usage.fallback_calls > 0 && (
                    <UsageStat icon={AlertCircle} label="fallback calls" value={usage.fallback_calls} warn />
                  )}
                  {usage.models?.length > 0 && (
                    <UsageStat icon={Bot} label="" value={usage.models.join(', ')} />
                  )}
                </div>
              )}
              {detail?.logs ? (
                <pre className="bg-gray-900 text-gray-100 rounded-lg p-3 text-xs font-mono whitespace-pre-wrap max-h-64 overflow-auto">
                  {detail.logs}
                </pre>
              ) : (
                <p className="text-xs text-gray-400">No logs for this run.</p>
              )}
            </>
          )}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

const ScheduledJobs = () => {
  const queryClient = useQueryClient()
  const toast = useToast()
  const [showJobRuns, setShowJobRuns] = useState(false)
  const [runFilter, setRunFilter] = useState(null)
  const [triggeringJobId, setTriggeringJobId] = useState(null)
  const [togglingJobId, setTogglingJobId] = useState(null)

  const {
    data: jobsResponse, isLoading: jobsLoading, isError: jobsError,
    error: jobsErrorObj, isFetching: jobsFetching, refetch: refetchJobs,
  } = useQuery({
    queryKey: ['jobs'],
    queryFn: getJobs,
  })

  const { data: jobRunsResponse, isLoading: jobRunsLoading } = useQuery({
    queryKey: ['jobRuns', 'all', runFilter],
    queryFn: () => getJobRuns(null, runFilter, 1, 20),
    enabled: showJobRuns,
    refetchInterval: activeRunPolling,
  })

  const triggerJobMutation = useMutation({
    mutationFn: (jobDefinitionId) => triggerJob(jobDefinitionId),
    onSuccess: (data) => {
      setTriggeringJobId(null)
      queryClient.invalidateQueries({ queryKey: ['jobs'] })
      queryClient.invalidateQueries({ queryKey: ['jobRuns'] })
      toast.success('Job Triggered', `Job run started. Session: ${data?.session_id?.slice(0, 8)}...`)
    },
    onError: (err) => {
      setTriggeringJobId(null)
      toast.error('Trigger Failed', err.message || 'Failed to trigger job.')
    },
  })

  const toggleEnabledMutation = useMutation({
    mutationFn: (job) => (job.enabled ? pauseJob(job.id) : resumeJob(job.id)),
    onSuccess: (data) => {
      setTogglingJobId(null)
      queryClient.invalidateQueries({ queryKey: ['jobs'] })
      toast.success(
        data?.enabled ? 'Schedule Resumed' : 'Schedule Paused',
        data?.enabled
          ? `"${data.name}" will run on its cron schedule again.`
          : `"${data.name}" won't trigger automatically. Run Now still works.`,
      )
    },
    onError: (err) => {
      setTogglingJobId(null)
      toast.error('Update Failed', err.message || 'Failed to update the schedule.')
    },
  })

  const jobs = jobsResponse?.items || []
  // Enabled jobs first; backend already orders by name within each group.
  const sortedJobs = [...jobs].sort((a, b) => Number(b.enabled) - Number(a.enabled))
  const jobNameById = Object.fromEntries(jobs.map((j) => [j.id, j.name]))
  const enabledCount = jobs.filter((j) => j.enabled).length
  const approvalCount = jobs.filter((j) => j.approval_required).length
  const agentCount = new Set(jobs.map((j) => j.agent_id).filter(Boolean)).size
  const runs = jobRunsResponse?.items || []

  return (
    <div className="space-y-6">
      <PageHeader title="Scheduled Jobs" subtitle="Cron job definitions loaded from YAML. Trigger any job manually with Run Now.">
        <button
          onClick={() => refetchJobs()}
          disabled={jobsFetching}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium text-gray-600 bg-white border border-gray-200 rounded-lg hover:bg-gray-50 disabled:opacity-50 transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${jobsFetching ? 'animate-spin' : ''}`} />
          Refresh
        </button>
      </PageHeader>

      {/* Summary stats */}
      {!jobsLoading && !jobsError && jobs.length > 0 && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
          <StatCard icon={CalendarClock} label="Total jobs" value={jobs.length} tone="bg-blue-50 text-blue-600" />
          <StatCard icon={Zap} label="Enabled" value={enabledCount} tone="bg-green-50 text-green-600" />
          <StatCard icon={Shield} label="Require approval" value={approvalCount} tone="bg-amber-50 text-amber-600" />
          <StatCard icon={Users} label="Agents" value={agentCount} tone="bg-purple-50 text-purple-600" />
        </div>
      )}

      {jobsLoading ? (
        <div className="space-y-4">
          {Array.from({ length: 2 }).map((_, i) => (
            <div key={i} className="bg-white rounded-xl border border-gray-100 p-4 animate-pulse">
              <div className="w-32 h-4 bg-gray-200 rounded mb-2" />
              <div className="w-3/4 h-3 bg-gray-100 rounded" />
            </div>
          ))}
        </div>
      ) : jobsError ? (
        <EmptyState
          icon={AlertCircle}
          title="Failed to load jobs"
          description={jobsErrorObj?.message || 'An unexpected error occurred'}
        />
      ) : jobs.length === 0 ? (
        <EmptyState
          icon={CalendarClock}
          title="No scheduled jobs"
          description="Add YAML definitions to druppie/jobs/definitions/"
        />
      ) : (
        <div className="space-y-4">
          {sortedJobs.map((job) => (
            <JobCard
              key={job.id}
              job={job}
              onTrigger={(id) => {
                setTriggeringJobId(id)
                triggerJobMutation.mutate(id)
              }}
              isTriggering={triggeringJobId === job.id}
              onToggleEnabled={(j) => {
                setTogglingJobId(j.id)
                toggleEnabledMutation.mutate(j)
              }}
              isToggling={togglingJobId === job.id}
            />
          ))}
        </div>
      )}

      {/* Job Runs Section */}
      <div className="mt-8 border-t pt-6">
        <button
          onClick={() => setShowJobRuns(!showJobRuns)}
          className="flex items-center gap-2 text-lg font-semibold text-gray-700 hover:text-gray-900 transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500 rounded"
          aria-expanded={showJobRuns}
          aria-controls="job-runs"
        >
          {showJobRuns ? <ChevronDown className="w-5 h-5" /> : <ChevronRight className="w-5 h-5" />}
          <ListChecks className="w-5 h-5 text-blue-500" />
          Run History
        </button>

        {showJobRuns && (
          <div id="job-runs" className="mt-4 space-y-4">
            {/* Status filter chips */}
            <div className="flex items-center gap-2 flex-wrap">
              {RUN_FILTERS.map((f) => (
                <button
                  key={f.label}
                  onClick={() => setRunFilter(f.value)}
                  className={`px-3 py-1 text-xs font-medium rounded-full border transition-colors ${
                    runFilter === f.value
                      ? 'bg-blue-600 text-white border-blue-600'
                      : 'bg-white text-gray-600 border-gray-200 hover:bg-gray-50'
                  }`}
                >
                  {f.label}
                </button>
              ))}
            </div>

            {jobRunsLoading ? (
              <div className="flex items-center justify-center h-32 bg-white rounded-xl border border-gray-100">
                <Loader2 className="w-6 h-6 animate-spin text-blue-500" />
                <span className="ml-2 text-gray-600">Loading run history…</span>
              </div>
            ) : runs.length > 0 ? (
              <div className="space-y-3">
                {runs.map((run) => (
                  <RunRow key={run.id} run={run} jobName={jobNameById[run.job_definition_id]} />
                ))}
              </div>
            ) : (
              <EmptyState
                icon={ListChecks}
                title="No job runs"
                description={runFilter ? `No runs with status "${runFilter}".` : 'No job runs found yet.'}
              />
            )}
          </div>
        )}
      </div>
    </div>
  )
}

export default ScheduledJobs
