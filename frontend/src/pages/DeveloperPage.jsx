import { useState, useCallback } from "react"
import { useQuery } from "@tanstack/react-query"
import { Loader2, Play, Terminal, AlertTriangle, Calendar, Clock, History } from "lucide-react"
import { getSessions, getProjects, executeDeveloperTask, getPiCodingRunBySession } from "../services/api"
import PageHeader from "../components/shared/PageHeader"
import PiCodingRunLiveCard from "../components/chat/PiCodingRunLiveCard"

const FLOWS = [
  { id: "planner", label: "TDD (Test-Driven Development)", description: "Plan, build, verify, and push code changes via the planner agent." },
  { id: "router", label: "Explore", description: "Explore a codebase via the router agent - read-only investigation with parallel explorer subagents." },
]

const REPO_TARGETS = [
  { id: "druppie_core", label: "Core Update", description: "Modify the Druppie platform itself via GitHub App (no project needed)." },
  { id: "project", label: "Project", description: "Work on a user project via Gitea (select project below)." },
]

const truncatePrompt = (str, max = 60) =>
  str && str.length > max ? str.slice(0, max) + "..." : str

const fmtRelTime = (iso) => {
  if (!iso) return ""
  const d = new Date(iso)
  const diffMin = Math.floor((Date.now() - d.getTime()) / 60000)
  const diffHr = Math.floor(diffMin / 60)
  const diffDay = Math.floor(diffHr / 24)
  if (diffMin < 0) {
    return "just now"
  }
  if (diffMin < 60) {
    return diffMin + "m ago"
  }
  if (diffHr < 24) {
    return diffHr + "h ago"
  }
  if (diffDay < 7) {
    return diffDay + "d ago"
  }
  return d.toLocaleDateString()
}

export default function DeveloperPage() {
  const [repoTarget, setRepoTarget] = useState("project")
  const [selectedProjectId, setSelectedProjectId] = useState("")
  const [selectedFlow, setSelectedFlow] = useState("planner")
  const [taskPrompt, setTaskPrompt] = useState("")
  const [toolCallId, setToolCallId] = useState(null)
  const [executing, setExecuting] = useState(false)
  const [error, setError] = useState(null)

  const projectsQuery = useQuery({
    queryKey: ["projects"],
    queryFn: getProjects,
  })

  const projectList = projectsQuery.data?.items || projectsQuery.data || []

  const sessionsQuery = useQuery({
    queryKey: ["sessions"],
    queryFn: () => getSessions(1, 50),
  })

  const devSessions = (sessionsQuery.data?.items || []).filter(
    (s) => s.title && s.title.startsWith("Dev: ")
  )

  const [loadingHistoryRun, setLoadingHistoryRun] = useState(null)

  const viewHistoryRun = useCallback(async (sessionId) => {
    setLoadingHistoryRun(sessionId)
    setError(null)
    try {
      const run = await getPiCodingRunBySession(sessionId)
      const toolCallId = run?.tool_call_id
      if (toolCallId) {
        setToolCallId(toolCallId)
      } else {
        setError("No pi_agent run found for this session.")
      }
    } catch (err) {
      if (err?.status === 404) {
        setError("No pi_agent run found for this session.")
      } else {
        setError(err.message || "Failed to load session details.")
      }
    } finally {
      setLoadingHistoryRun(null)
    }
  }, [])

  const canExecute = taskPrompt.trim() && (repoTarget === "druppie_core" || selectedProjectId)

  const startExecution = async () => {
    if (!canExecute) return
    setError(null)
    setExecuting(true)
    setToolCallId(null)
    try {
      const response = await executeDeveloperTask({
        task: taskPrompt.trim(),
        flow: selectedFlow,
        repo_target: repoTarget,
        project_id: repoTarget === "project" ? selectedProjectId : undefined,
      })
      if (!response.success) {
        throw new Error(response.message || "Execution failed")
      }
      setToolCallId(response.tool_call_id)
    } catch (err) {
      setError(err.message)
    } finally {
      setExecuting(false)
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader title="Developer Tool" subtitle="Manually execute pi_agent coding tasks." />

      <div className="flex gap-6">
        <div className="w-96 shrink-0 sticky top-4">
          <div className="border rounded-xl bg-white p-4 space-y-4">
            <h3 className="text-sm font-semibold text-gray-900">Task Configuration</h3>

            <div>
              <label className="block text-xs text-gray-500 mb-1">Target</label>
              <div className="space-y-1">
                {REPO_TARGETS.map((rt) => (
                  <label
                    key={rt.id}
                    className={"flex items-start gap-2 p-2 rounded cursor-pointer transition-colors " +
                      (repoTarget === rt.id ? "bg-blue-50 border border-blue-200" : "border border-gray-100 hover:bg-gray-50")
                    }
                    onClick={() => setRepoTarget(rt.id)}
                  >
                    <input
                      type="radio"
                      name="repoTarget"
                      checked={repoTarget === rt.id}
                      onChange={() => setRepoTarget(rt.id)}
                      className="mt-0.5 shrink-0"
                    />
                    <div>
                      <div className="text-sm font-medium">{rt.label}</div>
                      <div className="text-xs text-gray-500">{rt.description}</div>
                    </div>
                  </label>
                ))}
              </div>
            </div>

            {repoTarget === "project" && (
              <div>
                <label className="block text-xs text-gray-500 mb-1">Project</label>
                <select
                  value={selectedProjectId}
                  onChange={(e) => setSelectedProjectId(e.target.value)}
                  className="w-full px-3 py-2 border rounded text-sm"
                  disabled={projectsQuery.isLoading}
                >
                  {projectsQuery.isLoading ? (
                    <option>Loading...</option>
                  ) : projectList.length === 0 ? (
                    <option value="">No projects available</option>
                  ) : (
                    projectList.map((p) => (
                      <option key={p.id} value={p.id}>{p.name || p.id}</option>
                    ))
                  )}
                </select>
              </div>
            )}

            <div>
              <label className="block text-xs text-gray-500 mb-1">Flow</label>
              <div className="space-y-1">
                {FLOWS.map((flow) => (
                  <label
                    key={flow.id}
                    className={"flex items-start gap-2 p-2 rounded cursor-pointer transition-colors " +
                      (selectedFlow === flow.id ? "bg-blue-50 border border-blue-200" : "border border-gray-100 hover:bg-gray-50")
                    }
                    onClick={() => setSelectedFlow(flow.id)}
                  >
                    <input
                      type="radio"
                      name="flow"
                      checked={selectedFlow === flow.id}
                      onChange={() => setSelectedFlow(flow.id)}
                      className="mt-0.5 shrink-0"
                    />
                    <div>
                      <div className="text-sm font-medium">{flow.label}</div>
                      <div className="text-xs text-gray-500">{flow.description}</div>
                    </div>
                  </label>
                ))}
              </div>
            </div>

            <div>
              <label className="block text-xs text-gray-500 mb-1">Task</label>
              <textarea
                value={taskPrompt}
                onChange={(e) => setTaskPrompt(e.target.value)}
                placeholder="Describe the task to be completed..."
                rows={5}
                className="w-full px-3 py-2 border rounded text-sm resize-none"
                disabled={executing}
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

              {toolCallId && (
                <button
                  onClick={() => {
                    setToolCallId(null)
                    setError(null)
                  }}
                  className="px-3 py-2 border border-gray-300 text-gray-600 rounded text-sm hover:bg-gray-50"
                >
                  Reset
                </button>
              )}
            </div>
          </div>
        </div>

        <div className="flex-1 min-w-0">
          {error && (
            <div className="p-4 bg-rose-50 border border-rose-200 rounded-lg text-sm text-rose-800">
              <AlertTriangle className="inline w-4 h-4 mr-1" />
              {error}
            </div>
          )}

          {!toolCallId && !error && !executing && (
            <div className="p-12 text-center text-gray-400">
              <Terminal className="w-16 h-16 mx-auto mb-3 text-gray-300" />
              <p className="text-base">Configure a task and click Execute to start.</p>
            </div>
          )}

          {executing && !toolCallId && (
            <div className="p-8 text-center text-gray-500">
              <Loader2 className="animate-spin w-8 h-8 mx-auto mb-2" />
              <p className="text-sm">Executing developer task...</p>
            </div>
          )}

          {toolCallId && (
            <div>
              <PiCodingRunLiveCard toolCallId={toolCallId} />
            </div>
          )}

          <hr className="my-6 border-gray-200" />
          <div className="space-y-3">
            <h3 className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
              <History size={16} className="text-gray-400" />
              Run History
            </h3>

            {sessionsQuery.isLoading && (
              <div className="flex items-center justify-center py-6 text-gray-400">
                <Loader2 className="animate-spin w-5 h-5 mr-2" />
                <span className="text-sm">Loading history...</span>
              </div>
            )}

            {!sessionsQuery.isLoading && devSessions.length === 0 && (
              <p className="text-sm text-gray-400 text-center py-6">No previous developer runs found.</p>
            )}

            {!sessionsQuery.isLoading && devSessions.length > 0 && devSessions.slice(0, 10).map((s) => (
              <div
                key={s.id}
                className={"group cursor-pointer rounded-lg border p-3 transition-colors hover:bg-gray-50 " + (loadingHistoryRun === s.id ? "opacity-60 pointer-events-none" : "")}
                onClick={() => viewHistoryRun(s.id)}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="text-sm font-medium truncate flex-1">{truncatePrompt(s.title)}</span>
                  <span className={
                    "text-xs px-2 py-0.5 rounded-full shrink-0 " +
                    (s.status === "completed" ? "bg-green-100 text-green-700" : s.status === "failed" ? "bg-red-100 text-red-700" : "bg-gray-100 text-gray-600")
                  }>
                    {s.status}
                  </span>
                </div>
                <div className="flex items-center gap-2 mt-1 text-xs text-gray-400">
                  <Calendar size={12} className="shrink-0" />
                  {fmtRelTime(s.created_at)}
                  <Clock size={12} className="shrink-0" />
                  {loadingHistoryRun === s.id ? "Loading..." : "Click to view"}
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
