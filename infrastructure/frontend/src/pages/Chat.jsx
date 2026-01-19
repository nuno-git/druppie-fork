/**
 * Chat Page - Main interface for Druppie governance
 */

import React, { useState, useRef, useEffect } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Send, Bot, User, AlertCircle, CheckCircle, Loader2 } from 'lucide-react'
import { sendChat } from '../services/api'
import { useAuth } from '../App'

const Message = ({ message }) => {
  const isUser = message.role === 'user'

  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'} mb-4`}>
      <div
        className={`max-w-[80%] rounded-2xl px-4 py-3 ${
          isUser
            ? 'bg-blue-600 text-white rounded-br-none'
            : 'bg-white border border-gray-200 rounded-bl-none'
        }`}
      >
        <div className="flex items-start space-x-2">
          {!isUser && (
            <div className="w-6 h-6 rounded-full bg-blue-100 flex items-center justify-center flex-shrink-0">
              <Bot className="w-4 h-4 text-blue-600" />
            </div>
          )}
          <div className="flex-1">
            <p className="whitespace-pre-wrap">{message.content}</p>

            {/* Pending Approvals */}
            {message.pendingApprovals && message.pendingApprovals.length > 0 && (
              <div className="mt-3 p-3 bg-yellow-50 rounded-lg border border-yellow-200">
                <div className="flex items-center text-yellow-700 mb-2">
                  <AlertCircle className="w-4 h-4 mr-2" />
                  <span className="font-medium">Pending Approvals</span>
                </div>
                <ul className="text-sm text-yellow-800 space-y-1">
                  {message.pendingApprovals.map((approval, i) => (
                    <li key={i} className="flex items-center">
                      <span className="w-2 h-2 rounded-full bg-yellow-500 mr-2" />
                      {approval.task_name} - requires{' '}
                      <span className="font-medium ml-1">{approval.required_role}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {/* Plan ID */}
            {message.planId && (
              <div className="mt-2 text-xs opacity-70">Plan: {message.planId}</div>
            )}
          </div>
          {isUser && (
            <div className="w-6 h-6 rounded-full bg-blue-500 flex items-center justify-center flex-shrink-0">
              <User className="w-4 h-4 text-white" />
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

const Chat = () => {
  const { user } = useAuth()
  const [messages, setMessages] = useState([
    {
      role: 'assistant',
      content: `Hello ${user?.firstName || user?.username}! I'm Druppie, your AI governance assistant.

I can help you:
- Create and execute plans
- Manage code deployments (requires infra-engineer approval)
- Write and modify code
- Check compliance

What would you like to work on today?`,
    },
  ])
  const [input, setInput] = useState('')
  const [currentPlanId, setCurrentPlanId] = useState(null)
  const messagesEndRef = useRef(null)
  const queryClient = useQueryClient()

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }

  useEffect(() => {
    scrollToBottom()
  }, [messages])

  const chatMutation = useMutation({
    mutationFn: (message) => sendChat(message, currentPlanId),
    onSuccess: (data) => {
      setMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          content: data.response,
          planId: data.plan_id,
          pendingApprovals: data.pending_approvals,
          status: data.status,
        },
      ])
      setCurrentPlanId(data.plan_id)
      queryClient.invalidateQueries(['plans'])
      queryClient.invalidateQueries(['tasks'])
    },
    onError: (error) => {
      setMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          content: `Error: ${error.message}`,
        },
      ])
    },
  })

  const handleSubmit = (e) => {
    e.preventDefault()
    if (!input.trim() || chatMutation.isPending) return

    const userMessage = input.trim()
    setInput('')

    setMessages((prev) => [...prev, { role: 'user', content: userMessage }])
    chatMutation.mutate(userMessage)
  }

  const suggestions = [
    'Create a simple calculator application',
    'Deploy the latest changes to production',
    'Check compliance for user data handling',
    'Build a REST API with authentication',
  ]

  return (
    <div className="h-[calc(100vh-12rem)] flex flex-col">
      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-4 space-y-2">
        {messages.map((message, index) => (
          <Message key={index} message={message} />
        ))}

        {chatMutation.isPending && (
          <div className="flex justify-start mb-4">
            <div className="bg-white border border-gray-200 rounded-2xl rounded-bl-none px-4 py-3">
              <div className="flex items-center space-x-2">
                <div className="w-6 h-6 rounded-full bg-blue-100 flex items-center justify-center">
                  <Loader2 className="w-4 h-4 text-blue-600 animate-spin" />
                </div>
                <span className="text-gray-500">Thinking...</span>
              </div>
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Suggestions (show only at start) */}
      {messages.length <= 1 && (
        <div className="px-4 pb-4">
          <p className="text-sm text-gray-500 mb-2">Try asking:</p>
          <div className="flex flex-wrap gap-2">
            {suggestions.map((suggestion, index) => (
              <button
                key={index}
                onClick={() => setInput(suggestion)}
                className="px-3 py-1.5 bg-gray-100 hover:bg-gray-200 rounded-full text-sm text-gray-700 transition-colors"
              >
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
            placeholder="Type your message..."
            className="flex-1 px-4 py-3 border border-gray-300 rounded-xl focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            disabled={chatMutation.isPending}
          />
          <button
            type="submit"
            disabled={!input.trim() || chatMutation.isPending}
            className="px-6 py-3 bg-blue-600 text-white rounded-xl hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            <Send className="w-5 h-5" />
          </button>
        </div>
        {currentPlanId && (
          <div className="mt-2 flex items-center text-sm text-gray-500">
            <CheckCircle className="w-4 h-4 mr-1 text-green-500" />
            Active Plan: {currentPlanId}
            <button
              type="button"
              onClick={() => setCurrentPlanId(null)}
              className="ml-2 text-blue-600 hover:underline"
            >
              Start new plan
            </button>
          </div>
        )}
      </form>
    </div>
  )
}

export default Chat
