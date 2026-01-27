/**
 * Chat Page - Main interface for Druppie governance
 * Shows workflow events and conversation history sidebar
 */

import React, { useState, useRef, useEffect } from 'react'
import { useSearchParams, useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Send, Bug, FolderOpen, ExternalLink } from 'lucide-react'
import { sendChat, getSessions, getPlan, answerQuestion, approveTask, rejectTask, submitHITLResponse, getProject, cancelChat, getSessionTrace } from '../services/api'
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
  ToolExecutionCard,
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
  const seenApprovalIds = useRef(new Set()) // Track seen approval IDs to prevent duplicates
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

  // Workflow event listener
  useEffect(() => {
    const handleWorkflowEvent = (data) => {
      console.log('[Chat] handleWorkflowEvent called:', data)
      const eventSessionId = data.session_id || data.plan_id
      if (eventSessionId && currentPlanId && eventSessionId !== currentPlanId) {
        console.log('[Chat] Ignoring event - session mismatch:', eventSessionId, '!==', currentPlanId)
        return
      }

      const event = data.event
      if (!event) {
        console.log('[Chat] No event in data, skipping')
        return
      }

      const eventType = event.type || event.event_type || ''
      console.log('[Chat] Processing workflow event:', eventType, event)

      // Update agent working state based on event type
      if (eventType === 'agent_started' || eventType.includes('_started')) {
        const agentId = event.data?.agent_id || event.agent_id
        console.log('[Chat] Agent started:', agentId)
        setIsAgentWorking(true)
        if (agentId) setCurrentAgentId(agentId)
      }

      const stepTitle = event.title || event.data?.description || formatEventTitle(event)
      if (stepTitle) setCurrentStep(stepTitle)

      // Check if workflow is complete or failed - stop the working indicator
      if (eventType.includes('workflow_completed') || eventType.includes('workflow_failed') ||
          eventType.includes('session_completed') || eventType.includes('session_failed') ||
          eventType.includes('execution_complete') || eventType.includes('execution_failed')) {
        console.log('[Chat] Workflow/session completed or failed, stopping indicator')
        setIsAgentWorking(false)
        setCurrentStep(null)
        setCurrentAgentId(null)
      }

      // Agent completed - check if it's the last agent (deployer usually)
      if (eventType === 'agent_completed' || eventType.includes('_completed')) {
        const agentId = event.data?.agent_id || event.agent_id
        if (agentId) setCurrentAgentId(agentId)
        // If deployer completed, it's likely the end of the workflow
        if (agentId === 'deployer') {
          console.log('[Chat] Deployer completed, stopping indicator')
          setIsAgentWorking(false)
          setCurrentStep(null)
        }
      }

      // Tool approval required - stop the indicator
      if (eventType.includes('approval_required') || eventType.includes('approval_pending')) {
        console.log('[Chat] Approval required, stopping indicator')
        setIsAgentWorking(false)
        setCurrentStep(null)
      }

      const formattedEvent = {
        ...event,
        event_type: event.type,
        title: stepTitle,
        description: event.data?.description || event.description,
        status: event.status || (event.type?.includes('completed') || event.type?.includes('success') ? 'success' : 'working'),
        data: event.data || event,
        timestamp: event.timestamp || new Date().toISOString(),
      }
      setLiveWorkflowEvents((prev) => [...prev, formattedEvent])

      // Add to display list for inline workflow messages (show more events for transparency)
      // Include: agent events, tool calls/results, approvals
      const isDisplayable = eventType.includes('tool_call') || eventType.includes('tool_result') ||
                           eventType.includes('mcp_') ||
                           eventType.includes('approval') ||
                           eventType.includes('agent_started') || eventType.includes('agent_completed') ||
                           eventType.includes('_started') || eventType.includes('_completed')
      if (isDisplayable) {
        setWorkflowEventsForDisplay((prev) => {
          // Deduplicate by checking for similar recent events (same type and agent within 2 seconds)
          const recentEvent = prev.find(e => {
            const sameAgent = (e.agent || e.data?.agent_id) === (formattedEvent.agent || formattedEvent.data?.agent_id)
            const sameType = (e.type || e.event_type)?.includes('started') === eventType.includes('started') &&
                            (e.type || e.event_type)?.includes('completed') === eventType.includes('completed')
            const timeDiff = Math.abs(new Date(e.timestamp).getTime() - new Date(formattedEvent.timestamp).getTime())
            return sameAgent && sameType && timeDiff < 2000
          })
          if (recentEvent) return prev // Skip duplicate
          return [...prev, formattedEvent]
        })
      }
    }

    const unsubscribe = onWorkflowEvent(handleWorkflowEvent)
    return () => unsubscribe()
  }, [currentPlanId])

  // Approval event listeners
  useEffect(() => {
    const handleTaskApproved = (data) => {
      const approverId = data.approver_id
      const approverUsername = data.approver_username || data.approver_role || 'User'
      const approverRole = data.approver_role || 'user'
      const toolName = data.tool_name || data.name || 'action'
      const approvalId = data.approval_id || data.id
      const agentId = data.agent_id

      // Update the tool execution status instead of adding a message
      setToolExecutions((prev) => {
        const existing = prev.find(t => t.approvalId === approvalId)
        if (existing) {
          return prev.map(t => t.approvalId === approvalId ? {
            ...t,
            status: 'approved',
            approverUsername,
            approverRole,
            approvedAt: new Date().toISOString(),
          } : t)
        }
        // If not found, add it (for real-time updates from other sessions)
        return [...prev, {
          id: approvalId,
          approvalId,
          agentId: agentId || 'developer',
          toolName,
          parameters: data.args || {},
          status: 'approved',
          approverUsername,
          approverRole,
          approvedAt: new Date().toISOString(),
        }]
      })

      // Only show notification if it's from another user
      if (approverId && approverId !== user?.id) {
        toast.success('Task Approved', `${approverUsername} (${approverRole}) approved: ${toolName}`)

        // Show typing indicator since agent is now working
        setCurrentStep(`${agentId || 'Agent'} is continuing execution...`)
        setCurrentAgentId(agentId || 'developer')
        setIsAgentWorking(true)
        setLiveWorkflowEvents([])
      }

      // Remove the pending approval from messages and session-level approvals
      setMessages((prev) => prev.map((msg) => {
        if (!msg.pendingApprovals) return msg
        return { ...msg, pendingApprovals: msg.pendingApprovals.filter(a => (a.task_id || a.id) !== approvalId) }
      }))
      setSessionPendingApprovals((prev) => prev.filter(a => (a.task_id || a.id) !== approvalId))

      queryClient.invalidateQueries({ queryKey: ['sessions'] })
      queryClient.invalidateQueries({ queryKey: ['tasks'] })
    }

    const handleTaskRejected = (data) => {
      const rejectorId = data.approver_id
      const rejectorUsername = data.approver_username || data.approver_role || 'User'
      const rejectorRole = data.approver_role || 'user'
      const toolName = data.tool_name || data.name || 'action'
      const approvalId = data.approval_id || data.id
      const agentId = data.agent_id

      // Update the tool execution status instead of adding a message
      setToolExecutions((prev) => {
        const existing = prev.find(t => t.approvalId === approvalId)
        if (existing) {
          return prev.map(t => t.approvalId === approvalId ? {
            ...t,
            status: 'rejected',
            approverUsername: rejectorUsername,
            approverRole: rejectorRole,
            rejectionReason: data.reason || data.comment,
          } : t)
        }
        return [...prev, {
          id: approvalId,
          approvalId,
          agentId: agentId || 'developer',
          toolName,
          parameters: data.args || {},
          status: 'rejected',
          approverUsername: rejectorUsername,
          approverRole: rejectorRole,
          rejectionReason: data.reason || data.comment,
        }]
      })

      // Only show notification if it's from another user
      if (rejectorId && rejectorId !== user?.id) {
        toast.warning('Task Rejected', `${rejectorUsername} (${rejectorRole}) rejected: ${toolName}`)
      }

      // Remove the pending approval from messages
      setMessages((prev) => prev.map((msg) => {
        if (!msg.pendingApprovals) return msg
        return { ...msg, pendingApprovals: msg.pendingApprovals.filter(a => (a.task_id || a.id) !== approvalId) }
      }))
      setSessionPendingApprovals((prev) => prev.filter(a => (a.task_id || a.id) !== approvalId))

      queryClient.invalidateQueries({ queryKey: ['sessions'] })
      queryClient.invalidateQueries({ queryKey: ['tasks'] })
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
      console.log('[Chat] handleHITLQuestion called:', data)
      // Filter by session - only show questions for our session
      const eventSessionId = data.session_id
      if (eventSessionId && currentPlanId && eventSessionId !== currentPlanId) {
        console.log('[Chat] Ignoring question - session mismatch:', eventSessionId, '!==', currentPlanId)
        return
      }

      console.log('[Chat] Processing HITL question for session:', eventSessionId)

      // Create question data with agent info for proper display
      const questionData = {
        id: data.request_id || data.question_id,
        question: data.question,
        input_type: data.input_type,
        choices: data.choices || [],
        allow_other: data.allow_other !== false,
        context: data.context,
        session_id: data.session_id || currentPlanId,
        agent_id: data.agent_id || 'unknown',
      }

      // Stop showing typing indicator when waiting for user input
      setIsAgentWorking(false)
      setCurrentStep(null)

      // Add as a separate question message (not embedded in assistant message)
      setMessages((prev) => [
        ...prev,
        {
          role: 'question',
          questionData,
          timestamp: new Date().toISOString(),
        },
      ])

      const agentName = data.agent_id ? data.agent_id.charAt(0).toUpperCase() + data.agent_id.slice(1) : 'Agent'
      toast.info(`Question from ${agentName}`, data.question.substring(0, 80) + (data.question.length > 80 ? '...' : ''))
    }

    const handleApprovalRequired = (data) => {
      // Filter by session - only show approvals for our session
      const eventSessionId = data.session_id
      if (eventSessionId && currentPlanId && eventSessionId !== currentPlanId) {
        return
      }

      // Deduplicate - skip if we've already seen this approval
      const approvalId = data.approval_id
      if (seenApprovalIds.current.has(approvalId)) {
        return
      }
      seenApprovalIds.current.add(approvalId)

      // Handle both tool approvals (data.tool) and step approvals (data.message)
      const isStepApproval = data.tool?.startsWith('approval:') || data.message
      const taskName = isStepApproval
        ? (data.message || 'Approval checkpoint')
        : data.tool

      const approvalData = {
        task_id: data.approval_id,
        task_name: taskName,
        mcp_tool: isStepApproval ? null : data.tool,
        required_roles: data.required_roles || ['developer'],
        approval_type: data.required_roles?.length > 1 ? 'multi' : 'self',
        current_approvals: 0,
        required_approvals: 1,
        approved_by_roles: [],
        approved_by_ids: [],
        args: data.args || data.context,
        step_id: data.step_id,
      }

      // Add to tool executions for ToolExecutionCard display (only for tool approvals, not step approvals)
      if (!isStepApproval) {
        setToolExecutions((prev) => {
          // Avoid duplicates
          if (prev.find(t => t.approvalId === data.approval_id)) return prev
          return [...prev, {
            id: data.approval_id,
            approvalId: data.approval_id,
            agentId: data.agent_id || currentAgentId || 'developer',
            toolName: data.tool,
            parameters: data.args || data.context || {},
            status: 'pending',
          }]
        })
        // Stop showing typing indicator when waiting for approval
        setIsAgentWorking(false)
        setCurrentStep(null)
      }

      setMessages((prev) => {
        const lastMsg = prev[prev.length - 1]
        if (lastMsg && lastMsg.role !== 'user') {
          return prev.map((msg, idx) => idx === prev.length - 1
            ? { ...msg, pendingApprovals: [...(msg.pendingApprovals || []), approvalData] }
            : msg
          )
        }
        const content = isStepApproval
          ? taskName
          : `I need approval to run: ${data.tool}`
        return [...prev, { role: 'assistant', content, pendingApprovals: [approvalData], timestamp: new Date().toISOString() }]
      })
      toast.warning('Approval Required', taskName)
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

  // Deployment complete listener - shows the app URL when docker:run succeeds
  useEffect(() => {
    const handleDeploymentComplete = (data) => {
      const sessionId = data.session_id
      if (sessionId && currentPlanId && sessionId !== currentPlanId) return

      const url = data.url
      const containerName = data.container_name

      // Add or update the last message with deployment info
      setMessages((prev) => {
        const lastMsg = prev[prev.length - 1]
        if (lastMsg && lastMsg.role !== 'user') {
          // Update the last assistant message with deployment URL
          return prev.map((msg, idx) =>
            idx === prev.length - 1
              ? { ...msg, deploymentUrl: url, containerName: containerName }
              : msg
          )
        }
        // Add a new deployment message
        return [...prev, {
          role: 'assistant',
          content: `🎉 Deployment complete! Your application is now running.`,
          deploymentUrl: url,
          containerName: containerName,
          timestamp: new Date().toISOString(),
        }]
      })

      toast.success('Deployment Successful!', `Your app is running at ${url}`)
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

    // Fetch trace data from the normalized database endpoint
    let normalizedEvents = []
    let llmCalls = []
    try {
      const traceData = await getSessionTrace(sessionId)
      if (traceData?.trace) {
        // Convert trace events to DebugPanel format
        normalizedEvents = (traceData.trace.events || []).map(event => ({
          id: event.id,
          type: event.type,
          event_type: event.type,
          title: formatEventTitle({ type: event.type, event_type: event.type, data: { agent_id: event.agent, ...event.data } }),
          description: event.tool ? `Tool: ${event.tool}` : '',
          status: event.type.includes('complete') ? 'success' : event.type.includes('error') ? 'error' : 'working',
          timestamp: event.timestamp,
          data: {
            agent_id: event.agent,
            tool_name: event.tool,
            tool: event.tool,
            args_preview: event.args ? JSON.stringify(event.args).substring(0, 100) : null,
            arguments: event.args,
            result: event.result,
            ...event.data,
          },
          duration_ms: event.duration_ms,
        }))

        // Convert raw LLM calls to DebugPanel format
        llmCalls = (traceData.trace.raw_llm_calls || []).map((call, idx) => ({
          agent_id: call.agent_id,
          iteration: call.iteration || idx + 1,
          model: call.model,
          provider: call.provider,
          duration_ms: call.duration_ms,
          usage: call.usage,
          timestamp: call.timestamp,
          tool_calls: [],  // Not stored in normalized schema
          response: call.response,
        }))
      }
    } catch (err) {
      console.error('Error loading trace data:', err)
    }

    setDebugWorkflowEvents(normalizedEvents)
    setDebugLLMCalls(llmCalls)
    setApiCalls(llmCalls.map(call => ({ type: 'llm', ...call })))

    // Store workflow events for inline display (show more events for transparency)
    const displayableEvents = normalizedEvents.filter(event => {
      const type = event.type || event.event_type || ''
      // Include: agent events, tool calls/results, approvals
      return type.includes('agent_started') || type.includes('agent_completed') ||
             type.includes('tool_call') || type.includes('tool_result') ||
             type.includes('approval') || type.includes('mcp_') ||
             type.includes('_started') || type.includes('_completed')
    })
    setWorkflowEventsForDisplay(displayableEvents)
    console.log('[Chat] Loaded displayable events:', displayableEvents.length)

    let pendingApprovals = []
    let loadedToolExecutions = []
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

      // Load all tool executions (pending, approved, rejected) for ToolExecutionCard display
      loadedToolExecutions = fullSession.tasks
        .filter(task => task.mcp_tool && !task.mcp_tool.startsWith('approval:'))
        .map(task => {
          const lastApproval = task.approvals?.slice(-1)[0]
          const isApproved = task.status === 'approved' || task.status === 'completed'
          const isRejected = task.status === 'rejected'

          return {
            id: task.id,
            approvalId: task.id,
            agentId: task.agent_id || 'developer',
            toolName: task.mcp_tool,
            parameters: task.mcp_arguments || {},
            status: isApproved ? 'approved' : isRejected ? 'rejected' : 'pending',
            approverUsername: lastApproval?.approver_username || lastApproval?.approved_by_username,
            approverRole: lastApproval?.role,
            approvedAt: lastApproval?.created_at,
            rejectionReason: isRejected ? (lastApproval?.comment || task.rejection_reason) : undefined,
          }
        })
    }

    setToolExecutions(loadedToolExecutions)

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
        timestamp: msg.timestamp,
        ...(msg.role === 'assistant' && {
          workflowEvents: isLastAssistant ? normalizedEvents : [],
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
    // Use hitl_questions which includes all questions for full history reconstruction
    // Note: The answered question message shows the user's answer inline, no need for separate user message
    const hitlQuestions = fullSession.hitl_questions || fullSession.pending_questions || []
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
        timestamp: q.created_at || new Date().toISOString(),
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
    const appRunningEvent = normalizedEvents.find(
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
      // Find the last active agent from workflow events
      const lastAgentEvent = normalizedEvents
        .filter(e => e.data?.agent_id)
        .pop()
      const lastAgentId = lastAgentEvent?.data?.agent_id

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
    seenApprovalIds.current.clear()
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
    seenApprovalIds.current.clear()
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

        {/* Messages and Workflow Events - Combined and sorted by timestamp */}
        <div className="flex-1 overflow-y-auto p-4 space-y-2">
          {(() => {
            // Combine messages and workflow events for unified timeline
            const allItems = [
              ...messages.map((msg, idx) => ({
                ...msg,
                itemType: 'message',
                sortKey: msg.timestamp ? new Date(msg.timestamp).getTime() : idx,
                key: `msg-${idx}`,
              })),
              ...workflowEventsForDisplay.map((event, idx) => ({
                ...event,
                itemType: 'workflow',
                sortKey: event.timestamp ? new Date(event.timestamp).getTime() : idx + 10000,
                key: `event-${event.id || idx}`,
              })),
            ]

            // Sort by timestamp (keeping welcome message first)
            allItems.sort((a, b) => {
              // Welcome message always first (index 0 with no timestamp)
              if (a.itemType === 'message' && a.key === 'msg-0' && !a.timestamp) return -1
              if (b.itemType === 'message' && b.key === 'msg-0' && !b.timestamp) return 1
              return a.sortKey - b.sortKey
            })

            return allItems.map((item) => {
              if (item.itemType === 'workflow') {
                return <WorkflowEventMessage key={item.key} event={item} />
              }
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
          {/* Render completed tool executions (approved/rejected) - pending ones shown via ApprovalCard */}
          {toolExecutions
            .filter((execution) => execution.status !== 'pending')
            .map((execution) => (
              <ToolExecutionCard
                key={execution.id || execution.approvalId}
                agentId={execution.agentId}
                toolName={execution.toolName}
                parameters={execution.parameters}
                status={execution.status}
                approverUsername={execution.approverUsername}
                approverRole={execution.approverRole}
                approvedAt={execution.approvedAt}
                rejectionReason={execution.rejectionReason}
              />
            ))}

          {(chatMutation.isPending || isAgentWorking) && (
            <TypingIndicator
              currentStep={currentStep}
              liveEvents={liveWorkflowEvents}
              onStop={handleStopExecution}
              isStopping={isStopping}
              agentId={currentAgentId}
            />
          )}

          {/* Session-level pending approvals - shown when not attached to any message */}
          {!chatMutation.isPending && !isAgentWorking && sessionPendingApprovals.length > 0 && (
            <div className="space-y-3">
              {sessionPendingApprovals.map((approval, i) => (
                <ApprovalCard
                  key={approval.task_id || approval.id || i}
                  approval={approval}
                  onApprove={handleApproveTask}
                  onReject={handleRejectTask}
                  isProcessing={approveMutation.isPending || rejectMutation.isPending}
                  currentUserId={user?.id}
                  sessionId={currentPlanId}
                  userRoles={user?.roles || []}
                />
              ))}
            </div>
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
