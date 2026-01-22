/**
 * ConversationSidebar - Session history sidebar with collapsible view
 */

import React from 'react'
import {
  MessageSquare,
  Plus,
  ChevronRight,
  ChevronDown,
  History,
  Bug,
} from 'lucide-react'

// Individual conversation item
const ConversationItem = ({ session, isActive, onClick, onDebug }) => {
  const getStatusColor = (status) => {
    switch (status) {
      case 'completed':
        return 'bg-green-500'
      case 'active':
      case 'running':
        return 'bg-blue-500'
      case 'paused':
      case 'pending_approval':
        return 'bg-yellow-500'
      case 'failed':
        return 'bg-red-500'
      default:
        return 'bg-gray-400'
    }
  }

  // Use preview from new API format, or fall back to name for legacy format
  const preview = session.preview || session.name?.replace(/^Chat:\s*/i, '').slice(0, 50) || 'No message'
  const date = session.created_at ? new Date(session.created_at).toLocaleDateString() : ''

  return (
    <div
      className={`group w-full text-left p-3 rounded-lg transition-all ${
        isActive
          ? 'bg-blue-50 border border-blue-200'
          : 'hover:bg-gray-50 border border-transparent'
      }`}
    >
      <button onClick={onClick} className="w-full text-left">
        <div className="flex items-start gap-2">
          <MessageSquare className={`w-4 h-4 mt-0.5 flex-shrink-0 ${isActive ? 'text-blue-600' : 'text-gray-400'}`} />
          <div className="flex-1 min-w-0">
            <div className={`text-sm font-medium truncate ${isActive ? 'text-blue-900' : 'text-gray-800'}`}>
              {preview.length > 40 ? `${preview.slice(0, 40)}...` : preview}
            </div>
            <div className="flex items-center gap-2 mt-1">
              <span className={`w-2 h-2 rounded-full ${getStatusColor(session.status)}`} />
              <span className="text-xs text-gray-500">{date}</span>
              {session.project_name && (
                <span className="text-xs bg-purple-100 text-purple-700 px-1.5 py-0.5 rounded truncate max-w-[80px]">
                  {session.project_name}
                </span>
              )}
            </div>
          </div>
        </div>
      </button>
      {/* Debug link - visible on hover */}
      <div className="flex justify-end mt-1 opacity-0 group-hover:opacity-100 transition-opacity">
        <button
          onClick={(e) => {
            e.stopPropagation()
            onDebug(session.id)
          }}
          className="text-xs text-gray-500 hover:text-orange-600 flex items-center gap-1 focus:outline-none focus:ring-2 focus:ring-orange-500 rounded"
          aria-label="View debug trace for this session"
        >
          <Bug className="w-3 h-3" aria-hidden="true" />
          Debug
        </button>
      </div>
    </div>
  )
}

// Main sidebar component
const ConversationSidebar = ({
  sessions,
  activeSessionId,
  onSelectSession,
  onNewChat,
  onDebugSession,
  isCollapsed,
  onToggleCollapse,
}) => {
  // Extract sessions array from paginated response or use directly if already an array
  const sessionList = Array.isArray(sessions) ? sessions : (sessions?.sessions || [])
  const totalSessions = Array.isArray(sessions) ? sessions.length : (sessions?.total || 0)

  if (isCollapsed) {
    return (
      <div className="w-12 bg-white border-r border-gray-200 flex flex-col h-full">
        {/* Collapsed header with expand button */}
        <div className="p-2 border-b border-gray-200">
          <button
            onClick={onToggleCollapse}
            className="w-8 h-8 flex items-center justify-center bg-gray-100 hover:bg-gray-200 rounded-lg transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500"
            aria-label="Expand sidebar"
            aria-expanded="false"
          >
            <ChevronRight className="w-4 h-4 text-gray-600" aria-hidden="true" />
          </button>
        </div>
        {/* Collapsed new chat button */}
        <div className="p-2">
          <button
            onClick={onNewChat}
            className="w-8 h-8 flex items-center justify-center bg-gradient-to-r from-blue-600 to-purple-600 text-white rounded-lg hover:from-blue-700 hover:to-purple-700 transition-all shadow-md focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2"
            aria-label="Start new chat"
          >
            <Plus className="w-4 h-4" aria-hidden="true" />
          </button>
        </div>
        {/* Collapsed session indicators */}
        <div className="flex-1 overflow-y-auto p-2 space-y-2">
          {sessionList.slice(0, 10).map((session) => (
            <button
              key={session.id}
              onClick={() => onSelectSession(session)}
              className={`w-8 h-8 flex items-center justify-center rounded-lg transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500 ${
                session.id === activeSessionId
                  ? 'bg-blue-100 border border-blue-300'
                  : 'bg-gray-50 hover:bg-gray-100'
              }`}
              aria-label={`Select session: ${session.preview || 'Session'}`}
              aria-current={session.id === activeSessionId ? 'true' : undefined}
            >
              <MessageSquare className={`w-4 h-4 ${session.id === activeSessionId ? 'text-blue-600' : 'text-gray-400'}`} aria-hidden="true" />
            </button>
          ))}
        </div>
      </div>
    )
  }

  return (
    <div className="w-72 bg-white border-r border-gray-200 flex flex-col h-full">
      {/* Header with collapse button */}
      <div className="p-4 border-b border-gray-200">
        <div className="flex items-center gap-2 mb-3">
          <button
            onClick={onToggleCollapse}
            className="p-1.5 hover:bg-gray-100 rounded-lg transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500"
            aria-label="Collapse sidebar"
            aria-expanded="true"
          >
            <ChevronDown className="w-4 h-4 text-gray-500 rotate-90" aria-hidden="true" />
          </button>
          <span className="text-sm font-medium text-gray-700">Session History</span>
          {totalSessions > 0 && (
            <span className="text-xs bg-gray-100 text-gray-600 px-2 py-0.5 rounded-full ml-auto">
              {totalSessions}
            </span>
          )}
        </div>
        <button
          onClick={onNewChat}
          className="w-full flex items-center justify-center gap-2 px-4 py-2.5 bg-gradient-to-r from-blue-600 to-purple-600 text-white rounded-lg hover:from-blue-700 hover:to-purple-700 transition-all shadow-md focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2"
        >
          <Plus className="w-4 h-4" aria-hidden="true" />
          New Chat
        </button>
      </div>

      {/* Conversation List */}
      <div className="flex-1 overflow-y-auto p-2">
        <div className="flex items-center gap-2 px-2 py-2 text-xs font-medium text-gray-500 uppercase">
          <History className="w-3 h-3" />
          Recent Conversations
        </div>
        <div className="space-y-1">
          {sessionList.length > 0 ? (
            sessionList.map((session) => (
              <ConversationItem
                key={session.id}
                session={session}
                isActive={session.id === activeSessionId}
                onClick={() => onSelectSession(session)}
                onDebug={onDebugSession}
              />
            ))
          ) : (
            <div className="text-center py-8 text-gray-500 text-sm">
              <MessageSquare className="w-8 h-8 mx-auto mb-2 opacity-30" />
              <p>No conversations yet</p>
              <p className="text-xs mt-1">Start a new chat!</p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

export default ConversationSidebar
