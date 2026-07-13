import { getToken } from './keycloak'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

class SessionSocket {
  constructor(sessionId, onMessage, options = {}) {
    this.sessionId = sessionId
    this.onMessage = onMessage

    // Callbacks for connection lifecycle (replacing raw ws patching)
    this.onOpen = options.onOpen || (() => {})
    this.onAuthenticated = options.onAuthenticated || (() => {})
    this.onClose = options.onClose || (() => {})
    this.onError = options.onError || (() => {})

    this.ws = null
    this.reconnectAttempts = 0
    this.maxReconnectAttempts = 5
    this._disconnected = false
    this._authenticated = false
  }

  connect() {
    if (this._disconnected) return
    const token = getToken()
    if (!token) {
      console.log('SessionSocket: no token, skipping connect')
      return
    }

    const apiUrl = new URL(API_URL)
    const protocol = apiUrl.protocol === 'https:' ? 'wss:' : 'ws:'
    const wsUrl = `${protocol}//${apiUrl.host}/api/sessions/${this.sessionId}/events`

    this.ws = new WebSocket(wsUrl)

    this.ws.onopen = () => {
      this.onOpen()
      this.ws.send(JSON.stringify({ type: 'auth', token }))
    }

    this.ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)

        if (data.type === 'auth_success') {
          this._authenticated = true
          this.reconnectAttempts = 0
          this.onAuthenticated()
          return
        }

        if (!this._authenticated) {
          return
        }

        this.onMessage(data)
      } catch (e) {
        console.error('SessionSocket: failed to parse message', e)
      }
    }

    this.ws.onclose = (e) => {
      this._authenticated = false
      this.onClose()
      if (this._disconnected) return
      if (this.reconnectAttempts < this.maxReconnectAttempts) {
        const delay = Math.min(1000 * Math.pow(2, this.reconnectAttempts), 5000)
        this.reconnectAttempts++
        setTimeout(() => this.connect(), delay)
      }
    }

    this.ws.onerror = () => {
      this.onError()
    }
  }

  disconnect() {
    this._disconnected = true
    if (this.ws) {
      try {
        this.ws.close()
      } catch (e) {
        console.error('SessionSocket: error during disconnect', e)
      }
      this.ws = null
    }
  }
}

export default SessionSocket
