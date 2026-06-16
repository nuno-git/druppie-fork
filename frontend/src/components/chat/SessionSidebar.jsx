/**
 * Session Sidebar - left panel showing session list in Chat
 */

import { useState, useMemo, useCallback, useRef, useEffect } from 'react'
import { useInfiniteQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Plus, Search, PanelLeftClose, Trash2, Loader2 } from 'lucide-react'
import { getSessions, deleteSession, deleteAllSessions } from '../../services/api'
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

const PAGE_SIZE = 50

const SessionSidebar = ({ activeSessionId, onSelectSession, onNewChat, onCollapse }) => {
  const [search, setSearch] = useState('')
  const [deletingId, setDeletingId] = useState(null)
  const queryClient = useQueryClient()
  const scrollRef = useRef(null)

  const {
    data,
    isLoading,
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
  } = useInfiniteQuery({
    queryKey: ['sessions'],
    queryFn: ({ pageParam = 1 }) => getSessions(pageParam, PAGE_SIZE),
    getNextPageParam: (lastPage) => {
      const { page, limit, total } = lastPage
      return page * limit < total ? page + 1 : undefined
    },
    refetchInterval: (query) => {
      const pageCount = query.state.data?.pages?.length ?? 0
      return pageCount > 1 ? 30000 : 5000
    },
  })

  const deleteMutation = useMutation({
    mutationFn: deleteSession,
    onMutate: (id) => setDeletingId(id),
    onSuccess: (_, deletedId) => {
      queryClient.invalidateQueries({ queryKey: ['sessions'] })
      if (activeSessionId === deletedId) onNewChat()
      setDeletingId(null)
    },
    onError: () => setDeletingId(null),
  })

  const deleteAllMutation = useMutation({
    mutationFn: deleteAllSessions,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['sessions'] })
      onNewChat()
    },
  })

  const handleDeleteAll = () => {
    if (sessions.length === 0) return
    if (window.confirm(`Delete all ${sessions.length} sessions?\n\nThis will permanently delete all your sessions and their data. This cannot be undone.`)) {
      deleteAllMutation.mutate()
    }
  }

  const handleDelete = (e, session) => {
    e.stopPropagation()
    if (window.confirm(`Delete session "${session.title || 'Untitled'}"?\n\nThis will permanently delete the session and all its data.`)) {
      deleteMutation.mutate(session.id)
    }
  }

  const sessions = useMemo(
    () => data?.pages?.flatMap((p) => p.items) || [],
    [data]
  )
  const total = data?.pages?.[0]?.total ?? 0

  const filtered = search
    ? sessions.filter((s) =>
        (s.title || '').toLowerCase().includes(search.toLowerCase()) ||
        (s.project_name || '').toLowerCase().includes(search.toLowerCase())
      )
    : sessions

  const grouped = useMemo(() => groupSessionsByDate(filtered), [filtered])

  const handleScroll = useCallback(() => {
    const el = scrollRef.current
    if (!el || !hasNextPage || isFetchingNextPage) return
    if (el.scrollHeight - el.scrollTop - el.clientHeight < 200) {
      fetchNextPage()
    }
  }, [hasNextPage, isFetchingNextPage, fetchNextPage])

  useEffect(() => {
    const el = scrollRef.current
    if (!el) return
    el.addEventListener('scroll', handleScroll)
    return () => el.removeEventListener('scroll', handleScroll)
  }, [handleScroll])

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
      <div className="flex-1 overflow-y-auto" ref={scrollRef}>
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
              const isRunning = s.status === 'active' || s.status === 'running'
              const isPaused = s.status === 'paused' || (s.status?.startsWith('paused_') && s.status !== 'paused_crashed') || s.status?.startsWith('waiting_')
              const isCrashed = s.status === 'paused_crashed'
              const isFailed = s.status === 'failed'
              return (
                <div
                  key={s.id}
                  className={`group relative w-full text-left px-4 py-2.5 hover:bg-gray-50 transition-colors cursor-pointer ${
                    activeSessionId === s.id
                      ? 'bg-blue-50 border-l-2 border-l-blue-600'
                      : 'border-l-2 border-l-transparent'
                  }`}
                  onClick={() => onSelectSession(s.id)}
                >
                  <div className="flex items-center gap-2">
                    {isActive && (
                      <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 animate-pulse ${
                        isPaused ? 'bg-amber-500' : 'bg-blue-500'
                      }`} />
                    )}
                    {(isFailed || isCrashed) && (
                      <span className="w-1.5 h-1.5 rounded-full flex-shrink-0 bg-red-400" />
                    )}
                    <span className="text-sm font-medium truncate text-gray-900 pr-6">
                      {s.title || 'Untitled'}
                    </span>
                  </div>
                  <div className={`flex items-center gap-2 mt-0.5 ${isActive || isFailed || isCrashed ? 'ml-3.5' : ''}`}>
                    {s.username && (
                      <span className={`text-xs font-medium truncate ${
                        s.username.startsWith('t-') ? 'text-orange-500' : 'text-blue-400'
                      }`}>
                        {s.username}
                      </span>
                    )}
                    {s.project_name && (
                      <span className="text-xs text-gray-400 truncate">
                        {s.project_name}
                      </span>
                    )}
                    <span className="text-xs text-gray-300 ml-auto">
                      {timeAgo(s.updated_at || s.created_at)}
                    </span>
                  </div>
                  <button
                    onClick={(e) => handleDelete(e, s)}
                    disabled={deletingId === s.id}
                    className="absolute top-2 right-2 p-1 text-gray-400 hover:text-red-600 hover:bg-red-50 rounded opacity-0 group-hover:opacity-100 transition-all focus:opacity-100 focus:outline-none"
                    aria-label={`Delete session ${s.title || 'Untitled'}`}
                  >
                    {deletingId === s.id ? (
                      <div className="w-3.5 h-3.5 border-2 border-red-600 border-t-transparent rounded-full animate-spin" />
                    ) : (
                      <Trash2 className="w-3.5 h-3.5" />
                    )}
                  </button>
                </div>
              )
            })}
          </div>
        ))}
        {isFetchingNextPage && (
          <div className="flex items-center justify-center py-3">
            <Loader2 className="w-4 h-4 text-gray-400 animate-spin" />
          </div>
        )}
        {!isLoading && !hasNextPage && sessions.length > 0 && total > PAGE_SIZE && (
          <p className="text-gray-300 text-xs text-center py-2">All sessions loaded</p>
        )}
      </div>
      {sessions.length > 0 && (
        <div className="px-3 py-2 border-t">
          <button
            onClick={handleDeleteAll}
            disabled={deleteAllMutation.isPending}
            className="w-full flex items-center justify-center gap-1.5 px-3 py-1.5 text-xs text-gray-400 hover:text-red-600 hover:bg-red-50 rounded-lg transition-colors disabled:opacity-50"
          >
            {deleteAllMutation.isPending ? (
              <div className="w-3.5 h-3.5 border-2 border-red-600 border-t-transparent rounded-full animate-spin" />
            ) : (
              <Trash2 className="w-3.5 h-3.5" />
            )}
            {deleteAllMutation.isPending ? 'Deleting…' : 'Delete all sessions'}
          </button>
        </div>
      )}
    </div>
  )
}

export default SessionSidebar