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
  onDeploymentComplete,
  disconnectSocket,
} from '../services/socket'
import { useToast } from '../components/Toast'
import { formatEventTitle } from '../utils/eventUtils'
import {
  Message,
  HITLQuestionMessage,
  TypingIndicator,
  ConversationSidebar,
  DebugPanel,
  ApprovalCard,
  ToolDecisionCard,
  WorkflowEventMessage,
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
  const [sessionPendingApprovals, setSessionPendingApprovals] = useState([]) // Session-level approvals not attached to messages
  const [isAgentWorking, setIsAgentWorking] = useState(false) // For showing typing indicator after approval
  const [currentAgentId, setCurrentAgentId] = useState(null) // Track which agent is currently working
  const [toolExecutions, setToolExecutions] = useState([]) // Track tool executions with approval status
  const [workflowEventsForDisplay, setWorkflowEventsForDisplay] = useState([]) // Workflow events to render as messages

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

  // Workflow event listener - simplified to just trigger refetch and update UI state
  useEffect(() => {
    const handleWorkflowEvent = (data) => {
      const eventSessionId = data.session_id || data.plan_id
      if (eventSessionId && currentPlanId && eventSessionId !== currentPlanId) return

      const event = data.event
      if (!event) return

      const eventType = event.type || event.event_type || ''

      // Update agent working state based on event type
      if (eventType === 'agent_started' || eventType.includes('_started')) {
        const agentId = event.data?.agent_id || event.agent_id
        setIsAgentWorking(true)
        if (agentId) setCurrentAgentId(agentId)
        setCurrentStep(`${agentId || 'Agent'} is working...`)
      }

      // Check if workflow is complete or failed - stop the working indicator and refetch
      if (eventType.includes('workflow_completed') || eventType.includes('workflow_failed') ||
          eventType.includes('session_completed') || eventType.includes('session_failed') ||
          eventType.includes('execution_complete') || eventType.includes('execution_failed')) {
        setIsAgentWorking(false)
        setCurrentStep(null)
        setCurrentAgentId(null)
        // Refetch session data to get the final state
        if (currentPlanId) {
          getPlan(currentPlanId).then(fullSession => loadSessionData(fullSession, currentPlanId))
        }
      }

      // Agent completed - refetch to update the UI
      if (eventType === 'agent_completed' || eventType.includes('_completed')) {
        const agentId = event.data?.agent_id || event.agent_id
        if (agentId === 'deployer') {
          setIsAgentWorking(false)
          setCurrentStep(null)
        }
        // Refetch to show the latest tool calls
        if (currentPlanId) {
          getPlan(currentPlanId).then(fullSession => loadSessionData(fullSession, currentPlanId))
        }
      }

      // Tool approval required - stop indicator and refetch
      if (eventType.includes('approval_required') || eventType.includes('approval_pending')) {
        setIsAgentWorking(false)
        setCurrentStep(null)
        if (currentPlanId) {
          getPlan(currentPlanId).then(fullSession => loadSessionData(fullSession, currentPlanId))
        }
      }

      // For live events during execution, just add to the live list for typing indicator
      setLiveWorkflowEvents((prev) => [...prev, {
        ...event,
        event_type: event.type,
        timestamp: event.timestamp || new Date().toISOString(),
      }])
    }

    const unsubscribe = onWorkflowEvent(handleWorkflowEvent)
    return () => unsubscribe()
  }, [currentPlanId])

  // Approval event listeners - simplified to refetch session data
  useEffect(() => {
    const handleTaskApproved = (data) => {
      const approverId = data.approver_id
      const approverUsername = data.approver_username || data.approver_role || 'User'
      const approverRole = data.approver_role || 'user'
      const toolName = data.tool_name || data.name || 'action'
      const agentId = data.agent_id

      // Only show notification if it's from another user
      if (approverId && approverId !== user?.id) {
        toast.success('Task Approved', `${approverUsername} (${approverRole}) approved: ${toolName}`)
        // Show typing indicator since agent is now working
        setCurrentStep(`${agentId || 'Agent'} is continuing execution...`)
        setCurrentAgentId(agentId || 'developer')
        setIsAgentWorking(true)
      }

      // Refetch session to get updated state
      if (currentPlanId) {
        getPlan(currentPlanId).then(fullSession => loadSessionData(fullSession, currentPlanId))
      }
      queryClient.invalidateQueries({ queryKey: ['sessions'] })
      queryClient.invalidateQueries({ queryKey: ['tasks'] })
    }

    const handleTaskRejected = (data) => {
      const rejectorId = data.approver_id
      const rejectorUsername = data.approver_username || data.approver_role || 'User'
      const rejectorRole = data.approver_role || 'user'
      const toolName = data.tool_name || data.name || 'action'

      // Only show notification if it's from another user
      if (rejectorId && rejectorId !== user?.id) {
        toast.warning('Task Rejected', `${rejectorUsername} (${rejectorRole}) rejected: ${toolName}`)
      }

      // Refetch session to get updated state
      if (currentPlanId) {
        getPlan(currentPlanId).then(fullSession => loadSessionData(fullSession, currentPlanId))
      }
      queryClient.invalidateQueries({ queryKey: ['sessions'] })
      queryClient.invalidateQueries({ queryKey: ['tasks'] })
    }

    const unsubApproved = onTaskApproved(handleTaskApproved)
    const unsubRejected = onTaskRejected(handleTaskRejected)
    return () => { unsubApproved(); unsubRejected() }
  }, [queryClient, user?.id, toast, currentPlanId])

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

  // HITL event listeners - simplified to refetch session data
  useEffect(() => {
    const handleHITLQuestion = (data) => {
      const eventSessionId = data.session_id
      if (eventSessionId && currentPlanId && eventSessionId !== currentPlanId) return

      // Stop showing typing indicator when waiting for user input
      setIsAgentWorking(false)
      setCurrentStep(null)

      const agentName = data.agent_id ? data.agent_id.charAt(0).toUpperCase() + data.agent_id.slice(1) : 'Agent'
      toast.info(`Question from ${agentName}`, data.question?.substring(0, 80) + (data.question?.length > 80 ? '...' : ''))

      // Refetch session to get the question
      if (currentPlanId) {
        getPlan(currentPlanId).then(fullSession => loadSessionData(fullSession, currentPlanId))
      }
    }

    const handleApprovalRequired = (data) => {
      const eventSessionId = data.session_id
      if (eventSessionId && currentPlanId && eventSessionId !== currentPlanId) return

      // Stop showing typing indicator when waiting for approval
      setIsAgentWorking(false)
      setCurrentStep(null)

      const taskName = data.tool || data.message || 'Approval Required'
      toast.warning('Approval Required', taskName)

      // Refetch session to get the approval
      if (currentPlanId) {
        getPlan(currentPlanId).then(fullSession => loadSessionData(fullSession, currentPlanId))
      }
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

  // Deployment complete listener - simplified to refetch and show toast
  useEffect(() => {
    const handleDeploymentComplete = (data) => {
      const sessionId = data.session_id
      if (sessionId && currentPlanId && sessionId !== currentPlanId) return

      const url = data.url
      toast.success('Deployment Successful!', `Your app is running at ${url}`)

      // Refetch session to get the final state with deployment info
      if (currentPlanId) {
        getPlan(currentPlanId).then(fullSession => loadSessionData(fullSession, currentPlanId))
      }
    }

    const unsub = onDeploymentComplete(handleDeploymentComplete)
    return () => unsub()
  }, [currentPlanId, toast])

  // Auto-scroll
  const scrollToBottom = () => messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  useEffect(() => { scrollToBottom() }, [messages])

  // Helper to load session data
  const loadSessionData = async (fullSession, sessionId) => {
    let projectInfo = null
    if (fullSession.project) {
      projectInfo = fullSession.project
      setCurrentProject(fullSession.project)
    } else if (fullSession.project_id) {
      try {
        projectInfo = await getProject(fullSession.project_id)
        setCurrentProject(projectInfo)
      } catch { setCurrentProject(null) }
    } else {
      setCurrentProject(null)
    }

    // Use the new nested agent_runs structure directly from session data
    // Each agent_run now contains: llm_calls, tool_calls, approvals, hitl_questions
    const agentRuns = fullSession.agent_runs || []

    // Flatten all LLM calls from agent runs for debug panel
    const llmCalls = agentRuns.flatMap(run =>
      (run.llm_calls || []).map(call => ({
        agent_id: run.agent_id,
        model: call.model,
        provider: call.provider,
        duration_ms: call.duration_ms,
        usage: call.token_usage,
        timestamp: call.created_at,
        response: call.response_content,
      }))
    )

    // Build unified timeline from agent runs using the enhanced nested structure
    // The backend now returns response_tool_calls with embedded approval/HITL/execution data
    const timelineItems = []
    const knownAgents = ['router', 'planner', 'architect', 'developer', 'deployer', 'reviewer', 'tester']

    for (const run of agentRuns) {
      // Add agent_started event
      if (knownAgents.includes(run.agent_id)) {
        timelineItems.push({
          id: `${run.id}-start`,
          type: 'agent_started',
          agent_id: run.agent_id,
          timestamp: run.started_at,
        })
      }

      // Process each LLM call's tool decisions
      for (const llmCall of (run.llm_calls || [])) {
        for (const toolDecision of (llmCall.response_tool_calls || [])) {
          // Skip internal tools like hitl_progress
          if (toolDecision.name === 'hitl_progress') continue

          // Each toolDecision now has all embedded data from the backend
          timelineItems.push({
            id: toolDecision.id || `${llmCall.id}-${toolDecision.name}`,
            type: 'tool_decision',
            agent_id: run.agent_id,
            timestamp: llmCall.created_at,
            // The full tool decision with embedded data
            toolDecision: toolDecision,
          })
        }
      }

      // Add agent_completed event
      if (run.status === 'completed' && knownAgents.includes(run.agent_id)) {
        const lastLlmCall = (run.llm_calls || []).slice(-1)[0]
        const doneCall = lastLlmCall?.response_tool_calls?.find(tc => tc.is_done_tool || tc.name === 'done')

        timelineItems.push({
          id: `${run.id}-complete`,
          type: 'agent_completed',
          agent_id: run.agent_id,
          timestamp: run.completed_at || run.started_at,
          summary: doneCall?.arguments?.summary,
        })
      }
    }

    // Sort by timestamp
    timelineItems.sort((a, b) => {
      const timeA = a.timestamp ? new Date(a.timestamp).getTime() : 0
      const timeB = b.timestamp ? new Date(b.timestamp).getTime() : 0
      return timeA - timeB
    })

    setDebugWorkflowEvents(timelineItems)
    setDebugLLMCalls(llmCalls)
    setApiCalls(llmCalls.map(call => ({ type: 'llm', ...call })))
    setWorkflowEventsForDisplay(timelineItems)
    console.log('[Chat] Loaded timeline items:', timelineItems.length)

    // Session-level approvals for non-tool_call types (workflow_step approvals)
    // Extract from agent_runs since approvals are now embedded (not at top level)
    const allApprovals = agentRuns.flatMap(run => run.approvals || [])
    const pendingApprovals = allApprovals
      .filter(a => a.status === 'pending' && a.approval_type !== 'tool_call')
      .map(a => ({
        task_id: a.id,
        task_name: a.title || a.tool_name || 'Approval Required',
        mcp_tool: a.tool_name,
        mcp_arguments: a.arguments || {},
        required_role: a.required_roles?.[0],
        approval_type: a.approval_type,
        required_roles: a.required_roles || ['developer'],
        created_at: a.created_at,
      }))

    setToolExecutions([])

    // Load messages from normalized database
    // Filter out system messages that are approval notifications (they're shown via ToolExecutionCard)
    const filteredMessages = (fullSession.messages || []).filter((msg) => {
      if (msg.role === 'system') {
        // Filter out approval notification messages
        const content = msg.content || ''
        if (content.includes('approved:') || content.includes('rejected:')) {
          return false
        }
      }
      return true
    })

    const loadedMessages = filteredMessages.map((msg, idx) => {
      const isLastAssistant = idx === (filteredMessages.length - 1) && msg.role === 'assistant'

      return {
        role: msg.role,
        content: msg.content,
        agent_id: msg.agent_id,  // Include agent_id for agent attribution
        timestamp: msg.created_at || msg.timestamp,  // API returns created_at
        ...(msg.role === 'assistant' && {
          // Note: workflowEvents are now shown via ToolDecisionCard/WorkflowEventMessage
          llmCalls: isLastAssistant ? llmCalls : [],
          deploymentUrl: msg.deployment_url,
          containerName: msg.container_name,
        }),
        ...(isLastAssistant && {
          planId: sessionId,
          status: fullSession.status,
          pendingApprovals,
        }),
      }
    })

    // Add HITL questions (both pending and answered) as separate question messages
    // Extract from agent_runs since hitl_questions is now embedded (not at top level)
    const hitlQuestions = agentRuns.flatMap(run => run.hitl_questions || [])
    for (const q of hitlQuestions) {
      const isAnswered = q.status === 'answered'
      loadedMessages.push({
        role: 'question',
        questionData: {
          id: q.id,
          question: q.question,
          choices: q.choices || [],
          context: q.context,
          agent_id: q.agent_id || 'unknown',
          session_id: sessionId,
        },
        answered: isAnswered,
        userAnswer: q.answer,
        timestamp: q.created_at,
      })
    }

    // Sort all messages by timestamp to ensure correct order
    loadedMessages.sort((a, b) => {
      const timeA = new Date(a.timestamp || 0).getTime()
      const timeB = new Date(b.timestamp || 0).getTime()
      return timeA - timeB
    })

    // Check for app_running event in trace data to show deployment URL
    // This ensures the URL is shown even on page refresh
    const appRunningEvent = timelineItems.find(
      event => event.type === 'app_running' && event.data?.url
    )
    if (appRunningEvent) {
      const deployUrl = appRunningEvent.data.url
      const hasDeploymentMessage = loadedMessages.some(
        msg => msg.deploymentUrl === deployUrl
      )
      if (!hasDeploymentMessage) {
        loadedMessages.push({
          role: 'assistant',
          content: `🎉 Deployment complete! Your application is now running.`,
          deploymentUrl: deployUrl,
          containerName: appRunningEvent.data.container_name || 'app',
          timestamp: appRunningEvent.timestamp || new Date().toISOString(),
        })
      }
    }

    // If project has a running build with app_url, add deployment message if not already present
    if (projectInfo?.app_url && !appRunningEvent) {
      const hasDeploymentMessage = loadedMessages.some(
        msg => msg.deploymentUrl === projectInfo.app_url
      )
      if (!hasDeploymentMessage) {
        loadedMessages.push({
          role: 'assistant',
          content: `🎉 Your application is running!`,
          deploymentUrl: projectInfo.app_url,
          containerName: projectInfo.name || 'app',
          timestamp: new Date().toISOString(),
        })
      }
    }

    setMessages(loadedMessages)

    // Store session-level pending approvals for display at end of chat
    // These may not be attached to any message yet
    setSessionPendingApprovals(pendingApprovals)

    // Restore typing indicator state based on session status
    // If session is still executing, show the typing indicator
    // BUT NOT if there's a pending question - we're waiting for user input
    const sessionStatus = fullSession.status
    const isExecuting = ['executing', 'in_progress', 'running', 'active'].includes(sessionStatus)
    const isPausedForApproval = sessionStatus === 'paused_approval' && pendingApprovals.length > 0
    const hasPendingQuestion = hitlQuestions.some(q => q.status === 'pending')

    if (isExecuting && !hasPendingQuestion) {
      // Find the last active agent from timeline items
      const lastAgentEvent = timelineItems
        .filter(e => e.agent_id)
        .pop()
      const lastAgentId = lastAgentEvent?.agent_id

      setIsAgentWorking(true)
      setCurrentAgentId(lastAgentId || null)
      setCurrentStep(lastAgentId ? `${lastAgentId.charAt(0).toUpperCase() + lastAgentId.slice(1)} is working...` : 'Agent is working...')
    } else {
      // Clear typing indicator - either not executing, waiting for question, or waiting for approval
      setIsAgentWorking(false)
      setCurrentAgentId(null)
      setCurrentStep(null)
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

      // Create the assistant message
      const newMessages = [{
        role: 'assistant',
        content: data.response,
        planId: data.plan_id,
        pendingApprovals: data.pending_approvals,
        status: data.status,
        workflowEvents: normalizedEvents,
        timestamp: new Date().toISOString(),
      }]

      // Convert pending_questions to separate question messages
      if (data.pending_questions && data.pending_questions.length > 0) {
        for (const q of data.pending_questions) {
          newMessages.push({
            role: 'question',
            questionData: {
              id: q.id,
              question: q.question,
              choices: q.choices || [],
              context: q.context,
              agent_id: q.agent_id || 'unknown',
              session_id: data.plan_id,
            },
            timestamp: new Date().toISOString(),
          })
        }
      }

      setMessages((prev) => [...prev, ...newMessages])
      setCurrentPlanId(data.plan_id)

      // Check response status to determine if we should stop the loading indicator
      // Keep working if status indicates ongoing execution (unless waiting for approval/question)
      const responseStatus = data.status
      const isPaused = responseStatus === 'paused_approval' || responseStatus === 'paused_hitl'
      const isComplete = responseStatus === 'completed' || responseStatus === 'failed'
      const hasPendingApprovals = data.pending_approvals && data.pending_approvals.length > 0
      const hasPendingQuestions = data.pending_questions && data.pending_questions.length > 0

      console.log('[Chat] Response status:', responseStatus, 'isPaused:', isPaused, 'isComplete:', isComplete)

      if (isPaused || isComplete || hasPendingApprovals || hasPendingQuestions) {
        setCurrentStep(null)
        setIsAgentWorking(false)
      } else {
        // Still processing - keep indicator but update step
        setCurrentStep(null)
        setIsAgentWorking(false) // Default to stopping - backend will send events if still working
      }

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
      setIsAgentWorking(false)
      setDebugWorkflowEvents([...liveWorkflowEvents])
      setLiveWorkflowEvents([])
    },
  })

  // Approve/reject mutations
  const approveMutation = useMutation({
    mutationFn: (taskId) => approveTask(taskId),
    onSuccess: (data, taskId) => {
      // Remove the pending approval from messages and session-level approvals
      setMessages((prev) => prev.map(msg => msg.pendingApprovals ? { ...msg, pendingApprovals: msg.pendingApprovals.filter(a => a.task_id !== taskId) } : msg))
      setSessionPendingApprovals((prev) => prev.filter(a => (a.task_id || a.id) !== taskId))

      // Check if the tool execution failed
      if (data.success === false) {
        const errorMessage = data.user_message || data.error || 'Tool execution failed'
        setMessages((prev) => [...prev, {
          role: 'assistant',
          content: `❌ Execution failed: ${errorMessage}${data.retryable ? ' (You can try again)' : ''}`,
          timestamp: new Date().toISOString(),
        }])
        setCurrentStep(null)
        setIsAgentWorking(false)
        queryClient.invalidateQueries({ queryKey: ['tasks'] })
        queryClient.invalidateQueries({ queryKey: ['sessions'] })
        return
      }

      // Check if we have a resume result with actual response content
      const resumeResult = data.resume_result
      if (resumeResult && resumeResult.response) {
        // Display the actual response from the backend (e.g., deployment complete message)
        const workflowEvents = (resumeResult.workflow_events || []).map(event => ({
          ...event,
          event_type: event.type || event.event_type,
          title: event.title || formatEventTitle({ ...event, event_type: event.type }),
          description: event.data?.description || event.description || '',
          status: event.status || 'success',
          data: event.data || event,
        }))

        setMessages((prev) => [...prev, {
          role: 'assistant',
          content: resumeResult.response,
          workflowEvents,
          deploymentUrl: resumeResult.deployment_url,
          containerName: resumeResult.container_name,
          timestamp: new Date().toISOString(),
        }])

        // Update debug panel with events from the resumed execution
        if (workflowEvents.length > 0) {
          setDebugWorkflowEvents(prev => [...prev, ...workflowEvents])
        }
        if (resumeResult.llm_calls?.length > 0) {
          setDebugLLMCalls(prev => [...prev, ...resumeResult.llm_calls])
        }

        // Clear current step indicator since execution is complete
        setCurrentStep(null)
        setIsAgentWorking(false)
      } else {
        // Fallback to generic message if no resume result
        const isFullyApproved = !data.approvals_required || data.approvals_received >= data.approvals_required
        setMessages((prev) => [...prev, {
          role: 'assistant',
          content: isFullyApproved ? '✅ Task fully approved! The action will now proceed.' : `✅ Your approval has been recorded (${data.approvals_received}/${data.approvals_required}). Waiting for more approvals.`,
          timestamp: new Date().toISOString(),
        }])
        setIsAgentWorking(false)
      }

      queryClient.invalidateQueries({ queryKey: ['tasks'] })
      queryClient.invalidateQueries({ queryKey: ['sessions'] })
    },
    onError: (error) => { setMessages((prev) => [...prev, { role: 'assistant', content: `❌ Error approving task: ${error.message}` }]) },
  })

  const rejectMutation = useMutation({
    mutationFn: ({ taskId, reason }) => rejectTask(taskId, reason),
    onSuccess: (data, { taskId }) => {
      setMessages((prev) => prev.map(msg => msg.pendingApprovals ? { ...msg, pendingApprovals: msg.pendingApprovals.filter(a => a.task_id !== taskId) } : msg))
      setSessionPendingApprovals((prev) => prev.filter(a => (a.task_id || a.id) !== taskId))
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
      setIsAgentWorking(false)
    },
    onError: (error, variables) => {
      setMessages((prev) => [...prev, { role: 'assistant', content: `Error answering question: ${error.message}` }])
      setCurrentStep(null)
      setIsAgentWorking(false)
    },
  })

  // Handlers
  const handleApproveTask = (taskId) => approveMutation.mutate(taskId)
  const handleRejectTask = (taskId, reason) => rejectMutation.mutate({ taskId, reason })

  const handleAnswerQuestion = async (questionId, answer, selected = null) => {
    setMessages((prev) => {
      // Mark the question as answered (don't remove it - keep for history)
      // The answer is shown inline in the HITLQuestionMessage component, no separate user message needed
      return prev.map((msg) => {
        // Mark standalone question messages as answered
        if (msg.role === 'question' && msg.questionData?.id === questionId) {
          return { ...msg, answered: true, userAnswer: selected || answer }
        }
        // Handle legacy pendingQuestions embedded in assistant messages
        if (msg.pendingQuestions) {
          return {
            ...msg,
            pendingQuestions: msg.pendingQuestions.filter((q) => q.id !== questionId),
          }
        }
        return msg
      })
    })
    setCurrentStep('Processing your answer...')
    setIsAgentWorking(true)  // Show typing indicator while agent processes answer
    setLiveWorkflowEvents([])
    setDebugWorkflowEvents([])
    setDebugLLMCalls([])

    // All questions now use the database-backed endpoint
    // (Redis-based HITL MCP server has been removed)
    answerMutation.mutate({ questionId, answer })
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
    setSessionPendingApprovals([])
    setCurrentStep(null)
    setIsAgentWorking(false)
    setCurrentAgentId(null)
    setToolExecutions([])
    setWorkflowEventsForDisplay([])
    setSearchParams({})
    setMessages([{ role: 'assistant', content: `Hello ${user?.firstName || user?.username}! I'm Druppie, your AI governance assistant.\n\nI can help you:\n• Create applications (just describe what you want!)\n• Manage code deployments\n• Check compliance and permissions\n\nWhat would you like to build today?` }])
  }

  const handleSelectPlan = async (session) => {
    setCurrentPlanId(session.id)
    setLiveWorkflowEvents([])
    setToolExecutions([])
    setWorkflowEventsForDisplay([])
    setCurrentAgentId(null)
    setIsAgentWorking(false)
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
    const session = sessionsData?.items?.find(s => s.id === sessionId)
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

        {/* Messages and Timeline Events - Combined and sorted by timestamp */}
        <div className="flex-1 overflow-y-auto p-4 space-y-2">
          {(() => {
            // Combine messages and timeline items
            const allItems = [
              // User and assistant messages
              ...messages.map((msg, idx) => ({
                ...msg,
                itemType: 'message',
                sortKey: msg.timestamp ? new Date(msg.timestamp).getTime() : idx,
                key: `msg-${idx}`,
              })),
              // Timeline items from backend (agent_started, tool_decision, agent_completed)
              ...workflowEventsForDisplay.map((item, idx) => ({
                ...item,
                itemType: 'timeline',
                sortKey: item.timestamp ? new Date(item.timestamp).getTime() : idx + 10000,
                key: `timeline-${item.id || idx}`,
              })),
              // Session-level pending approvals (non-tool_call types)
              ...sessionPendingApprovals.map((approval, i) => ({
                ...approval,
                itemType: 'pendingApproval',
                sortKey: approval.created_at ? new Date(approval.created_at).getTime() : Date.now(),
                key: `approval-${approval.task_id || approval.id || i}`,
              })),
            ]

            // Sort by timestamp (keeping welcome message first)
            allItems.sort((a, b) => {
              if (a.itemType === 'message' && a.key === 'msg-0' && !a.timestamp) return -1
              if (b.itemType === 'message' && b.key === 'msg-0' && !b.timestamp) return 1
              return a.sortKey - b.sortKey
            })

            return allItems.map((item) => {
              // Timeline items (from the unified backend structure)
              if (item.itemType === 'timeline') {
                // tool_decision items use the new ToolDecisionCard
                if (item.type === 'tool_decision' && item.toolDecision) {
                  return (
                    <ToolDecisionCard
                      key={item.key}
                      item={item}
                      onApprove={handleApproveTask}
                      onReject={handleRejectTask}
                      onAnswerQuestion={handleAnswerQuestion}
                      isProcessing={approveMutation.isPending || rejectMutation.isPending}
                      isAnswering={answerMutation.isPending}
                      userRoles={user?.roles || []}
                    />
                  )
                }
                // agent_started and agent_completed use WorkflowEventMessage
                return (
                  <WorkflowEventMessage
                    key={item.key}
                    event={item}
                    onApprove={handleApproveTask}
                    onReject={handleRejectTask}
                    isProcessing={approveMutation.isPending || rejectMutation.isPending}
                    userRoles={user?.roles || []}
                    sessionId={currentPlanId}
                  />
                )
              }
              // Non-tool_call approvals (workflow_step approvals)
              if (item.itemType === 'pendingApproval' && !chatMutation.isPending && !isAgentWorking) {
                return (
                  <ApprovalCard
                    key={item.key}
                    approval={item}
                    onApprove={handleApproveTask}
                    onReject={handleRejectTask}
                    isProcessing={approveMutation.isPending || rejectMutation.isPending}
                    currentUserId={user?.id}
                    sessionId={currentPlanId}
                    userRoles={user?.roles || []}
                  />
                )
              }
              // Standalone HITL questions (from messages)
              if (item.role === 'question') {
                return (
                  <HITLQuestionMessage
                    key={item.key}
                    question={item.questionData}
                    onAnswer={handleAnswerQuestion}
                    isAnswering={answerMutation.isPending}
                    answered={item.answered}
                    userAnswer={item.userAnswer}
                  />
                )
              }
              // Regular messages
              return (
                <Message
                  key={item.key}
                  message={item}
                  onAnswerQuestion={handleAnswerQuestion}
                  isAnsweringQuestion={answerMutation.isPending}
                  onApproveTask={handleApproveTask}
                  onRejectTask={handleRejectTask}
                  isApprovingTask={approveMutation.isPending || rejectMutation.isPending}
                  currentUserId={user?.id}
                  sessionId={currentPlanId}
                  userRoles={user?.roles || []}
                />
              )
            })
          })()}

          {(chatMutation.isPending || isAgentWorking) && (
            <TypingIndicator
              currentStep={currentStep}
              liveEvents={liveWorkflowEvents}
              onStop={handleStopExecution}
              isStopping={isStopping}
              agentId={currentAgentId}
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
        sessionId={currentPlanId}
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
