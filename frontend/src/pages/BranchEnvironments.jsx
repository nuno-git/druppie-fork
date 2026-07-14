/**
 * Branch Environments — deploy full per-branch Druppie instances to the cluster.
 *
 * Lists branch environments as cards keyed by branch, supports deploy (modal),
 * open via the env URL, redeploy, teardown, and cancelling an in-flight deploy
 * (of the env or its workspace — a cancel is a teardown of what's deploying).
 * Polls every 5s while any env is in a transitional state (deploying / deleting).
 */

import { useState, useEffect, useMemo, useCallback } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  GitBranch,
  Rocket,
  RefreshCw,
  ExternalLink,
  Trash2,
  AlertCircle,
  Loader2,
  X,
  Code2,
  Monitor,
  PowerOff,
  ChevronDown,
  ChevronUp,
  Ban,
} from 'lucide-react'

import { branchEnvironmentsApi } from '../services/api'
import { useAuth } from '../App'
import { useToast } from '../components/Toast'
import BranchEnvPipeline from '../components/BranchEnvPipeline'
import PageHeader from '../components/shared/PageHeader'
import EmptyState from '../components/shared/EmptyState'
import { SkeletonProjectCard } from '../components/shared/Skeleton'

const POLL_MS = 5000

const TRANSITIONAL = new Set(['deploying', 'deleting'])

const STATUS_STYLE = {
  deploying: { cls: 'bg-blue-100 text-blue-700', dot: 'bg-blue-500', spin: true },
  running: { cls: 'bg-green-100 text-green-700', dot: 'bg-green-500', spin: false },
  failed: { cls: 'bg-red-100 text-red-700', dot: 'bg-red-500', spin: false },
  deleting: { cls: 'bg-amber-100 text-amber-700', dot: 'bg-amber-500', spin: true },
}

const StatusBadge = ({ status }) => {
  const s = STATUS_STYLE[status] || STATUS_STYLE.failed
  return (
    <span className={`inline-flex items-center px-2 py-1 rounded-full text-xs font-medium ${s.cls}`}>
      {s.spin ? (
        <Loader2 className="w-3 h-3 mr-1.5 animate-spin" />
      ) : (
        <span className={`w-2 h-2 rounded-full mr-1.5 ${s.dot}`} />
      )}
      {status}
    </span>
  )
}

const StatCard = ({ label, value, tone = 'gray' }) => {
  const tones = {
    gray: 'text-gray-700',
    green: 'text-green-700',
    blue: 'text-blue-700',
    red: 'text-red-700',
  }
  return (
    <div className="bg-white border border-gray-200 rounded-lg px-4 py-3">
      <div className="text-xs uppercase text-gray-500">{label}</div>
      <div className={`text-2xl font-semibold ${tones[tone]}`}>{value}</div>
    </div>
  )
}

// Derive a DNS-safe slug from a branch name: lowercase, non-[a-z0-9-] → '-',
// collapse consecutive '-', trim '-' from both ends.
export const slugifyBranch = (branch) =>
  (branch || '')
    .toLowerCase()
    .replace(/[^a-z0-9-]+/g, '-')
    .replace(/-+/g, '-')
    .replace(/^-+|-+$/g, '')

const formatDate = (value) => {
  if (!value) return '—'
  const d = new Date(value)
  return Number.isNaN(d.getTime()) ? '—' : d.toLocaleDateString()
}

const WorkspaceSection = ({
  env,
  onEnableWorkspace,
  onDisableWorkspace,
  isEnablingWorkspace,
  isDisablingWorkspace,
}) => {
  const status = env.workspace_status
  const canOpenWorkspace = status === 'running' && env.workspace_url

  const handleDisable = () => {
    if (
      window.confirm(
        `Turn off the workspace for "${env.branch}"?\n\nThe in-browser VS Code will be removed. The environment itself stays running.`
      )
    ) {
      onDisableWorkspace(env.id)
    }
  }

  const handleCancelDeploy = () => {
    if (
      window.confirm(
        `Cancel the workspace deployment for "${env.branch}"?\n\nThe workspace being deployed will be removed. The environment itself stays running.`
      )
    ) {
      onDisableWorkspace(env.id)
    }
  }

  return (
    <div className="mt-3 pt-3 border-t border-gray-100">
      {env.workspace_enabled ? (
        <div className="flex items-center gap-2">
          {status === 'deploying' ? (
            <>
              <span className="inline-flex items-center px-2 py-1 rounded-full text-xs font-medium bg-blue-100 text-blue-700">
                <Loader2 className="w-3 h-3 mr-1.5 animate-spin" />
                deploying
              </span>
              <button
                onClick={handleCancelDeploy}
                disabled={isDisablingWorkspace}
                title="Cancel workspace deployment"
                aria-label={`Cancel workspace deployment for ${env.branch}`}
                className="ml-auto inline-flex items-center gap-1.5 py-1 px-2.5 text-xs text-amber-700 bg-amber-50 hover:bg-amber-100 rounded-lg transition-colors focus:outline-none focus:ring-2 focus:ring-amber-400 focus:ring-offset-2 disabled:opacity-50"
              >
                {isDisablingWorkspace ? (
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                ) : (
                  <Ban className="w-3.5 h-3.5" />
                )}
                Cancel
              </button>
            </>
          ) : (
            <span className="inline-flex items-center px-2 py-1 rounded-full text-xs font-medium bg-green-100 text-green-700">
              <span className="w-2 h-2 rounded-full mr-1.5 bg-green-500" />
              running
            </span>
          )}
          {canOpenWorkspace && (
            <>
              <a
                href={env.workspace_url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1.5 py-1 px-2.5 text-xs text-white bg-indigo-600 hover:bg-indigo-700 rounded-lg transition-colors focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-2"
              >
                <ExternalLink className="w-3.5 h-3.5" />
                Open workspace
              </a>
              <a
                href={`${env.workspace_url.replace(/\/$/, '')}/proxy/6080/`}
                target="_blank"
                rel="noopener noreferrer"
                title="XFCE desktop (noVNC) in this workspace"
                className="inline-flex items-center gap-1.5 py-1 px-2.5 text-xs text-indigo-700 bg-indigo-50 hover:bg-indigo-100 rounded-lg transition-colors focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-2"
              >
                <Monitor className="w-3.5 h-3.5" />
                Open desktop
              </a>
            </>
          )}
          {status !== 'deploying' && (
            <button
              onClick={handleDisable}
              disabled={isDisablingWorkspace}
              title="Turn off workspace"
              aria-label={`Turn off workspace for ${env.branch}`}
              className="ml-auto py-1 px-2 text-xs text-gray-500 bg-gray-50 hover:bg-gray-100 hover:text-gray-700 rounded-lg transition-colors flex items-center justify-center focus:outline-none focus:ring-2 focus:ring-gray-400 focus:ring-offset-2 disabled:opacity-50"
            >
              {isDisablingWorkspace ? (
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
              ) : (
                <PowerOff className="w-3.5 h-3.5" />
              )}
            </button>
          )}
        </div>
      ) : (
        <button
          onClick={() => onEnableWorkspace(env.id)}
          disabled={env.status !== 'running' || isEnablingWorkspace}
          title={
            env.status !== 'running'
              ? 'The environment must be running before you can turn on a workspace'
              : 'Turn on an in-browser VS Code workspace'
          }
          className="inline-flex items-center gap-1.5 py-1 px-2.5 text-xs text-gray-600 bg-gray-50 hover:bg-gray-100 hover:text-gray-800 rounded-lg transition-colors focus:outline-none focus:ring-2 focus:ring-gray-400 focus:ring-offset-2 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {isEnablingWorkspace ? (
            <Loader2 className="w-3.5 h-3.5 animate-spin" />
          ) : (
            <Code2 className="w-3.5 h-3.5" />
          )}
          Workspace aanzetten
        </button>
      )}
      <p className="mt-1.5 text-xs text-gray-400">
        VS Code in the browser with hot reload on this branch.
      </p>
    </div>
  )
}

const BranchEnvCard = ({
  env,
  onRedeploy,
  onDelete,
  onEnableWorkspace,
  onDisableWorkspace,
  isRedeploying,
  isDeleting,
  isEnablingWorkspace,
  isDisablingWorkspace,
}) => {
  const isTransitional = TRANSITIONAL.has(env.status)
  const canOpen = env.status === 'running' && env.url

  // Deploy pipeline: auto-open while the env is transitioning or failed so you
  // can see which hop is busy/broken; the toggle overrides the default.
  const pipelineAutoOpen = isTransitional || env.status === 'failed'
  const [pipelineChoice, setPipelineChoice] = useState(null)
  const pipelineOpen = pipelineChoice ?? pipelineAutoOpen

  const { data: pipeline, isLoading: pipelineLoading } = useQuery({
    queryKey: ['branch-env-pipeline', env.id],
    queryFn: () => branchEnvironmentsApi.pipeline(env.id),
    enabled: pipelineOpen,
    refetchInterval: pipelineOpen && pipelineAutoOpen ? POLL_MS : false,
  })

  const handleDelete = () => {
    if (
      window.confirm(
        `Tear down the environment for "${env.branch}"?\n\nThis removes the deployment from the cluster. This cannot be undone.`
      )
    ) {
      onDelete(env.id)
    }
  }

  // Cancelling a deploy IS a teardown — the manifests are removed from the
  // GitOps repo and Flux prunes whatever was already stood up.
  const handleCancelDeploy = () => {
    if (
      window.confirm(
        `Cancel the deployment of "${env.branch}"?\n\nThe environment being deployed will be removed from the cluster.`
      )
    ) {
      onDelete(env.id)
    }
  }

  return (
    <div className="p-4 rounded-xl border border-gray-100 bg-white hover:border-gray-200 transition-all">
      {/* Header */}
      <div className="flex items-start justify-between mb-3">
        <div className="flex items-center min-w-0">
          <GitBranch className="w-5 h-5 mr-2 text-blue-500 flex-shrink-0" />
          <h3 className="font-semibold text-gray-900 truncate">{env.branch}</h3>
        </div>
        <StatusBadge status={env.status} />
      </div>

      {/* URL */}
      {canOpen && (
        <div className="mb-3 p-2 bg-green-50/70 rounded-lg">
          <div className="flex items-center min-w-0">
            <ExternalLink className="w-4 h-4 text-green-600 mr-2 flex-shrink-0" />
            <span className="text-sm text-green-700 truncate font-mono">{env.url}</span>
          </div>
        </div>
      )}

      {/* Secondary text */}
      <div className="mb-3 space-y-1 text-xs text-gray-500">
        <div className="truncate">
          <span className="text-gray-400">namespace</span>{' '}
          <span className="font-mono">{env.namespace}</span>
        </div>
        <div className="truncate">
          <span className="text-gray-400">image</span>{' '}
          <span className="font-mono">{env.image_tag || 'default'}</span>
        </div>
      </div>

      {/* Failure message */}
      {env.status === 'failed' && env.status_message && (
        <div
          className="mb-3 p-2 bg-red-50 border border-red-200 rounded text-xs text-red-700 truncate"
          title={env.status_message}
        >
          {env.status_message}
        </div>
      )}

      {/* Footer */}
      <div className="flex items-center justify-between text-xs text-gray-500">
        <span>{formatDate(env.created_at)}</span>
        <span className="font-mono truncate max-w-[120px]">{env.slug}</span>
      </div>

      {/* Actions */}
      <div className="mt-3 flex items-center space-x-2">
        {canOpen ? (
          <a
            href={env.url}
            target="_blank"
            rel="noopener noreferrer"
            className="flex-1 py-2 px-3 text-sm text-white bg-green-600 hover:bg-green-700 rounded-lg transition-colors flex items-center justify-center focus:outline-none focus:ring-2 focus:ring-green-500 focus:ring-offset-2"
          >
            <ExternalLink className="w-4 h-4 mr-1.5" />
            Open
          </a>
        ) : (
          <button
            disabled
            title={isTransitional ? 'Environment is still transitioning…' : 'Environment is not running'}
            className="flex-1 py-2 px-3 text-sm text-gray-400 bg-gray-100 rounded-lg cursor-not-allowed flex items-center justify-center"
          >
            <ExternalLink className="w-4 h-4 mr-1.5" />
            {env.status === 'deploying' ? 'Deploying…' : env.status === 'deleting' ? 'Deleting…' : 'Unavailable'}
          </button>
        )}
        <button
          onClick={() => onRedeploy(env.id)}
          disabled={isTransitional || isRedeploying}
          title="Redeploy"
          className="py-2 px-3 text-sm text-blue-600 bg-blue-50 hover:bg-blue-100 rounded-lg transition-colors flex items-center justify-center focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 disabled:opacity-50"
          aria-label={`Redeploy ${env.branch}`}
        >
          {isRedeploying ? (
            <Loader2 className="w-4 h-4 animate-spin" />
          ) : (
            <RefreshCw className="w-4 h-4" />
          )}
        </button>
        {env.status === 'deploying' ? (
          <button
            onClick={handleCancelDeploy}
            disabled={isDeleting}
            title="Cancel deployment"
            className="py-2 px-3 text-sm text-amber-700 bg-amber-50 hover:bg-amber-100 rounded-lg transition-colors flex items-center justify-center focus:outline-none focus:ring-2 focus:ring-amber-400 focus:ring-offset-2 disabled:opacity-50"
            aria-label={`Cancel deployment of ${env.branch}`}
          >
            {isDeleting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Ban className="w-4 h-4" />}
          </button>
        ) : (
          <button
            onClick={handleDelete}
            disabled={isTransitional || isDeleting}
            className="py-2 px-3 text-sm text-red-600 bg-red-50 hover:bg-red-100 rounded-lg transition-colors flex items-center justify-center focus:outline-none focus:ring-2 focus:ring-red-500 focus:ring-offset-2 disabled:opacity-50"
            aria-label={`Delete ${env.branch}`}
          >
            {isDeleting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Trash2 className="w-4 h-4" />}
          </button>
        )}
      </div>

      {/* Deploy pipeline */}
      <div className="mt-3 pt-3 border-t border-gray-100">
        <button
          onClick={() => setPipelineChoice(!pipelineOpen)}
          aria-expanded={pipelineOpen}
          className="flex items-center gap-1 text-xs text-gray-500 hover:text-gray-700 transition-colors focus:outline-none"
        >
          {pipelineOpen ? (
            <ChevronUp className="w-3.5 h-3.5" />
          ) : (
            <ChevronDown className="w-3.5 h-3.5" />
          )}
          Pipeline
        </button>
        {pipelineOpen &&
          (pipeline ? (
            <div className="mt-2">
              <BranchEnvPipeline stages={pipeline.stages} />
            </div>
          ) : pipelineLoading ? (
            <div className="mt-2 flex items-center gap-2 text-xs text-gray-400">
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
              Loading pipeline…
            </div>
          ) : null)}
      </div>

      {/* Workspace */}
      <WorkspaceSection
        env={env}
        onEnableWorkspace={onEnableWorkspace}
        onDisableWorkspace={onDisableWorkspace}
        isEnablingWorkspace={isEnablingWorkspace}
        isDisablingWorkspace={isDisablingWorkspace}
      />
    </div>
  )
}

const DeployBranchDialog = ({ onClose, onDeploy, isDeploying, deployError, username }) => {
  const [branch, setBranch] = useState('')
  const [imageTag, setImageTag] = useState('')
  const [secretsSource, setSecretsSource] = useState('colab-dev')
  const [showAdvanced, setShowAdvanced] = useState(false)

  useEffect(() => {
    const onKey = (e) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const slug = slugifyBranch(branch)
  const previewUrl = slug ? `druppie-${slug}.rijnland.dev` : ''

  const submit = (e) => {
    e.preventDefault()
    if (!slug) return
    onDeploy({
      branch: branch.trim(),
      image_tag: imageTag.trim() || undefined,
      secrets_source: secretsSource,
    })
  }

  return (
    <>
      <div className="fixed inset-0 bg-black/30 z-30" onClick={onClose} />
      <div className="fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 z-40 bg-white rounded-lg shadow-2xl border border-gray-200 p-5 w-[34rem] max-h-[85vh] overflow-y-auto">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <Rocket className="w-5 h-5 text-blue-600" />
            <h3 className="text-sm font-semibold text-gray-900">Deploy branch environment</h3>
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition-colors"
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
                onChange={(e) => setBranch(e.target.value)}
                autoFocus
                required
                placeholder="feature/my-branch"
                className="w-full pl-9 pr-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/30"
              />
            </div>
            <p className="text-xs text-gray-400 mt-1">
              {previewUrl ? (
                <>
                  URL preview: <span className="font-mono text-gray-500">{previewUrl}</span>
                </>
              ) : (
                'A DNS-safe slug is derived from the branch name.'
              )}
            </p>
          </div>

          <div>
            <label className="block text-xs font-medium text-gray-700 mb-1">Secrets</label>
            <div className="space-y-1.5">
              <label className="flex items-start gap-2 text-sm text-gray-700 cursor-pointer">
                <input
                  type="radio"
                  name="secrets-source"
                  value="colab-dev"
                  checked={secretsSource === 'colab-dev'}
                  onChange={() => setSecretsSource('colab-dev')}
                  className="mt-0.5"
                />
                <span>
                  colab-dev defaults
                  <span className="block text-xs text-gray-400">
                    Borrow the LLM API keys colab-dev uses — works out of the box.
                  </span>
                </span>
              </label>
              <label className="flex items-start gap-2 text-sm text-gray-700 cursor-pointer">
                <input
                  type="radio"
                  name="secrets-source"
                  value="developer"
                  checked={secretsSource === 'developer'}
                  onChange={() => setSecretsSource('developer')}
                  className="mt-0.5"
                />
                <span>
                  My developer Vault map
                  <span className="block text-xs text-gray-400 font-mono">
                    druppie/developers/{(username || 'you').toLowerCase()}
                  </span>
                  <span className="block text-xs text-gray-400">
                    Self-service in the Vault UI; key names are the env var names
                    (e.g. ZAI_API_KEY). Missing keys fall back to chart defaults.
                  </span>
                </span>
              </label>
            </div>
          </div>

          <div>
            <button
              type="button"
              onClick={() => setShowAdvanced((v) => !v)}
              className="text-xs text-blue-600 hover:text-blue-700"
            >
              {showAdvanced ? 'Hide' : 'Show'} advanced options
            </button>
            {showAdvanced && (
              <div className="mt-2">
                <label className="block text-xs font-medium text-gray-700 mb-1">Image tag (optional)</label>
                <input
                  type="text"
                  value={imageTag}
                  onChange={(e) => setImageTag(e.target.value)}
                  placeholder="latest"
                  className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm font-mono focus:outline-none focus:ring-2 focus:ring-blue-500/30"
                />
                <p className="text-xs text-gray-400 mt-1">
                  Leave empty to use the branch&apos;s default image tag.
                </p>
              </div>
            )}
          </div>

          {deployError && (
            <div className="bg-red-50 border border-red-200 rounded p-2 text-xs text-red-700">
              {deployError}
            </div>
          )}

          <div className="flex justify-end gap-2 pt-1">
            <button
              type="button"
              onClick={onClose}
              disabled={isDeploying}
              className="px-3 py-1.5 text-sm text-gray-600 rounded-md hover:bg-gray-100 transition-colors disabled:opacity-50"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={isDeploying || !slug}
              className="px-3 py-1.5 text-sm font-medium bg-blue-600 text-white rounded-md hover:bg-blue-700 disabled:opacity-50 transition-colors flex items-center gap-1.5"
            >
              {isDeploying ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Rocket className="w-3.5 h-3.5" />}
              {isDeploying ? 'Deploying…' : 'Deploy'}
            </button>
          </div>
        </form>
      </div>
    </>
  )
}

const BranchEnvironments = () => {
  const [showDeploy, setShowDeploy] = useState(false)
  const [deployError, setDeployError] = useState(null)
  const { user } = useAuth() || {}
  const toast = useToast()
  const qc = useQueryClient()

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ['branch-environments'],
    queryFn: () => branchEnvironmentsApi.list(),
    refetchInterval: (query) => {
      const items = query.state.data?.items || []
      const busy = items.some(
        (e) => TRANSITIONAL.has(e.status) || e.workspace_status === 'deploying'
      )
      return busy ? POLL_MS : false
    },
  })

  const items = data?.items || []

  const stats = useMemo(() => {
    const running = items.filter((e) => e.status === 'running').length
    const deploying = items.filter((e) => e.status === 'deploying').length
    const failed = items.filter((e) => e.status === 'failed').length
    return { total: items.length, running, deploying, failed }
  }, [items])

  const invalidate = useCallback(() => {
    qc.invalidateQueries({ queryKey: ['branch-environments'] })
  }, [qc])

  const deployMut = useMutation({
    mutationFn: (payload) => branchEnvironmentsApi.deploy(payload),
    onSuccess: (env, payload) => {
      setShowDeploy(false)
      setDeployError(null)
      // Surface the secrets source the backend actually used, and call out a
      // fallback explicitly when it differs from what was requested.
      const used = env?.secrets_source || 'colab-dev'
      const fellBack = payload?.secrets_source && payload.secrets_source !== used
      toast.success(
        'Deploy started',
        fellBack
          ? `Requested "${payload.secrets_source}" secrets were unavailable — fell back to "${used}". The environment will appear below once ready.`
          : `Using "${used}" secrets. The environment will appear below once ready.`
      )
      invalidate()
    },
    onError: (err) => setDeployError(err.message),
  })

  const redeployMut = useMutation({
    mutationFn: (id) => branchEnvironmentsApi.redeploy(id),
    onSuccess: () => {
      toast.success('Redeploy started', 'The environment is being redeployed.')
      invalidate()
    },
    onError: (err) => toast.error('Redeploy failed', err.message),
  })

  const deleteMut = useMutation({
    mutationFn: (id) => branchEnvironmentsApi.teardown(id),
    onSuccess: () => {
      toast.success('Teardown started', 'The environment is being removed.')
      invalidate()
    },
    onError: (err) => toast.error('Teardown failed', err.message),
  })

  const enableWorkspaceMut = useMutation({
    mutationFn: (id) => branchEnvironmentsApi.enableWorkspace(id),
    onSuccess: () => {
      toast.success('Workspace starting', 'The in-browser VS Code is being deployed.')
      invalidate()
    },
    onError: (err) => toast.error('Could not turn on workspace', err.message),
  })

  const disableWorkspaceMut = useMutation({
    mutationFn: (id) => branchEnvironmentsApi.disableWorkspace(id),
    onSuccess: () => {
      toast.success('Workspace stopping', 'The workspace is being removed.')
      invalidate()
    },
    onError: (err) => toast.error('Could not turn off workspace', err.message),
  })

  return (
    <div className="space-y-4">
      <PageHeader
        title="Branch Environments"
        subtitle="Deploy a full Druppie instance for a git branch to the cluster."
      >
        <button
          onClick={() => refetch()}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm bg-white border border-gray-200 rounded hover:bg-gray-50"
        >
          <RefreshCw className="w-4 h-4" />
          Refresh
        </button>
        <button
          onClick={() => {
            setDeployError(null)
            setShowDeploy(true)
          }}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium text-white bg-blue-600 rounded hover:bg-blue-700"
        >
          <Rocket className="w-4 h-4" />
          Deploy branch
        </button>
      </PageHeader>

      {/* Stats */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <StatCard label="Total" value={stats.total} />
        <StatCard label="Running" value={stats.running} tone="green" />
        <StatCard label="Deploying" value={stats.deploying} tone="blue" />
        <StatCard label="Failed" value={stats.failed} tone={stats.failed ? 'red' : 'gray'} />
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
          <p className="text-lg font-medium">Failed to load branch environments</p>
          <p className="text-sm text-red-400">{error?.message || 'An unexpected error occurred'}</p>
          <button
            onClick={() => refetch()}
            className="mt-4 px-4 py-2 bg-blue-500 text-white rounded-lg hover:bg-blue-600 transition-colors"
          >
            Retry
          </button>
        </div>
      )}

      {!isLoading && !isError && items.length === 0 && (
        <EmptyState
          icon={GitBranch}
          title="No branch environments yet"
          description="Deploy a full Druppie instance for a git branch to preview it on the cluster."
          actionLabel="Deploy branch"
          onClick={() => {
            setDeployError(null)
            setShowDeploy(true)
          }}
        />
      )}

      {!isLoading && !isError && items.length > 0 && (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {items.map((env) => (
            <BranchEnvCard
              key={env.branch}
              env={env}
              onRedeploy={(id) => redeployMut.mutate(id)}
              onDelete={(id) => deleteMut.mutate(id)}
              onEnableWorkspace={(id) => enableWorkspaceMut.mutate(id)}
              onDisableWorkspace={(id) => disableWorkspaceMut.mutate(id)}
              isRedeploying={redeployMut.isPending && redeployMut.variables === env.id}
              isDeleting={deleteMut.isPending && deleteMut.variables === env.id}
              isEnablingWorkspace={enableWorkspaceMut.isPending && enableWorkspaceMut.variables === env.id}
              isDisablingWorkspace={disableWorkspaceMut.isPending && disableWorkspaceMut.variables === env.id}
            />
          ))}
        </div>
      )}

      {/* Deploy modal */}
      {showDeploy && (
        <DeployBranchDialog
          onClose={() => setShowDeploy(false)}
          onDeploy={(payload) => deployMut.mutate(payload)}
          isDeploying={deployMut.isPending}
          deployError={deployError}
          username={user?.username}
        />
      )}
    </div>
  )
}

export default BranchEnvironments
