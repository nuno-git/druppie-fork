/**
 * Chat Page - Two-panel polling-based session viewer
 *
 * Left sidebar: session list (polls every 5s)
 * Right panel: new session input or session detail (polls every 0.5s)
 * URL param ?session=<id> drives which session is shown
 */

import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { PanelLeftOpen } from 'lucide-react'
import SessionSidebar from '../components/chat/SessionSidebar'
import SessionDetail from '../components/chat/SessionDetail'
import NewSessionPanel from '../components/chat/NewSessionPanel'

const ChatPage = () => {
  const [searchParams, setSearchParams] = useSearchParams()
  const sessionId = searchParams.get('session')
  const initialMode = searchParams.get('mode')
  const [sidebarOpen, setSidebarOpen] = useState(() =>
    localStorage.getItem('druppie-chat-sidebar') !== 'false'
  )

  const toggleSidebar = () => {
    setSidebarOpen((prev) => {
      localStorage.setItem('druppie-chat-sidebar', String(!prev))
      return !prev
    })
  }

  const selectSession = (id) => {
    setSearchParams({ session: id })
  }

  const startNewChat = () => {
    setSearchParams({})
  }

  return (
    <div className="flex h-full flex-1 min-w-0">
      {/* Collapsible left sidebar */}
      <div
        className={`flex-shrink-0 bg-white border-r overflow-hidden transition-all duration-200 ${
          sidebarOpen ? 'w-72' : 'w-0'
        }`}
      >
        <div className="w-72 h-full">
          <SessionSidebar
            activeSessionId={sessionId}
            onSelectSession={selectSession}
            onNewChat={startNewChat}
            onCollapse={toggleSidebar}
          />
        </div>
      </div>

      {/* Right panel */}
      <div className="flex-1 min-w-0 bg-white overflow-hidden relative">
        {!sidebarOpen && (
          <button
            onClick={toggleSidebar}
            className="absolute top-3 left-3 z-10 p-1.5 rounded-lg text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition-colors"
            title="Expand sidebar"
            aria-label="Expand sidebar"
          >
            <PanelLeftOpen className="w-4 h-4" />
          </button>
        )}
        {sessionId ? (
          <SessionDetail key={sessionId} sessionId={sessionId} initialViewMode={initialMode} />
        ) : (
          <NewSessionPanel onSessionCreated={selectSession} />
        )}
      </div>
    </div>
  )
}

export default ChatPage
