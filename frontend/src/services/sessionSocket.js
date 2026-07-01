import { getToken } from './keycloak'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

class SessionSocket {
  constructor(sessionId, onMessage) {
    this.sessionId = sessionId
    this.onMessage = onMessage
    this.ws = null
    this.reconnectAttempts = 0
    this.maxReconnectAttempts = 5
    this._disconnected = false
  }

  connect() {
    if (this._disconnected) return
    const token = getToken()
    if (!token) return

    const apiUrl = new URL(API_URL)
    const protocol = apiUrl.protocol === 'https:' ? 'wss:' : 'ws:'
    const wsUrl = `${protocol}//${apiUrl.host}/api/sessions/${this.sessionId}/events?token=${token}`

    this.ws = new WebSocket(wsUrl)
    this.ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)
        this.onMessage(data)
      } catch (e) {
        console.error('SessionSocket: failed to parse message', e)
      }
    }
    this.ws.onclose = () => {
      if (this._disconnected) return
      if (this.reconnectAttempts < this.maxReconnectAttempts) {
        const delay = Math.min(1000 * Math.pow(2, this.reconnectAttempts), 5000)
        this.reconnectAttempts++
        setTimeout(() => this.connect(), delay)
      }
    }
    this.ws.onerror = () => {
      // onclose will fire after onerror, triggering reconnect
    }
  }

  disconnect() {
    this._disconnected = true
    if (this.ws) {
      this.ws.close()
      this.ws = null
    }
  }
}

export default SessionSocket
