/**
 * BranchEnvPipeline — pipe-and-node visual of one environment's deploy chain.
 *
 * Stages come from GET /api/branch-environments/{id}/pipeline:
 *   commit → ci-build → flux → (source | secrets) → helm → workloads → live
 * (or commit-removed → pruning for a teardown). When CI is still building
 * images the cluster-derived stages are hidden (they would show transient
 * Helm errors). Each node is colored by its status; the first failed stage
 * shows its error message below the row, so you can see exactly where a
 * deploy is busy and where it went wrong.
 */

import {
  GitCommit,
  RefreshCw,
  GitBranch,
  KeyRound,
  Package,
  Boxes,
  Globe,
  Trash2,
  Circle,
  Loader2,
  AlertCircle,
  ExternalLink,
  Zap,
} from 'lucide-react'

const STAGE_ICONS = {
  commit: GitCommit,
  'ci-build': Zap,
  flux: RefreshCw,
  source: GitBranch,
  secrets: KeyRound,
  helm: Package,
  workloads: Boxes,
  live: Globe,
  'commit-removed': Trash2,
  pruning: Boxes,
}

// Same palette as STATUS_STYLE in pages/BranchEnvironments.jsx.
const NODE_STYLE = {
  done: 'bg-green-100 text-green-600 border-green-300',
  busy: 'bg-blue-100 text-blue-600 border-blue-300',
  failed: 'bg-red-100 text-red-600 border-red-300',
  pending: 'bg-gray-50 text-gray-400 border-gray-200',
  skipped: 'bg-gray-50 text-gray-400 border-gray-200',
}

const PIPE_STYLE = {
  done: 'bg-green-300',
  busy: 'bg-blue-300 animate-pulse',
  failed: 'bg-red-300',
  pending: 'bg-gray-200',
  skipped: 'bg-gray-200',
}

// source + secrets run in parallel (both gate helm) — stack them in one column.
const groupColumns = (stages) => {
  const columns = []
  for (const stage of stages) {
    const prev = columns[columns.length - 1]
    if (stage.id === 'secrets' && prev?.[0]?.id === 'source') {
      prev.push(stage)
    } else {
      columns.push([stage])
    }
  }
  return columns
}

// The pipe leading INTO a column takes the column's most urgent status.
const columnStatus = (column) => {
  const statuses = column.map((s) => s.status)
  if (statuses.includes('failed')) return 'failed'
  if (statuses.includes('busy')) return 'busy'
  if (statuses.every((s) => s === 'done')) return 'done'
  return 'pending'
}

const isUrl = (s) => typeof s === 'string' && s.startsWith('http')

const StageNode = ({ stage }) => {
  const Icon = STAGE_ICONS[stage.id] || Circle
  const style = NODE_STYLE[stage.status] || NODE_STYLE.pending
  return (
    <div
      className="flex flex-col items-center w-16"
      data-testid={`pipeline-stage-${stage.id}`}
      data-status={stage.status}
      title={stage.message || stage.detail || stage.name}
    >
      <div
        className={`relative w-9 h-9 rounded-full border flex items-center justify-center ${style}`}
      >
        <Icon className="w-4 h-4" />
        {stage.status === 'busy' && (
          <Loader2 className="absolute -top-1 -right-1 w-3.5 h-3.5 animate-spin text-blue-500" />
        )}
      </div>
      <span className="mt-1 text-[10px] leading-tight text-center text-gray-500">
        {stage.name}
      </span>
      {stage.detail && (
        isUrl(stage.detail) ? (
          <a
            href={stage.detail}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-0.5 text-[10px] leading-tight text-center text-blue-500 hover:text-blue-700 underline font-mono"
            onClick={(e) => e.stopPropagation()}
          >
            <ExternalLink className="w-2.5 h-2.5" />
            View in Gitea
          </a>
        ) : (
          <span className="text-[10px] leading-tight text-center text-gray-400 font-mono">
            {stage.detail}
          </span>
        )
      )}
    </div>
  )
}

const BranchEnvPipeline = ({ stages }) => {
  if (!stages?.length) return null
  const columns = groupColumns(stages)
  const failed = stages.find((s) => s.status === 'failed')
  const busy = !failed && stages.find((s) => s.status === 'busy' && s.message)

  return (
    <div data-testid="branch-env-pipeline">
      <div className="flex items-start overflow-x-auto py-1">
        {columns.map((column, i) => (
          <div key={column[0].id} className="flex items-start min-w-0">
            {i > 0 && (
              <div
                className={`h-0.5 w-6 sm:w-8 mt-[18px] rounded-full flex-shrink-0 ${
                  PIPE_STYLE[columnStatus(column)] || PIPE_STYLE.pending
                }`}
              />
            )}
            <div className="flex flex-col items-center gap-2">
              {column.map((stage) => (
                <StageNode key={stage.id} stage={stage} />
              ))}
            </div>
          </div>
        ))}
      </div>

      {failed?.message && (
        <div
          className="mt-2 p-2 bg-red-50 border border-red-200 rounded text-xs text-red-700 flex items-start gap-1.5"
          title={failed.message}
        >
          <AlertCircle className="w-3.5 h-3.5 mt-0.5 flex-shrink-0" />
          <span className="min-w-0 break-words">
            <span className="font-medium">{failed.name}:</span> {failed.message}
          </span>
        </div>
      )}
      {busy && (
        <p className="mt-2 text-xs text-blue-600 truncate" title={busy.message}>
          {busy.name}: {busy.message}
        </p>
      )}
    </div>
  )
}

export default BranchEnvPipeline
