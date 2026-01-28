/**
 * WebSocket Service for Druppie Real-time Updates
 *
 * Updated to use native WebSocket for the new FastAPI backend.
 * Includes race condition prevention and proper cleanup.
 */

import { getToken } from './keycloak'

const WS_URL = (import.meta.env.VITE_API_URL || 'http://localhost:8000')
  .replace('http://', 'ws://')
  .replace('https://', 'wss://')

let socket = null
let reconnectAttempts = 0
let reconnectTimer = null  // Track reconnect timer to prevent race conditions
let isConnecting = false   // Prevent multiple simultaneous connection attempts
const MAX_RECONNECT_ATTEMPTS = 10
const RECONNECT_DELAY = 1000
const MAX_RECONNECT_DELAY = 30000

/**
 * Calculate reconnection delay with exponential backoff and jitter
 * @param {number} attempt - Current attempt number (0-indexed)
 * @returns {number} Delay in milliseconds
 */
const calculateReconnectDelay = (attempt) => {
  // Exponential backoff: delay = RECONNECT_DELAY * (2 ** attempt)
  const exponentialDelay = RECONNECT_DELAY * Math.pow(2, attempt)
  // Cap at max delay
  const cappedDelay = Math.min(exponentialDelay, MAX_RECONNECT_DELAY)
  // Add jitter: delay * (0.5 + random * 0.5) to prevent thundering herd
  const jitter = 0.5 + Math.random() * 0.5
  return Math.floor(cappedDelay * jitter)
}

// Connection status: 'disconnected' | 'connecting' | 'connected' | 'reconnecting'
let connectionStatus = 'disconnected'

// Status change callbacks
const statusCallbacks = []

/**
 * Get current connection status
 */
export const getConnectionStatus = () => connectionStatus

/**
 * Subscribe to connection status changes
 * @param {function} callback - Called with new status when it changes
 * @returns {function} Unsubscribe function
 */
export const onConnectionStatusChange = (callback) => {
  statusCallbacks.push(callback)
  // Immediately call with current status
  callback(connectionStatus)

  return () => {
    const idx = statusCallbacks.indexOf(callback)
    if (idx > -1) {
      statusCallbacks.splice(idx, 1)
    }
  }
}

/**
 * Update connection status and notify listeners
 */
const setConnectionStatus = (status) => {
  if (connectionStatus !== status) {
    connectionStatus = status
    statusCallbacks.forEach((callback) => {
      try {
        callback(status)
      } catch (err) {
        // Silently ignore callback errors
      }
    })
  }
}

// Event callbacks
const eventCallbacks = {
  task_approved: [],
  task_rejected: [],
  plan_updated: [],
  workflow_event: [],
  approval_requested: [],
  approval_required: [],  // MCP microservices approval
  approval_status_changed: [],  // Approval status updates
  session_updated: [],
  question_pending: [],
  question: [],  // HITL MCP question events
  progress: [],  // HITL MCP progress events
  notification: [],  // HITL MCP notification events
  execution_cancelled: [],  // Execution cancelled by user
  deployment_complete: [],  // Deployment successful with URL
}

/**
 * Clear any pending reconnection timer
 */
const clearReconnectTimer = () => {
  if (reconnectTimer) {
    clearTimeout(reconnectTimer)
    reconnectTimer = null
  }
}

/**
 * Initialize WebSocket connection
 */
export const initSocket = (sessionId = null) => {
  // If already connected, return existing socket
  if (socket?.readyState === WebSocket.OPEN) {
    return socket
  }

  // If already connecting, don't create another connection
  if (isConnecting || socket?.readyState === WebSocket.CONNECTING) {
    return socket
  }

  // Clear any pending reconnection
  clearReconnectTimer()

  // Close existing socket cleanly if any
  if (socket) {
    // Remove event handlers to prevent callbacks during close
    socket.onopen = null
    socket.onclose = null
    socket.onerror = null
    socket.onmessage = null
    try {
      socket.close()
    } catch (e) {
      // Ignore close errors
    }
    socket = null
  }

  const token = getToken()
  if (!token) {
    // Don't attempt connection without token
    setConnectionStatus('disconnected')
    return null
  }

  const wsPath = sessionId ? `/ws/session/${sessionId}` : '/ws'
  const wsUrl = `${WS_URL}${wsPath}?token=${token}`

  // Set status to connecting (or reconnecting if we've already attempted)
  isConnecting = true
  setConnectionStatus(reconnectAttempts > 0 ? 'reconnecting' : 'connecting')

  try {
    socket = new WebSocket(wsUrl)
  } catch (e) {
    isConnecting = false
    setConnectionStatus('disconnected')
    return null
  }

  socket.onopen = () => {
    isConnecting = false
    reconnectAttempts = 0
    setConnectionStatus('connected')
  }

  socket.onclose = (event) => {
    isConnecting = false

    // Don't reconnect if we're intentionally disconnecting (code 1000)
    if (event.code === 1000) {
      setConnectionStatus('disconnected')
      return
    }

    // Attempt reconnection with exponential backoff and jitter
    if (reconnectAttempts < MAX_RECONNECT_ATTEMPTS) {
      const delay = calculateReconnectDelay(reconnectAttempts)
      reconnectAttempts++
      setConnectionStatus('reconnecting')
      clearReconnectTimer()
      reconnectTimer = setTimeout(() => {
        reconnectTimer = null
        initSocket(sessionId)
      }, delay)
    } else {
      setConnectionStatus('disconnected')
    }
  }

  socket.onerror = () => {
    // Error is handled by onclose, just mark as not connecting
    isConnecting = false
  }

  socket.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data)
      const eventType = data.type

      // DEBUG: Log all incoming WebSocket messages
      console.log('[WebSocket] Received:', eventType, data)

      // Handle connected confirmation (no action needed)
      if (eventType === 'connected') {
        console.log('[WebSocket] Connected to server')
        return
      }

      // Dispatch to registered callbacks
      // Map new event types to legacy names for backwards compatibility
      const eventMap = {
        approval_approved: 'task_approved',
        approval_rejected: 'task_rejected',
        session_updated: 'plan_updated',
      }

      const callbackType = eventMap[eventType] || eventType
      const callbacks = eventCallbacks[callbackType] || []
      console.log('[WebSocket] Dispatching to', callbackType, '- callbacks registered:', callbacks.length)
      callbacks.forEach((callback) => {
        try {
          callback(data)
        } catch (err) {
          console.error('[WebSocket] Callback error:', err)
        }
      })
    } catch (err) {
      console.error('[WebSocket] Parse error:', err)
    }
  }

  return socket
}

/**
 * Get the socket instance
 */
export const getSocket = () => {
  if (!socket || socket.readyState !== WebSocket.OPEN) {
    return initSocket()
  }
  return socket
}

/**
 * Send a message through the WebSocket
 */
const sendMessage = (message) => {
  const s = getSocket()
  if (s && s.readyState === WebSocket.OPEN) {
    s.send(JSON.stringify(message))
  }
  // Silently ignore send attempts when not connected - connection status is tracked via UI
}

/**
 * Join a plan/session room for real-time updates
 */
export const joinPlanRoom = (planId) => {
  if (planId) {
    console.log('[WebSocket] Joining session room:', planId)
    sendMessage({ type: 'join_session', session_id: planId })
  }
}

/**
 * Join approvals rooms for the user's roles
 */
export const joinApprovalsRoom = (roles) => {
  if (roles?.length > 0) {
    sendMessage({ type: 'join_approvals', roles })
  }
}

/**
 * Register a callback for an event type
 */
const registerCallback = (eventType, callback) => {
  if (!eventCallbacks[eventType]) {
    eventCallbacks[eventType] = []
  }
  eventCallbacks[eventType].push(callback)

  // Return unsubscribe function
  return () => {
    const idx = eventCallbacks[eventType].indexOf(callback)
    if (idx > -1) {
      eventCallbacks[eventType].splice(idx, 1)
    }
  }
}

/**
 * Subscribe to task approved events
 */
export const onTaskApproved = (callback) => {
  return registerCallback('task_approved', callback)
}

/**
 * Subscribe to task rejected events
 */
export const onTaskRejected = (callback) => {
  return registerCallback('task_rejected', callback)
}

/**
 * Subscribe to plan updated events
 */
export const onPlanUpdated = (callback) => {
  return registerCallback('plan_updated', callback)
}

/**
 * Subscribe to workflow events
 */
export const onWorkflowEvent = (callback) => {
  return registerCallback('workflow_event', callback)
}

/**
 * Subscribe to approval requested events
 */
export const onApprovalRequested = (callback) => {
  return registerCallback('approval_requested', callback)
}

/**
 * Subscribe to session updated events
 */
export const onSessionUpdated = (callback) => {
  return registerCallback('session_updated', callback)
}

/**
 * Subscribe to question pending events
 */
export const onQuestionPending = (callback) => {
  return registerCallback('question_pending', callback)
}

/**
 * Subscribe to HITL question events (from MCP microservices)
 */
export const onHITLQuestion = (callback) => {
  return registerCallback('question', callback)
}

/**
 * Subscribe to approval required events (from MCP microservices)
 */
export const onApprovalRequired = (callback) => {
  return registerCallback('approval_required', callback)
}

/**
 * Subscribe to approval status changed events
 */
export const onApprovalStatusChanged = (callback) => {
  return registerCallback('approval_status_changed', callback)
}

/**
 * Check if socket is connected
 */
export const isSocketConnected = () => {
  return socket && socket.readyState === WebSocket.OPEN
}

/**
 * Subscribe to execution cancelled events
 */
export const onExecutionCancelled = (callback) => {
  return registerCallback('execution_cancelled', callback)
}

/**
 * Subscribe to deployment complete events
 * Called when docker:run succeeds with a URL
 */
export const onDeploymentComplete = (callback) => {
  return registerCallback('deployment_complete', callback)
}

/**
 * Disconnect the socket
 */
export const disconnectSocket = () => {
  clearReconnectTimer()
  isConnecting = false

  if (socket) {
    // Remove event handlers to prevent reconnection attempts
    socket.onopen = null
    socket.onclose = null
    socket.onerror = null
    socket.onmessage = null
    try {
      socket.close(1000, 'User disconnect')  // Use code 1000 for intentional close
    } catch (e) {
      // Ignore close errors
    }
    socket = null
  }

  reconnectAttempts = 0
  setConnectionStatus('disconnected')
}
