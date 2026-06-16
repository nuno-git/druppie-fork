/**
 * Tasks (Approvals) Page
 */

import React, { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { CheckCircle, XCircle, Clock, Shield, AlertTriangle, AlertCircle, Loader2, MessageSquare, Bot, ExternalLink, ChevronDown, ChevronRight, History, User, FileCode, FilePlus, Terminal, GitBranch, Code, Eye, X, Calendar } from 'lucide-react'
import { getTasks, approveTask, rejectTask, getApprovalHistory, getJobRuns, getJobs, triggerJob, getPendingJobApprovals, approveJob, rejectJob } from '../services/api'
import { chatMarkdownComponents, ProjectRepoContext, SourceFileContext } from '../components/chat/ChatHelpers'
import { useAuth } from '../App'
import { hasRole } from '../services/keycloak'
import { useToast } from '../components/Toast'
import PageHeader from '../components/shared/PageHeader'
import { SkeletonTaskCard } from '../components/shared/Skeleton'
import EmptyState from '../components/shared/EmptyState'

const activeRunPolling = (query) => {
  const latestItems = query.state.data?.items || []
  const hasActive = latestItems.some(
    (r) => !['completed', 'failed', 'rejected', 'cancelled'].includes(r.status)
  )
  return hasActive ? 5000 : false
}

// Helper to check if a file path is a markdown file
const isMarkdownFile = (path) => {
  if (!path) return false
  return path.toLowerCase().endsWith('.md') || path.toLowerCase().endsWith('.mdx')
}

// Fullscreen modal for previewing file content
const FilePreviewModal = ({ files, onClose }) => {
  // files: [{ path, content }]
  const [rawOverrides, setRawOverrides] = useState({})

  const toggleRaw = (path) => {
    setRawOverrides((prev) => ({ ...prev, [path]: !prev[path] }))
  }

  const isRaw = (path) => {
    if (path in rawOverrides) return rawOverrides[path]
    return !isMarkdownFile(path)
  }

  // Close on Escape
  React.useEffect(() => {
    const handleKey = (e) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', handleKey)
    return () => window.removeEventListener('keydown', handleKey)
  }, [onClose])

  return (
    <>
      {/* Backdrop */}
      <div className="fixed inset-0 bg-black/40 z-30" onClick={onClose} />
      {/* Centered modal */}
      <div
        className="fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 z-40 bg-gray-900 rounded-lg shadow-2xl border border-gray-700 flex flex-col"
        style={{ width: 'min(1100px, 95vw)', height: 'min(90vh, 860px)' }}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-2.5 border-b border-gray-700 bg-gray-800 rounded-t-lg flex-shrink-0">
          <div className="flex items-center gap-2">
            <FileCode className="w-4 h-4 text-gray-400" />
            <span className="text-sm font-medium text-gray-200">
              {files.length === 1 ? files[0].path : `${files.length} files to be written`}
            </span>
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded text-gray-400 hover:text-gray-200 hover:bg-gray-700 transition-colors"
            title="Close (Esc)"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Scrollable content area */}
        <div className="flex-1 overflow-auto p-4">
          <div className="space-y-4">
            {files.map(({ path, content }) => (
              <div key={path} className="bg-gray-900 rounded-lg border border-gray-700 overflow-hidden">
                {/* File header */}
                <div className="flex items-center justify-between px-4 py-2.5 bg-gray-800 border-b border-gray-700">
                  <div className="flex items-center gap-3">
                    <FileCode className="w-4 h-4 text-gray-400" />
                    <span className="text-sm text-gray-200 font-mono">{path}</span>
                    <span className="text-xs px-2 py-0.5 bg-gray-700 text-gray-400 rounded">{getLanguageFromPath(path)}</span>
                  </div>
                  <div className="flex items-center gap-3">
                    {isMarkdownFile(path) && (
                      <button
                        onClick={() => toggleRaw(path)}
                        className="flex items-center gap-1.5 px-3 py-1 text-xs rounded-md transition-colors text-gray-400 hover:text-gray-200 hover:bg-gray-700 border border-gray-600"
                      >
                        {isRaw(path) ? <Eye className="w-3.5 h-3.5" /> : <Code className="w-3.5 h-3.5" />}
                        {isRaw(path) ? 'Preview' : 'Raw'}
                      </button>
                    )}
                    <span className="text-xs text-gray-500">{content?.split('\n').length || 0} lines</span>
                  </div>
                </div>
                {/* Content */}
                {isMarkdownFile(path) && !isRaw(path) ? (
                  <div className="p-6 markdown-content text-sm bg-white text-gray-900 rounded-b-lg">
                    <SourceFileContext.Provider value={path}>
                      <ReactMarkdown remarkPlugins={[remarkGfm]} components={chatMarkdownComponents}>{content}</ReactMarkdown>
                    </SourceFileContext.Provider>
                  </div>
                ) : (
                  <pre className="p-4 text-sm text-gray-100 whitespace-pre-wrap font-mono leading-relaxed">
                    {content}
                  </pre>
                )}
              </div>
            ))}
          </div>
        </div>
      </div>
    </>
  )
}

// Helper to get human-readable tool description
const getToolDescription = (toolName) => {
  const toolDescriptions = {
    'run_command': 'Execute a shell command in the workspace',
    'coding:run_command': 'Execute a shell command in the workspace',
    'write_file': 'Write content to a file in the workspace',
    'coding:write_file': 'Write content to a file in the workspace',
    'delete_file': 'Delete a file from the workspace',
    'coding:delete_file': 'Delete a file from the workspace',
    'commit_and_push': 'Commit changes and push to Git repository',
    'coding:commit_and_push': 'Commit changes and push to Git repository',
    'merge_to_main': 'Merge current branch to main branch',
    'coding:merge_to_main': 'Merge current branch to main branch',
    'build': 'Build a Docker image',
    'docker:build': 'Build a Docker image',
    'run': 'Run a Docker container',
    'docker:run': 'Run a Docker container',
    'stop': 'Stop a running Docker container',
    'docker:stop': 'Stop a running Docker container',
    'remove': 'Remove a Docker container',
    'docker:remove': 'Remove a Docker container',
    'exec_command': 'Execute command inside a Docker container',
    'docker:exec_command': 'Execute command inside a Docker container',
  }
  return toolDescriptions[toolName] || `Execute ${toolName}`
}

// Helper to detect language from file path for syntax highlighting hint
const getLanguageFromPath = (path) => {
  if (!path) return 'text'
  const ext = path.split('.').pop()?.toLowerCase()
  const langMap = {
    js: 'javascript', jsx: 'javascript', ts: 'typescript', tsx: 'typescript',
    py: 'python', rb: 'ruby', go: 'go', rs: 'rust', java: 'java',
    c: 'c', cpp: 'cpp', h: 'c', hpp: 'cpp', cs: 'csharp', php: 'php',
    swift: 'swift', kt: 'kotlin', scala: 'scala', sh: 'bash', bash: 'bash',
    yml: 'yaml', yaml: 'yaml', json: 'json', xml: 'xml', html: 'html',
    css: 'css', scss: 'scss', sql: 'sql', md: 'markdown', dockerfile: 'dockerfile',
  }
  return langMap[ext] || 'text'
}

// Helper to get tool icon and label
const getToolInfo = (toolName) => {
  const tools = {
    'write_file': { icon: FilePlus, label: 'Write File', color: 'text-blue-600' },
    'coding:write_file': { icon: FilePlus, label: 'Write File', color: 'text-blue-600' },
    'batch_write_files': { icon: FileCode, label: 'Write Files', color: 'text-blue-600' },
    'coding:batch_write_files': { icon: FileCode, label: 'Write Files', color: 'text-blue-600' },
    'run_command': { icon: Terminal, label: 'Run Command', color: 'text-gray-600' },
    'coding:run_command': { icon: Terminal, label: 'Run Command', color: 'text-gray-600' },
    'commit_and_push': { icon: GitBranch, label: 'Git Commit', color: 'text-green-600' },
    'coding:commit_and_push': { icon: GitBranch, label: 'Git Commit', color: 'text-green-600' },
  }
  return tools[toolName] || { icon: Code, label: toolName?.split(':').pop() || 'Tool', color: 'text-gray-600' }
}

// Helper to format agent display name
const formatAgentName = (agentId) => {
  if (!agentId) return null
  // Remove common suffixes like '_agent' and format nicely
  return agentId
    .replace(/_agent$/i, '')
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase())
}

const TaskCard = ({ task, onApprove, onReject }) => {
  const [rejectReason, setRejectReason] = useState('')
  const [showReject, setShowReject] = useState(false)
  const [showDetails, setShowDetails] = useState(false)
  const [showCodePreview, setShowCodePreview] = useState(false)
  const { user } = useAuth()

  // Extract arguments for content preview
  const args = task.mcp_arguments || task.arguments || {}
  const filePath = args.path || args.file_path
  const newContent = args.content
  const batchFiles = args.files
  const command = args.command
  const commitMessage = args.message || args.commit_message
  const isBatchWrite = !!batchFiles && Object.keys(batchFiles).length > 0

  // Normalize: derive required_role from required_roles array if not present
  const requiredRoles = task.required_roles || (task.required_role ? [task.required_role] : ['admin'])
  const requiredRole = task.required_role || (requiredRoles.length > 0 ? requiredRoles[0] : 'admin')

  // Check if user has any of the required roles
  // For session_owner approvals, check if user owns the session
  const isSessionOwnerApproval = requiredRoles.includes('session_owner')
  const canApprove = isSessionOwnerApproval
    ? (user?.id === task.session_user_id || hasRole('admin'))
    : requiredRoles.some(role => hasRole(role))

  // MULTI approval state
  const isMultiApproval = task.approval_type === 'multi'
  const requiredApprovals = task.required_approvals || 2
  const currentApprovals = task.current_approvals || 0
  const approvedByRoles = task.approved_by_roles || []
  const remainingRoles = requiredRoles.filter(role => !approvedByRoles.includes(role))

  // Get tool info
  const toolName = task.mcp_tool || task.tool_name || null
  const isWorkflowStep = task.approval_type === 'workflow_step'
  const toolDescription = toolName ? getToolDescription(toolName) : (isWorkflowStep ? 'Approve workflow checkpoint to proceed to next phase' : 'Approval required')
  return (
    <div className={`bg-white rounded-xl border p-4 ${isMultiApproval ? 'border-blue-200' : 'border-gray-100'}`}>
      {/* Header — compact summary line with inline actions */}
      <div className="flex items-start justify-between gap-4">
        <div className="flex-1 min-w-0">
          {isMultiApproval && (
            <div className="flex items-center gap-2 mb-1">
              <span className="text-blue-600 text-xs font-medium">Multi-Approval</span>
              <span className="px-1.5 py-0.5 bg-blue-100 text-blue-700 text-xs rounded-full">
                {currentApprovals}/{requiredApprovals}
              </span>
            </div>
          )}
          <div className="flex items-center gap-2 flex-wrap">
            {(() => {
              const info = toolName ? getToolInfo(toolName) : null
              const Icon = info?.icon || Shield
              return <Icon className={`w-4 h-4 flex-shrink-0 ${info?.color || 'text-gray-400'}`} />
            })()}
            <h3 className="font-medium text-gray-900">
              {task.name || (isWorkflowStep ? 'Workflow Checkpoint' : toolName?.split(':').pop() || 'Approval')}
            </h3>
            {task.agent_id && (
              <span className="text-xs text-gray-400">
                from {formatAgentName(task.agent_id)}
              </span>
            )}
          </div>
          <p className="text-gray-400 text-sm mt-0.5 truncate">{task.description || toolDescription}</p>
        </div>

        {/* Actions — compact, right-aligned */}
        {canApprove ? (
          <div className="flex items-center gap-2 flex-shrink-0">
            {!showReject ? (
              <>
                <button
                  onClick={() => onApprove(task.id)}
                  className={`px-3 py-1.5 text-sm text-white rounded-lg flex items-center focus:outline-none focus:ring-2 focus:ring-offset-2 ${
                    isMultiApproval ? 'bg-blue-600 hover:bg-blue-700 focus:ring-blue-500' : 'bg-green-600 hover:bg-green-700 focus:ring-green-500'
                  }`}
                  aria-label={isMultiApproval ? `Add approval ${currentApprovals + 1} of ${requiredApprovals}` : 'Approve task'}
                >
                  <CheckCircle className="w-4 h-4 mr-1.5" aria-hidden="true" />
                  {isMultiApproval ? `Approve (${currentApprovals + 1}/${requiredApprovals})` : 'Approve'}
                </button>
                <button
                  onClick={() => setShowReject(true)}
                  className="px-3 py-1.5 text-sm text-gray-500 hover:text-red-600 hover:bg-red-50 rounded-lg transition-colors focus:outline-none"
                  aria-label="Reject task"
                >
                  Reject
                </button>
              </>
            ) : null}
          </div>
        ) : (
          <span className="flex items-center gap-1.5 text-xs text-gray-400 flex-shrink-0">
            <Clock className="w-3.5 h-3.5 animate-pulse" />
            Needs {requiredRoles.join(' or ')}
          </span>
        )}
      </div>

      {/* Reject form — appears below header when active */}
      {canApprove && showReject && (
        <div className="mt-3 space-y-2">
          <textarea
            value={rejectReason}
            onChange={(e) => setRejectReason(e.target.value)}
            placeholder="Reason for rejection..."
            className="w-full px-3 py-2 border border-gray-200 rounded-lg focus:ring-2 focus:ring-red-500 focus:border-transparent text-sm resize-y"
            rows={3}
            maxLength={10000}
            autoFocus
          />
          <div className="flex items-center justify-between">
            <span className="text-xs text-gray-400">{rejectReason.length} / 10,000</span>
            <div className="flex items-center gap-2">
              <button
                onClick={() => setShowReject(false)}
                className="px-3 py-1.5 text-sm text-gray-500 hover:text-gray-700 rounded-lg"
              >
                Cancel
              </button>
              <button
                onClick={() => {
                  if (rejectReason.trim()) {
                    onReject(task.id, rejectReason)
                  }
                }}
                disabled={!rejectReason.trim()}
                className="px-3 py-1.5 text-sm bg-red-600 text-white rounded-lg hover:bg-red-700 disabled:opacity-50"
              >
                Confirm Reject
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Expandable details — collapsed by default */}
      {(command || commitMessage || newContent || isBatchWrite || Object.keys(args).length > 0) && (
        <div className="mt-3 pt-3 border-t border-gray-50">
          <button
            onClick={() => setShowDetails(!showDetails)}
            className="text-xs text-gray-400 hover:text-gray-600 flex items-center gap-1"
          >
            {showDetails ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
            Details
          </button>

          {showDetails && (
            <div className="mt-2 space-y-2">
              {/* Command preview */}
              {command && (
                <div className="bg-gray-900 rounded-lg p-3 overflow-x-auto">
                  <code className="text-green-400 text-sm font-mono whitespace-pre-wrap">$ {command}</code>
                </div>
              )}

              {/* Commit message */}
              {commitMessage && (
                <div className="bg-gray-50 rounded-lg p-3">
                  <p className="text-sm text-gray-700 whitespace-pre-wrap">{commitMessage}</p>
                </div>
              )}

              {/* File preview */}
              {(newContent || isBatchWrite) && (
                <div>
                  <button
                    onClick={() => setShowCodePreview(true)}
                    className="flex items-center gap-2 text-blue-600 hover:text-blue-800 text-sm focus:outline-none rounded"
                  >
                    <FileCode className="w-4 h-4" />
                    View {isBatchWrite ? `${Object.keys(batchFiles).length} files` : 'file'}
                  </button>
                  {showCodePreview && (
                    <ProjectRepoContext.Provider
                      value={task.repo_url || task.project_id ? {
                        id: task.project_id,
                        repo_url: task.repo_url,
                        default_branch: 'main',
                        session_id: task.session_id,
                      } : null}
                    >
                      <FilePreviewModal
                        files={
                          isBatchWrite
                            ? Object.entries(batchFiles).map(([path, content]) => ({ path, content }))
                            : [{ path: filePath || 'file', content: newContent }]
                        }
                        onClose={() => setShowCodePreview(false)}
                      />
                    </ProjectRepoContext.Provider>
                  )}
                </div>
              )}

              {/* Raw arguments */}
              {!command && !commitMessage && !newContent && !isBatchWrite && Object.keys(args).length > 0 && (
                <pre className="bg-gray-50 p-3 rounded text-xs overflow-x-auto text-gray-600 font-mono">
                  {JSON.stringify(args, null, 2)}
                </pre>
              )}

              {/* Context info — single line */}
              <div className="flex items-center gap-4 text-xs text-gray-400 flex-wrap">
                <span>{new Date(task.created_at).toLocaleString()}</span>
                {task.session_id && (
                  <Link to={`/chat?session=${task.session_id}`} className="text-blue-500 hover:text-blue-700 hover:underline flex items-center gap-1">
                    <MessageSquare className="w-3 h-3" />
                    Conversation
                  </Link>
                )}
                <span className={canApprove ? 'text-green-500' : ''}>
                  {isSessionOwnerApproval ? 'session owner' : requiredRoles.join(', ')}
                </span>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Multi-approval progress bar — only when relevant */}
      {isMultiApproval && (
        <div className="mt-3 pt-3 border-t border-gray-50">
          <div className="w-full bg-gray-100 rounded-full h-1.5">
            <div
              className="bg-blue-600 h-1.5 rounded-full transition-all"
              style={{ width: `${(currentApprovals / requiredApprovals) * 100}%` }}
            />
          </div>
          <div className="flex items-center gap-2 mt-1.5 text-xs text-gray-400">
            {approvedByRoles.map(role => (
              <span key={role} className="text-green-600">{role}</span>
            ))}
            {remainingRoles.map(role => (
              <span key={role}>{role}</span>
            ))}
          </div>
        </div>
      )}
    </div>
  )
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

const JobApprovalCard = ({ run, onApprove, onReject }) => {
  const [rejectReason, setRejectReason] = useState('')
  const [showReject, setShowReject] = useState(false)

  const requiredRole = run.required_role || 'admin'
  const canApprove = hasRole('admin') || hasRole(requiredRole)

  return (
    <div className={`bg-white rounded-xl border p-4 border-amber-100`}>
      <div className="flex items-start justify-between gap-4">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <Calendar className="w-4 h-4 text-purple-600 flex-shrink-0" />
            <h3 className="font-medium text-gray-900">Scheduled Job Approval</h3>
            <span className="text-xs text-gray-400">{run.trigger_type}</span>
          </div>
          <p className="text-gray-400 text-sm mt-0.5">
            Requires <span className="font-semibold text-gray-700">{requiredRole}</span> role to execute
          </p>
          {run.error_message && (
            <p className="text-red-500 text-sm mt-1">{run.error_message}</p>
          )}
          <div className="flex items-center gap-4 text-xs text-gray-400 flex-wrap mt-1">
            <span>{new Date(run.created_at).toLocaleString()}</span>
            {run.session_id && (
              <Link to={`/chat?session=${run.session_id}`} className="text-blue-500 hover:text-blue-700 hover:underline flex items-center gap-1">
                <MessageSquare className="w-3 h-3" />
                Conversation
              </Link>
            )}
          </div>
        </div>

        {canApprove ? (
          <div className="flex items-center gap-2 flex-shrink-0">
            {!showReject ? (
              <>
                <button
                  onClick={() => onApprove(run.id)}
                  className="px-3 py-1.5 text-sm text-white rounded-lg flex items-center focus:outline-none focus:ring-2 focus:ring-offset-2 bg-green-600 hover:bg-green-700 focus:ring-green-500"
                  aria-label="Approve job run"
                >
                  <CheckCircle className="w-4 h-4 mr-1.5" aria-hidden="true" />
                  Approve
                </button>
                <button
                  onClick={() => setShowReject(true)}
                  className="px-3 py-1.5 text-sm text-gray-500 hover:text-red-600 hover:bg-red-50 rounded-lg transition-colors focus:outline-none"
                  aria-label="Reject job run"
                >
                  Reject
                </button>
              </>
            ) : null}
          </div>
        ) : (
          <span className="flex items-center gap-1.5 text-xs text-gray-400 flex-shrink-0">
            <Clock className="w-3.5 h-3.5 animate-pulse" />
            Needs {requiredRole}
          </span>
        )}
      </div>

      {canApprove && showReject && (
        <div className="mt-3 space-y-2">
          <textarea
            value={rejectReason}
            onChange={(e) => setRejectReason(e.target.value)}
            placeholder="Reason for rejection..."
            className="w-full px-3 py-2 border border-gray-200 rounded-lg focus:ring-2 focus:ring-red-500 focus:border-transparent text-sm resize-y"
            rows={3}
            maxLength={10000}
            autoFocus
          />
          <div className="flex items-center justify-between">
            <span className="text-xs text-gray-400">{rejectReason.length} / 10,000</span>
            <div className="flex items-center gap-2">
              <button
                onClick={() => setShowReject(false)}
                className="px-3 py-1.5 text-sm text-gray-500 hover:text-gray-700 rounded-lg"
              >
                Cancel
              </button>
              <button
                onClick={() => {
                  if (rejectReason.trim()) {
                    onReject(run.id, rejectReason)
                  }
                }}
                disabled={!rejectReason.trim()}
                className="px-3 py-1.5 text-sm bg-red-600 text-white rounded-lg hover:bg-red-700 disabled:opacity-50"
              >
                Confirm Reject
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

const Tasks = () => {
  const { user } = useAuth()
  const queryClient = useQueryClient()
  const toast = useToast()
  const [showHistory, setShowHistory] = useState(false)
  const [showJobRuns, setShowJobRuns] = useState(false)
  const [showJobs, setShowJobs] = useState(true)
  const [triggeringJobId, setTriggeringJobId] = useState(null)
  const isAdmin = hasRole('admin')

  const { data: tasksResponse, isLoading, isError, error, refetch: refetchTasks } = useQuery({
    queryKey: ['tasks'],
    queryFn: getTasks,
    refetchInterval: 5000,
  })

  const { data: jobRunsResponse, isLoading: jobRunsLoading } = useQuery({
    queryKey: ['jobRuns'],
    queryFn: () => getJobRuns(null, null, 1, 20),
    enabled: showJobRuns && isAdmin,
    refetchInterval: activeRunPolling,
  })

   // Fetch approval history (completed approvals)
  const { data: historyResponse, isLoading: historyLoading } = useQuery({
    queryKey: ['approvalHistory'],
    queryFn: () => getApprovalHistory(1, 20),
    enabled: showHistory, // Only fetch when history section is expanded
  })

  const { data: jobsResponse, isLoading: jobsLoading, isError: jobsError, error: jobsErrorObj } = useQuery({
    queryKey: ['jobs'],
    queryFn: getJobs,
    enabled: showJobs && isAdmin,
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

  // Fetch pending job-level approvals
  const { data: pendingJobApprovalsResponse, isLoading: pendingJobApprovalsLoading } = useQuery({
    queryKey: ['pendingJobApprovals'],
    queryFn: getPendingJobApprovals,
    refetchInterval: 5000,
  })

  const approveJobMutation = useMutation({
    mutationFn: (jobRunId) => approveJob(jobRunId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['pendingJobApprovals'] })
      queryClient.invalidateQueries({ queryKey: ['jobRuns'] })
      toast.success('Job Approved', 'The scheduled job has been approved and will execute.')
    },
    onError: (err) => {
      toast.error('Approval Failed', err.message || 'Failed to approve the job. Please try again.')
    },
  })

  const rejectJobMutation = useMutation({
    mutationFn: ({ jobRunId, reason }) => rejectJob(jobRunId, reason),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['pendingJobApprovals'] })
      queryClient.invalidateQueries({ queryKey: ['jobRuns'] })
      toast.success('Job Rejected', 'The scheduled job has been rejected.')
    },
    onError: (err) => {
      toast.error('Rejection Failed', err.message || 'Failed to reject the job. Please try again.')
    },
  })

  const handleApproveJob = (jobRunId) => {
    approveJobMutation.mutate(jobRunId)
  }

  const handleRejectJob = (jobRunId, reason) => {
    rejectJobMutation.mutate({ jobRunId, reason })
  }

  // Extract tasks array from paginated response
  const tasks = tasksResponse?.items || []

  const invalidateApprovalCaches = () => {
    queryClient.invalidateQueries({ queryKey: ['tasks'] })
    queryClient.invalidateQueries({ queryKey: ['plans'] })
    queryClient.invalidateQueries({ queryKey: ['approvalHistory'] })
    queryClient.invalidateQueries({ queryKey: ['pending-approvals-count'] })
    queryClient.invalidateQueries({ queryKey: ['pendingJobApprovals'] })
    queryClient.invalidateQueries({ queryKey: ['jobRuns'] })
    queryClient.invalidateQueries({ queryKey: ['jobs'] })
  }

  const approveMutation = useMutation({
    mutationFn: ({ taskId, comment }) => approveTask(taskId, comment),
    onSuccess: () => {
      invalidateApprovalCaches()
      toast.success('Approval Granted', 'The task has been approved successfully.')
    },
    onError: (err) => {
      toast.error('Approval Failed', err.message || 'Failed to approve the task. Please try again.')
    },
  })

  const rejectMutation = useMutation({
    mutationFn: ({ taskId, reason }) => rejectTask(taskId, reason),
    onSuccess: () => {
      invalidateApprovalCaches()
      toast.success('Task Rejected', 'The task has been rejected.')
    },
    onError: (err) => {
      toast.error('Rejection Failed', err.message || 'Failed to reject the task. Please try again.')
    },
  })

  const handleApprove = (taskId) => {
    approveMutation.mutate({ taskId, comment: '' })
  }

  const handleReject = (taskId, reason) => {
    rejectMutation.mutate({ taskId, reason })
  }

  // Group tasks by required role (use first role from required_roles array)
  const tasksByRole = tasks.reduce((acc, task) => {
    const roles = task.required_roles || (task.required_role ? [task.required_role] : ['admin'])
    const role = roles[0] || 'other'
    if (!acc[role]) acc[role] = []
    acc[role].push(task)
    return acc
  }, {})

  const jobs = jobsResponse?.items || []

  return (
    <div className="space-y-6">
      {isAdmin && (
        <>
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
      <div className="border-t border-gray-200 pt-6" />
    </>
  )}

      {isAdmin && (
        <>
          <PageHeader title="Pending Job Approvals" subtitle="Scheduled jobs awaiting approval before execution.">
            <div className="flex items-center gap-2">
              <span className="text-sm text-gray-500">Your roles:</span>
              {user?.roles?.slice(0, 3).map((role) => (
                <span
                  key={role}
                  className="px-2 py-1 bg-blue-100 text-blue-700 text-xs rounded-full"
                >
                  {role}
                </span>
              ))}
            </div>
          </PageHeader>

          {pendingJobApprovalsLoading ? (
            <div className="space-y-4">
              {Array.from({ length: 2 }).map((_, i) => (
                <div key={i} className="bg-white rounded-xl border border-gray-100 p-4 animate-pulse">
                  <div className="w-32 h-4 bg-gray-200 rounded mb-2" />
                  <div className="w-3/4 h-3 bg-gray-100 rounded" />
                </div>
              ))}
            </div>
          ) : (pendingJobApprovalsResponse?.items || []).length === 0 ? (
            <EmptyState
              icon={CheckCircle}
              title="No pending job approvals"
              description="No scheduled jobs waiting for approval right now."
            />
          ) : (
            <div className="space-y-4">
              {(pendingJobApprovalsResponse?.items || []).map((run) => (
                <JobApprovalCard
                  key={run.id}
                  run={run}
                  onApprove={handleApproveJob}
                  onReject={handleRejectJob}
                />
              ))}
            </div>
          )}

          <div className="border-t border-gray-200 pt-6" />
        </>
      )}

      <PageHeader title="Pending Tool Approvals" subtitle="Review and approve MCP tool executions based on your role permissions.">
        <div className="flex items-center gap-2">
          <span className="text-sm text-gray-500">Your roles:</span>
          {user?.roles?.slice(0, 3).map((role) => (
            <span
              key={role}
              className="px-2 py-1 bg-blue-100 text-blue-700 text-xs rounded-full"
            >
              {role}
            </span>
          ))}
        </div>
      </PageHeader>

      {/* Approval Tasks Section */}
      {isLoading ? (
        <div className="space-y-4">
          {Array.from({ length: 3 }).map((_, i) => <SkeletonTaskCard key={i} />)}
        </div>
      ) : isError ? (
        <div className="flex flex-col items-center justify-center h-64 text-red-500">
          <AlertCircle className="w-12 h-12 mb-2" />
          <p className="text-lg font-medium">Failed to load tasks</p>
          <p className="text-sm text-red-400">{error?.message || 'An unexpected error occurred'}</p>
          <button
            onClick={() => refetchTasks()}
            className="mt-4 px-4 py-2 bg-blue-500 text-white rounded-lg hover:bg-blue-600 transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2"
            aria-label="Retry loading tasks"
          >
            Retry
          </button>
        </div>
      ) : tasks.length === 0 ? (
        <EmptyState
          icon={CheckCircle}
          title="All clear"
          description="No pending approvals right now."
        />
      ) : (
        <div className="space-y-8">
          {Object.entries(tasksByRole).map(([role, roleTasks]) => (
            <div key={role}>
              <h2 className="text-lg font-semibold mb-4 flex items-center">
                <Shield
                  className={`w-5 h-5 mr-2 ${
                    hasRole(role) ? 'text-green-500' : 'text-gray-400'
                  }`}
                />
                {role}
                <span className="ml-2 px-2 py-0.5 bg-gray-100 text-gray-600 text-sm rounded-full">
                  {roleTasks.length}
                </span>
                {hasRole(role) && (
                  <span className="ml-2 text-sm text-green-600">(You can approve)</span>
                )}
              </h2>
              <div className="grid gap-4">
                {roleTasks.map((task) => (
                  <TaskCard
                    key={task.id}
                    task={task}
                    onApprove={handleApprove}
                    onReject={handleReject}
                  />
                ))}
              </div>
            </div>
          ))}
        </div>
      )}

      {isAdmin && (
        <>
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
      </>
    )}

      {/* Approval History Section */}
      <div className="mt-8 border-t pt-6">
        <button
          onClick={() => setShowHistory(!showHistory)}
          className="flex items-center gap-2 text-lg font-semibold text-gray-700 hover:text-gray-900 transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500 rounded"
          aria-expanded={showHistory}
          aria-controls="approval-history"
        >
          {showHistory ? (
            <ChevronDown className="w-5 h-5" />
          ) : (
            <ChevronRight className="w-5 h-5" />
          )}
          <History className="w-5 h-5 text-blue-500" />
          Approval History
        </button>

        {showHistory && (
          <div id="approval-history" className="mt-4">
            {historyLoading ? (
              <div className="flex items-center justify-center h-32 bg-white rounded-xl border border-gray-100">
                <Loader2 className="w-6 h-6 animate-spin text-blue-500" />
                <span className="ml-2 text-gray-600">Loading history...</span>
              </div>
            ) : historyResponse?.items?.length > 0 ? (
              <div className="space-y-3">
                {historyResponse.items.map((approval) => (
                  <div
                    key={approval.id}
                    className="bg-white rounded-lg border border-gray-100 p-4 hover:border-gray-200 transition-colors"
                  >
                    <div className="flex items-start justify-between">
                      <div className="flex-1">
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className="font-medium">{approval.title || approval.tool_name || 'Unknown tool'}</span>
                          <span className={`px-2 py-0.5 ${
                            approval.status === 'approved'
                              ? 'bg-green-100 text-green-700'
                              : approval.status === 'rejected'
                              ? 'bg-red-100 text-red-700'
                              : 'bg-gray-100 text-gray-700'
                          } text-xs rounded-full flex items-center`}>
                            {approval.status === 'approved' ? (
                              <><CheckCircle className="w-3 h-3 mr-1" />Approved</>
                            ) : approval.status === 'rejected' ? (
                              <><XCircle className="w-3 h-3 mr-1" />Rejected</>
                            ) : (
                              <>{approval.status}</>
                            )}
                          </span>
                          {approval.agent_id && (
                            <span className="px-2 py-0.5 bg-purple-100 text-purple-600 text-xs rounded-full flex items-center">
                              <Bot className="w-3 h-3 mr-1" />
                              {formatAgentName(approval.agent_id)}
                            </span>
                          )}
                        </div>
                        {approval.description && (
                          <p className="text-gray-500 text-sm mt-1 line-clamp-2">{approval.description}</p>
                        )}
                        {approval.status === 'rejected' && approval.rejection_reason && (
                          <p className="text-red-500 text-sm mt-1 line-clamp-2">Reason: {approval.rejection_reason}</p>
                        )}
                        <div className="flex items-center gap-4 mt-2 text-xs text-gray-500 flex-wrap">
                          {approval.resolved_by && (
                            <span className="flex items-center gap-1">
                              <User className="w-3 h-3" />
                              {approval.status === 'approved' ? 'Approved' : 'Rejected'} by: {
                                String(approval.resolved_by).substring(0, 8) + '...'
                              }
                            </span>
                          )}
                          {approval.resolved_at && (
                            <span className="flex items-center gap-1">
                              <Clock className="w-3 h-3" />
                              {new Date(approval.resolved_at).toLocaleString()}
                            </span>
                          )}
                          {!approval.resolved_at && approval.created_at && (
                            <span className="flex items-center gap-1">
                              <Clock className="w-3 h-3" />
                              {new Date(approval.created_at).toLocaleString()}
                            </span>
                          )}
                        </div>
                        {/* Session links for context */}
                        {approval.session_id && (
                          <div className="flex items-center gap-3 mt-2">
                            <Link
                              to={`/chat?session=${approval.session_id}`}
                              className="inline-flex items-center gap-1 text-xs text-blue-600 hover:text-blue-800 hover:underline"
                            >
                              <MessageSquare className="w-3 h-3" />
                              View Conversation
                            </Link>
                            <Link
                              to={`/chat?session=${approval.session_id}&mode=inspect`}
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
                icon={History}
                title="No approval history"
                description="No approval history found."
              />
            )}
          </div>
        )}
      </div>
    </div>
  )
}

export default Tasks
