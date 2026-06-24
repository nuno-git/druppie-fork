/**
 * Dev Environments — manage developer VMs (sysbox workspaces via Guacamole).
 *
 * Lists dev VMs as cards, supports create (modal), open via Guacamole,
 * delete (stops + removes), and a manual k3s deploy trigger. Polls every 5s
 * while any VM is in the "creating" state.
 */

import { useState, useEffect, useMemo, useCallback } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  MonitorDot,
  Plus,
  RefreshCw,
  ExternalLink,
  Trash2,
  GitBranch,
  Rocket,
  AlertCircle,
  Loader2,
  X,
  Search,
} from 'lucide-react'

import { devEnvironmentsApi } from '../services/api'
import { useToast } from '../components/Toast'
import PageHeader from '../components/shared/PageHeader'
import EmptyState from '../components/shared/EmptyState'
import { SkeletonProjectCard } from '../components/shared/Skeleton'

const POLL_MS = 5000

const STATUS_STYLE = {
  creating: { cls: 'bg-amber-100 text-amber-700', dot: 'bg-amber-500', pulse: true },
  running: { cls: 'bg-green-100 text-green-700', dot: 'bg-green-500', pulse: true },
  stopped: { cls: 'bg-gray-100 text-gray-600', dot: 'bg-gray-400', pulse: false },
  error: { cls: 'bg-red-100 text-red-700', dot: 'bg-red-500', pulse: false },
}

const StatusBadge = ({ status }) => {
  const s = STATUS_STYLE[status] || STATUS_STYLE.stopped
  return (
    <span className={`inline-flex items-center px-2 py-1 rounded-full text-xs font-medium ${s.cls}`}>
      <span className={`w-2 h-2 rounded-full mr-1.5 ${s.dot} ${s.pulse ? 'animate-pulse' : ''}`} />
      {status}
    </span>
  )
}

const StatCard = ({ label, value, tone = 'gray' }) => {
  const tones = {
    gray: 'text-gray-700',
    green: 'text-green-700',
    amber: 'text-amber-700',
    red: 'text-red-700',
  }
  return (
    <div className="bg-white border border-gray-200 rounded-lg px-4 py-3">
      <div className="text-xs uppercase text-gray-500">{label}</div>
      <div className={`text-2xl font-semibold ${tones[tone]}`}>{value}</div>
    </div>
  )
}

const slugifyBranch = (branch) =>
  branch
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')

const deriveName = (branch) => {
  const slug = slugifyBranch(branch)
  return slug ? `dev-${slug}-vm` : ''
}

const DevVmCard = ({ vm, onDelete, isDeleting }) => {
  const canOpen = vm.status === 'running' && vm.guacamole_url
  const handleDelete = () => {
    if (window.confirm(`Delete "${vm.name}"?\n\nThis stops and removes the VM. This cannot be undone.`)) {
      onDelete(vm.id)
    }
  }

  return (
    <div className="p-4 rounded-xl border border-gray-100 bg-white hover:border-gray-200 transition-all relative group">
      {/* Header */}
      <div className="flex items-start justify-between mb-3">
        <div className="flex items-center min-w-0">
          <MonitorDot className="w-5 h-5 mr-2 text-blue-500 flex-shrink-0" />
          <h3 className="font-semibold text-gray-900 truncate">{vm.name}</h3>
        </div>
        <StatusBadge status={vm.status} />
      </div>

      {/* Branch */}
      {vm.branch && (
        <div className="mb-3 flex items-center">
          <GitBranch className="w-4 h-4 text-gray-400 mr-2 flex-shrink-0" />
          <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-blue-50 text-blue-700">
            {vm.branch}
          </span>
        </div>
      )}

      {/* Guacamole URL */}
      {canOpen && (
        <div className="mb-3 p-2 bg-green-50/70 rounded-lg">
          <div className="flex items-center justify-between">
            <div className="flex items-center min-w-0 flex-1">
              <ExternalLink className="w-4 h-4 text-green-600 mr-2 flex-shrink-0" />
              <span className="text-sm text-green-700 truncate font-mono">Guacamole desktop</span>
            </div>
          </div>
        </div>
      )}

      {/* Footer */}
      <div className="flex items-center justify-between text-xs text-gray-500">
        <span>{vm.created_at ? new Date(vm.created_at).toLocaleString() : '—'}</span>
        <span className="font-mono truncate max-w-[120px]">{vm.id}</span>
      </div>

      {/* Actions */}
      <div className="mt-3 flex items-center space-x-2">
        {canOpen ? (
          <a
            href={vm.guacamole_url}
            target="_blank"
            rel="noopener noreferrer"
            className="flex-1 py-2 px-3 text-sm text-white bg-green-600 hover:bg-green-700 rounded-lg transition-colors flex items-center justify-center focus:outline-none focus:ring-2 focus:ring-green-500 focus:ring-offset-2"
          >
            <ExternalLink className="w-4 h-4 mr-1.5" />
            Open VM
          </a>
        ) : (
          <button
            disabled
            title={vm.status === 'creating' ? 'VM is still starting…' : 'VM is not running'}
            className="flex-1 py-2 px-3 text-sm text-gray-400 bg-gray-100 rounded-lg cursor-not-allowed flex items-center justify-center"
          >
            <MonitorDot className="w-4 h-4 mr-1.5" />
            {vm.status === 'creating' ? 'Creating…' : 'Unavailable'}
          </button>
        )}
        <button
          onClick={handleDelete}
          disabled={isDeleting}
          className="py-2 px-3 text-sm text-red-600 bg-red-50 hover:bg-red-100 rounded-lg transition-colors flex items-center justify-center focus:outline-none focus:ring-2 focus:ring-red-500 focus:ring-offset-2 disabled:opacity-50"
          aria-label={`Delete ${vm.name}`}
        >
          {isDeleting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Trash2 className="w-4 h-4" />}
        </button>
      </div>
    </div>
  )
}

const CreateDevVmDialog = ({ onClose, onCreate, isCreating, createError }) => {
  const [name, setName] = useState('')
  const [branch, setBranch] = useState('')
  const [nameTouched, setNameTouched] = useState(false)

  useEffect(() => {
    const onKey = (e) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const handleBranchChange = (e) => {
    const value = e.target.value
    setBranch(value)
    if (!nameTouched) setName(deriveName(value))
  }

  const handleNameChange = (e) => {
    setNameTouched(true)
    setName(e.target.value)
  }

  const submit = (e) => {
    e.preventDefault()
    onCreate({ name: name.trim(), branch: branch.trim() })
  }

  return (
    <>
      <div className="fixed inset-0 bg-black/30 z-30" onClick={onClose} />
      <div className="fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 z-40 bg-white rounded-lg shadow-2xl border border-gray-200 p-5 w-[34rem] max-h-[85vh] overflow-y-auto">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <MonitorDot className="w-5 h-5 text-blue-600" />
            <h3 className="text-sm font-semibold text-gray-900">New Dev VM</h3>
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded text-gray-400 hover:text-gray-200 hover:bg-gray-100 transition-colors"
            aria-label="Close"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <form onSubmit={submit} className="space-y-4">
          <div>
            <label className="block text-xs font-medium text-gray-700 mb-1">Branch</label>
            <div className="relative">
              <GitBranch className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
              <input
                type="text"
                value={branch}
                onChange={handleBranchChange}
                autoFocus
                required
                placeholder="feature/my-branch"
                className="w-full pl-9 pr-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/30"
              />
            </div>
          </div>

          <div>
            <label className="block text-xs font-medium text-gray-700 mb-1">Name</label>
            <input
              type="text"
              value={name}
              onChange={handleNameChange}
              required
              placeholder="dev-my-branch-vm"
              className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm font-mono focus:outline-none focus:ring-2 focus:ring-blue-500/30"
            />
            <p className="text-xs text-gray-400 mt-1">Auto-suggested from the branch name — edit if needed.</p>
          </div>

          {createError && (
            <div className="bg-red-50 border border-red-200 rounded p-2 text-xs text-red-700">
              {createError}
            </div>
          )}

          <div className="flex justify-end gap-2 pt-1">
            <button
              type="button"
              onClick={onClose}
              disabled={isCreating}
              className="px-3 py-1.5 text-sm text-gray-600 rounded-md hover:bg-gray-100 transition-colors disabled:opacity-50"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={isCreating}
              className="px-3 py-1.5 text-sm font-medium bg-blue-600 text-white rounded-md hover:bg-blue-700 disabled:opacity-50 transition-colors flex items-center gap-1.5"
            >
              {isCreating ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Plus className="w-3.5 h-3.5" />}
              {isCreating ? 'Creating…' : 'Create VM'}
            </button>
          </div>
        </form>
      </div>
    </>
  )
}

const DeployCard = () => {
  const toast = useToast()
  const [image, setImage] = useState('')
  const [tag, setTag] = useState('latest')
  const [lastStatus, setLastStatus] = useState(null)

  const deployMut = useMutation({
    mutationFn: () => devEnvironmentsApi.triggerDeploy(image.trim(), tag.trim() || 'latest'),
    onSuccess: (data) => {
      const msg = data?.message || data?.status || 'Deploy triggered'
      setLastStatus({ ok: true, message: msg })
      toast.success('Deploy triggered', msg)
    },
    onError: (err) => {
      setLastStatus({ ok: false, message: err.message })
      toast.error('Deploy failed', err.message)
    },
  })

  return (
    <div className="bg-white border border-gray-200 rounded-lg p-4">
      <div className="flex items-center gap-2 mb-3">
        <Rocket className="w-5 h-5 text-blue-600" />
        <h3 className="text-sm font-semibold text-gray-900">Deploy to k3s</h3>
        <span className="text-xs text-gray-400">manual Harbor webhook trigger (testing)</span>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-[1fr_auto_auto] gap-2 items-end">
        <div>
          <label className="block text-xs font-medium text-gray-700 mb-1">Image</label>
          <input
            type="text"
            value={image}
            onChange={(e) => setImage(e.target.value)}
            placeholder="registry.example.com/app"
            className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm font-mono focus:outline-none focus:ring-2 focus:ring-blue-500/30"
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-700 mb-1">Tag</label>
          <input
            type="text"
            value={tag}
            onChange={(e) => setTag(e.target.value)}
            placeholder="latest"
            className="w-full sm:w-28 px-3 py-2 border border-gray-200 rounded-lg text-sm font-mono focus:outline-none focus:ring-2 focus:ring-blue-500/30"
          />
        </div>
        <button
          onClick={() => deployMut.mutate()}
          disabled={deployMut.isPending || !image.trim()}
          className="px-3 py-2 text-sm font-medium text-white bg-blue-600 hover:bg-blue-700 rounded-lg disabled:opacity-50 transition-colors flex items-center justify-center gap-1.5"
        >
          {deployMut.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Rocket className="w-4 h-4" />}
          Deploy Latest
        </button>
      </div>
      {lastStatus && (
        <div
          className={`mt-3 text-xs rounded p-2 ${
            lastStatus.ok
              ? 'bg-green-50 border border-green-200 text-green-700'
              : 'bg-red-50 border border-red-200 text-red-700'
          }`}
        >
          {lastStatus.message}
        </div>
      )}
    </div>
  )
}

const DevEnvironments = () => {
  const [showCreate, setShowCreate] = useState(false)
  const [search, setSearch] = useState('')
  const [createError, setCreateError] = useState(null)
  const toast = useToast()
  const qc = useQueryClient()

  const { data: vmData, isLoading, isError, error, refetch } = useQuery({
    queryKey: ['dev-vms'],
    queryFn: () => devEnvironmentsApi.list(),
    refetchInterval: (query) => {
      const items = query.state.data?.items || []
      return items.some((v) => v.status === 'creating') ? POLL_MS : false
    },
  })

  const items = vmData?.items || []

  const filtered = useMemo(() => {
    if (!search.trim()) return items
    const q = search.toLowerCase()
    return items.filter((v) =>
      [v.name, v.branch, v.status, v.id].filter(Boolean).some((val) => String(val).toLowerCase().includes(q))
    )
  }, [items, search])

  const stats = useMemo(() => {
    const running = items.filter((v) => v.status === 'running').length
    const creating = items.filter((v) => v.status === 'creating').length
    const errors = items.filter((v) => v.status === 'error').length
    return { total: items.length, running, creating, errors }
  }, [items])

  const invalidate = useCallback(() => {
    qc.invalidateQueries({ queryKey: ['dev-vms'] })
  }, [qc])

  const createMut = useMutation({
    mutationFn: (payload) => devEnvironmentsApi.create(payload),
    onSuccess: () => {
      setShowCreate(false)
      setCreateError(null)
      toast.success('Dev VM created', 'It will appear below once ready.')
      invalidate()
    },
    onError: (err) => setCreateError(err.message),
  })

  const deleteMut = useMutation({
    mutationFn: (id) => devEnvironmentsApi.delete(id),
    onSuccess: (_r, id) => {
      toast.success('Deleted dev VM', id)
      invalidate()
    },
    onError: (err) => toast.error('Delete failed', err.message),
  })

  return (
    <div className="space-y-4">
      <PageHeader title="Dev Environments" subtitle="Manage your developer VMs and trigger deployments.">
        <button
          onClick={() => refetch()}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm bg-white border border-gray-200 rounded hover:bg-gray-50"
        >
          <RefreshCw className="w-4 h-4" />
          Refresh
        </button>
        <button
          onClick={() => {
            setCreateError(null)
            setShowCreate(true)
          }}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium text-white bg-blue-600 rounded hover:bg-blue-700"
        >
          <Plus className="w-4 h-4" />
          New Dev VM
        </button>
      </PageHeader>

      {/* Stats */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <StatCard label="Total" value={stats.total} />
        <StatCard label="Running" value={stats.running} tone="green" />
        <StatCard label="Creating" value={stats.creating} tone="amber" />
        <StatCard label="Errors" value={stats.errors} tone={stats.errors ? 'red' : 'gray'} />
      </div>

      {/* Search */}
      <div className="relative">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search by name, branch, status…"
          className="w-full pl-9 pr-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/30"
        />
      </div>

      {/* List */}
      {isLoading && (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {Array.from({ length: 3 }).map((_, i) => (
            <SkeletonProjectCard key={i} />
          ))}
        </div>
      )}

      {isError && (
        <div className="flex flex-col items-center justify-center h-64 text-red-500">
          <AlertCircle className="w-12 h-12 mb-2" />
          <p className="text-lg font-medium">Failed to load dev environments</p>
          <p className="text-sm text-red-400">{error?.message || 'An unexpected error occurred'}</p>
          <button
            onClick={() => refetch()}
            className="mt-4 px-4 py-2 bg-blue-500 text-white rounded-lg hover:bg-blue-600 transition-colors"
          >
            Retry
          </button>
        </div>
      )}

      {!isLoading && !isError && filtered.length === 0 && (
        <EmptyState
          icon={MonitorDot}
          title={search.trim() ? 'No matching VMs' : 'No dev environments yet'}
          description={
            search.trim()
              ? 'Try a different search term.'
              : 'Create a dev VM to get an isolated workspace you can open in your browser.'
          }
          actionLabel={search.trim() ? undefined : 'New Dev VM'}
          onClick={search.trim() ? undefined : () => setShowCreate(true)}
        />
      )}

      {!isLoading && !isError && filtered.length > 0 && (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {filtered.map((vm) => (
            <DevVmCard
              key={vm.id}
              vm={vm}
              onDelete={(id) => deleteMut.mutate(id)}
              isDeleting={deleteMut.isPending && deleteMut.variables === vm.id}
            />
          ))}
        </div>
      )}

      {/* Deploy */}
      <DeployCard />

      {/* Create modal */}
      {showCreate && (
        <CreateDevVmDialog
          onClose={() => setShowCreate(false)}
          onCreate={(payload) => createMut.mutate(payload)}
          isCreating={createMut.isPending}
          createError={createError}
        />
      )}
    </div>
  )
}

export default DevEnvironments
