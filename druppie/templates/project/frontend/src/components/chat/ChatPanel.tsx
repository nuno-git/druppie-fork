/**
 * ChatPanel — Full chat UI with sidebar session list and message area.
 *
 * Drop this into any page to add a conversational AI assistant.
 * Customize the agent backend in app/agent.py.
 */

import { useState, useEffect, useRef, useCallback } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { MessageSquarePlus, Trash2, ChevronDown, ChevronRight, Send, Loader2, PanelLeftClose, PanelLeft } from "lucide-react"
import type { ChatSession, ChatMessage, AgentStep } from "./types"
import * as api from "./api"

// ---------------------------------------------------------------------------
// Agent step rendering (transparency)
// ---------------------------------------------------------------------------

function StepBadge({ step }: { step: AgentStep }) {
  const [open, setOpen] = useState(false)
  const colors: Record<string, string> = {
    search: "bg-blue-50 text-blue-700 border-blue-200",
    query: "bg-amber-50 text-amber-700 border-amber-200",
    tool: "bg-purple-50 text-purple-700 border-purple-200",
    reasoning: "bg-gray-50 text-gray-600 border-gray-200",
  }
  const cls = colors[step.type] || colors.reasoning

  return (
    <div className="text-xs">
      <button
        onClick={() => step.detail && setOpen(!open)}
        className={`inline-flex items-center gap-1 px-2 py-0.5 rounded border ${cls} ${step.detail ? "cursor-pointer hover:opacity-80" : ""}`}
      >
        {step.detail ? (open ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />) : null}
        <span>{step.label}</span>
      </button>
      {open && step.detail && (
        <pre className="mt-1 p-2 bg-muted rounded text-[11px] whitespace-pre-wrap max-h-40 overflow-y-auto">
          {typeof step.detail === "string"
            ? step.detail
            : Array.isArray(step.detail)
              ? step.detail.join("\n")
              : JSON.stringify(step.detail, null, 2)}
        </pre>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Sidebar
// ---------------------------------------------------------------------------

function Sidebar({
  sessions, activeId, onSelect, onNew, onDelete, collapsed, onToggle,
}: {
  sessions: ChatSession[]
  activeId: number | null
  onSelect: (id: number) => void
  onNew: () => void
  onDelete: (id: number) => void
  collapsed: boolean
  onToggle: () => void
}) {
  if (collapsed) {
    return (
      <div className="w-12 border-r bg-card flex flex-col items-center py-3 gap-2 shrink-0">
        <button onClick={onToggle} className="p-2 rounded hover:bg-muted" title="Open sidebar">
          <PanelLeft className="w-4 h-4" />
        </button>
        <button onClick={onNew} className="p-2 rounded hover:bg-muted" title="Nieuw gesprek">
          <MessageSquarePlus className="w-4 h-4" />
        </button>
      </div>
    )
  }

  return (
    <div className="w-64 border-r bg-card flex flex-col shrink-0">
      <div className="p-3 border-b flex items-center justify-between">
        <Button variant="outline" size="sm" className="flex-1 mr-2" onClick={onNew}>
          <MessageSquarePlus className="w-4 h-4 mr-1" /> Nieuw gesprek
        </Button>
        <button onClick={onToggle} className="p-1.5 rounded hover:bg-muted" title="Sluit sidebar">
          <PanelLeftClose className="w-4 h-4" />
        </button>
      </div>
      <div className="flex-1 overflow-y-auto">
        {sessions.length === 0 && (
          <p className="text-xs text-muted-foreground text-center py-6">Geen gesprekken</p>
        )}
        {sessions.map(s => (
          <div
            key={s.id}
            className={`group flex items-center px-3 py-2 cursor-pointer text-sm transition-colors ${
              s.id === activeId ? "bg-muted font-medium" : "hover:bg-muted/50"
            }`}
            onClick={() => onSelect(s.id)}
          >
            <span className="flex-1 truncate">{s.title}</span>
            <button
              onClick={e => { e.stopPropagation(); onDelete(s.id) }}
              className="opacity-0 group-hover:opacity-100 p-1 rounded hover:bg-destructive/10 hover:text-destructive transition-opacity"
              title="Verwijderen"
            >
              <Trash2 className="w-3 h-3" />
            </button>
          </div>
        ))}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main ChatPanel
// ---------------------------------------------------------------------------

export default function ChatPanel() {
  const [sessions, setSessions] = useState<ChatSession[]>([])
  const [activeId, setActiveId] = useState<number | null>(null)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState("")
  const [sending, setSending] = useState(false)
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
  const endRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  // Load sessions on mount
  const loadSessions = useCallback(async () => {
    const list = await api.listSessions()
    setSessions(list)
  }, [])

  useEffect(() => { loadSessions() }, [loadSessions])
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth" }) }, [messages])

  // Load messages when active session changes
  const loadMessages = useCallback(async (sid: number) => {
    const data = await api.getSession(sid)
    setMessages(data.messages || [])
    return data.messages || []
  }, [])

  useEffect(() => {
    if (!activeId) { setMessages([]); return }
    loadMessages(activeId)
  }, [activeId, loadMessages])

  // Poll for "thinking" messages — agent processes in background
  useEffect(() => {
    const hasThinking = messages.some(m => m.status === "thinking")
    if (!hasThinking || !activeId) return

    const interval = setInterval(async () => {
      const msgs = await loadMessages(activeId)
      const stillThinking = msgs.some((m: ChatMessage) => m.status === "thinking")
      if (!stillThinking) {
        setSending(false)
        loadSessions() // title may have updated
      }
    }, 2000)

    return () => clearInterval(interval)
  }, [messages, activeId, loadMessages, loadSessions])

  const handleNew = async () => {
    const session = await api.createSession()
    setSessions(prev => [session, ...prev])
    setActiveId(session.id)
    setMessages([])
    inputRef.current?.focus()
  }

  const handleDelete = async (id: number) => {
    await api.deleteSession(id)
    setSessions(prev => prev.filter(s => s.id !== id))
    if (activeId === id) {
      setActiveId(null)
      setMessages([])
    }
  }

  const handleSend = async () => {
    if (!input.trim() || sending) return
    let sid = activeId
    if (!sid) {
      const session = await api.createSession()
      setSessions(prev => [session, ...prev])
      setActiveId(session.id)
      sid = session.id
    }
    setInput("")
    setSending(true)
    try {
      // Server returns immediately with a "thinking" message
      await api.sendMessage(sid, input.trim())
      // Reload to show user msg + thinking placeholder
      await loadMessages(sid)
      loadSessions()
      // Polling effect above will handle the rest
    } catch {
      setSending(false)
      setMessages(prev => [
        ...prev,
        { id: Date.now(), role: "assistant", content: "Verbindingsfout — probeer opnieuw.",
          status: "error", steps: null, created_at: new Date().toISOString() },
      ])
    }
  }

  return (
    <div className="flex h-full">
      <Sidebar
        sessions={sessions}
        activeId={activeId}
        onSelect={setActiveId}
        onNew={handleNew}
        onDelete={handleDelete}
        collapsed={sidebarCollapsed}
        onToggle={() => setSidebarCollapsed(!sidebarCollapsed)}
      />

      {/* Chat area */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Messages */}
        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          {!activeId && messages.length === 0 && (
            <div className="flex items-center justify-center h-full">
              <div className="text-center space-y-3">
                <MessageSquarePlus className="w-12 h-12 mx-auto text-muted-foreground/30" />
                <p className="text-muted-foreground">Start een nieuw gesprek of selecteer een bestaand gesprek.</p>
                <Button onClick={handleNew}>Nieuw gesprek</Button>
              </div>
            </div>
          )}

          {messages.map(m => (
            <div key={m.id} className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}>
              <div className={`max-w-[85%] space-y-2 ${
                m.role === "user"
                  ? "bg-primary text-primary-foreground rounded-2xl rounded-tr-sm px-4 py-2.5"
                  : "space-y-2"
              }`}>
                {/* Agent steps (transparency) */}
                {m.role === "assistant" && m.steps && m.steps.length > 0 && (
                  <div className="flex flex-wrap gap-1.5">
                    {m.steps.map((step, i) => <StepBadge key={i} step={step} />)}
                  </div>
                )}
                <div className={`text-sm whitespace-pre-wrap ${m.role === "assistant" ? "bg-muted rounded-2xl rounded-tl-sm px-4 py-2.5" : ""}`}>
                  {m.role === "assistant" && m.status === "thinking" ? (
                    <span className="flex items-center gap-2 text-muted-foreground">
                      <Loader2 className="w-4 h-4 animate-spin" /> Denken...
                    </span>
                  ) : m.content}
                </div>
              </div>
            </div>
          ))}

          {/* No separate "thinking" bubble needed — the message itself shows status */}
          <div ref={endRef} />
        </div>

        {/* Input */}
        <div className="border-t p-3">
          <div className="flex gap-2 max-w-3xl mx-auto">
            <Input
              ref={inputRef}
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={e => e.key === "Enter" && !e.shiftKey && handleSend()}
              placeholder={activeId ? "Typ een bericht..." : "Start een nieuw gesprek..."}
              disabled={sending}
              className="flex-1"
            />
            <Button onClick={handleSend} disabled={sending || !input.trim()} size="icon">
              <Send className="w-4 h-4" />
            </Button>
          </div>
        </div>
      </div>
    </div>
  )
}
