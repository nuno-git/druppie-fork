/**
 * NewChat - Simple debug page for testing the new backend API
 *
 * Shows raw JSON responses from:
 * - GET /api/sessions (list sessions)
 * - GET /api/sessions/{id} (session details)
 * - POST /api/chat (send message)
 */

import React, { useState, useEffect } from 'react'
import { getToken } from '../services/keycloak'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

// Simple fetch wrapper that logs everything
const apiFetch = async (endpoint, options = {}) => {
  const token = getToken()

  const headers = {
    'Content-Type': 'application/json',
    ...options.headers,
  }

  if (token) {
    headers['Authorization'] = `Bearer ${token}`
  }

  const url = `${API_URL}${endpoint}`
  const method = options.method || 'GET'

  console.log('========================================')
  console.log(`API ${method} ${endpoint}`)
  console.log('URL:', url)
  console.log('Headers:', headers)
  if (options.body) {
    console.log('Body:', JSON.parse(options.body))
  }
  console.log('----------------------------------------')

  try {
    const response = await fetch(url, { ...options, headers })
    const data = await response.json()

    console.log('Status:', response.status)
    console.log('Response:', data)
    console.log('========================================')

    return { ok: response.ok, status: response.status, data }
  } catch (err) {
    console.error('Error:', err)
    console.log('========================================')
    return { ok: false, error: err.message }
  }
}

export default function NewChat() {
  const [sessions, setSessions] = useState(null)
  const [selectedSession, setSelectedSession] = useState(null)
  const [sessionDetail, setSessionDetail] = useState(null)
  const [message, setMessage] = useState('')
  const [chatResponse, setChatResponse] = useState(null)
  const [loading, setLoading] = useState({})

  // Fetch sessions on mount
  useEffect(() => {
    fetchSessions()
  }, [])

  const fetchSessions = async () => {
    setLoading(l => ({ ...l, sessions: true }))
    const result = await apiFetch('/api/sessions')
    setSessions(result)
    setLoading(l => ({ ...l, sessions: false }))
  }

  const fetchSessionDetail = async (sessionId) => {
    setSelectedSession(sessionId)
    setSessionDetail(null)
    setLoading(l => ({ ...l, detail: true }))
    const result = await apiFetch(`/api/sessions/${sessionId}`)
    setSessionDetail(result)
    setLoading(l => ({ ...l, detail: false }))
  }

  const sendChat = async () => {
    if (!message.trim()) return

    setLoading(l => ({ ...l, chat: true }))
    setChatResponse(null)

    const result = await apiFetch('/api/chat', {
      method: 'POST',
      body: JSON.stringify({ message: message.trim() }),
    })

    setChatResponse(result)
    setLoading(l => ({ ...l, chat: false }))

    // Refresh sessions list after sending
    if (result.ok) {
      fetchSessions()
    }
  }

  return (
    <div className="p-4 space-y-6">
      <h1 className="text-2xl font-bold">New Chat - API Debug Page</h1>
      <p className="text-gray-600">Check browser console for detailed API logs</p>

      {/* Send Chat Section */}
      <div className="border rounded-lg p-4 bg-white">
        <h2 className="text-lg font-semibold mb-3">POST /api/chat</h2>
        <div className="flex gap-2">
          <input
            type="text"
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && sendChat()}
            placeholder="Type a message..."
            className="flex-1 px-3 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
          <button
            onClick={sendChat}
            disabled={loading.chat || !message.trim()}
            className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50"
          >
            {loading.chat ? 'Sending...' : 'Send'}
          </button>
        </div>

        {chatResponse && (
          <div className="mt-4">
            <h3 className="font-medium mb-2">Response:</h3>
            <pre className="bg-gray-100 p-3 rounded-lg text-sm overflow-auto max-h-60">
              {JSON.stringify(chatResponse, null, 2)}
            </pre>
          </div>
        )}
      </div>

      {/* Sessions List Section */}
      <div className="border rounded-lg p-4 bg-white">
        <div className="flex justify-between items-center mb-3">
          <h2 className="text-lg font-semibold">GET /api/sessions</h2>
          <button
            onClick={fetchSessions}
            disabled={loading.sessions}
            className="px-3 py-1 bg-gray-200 rounded hover:bg-gray-300 text-sm"
          >
            {loading.sessions ? 'Loading...' : 'Refresh'}
          </button>
        </div>

        {sessions && (
          <div>
            <h3 className="font-medium mb-2">Raw Response:</h3>
            <pre className="bg-gray-100 p-3 rounded-lg text-sm overflow-auto max-h-40 mb-4">
              {JSON.stringify(sessions, null, 2)}
            </pre>

            {/* Clickable session list */}
            {sessions.ok && sessions.data?.items && (
              <div>
                <h3 className="font-medium mb-2">Click a session to view details:</h3>
                <div className="space-y-2">
                  {sessions.data.items.map((session) => (
                    <button
                      key={session.id}
                      onClick={() => fetchSessionDetail(session.id)}
                      className={`w-full text-left p-3 rounded-lg border transition-colors ${
                        selectedSession === session.id
                          ? 'bg-blue-50 border-blue-300'
                          : 'hover:bg-gray-50'
                      }`}
                    >
                      <div className="font-medium truncate">{session.title || 'Untitled'}</div>
                      <div className="text-sm text-gray-500">
                        ID: {session.id} | Status: {session.status}
                      </div>
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Session Detail Section */}
      {selectedSession && (
        <div className="border rounded-lg p-4 bg-white">
          <h2 className="text-lg font-semibold mb-3">
            GET /api/sessions/{selectedSession}
          </h2>

          {loading.detail ? (
            <p className="text-gray-500">Loading...</p>
          ) : sessionDetail ? (
            <div>
              <h3 className="font-medium mb-2">Raw Response:</h3>
              <pre className="bg-gray-100 p-3 rounded-lg text-sm overflow-auto max-h-96">
                {JSON.stringify(sessionDetail, null, 2)}
              </pre>
            </div>
          ) : null}
        </div>
      )}
    </div>
  )
}
