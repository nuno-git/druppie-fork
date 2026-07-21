/**
 * Scheduled Jobs Page
 *
 * Cron job definitions and their run history. Moved out of the Approvals
 * (Tasks) page into its own tab so scheduling lives separately from approvals.
 */

import React, { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { CheckCircle, XCircle, Clock, Shield, AlertCircle, Loader2, MessageSquare, Bot, ExternalLink, ChevronDown, ChevronRight, Calendar } from 'lucide-react'
import { getJobRuns, getJobs, triggerJob } from '../services/api'
import { useAuth } from '../App'
import { useToast } from '../components/Toast'
import PageHeader from '../components/shared/PageHeader'
import EmptyState from '../components/shared/EmptyState'

const activeRunPolling = (query) => {
  const latestItems = query.state.data?.items || []
  const hasActive = latestItems.some(
    (r) => !['completed', 'failed', 'rejected', 'cancelled'].includes(r.status)
  )
  return hasActive ? 5000 : false
}

const JobCard = ({ job, onTrigger, isTriggering }) => {
  const { data: runsResponse, isLoading: runsLoading } = useQuery({
    queryKey: ['jobRuns', job.id],
    queryFn: () => getJobRuns(job.id, null, 1, 5),
    refetchInterval: activeRunPolling,
  })
  const jobRuns = runsResponse?.items || []

  return (
    <div className="bg-white rounded-xl border border-gray-100 p-4">
      <div className="flex items-start justify-between gap-4">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <Calendar className="w-4 h-4 text-blue-500 flex-shrink-0" />
            <h3 className="font-medium text-gray-900">{job.name}</h3>
            <span className={`px-2 py-0.5 text-xs rounded-full ${job.enabled ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-500'}`}>
              {job.enabled ? 'Enabled' : 'Disabled'}
            </span>
            {job.approval_required && (
              <span className="px-2 py-0.5 bg-amber-100 text-amber-700 text-xs rounded-full flex items-center">
                <Shield className="w-3 h-3 mr-1" />
                Approval Required
                {job.required_role && ` (${job.required_role})`}
              </span>
            )}
          </div>
          <p className="text-gray-400 text-sm mt-1">{job.description}</p>
          <div className="flex items-center gap-4 mt-2 text-xs text-gray-500 flex-wrap">
            <span className="flex items-center gap-1">
              <Clock className="w-3 h-3" />
              {job.schedule}
            </span>
            <span className="flex items-center gap-1">
              <Bot className="w-3 h-3" />
              Agent: {job.agent_id}
            </span>
          </div>
        </div>
        <button
          onClick={() => onTrigger(job.id)}
          disabled={isTriggering}
          className="px-3 py-1.5 text-sm bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:bg-gray-300 flex items-center gap-1.5 flex-shrink-0 transition-colors"
        >
          {isTriggering ? (
            <><Loader2 className="w-3.5 h-3.5 animate-spin" />Triggering…</>
          ) : (
            <><Calendar className="w-3.5 h-3.5" />Run Now</>
          )}
        </button>
      </div>

      {runsLoading ? (
        <div className="mt-3 pt-3 border-t border-gray-50">
          <div className="flex items-center gap-2 text-xs text-gray-400">
            <Loader2 className="w-3 h-3 animate-spin" />
            Loading runs...
          </div>
        </div>
      ) : jobRuns.length > 0 && (
        <div className="mt-3 pt-3 border-t border-gray-50">
          <p className="text-xs font-medium text-gray-500 mb-2">Recent runs</p>
          <div className="space-y-2">
            {jobRuns.map((run) => (
              <div key={run.id} className="flex items-center gap-3 text-xs">
                <span className={`px-1.5 py-0.5 rounded-full ${
                  run.status === 'completed'
                    ? 'bg-green-100 text-green-700'
                    : run.status === 'failed'
                    ? 'bg-red-100 text-red-700'
                    : run.status === 'rejected'
                    ? 'bg-red-100 text-red-700'
                    : run.status === 'running'
                    ? 'bg-blue-100 text-blue-700'
                    : run.status === 'waiting_approval'
                    ? 'bg-amber-100 text-amber-700'
                    : 'bg-gray-100 text-gray-600'
                }`}>
                  {run.status === 'waiting_approval' ? 'Waiting Approval' : run.status}
                </span>
                <span className="text-gray-400">{run.trigger_type}</span>
                {run.started_at && (
                  <span className="text-gray-400">{new Date(run.started_at).toLocaleString()}</span>
                )}
                {run.error_message && (
                  <span className="text-red-500 truncate max-w-[200px]">{run.error_message}</span>
                )}
                {run.session_id && (
                  <Link
                    to={`/chat?session=${run.session_id}`}
                    className="text-blue-600 hover:text-blue-800 hover:underline"
                  >
                    View Session
                  </Link>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

const ScheduledJobs = () => {
  const queryClient = useQueryClient()
  const toast = useToast()
  const [showJobRuns, setShowJobRuns] = useState(false)
  const [triggeringJobId, setTriggeringJobId] = useState(null)

  const { data: jobsResponse, isLoading: jobsLoading, isError: jobsError, error: jobsErrorObj } = useQuery({
    queryKey: ['jobs'],
    queryFn: getJobs,
  })

  const { data: jobRunsResponse, isLoading: jobRunsLoading } = useQuery({
    queryKey: ['jobRuns'],
    queryFn: () => getJobRuns(null, null, 1, 20),
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

  const jobs = jobsResponse?.items || []

  return (
    <div className="space-y-6">
      <PageHeader title="Scheduled Jobs" subtitle="Cron job definitions. Click Run Now to trigger manually.">
        <div className="flex items-center gap-2">
          <span className="text-sm text-gray-400">Jobs loaded from YAML definitions</span>
        </div>
      </PageHeader>

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
          icon={Calendar}
          title="No scheduled jobs"
          description="Add YAML definitions to druppie/jobs/definitions/"
        />
      ) : (
        <div className="space-y-4">
          {jobs.map((job) => (
            <JobCard
              key={job.id}
              job={job}
              onTrigger={(id) => {
                setTriggeringJobId(id)
                triggerJobMutation.mutate(id)
              }}
              isTriggering={triggeringJobId === job.id}
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
          {showJobRuns ? (
            <ChevronDown className="w-5 h-5" />
          ) : (
            <ChevronRight className="w-5 h-5" />
          )}
          <Calendar className="w-5 h-5 text-blue-500" />
          Job Runs
        </button>

        {showJobRuns && (
          <div id="job-runs" className="mt-4">
            {jobRunsLoading ? (
              <div className="flex items-center justify-center h-32 bg-white rounded-xl border border-gray-100">
                <Loader2 className="w-6 h-6 animate-spin text-blue-500" />
                <span className="ml-2 text-gray-600">Loading job runs...</span>
              </div>
            ) : jobRunsResponse?.items?.length > 0 ? (
              <div className="space-y-3">
                {jobRunsResponse.items.map((run) => (
                  <div
                    key={run.id}
                    className="bg-white rounded-lg border border-gray-100 p-4 hover:border-gray-200 transition-colors"
                  >
                    <div className="flex items-start justify-between">
                      <div className="flex-1">
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className="font-medium">Job Run</span>
                          <span className={`px-2 py-0.5 text-xs rounded-full flex items-center ${
                            run.status === 'completed'
                              ? 'bg-green-100 text-green-700'
                              : run.status === 'failed'
                              ? 'bg-red-100 text-red-700'
                              : run.status === 'rejected'
                              ? 'bg-red-100 text-red-700'
                              : run.status === 'running'
                              ? 'bg-blue-100 text-blue-700'
                              : 'bg-gray-100 text-gray-700'
                          }`}>
                            {run.status === 'completed' ? (
                              <><CheckCircle className="w-3 h-3 mr-1" />Completed</>
                            ) : run.status === 'failed' ? (
                              <><XCircle className="w-3 h-3 mr-1" />Failed</>
                            ) : run.status === 'rejected' ? (
                              <><XCircle className="w-3 h-3 mr-1" />Rejected</>
                            ) : run.status === 'running' ? (
                              <><Loader2 className="w-3 h-3 mr-1 animate-spin" />Running</>
                            ) : (
                              <><Clock className="w-3 h-3 mr-1" />{run.status}</>
                            )}
                          </span>
                          <span className="px-2 py-0.5 bg-purple-100 text-purple-600 text-xs rounded-full flex items-center">
                            <Bot className="w-3 h-3 mr-1" />
                            {run.trigger_type || 'scheduled'}
                          </span>
                        </div>
                        {run.error_message && (
                          <p className="text-red-500 text-sm mt-1 line-clamp-2">{run.error_message}</p>
                        )}
                        {run.logs && (
                          <p className="text-gray-500 text-sm mt-1 line-clamp-2">{run.logs}</p>
                        )}
                        <div className="flex items-center gap-4 mt-2 text-xs text-gray-500 flex-wrap">
                          {run.started_at && (
                            <span className="flex items-center gap-1">
                              <Clock className="w-3 h-3" />
                              Started: {new Date(run.started_at).toLocaleString()}
                            </span>
                          )}
                          {run.completed_at && (
                            <span className="flex items-center gap-1">
                              <CheckCircle className="w-3 h-3" />
                              Completed: {new Date(run.completed_at).toLocaleString()}
                            </span>
                          )}
                        </div>
                        {run.session_id && (
                          <div className="flex items-center gap-3 mt-2">
                            <Link
                              to={`/chat?session=${run.session_id}`}
                              className="inline-flex items-center gap-1 text-xs text-blue-600 hover:text-blue-800 hover:underline"
                            >
                              <MessageSquare className="w-3 h-3" />
                              View Session
                            </Link>
                            <Link
                              to={`/chat?session=${run.session_id}&mode=inspect`}
                              className="inline-flex items-center gap-1 text-xs text-indigo-600 hover:text-indigo-800 hover:underline"
                            >
                              <ExternalLink className="w-3 h-3" />
                              Inspect Trace
                            </Link>
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <EmptyState
                icon={Calendar}
                title="No job runs"
                description="No job runs found."
              />
            )}
          </div>
        )}
      </div>
    </div>
  )
}

export default ScheduledJobs
