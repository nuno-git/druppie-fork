/**
 * Cached Dependencies Page
 *
 * Shows packages cached in the shared sandbox dependency cache.
 * Two views: grouped by package manager, or grouped by project.
 */

import React, { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Package, Search, RefreshCw, ChevronDown, ChevronRight, FolderOpen, Layers } from 'lucide-react'
import { Link } from 'react-router-dom'
import { getCachedPackages, getAllProjectDependencies } from '../services/api'
import PageHeader from '../components/shared/PageHeader'

const MANAGER_LABELS = {
  npm: 'npm',
  pnpm: 'pnpm',
  bun: 'Bun',
  uv: 'uv (Python)',
  pip: 'pip',
}

const MANAGER_COLORS = {
  npm: 'bg-red-100 text-red-700',
  pnpm: 'bg-orange-100 text-orange-700',
  bun: 'bg-yellow-100 text-yellow-800',
  uv: 'bg-blue-100 text-blue-700',
  pip: 'bg-green-100 text-green-700',
}

// ─── Package Manager View ───────────────────────────────────────────────

const ManagerSection = ({ manager, packages, filter, projectMap }) => {
  const [expanded, setExpanded] = useState(true)

  const filtered = filter
    ? packages.filter(p => p.name.toLowerCase().includes(filter.toLowerCase()))
    : packages

  if (filter && filtered.length === 0) return null

  return (
    <div className="bg-white rounded-xl border border-gray-100">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center gap-3 px-5 py-4 text-left hover:bg-gray-50 transition-colors rounded-xl"
      >
        {expanded ? <ChevronDown className="w-4 h-4 text-gray-400" /> : <ChevronRight className="w-4 h-4 text-gray-400" />}
        <span className="font-medium text-gray-900">{MANAGER_LABELS[manager] || manager}</span>
        <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${MANAGER_COLORS[manager] || 'bg-gray-100 text-gray-700'}`}>
          {filtered.length}
        </span>
      </button>
      {expanded && filtered.length > 0 && (
        <div className="border-t border-gray-100 px-5 py-3">
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-x-6 gap-y-1">
            {filtered.map((pkg, i) => {
              const projects = projectMap?.[`${manager}:${pkg.name}`] || []
              return (
                <div key={`${pkg.name}-${pkg.version}-${i}`} className="py-1 min-w-0">
                  <div className="flex items-baseline gap-1.5">
                    <span className="text-sm text-gray-900 font-mono truncate">{pkg.name}</span>
                    <span className="text-xs text-gray-400 flex-shrink-0">{pkg.version}</span>
                  </div>
                  {projects.length > 0 && (
                    <div className="text-[11px] text-gray-400 truncate">
                      {projects.map((p, j) => (
                        <Link key={p.project_id} to={`/projects/${p.project_id}`} className="text-blue-400 hover:text-blue-600 hover:underline">
                          {p.project_name}{j < projects.length - 1 ? ', ' : ''}
                        </Link>
                      ))}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        </div>
      )}
      {expanded && filtered.length === 0 && (
        <div className="border-t border-gray-100 px-5 py-4 text-sm text-gray-400">No packages cached</div>
      )}
    </div>
  )
}

// ─── Project View ───────────────────────────────────────────────────────

const ProjectSection = ({ project, filter }) => {
  const [expanded, setExpanded] = useState(true)

  const filtered = filter
    ? project.packages.filter(p => p.name.toLowerCase().includes(filter.toLowerCase()))
    : project.packages

  if (filter && filtered.length === 0) return null

  // Group packages by manager
  const byManager = {}
  for (const pkg of filtered) {
    if (!byManager[pkg.manager]) byManager[pkg.manager] = []
    byManager[pkg.manager].push(pkg)
  }

  return (
    <div className="bg-white rounded-xl border border-gray-100">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center gap-3 px-5 py-4 text-left hover:bg-gray-50 transition-colors rounded-xl"
      >
        {expanded ? <ChevronDown className="w-4 h-4 text-gray-400" /> : <ChevronRight className="w-4 h-4 text-gray-400" />}
        <FolderOpen className="w-4 h-4 text-blue-500" />
        <Link
          to={`/projects/${project.project_id}`}
          onClick={e => e.stopPropagation()}
          className="font-medium text-gray-900 hover:text-blue-600 hover:underline"
        >
          {project.project_name}
        </Link>
        <span className="px-2 py-0.5 rounded-full text-xs font-medium bg-gray-100 text-gray-700">
          {filtered.length} packages
        </span>
      </button>
      {expanded && (
        <div className="border-t border-gray-100 px-5 py-3 space-y-3">
          {Object.entries(byManager)
            .sort(([a], [b]) => a.localeCompare(b))
            .map(([manager, pkgs]) => (
              <div key={manager}>
                <div className="flex items-center gap-2 mb-1">
                  <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${MANAGER_COLORS[manager] || 'bg-gray-100 text-gray-700'}`}>
                    {MANAGER_LABELS[manager] || manager}
                  </span>
                  <span className="text-xs text-gray-400">{pkgs.length}</span>
                </div>
                <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-x-6 gap-y-0.5 ml-2">
                  {pkgs.map((pkg, i) => (
                    <div key={`${pkg.name}-${pkg.version}-${i}`} className="flex items-baseline gap-2 py-0.5">
                      <span className="text-sm text-gray-900 font-mono truncate">{pkg.name}</span>
                      <span className="text-xs text-gray-400 flex-shrink-0">{pkg.version}</span>
                    </div>
                  ))}
                </div>
              </div>
            ))}
        </div>
      )}
    </div>
  )
}

// ─── Main Page ──────────────────────────────────────────────────────────

const CachedDependencies = () => {
  const [filter, setFilter] = useState('')
  const [view, setView] = useState('manager') // 'manager' or 'project'

  const { data, isLoading, isError, error, refetch, isFetching } = useQuery({
    queryKey: ['cached-packages'],
    queryFn: getCachedPackages,
    staleTime: 30000,
  })

  const { data: projectDeps } = useQuery({
    queryKey: ['all-project-dependencies'],
    queryFn: getAllProjectDependencies,
    staleTime: 30000,
  })

  const managers = data?.managers || {}
  const totalCount = data?.total_count || Object.values(managers).reduce((sum, pkgs) => sum + pkgs.length, 0)

  // Build lookup: "manager:name" -> [{project_id, project_name}]
  const projectMap = {}
  if (projectDeps) {
    for (const proj of projectDeps) {
      for (const pkg of proj.packages) {
        const key = `${pkg.manager}:${pkg.name}`
        if (!projectMap[key]) projectMap[key] = []
        if (!projectMap[key].some(p => p.project_id === proj.project_id)) {
          projectMap[key].push({ project_id: proj.project_id, project_name: proj.project_name })
        }
      }
    }
  }

  return (
    <div>
      <PageHeader
        title="Dependency Cache"
        subtitle={`${totalCount} packages cached across ${Object.keys(managers).length} package managers`}
        icon={Package}
      />

      {/* Toolbar */}
      <div className="flex items-center gap-3 mb-4">
        <div className="relative flex-1 max-w-sm">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
          <input
            type="text"
            placeholder="Filter packages..."
            value={filter}
            onChange={e => setFilter(e.target.value)}
            className="w-full pl-9 pr-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
          />
        </div>

        {/* View toggle */}
        <div className="flex bg-gray-100 rounded-lg p-0.5">
          <button
            onClick={() => setView('manager')}
            className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${
              view === 'manager' ? 'bg-white text-gray-900 shadow-sm' : 'text-gray-500 hover:text-gray-700'
            }`}
          >
            <Layers className="w-3.5 h-3.5" />
            By Manager
          </button>
          <button
            onClick={() => setView('project')}
            className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${
              view === 'project' ? 'bg-white text-gray-900 shadow-sm' : 'text-gray-500 hover:text-gray-700'
            }`}
          >
            <FolderOpen className="w-3.5 h-3.5" />
            By Project
          </button>
        </div>

        <button
          onClick={() => refetch()}
          disabled={isFetching}
          className="flex items-center gap-1.5 px-3 py-2 text-sm text-gray-600 bg-white border border-gray-200 rounded-lg hover:bg-gray-50 disabled:opacity-50"
        >
          <RefreshCw className={`w-4 h-4 ${isFetching ? 'animate-spin' : ''}`} />
          Refresh
        </button>
      </div>

      {/* Error from cache scan */}
      {data?.error && (
        <div className="mb-4 p-3 bg-yellow-50 border border-yellow-200 rounded-lg text-sm text-yellow-800">
          {data.error}
        </div>
      )}

      {/* Loading */}
      {isLoading && (
        <div className="space-y-3">
          {[1, 2, 3].map(i => (
            <div key={i} className="bg-white rounded-xl border border-gray-100 p-5 animate-pulse">
              <div className="h-5 bg-gray-200 rounded w-32" />
            </div>
          ))}
        </div>
      )}

      {/* Fetch error */}
      {isError && (
        <div className="bg-white rounded-xl border border-red-200 p-6 text-center">
          <p className="text-red-600 mb-2">Failed to load cached packages</p>
          <p className="text-sm text-gray-500">{error?.message}</p>
          <button onClick={() => refetch()} className="mt-3 px-4 py-2 text-sm bg-blue-600 text-white rounded-lg hover:bg-blue-700">
            Retry
          </button>
        </div>
      )}

      {/* Content */}
      {!isLoading && !isError && (
        <div className="space-y-3">
          {view === 'manager' && (
            <>
              {Object.entries(managers).length === 0 ? (
                <div className="bg-white rounded-xl border border-gray-100 p-8 text-center text-gray-500">
                  <Package className="w-10 h-10 mx-auto mb-3 text-gray-300" />
                  <p>No cached packages yet</p>
                  <p className="text-sm mt-1">Packages will appear here after sandbox runs install dependencies</p>
                </div>
              ) : (
                Object.entries(managers)
                  .sort(([, a], [, b]) => b.length - a.length)
                  .map(([manager, packages]) => (
                    <ManagerSection key={manager} manager={manager} packages={packages} filter={filter} projectMap={projectMap} />
                  ))
              )}
            </>
          )}

          {view === 'project' && (
            <>
              {(!projectDeps || projectDeps.length === 0) ? (
                <div className="bg-white rounded-xl border border-gray-100 p-8 text-center text-gray-500">
                  <FolderOpen className="w-10 h-10 mx-auto mb-3 text-gray-300" />
                  <p>No project dependencies tracked yet</p>
                  <p className="text-sm mt-1">Dependencies are linked to projects after sandbox runs install packages</p>
                </div>
              ) : (
                projectDeps.map(project => (
                  <ProjectSection key={project.project_id} project={project} filter={filter} />
                ))
              )}
            </>
          )}
        </div>
      )}
    </div>
  )
}

export default CachedDependencies
