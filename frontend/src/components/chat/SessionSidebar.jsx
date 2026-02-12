/**
 * Session Sidebar - left panel showing session list in Chat
 */

import { useState, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Plus, Search, PanelLeftClose } from 'lucide-react'
import { getSessions } from '../../services/api'
import { timeAgo, ACTIVE_STATUSES } from './ChatHelpers'
import { SkeletonSidebarItem } from '../shared/Skeleton'

const groupSessionsByDate = (sessions) => {
  // Sort by most recent interaction first
  const sorted = [...sessions].sort(
    (a, b) => new Date(b.updated_at || b.created_at) - new Date(a.updated_at || a.created_at)
  )

  const now = new Date()
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const yesterday = new Date(today - 86400000)
  const lastWeek = new Date(today - 7 * 86400000)

  const groups = { today: [], yesterday: [], lastWeek: [], older: [] }
  sorted.forEach((s) => {
    const date = new Date(s.updated_at || s.created_at)
    if (date >= today) groups.today.push(s)
    else if (date >= yesterday) groups.yesterday.push(s)
    else if (date >= lastWeek) groups.lastWeek.push(s)
    else groups.older.push(s)
  })

  return [
    { key: 'today', label: 'Today', sessions: groups.today },
    { key: 'yesterday', label: 'Yesterday', sessions: groups.yesterday },
    { key: 'lastWeek', label: 'Last 7 days', sessions: groups.lastWeek },
    { key: 'older', label: 'Older', sessions: groups.older },
  ].filter((g) => g.sessions.length > 0)
}

const SessionSidebar = ({ activeSessionId, onSelectSession, onNewChat, onCollapse }) => {
  const [search, setSearch] = useState('')
  const { data, isLoading } = useQuery({
    queryKey: ['sessions'],
    queryFn: () => getSessions(1, 50),
    refetchInterval: 5000,
  })

  const sessions = data?.items || []
  const filtered = search
    ? sessions.filter((s) =>
        (s.title || '').toLowerCase().includes(search.toLowerCase()) ||
        (s.project_name || '').toLowerCase().includes(search.toLowerCase())
      )
    : sessions

  const grouped = useMemo(() => groupSessionsByDate(filtered), [filtered])

  return (
    <div className="flex flex-col h-full">
      <div className="px-3 py-3 border-b flex items-center justify-between gap-2">
        <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wider">
          Sessions
        </h2>
        <div className="flex items-center gap-1">
          <button
            onClick={onNewChat}
            className="p-1.5 rounded-lg bg-blue-600 text-white hover:bg-blue-700 transition-colors"
            title="New chat"
          >
            <Plus className="w-4 h-4" />
          </button>
          <button
            onClick={onCollapse}
            className="p-1.5 rounded-lg text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition-colors"
            title="Collapse sidebar"
          >
            <PanelLeftClose className="w-4 h-4" />
          </button>
        </div>
      </div>
      <div className="px-3 py-2 border-b">
        <div className="relative">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search sessions..."
            className="w-full pl-8 pr-3 py-1.5 text-sm border rounded-lg focus:outline-none focus:ring-1 focus:ring-blue-400"
          />
        </div>
      </div>
      <div className="flex-1 overflow-y-auto">
        {isLoading && (
          <div className="space-y-1 py-2">
            {Array.from({ length: 5 }).map((_, i) => <SkeletonSidebarItem key={i} />)}
          </div>
        )}
        {!isLoading && filtered.length === 0 && (
          <p className="text-gray-400 text-sm text-center py-8">
            {search ? 'No matching sessions' : 'No sessions yet'}
          </p>
        )}
        {grouped.map((group) => (
          <div key={group.key}>
            <div className="px-4 py-1.5 text-[11px] font-medium text-gray-400 uppercase tracking-wider sticky top-0 bg-white/95 backdrop-blur-sm border-b border-gray-100">
              {group.label}
            </div>
            {group.sessions.map((s) => {
              const isActive = ACTIVE_STATUSES.has(s.status)
              const isRunning = s.status === 'running'
              const isFailed = s.status === 'failed'
              return (
                <button
                  key={s.id}
                  onClick={() => onSelectSession(s.id)}
                  className={`w-full text-left px-4 py-2.5 hover:bg-gray-50 transition-colors ${
                    activeSessionId === s.id
                      ? 'bg-blue-50 border-l-2 border-l-blue-600'
                      : 'border-l-2 border-l-transparent'
                  }`}
                >
                  <div className="flex items-center gap-2">
                    {isActive && (
                      <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 animate-pulse ${
                        isRunning ? 'bg-blue-500' : 'bg-blue-400'
                      }`} />
                    )}
                    {isFailed && (
                      <span className="w-1.5 h-1.5 rounded-full flex-shrink-0 bg-red-400" />
                    )}
                    <span className="text-sm font-medium truncate text-gray-900">
                      {s.title || 'Untitled'}
                    </span>
                  </div>
                  <div className={`flex items-center gap-2 mt-0.5 ${isActive || isFailed ? 'ml-3.5' : ''}`}>
                    {s.project_name && (
                      <span className="text-xs text-gray-400 truncate">
                        {s.project_name}
                      </span>
                    )}
                    <span className="text-xs text-gray-300 ml-auto">
                      {timeAgo(s.updated_at || s.created_at)}
                    </span>
                  </div>
                </button>
              )
            })}
          </div>
        ))}
      </div>
    </div>
  )
}

export default SessionSidebar
