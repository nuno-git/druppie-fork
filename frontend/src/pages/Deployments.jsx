/**
 * Deployments — user-facing dashboard for managing deployed applications.
 *
 * Shows the current user's deployments (admins see all).
 * Polls /api/deployments every 5s. Supports start/stop/restart/logs.
 */

import React, { useState, useMemo } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Rocket,
  RefreshCw,
  Play,
  Square,
  RotateCw,
  FileText,
  Search,
  AlertCircle,
  CheckCircle2,
  Circle,
  ExternalLink,
  X,
} from 'lucide-react'

import {
  getDeployments,
  startDeployment,
  stopDeployment,
  restartDeployment,
  getDeploymentLogs,
} from '../services/api'
import { useToast } from '../components/Toast'
import PageHeader from '../components/shared/PageHeader'
import EmptyState from '../components/shared/EmptyState'

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
  const map = { ...HEALTH_STYLES, ...STATE_STYLES, gray: 'bg-gray-100 text-gray-700' }
  const cls = map[tone] || map.gray
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium ${cls}`}>
      {Icon && <Icon className="w-3 h-3" />}
      {children}
    </span>
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

const IconBtn = ({ icon: Icon, onClick, title, tone = 'gray', disabled = false }) => {
  const tones = {
    gray: 'text-gray-600 hover:bg-gray-100',
    red: 'text-red-600 hover:bg-red-50',
    green: 'text-green-600 hover:bg-green-50',
  }
  return (
    <button
      onClick={onClick}
      title={title}
      disabled={disabled}
      className={`p-1.5 rounded transition-colors disabled:opacity-50 ${tones[tone]}`}
    >
      <Icon className="w-4 h-4" />
    </button>
  )
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

const ContainerRow = ({ c, onStart, onStop, onRestart, onLogs, isMutating }) => {
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
          icon={c.health === 'healthy' ? CheckCircle2 : c.health === 'unhealthy' ? AlertCircle : Circle}
        >
          {c.health}
        </Chip>
      </td>
      <td className="px-3 py-2 font-mono text-xs">{c.ports || '-'}</td>
      <td className="px-3 py-2">
        <div className="flex justify-end gap-1">
          {running ? (
            <>
              <IconBtn title="Restart" onClick={() => onRestart(c.container_name)} icon={RotateCw} disabled={isMutating} />
              <IconBtn title="Stop" onClick={() => onStop(c.container_name)} icon={Square} tone="red" disabled={isMutating} />
            </>
          ) : (
            <IconBtn title="Start" onClick={() => onStart(c.container_name)} icon={Play} tone="green" disabled={isMutating} />
          )}
          <IconBtn title="Logs" onClick={() => onLogs(c.container_name)} icon={FileText} />
        </div>
      </td>
    </tr>
  )
}

const Deployments = () => {
  const [search, setSearch] = useState('')
  const [logsFor, setLogsFor] = useState(null)
  const toast = useToast()
  const qc = useQueryClient()

  const { data: deployData, isLoading, refetch } = useQuery({
    queryKey: ['deployments'],
    queryFn: () => getDeployments(),
    refetchInterval: POLL_MS,
  })

  const items = deployData?.items || []

  const filtered = useMemo(() => {
    if (!search.trim()) return items
    const q = search.toLowerCase()
    return items.filter((c) =>
      [c.container_name, c.image, c.project_id, c.compose_project]
        .filter(Boolean)
        .some((v) => String(v).toLowerCase().includes(q))
    )
  }, [items, search])

  const invalidate = () => qc.invalidateQueries({ queryKey: ['deployments'] })

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

  const isMutating = startMut.isPending || stopMut.isPending || restartMut.isPending

  const stats = useMemo(() => {
    const running = items.filter((c) => c.state === 'running').length
    const unhealthy = items.filter((c) => c.health === 'unhealthy').length
    const stopped = items.filter((c) => c.state !== 'running').length
    return { total: items.length, running, unhealthy, stopped }
  }, [items])

  return (
    <div className="space-y-4">
      <PageHeader title="Deployments" subtitle="Manage your deployed applications">
        <button
          onClick={() => refetch()}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm bg-white border border-gray-200 rounded hover:bg-gray-50"
        >
          <RefreshCw className="w-4 h-4" />
          Refresh
        </button>
      </PageHeader>

      {/* Stats row */}
      <div className="grid grid-cols-4 gap-3">
        <StatCard label="Total" value={stats.total} />
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
          placeholder="Search by container, image, project…"
          className="w-full pl-9 pr-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/30"
        />
      </div>

      {/* Container table */}
      {isLoading && <div className="text-sm text-gray-500">Loading deployments…</div>}
      {!isLoading && filtered.length === 0 && (
        <EmptyState
          icon={Rocket}
          title="No deployments"
          description="Deployed applications will appear here once an agent deploys code."
        />
      )}
      {!isLoading && filtered.length > 0 && (
        <div className="bg-white border border-gray-200 rounded-lg overflow-hidden">
          <table className="w-full text-sm">
            <thead className="text-xs uppercase text-gray-500 bg-gray-50">
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
              {filtered.map((c) => (
                <ContainerRow
                  key={c.container_id || c.container_name}
                  c={c}
                  onStart={(n) => startMut.mutate(n)}
                  onStop={(n) => stopMut.mutate(n)}
                  onRestart={(n) => restartMut.mutate(n)}
                  onLogs={(n) => setLogsFor(n)}
                  isMutating={isMutating}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}

      <LogsDrawer containerName={logsFor} onClose={() => setLogsFor(null)} />
    </div>
  )
}

export default Deployments
