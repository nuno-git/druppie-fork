/**
 * ConversationSidebar - Session history sidebar with collapsible view
 * Includes search/filter functionality for finding sessions
 */

import React, { useState, useMemo } from 'react'
import {
  MessageSquare,
  Plus,
  ChevronRight,
  ChevronDown,
  History,
  Bug,
  Zap,
  Search,
  X,
} from 'lucide-react'
import { formatTokens, formatCost, calculateCost } from '../../utils/tokenUtils'

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
            <div className="flex items-center gap-2 mt-1 flex-wrap">
              <span className={`w-2 h-2 rounded-full ${getStatusColor(session.status)}`} />
              <span className="text-xs text-gray-500">{date}</span>
              {formatTokens(session.total_tokens) && (
                <span className="text-xs bg-yellow-100 text-yellow-700 px-1.5 py-0.5 rounded flex items-center gap-0.5" title={`${session.total_tokens?.toLocaleString() || 0} tokens (${formatCost(calculateCost(session.total_tokens)) || '<$0.01'})`}>
                  <Zap className="w-2.5 h-2.5" />
                  {formatTokens(session.total_tokens)}
                  {formatCost(calculateCost(session.total_tokens)) && (
                    <span className="text-yellow-600 ml-0.5">{formatCost(calculateCost(session.total_tokens))}</span>
                  )}
                </span>
              )}
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
  const [searchQuery, setSearchQuery] = useState('')
  const [statusFilter, setStatusFilter] = useState('all') // all, completed, failed, running

  // Extract sessions array from paginated response or use directly if already an array
  const sessionList = Array.isArray(sessions) ? sessions : (sessions?.sessions || [])
  const totalSessions = Array.isArray(sessions) ? sessions.length : (sessions?.total || 0)

  // Filter sessions based on search query and status
  const filteredSessions = useMemo(() => {
    let filtered = sessionList

    // Apply status filter
    if (statusFilter !== 'all') {
      filtered = filtered.filter(session => {
        if (statusFilter === 'completed') return session.status === 'completed'
        if (statusFilter === 'failed') return session.status === 'failed'
        if (statusFilter === 'running') return ['active', 'running', 'paused', 'pending_approval', 'paused_hitl'].includes(session.status)
        return true
      })
    }

    // Apply text search
    if (searchQuery.trim()) {
      const query = searchQuery.toLowerCase()
      filtered = filtered.filter(session => {
        const preview = (session.preview || session.name || '').toLowerCase()
        const projectName = (session.project_name || '').toLowerCase()
        return preview.includes(query) || projectName.includes(query)
      })
    }

    return filtered
  }, [sessionList, searchQuery, statusFilter])

  // Count sessions by status for filter badges
  const statusCounts = useMemo(() => {
    const counts = { completed: 0, failed: 0, running: 0 }
    sessionList.forEach(session => {
      if (session.status === 'completed') counts.completed++
      else if (session.status === 'failed') counts.failed++
      else if (['active', 'running', 'paused', 'pending_approval', 'paused_hitl'].includes(session.status)) counts.running++
    })
    return counts
  }, [sessionList])

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
        {/* Search input */}
        <div className="relative mt-3">
          <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 w-4 h-4 text-gray-400" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search sessions..."
            className="w-full pl-9 pr-8 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            aria-label="Search sessions"
          />
          {searchQuery && (
            <button
              onClick={() => setSearchQuery('')}
              className="absolute right-2 top-1/2 transform -translate-y-1/2 p-1 hover:bg-gray-100 rounded"
              aria-label="Clear search"
            >
              <X className="w-3 h-3 text-gray-400" />
            </button>
          )}
        </div>
        {/* Status filter chips */}
        <div className="flex flex-wrap gap-1.5 mt-2">
          <button
            onClick={() => setStatusFilter('all')}
            className={`text-xs px-2 py-1 rounded-full transition-colors ${
              statusFilter === 'all'
                ? 'bg-gray-800 text-white'
                : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
            }`}
          >
            All
          </button>
          <button
            onClick={() => setStatusFilter('completed')}
            className={`text-xs px-2 py-1 rounded-full transition-colors flex items-center gap-1 ${
              statusFilter === 'completed'
                ? 'bg-green-600 text-white'
                : 'bg-green-50 text-green-700 hover:bg-green-100'
            }`}
          >
            <span className="w-1.5 h-1.5 rounded-full bg-current" />
            {statusCounts.completed}
          </button>
          {statusCounts.failed > 0 && (
            <button
              onClick={() => setStatusFilter('failed')}
              className={`text-xs px-2 py-1 rounded-full transition-colors flex items-center gap-1 ${
                statusFilter === 'failed'
                  ? 'bg-red-600 text-white'
                  : 'bg-red-50 text-red-700 hover:bg-red-100'
              }`}
            >
              <span className="w-1.5 h-1.5 rounded-full bg-current" />
              {statusCounts.failed}
            </button>
          )}
          {statusCounts.running > 0 && (
            <button
              onClick={() => setStatusFilter('running')}
              className={`text-xs px-2 py-1 rounded-full transition-colors flex items-center gap-1 ${
                statusFilter === 'running'
                  ? 'bg-blue-600 text-white'
                  : 'bg-blue-50 text-blue-700 hover:bg-blue-100'
              }`}
            >
              <span className="w-1.5 h-1.5 rounded-full bg-current animate-pulse" />
              {statusCounts.running}
            </button>
          )}
        </div>
      </div>

      {/* Conversation List */}
      <div className="flex-1 overflow-y-auto p-2">
        <div className="flex items-center justify-between px-2 py-2">
          <div className="flex items-center gap-2 text-xs font-medium text-gray-500 uppercase">
            <History className="w-3 h-3" />
            {(searchQuery || statusFilter !== 'all') ? `Results (${filteredSessions.length})` : 'Recent Conversations'}
          </div>
        </div>
        <div className="space-y-1">
          {filteredSessions.length > 0 ? (
            filteredSessions.map((session) => (
              <ConversationItem
                key={session.id}
                session={session}
                isActive={session.id === activeSessionId}
                onClick={() => onSelectSession(session)}
                onDebug={onDebugSession}
              />
            ))
          ) : searchQuery ? (
            <div className="text-center py-8 text-gray-500 text-sm">
              <Search className="w-8 h-8 mx-auto mb-2 opacity-30" />
              <p>No matching sessions</p>
              <p className="text-xs mt-1">Try a different search term</p>
            </div>
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
