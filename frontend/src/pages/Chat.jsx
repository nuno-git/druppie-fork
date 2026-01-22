/**
 * Chat Page - Main interface for Druppie governance
 * Shows workflow events and conversation history sidebar
 */

import React, { useState, useRef, useEffect } from 'react'
import { useSearchParams, useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Send, Bug, FolderOpen, ExternalLink } from 'lucide-react'
import { sendChat, getSessions, getPlan, answerQuestion, approveTask, rejectTask, submitHITLResponse, getProject, cancelChat } from '../services/api'
import { useAuth } from '../App'
import {
  initSocket,
  joinPlanRoom,
  joinApprovalsRoom,
  onTaskApproved,
  onTaskRejected,
  onWorkflowEvent,
  onHITLQuestion,
  onApprovalRequired,
  onHITLProgress,
  onExecutionCancelled,
  disconnectSocket,
} from '../services/socket'
import { useToast } from '../components/Toast'
import { formatEventTitle } from '../utils/eventUtils'
import {
  Message,
  TypingIndicator,
  ConversationSidebar,
  DebugPanel,
} from '../components/chat'

const Chat = () => {
  const { user } = useAuth()
  const toast = useToast()
  const [searchParams, setSearchParams] = useSearchParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const messagesEndRef = useRef(null)

  // State
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [currentPlanId, setCurrentPlanId] = useState(null)
  const [currentStep, setCurrentStep] = useState(null)
  const [debugPanelOpen, setDebugPanelOpen] = useState(false)
  const [apiCalls, setApiCalls] = useState([])
  const [liveWorkflowEvents, setLiveWorkflowEvents] = useState([])
  const [debugWorkflowEvents, setDebugWorkflowEvents] = useState([])
  const [debugLLMCalls, setDebugLLMCalls] = useState([])
  const [workspaceInfo, setWorkspaceInfo] = useState(null)
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
  const [initialSessionLoaded, setInitialSessionLoaded] = useState(false)
  const [currentProject, setCurrentProject] = useState(null)
  const [isStopping, setIsStopping] = useState(false)

  // Fetch session history
  const { data: sessionsData } = useQuery({
    queryKey: ['sessions'],
    queryFn: () => getSessions(1, 20),
    refetchInterval: 30000,
  })

  // Load session from URL parameter on initial load
  useEffect(() => {
    if (initialSessionLoaded) return
    const sessionIdFromUrl = searchParams.get('session')
    if (!sessionIdFromUrl) {
      setInitialSessionLoaded(true)
      return
    }

    const loadSessionFromUrl = async () => {
      try {
        const fullSession = await getPlan(sessionIdFromUrl)
        if (fullSession) {
          setCurrentPlanId(sessionIdFromUrl)
          setInitialSessionLoaded(true)
          loadSessionData(fullSession, sessionIdFromUrl)
        }
      } catch (err) {
        console.error('Error loading session from URL:', err)
        setInitialSessionLoaded(true)
      }
    }
    loadSessionFromUrl()
  }, [searchParams, initialSessionLoaded])

  // Initialize with welcome message
  useEffect(() => {
    if (messages.length === 0 && !currentPlanId) {
      setMessages([{
        role: 'assistant',
        content: `Hello ${user?.firstName || user?.username}! I'm Druppie, your AI governance assistant.\n\nI can help you:\n• Create applications (just describe what you want!)\n• Manage code deployments\n• Check compliance and permissions\n\nWhat would you like to build today?`,
      }])
    }
  }, [user, currentPlanId])

  // WebSocket setup
  useEffect(() => {
    if (!user?.roles) return
    initSocket()
    joinApprovalsRoom(user.roles)
    return () => disconnectSocket()
  }, [user?.roles])

  useEffect(() => {
    if (currentPlanId) joinPlanRoom(currentPlanId)
  }, [currentPlanId])

  // Workflow event listener
  useEffect(() => {
    const handleWorkflowEvent = (data) => {
      const eventSessionId = data.session_id || data.plan_id
      if (eventSessionId && currentPlanId && eventSessionId !== currentPlanId) return

      const event = data.event
      if (!event) return

      const stepTitle = event.title || event.data?.description || formatEventTitle(event)
      if (stepTitle) setCurrentStep(stepTitle)

      const formattedEvent = {
        ...event,
        event_type: event.type,
        title: stepTitle,
        description: event.data?.description || event.description,
        status: event.status || (event.type?.includes('completed') || event.type?.includes('success') ? 'success' : 'working'),
        data: event.data || event,
      }
      setLiveWorkflowEvents((prev) => [...prev, formattedEvent])
    }

    const unsubscribe = onWorkflowEvent(handleWorkflowEvent)
    return () => unsubscribe()
  }, [currentPlanId])

  // Approval event listeners
  useEffect(() => {
    const handleTaskApproved = (task) => {
      const approvals = task.approvals || []
      const latestApproval = approvals[approvals.length - 1]
      const approverId = latestApproval?.approved_by || latestApproval?.approver_id

      if (approverId && approverId !== user?.id) {
        if (task.status === 'approved') {
          toast.success('Task Fully Approved', `"${task.name}" has been approved and will now execute.`)
        } else {
          toast.info('New Approval Received', `A ${latestApproval?.approver_role || 'user'} has approved "${task.name}".`)
        }
      }

      setMessages((prev) => prev.map((msg) => {
        if (!msg.pendingApprovals) return msg
        const updatedApprovals = msg.pendingApprovals.map((approval) => {
          if (approval.task_id === task.id) {
            const approvedApprovals = approvals.filter(a => a.decision === 'approved')
            return {
              ...approval,
              current_approvals: approvedApprovals.length,
              approved_by_roles: approvedApprovals.map(a => a.approver_role || a.role).filter(Boolean),
              approved_by_ids: approvedApprovals.map(a => a.approved_by || a.approver_id).filter(Boolean),
              status: task.status,
            }
          }
          return approval
        })
        return { ...msg, pendingApprovals: updatedApprovals.filter(a => a.status !== 'approved' && a.status !== 'rejected') }
      }))
      queryClient.invalidateQueries({ queryKey: ['sessions'] })
    }

    const handleTaskRejected = (task) => {
      const rejectionApproval = (task.approvals || []).find(a => a.decision === 'rejected')
      const rejectorId = rejectionApproval?.approved_by || rejectionApproval?.approver_id

      if (rejectorId && rejectorId !== user?.id) {
        toast.warning('Task Rejected', `"${task.name}" has been rejected.`)
      }

      setMessages((prev) => prev.map((msg) => {
        if (!msg.pendingApprovals) return msg
        return { ...msg, pendingApprovals: msg.pendingApprovals.filter(a => a.task_id !== task.id) }
      }))
      queryClient.invalidateQueries({ queryKey: ['sessions'] })
    }

    const unsubApproved = onTaskApproved(handleTaskApproved)
    const unsubRejected = onTaskRejected(handleTaskRejected)
    return () => { unsubApproved(); unsubRejected() }
  }, [queryClient, user?.id, toast])

  // Execution cancelled listener
  useEffect(() => {
    const handleExecutionCancelled = (data) => {
      const sessionId = data.session_id
      if (sessionId && currentPlanId && sessionId !== currentPlanId) return

      toast.info('Execution Cancelled', data.message || 'The execution was stopped.')
      setCurrentStep(null)
      setIsStopping(false)
    }

    const unsub = onExecutionCancelled(handleExecutionCancelled)
    return () => unsub()
  }, [currentPlanId, toast])

  // HITL event listeners
  useEffect(() => {
    const handleHITLQuestion = (data) => {
      const questionData = {
        id: data.request_id,
        question: data.question,
        input_type: data.input_type,
        choices: data.choices || [],
        allow_other: data.allow_other !== false,
        context: data.context,
        session_id: data.session_id || currentPlanId,
      }

      setMessages((prev) => {
        const lastMsg = prev[prev.length - 1]
        if (lastMsg && lastMsg.role !== 'user') {
          return prev.map((msg, idx) => idx === prev.length - 1
            ? { ...msg, pendingQuestions: [...(msg.pendingQuestions || []), questionData] }
            : msg
          )
        }
        return [...prev, { role: 'assistant', content: '', pendingQuestions: [questionData], timestamp: new Date().toISOString() }]
      })
      toast.info('Question from Agent', data.question)
    }

    const handleApprovalRequired = (data) => {
      const approvalData = {
        task_id: data.approval_id,
        task_name: `${data.tool}`,
        mcp_tool: data.tool,
        required_roles: data.required_roles || ['developer'],
        approval_type: data.required_roles?.length > 1 ? 'multi' : 'self',
        current_approvals: 0,
        required_approvals: 1,
        approved_by_roles: [],
        approved_by_ids: [],
        args: data.args,
      }

      setMessages((prev) => {
        const lastMsg = prev[prev.length - 1]
        if (lastMsg && lastMsg.role !== 'user') {
          return prev.map((msg, idx) => idx === prev.length - 1
            ? { ...msg, pendingApprovals: [...(msg.pendingApprovals || []), approvalData] }
            : msg
          )
        }
        return [...prev, { role: 'assistant', content: `I need approval to run: ${data.tool}`, pendingApprovals: [approvalData], timestamp: new Date().toISOString() }]
      })
      toast.warning('Approval Required', `Agent wants to run: ${data.tool}`)
    }

    const handleHITLProgress = (data) => {
      setLiveWorkflowEvents((prev) => [...prev, {
        event_type: 'progress',
        title: data.step || 'Progress Update',
        description: data.message,
        status: 'working',
        data: { percent: data.percent },
      }])
    }

    const unsubQuestion = onHITLQuestion(handleHITLQuestion)
    const unsubApproval = onApprovalRequired(handleApprovalRequired)
    const unsubProgress = onHITLProgress(handleHITLProgress)
    return () => { unsubQuestion(); unsubApproval(); unsubProgress() }
  }, [currentPlanId, toast])

  // Auto-scroll
  const scrollToBottom = () => messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  useEffect(() => { scrollToBottom() }, [messages])

  // Helper to load session data
  const loadSessionData = async (fullSession, sessionId) => {
    if (fullSession.project) {
      setCurrentProject(fullSession.project)
    } else if (fullSession.project_id) {
      try {
        const projectInfo = await getProject(fullSession.project_id)
        setCurrentProject(projectInfo)
      } catch { setCurrentProject(null) }
    } else {
      setCurrentProject(null)
    }

    const workflowEvents = fullSession.result?.workflow_events || []
    const llmCalls = fullSession.result?.llm_calls || []
    const normalizedEvents = workflowEvents.map(event => ({
      ...event,
      event_type: event.type || event.event_type,
      title: event.title || formatEventTitle({ ...event, event_type: event.type }),
      description: event.data?.description || event.description || '',
      status: event.status || 'info',
      data: event.data || event,
    }))
    setDebugWorkflowEvents(normalizedEvents)
    setDebugLLMCalls(llmCalls)
    setApiCalls(llmCalls.map(call => ({ type: 'llm', ...call })))

    let pendingApprovals = []
    if (fullSession.tasks) {
      pendingApprovals = fullSession.tasks
        .filter(task => task.status === 'pending_approval')
        .map(task => ({
          task_id: task.id,
          task_name: task.name,
          mcp_tool: task.mcp_tool,
          required_role: task.required_role,
          approval_type: task.approval_type,
          required_roles: task.required_roles,
          required_approvals: task.required_approvals || 1,
          current_approvals: task.approvals?.filter(a => a.decision === 'approved').length || 0,
          approved_by_roles: task.approvals?.filter(a => a.decision === 'approved').map(a => a.role) || [],
          approved_by_ids: task.approvals?.filter(a => a.decision === 'approved').map(a => a.approved_by || a.approver_id) || [],
        }))
    }

    // Check if session has stored messages (new format)
    if (fullSession.messages && fullSession.messages.length > 0) {
      // Use stored messages directly - they contain full conversation history with per-message events
      const loadedMessages = fullSession.messages.map((msg, idx) => {
        const isLastAssistant = idx === fullSession.messages.length - 1 && msg.role === 'assistant'

        // Use per-message workflow events if available, otherwise fall back to session-level events for last message
        const msgWorkflowEvents = msg.workflow_events || msg.workflowEvents || []
        const msgLlmCalls = msg.llm_calls || msg.llmCalls || []

        // Normalize workflow events
        const normalizedMsgEvents = msgWorkflowEvents.map(event => ({
          ...event,
          event_type: event.type || event.event_type,
          title: event.title || formatEventTitle({ ...event, event_type: event.type }),
          description: event.data?.description || event.description || '',
          status: event.status || 'info',
          data: event.data || event,
        }))

        return {
          role: msg.role,
          content: msg.content,
          timestamp: msg.timestamp,
          // Attach per-message workflow events
          ...(msg.role === 'assistant' && {
            workflowEvents: normalizedMsgEvents.length > 0 ? normalizedMsgEvents : (isLastAssistant ? normalizedEvents : []),
            llmCalls: msgLlmCalls,
          }),
          // Attach approvals to last assistant message
          ...(isLastAssistant && {
            planId: sessionId,
            status: fullSession.status,
            pendingApprovals,
          }),
        }
      })
      setMessages(loadedMessages)
    } else {
      // Fallback: Reconstruct from legacy format (description + result.response)
      const reconstructedMessages = []
      const userMessage = fullSession.description || fullSession.preview
      if (userMessage) reconstructedMessages.push({ role: 'user', content: userMessage })
      reconstructedMessages.push({
        role: 'assistant',
        content: fullSession.result?.response || `Session - Status: ${fullSession.status}`,
        planId: sessionId,
        status: fullSession.status,
        workflowEvents,
        pendingApprovals,
      })
      setMessages(reconstructedMessages.length > 0 ? reconstructedMessages : [{ role: 'assistant', content: 'Continuing conversation...', planId: sessionId }])
    }
  }

  // Chat mutation
  const chatMutation = useMutation({
    mutationFn: async ({ message, conversationHistory, sessionId }) => {
      const startTime = Date.now()
      const effectiveSessionId = sessionId || currentPlanId
      const requestData = { message, session_id: effectiveSessionId, conversation_history: conversationHistory.length > 0 ? conversationHistory : null }

      try {
        const response = await sendChat(message, effectiveSessionId, requestData.conversation_history)
        setApiCalls((prev) => [...prev, { type: 'api', method: 'POST', endpoint: '/api/chat', timestamp: new Date().toISOString(), duration: Date.now() - startTime, status: 'success', request: requestData }, ...(response.llm_calls || []).map(call => ({ type: 'llm', ...call }))])
        return response
      } catch (error) {
        setApiCalls((prev) => [...prev, { type: 'api', method: 'POST', endpoint: '/api/chat', timestamp: new Date().toISOString(), duration: Date.now() - startTime, status: 'error', request: requestData, response: { error: error.message } }])
        throw error
      }
    },
    onSuccess: (data) => {
      const normalizedEvents = (data.workflow_events || []).map(event => ({
        ...event,
        event_type: event.type || event.event_type,
        title: event.title || formatEventTitle({ ...event, event_type: event.type }),
        description: event.data?.description || event.description || '',
        status: event.status || (event.type?.includes('completed') || event.type?.includes('success') ? 'success' : 'info'),
        data: event.data || event,
      }))

      setMessages((prev) => [...prev, {
        role: 'assistant',
        content: data.response,
        planId: data.plan_id,
        pendingApprovals: data.pending_approvals,
        pendingQuestions: data.pending_questions || [],
        status: data.status,
        workflowEvents: normalizedEvents,
        timestamp: new Date().toISOString(),
      }])
      setCurrentPlanId(data.plan_id)
      setCurrentStep(null)
      setDebugWorkflowEvents([...liveWorkflowEvents, ...normalizedEvents])
      setDebugLLMCalls(data.llm_calls || [])
      setLiveWorkflowEvents([])

      // Update URL with session ID for persistence
      if (data.plan_id) {
        setSearchParams({ session: data.plan_id })
      }

      if (data.workspace_id || data.project_id || data.branch) {
        setWorkspaceInfo({ workspace_id: data.workspace_id, project_id: data.project_id, branch: data.branch, workspace_path: data.workspace_path })
      }

      // Set current project with friendly name from response
      if (data.project_id) {
        // Use the friendly project_name from the response if available
        // This provides immediate feedback without waiting for API call
        if (data.project_name) {
          setCurrentProject({
            id: data.project_id,
            name: data.project_name,
          })
        } else {
          // Fallback: fetch project details from API
          getProject(data.project_id)
            .then(projectInfo => setCurrentProject(projectInfo))
            .catch(() => setCurrentProject({ id: data.project_id, name: 'Project' }))
        }
      }

      queryClient.invalidateQueries({ queryKey: ['projects'] })
      queryClient.invalidateQueries({ queryKey: ['sessions'] })
    },
    onError: (error) => {
      setMessages((prev) => [...prev, { role: 'assistant', content: `Error: ${error.message}` }])
      setCurrentStep(null)
      setDebugWorkflowEvents([...liveWorkflowEvents])
      setLiveWorkflowEvents([])
    },
  })

  // Approve/reject mutations
  const approveMutation = useMutation({
    mutationFn: (taskId) => approveTask(taskId),
    onSuccess: (data, taskId) => {
      const isFullyApproved = !data.approvals_required || data.approvals_received >= data.approvals_required
      setMessages((prev) => prev.map(msg => msg.pendingApprovals ? { ...msg, pendingApprovals: msg.pendingApprovals.filter(a => a.task_id !== taskId) } : msg))
      setMessages((prev) => [...prev, { role: 'assistant', content: isFullyApproved ? '✅ Task fully approved! The action will now proceed.' : `✅ Your approval has been recorded (${data.approvals_received}/${data.approvals_required}). Waiting for more approvals.` }])
      queryClient.invalidateQueries({ queryKey: ['tasks'] })
      queryClient.invalidateQueries({ queryKey: ['sessions'] })
    },
    onError: (error) => { setMessages((prev) => [...prev, { role: 'assistant', content: `❌ Error approving task: ${error.message}` }]) },
  })

  const rejectMutation = useMutation({
    mutationFn: ({ taskId, reason }) => rejectTask(taskId, reason),
    onSuccess: (data, { taskId }) => {
      setMessages((prev) => prev.map(msg => msg.pendingApprovals ? { ...msg, pendingApprovals: msg.pendingApprovals.filter(a => a.task_id !== taskId) } : msg))
      setMessages((prev) => [...prev, { role: 'assistant', content: '🚫 Task rejected. The action has been cancelled.' }])
      queryClient.invalidateQueries({ queryKey: ['tasks'] })
      queryClient.invalidateQueries({ queryKey: ['sessions'] })
    },
    onError: (error) => { setMessages((prev) => [...prev, { role: 'assistant', content: `❌ Error rejecting task: ${error.message}` }]) },
  })

  // Answer mutation
  const answerMutation = useMutation({
    mutationFn: ({ questionId, answer }) => answerQuestion(questionId, answer),
    onSuccess: (data) => {
      if (data.status === 'answered_and_continued' && data.response) {
        setMessages((prev) => [...prev, { role: 'assistant', content: data.response, planId: data.plan_id, pendingApprovals: data.pending_approvals, pendingQuestions: data.pending_questions || [], workflowEvents: data.workflow_events || [] }])
        if (data.llm_calls?.length > 0) setApiCalls((prev) => [...prev, ...data.llm_calls.map(call => ({ type: 'llm', ...call }))])
      }
      queryClient.invalidateQueries({ queryKey: ['questions'] })
      queryClient.invalidateQueries({ queryKey: ['sessions'] })
      setCurrentStep(null)
    },
    onError: (error, variables) => {
      setMessages((prev) => [...prev.filter(msg => msg.role !== 'user' || msg.content !== variables.answer), { role: 'assistant', content: `Error answering question: ${error.message}` }])
      setCurrentStep(null)
    },
  })

  // Handlers
  const handleApproveTask = (taskId) => approveMutation.mutate(taskId)
  const handleRejectTask = (taskId, reason) => rejectMutation.mutate({ taskId, reason })

  const handleAnswerQuestion = async (questionId, answer, selected = null) => {
    setMessages((prev) => {
      const updated = prev.map(msg => msg.pendingQuestions ? { ...msg, pendingQuestions: msg.pendingQuestions.filter(q => q.id !== questionId) } : msg)
      return [...updated, { role: 'user', content: selected || answer }]
    })
    setCurrentStep('Processing your answer...')
    setLiveWorkflowEvents([])
    setDebugWorkflowEvents([])
    setDebugLLMCalls([])

    const isHITLRequest = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(questionId)
    if (isHITLRequest) {
      try { await submitHITLResponse(questionId, answer, selected); setCurrentStep(null) }
      catch { toast.error('Error', 'Failed to submit answer'); setCurrentStep(null) }
    } else {
      answerMutation.mutate({ questionId, answer })
    }
  }

  const handleSubmit = (e) => {
    e.preventDefault()
    if (!input.trim() || chatMutation.isPending) return

    const userMessage = input.trim()
    setInput('')
    setCurrentStep('Processing your request...')
    setLiveWorkflowEvents([])
    setDebugWorkflowEvents([])
    setDebugLLMCalls([])

    const sessionId = currentPlanId || crypto.randomUUID()
    joinPlanRoom(sessionId)
    if (!currentPlanId) setCurrentPlanId(sessionId)

    // Build conversation history from all messages (excluding welcome message)
    const conversationHistory = messages
      .filter((msg, idx) => idx > 0)  // Skip welcome message
      .map((msg) => ({
        role: msg.role,
        content: msg.content?.substring(0, 1000),  // Increased limit for better context
      }))

    setMessages((prev) => [...prev, { role: 'user', content: userMessage, timestamp: new Date().toISOString() }])
    chatMutation.mutate({ message: userMessage, conversationHistory, sessionId })
  }

  const handleNewChat = () => {
    setCurrentPlanId(null)
    setApiCalls([])
    setLiveWorkflowEvents([])
    setDebugWorkflowEvents([])
    setDebugLLMCalls([])
    setWorkspaceInfo(null)
    setCurrentProject(null)
    setSearchParams({})
    setMessages([{ role: 'assistant', content: `Hello ${user?.firstName || user?.username}! I'm Druppie, your AI governance assistant.\n\nI can help you:\n• Create applications (just describe what you want!)\n• Manage code deployments\n• Check compliance and permissions\n\nWhat would you like to build today?` }])
  }

  const handleSelectPlan = async (session) => {
    setCurrentPlanId(session.id)
    setLiveWorkflowEvents([])
    setSearchParams({ session: session.id })
    try {
      const fullSession = await getPlan(session.id)
      await loadSessionData(fullSession, session.id)
    } catch (err) {
      console.error('Error loading session:', err)
      setCurrentProject(null)
    }
  }

  const handleDebugSession = (sessionId) => {
    const session = sessionsData?.sessions?.find(s => s.id === sessionId)
    if (session) {
      handleSelectPlan(session)
      setTimeout(() => setDebugPanelOpen(true), 100)
    }
  }

  // Handle stop/cancel execution
  const handleStopExecution = async () => {
    if (!currentPlanId || isStopping) return

    setIsStopping(true)
    try {
      const result = await cancelChat(currentPlanId)
      if (result.cancelled) {
        toast.info('Execution Stopped', 'The execution has been cancelled.')
        setCurrentStep(null)
        setMessages((prev) => [
          ...prev,
          {
            role: 'assistant',
            content: 'Execution was stopped by user.',
            timestamp: new Date().toISOString(),
          },
        ])
      } else {
        toast.warning('Could Not Stop', result.reason || 'No active execution to cancel.')
      }
    } catch (error) {
      console.error('Error stopping execution:', error)
      toast.error('Error', 'Failed to stop execution.')
    } finally {
      setIsStopping(false)
    }
  }

  const suggestions = ['Create a todo app with Flask', 'Build a simple calculator', 'Make a notes app with React', 'Create a weather dashboard']

  return (
    <div className="flex h-[calc(100vh-10rem)] -mx-4 sm:-mx-6 lg:-mx-8">
      <ConversationSidebar
        sessions={sessionsData}
        activeSessionId={currentPlanId}
        onSelectSession={handleSelectPlan}
        onNewChat={handleNewChat}
        onDebugSession={handleDebugSession}
        isCollapsed={sidebarCollapsed}
        onToggleCollapse={() => setSidebarCollapsed(!sidebarCollapsed)}
      />

      <div className="flex-1 flex flex-col bg-gray-50">
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-2 border-b border-gray-200 bg-white">
          <div className="flex items-center gap-4">
            <div className="text-sm text-gray-600">
              {currentPlanId ? (
                <span className="flex items-center gap-2">
                  <span className="w-2 h-2 rounded-full bg-green-500"></span>
                  Active Conversation
                </span>
              ) : <span>New Conversation</span>}
            </div>
            {currentProject && (
              <div className="flex items-center gap-2 px-3 py-1.5 bg-purple-50 rounded-lg border border-purple-200">
                <FolderOpen className="w-4 h-4 text-purple-600" />
                <span className="text-sm font-medium text-purple-900">{currentProject.name}</span>
                <button onClick={() => navigate(`/projects/${currentProject.id}`)} className="ml-1 flex items-center gap-1 text-xs text-purple-600 hover:text-purple-800 hover:underline focus:outline-none focus:ring-2 focus:ring-purple-500 rounded">
                  <ExternalLink className="w-3 h-3" />View Project
                </button>
              </div>
            )}
          </div>
          <button onClick={() => setDebugPanelOpen(true)} className="flex items-center gap-2 px-3 py-1.5 text-sm text-gray-600 hover:text-gray-800 hover:bg-gray-100 rounded-lg transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500">
            <Bug className="w-4 h-4" />Debug
            {apiCalls.length > 0 && <span className="bg-orange-100 text-orange-700 text-xs px-1.5 py-0.5 rounded-full">{apiCalls.length}</span>}
          </button>
        </div>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto p-4 space-y-2">
          {messages.map((message, index) => (
            <Message
              key={index}
              message={message}
              onAnswerQuestion={handleAnswerQuestion}
              isAnsweringQuestion={answerMutation.isPending}
              onApproveTask={handleApproveTask}
              onRejectTask={handleRejectTask}
              isApprovingTask={approveMutation.isPending || rejectMutation.isPending}
              currentUserId={user?.id}
            />
          ))}
          {chatMutation.isPending && (
            <TypingIndicator
              currentStep={currentStep}
              liveEvents={liveWorkflowEvents}
              onStop={handleStopExecution}
              isStopping={isStopping}
            />
          )}
          <div ref={messagesEndRef} />
        </div>

        {/* Suggestions */}
        {messages.length <= 1 && !currentPlanId && (
          <div className="px-4 pb-4">
            <p className="text-sm text-gray-500 mb-2">Try one of these:</p>
            <div className="flex flex-wrap gap-2">
              {suggestions.map((suggestion, index) => (
                <button key={index} onClick={() => setInput(suggestion)} className="px-3 py-1.5 bg-white hover:bg-gray-100 rounded-full text-sm text-gray-700 transition-colors border border-gray-200 shadow-sm">
                  {suggestion}
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Input */}
        <form onSubmit={handleSubmit} className="p-4 border-t border-gray-200 bg-white">
          <div className="flex space-x-3">
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Describe what you want to build..."
              className="flex-1 px-4 py-3 border border-gray-300 rounded-xl focus:ring-2 focus:ring-blue-500 focus:border-transparent transition-all"
              disabled={chatMutation.isPending}
            />
            <button
              type="submit"
              disabled={!input.trim() || chatMutation.isPending}
              className="px-6 py-3 bg-gradient-to-r from-blue-600 to-purple-600 text-white rounded-xl hover:from-blue-700 hover:to-purple-700 disabled:opacity-50 disabled:cursor-not-allowed transition-all shadow-md hover:shadow-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2"
            >
              <Send className="w-5 h-5" />
            </button>
          </div>
        </form>
      </div>

      <DebugPanel
        isOpen={debugPanelOpen}
        onClose={() => setDebugPanelOpen(false)}
        apiCalls={apiCalls}
        workflowEvents={liveWorkflowEvents.length > 0 ? liveWorkflowEvents : debugWorkflowEvents}
        llmCalls={debugLLMCalls}
        workspaceInfo={workspaceInfo}
        messages={messages}
      />
    </div>
  )
}

export default Chat
