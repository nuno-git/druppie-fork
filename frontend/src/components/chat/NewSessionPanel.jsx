/**
 * New Session Panel - shown when no session is selected in Chat
 */

import { useState, useRef, useEffect } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Send, Shield } from 'lucide-react'
import { sendChat } from '../../services/api'

const NEW_SESSION_SUGGESTIONS = [
  'Set up a new project',
  'Review my code architecture',
  'Help me deploy an app',
  'Write a feature specification',
]

const NewSessionPanel = ({ onSessionCreated }) => {
  const [input, setInput] = useState('')
  const inputRef = useRef(null)
  const queryClient = useQueryClient()

  const mutation = useMutation({
    mutationFn: (message) => sendChat(message),
    onSuccess: (data) => {
      setInput('')
      queryClient.invalidateQueries({ queryKey: ['sessions'] })
      if (data.session_id) {
        onSessionCreated(data.session_id)
      }
    },
  })

  // Auto-resize textarea
  useEffect(() => {
    if (inputRef.current) {
      inputRef.current.style.height = 'auto'
      inputRef.current.style.height = Math.min(inputRef.current.scrollHeight, 160) + 'px'
    }
  }, [input])

  const handleSend = (text) => {
    const trimmed = (text || input).trim()
    if (!trimmed) return
    mutation.mutate(trimmed)
  }

  return (
    <div className="flex flex-col h-full">
      {/* Center greeting */}
      <div className="flex-1 flex flex-col items-center justify-center px-4">
        <div className="w-12 h-12 bg-blue-600 rounded-xl flex items-center justify-center mb-6">
          <Shield className="w-7 h-7 text-white" />
        </div>
        <h1 className="text-2xl font-semibold text-gray-900 mb-2">
          What would you like to build?
        </h1>
        <p className="text-gray-400 text-sm mb-8">
          Start a new governance session with Druppie
        </p>
        <div className="flex flex-wrap justify-center gap-2 max-w-lg">
          {NEW_SESSION_SUGGESTIONS.map((s) => (
            <button
              key={s}
              onClick={() => handleSend(s)}
              disabled={mutation.isPending}
              className="px-4 py-2 text-sm border border-gray-200 rounded-full text-gray-600 hover:bg-gray-50 hover:border-gray-300 transition-colors disabled:opacity-50"
            >
              {s}
            </button>
          ))}
        </div>
      </div>

      {/* Floating input bar */}
      <div className="px-4 pb-4 pt-2 flex-shrink-0">
        <div className="max-w-3xl mx-auto">
          <div className="flex items-end gap-2 border border-gray-200 rounded-2xl shadow-lg px-4 py-3 bg-white focus-within:border-gray-300 focus-within:shadow-xl transition-shadow">
            <textarea
              ref={inputRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey && !mutation.isPending) {
                  e.preventDefault()
                  handleSend()
                }
              }}
              placeholder="Describe what you'd like to build..."
              rows={1}
              className="flex-1 resize-none bg-transparent outline-none text-sm leading-6 py-1 max-h-40"
              disabled={mutation.isPending}
            />
            <button
              onClick={() => handleSend()}
              disabled={!input.trim() || mutation.isPending}
              className="flex-shrink-0 p-2 rounded-xl bg-gray-900 text-white hover:bg-gray-700 disabled:opacity-30 disabled:hover:bg-gray-900 transition-colors"
            >
              {mutation.isPending ? (
                <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
              ) : (
                <Send className="w-4 h-4" />
              )}
            </button>
          </div>
          {mutation.isError && (
            <p className="mt-2 text-xs text-red-600 text-center">
              {mutation.error.message}
            </p>
          )}
        </div>
      </div>
    </div>
  )
}

export default NewSessionPanel
