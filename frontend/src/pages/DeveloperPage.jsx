import { useState, useCallback, useRef, useEffect } from "react"
import { useQuery } from "@tanstack/react-query"
import {
  Loader2, Play, Terminal, AlertTriangle, Calendar, Clock, History,
  Info, Shield, Wrench, CheckCircle, XCircle, AlertCircle,
} from "lucide-react"
import { getAgents, getSessions, getProjects, executeAgentTest, getAgentTestRun } from "../services/api"
import PageHeader from "../components/shared/PageHeader"

const ROLE_BADGE = {
  primary: "bg-blue-100 text-blue-700",
  subagent: "bg-amber-100 text-amber-700",
  both: "bg-purple-100 text-purple-700",
}

const GIT_SCOPE_LABEL = {
  current_project: "Current Project",
  update_core: "Core Update",
  other_projects: "Other Projects",
}

const STATUS_BADGE = {
  completed: "bg-green-100 text-green-700",
  failed: "bg-red-100 text-red-700",
  running: "bg-blue-100 text-blue-700",
  pending: "bg-gray-100 text-gray-600",
  cancelled: "bg-gray-100 text-gray-500",
}

const STATUS_ICON = {
  completed: CheckCircle,
  failed: XCircle,
  running: Loader2,
  pending: Clock,
  cancelled: AlertCircle,
}

const truncatePrompt = (str, max = 60) =>
  str && str.length > max ? str.slice(0, max) + "..." : str

const fmtRelTime = (iso) => {
  if (!iso) return ""
  const d = new Date(iso)
  const diffMin = Math.floor((Date.now() - d.getTime()) / 60000)
  const diffHr = Math.floor(diffMin / 60)
  const diffDay = Math.floor(diffHr / 24)
  if (diffMin < 0) return "just now"
  if (diffMin < 60) return diffMin + "m ago"
  if (diffHr < 24) return diffHr + "h ago"
  if (diffDay < 7) return diffDay + "d ago"
  return d.toLocaleDateString()
}

export default function DeveloperPage() {
  const [selectedAgentId, setSelectedAgentId] = useState("")
  const [selectedProjectId, setSelectedProjectId] = useState("")
  const [taskPrompt, setTaskPrompt] = useState("")
  const [agentRunId, setAgentRunId] = useState(null)
  const [sessionId, setSessionId] = useState(null)
  const [executing, setExecuting] = useState(false)
  const [error, setError] = useState(null)
  const [runStatus, setRunStatus] = useState(null)
  const pollInterval = useRef(null)

  const agentsQuery = useQuery({
    queryKey: ["agents"],
    queryFn: getAgents,
  })

  const agentList = agentsQuery.data || []

  const projectsQuery = useQuery({
    queryKey: ["projects"],
    queryFn: getProjects,
  })

  const projectList = projectsQuery.data?.items || []

  const sessionsQuery = useQuery({
    queryKey: ["sessions"],
    queryFn: () => getSessions(1, 50),
  })

  const testSessions = (sessionsQuery.data?.items || []).filter(
    (s) => s.title && s.title.startsWith("Agent Test: ")
  )

  const selectedAgent = agentList.find((a) => a.id === selectedAgentId)
  const needsProject = selectedAgent?.git_scope === "current_project"
  const canExecute = taskPrompt.trim() && selectedAgentId && (!needsProject || selectedProjectId)

  useEffect(() => {
    return () => {
      if (pollInterval.current) clearInterval(pollInterval.current)
    }
  }, [])

  const startPolling = useCallback((runId) => {
    setRunStatus("pending")
    pollInterval.current = setInterval(async () => {
      try {
        const data = await getAgentTestRun(runId)
        setRunStatus(data.status)
        if (["completed", "failed", "cancelled"].includes(data.status)) {
          clearInterval(pollInterval.current)
          pollInterval.current = null
        }
      } catch {
        clearInterval(pollInterval.current)
        pollInterval.current = null
      }
    }, 1500)
  }, [])

  const startExecution = async () => {
    if (!canExecute) return
    setError(null)
    setExecuting(true)
    setAgentRunId(null)
    setSessionId(null)
    setRunStatus(null)
    try {
      const response = await executeAgentTest({
        agent_id: selectedAgentId,
        prompt: taskPrompt.trim(),
        project_id: needsProject ? selectedProjectId : undefined,
      })
      if (!response.success) throw new Error(response.message || "Execution failed")
      setAgentRunId(response.agent_run_id)
      setSessionId(response.session_id)
      if (response.agent_run_id) startPolling(response.agent_run_id)
    } catch (err) {
      setError(err.message)
    } finally {
      setExecuting(false)
    }
  }

  const resetRun = () => {
    if (pollInterval.current) {
      clearInterval(pollInterval.current)
      pollInterval.current = null
    }
    setAgentRunId(null)
    setSessionId(null)
    setRunStatus(null)
    setError(null)
  }

  if (agentsQuery.isLoading) {
    return (
      <div className="flex-1 flex flex-col min-h-0">
        <div className="flex items-center justify-center py-16">
          <div className="text-center">
            <Loader2 className="animate-spin w-8 h-8 text-gray-400 mx-auto mb-3" />
            Loading agents...
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <PageHeader title="Execute Agent" subtitle="Run any agent definition in an isolated session" />

      <div className="flex gap-4">
        <div className="w-96 shrink-0">
          <div className="border rounded-xl bg-white p-4 space-y-4 sticky top-4">
            <div className="flex items-center gap-2">
              <Terminal className="w-5 h-5 text-gray-700" />
              <span className="text-sm font-semibold text-gray-900">Task Configuration</span>
            </div>

            <div>
              <label className="block text-xs text-gray-500 mb-1">Agent</label>
              <select
                className="w-full px-3 py-2 border rounded text-sm"
                value={selectedAgentId}
                onChange={(e) => setSelectedAgentId(e.target.value)}
                disabled={agentsQuery.isLoading}
              >
                <option value="">Select an agent...</option>
                {agentList.map((a) => (
                  <option key={a.id} value={a.id}>{a.name}{a.description ? ` — ${a.description}` : ""}</option>
                ))}
              </select>
            </div>

            {selectedAgent && (
              <div className="space-y-2 p-3 bg-gray-50 rounded text-sm">
                <div className="flex items-center gap-2 flex-wrap">
                  <span
                    className={`text-xs font-medium px-2 py-0.5 rounded-full ${ROLE_BADGE[selectedAgent.role] || ROLE_BADGE.primary}`}
                  >
                    {selectedAgent.role || "primary"}
                  </span>
                  {selectedAgent.git_scope && (
                    <span className="text-xs bg-gray-200 text-gray-600 px-2 py-0.5 rounded">
                      {GIT_SCOPE_LABEL[selectedAgent.git_scope] || selectedAgent.git_scope}
                    </span>
                  )}
                  {selectedAgent.role === "subagent" && (
                    <span className="text-xs flex items-center gap-1 text-amber-700"><AlertTriangle size={12} /> Subagent</span>
                  )}
                </div>
                {selectedAgent.role === "subagent" && (
                  <div className="flex items-start gap-1.5 p-2 bg-amber-50 border border-amber-200 rounded text-xs text-amber-800">
                    <AlertTriangle size={14} className="shrink-0 mt-0.5" />
                    Warning: subagent agent — normally spawned by a parent agent. It will still work here.
                  </div>
                )}
                {selectedAgent.tools && selectedAgent.tools.length > 0 && (
                  <div>
                    <span className="text-xs text-gray-500 font-medium">Tools</span>: {selectedAgent.tools.length}
                  </div>
                )}
              </div>
            )}

            {needsProject && (
              <div>
                <label className="block text-xs text-gray-500 mb-1">Project</label>
                <select
                  className="w-full px-3 py-2 border rounded text-sm"
                  value={selectedProjectId}
                  onChange={(e) => setSelectedProjectId(e.target.value)}
                >
                  <option value="">Select a project...</option>
                  {projectList.map((p) => (
                    <option key={p.id} value={p.id}>{p.name || p.id}</option>
                  ))}
                </select>
              </div>
            )}
            {selectedAgent && selectedAgent.git_scope === "update_core" && (
              <div className="text-xs text-gray-500 bg-gray-50 px-3 py-2 rounded border">
                <Shield size={14} className="inline mr-1" />Core update — no project needed
              </div>
            )}
            {selectedAgent && !selectedAgent.git_scope && selectedAgent.has_sandbox === false && (
              <div className="text-xs text-gray-500 bg-gray-50 px-3 py-2 rounded border">
                <Wrench size={14} className="inline mr-1" />No sandbox — runs without a project
              </div>
            )}

            <div>
              <label className="block text-xs text-gray-500 mb-1">Prompt</label>
              <textarea
                className="w-full px-3 py-2 border rounded text-sm resize-none"
                placeholder="Describe the task to be completed..."
                rows={5}
                value={taskPrompt}
                onChange={(e) => setTaskPrompt(e.target.value)}
              />
            </div>

            <div className="flex gap-2">
              <button
                onClick={startExecution}
                disabled={!canExecute || executing}
                className="flex items-center gap-1.5 px-4 py-2 bg-blue-600 text-white rounded text-sm hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              >
                {executing ? <Loader2 className="animate-spin" size={14} /> : <Play size={14} />}
                {executing ? "Running..." : "Execute"}
              </button>
              {agentRunId && (
                <button onClick={resetRun} className="px-3 py-2 border border-gray-300 text-gray-600 rounded text-sm hover:bg-gray-50">
                  Reset
                </button>
              )}
            </div>
          </div>
        </div>

        <div className="flex-1 min-w-0 space-y-4">
          {error && (
            <div className="p-4 bg-rose-50 border border-rose-200 rounded-lg text-sm text-rose-800">
              <AlertTriangle className="inline w-4 h-4 mr-1" />
              {error}
            </div>
          )}
          {!agentRunId && !executing && !error && (
            <div className="p-12 text-center text-gray-400">
              <Terminal className="w-16 h-16 mx-auto mb-3 text-gray-300" />
              <span className="text-base">Configure a task and click Execute to start.</span>
            </div>
          )}
          {executing && !agentRunId && (
            <div className="p-8 text-center text-gray-500">
              <Loader2 className="animate-spin w-8 h-8 mx-auto mb-2" />
              <span className="text-sm">Starting agent...</span>
            </div>
          )}
          {agentRunId && (
            <div className="border rounded-xl bg-white p-4">
              <div className="flex items-center gap-2">
                {runStatus === "completed" && <CheckCircle className="w-5 h-5 text-green-500" />}
                {runStatus === "failed" && <XCircle className="w-5 h-5 text-red-500" />}
                {runStatus === "running" && <Loader2 className="w-5 h-5 text-blue-500 animate-spin" />}
                {runStatus === "pending" && <Clock className="w-5 h-5 text-gray-400" />}
                {runStatus === "cancelled" && <AlertCircle className="w-5 h-5 text-gray-400" />}
                {selectedAgent && <span className="text-sm font-medium">{selectedAgent.name || selectedAgent.id}</span>}
                {runStatus && <span className="text-xs px-2 py-0.5 rounded-full bg-gray-100 text-gray-600">{runStatus}</span>}
              </div>
              <div className="text-xs text-gray-400">
                {sessionId && <span>Session: {sessionId.slice(0, 8)}...</span>}
              </div>
            </div>
          )}

          <hr className="my-6 border-gray-200" />
          <div className="space-y-3">
            <div className="flex items-center gap-1.5 text-sm font-semibold text-gray-900">
              <History size={16} className="text-gray-400" />
              Run History
            </div>
            {sessionsQuery.isLoading && (
              <div className="flex items-center justify-center py-6 text-gray-400">
                <Loader2 className="animate-spin w-5 h-5 mr-2" />
                <span className="text-sm">Loading history...</span>
              </div>
            )}
            {!sessionsQuery.isLoading && testSessions.length === 0 && (
              <span className="text-sm text-gray-400 text-center block py-6">No previous agent test runs found.</span>
            )}
            {!sessionsQuery.isLoading && testSessions.slice(0, 10).map((s) => (
              <div
                className="group cursor-pointer rounded-lg border p-3 transition-colors hover:bg-gray-50"
                key={s.id}
                onClick={() => window.open(`/chat?session=${s.id}&mode=inspect`, '_blank')}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="text-sm font-medium truncate">{truncatePrompt(s.title)}</span>
                  <span className="text-xs px-2 py-0.5 rounded-full bg-gray-100 text-gray-600">{s.status}</span>
                </div>
                <div className="flex items-center gap-2 mt-1 text-xs text-gray-400">
                  <Calendar size={12} className="shrink-0" />
                  {fmtRelTime(s.created_at)}
                  <Clock size={12} className="shrink-0" />
                  Click to inspect
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
