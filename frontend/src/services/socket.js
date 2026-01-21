/**
 * WebSocket Service for Druppie Real-time Updates
 *
 * Updated to use native WebSocket for the new FastAPI backend.
 */

import { getToken } from './keycloak'

const WS_URL = (import.meta.env.VITE_API_URL || 'http://localhost:8000')
  .replace('http://', 'ws://')
  .replace('https://', 'wss://')

let socket = null
let reconnectAttempts = 0
const MAX_RECONNECT_ATTEMPTS = 5
const RECONNECT_DELAY = 1000

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
}

/**
 * Initialize WebSocket connection
 */
export const initSocket = (sessionId = null) => {
  if (socket?.readyState === WebSocket.OPEN) {
    return socket
  }

  // Close existing socket if any
  if (socket) {
    socket.close()
  }

  const token = getToken()
  const wsPath = sessionId ? `/ws/session/${sessionId}` : '/ws'
  const wsUrl = token ? `${WS_URL}${wsPath}?token=${token}` : `${WS_URL}${wsPath}`

  socket = new WebSocket(wsUrl)

  socket.onopen = () => {
    console.log('[WebSocket] Connected')
    reconnectAttempts = 0
  }

  socket.onclose = (event) => {
    console.log('[WebSocket] Disconnected:', event.code, event.reason)

    // Attempt reconnection
    if (reconnectAttempts < MAX_RECONNECT_ATTEMPTS) {
      reconnectAttempts++
      console.log(`[WebSocket] Reconnecting (attempt ${reconnectAttempts}/${MAX_RECONNECT_ATTEMPTS})...`)
      setTimeout(() => initSocket(sessionId), RECONNECT_DELAY * reconnectAttempts)
    } else {
      console.error('[WebSocket] Max reconnection attempts reached')
    }
  }

  socket.onerror = (error) => {
    console.error('[WebSocket] Error:', error)
  }

  socket.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data)
      const eventType = data.type

      console.log('[WebSocket] Message received:', eventType, data)

      // Handle connected confirmation
      if (eventType === 'connected') {
        console.log('[WebSocket] Server confirmed connection:', data)
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
      callbacks.forEach((callback) => {
        try {
          callback(data)
        } catch (err) {
          console.error('[WebSocket] Callback error:', err)
        }
      })
    } catch (err) {
      console.error('[WebSocket] Failed to parse message:', err)
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
  } else {
    console.warn('[WebSocket] Cannot send message - not connected')
  }
}

/**
 * Join a plan/session room for real-time updates
 */
export const joinPlanRoom = (planId) => {
  if (planId) {
    sendMessage({ type: 'join_session', session_id: planId })
    console.log('[WebSocket] Joining session room:', planId)
  }
}

/**
 * Join approvals rooms for the user's roles
 */
export const joinApprovalsRoom = (roles) => {
  if (roles?.length > 0) {
    sendMessage({ type: 'join_approvals', roles })
    console.log('[WebSocket] Joining approvals rooms for roles:', roles)
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
 * Subscribe to HITL progress events
 */
export const onHITLProgress = (callback) => {
  return registerCallback('progress', callback)
}

/**
 * Subscribe to HITL notification events
 */
export const onHITLNotification = (callback) => {
  return registerCallback('notification', callback)
}

/**
 * Disconnect the socket
 */
export const disconnectSocket = () => {
  if (socket) {
    socket.close()
    socket = null
    reconnectAttempts = 0
    console.log('[WebSocket] Disconnected')
  }
}
