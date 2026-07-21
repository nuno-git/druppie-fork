/**
 * Session Detail - right panel when a session is selected in Chat
 */

import { useState, useRef, useEffect, useContext } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Send, CheckCircle, XCircle, Shield, ShieldOff, Loader2, ExternalLink, MessageSquare, FileCode, FilePlus, FileText, FileType, StopCircle, PlayCircle, ArrowUp, AlertTriangle, Terminal, ChevronDown, ChevronRight, Calendar, Ban } from 'lucide-react'
import { Link } from 'react-router-dom'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { getSession, sendChat, cancelChat, resumeSession, getResumableRuns, approveApproval, rejectApproval, answerQuestion, getToolCallLiveOutput, getSandboxEvents, getAttachmentUrl } from '../../services/api'
import { getUserInfo } from '../../services/keycloak'
import { useAuth } from '../../App'
import { getAgentConfig, getAgentMessageColors, formatToolName } from '../../utils/agentConfig'
import { FilePreviewModal } from './ApprovalCard'
import DownloadMenu from './DownloadMenu'
import { downloadAsMarkdown, downloadContentAsPdf, buildChatTranscript } from '../../utils/downloadDesign'
import HITLQuestionMessage from './HITLQuestionMessage'
import FallbackModal from './FallbackModal'
import WorkflowPipeline from './WorkflowPipeline'
import DebugEventLog from './DebugEventLog'
import ContinueDialog from './ContinueDialog'
import AnnotationBar from './AnnotationBar'
import { consumePending } from '../../services/pendingChat'
import {
  chatMarkdownComponents,
  CopyJsonButton,
  buildVisibleJson,
  extractSurfacedApprovals,
  extractOrderedItems,
  extractSurfacedFileWrites,
  buildApprovalFileList,
  findFallbackQuestion,
  extractDependencyInstalls,
  findPendingQuestion,
  ProjectRepoContext,
} from './ChatHelpers'
import FileUploadButton from './FileUploadButton'
import AttachmentChips from './AttachmentChips'
import SurfacedFileCard from './SurfacedFileCard'
import TestResultCard from './TestResultCard'
import BAHitlCard from './BAHitlCard'
import ArchitectHitlCard from './ArchitectHitlCard'
import EscalationHistoryList from './EscalationHistoryList'

// Fast-poll window after user actions (answer/approve/continue) so the
// loading indicator appears promptly instead of waiting for the 2s paused poll.
let _resumingUntil = 0
const markResuming = () => { _resumingUntil = Date.now() + 10000 }
const isResuming = () => Date.now() < _resumingUntil

// --- Tool label helper ---

const getToolLabel = (toolName) => {
  if (!toolName) return 'Unknown Tool'
  const labels = {
    'write_file': 'Write File',
    'coding:write_file': 'Write File',
    'batch_write_files': 'Write Files',
    'coding:batch_write_files': 'Write Files',
    'run_command': 'Run Command',
    'coding:run_command': 'Run Command',
    'commit_and_push': 'Git Commit & Push',
    'coding:commit_and_push': 'Git Commit & Push',
  }
  return labels[toolName] || toolName?.split(':').pop() || 'Tool Action'
}

// --- Inline Approval (minimal chat card) ---

const InlineApproval = ({ tc, sessionId, sessionUserId }) => {
  const queryClient = useQueryClient()
  const user = getUserInfo()
  const repo = useContext(ProjectRepoContext)
  const [rejectMode, setRejectMode] = useState(false)
  const [rejectReason, setRejectReason] = useState('')
  const [rejectAttachments, setRejectAttachments] = useState([])
  const [showFilePreview, setShowFilePreview] = useState(false)
  const [pdfDownloading, setPdfDownloading] = useState(false)

  const invalidate = () => {
    markResuming()
    queryClient.invalidateQueries({ queryKey: ['session', sessionId] })
    queryClient.invalidateQueries({ queryKey: ['tasks'] })
    queryClient.invalidateQueries({ queryKey: ['approvalHistory'] })
    queryClient.invalidateQueries({ queryKey: ['pending-approvals-count'] })
  }

  const approveMut = useMutation({
    mutationFn: (approvalId) => approveApproval(approvalId, ''),
    onSuccess: invalidate,
  })

  const rejectMut = useMutation({
    mutationFn: ({ approvalId, reason, attachmentIds }) => rejectApproval(approvalId, reason || '', attachmentIds || []),
    onSuccess: () => {
      invalidate()
      setRejectMode(false)
      setRejectReason('')
      setRejectAttachments([])
    },
  })

  const isPending = tc.approval.status === 'pending'
  const isApproved = tc.approval.status === 'approved'
  const isRejected = tc.approval.status === 'rejected'
  const isProcessing = approveMut.isPending || rejectMut.isPending

  const toolLabel = formatToolName(tc.tool_name)
  const args = tc.arguments || {}
  const contextLine = args.path || args.file_path || args.command || args.message || args.commit_message || null

  const userRoles = user?.roles || []
  const requiredRoles = tc.approval.required_role ? [tc.approval.required_role] : ['admin']
  const isSessionOwnerApproval = requiredRoles.includes('session_owner')
  const userCanApprove = isSessionOwnerApproval
    ? (user?.id === sessionUserId || userRoles.includes('admin'))
    : (userRoles.includes('admin') || requiredRoles.some((r) => userRoles.includes(r)))

  return (
    <div className="group">
      <div className="flex items-center gap-2 mb-1.5">
        <div className="w-6 h-6 rounded-full flex items-center justify-center flex-shrink-0 bg-amber-50 border border-amber-200">
          <Shield className="w-3.5 h-3.5 text-amber-600" />
        </div>
        <span className="text-sm font-medium text-amber-700">System</span>
        {tc.approval.resolved_at && (
          <span className="text-xs text-gray-300">
            {new Date(tc.approval.resolved_at).toLocaleTimeString()}
          </span>
        )}
      </div>
      <div className="pl-8">
        <div className={`rounded-lg border p-3 ${
          isApproved ? 'bg-green-50 border-green-200'
            : isRejected ? 'bg-red-50 border-red-200'
            : 'bg-amber-50 border-amber-200'
        }`}>
          <div className="flex items-center gap-2">
            <span className={`text-xs font-semibold uppercase tracking-wider ${
              isApproved ? 'text-green-700'
                : isRejected ? 'text-red-700'
                : 'text-amber-700'
            }`}>
              {isApproved ? 'Approved' : isRejected ? 'Rejected' : 'Approval Required'}
            </span>
          </div>
          <div className="mt-1 text-sm font-medium text-gray-900">{toolLabel}</div>
          {contextLine && (
            <div className="mt-0.5 text-xs text-gray-500 font-mono truncate" title={contextLine}>
              {contextLine}
            </div>
          )}

          {isRejected && tc.approval.rejection_reason && (
            <div className="mt-1.5 text-xs text-red-700 whitespace-pre-wrap">{tc.approval.rejection_reason}</div>
          )}
          {isRejected && tc.approval.attachments?.length > 0 && (
            <div className="mt-1.5 flex flex-wrap gap-1.5">
              {tc.approval.attachments.map((att) => {
                const Icon = att.content_type === 'application/pdf' ? FileType : FileText
                return (
                  <button
                    key={att.id}
                    type="button"
                    onClick={() => {
                      if (window.confirm(`Download "${att.original_filename}"?`)) {
                        window.open(getAttachmentUrl(att.id), '_blank')
                      }
                    }}
                    className="inline-flex items-center gap-1.5 px-2.5 py-1 bg-white/60 rounded-lg text-xs text-gray-600 hover:bg-white transition-colors cursor-pointer"
                  >
                    <Icon className="w-3.5 h-3.5 text-gray-400" />
                    <span className="truncate max-w-[120px]">{att.original_filename}</span>
                  </button>
                )
              })}
            </div>
          )}

          {/* File preview for write operations */}
          {(() => {
            const files = buildApprovalFileList(args)
            if (!files) return null
            const displayPath = args.translated_path || args.path || args.file_path || 'file'
            return (
              <div className="mt-1.5">
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => setShowFilePreview(true)}
                    className="flex items-center gap-1.5 text-xs text-blue-600 hover:text-blue-800 transition-colors"
                  >
                    {files.length > 1 && !args.translated_content ? <FileCode className="w-3.5 h-3.5" /> : <FilePlus className="w-3.5 h-3.5" />}
                    View {files.length > 1 && !args.translated_content ? `${files.length} files` : displayPath}
                  </button>
                  {files.length === 1 && args.content && (
                    <DownloadMenu
                      variant="light"
                      loading={pdfDownloading}
                      onDownloadMd={() => downloadAsMarkdown(args.content, displayPath)}
                      onDownloadPdf={async () => {
                        setPdfDownloading(true)
                        try { await downloadContentAsPdf(args.content, displayPath, repo) }
                        finally { setPdfDownloading(false) }
                      }}
                    />
                  )}
                </div>
                {showFilePreview && (
                  <FilePreviewModal files={files} onClose={() => setShowFilePreview(false)} />
                )}
              </div>
            )
          })()}

          {isPending && (
            <div className="mt-2">
              {userCanApprove ? (
                !rejectMode ? (
                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => approveMut.mutate(tc.approval.id)}
                      disabled={isProcessing}
                      className="inline-flex items-center gap-1 px-2.5 py-1 text-xs font-medium bg-green-600 text-white rounded-md hover:bg-green-700 disabled:opacity-50 transition-colors"
                    >
                      {isProcessing ? <Loader2 className="w-3 h-3 animate-spin" /> : <CheckCircle className="w-3 h-3" />}
                      Approve
                    </button>
                    <button
                      onClick={() => setRejectMode(true)}
                      disabled={isProcessing}
                      className="px-2.5 py-1 text-xs text-gray-500 hover:text-red-600 hover:bg-red-50 rounded-md transition-colors"
                    >
                      Reject
                    </button>
                  </div>
                ) : (
                  <div className="space-y-1.5">
                    <AttachmentChips
                      attachments={rejectAttachments}
                      onRemove={(id) => setRejectAttachments((prev) => prev.filter((a) => a.id !== id))}
                    />
                    <textarea
                      value={rejectReason}
                      onChange={(e) => setRejectReason(e.target.value)}
                      placeholder="Reason for rejection..."
                      aria-label="Rejection reason"
                      className="w-full px-2 py-1 text-xs border border-gray-200 rounded-md focus:outline-none focus:ring-1 focus:ring-red-400 resize-y"
                      rows={3}
                      maxLength={10000}
                      autoFocus
                      onKeyDown={(e) => {
                        if (e.key === 'Escape') {
                          setRejectMode(false)
                          setRejectReason('')
                          setRejectAttachments([])
                        }
                        if (e.key === 'Enter' && (e.metaKey || e.ctrlKey) && rejectReason.trim() && !isProcessing) {
                          e.preventDefault()
                          rejectMut.mutate({ approvalId: tc.approval.id, reason: rejectReason, attachmentIds: rejectAttachments.map((a) => a.id) })
                        }
                      }}
                    />
                    <div className="flex items-center justify-between">
                      <span className="text-xs text-gray-400">{rejectReason.length} / 10,000</span>
                      <div className="flex items-center gap-1.5">
                        <FileUploadButton
                          onUpload={(att) => setRejectAttachments((prev) => [...prev, att])}
                          onError={() => {}}
                          sessionId={sessionId}
                          scope={`reject-${tc.approval.id}`}
                          disabled={isProcessing}
                        />
                        <button
                          onClick={() => rejectMut.mutate({ approvalId: tc.approval.id, reason: rejectReason, attachmentIds: rejectAttachments.map((a) => a.id) })}
                          disabled={isProcessing || !rejectReason.trim()}
                          className="px-2 py-1 text-xs bg-red-600 text-white rounded-md hover:bg-red-700 disabled:opacity-50 transition-colors"
                        >
                          Reject
                        </button>
                        <button
                          onClick={() => { setRejectMode(false); setRejectReason(''); setRejectAttachments([]) }}
                          className="px-2 py-1 text-xs text-gray-400 hover:text-gray-600 transition-colors"
                        >
                          Cancel
                        </button>
                      </div>
                    </div>
                  </div>
                )
              ) : (
                <span className="text-xs text-amber-600">
                  {isSessionOwnerApproval
                    ? 'Waiting for your approval'
                    : `Waiting for ${requiredRoles.join(' or ')} approval`}
                </span>
              )}
            </div>
          )}

          <Link
            to="/tasks"
            className="mt-2 inline-flex items-center gap-1 text-xs text-blue-600 hover:text-blue-800 transition-colors"
          >
            View full details <ExternalLink className="w-3 h-3" />
          </Link>
        </div>
      </div>
    </div>
  )
}

// --- Timeline HITL Question ---

const TimelineQuestion = ({ tc, agentId, sessionId, isOwner, isAdmin, userRoles, attachments = [], onAttachmentsConsumed, onAnswerSubmitted }) => {
  const queryClient = useQueryClient()

  const answerMut = useMutation({
    mutationFn: ({ questionId, answer, selectedChoices = null, attachmentIds = [] }) =>
      answerQuestion(questionId, answer, selectedChoices, attachmentIds),
    onSuccess: () => {
      onAttachmentsConsumed?.()
      markResuming()
      onAnswerSubmitted?.()
      queryClient.invalidateQueries({ queryKey: ['session', sessionId] })
    },
  })

  const isAnswered = tc.status === 'completed'
  const isExpertTool = tc.tool_name === 'ask_expert_question' || tc.tool_name === 'ask_expert_multiple_choice_question'
  const expertRole = isExpertTool ? tc.arguments?.expert_role : null

  // Who is allowed to answer this question right here in the session view:
  // - regular HITL: session owner or admin
  // - ask_expert: any user with the expert_role, or admin
  // The session owner does NOT get to answer expert questions (unless they
  // hold the role themselves) — they have to wait for the expert.
  const canAnswer = isAdmin
    || (isExpertTool
      ? !!expertRole && Array.isArray(userRoles) && userRoles.includes(expertRole)
      : !!isOwner)

  const rawChoices = tc.arguments?.choices || tc.arguments?.options || []
  const choices = rawChoices
    .map(c => (typeof c === 'string' ? c : c.text || c.label || String(c)))
    .filter(c => !/^other\b/i.test(c.trim()))

  let displayAnswer = null
  if (isAnswered && tc.result) {
    try {
      const parsed = typeof tc.result === 'string' ? JSON.parse(tc.result) : tc.result
      displayAnswer = parsed.user_answer || parsed.display_answer || parsed.answer_english || parsed.answer || parsed.text || (typeof parsed === 'string' ? parsed : tc.result)
    } catch {
      displayAnswer = tc.result
    }
    if (typeof displayAnswer === 'object') {
      displayAnswer = JSON.stringify(displayAnswer)
    }
  }

  const allowOther = tc.tool_name === 'hitl_ask_multiple_choice_question'
    || tc.tool_name === 'ask_expert_multiple_choice_question'

  // If the LLM put the question text in context instead of question, promote it
  const hasQuestion = !!tc.arguments?.question
  const questionData = {
    id: tc.question_id,
    agent_id: agentId,
    question: tc.arguments?.question || tc.arguments?.context || 'Agent is asking a question',
    choices,
    context: hasQuestion ? tc.arguments?.context : undefined,
    allowOther,
  }

  // For non-answerers we render a stripped-down read-only view. We can't
  // just pass `answered={true}` to HITLQuestionMessage because the
  // question is in fact still pending — we just want the UI to not
  // expose answer controls.
  const showAsReadOnly = !canAnswer && !isAnswered

  return (
    <>
      {isExpertTool && !isAnswered && (
        <div className="ml-8 mb-1 inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-purple-50 border border-purple-200 text-[11px] font-medium text-purple-700">
          Expert question · {expertRole || 'unknown role'}
        </div>
      )}
      <HITLQuestionMessage
        question={questionData}
        onSubmitAnswer={({ indices, answerText }) => answerMut.mutate({ questionId: tc.question_id, answer: answerText, selectedChoices: indices, attachmentIds: attachments.map((a) => a.id) })}
        isAnswering={answerMut.isPending}
        answered={isAnswered || showAsReadOnly}
      />
      {showAsReadOnly && (
        <div className="ml-8 mt-1 text-xs text-gray-500 italic">
          {isExpertTool
            ? `Waiting for a user with the "${expertRole}" role to answer.`
            : 'Only the session owner can answer this question.'}
        </div>
      )}
      {isAnswered && displayAnswer && (
        <div className="flex justify-end">
          <div className="max-w-[85%] rounded-2xl px-4 py-2.5 text-sm bg-gray-100 text-gray-900">
            {!(tc.attachments?.length > 0 && (displayAnswer.startsWith('See uploaded files:') || displayAnswer.startsWith('Zie geüploade bestanden:'))) && (
              <div className="whitespace-pre-wrap">{displayAnswer}</div>
            )}
            {tc.attachments?.length > 0 && (
              <div className={`flex flex-wrap gap-1.5${displayAnswer && !displayAnswer.startsWith('See uploaded files:') && !displayAnswer.startsWith('Zie geüploade bestanden:') ? ' mt-2' : ''}`}>
                {tc.attachments.map((att) => {
                  const Icon = att.content_type === 'application/pdf' ? FileType : FileText
                  return (
                    <button
                      key={att.id}
                      type="button"
                      onClick={() => {
                        if (window.confirm(`Download "${att.original_filename}"?`)) {
                          window.open(getAttachmentUrl(att.id), '_blank')
                        }
                      }}
                      className="inline-flex items-center gap-1.5 px-2.5 py-1 bg-white/60 rounded-lg text-xs text-gray-600 hover:bg-white transition-colors cursor-pointer"
                    >
                      <Icon className="w-3.5 h-3.5 text-gray-400" />
                      <span className="truncate max-w-[120px]">{att.original_filename}</span>
                    </button>
                  )
                })}
              </div>
            )}
          </div>
        </div>
      )}
    </>
  )
}

// --- Subagent Run Card ---

const STATUS_COLORS = {
  completed: { bg: 'bg-emerald-50', text: 'text-emerald-700', border: 'border-emerald-200' },
  failed: { bg: 'bg-red-50', text: 'text-red-700', border: 'border-red-200' },
  running: { bg: 'bg-blue-50', text: 'text-blue-700', border: 'border-blue-200' },
  pending: { bg: 'bg-gray-50', text: 'text-gray-500', border: 'border-gray-200' },
  paused_hitl: { bg: 'bg-amber-50', text: 'text-amber-700', border: 'border-amber-200' },
  paused_tool: { bg: 'bg-amber-50', text: 'text-amber-700', border: 'border-amber-200' },
  paused_sandbox: { bg: 'bg-amber-50', text: 'text-amber-700', border: 'border-amber-200' },
  paused_crashed: { bg: 'bg-red-50', text: 'text-red-700', border: 'border-red-200' },
  paused_ba_hitl: { bg: 'bg-amber-50', text: 'text-amber-700', border: 'border-amber-200' },
  paused_architect_hitl: { bg: 'bg-indigo-50', text: 'text-indigo-700', border: 'border-indigo-200' },
  terminated: { bg: 'bg-gray-100', text: 'text-gray-600', border: 'border-gray-300' },
}

const StatusBadge = ({ status }) => {
  const colors = STATUS_COLORS[status] || STATUS_COLORS.pending
  const label = status?.replace(/_/g, ' ') || 'unknown'
  return (
    <span className={`inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium uppercase tracking-wider ${colors.bg} ${colors.text} ${colors.border} border`}>
      {label}
    </span>
  )
}

// --- Bash Live Output ---

const BashLiveOutput = ({ tc }) => {
  const { data } = useQuery({
    queryKey: ['bash-live-output', tc.id],
    queryFn: () => getToolCallLiveOutput(tc.id),
    refetchInterval: (query) => {
      if (!query.state.data || query.state.data.status !== 'executing') return false
      return 2000
    },
    enabled: tc.status === 'executing',
    retry: false,
  })

  if (!data?.output) return null

  return (
    <div className="ml-4.5 mt-0.5 p-2 rounded bg-gray-900 border border-gray-700 text-xs text-green-400 whitespace-pre-wrap break-all max-h-40 overflow-auto font-mono">
      {data.output.length > 5000 ? data.output.slice(-5000) : data.output}
    </div>
  )
}

const SubagentToolCall = ({ tc, sessionId, sessionUserId }) => {
  const [expanded, setExpanded] = useState(false)
  const queryClient = useQueryClient()
  const [rejectMode, setRejectMode] = useState(false)
  const [rejectReason, setRejectReason] = useState('')

  const hasResult = tc.result && tc.status === 'completed'
  const parsedResult = (() => {
    if (!hasResult) return null
    try {
      return typeof tc.result === 'string' ? JSON.parse(tc.result) : tc.result
    } catch {
      return tc.result
    }
  })()
  const resultStr = parsedResult && typeof parsedResult === 'string'
    ? parsedResult
    : parsedResult ? JSON.stringify(parsedResult, null, 2) : null

  const tcStatusColors = tc.status === 'completed'
    ? 'text-emerald-600'
    : tc.status === 'failed'
      ? 'text-red-600'
      : 'text-gray-400'

  const hasApproval = !!tc.approval
  const isPending = hasApproval && tc.approval.status === 'pending'
  const isApproved = hasApproval && tc.approval.status === 'approved'
  const isRejected = hasApproval && tc.approval.status === 'rejected'

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['session', sessionId] })
    queryClient.invalidateQueries({ queryKey: ['tasks'] })
    queryClient.invalidateQueries({ queryKey: ['approvalHistory'] })
    queryClient.invalidateQueries({ queryKey: ['pending-approvals-count'] })
  }

  const approveMut = useMutation({
    mutationFn: (approvalId) => approveApproval(approvalId, ''),
    onSuccess: invalidate,
  })

  const rejectMut = useMutation({
    mutationFn: ({ approvalId, reason }) => rejectApproval(approvalId, reason || ''),
    onSuccess: () => {
      invalidate()
      setRejectMode(false)
      setRejectReason('')
    },
  })

  const isProcessing = approveMut.isPending || rejectMut.isPending

  const user = getUserInfo()
  const userRoles = user?.roles || []
  const requiredRoles = tc.approval?.required_role ? [tc.approval.required_role] : ['admin']
  const isSessionOwnerApproval = requiredRoles.includes('session_owner')
  const userCanApprove = isSessionOwnerApproval
    ? (user?.id === sessionUserId || userRoles.includes('admin'))
    : (userRoles.includes('admin') || requiredRoles.some((r) => userRoles.includes(r)))

  return (
    <div className="flex flex-col">
      <div className="flex items-center gap-1.5">
        <button
          onClick={() => hasResult && setExpanded(!expanded)}
          className={`flex items-center gap-1.5 text-xs py-0.5 ${hasResult ? 'cursor-pointer hover:text-gray-900' : 'cursor-default'}`}
        >
          {hasResult ? (
            expanded ? <ChevronDown className="w-3 h-3 flex-shrink-0" /> : <ChevronRight className="w-3 h-3 flex-shrink-0" />
          ) : (
            <span className="w-3" />
          )}
          <span className={`font-mono ${tcStatusColors}`}>{getToolLabel(tc.tool_name)}</span>
          {!hasResult && tc.status && (
            <span className="text-[10px] text-gray-400">{tc.status}</span>
          )}
        </button>
        {/* Approval status badge */}
        {hasApproval && (
          <span className={`text-[10px] font-semibold uppercase tracking-wider px-1.5 py-0.5 rounded ${
            isApproved ? 'text-green-700 bg-green-50'
              : isRejected ? 'text-red-700 bg-red-50'
              : 'text-amber-700 bg-amber-50'
          }`}>
            {isApproved ? 'Approved' : isRejected ? 'Rejected' : 'Approval Required'}
          </span>
        )}
      </div>
      {expanded && resultStr && (
        <div className="ml-4.5 mt-0.5 p-2 rounded bg-gray-50 border border-gray-100 text-xs text-gray-700 whitespace-pre-wrap break-all max-h-40 overflow-auto font-mono">
          {resultStr.length > 2000 ? resultStr.slice(0, 2000) + '…' : resultStr}
        </div>
      )}
      {tc.status === 'executing' && tc.tool_name === 'bash' && (
        <BashLiveOutput tc={tc} />
      )}
      {/* Approve/reject buttons for pending approvals */}
      {isPending && (
        <div className="ml-4.5 mt-1">
          {userCanApprove ? (
            !rejectMode ? (
              <div className="flex items-center gap-2">
                <button
                  onClick={() => approveMut.mutate(tc.approval.id)}
                  disabled={isProcessing}
                  className="inline-flex items-center gap-1 px-2 py-0.5 text-xs font-medium bg-green-600 text-white rounded-md hover:bg-green-700 disabled:opacity-50 transition-colors"
                >
                  {isProcessing ? <Loader2 className="w-3 h-3 animate-spin" /> : <CheckCircle className="w-3 h-3" />}
                  Approve
                </button>
                <button
                  onClick={() => setRejectMode(true)}
                  disabled={isProcessing}
                  className="px-2 py-0.5 text-xs text-gray-500 hover:text-red-600 hover:bg-red-50 rounded-md transition-colors"
                >
                  Reject
                </button>
              </div>
            ) : (
              <div className="flex items-center gap-1.5">
                <input
                  type="text"
                  value={rejectReason}
                  onChange={(e) => setRejectReason(e.target.value)}
                  placeholder="Reason..."
                  aria-label="Rejection reason"
                  className="flex-1 min-w-0 px-2 py-0.5 text-xs border border-gray-200 rounded-md focus:outline-none focus:ring-1 focus:ring-red-400"
                  autoFocus
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && rejectReason.trim()) {
                      rejectMut.mutate({ approvalId: tc.approval.id, reason: rejectReason })
                    }
                    if (e.key === 'Escape') {
                      setRejectMode(false)
                      setRejectReason('')
                    }
                  }}
                />
                <button
                  onClick={() => rejectMut.mutate({ approvalId: tc.approval.id, reason: rejectReason })}
                  disabled={isProcessing || !rejectReason.trim()}
                  className="px-2 py-0.5 text-xs bg-red-600 text-white rounded-md hover:bg-red-700 disabled:opacity-50 transition-colors"
                >
                  Reject
                </button>
                <button
                  onClick={() => { setRejectMode(false); setRejectReason('') }}
                  className="px-2 py-0.5 text-xs text-gray-400 hover:text-gray-600 transition-colors"
                >
                  Cancel
                </button>
              </div>
            )
          ) : (
            <span className="text-[10px] text-amber-600">
              {isSessionOwnerApproval
                ? 'Waiting for your approval'
                : `Waiting for ${requiredRoles.join(' or ')} approval`}
            </span>
          )}
        </div>
      )}
    </div>
  )
}

const DEPTH_STYLES = [
  { border: 'border-blue-200', bg: 'bg-blue-50/40' },
  { border: 'border-purple-200', bg: 'bg-purple-50/40' },
  { border: 'border-amber-200', bg: 'bg-amber-50/40' },
  { border: 'border-gray-300', bg: 'bg-gray-50/40' },
]

const SubagentRunCard = ({ subagentRun, depth = 0, sessionId, sessionUserId, isOwner, isAdmin, userRoles }) => {
  const [expanded, setExpanded] = useState(depth < 1)
  const queryClient = useQueryClient()
  const config = getAgentConfig(subagentRun.agent_id)
  const AgentIcon = config.icon

  const allToolCalls = []
  subagentRun.llm_calls?.forEach((llm) => {
    llm.tool_calls?.forEach((tc) => {
      allToolCalls.push(tc)
    })
  })

  const hasContent = allToolCalls.length > 0 || (subagentRun.subagent_runs?.length > 0)
  const depthStyle = DEPTH_STYLES[Math.min(depth, DEPTH_STYLES.length - 1)]

  return (
    <div
      className={`mt-1.5 rounded-lg border ${depthStyle.border} ${depthStyle.bg}`}
      style={{ marginLeft: depth * 16 }}
    >
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center gap-2 px-2.5 py-1.5 text-left hover:bg-gray-50/50 rounded-lg transition-colors"
      >
        {expanded ? (
          <ChevronDown className="w-3.5 h-3.5 text-gray-400 flex-shrink-0" />
        ) : (
          <ChevronRight className="w-3.5 h-3.5 text-gray-400 flex-shrink-0" />
        )}
        <div className="w-4 h-4 rounded-full bg-gray-100 border border-gray-200 flex items-center justify-center flex-shrink-0">
          <AgentIcon className="w-2.5 h-2.5 text-gray-500" />
        </div>
        <span className="text-xs font-medium text-gray-700">{config.name}</span>
        <StatusBadge status={subagentRun.status} />
        {allToolCalls.length > 0 && (
          <span className="text-[10px] text-gray-400 ml-auto">
            {allToolCalls.length} tool{allToolCalls.length !== 1 ? 's' : ''}
          </span>
        )}
      </button>

      {expanded && hasContent && (
        <div className="px-3 pb-2 pt-0.5 space-y-0.5">
          {(() => {
            const toolSubagentMap = {}
            for (const tc of allToolCalls) {
              if (tc.tool_name === 'subagents' && subagentRun.subagent_runs?.length > 0) {
                const linked = subagentRun.subagent_runs.filter(
                  sa => sa.spawning_tool_call_id === tc.id
                )
                if (linked.length > 0) {
                  toolSubagentMap[tc.id] = linked
                }
              }
            }
            return allToolCalls.map((tc, i) => (
              <div key={tc.id || i}>
                {tc.question_id ? (
                  <TimelineQuestion tc={tc} agentId={subagentRun.agent_id} sessionId={sessionId} isOwner={isOwner} isAdmin={isAdmin} userRoles={userRoles} />
                ) : (
                  <SubagentToolCall tc={tc} sessionId={sessionId} sessionUserId={sessionUserId} />
                )}
                {toolSubagentMap[tc.id]?.map((sa, si) => (
                  <SubagentRunCard key={sa.id || si} subagentRun={sa} depth={depth + 1} sessionId={sessionId} sessionUserId={sessionUserId} isOwner={isOwner} isAdmin={isAdmin} userRoles={userRoles} />
                ))}
              </div>
            ))
          })()}
        </div>
      )}
    </div>
  )
}

// --- Agent Run ---

const AgentRunItem = ({ run, timelineIndex, sessionId, hasFollowingMessage, sessionUserId, isOwner, isAdmin, userRoles, surfacedFiles, attachments, onAttachmentsConsumed, onAnswerSubmitted, language }) => {
  const orderedItems = extractOrderedItems(run, hasFollowingMessage)

  const showAgentTrace = !hasFollowingMessage && run.status !== 'running'

  const fallbackCall = !run._hideFallback && run.llm_calls?.find(llm => llm.fallback_used)
  const hasFailed = run.status === 'failed' && run.error_message

  if (!showAgentTrace && orderedItems.length === 0 && (!surfacedFiles || surfacedFiles.length === 0) && !fallbackCall && !hasFailed) return null

  const config = getAgentConfig(run.agent_id)
  const AgentIcon = config.icon
  const colors = getAgentMessageColors(config.color)

  return (
    <div data-type="agent-run" data-timeline-idx={timelineIndex}>
      {fallbackCall && (
        <div className="flex items-center gap-2 px-3 py-1.5 mb-2 rounded-lg bg-amber-50 border border-amber-200 text-xs text-amber-700">
          <AlertTriangle className="w-3.5 h-3.5 flex-shrink-0" />
          <span>
            {language === 'nl'
              ? <>Model gewisseld: geconfigureerd <code className="font-semibold">{fallbackCall.intended_provider}/{fallbackCall.intended_model?.split('/').pop()}</code> niet beschikbaar, gebruikt <code className="font-semibold">{fallbackCall.model}</code></>
              : <>Model switched: configured <code className="font-semibold">{fallbackCall.intended_provider}/{fallbackCall.intended_model?.split('/').pop()}</code> unavailable, using <code className="font-semibold">{fallbackCall.model}</code></>
            }
          </span>
        </div>
      )}
      {hasFailed && (
        <div className="flex items-center gap-2 px-3 py-1.5 mb-2 rounded-lg bg-red-50 border border-red-200 text-xs text-red-700">
          <XCircle className="w-3.5 h-3.5 flex-shrink-0" />
          <span>
            {language === 'nl'
              ? <>{config.name} mislukt: {run.error_message}</>
              : <>{config.name} failed: {run.error_message}</>
            }
          </span>
        </div>
      )}
      {showAgentTrace && (
        <div className="group">
          <div className="flex items-center gap-2">
            <div className={`w-6 h-6 rounded-full flex items-center justify-center flex-shrink-0 ${colors.bg} border ${colors.border}`}>
              <AgentIcon className={`w-3.5 h-3.5 ${colors.accent}`} />
            </div>
            <span className={`text-sm font-medium ${colors.accent}`}>{config.name}</span>
          </div>
        </div>
      )}
      {orderedItems.map((item, i) => {
        if (item.type === 'approval') {
          return (
            <div key={i} className="mt-2">
              <InlineApproval tc={item.tc} sessionId={sessionId} sessionUserId={sessionUserId} />
            </div>
          )
        }
        if (item.type === 'question') {
          return (
            <div key={i} className="mt-3">
              <TimelineQuestion tc={item.tc} agentId={item.agentId} sessionId={sessionId} isOwner={isOwner} isAdmin={isAdmin} userRoles={userRoles} attachments={attachments} onAttachmentsConsumed={onAttachmentsConsumed} onAnswerSubmitted={onAnswerSubmitted} />

            </div>
          )
        }
        if (item.type === 'test') {
          return (
            <div key={i} className="mt-2">
              <TestResultCard testResults={[item.data]} />
            </div>
          )
        }
        if (item.type === 'subagents') {
          return (
            <div key={i} className="mt-2 border-l-2 border-blue-200 pl-2">
              {item.subagentRuns.map((sa, si) => (
                <SubagentRunCard key={sa.id || si} subagentRun={sa} depth={0} sessionId={sessionId} sessionUserId={sessionUserId} isOwner={isOwner} isAdmin={isAdmin} userRoles={userRoles} />
              ))}
            </div>
          )
        }
      return null
      })}
      {surfacedFiles.length > 0 && (
        <SurfacedFileCard files={surfacedFiles} />
      )}
    </div>
  )
}

// --- Message ---

const MessageItem = ({ message, agentRun, sessionId }) => {
  const isUser = message.role === 'user'
  const isResumeContext = isUser && message.agent_run_id
  const hasAgent = message.agent_id && !isUser
  const surfacedApprovals = agentRun
    ? extractSurfacedApprovals(agentRun.llm_calls).filter((item) => item.tc.approval.status !== 'pending')
    : []

  if (isUser) {
    if (isResumeContext) return null
    const atts = message.attachments || []
    const attNames = atts.map((a) => a.original_filename).join(', ')
    const isAttachmentOnly = atts.length > 0 && (message.content === 'See attached' || message.content === 'Zie bijlage' || message.content === attNames)
    return (
      <div className="group flex justify-end gap-2">
        <span className="text-xs text-gray-300 self-end pb-1">
          {message.created_at && new Date(message.created_at).toLocaleTimeString()}
        </span>
        <div className="max-w-[85%] rounded-2xl px-4 py-2.5 text-sm bg-gray-100 text-gray-900 overflow-hidden">
          {!isAttachmentOnly && (
            <div className="whitespace-pre-wrap break-words">{message.content}</div>
          )}
          {atts.length > 0 && (
            <div className={`flex flex-wrap gap-1.5${isAttachmentOnly ? '' : ' mt-2'}`}>
              {atts.map((att) => {
                const Icon = att.content_type === 'application/pdf' ? FileType : FileText
                return (
                  <button
                    key={att.id}
                    type="button"
                    onClick={() => {
                      if (window.confirm(`Download "${att.original_filename}"?`)) {
                        window.open(getAttachmentUrl(att.id), '_blank')
                      }
                    }}
                    className="inline-flex items-center gap-1.5 px-2.5 py-1 bg-white/60 rounded-lg text-xs text-gray-600 hover:bg-white transition-colors cursor-pointer"
                  >
                    <Icon className="w-3.5 h-3.5 text-gray-400" />
                    <span className="truncate max-w-[120px]">{att.original_filename}</span>
                  </button>
                )
              })}
            </div>
          )}
        </div>
      </div>
    )
  }

  if (hasAgent) {
    const config = getAgentConfig(message.agent_id)
    const AgentIcon = config.icon
    const colors = getAgentMessageColors(config.color)

    return (
      <>
        <div className="group">
          <div className="flex items-center gap-2 mb-1.5">
            <div className={`w-6 h-6 rounded-full flex items-center justify-center flex-shrink-0 ${colors.bg} border ${colors.border}`}>
              <AgentIcon className={`w-3.5 h-3.5 ${colors.accent}`} />
            </div>
            <span className={`text-sm font-medium ${colors.accent}`}>{config.name}</span>
            <span className="text-xs text-gray-300">
              {message.created_at && new Date(message.created_at).toLocaleTimeString()}
            </span>
          </div>
          <div className="pl-8 markdown-content text-sm text-gray-800 leading-relaxed break-words overflow-hidden">
            <ReactMarkdown remarkPlugins={[remarkGfm]} components={chatMarkdownComponents}>
              {message.content}
            </ReactMarkdown>
          </div>
          {(message.attachments || []).length > 0 && (
            <div className="pl-8 mt-2 flex flex-wrap gap-1.5">
              {message.attachments.map((att) => {
                const Icon = att.content_type === 'application/pdf' ? FileType : FileText
                return (
                  <button
                    key={att.id}
                    type="button"
                    onClick={() => {
                      if (window.confirm(`Download "${att.original_filename}"?`)) {
                        window.open(getAttachmentUrl(att.id), '_blank')
                      }
                    }}
                    className="inline-flex items-center gap-1.5 px-2.5 py-1 bg-white/60 rounded-lg text-xs text-gray-600 hover:bg-white transition-colors cursor-pointer"
                  >
                    <Icon className="w-3.5 h-3.5 text-gray-400" />
                    <span className="truncate max-w-[120px]">{att.original_filename}</span>
                  </button>
                )
              })}
            </div>
          )}
        </div>
        {surfacedApprovals.length > 0 && (
          <div className="mt-3 space-y-3">
            {surfacedApprovals.map((item, i) => (
              <InlineApproval key={i} tc={item.tc} sessionId={sessionId} />
            ))}
          </div>
        )}
      </>
    )
  }

  return (
    <div className="group">
      <div className="flex items-center gap-2 mb-1.5">
        <div className="w-6 h-6 rounded-full flex items-center justify-center flex-shrink-0 bg-gray-100 border border-gray-200">
          <Shield className="w-3.5 h-3.5 text-gray-500" />
        </div>
        <span className="text-sm font-medium text-gray-500">System</span>
        <span className="text-xs text-gray-300">
          {message.created_at && new Date(message.created_at).toLocaleTimeString()}
        </span>
      </div>
      <div className="pl-8 text-sm text-gray-700 leading-relaxed overflow-hidden">
        <div className="whitespace-pre-wrap break-words">{message.content}</div>
      </div>
    </div>
  )
}

// --- Sandbox Live Progress ---

// --- Main SessionDetail ---

const VALID_VIEW_MODES = new Set(['chat', 'annotated', 'inspect'])
// AgentRunStatus values that indicate the agent has started processing (not pending)
// Note: 'paused_user' was removed as it doesn't exist; 'paused_crashed' added
const STARTED_STATUSES = new Set(['running', 'completed', 'failed', 'paused_hitl', 'paused_tool', 'paused_sandbox', 'paused_crashed', 'waiting_approval', 'waiting_answer'])

const SessionDetail = ({ sessionId, initialViewMode }) => {
  const timelineEndRef = useRef(null)
  const timelineRef = useRef(null)
  const prevLengthRef = useRef(0)
  const inputRef = useRef(null)
  const [continueInput, setContinueInput] = useState('')
  const [showContinueDialog, setShowContinueDialog] = useState(false)
  const [attachments, setAttachments] = useState([])
  const [uploadError, setUploadError] = useState(null)
  const [transcriptPdfLoading, setTranscriptPdfLoading] = useState(false)
  const [pendingMessage, setPendingMessage] = useState(() => {
    const cached = consumePending(sessionId)
    return cached?.message || null
  })
  const [isAnswering, setIsAnswering] = useState(false)
  const pendingSetAtLength = useRef(pendingMessage ? 0 : null)
  const savedInspectScroll = useRef(0)
  const [viewMode, _setViewMode] = useState(() => {
    if (initialViewMode && VALID_VIEW_MODES.has(initialViewMode)) return initialViewMode
    return 'chat'
  })
  const setViewMode = (newMode) => {
    // Save scroll only when leaving timeline for inspect
    if (viewMode !== 'inspect' && newMode === 'inspect' && timelineRef.current) {
      savedInspectScroll.current = timelineRef.current.scrollTop
    }
    _setViewMode(newMode)
  }
  const queryClient = useQueryClient()
  const { user } = useAuth()
  const canDebug = user?.roles?.some(r => r === 'developer' || r === 'admin')
  const isAdmin = !!user?.roles?.includes('admin')

  const { data, isLoading, error } = useQuery({
    queryKey: ['session', sessionId],
    queryFn: () => getSession(sessionId),
    retry: (failureCount, error) => {
      if (error?.status === 403 || error?.status === 404) return false
      return failureCount < 3
    },
    refetchInterval: (query) => {
      if (query.state.error) return false
      const status = query.state.data?.status
      if (status === 'completed' || status === 'failed' || status === 'terminated') return false
      // Fast poll briefly after submitting an answer/approval (translation in progress)
      if (isResuming()) return 500
      if (status === 'paused_crashed') return 1000
      if (status === 'paused_sandbox') return 1000
      if (status === 'paused' || status === 'paused_approval' || status === 'paused_hitl' || status === 'paused_ba_hitl' || status === 'paused_architect_hitl') {
        return 500
      }
      return 500
    },
    enabled: !!sessionId,
  })

  const continueMutation = useMutation({
    mutationFn: ({ message, attachmentIds }) => sendChat(message, sessionId, null, attachmentIds),
    onSuccess: () => {
      markResuming()
      setContinueInput('')
      setAttachments([])
      setUploadError(null)
      queryClient.invalidateQueries({ queryKey: ['session', sessionId] })
      queryClient.invalidateQueries({ queryKey: ['sessions'] })
    },
    onError: () => {
      setPendingMessage(null)
    },
  })

  const cancelMutation = useMutation({
    mutationFn: () => cancelChat(sessionId),
    onSuccess: () => {
      queryClient.refetchQueries({ queryKey: ['session', sessionId] })
      queryClient.invalidateQueries({ queryKey: ['sessions'] })
    },
    onError: (err) => {
      console.error('Cancel failed:', err)
    },
  })

  // Derive "stopping" state: session is paused but agent is still finishing current operation
  const hasRunningAgentRun = data?.timeline?.some(
    e => e.type === 'agent_run' && e.agent_run?.status === 'running'
  )

  // If all tool calls are failed, don't show "Stopping..." even if agent_run is "running"
  const hasActuallyRunningToolCall = data?.timeline?.some(
    e => e.type === 'agent_run' && (e.agent_run?.llm_calls || []).some(
      llm => (llm.tool_calls || []).some(
        tc => tc.status === 'executing' || tc.status === 'waiting_approval' || tc.status === 'waiting_sandbox'
      )
    )
  )

  const isStopping = data?.status === 'paused' && hasRunningAgentRun && hasActuallyRunningToolCall

  // When session has pending approvals, keep the tasks/badge cache fresh
  useEffect(() => {
    const status = data?.status
    if (status === 'paused_approval') {
      queryClient.invalidateQueries({ queryKey: ['tasks'] })
      queryClient.invalidateQueries({ queryKey: ['pending-approvals-count'] })
    }
  }, [data?.status, queryClient])

  useEffect(() => {
    const currentLength = data?.timeline?.length || 0
    if (currentLength > prevLengthRef.current) {
      const isInitial = prevLengthRef.current === 0
      // Double rAF for initial load: ensures flex layout is fully computed
      // (cached data can arrive before the container has its final height).
      // Single rAF suffices for incremental new-message scrolls.
      const schedule = isInitial
        ? (fn) => requestAnimationFrame(() => requestAnimationFrame(fn))
        : (fn) => requestAnimationFrame(fn)
      schedule(() => {
        const el = timelineRef.current
        if (el) el.scrollTo({ top: el.scrollHeight, behavior: isInitial ? 'instant' : 'smooth' })
      })
    }
    prevLengthRef.current = currentLength
  }, [data?.timeline?.length])

  // Restore scroll position when returning from inspect to timeline
  const prevViewMode = useRef(viewMode)
  useEffect(() => {
    if (prevViewMode.current === 'inspect' && viewMode !== 'inspect') {
      const saved = savedInspectScroll.current
      requestAnimationFrame(() => {
        if (timelineRef.current) {
          timelineRef.current.scrollTop = saved
        }
      })
    }
    prevViewMode.current = viewMode
  }, [viewMode])

  useEffect(() => {
    if (inputRef.current) {
      inputRef.current.style.height = 'auto'
      inputRef.current.style.height = Math.min(inputRef.current.scrollHeight, 160) + 'px'
    }
  }, [continueInput])

  const isBusy = continueMutation.isPending || isAnswering

  // Clear optimistic message once server data catches up (new timeline entries)
  useEffect(() => {
    if (pendingMessage === null) return
    const len = data?.timeline?.length || 0
    if (pendingSetAtLength.current !== null && len > pendingSetAtLength.current) {
      setPendingMessage(null)
      setIsAnswering(false)
    }
  }, [data?.timeline?.length, pendingMessage])

  // Safety: clear pending message after 30s in case data never arrives
  useEffect(() => {
    if (!pendingMessage) return
    const timer = setTimeout(() => {
      setPendingMessage(null)
      setIsAnswering(false)
    }, 30000)
    return () => clearTimeout(timer)
  }, [pendingMessage])

  // Scroll to bottom when optimistic message appears
  useEffect(() => {
    if (pendingMessage) {
      requestAnimationFrame(() => {
        const el = timelineRef.current
        if (el) el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' })
      })
    }
  }, [pendingMessage])

  if (isLoading) {
    return (
      <div className="flex flex-col h-full min-w-0">
        {/* Skeleton header */}
        <div className="px-4 py-3 border-b flex items-center gap-3">
          <div className="w-32 h-4 bg-gray-200 rounded animate-pulse" />
          <div className="w-20 h-4 bg-gray-100 rounded animate-pulse" />
        </div>
        {/* Skeleton messages */}
        <div className="flex-1 p-4 space-y-6">
          {/* User message skeleton */}
          <div className="flex justify-end">
            <div className="w-2/3 h-12 bg-gray-100 rounded-2xl animate-pulse" />
          </div>
          {/* Agent message skeleton */}
          <div className="flex items-start gap-2">
            <div className="w-6 h-6 bg-gray-200 rounded-full animate-pulse flex-shrink-0" />
            <div className="space-y-2 flex-1">
              <div className="w-24 h-3 bg-gray-200 rounded animate-pulse" />
              <div className="w-full h-20 bg-gray-100 rounded-lg animate-pulse" />
            </div>
          </div>
          {/* Another user message */}
          <div className="flex justify-end">
            <div className="w-1/2 h-10 bg-gray-100 rounded-2xl animate-pulse" />
          </div>
        </div>
      </div>
    )
  }

  if (error) {
    const isAccessDenied = error.status === 403
    const isNotFound = error.status === 404
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-center max-w-sm space-y-3">
          {isAccessDenied ? (
            <>
              <ShieldOff className="w-12 h-12 text-gray-300 mx-auto" />
              <h3 className="text-lg font-semibold text-gray-700">Access Denied</h3>
              <p className="text-sm text-gray-500">You don't have permission to view this session. It may belong to another user.</p>
            </>
          ) : isNotFound ? (
            <>
              <MessageSquare className="w-12 h-12 text-gray-300 mx-auto" />
              <h3 className="text-lg font-semibold text-gray-700">Session Not Found</h3>
              <p className="text-sm text-gray-500">This session doesn't exist or may have been deleted.</p>
            </>
          ) : (
            <>
              <AlertTriangle className="w-12 h-12 text-red-300 mx-auto" />
              <h3 className="text-lg font-semibold text-gray-700">Something Went Wrong</h3>
              <p className="text-sm text-gray-500">{error.message}</p>
            </>
          )}
          <Link to="/chat" className="inline-block text-sm text-blue-600 hover:text-blue-700 mt-2">
            ← Back to conversations
          </Link>
        </div>
      </div>
    )
  }

  if (!data) return null

  // Ownership / control gating.
  // - Owner: can answer their own HITL questions, send messages, stop, resume
  // - Expert (non-owner with the right role): read-only here; they answer
  //   expert questions on the /questions page (or inline when allowed).
  //   They cannot send messages or stop/resume the session.
  // - Admin: same as owner.
  const isOwner = !!data?.user_id && data.user_id === user?.id
  const canControlSession = isOwner || isAdmin

  const pendingQuestion = findPendingQuestion(data.timeline)
  const fallbackQuestion = findFallbackQuestion(data.timeline)

  const handleContinueSend = () => {
    const trimmed = continueInput.trim()
    if (!trimmed && !attachments.length) return
    if (pendingQuestion) {
      const fileNames = attachments.map((a) => a.original_filename).join(', ')
      const answer = trimmed
        || (attachments.length ? `Zie geüploade bestanden: ${fileNames}` : '')
      if (!answer) return
      setPendingMessage(trimmed || true)
      setIsAnswering(true)
      pendingSetAtLength.current = data?.timeline?.length || 0
      setContinueInput('')
      setAttachments([])
      const attIds = attachments.map((a) => a.id)
      answerQuestion(pendingQuestion.tc.question_id, answer, null, attIds)
        .then(() => {
          setIsAnswering(false)
          markResuming()
          queryClient.invalidateQueries({ queryKey: ['session', sessionId] })
        })
        .catch((err) => {
          console.error('Failed to answer question:', err.message || err)
          setPendingMessage(null)
          setIsAnswering(false)
        })
      return
    }
    setUploadError(null)
    const fallback = attachments.length
      ? attachments.map((a) => a.original_filename).join(', ')
      : 'Zie bijlage'
    const message = trimmed || fallback
    setPendingMessage(trimmed || true)
    pendingSetAtLength.current = data?.timeline?.length || 0
    continueMutation.mutate({ message, attachmentIds: attachments.map((a) => a.id) })
  }

  const statusDotColor = isStopping
    ? 'bg-amber-500 animate-pulse'
    : {
        completed: 'bg-green-500',
        active: 'bg-blue-500 animate-pulse',
        running: 'bg-blue-500 animate-pulse',
        failed: 'bg-red-500',
        pending: 'bg-gray-400',
        paused: 'bg-amber-500',
        paused_crashed: 'bg-red-500',
        paused_hitl: 'bg-amber-500 animate-pulse',
        paused_tool: 'bg-amber-500 animate-pulse',
        paused_sandbox: 'bg-blue-500 animate-pulse',
        paused_approval: 'bg-amber-500 animate-pulse',
        waiting_answer: 'bg-amber-500 animate-pulse',
        paused_ba_hitl: 'bg-amber-500 animate-pulse',
        paused_architect_hitl: 'bg-indigo-500 animate-pulse',
        terminated: 'bg-gray-400',
      }[data.status] || 'bg-gray-400'

  const projectRepo = data?.project
    ? {
        id: data.project.id,
        repo_url: data.project.repo_url,
        default_branch: data.project.default_branch || 'main',
        // Carries the current session so embedded artifacts (e.g. the
        // .archimate file referenced from a ```archimate``` block in the
        // TD preview) can be fetched from the session workspace before
        // the architect's commit reaches Gitea.
        session_id: sessionId,
      }
    : null

  return (
    <ProjectRepoContext.Provider value={projectRepo}>
    <div className="flex flex-col h-full min-w-0">
      {fallbackQuestion && <FallbackModal tc={fallbackQuestion} sessionId={sessionId} language={data.language} />}
      {/* Header */}
      <div className="px-4 py-2.5 border-b flex-shrink-0">
        <div className="flex items-center gap-2.5 min-w-0">
          <span className={`w-2 h-2 rounded-full flex-shrink-0 ${statusDotColor}`} />
          <h2 className="text-sm font-medium text-gray-900 truncate">
            {data.title || 'Untitled Session'}
          </h2>
          {data.intent === 'scheduled_job' && (
            <span className="inline-flex items-center gap-1 px-2 py-0.5 text-xs font-medium text-purple-600 bg-purple-50 border border-purple-200 rounded-full">
              <Calendar className="w-3 h-3" />
              Scheduled Job
            </span>
          )}
          <div className="ml-auto flex items-center gap-3 flex-shrink-0">
            {/* Stopping indicator — session is paused but agent still finishing */}
            {isStopping && (
              <span className="inline-flex items-center gap-1 px-2.5 py-1 text-xs font-medium text-amber-600 bg-amber-50 border border-amber-200 rounded-lg">
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
                Stopping…
              </span>
            )}
            {/* Sandbox running indicator */}
            {data.status === 'paused_sandbox' && (
              <span className="inline-flex items-center gap-1 px-2.5 py-1 text-xs font-medium text-blue-600 bg-blue-50 border border-blue-200 rounded-lg">
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
                Sandbox running…
              </span>
            )}
            {/* Continue button — when fully stopped, crashed, or failed */}
            {canControlSession && ['paused', 'paused_hitl', 'paused_crashed', 'failed'].includes(data.status) && !isStopping && (
              <button
                onClick={() => setShowContinueDialog(true)}
                className="inline-flex items-center gap-1 px-2.5 py-1 text-xs font-medium text-green-600 bg-green-50 border border-green-200 rounded-lg hover:bg-green-100 transition-colors"
              >
                <PlayCircle className="w-3.5 h-3.5" />
                Continue
              </button>
            )}
            {canControlSession && data.status === 'active' && (
              <button
                onClick={() => cancelMutation.mutate()}
                disabled={cancelMutation.isPending}
                className="inline-flex items-center gap-1 px-2.5 py-1 text-xs font-medium text-red-600 bg-red-50 border border-red-200 rounded-lg hover:bg-red-100 disabled:opacity-50 transition-colors"
              >
                {cancelMutation.isPending ? (
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                ) : (
                  <StopCircle className="w-3.5 h-3.5" />
                )}
                Stop
              </button>
            )}
            {!canControlSession && (
              <span className="inline-flex items-center gap-1 px-2.5 py-1 text-xs font-medium text-purple-700 bg-purple-50 border border-purple-200 rounded-lg">
                Read-only · expert view
              </span>
            )}
            {cancelMutation.isError && (
              <span className="text-xs text-red-600">
                {cancelMutation.error?.message || 'Action failed'}
              </span>
            )}
            {canDebug && (
              <div className="flex items-center bg-gray-100 rounded-lg p-0.5 text-xs">
                {['chat', 'annotated', 'inspect'].map((mode) => (
                  <button
                    key={mode}
                    onClick={() => setViewMode(mode)}
                    className={`px-2 py-1 rounded transition-colors capitalize ${
                      viewMode === mode
                        ? 'bg-white shadow-sm text-gray-900 font-medium'
                        : 'text-gray-500 hover:text-gray-700'
                    }`}
                  >
                    {mode === 'inspect' ? 'Inspect' : mode === 'annotated' ? 'Annotated' : 'Chat'}
                  </button>
                ))}
              </div>
            )}
            {data.project && (
              <a
                href={`/projects/${data.project.id}`}
                className="text-xs text-gray-400 hover:text-blue-500 flex items-center gap-1 transition-colors"
              >
                {data.project.name}
              </a>
            )}
            <DownloadMenu
              loading={transcriptPdfLoading}
              onDownloadMd={() => {
                const md = buildChatTranscript(data)
                const slug = (data.title || 'chat').replace(/[^a-z0-9]+/gi, '-').toLowerCase()
                downloadAsMarkdown(md, `${slug}.md`)
              }}
              onDownloadPdf={async () => {
                setTranscriptPdfLoading(true)
                try {
                  const md = buildChatTranscript(data)
                  const slug = (data.title || 'chat').replace(/[^a-z0-9]+/gi, '-').toLowerCase()
                  await downloadContentAsPdf(md, `${slug}.pdf`)
                } finally {
                  setTranscriptPdfLoading(false)
                }
              }}
            />
            <CopyJsonButton
              getData={() => buildVisibleJson(data, timelineRef.current)}
              label="Copy JSON"
            />
          </div>
        </div>
      </div>

      {/* Crash recovery banner */}
      {data.status === 'paused_crashed' && (
        <div className="mx-4 mt-2 px-3 py-2 bg-amber-50 border border-amber-200 rounded-lg flex items-start gap-2">
          <AlertTriangle className="w-4 h-4 text-amber-500 mt-0.5 flex-shrink-0" />
          <div className="text-xs text-amber-800">
            <span className="font-medium">The system restarted during this run.</span>{' '}
            Click Continue to pick up where it left off.
          </div>
        </div>
      )}

      {/* Workflow Pipeline — quick-glance status bar for all modes */}
      <WorkflowPipeline timeline={data.timeline} />

      {/* Content area: Chat/Annotated timeline or Inspect event log */}
      {viewMode === 'inspect' ? (
        <DebugEventLog data={data} sessionId={sessionId} sessionStatus={data.status} />
      ) : (
        <div ref={timelineRef} className="flex-1 min-h-0 overflow-y-auto overflow-x-hidden">
          <div className="max-w-3xl mx-auto px-4 py-6 space-y-6">
          {(!data.timeline || data.timeline.length === 0) && !pendingMessage && (
            data.status === 'active' || data.status === 'running' ? (
              <div className="flex items-center justify-center py-12">
                <Loader2 className="w-5 h-5 text-gray-400 animate-spin" />
              </div>
            ) : (
              <div className="text-center py-12 flex flex-col items-center gap-2">
                <MessageSquare className="w-8 h-8 text-gray-300" />
                <p className="text-gray-400 text-sm">No timeline entries yet</p>
              </div>
            )
          )}
          {(() => {
            // messageRunMap: pairs each agent's last non-user message with its run
            // (used for surfaced approvals in chat bubbles)
            const messageRunMap = new Map()
            const runsWithMessages = new Set()
            // annotationMap: places each agent's AnnotationBar after the last
            // timeline entry (any message role) before the next agent_run starts
            const annotationMap = new Map()
            if (data.timeline) {
              let lastRun = null
              let lastRunIdx = null
              let lastMsgIdx = null
              // For annotation placement
              let annotCurrentRun = null
              let annotCurrentRunIdx = null
              let annotLastEntryIdx = null
              for (let idx = 0; idx < data.timeline.length; idx++) {
                const e = data.timeline[idx]
                if (e.type === 'agent_run' && e.agent_run) {
                  // messageRunMap logic (non-user messages only)
                  if (lastRun && lastMsgIdx !== null) {
                    messageRunMap.set(lastMsgIdx, lastRun)
                    runsWithMessages.add(lastRunIdx)
                  }
                  lastRun = e.agent_run
                  lastRunIdx = idx
                  lastMsgIdx = null
                  // annotationMap logic (all messages)
                  if (annotCurrentRun) {
                    annotationMap.set(annotLastEntryIdx ?? annotCurrentRunIdx, annotCurrentRun)
                  }
                  annotCurrentRun = e.agent_run
                  annotCurrentRunIdx = idx
                  annotLastEntryIdx = null
                } else if (e.type === 'message') {
                  if (e.message?.role !== 'user' && lastRun) {
                    lastMsgIdx = idx
                  }
                  annotLastEntryIdx = idx
                }
              }
              if (lastRun && lastMsgIdx !== null) {
                messageRunMap.set(lastMsgIdx, lastRun)
                runsWithMessages.add(lastRunIdx)
              }
              if (annotCurrentRun) {
                annotationMap.set(annotLastEntryIdx ?? annotCurrentRunIdx, annotCurrentRun)
              }
            }

            const renderAnnotation = (i) => {
              if (viewMode !== 'annotated') return null
              const run = annotationMap.get(i)
              if (!run) return null
              return (
                <div className="pl-8 mt-1">
                  <AnnotationBar run={run} />
                </div>
              )
            }

            const fallbackSeen = new Set()
            return data.timeline?.map((entry, i) => {
              // Messages always render
              if (entry.type === 'message' && entry.message) {
                return (
                  <div key={i}>
                    <MessageItem
                      message={entry.message}
                      agentRun={messageRunMap.get(i)}
                      sessionId={sessionId}
                    />
                    {renderAnnotation(i)}
                  </div>
                )
              }

              // Agent runs: render if they have visible content or completed without a message
              if (entry.type === 'agent_run' && entry.agent_run) {
                // Skip pending agents that haven't started yet — they show in the workflow bar
                if (!STARTED_STATUSES.has(entry.agent_run.status)) return null

                const hasFollowingMessage = runsWithMessages.has(i)
                const orderedItems = extractOrderedItems(entry.agent_run, hasFollowingMessage)
                const surfacedFiles = extractSurfacedFileWrites(entry.agent_run)
                // Show completed runs without a following message (e.g. architect)
                const isCompletedWithoutMessage = !hasFollowingMessage && entry.agent_run.status !== 'running'

                const fallbackCall = entry.agent_run.llm_calls?.find(llm => llm.fallback_used)
                const fallbackKey = fallbackCall ? `${fallbackCall.intended_provider}/${fallbackCall.intended_model}→${fallbackCall.model}` : null
                const showFallback = fallbackKey && !fallbackSeen.has(fallbackKey)
                if (showFallback) fallbackSeen.add(fallbackKey)

                if (orderedItems.length === 0 && surfacedFiles.length === 0 && !isCompletedWithoutMessage && !showFallback) {
                  return null
                }
                return (
                  <div key={i}>
                    <AgentRunItem
                      run={showFallback ? entry.agent_run : { ...entry.agent_run, _hideFallback: true }}
                      timelineIndex={i}
                      sessionId={sessionId}
                      hasFollowingMessage={hasFollowingMessage}
                      sessionUserId={data?.user_id}
                      isOwner={isOwner}
                      isAdmin={isAdmin}
                      userRoles={user?.roles || []}
                      surfacedFiles={surfacedFiles}
                      attachments={attachments}
                      onAttachmentsConsumed={() => { setAttachments([]); setUploadError(null) }}
                      onAnswerSubmitted={() => {
                        setPendingMessage(true)
                        pendingSetAtLength.current = data?.timeline?.length || 0
                      }}
                      language={data?.language}
                    />
                    {renderAnnotation(i)}
                  </div>
                )
              }

              return null
            })
          })()}
          {/* Optimistic user message + processing indicator */}
          {pendingMessage && (
            <>
              {typeof pendingMessage === 'string' && (
                <div className="flex justify-end gap-2">
                  <div className="max-w-[85%] rounded-2xl px-4 py-2.5 text-sm bg-gray-100 text-gray-900 overflow-hidden">
                    <div className="whitespace-pre-wrap break-words">{pendingMessage}</div>
                  </div>
                </div>
              )}
              <div className="flex items-center py-1">
                <Loader2 className="w-3.5 h-3.5 text-gray-400 animate-spin" />
              </div>
            </>
          )}
          {/* Trailing thinking / sandbox-waiting indicator */}
          {(() => {
            // Don't show thinking indicator if session itself has ended
            if (data.status === 'failed' || data.status === 'completed') return null
            const activeEntry = data.timeline?.findLast(
              (e) => e.type === 'agent_run' && (e.agent_run?.status === 'running' || e.agent_run?.status === 'paused_sandbox')
            )
            if (!activeEntry) return null
            const run = activeEntry.agent_run
            const isSandboxWaiting = run.status === 'paused_sandbox'
            const config = getAgentConfig(run.agent_id)
            const AgentIcon = config.icon
            const colors = getAgentMessageColors(config.color)
            return (
              <div>
                <div className="flex items-center gap-2 mb-1.5">
                  <div className={`w-6 h-6 rounded-full flex items-center justify-center flex-shrink-0 ${colors.bg} border ${colors.border}`}>
                    <AgentIcon className={`w-3.5 h-3.5 ${colors.accent}`} />
                  </div>
                  <span className={`text-sm font-medium ${colors.accent}`}>{config.name}</span>
                </div>
                  <div className="pl-8 flex items-center gap-1.5 py-1">
                    <span className="w-1.5 h-1.5 bg-gray-400 rounded-full animate-bounce [animation-delay:0ms]" />
                    <span className="w-1.5 h-1.5 bg-gray-400 rounded-full animate-bounce [animation-delay:150ms]" />
                    <span className="w-1.5 h-1.5 bg-gray-400 rounded-full animate-bounce [animation-delay:300ms]" />
                  </div>
              </div>
            )
          })()}
          {/* Pending approvals */}
          {(() => {
            const pending = []
            const scanRun = (run) => {
              run?.llm_calls?.forEach((llm) => {
                llm.tool_calls?.forEach((tc) => {
                  if (tc.approval?.status === 'pending') {
                    pending.push(tc)
                  }
                })
              })
              run?.subagent_runs?.forEach(scanRun)
            }
            data.timeline?.forEach((entry) => {
              if (entry.type !== 'agent_run' || !entry.agent_run) return
              scanRun(entry.agent_run)
            })
            if (pending.length === 0) return null
            return (
              <div className="space-y-3">
                {pending.map((tc, i) => (
                  <InlineApproval key={tc.approval.id || i} tc={tc} sessionId={sessionId} sessionUserId={data?.user_id} />
                ))}
              </div>
            )
          })()}
          {/* FD escalation HITL review surfaces — scroll with the chat */}
          {viewMode !== 'inspect' && (data.status === 'paused_ba_hitl' || data.status === 'paused_architect_hitl' || data.status === 'terminated') && (
            <div className="space-y-3 pt-4">
              {data.status === 'paused_ba_hitl' && (
                <>
                  <BAHitlCard sessionId={sessionId} session={data} />
                  <EscalationHistoryList sessionId={sessionId} />
                </>
              )}
              {data.status === 'paused_architect_hitl' && (
                <>
                  <ArchitectHitlCard sessionId={sessionId} session={data} />
                  <EscalationHistoryList sessionId={sessionId} />
                </>
              )}
              {data.status === 'terminated' && (
                <>
                  <div className="flex items-start gap-2.5 border border-gray-300 rounded-2xl shadow-sm px-4 py-3.5 bg-gray-100">
                    <Ban className="w-5 h-5 text-gray-500 flex-shrink-0 mt-0.5" />
                    <div className="min-w-0">
                      <p className="text-sm font-medium text-gray-800">Session terminated</p>
                      <p className="text-sm text-gray-600 mt-0.5">This session has been permanently terminated and cannot be resumed.</p>
                      {data.error_message && (
                        <p className="text-sm text-gray-700 mt-1.5 italic border-t border-gray-300 pt-1.5">
                          Reason: {data.error_message}
                        </p>
                      )}
                    </div>
                  </div>
                  <EscalationHistoryList sessionId={sessionId} />
                </>
              )}
            </div>
          )}
          <div ref={timelineEndRef} />
          </div>
        </div>
      )}

      {/* Failed session banner — show error message so the user knows what went wrong */}
      {data.status === 'failed' && viewMode !== 'inspect' && (
        <div className="px-4 pb-4 pt-2 flex-shrink-0">
          <div className="max-w-3xl mx-auto">
            <div className="flex items-start gap-2.5 border border-red-200 rounded-2xl shadow-sm px-4 py-3.5 bg-red-50">
              <XCircle className="w-5 h-5 text-red-500 flex-shrink-0 mt-0.5" />
              <div className="min-w-0">
                <p className="text-sm font-medium text-red-800">{data.language === 'nl' ? 'Sessie mislukt' : 'Session failed'}</p>
                {data.error_message && (
                  <p className="text-sm text-red-600 mt-0.5 break-words">{data.error_message}</p>
                )}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Sandbox waiting bar — replaces input when sandbox is running */}
      {data.status === 'paused_sandbox' && viewMode !== 'inspect' && (
        <div className="px-4 pb-4 pt-2 flex-shrink-0">
          <div className="max-w-3xl mx-auto">
            <div className="flex items-center justify-center gap-2 border border-blue-200 rounded-2xl shadow-sm px-4 py-3.5 bg-blue-50">
              <Loader2 className="w-4 h-4 text-blue-500 animate-spin" />
              <span className="text-sm text-blue-600">Coding agent is running in sandbox…</span>
            </div>
          </div>
        </div>
      )}

      {/* Floating input bar — hidden in inspect mode, during sandbox, HITL
          review states, terminated sessions, and for non-owner experts (they
          can only view the session here; they answer their expert questions
          on the /questions page). */}
      {canControlSession && !['failed', 'paused_sandbox', 'paused_ba_hitl', 'paused_architect_hitl', 'terminated'].includes(data.status) && viewMode !== 'inspect' && (
        <div className="px-4 pb-4 pt-2 flex-shrink-0">
          <div className="max-w-3xl mx-auto">
            <div className="border border-gray-200 rounded-2xl shadow-lg px-4 py-3 bg-white focus-within:border-gray-300 focus-within:shadow-xl transition-shadow">
              <AttachmentChips
                attachments={attachments}
                onRemove={(id) => setAttachments((prev) => prev.filter((a) => a.id !== id))}
              />
              <div className="flex items-end gap-2">
              <FileUploadButton
                onUpload={(att) => { setUploadError(null); setAttachments((prev) => [...prev, att]) }}
                onError={setUploadError}
                sessionId={sessionId}
                disabled={isBusy}
              />
              <textarea
                ref={inputRef}
                value={continueInput}
                onChange={(e) => setContinueInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey && !isBusy) {
                    e.preventDefault()
                    handleContinueSend()
                  }
                }}
                placeholder={
                  pendingQuestion
                    ? 'Type your answer...'
                    : data.status === 'completed'
                      ? 'Send a follow-up message...'
                      : 'Type a message...'
                }
                rows={1}
                className="flex-1 resize-none bg-transparent outline-none text-sm leading-6 py-1 max-h-40"
                aria-label="Chat message input"
                disabled={isBusy}
              />
              {isStopping ? (
                <button
                  disabled
                  className="flex-shrink-0 p-2 rounded-xl bg-amber-500 text-white transition-colors"
                  aria-label="Stopping"
                >
                  <Loader2 className="w-4 h-4 animate-spin" />
                </button>
              ) : data.status === 'active' ? (
                <button
                  onClick={() => cancelMutation.mutate()}
                  disabled={cancelMutation.isPending}
                  className="flex-shrink-0 p-2 rounded-xl bg-red-600 text-white hover:bg-red-700 disabled:opacity-50 transition-colors"
                  aria-label="Stop agent"
                >
                  {cancelMutation.isPending ? (
                    <Loader2 className="w-4 h-4 animate-spin" />
                  ) : (
                    <StopCircle className="w-4 h-4" />
                  )}
                </button>
              ) : ['paused', 'paused_hitl', 'paused_crashed', 'failed'].includes(data.status) ? (
                <button
                  onClick={() => setShowContinueDialog(true)}
                  className="flex-shrink-0 p-2 rounded-xl bg-green-600 text-white hover:bg-green-700 transition-colors"
                  aria-label="Continue agent"
                >
                  <PlayCircle className="w-4 h-4" />
                </button>
              ) : (
                <button
                  onClick={handleContinueSend}
                  disabled={(!continueInput.trim() && !attachments.length) || isBusy}
                  className="flex-shrink-0 p-2 rounded-xl bg-gray-900 text-white hover:bg-gray-700 disabled:opacity-30 disabled:hover:bg-gray-900 transition-colors"
                  aria-label="Send message"
                >
                  {isBusy ? (
                    <Loader2 className="w-4 h-4 animate-spin" />
                  ) : (
                    <ArrowUp className="w-4 h-4" />
                  )}
                </button>
              )}
              </div>
            </div>
            {(continueMutation.isError || uploadError) && (
              <p className="mt-2 text-xs text-red-600 text-center">
                {continueMutation.error?.message || uploadError}
              </p>
            )}
          </div>
        </div>
      )}
    </div>
    {showContinueDialog && (
      <ContinueDialog
        sessionId={sessionId}
        onClose={() => setShowContinueDialog(false)}
      />
    )}
    </ProjectRepoContext.Provider>
  )
}

export default SessionDetail
