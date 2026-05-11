/**
 * Platform dashboard — admin view over druppie-managed Docker containers and volumes.
 *
 * Polls /api/deployments and /api/deployments/volumes/list every 5s.
 * Lets admins restart, stop, start, view logs, and wipe whole projects.
 */

import React, { useState, useMemo } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Boxes,
  RefreshCw,
  Play,
  Square,
  RotateCw,
  FileText,
  Trash2,
  Search,
  AlertCircle,
  CheckCircle2,
  Circle,
  HardDrive,
  X,
  ExternalLink,
} from 'lucide-react'

import {
  getDeployments,
  startDeployment,
  stopDeployment,
  restartDeployment,
  getDeploymentLogs,
  getDeploymentVolumes,
  wipeProject,
} from '../services/api'
import { useToast } from '../components/Toast'

const POLL_MS = 5000

const HEALTH_STYLES = {
  healthy: 'bg-green-100 text-green-700',
  unhealthy: 'bg-red-100 text-red-700',
  starting: 'bg-amber-100 text-amber-700',
  none: 'bg-gray-100 text-gray-600',
}

const STATE_STYLES = {
  running: 'bg-green-100 text-green-700',
  restarting: 'bg-amber-100 text-amber-700',
  paused: 'bg-blue-100 text-blue-700',
  created: 'bg-gray-100 text-gray-700',
  exited: 'bg-gray-200 text-gray-700',
  unknown: 'bg-gray-100 text-gray-500',
}

const Chip = ({ tone = 'gray', children, icon: Icon }) => {
  const map = {
    ...HEALTH_STYLES,
    ...STATE_STYLES,
    gray: 'bg-gray-100 text-gray-700',
  }
  const cls = map[tone] || map.gray
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium ${cls}`}>
      {Icon && <Icon className="w-3 h-3" />}
      {children}
    </span>
  )
}

// Group containers by project_id (null project = "Unassigned")
const groupByProject = (items) => {
  const groups = new Map()
  for (const c of items) {
    const key = c.project_id || '__unassigned__'
    if (!groups.has(key)) groups.set(key, [])
    groups.get(key).push(c)
  }
  return groups
}

const LogsDrawer = ({ containerName, onClose }) => {
  const { data, isLoading, refetch, isFetching } = useQuery({
    queryKey: ['deployment-logs', containerName],
    queryFn: () => getDeploymentLogs(containerName, 300),
    enabled: !!containerName,
  })

  if (!containerName) return null

  return (
    <div className="fixed inset-0 z-40 flex">
      <div className="flex-1 bg-black/30" onClick={onClose} />
      <div className="w-[720px] max-w-[90vw] bg-white h-full flex flex-col border-l border-gray-200 shadow-xl">
        <div className="flex items-center justify-between px-4 py-3 border-b border-gray-200">
          <div className="flex items-center gap-2">
            <FileText className="w-4 h-4 text-gray-600" />
            <span className="font-medium text-sm">{containerName}</span>
            <span className="text-xs text-gray-500">last 300 lines</span>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => refetch()}
              className="p-1.5 text-gray-500 hover:text-gray-700 hover:bg-gray-100 rounded"
              title="Refresh"
            >
              <RefreshCw className={`w-4 h-4 ${isFetching ? 'animate-spin' : ''}`} />
            </button>
            <button
              onClick={onClose}
              className="p-1.5 text-gray-500 hover:text-gray-700 hover:bg-gray-100 rounded"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>
        <pre className="flex-1 overflow-auto p-4 text-xs font-mono bg-gray-900 text-gray-100 whitespace-pre-wrap">
{isLoading ? 'Loading…' : (data?.logs || '(no logs)')}
        </pre>
      </div>
    </div>
  )
}

const Platform = () => {
  const [search, setSearch] = useState('')
  const [logsFor, setLogsFor] = useState(null)
  const [confirmWipe, setConfirmWipe] = useState(null)
  const toast = useToast()
  const qc = useQueryClient()

  const { data: deployData, isLoading: loadingDeploy, refetch: refetchDeploy } = useQuery({
    queryKey: ['platform-deployments'],
    queryFn: () => getDeployments(null, true),
    refetchInterval: POLL_MS,
  })

  const { data: volData, isLoading: loadingVol } = useQuery({
    queryKey: ['platform-volumes'],
    queryFn: () => getDeploymentVolumes(),
    refetchInterval: POLL_MS,
  })

  const items = deployData?.items || []
  const volumes = volData?.items || []

  const filtered = useMemo(() => {
    if (!search.trim()) return items
    const q = search.toLowerCase()
    return items.filter((c) =>
      [c.container_name, c.image, c.project_id, c.user_id, c.session_id]
        .filter(Boolean)
        .some((v) => String(v).toLowerCase().includes(q))
    )
  }, [items, search])

  const groups = useMemo(() => groupByProject(filtered), [filtered])

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['platform-deployments'] })
    qc.invalidateQueries({ queryKey: ['platform-volumes'] })
  }

  const startMut = useMutation({
    mutationFn: (name) => startDeployment(name),
    onSuccess: (r, name) => {
      r?.success ? toast.success(`Started ${name}`) : toast.error(r?.error || `Failed to start ${name}`)
      invalidate()
    },
    onError: (e) => toast.error(e.message),
  })
  const stopMut = useMutation({
    mutationFn: (name) => stopDeployment(name, false),
    onSuccess: (r, name) => {
      r?.success ? toast.success(`Stopped ${name}`) : toast.error(`Failed to stop ${name}`)
      invalidate()
    },
    onError: (e) => toast.error(e.message),
  })
  const restartMut = useMutation({
    mutationFn: (name) => restartDeployment(name),
    onSuccess: (r, name) => {
      r?.success ? toast.success(`Restarted ${name}`) : toast.error(r?.error || `Failed to restart ${name}`)
      invalidate()
    },
    onError: (e) => toast.error(e.message),
  })
  const wipeMut = useMutation({
    mutationFn: (projectId) => wipeProject(projectId),
    onSuccess: (r, pid) => {
      if (r?.success) {
        toast.success(
          `Wiped ${pid}: ${r.containers_removed.length} containers, ${r.volumes_removed.length} volumes`
        )
      } else {
        toast.error(`Wipe had errors: ${(r?.errors || []).join('; ')}`)
      }
      invalidate()
    },
    onError: (e) => toast.error(e.message),
  })

  const stats = useMemo(() => {
    const running = items.filter((c) => c.state === 'running').length
    const unhealthy = items.filter((c) => c.health === 'unhealthy').length
    const stopped = items.filter((c) => c.state !== 'running').length
    return { total: items.length, running, unhealthy, stopped }
  }, [items])

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Boxes className="w-6 h-6 text-purple-600" />
          <h1 className="text-2xl font-semibold">Platform</h1>
        </div>
        <button
          onClick={() => refetchDeploy()}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm bg-white border border-gray-200 rounded hover:bg-gray-50"
        >
          <RefreshCw className="w-4 h-4" />
          Refresh
        </button>
      </div>

      {/* Stats row */}
      <div className="grid grid-cols-4 gap-3">
        <StatCard label="Containers" value={stats.total} />
        <StatCard label="Running" value={stats.running} tone="green" />
        <StatCard label="Stopped" value={stats.stopped} tone="gray" />
        <StatCard label="Unhealthy" value={stats.unhealthy} tone={stats.unhealthy ? 'red' : 'gray'} />
      </div>

      {/* Search */}
      <div className="relative">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search by container, image, project, user…"
          className="w-full pl-9 pr-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-purple-500/30"
        />
      </div>

      {/* Grouped containers */}
      <div className="space-y-4">
        {loadingDeploy && <div className="text-sm text-gray-500">Loading deployments…</div>}
        {!loadingDeploy && groups.size === 0 && (
          <div className="text-sm text-gray-500 border border-dashed border-gray-200 rounded-lg p-6 text-center">
            No deployments match.
          </div>
        )}
        {[...groups.entries()].map(([projectId, cs]) => (
          <ProjectGroup
            key={projectId}
            projectId={projectId}
            containers={cs}
            onStart={(n) => startMut.mutate(n)}
            onStop={(n) => stopMut.mutate(n)}
            onRestart={(n) => restartMut.mutate(n)}
            onLogs={(n) => setLogsFor(n)}
            onWipe={(pid) => setConfirmWipe(pid)}
          />
        ))}
      </div>

      {/* Volumes */}
      <div className="mt-6">
        <div className="flex items-center gap-2 mb-2">
          <HardDrive className="w-5 h-5 text-gray-600" />
          <h2 className="text-lg font-semibold">Volumes</h2>
          <span className="text-xs text-gray-500">({volumes.length})</span>
        </div>
        {loadingVol && <div className="text-sm text-gray-500">Loading volumes…</div>}
        {!loadingVol && volumes.length === 0 && (
          <div className="text-sm text-gray-500 border border-dashed border-gray-200 rounded-lg p-4 text-center">
            No druppie-labeled volumes.
          </div>
        )}
        {volumes.length > 0 && (
          <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 text-gray-600 text-xs uppercase">
                <tr>
                  <th className="text-left px-3 py-2">Name</th>
                  <th className="text-left px-3 py-2">Driver</th>
                  <th className="text-left px-3 py-2">Project</th>
                  <th className="text-left px-3 py-2">Compose</th>
                </tr>
              </thead>
              <tbody>
                {volumes.map((v) => (
                  <tr key={v.name} className="border-t border-gray-100">
                    <td className="px-3 py-2 font-mono text-xs">{v.name}</td>
                    <td className="px-3 py-2">{v.driver}</td>
                    <td className="px-3 py-2 font-mono text-xs">{v.project_id || '-'}</td>
                    <td className="px-3 py-2 font-mono text-xs">{v.compose_project || '-'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <LogsDrawer containerName={logsFor} onClose={() => setLogsFor(null)} />

      {confirmWipe && (
        <ConfirmWipe
          projectId={confirmWipe}
          pending={wipeMut.isPending}
          onConfirm={() => {
            wipeMut.mutate(confirmWipe)
            setConfirmWipe(null)
          }}
          onCancel={() => setConfirmWipe(null)}
        />
      )}
    </div>
  )
}

const StatCard = ({ label, value, tone = 'blue' }) => {
  const tones = {
    blue: 'text-blue-700',
    green: 'text-green-700',
    red: 'text-red-700',
    gray: 'text-gray-700',
  }
  return (
    <div className="bg-white border border-gray-200 rounded-lg px-4 py-3">
      <div className="text-xs uppercase text-gray-500">{label}</div>
      <div className={`text-2xl font-semibold ${tones[tone]}`}>{value}</div>
    </div>
  )
}

const ProjectGroup = ({ projectId, containers, onStart, onStop, onRestart, onLogs, onWipe }) => {
  const isUnassigned = projectId === '__unassigned__'
  return (
    <div className="bg-white border border-gray-200 rounded-lg overflow-hidden">
      <div className="px-3 py-2 bg-gray-50 border-b border-gray-200 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-xs uppercase text-gray-500">Project</span>
          <span className="font-mono text-sm">
            {isUnassigned ? '(unassigned)' : projectId}
          </span>
          <span className="text-xs text-gray-500">{containers.length} containers</span>
        </div>
        {!isUnassigned && (
          <button
            onClick={() => onWipe(projectId)}
            className="inline-flex items-center gap-1 px-2 py-1 text-xs text-red-600 hover:bg-red-50 rounded"
            title="Stop + remove all containers and labeled volumes"
          >
            <Trash2 className="w-3.5 h-3.5" />
            Wipe
          </button>
        )}
      </div>
      <table className="w-full text-sm">
        <thead className="text-xs uppercase text-gray-500">
          <tr>
            <th className="text-left px-3 py-2">Container</th>
            <th className="text-left px-3 py-2">Image</th>
            <th className="text-left px-3 py-2">State</th>
            <th className="text-left px-3 py-2">Health</th>
            <th className="text-left px-3 py-2">Ports</th>
            <th className="text-right px-3 py-2">Actions</th>
          </tr>
        </thead>
        <tbody>
          {containers.map((c) => (
            <ContainerRow
              key={c.container_id || c.container_name}
              c={c}
              onStart={onStart}
              onStop={onStop}
              onRestart={onRestart}
              onLogs={onLogs}
            />
          ))}
        </tbody>
      </table>
    </div>
  )
}

const ContainerRow = ({ c, onStart, onStop, onRestart, onLogs }) => {
  const running = c.state === 'running'
  return (
    <tr className="border-t border-gray-100 hover:bg-gray-50">
      <td className="px-3 py-2">
        <div className="font-mono text-xs">{c.container_name}</div>
        {c.app_url && running && (
          <a
            href={c.app_url}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 text-xs text-blue-600 hover:underline"
          >
            {c.app_url}
            <ExternalLink className="w-3 h-3" />
          </a>
        )}
      </td>
      <td className="px-3 py-2 font-mono text-xs truncate max-w-[220px]">{c.image}</td>
      <td className="px-3 py-2">
        <Chip tone={c.state}>{c.state}</Chip>
      </td>
      <td className="px-3 py-2">
        <Chip
          tone={c.health}
          icon={
            c.health === 'healthy'
              ? CheckCircle2
              : c.health === 'unhealthy'
                ? AlertCircle
                : Circle
          }
        >
          {c.health}
        </Chip>
      </td>
      <td className="px-3 py-2 font-mono text-xs">{c.ports || '-'}</td>
      <td className="px-3 py-2">
        <div className="flex justify-end gap-1">
          {running ? (
            <>
              <IconBtn title="Restart" onClick={() => onRestart(c.container_name)} icon={RotateCw} />
              <IconBtn title="Stop" onClick={() => onStop(c.container_name)} icon={Square} tone="red" />
            </>
          ) : (
            <IconBtn title="Start" onClick={() => onStart(c.container_name)} icon={Play} tone="green" />
          )}
          <IconBtn title="Logs" onClick={() => onLogs(c.container_name)} icon={FileText} />
        </div>
      </td>
    </tr>
  )
}

const IconBtn = ({ icon: Icon, onClick, title, tone = 'gray' }) => {
  const tones = {
    gray: 'text-gray-600 hover:bg-gray-100',
    red: 'text-red-600 hover:bg-red-50',
    green: 'text-green-600 hover:bg-green-50',
  }
  return (
    <button
      onClick={onClick}
      title={title}
      className={`p-1.5 rounded ${tones[tone]}`}
    >
      <Icon className="w-4 h-4" />
    </button>
  )
}

const ConfirmWipe = ({ projectId, onConfirm, onCancel, pending }) => (
  <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/40">
    <div className="bg-white rounded-lg shadow-xl max-w-md w-full p-5">
      <div className="flex items-center gap-2 mb-2">
        <Trash2 className="w-5 h-5 text-red-600" />
        <h3 className="text-lg font-semibold">Wipe project {projectId}?</h3>
      </div>
      <p className="text-sm text-gray-600 mb-4">
        Stops and removes <b>all containers</b> for this project, plus any Docker volumes
        labeled <code className="font-mono">druppie.project_id={projectId}</code>. This
        cannot be undone.
      </p>
      <div className="flex justify-end gap-2">
        <button
          onClick={onCancel}
          className="px-3 py-1.5 text-sm rounded border border-gray-200 hover:bg-gray-50"
          disabled={pending}
        >
          Cancel
        </button>
        <button
          onClick={onConfirm}
          className="px-3 py-1.5 text-sm rounded bg-red-600 text-white hover:bg-red-700 disabled:opacity-50"
          disabled={pending}
        >
          {pending ? 'Wiping…' : 'Wipe'}
        </button>
      </div>
    </div>
  </div>
)

export default Platform
