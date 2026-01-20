/**
 * WebSocket Service for Druppie Real-time Updates
 */

import { io } from 'socket.io-client'
import { getToken } from './keycloak'

const SOCKET_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

let socket = null
let reconnectAttempts = 0
const MAX_RECONNECT_ATTEMPTS = 5

/**
 * Initialize socket connection
 */
export const initSocket = () => {
  if (socket?.connected) {
    return socket
  }

  const token = getToken()

  socket = io(SOCKET_URL, {
    auth: {
      token: token,
    },
    transports: ['websocket', 'polling'],
    reconnection: true,
    reconnectionAttempts: MAX_RECONNECT_ATTEMPTS,
    reconnectionDelay: 1000,
  })

  socket.on('connect', () => {
    console.log('[Socket] Connected:', socket.id)
    reconnectAttempts = 0
  })

  socket.on('disconnect', (reason) => {
    console.log('[Socket] Disconnected:', reason)
  })

  socket.on('connect_error', (error) => {
    console.error('[Socket] Connection error:', error.message)
    reconnectAttempts++
    if (reconnectAttempts >= MAX_RECONNECT_ATTEMPTS) {
      console.error('[Socket] Max reconnection attempts reached')
    }
  })

  socket.on('connected', (data) => {
    console.log('[Socket] Server confirmed connection:', data)
  })

  return socket
}

/**
 * Get the socket instance
 */
export const getSocket = () => {
  if (!socket) {
    return initSocket()
  }
  return socket
}

/**
 * Join a plan room for real-time updates
 */
export const joinPlanRoom = (planId) => {
  const s = getSocket()
  if (s && planId) {
    s.emit('join_plan', { plan_id: planId })
    console.log('[Socket] Joining plan room:', planId)
  }
}

/**
 * Join approvals rooms for the user's roles
 */
export const joinApprovalsRoom = (roles) => {
  const s = getSocket()
  if (s && roles?.length > 0) {
    s.emit('join_approvals', { roles })
    console.log('[Socket] Joining approvals rooms for roles:', roles)
  }
}

/**
 * Subscribe to task approved events
 */
export const onTaskApproved = (callback) => {
  const s = getSocket()
  if (s) {
    s.on('task_approved', callback)
    return () => s.off('task_approved', callback)
  }
  return () => {}
}

/**
 * Subscribe to task rejected events
 */
export const onTaskRejected = (callback) => {
  const s = getSocket()
  if (s) {
    s.on('task_rejected', callback)
    return () => s.off('task_rejected', callback)
  }
  return () => {}
}

/**
 * Subscribe to plan updated events
 */
export const onPlanUpdated = (callback) => {
  const s = getSocket()
  if (s) {
    s.on('plan_updated', callback)
    return () => s.off('plan_updated', callback)
  }
  return () => {}
}

/**
 * Subscribe to workflow events
 */
export const onWorkflowEvent = (callback) => {
  const s = getSocket()
  if (s) {
    s.on('workflow_event', callback)
    return () => s.off('workflow_event', callback)
  }
  return () => {}
}

/**
 * Subscribe to approval requested events
 */
export const onApprovalRequested = (callback) => {
  const s = getSocket()
  if (s) {
    s.on('approval_requested', callback)
    return () => s.off('approval_requested', callback)
  }
  return () => {}
}

/**
 * Disconnect the socket
 */
export const disconnectSocket = () => {
  if (socket) {
    socket.disconnect()
    socket = null
    console.log('[Socket] Disconnected')
  }
}
