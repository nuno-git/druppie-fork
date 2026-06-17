/**
 * Projects Page - View and manage projects with deployment status
 */

import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Folder,
  ExternalLink,
  GitBranch,
  Play,
  Square,
  CheckCircle,
  Copy,
  Server,
  Trash2,
  Loader2,
  AlertCircle,
  Eye,
  CheckSquare,
  X,
} from 'lucide-react'

import { getProjects, getDeployments, stopDeployment, deleteProjects } from '../services/api'
import { useToast } from '../components/Toast'
import PageHeader from '../components/shared/PageHeader'
import SharedCopyButton from '../components/shared/CopyButton'
import { SkeletonProjectCard } from '../components/shared/Skeleton'
import EmptyState from '../components/shared/EmptyState'

const StatusBadge = ({ isRunning, hasRepo }) => {
  if (isRunning) {
    return (
      <span className="inline-flex items-center px-2 py-1 rounded-full text-xs font-medium bg-green-100 text-green-700">
        <span className="w-2 h-2 bg-green-500 rounded-full mr-1.5 animate-pulse" />
        Running
      </span>
    )
  }

  if (hasRepo) {
    return (
      <span className="inline-flex items-center px-2 py-1 rounded-full text-xs font-medium bg-blue-100 text-blue-700">
        <CheckCircle className="w-3 h-3 mr-1" />
        Ready
      </span>
    )
  }

  return (
    <span className="inline-flex items-center px-2 py-1 rounded-full text-xs font-medium bg-gray-100 text-gray-600">
      <CheckCircle className="w-3 h-3 mr-1" />
      Created
    </span>
  )
}

const CopyButton = SharedCopyButton

const ProjectCard = ({ project, deployment, onDelete, isDeleting, onViewDetails, onStop, isStopping, selectionMode, isSelected, onToggleSelect }) => {
  const repoUrl = project.repo_url
  const hasRepo = !!repoUrl
  const isRunning = !!deployment
  const appUrl = deployment?.app_url

  const handleDelete = (e) => {
    e.stopPropagation()
    if (window.confirm(`Are you sure you want to delete "${project.name}"?\n\nThis will archive the project.`)) {
      onDelete(project.id)
    }
  }

  const handleClick = () => {
    if (selectionMode) {
      onToggleSelect(project.id)
    }
  }

  return (
    <div
      className={`p-4 rounded-xl border transition-all relative group bg-white ${
        selectionMode && isSelected
          ? 'border-blue-400 bg-blue-50/30 ring-1 ring-blue-200'
          : 'border-gray-100 hover:border-gray-200 hover:bg-gray-50/30'
      } ${isDeleting ? 'opacity-50 pointer-events-none' : ''} ${selectionMode ? 'cursor-pointer' : ''}`}
      onClick={handleClick}
    >
      {/* Selection checkbox */}
      {selectionMode && (
        <div className="absolute top-3 left-3 z-10">
          {isSelected ? (
            <CheckSquare className="w-5 h-5 text-blue-600" />
          ) : (
            <Square className="w-5 h-5 text-gray-400" />
          )}
        </div>
      )}

      {/* Delete Button */}
      {!selectionMode && (
        <button
          onClick={handleDelete}
          disabled={isDeleting}
          className="absolute top-2 right-2 p-1.5 text-gray-400 hover:text-red-600 hover:bg-red-50 rounded-lg opacity-0 group-hover:opacity-100 transition-all focus:opacity-100 focus:outline-none focus:ring-2 focus:ring-red-500"
          aria-label={`Delete project ${project.name}`}
        >
          {isDeleting ? (
            <div className="w-4 h-4 border-2 border-red-600 border-t-transparent rounded-full animate-spin" />
          ) : (
            <Trash2 className="w-4 h-4" />
          )}
        </button>
      )}

      {/* Header */}
      <div className={`flex items-start justify-between mb-3 pr-8 ${selectionMode ? 'ml-7' : ''}`}>
        <div className="flex items-center">
          <Folder className="w-5 h-5 mr-2 text-yellow-500" />
          <h3 className="font-semibold text-gray-900 truncate">{project.name}</h3>
        </div>
        <StatusBadge hasRepo={hasRepo} isRunning={isRunning} />
      </div>
      {project.username && (
        <div className={`mb-2 ${selectionMode ? 'ml-7' : ''}`}>
          <span className={`text-xs font-medium ${
            project.username.startsWith('t-') ? 'text-orange-500' : 'text-blue-500'
          }`}>
            {project.username}
          </span>
        </div>
      )}

      {/* Description */}
      {project.description && (
        <p className={`text-sm text-gray-600 mb-3 line-clamp-2 ${selectionMode ? 'ml-7' : ''}`}>{project.description}</p>
      )}

      {/* Repo URL */}
      {repoUrl && (
        <div className="mb-3 p-2 bg-gray-50/70 rounded-lg">
          <div className="flex items-center justify-between">
            <div className="flex items-center min-w-0 flex-1">
              <GitBranch className="w-4 h-4 text-gray-400 mr-2 flex-shrink-0" />
              <a
                href={repoUrl}
                target="_blank"
                rel="noopener noreferrer"
                onClick={(e) => e.stopPropagation()}
                className="text-sm text-blue-600 hover:text-blue-800 hover:underline truncate"
              >
                {repoUrl}
              </a>
            </div>
            <div className="flex items-center ml-2" onClick={(e) => e.stopPropagation()}>
              <CopyButton text={repoUrl} label="repository URL" />
              <a
                href={repoUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="p-1.5 text-gray-400 hover:text-blue-600 hover:bg-blue-50 rounded transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500"
                aria-label="Open repository in new tab"
              >
                <ExternalLink className="w-4 h-4" />
              </a>
            </div>
          </div>
        </div>
      )}

      {/* App URL if running */}
      {appUrl && (
        <div className="mb-3 p-2 bg-green-50/70 rounded-lg">
          <div className="flex items-center justify-between">
            <div className="flex items-center min-w-0 flex-1">
              <Server className="w-4 h-4 text-green-600 mr-2 flex-shrink-0" />
              <a
                href={appUrl}
                target="_blank"
                rel="noopener noreferrer"
                onClick={(e) => e.stopPropagation()}
                className="text-sm text-green-700 hover:text-green-900 hover:underline truncate"
              >
                {appUrl}
              </a>
            </div>
            <div className="flex items-center ml-2" onClick={(e) => e.stopPropagation()}>
              <a
                href={appUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center px-2 py-1 bg-green-500 text-white text-xs rounded hover:bg-green-600 transition-colors focus:outline-none focus:ring-2 focus:ring-green-500 focus:ring-offset-2"
                aria-label="Open running application in new tab"
              >
                <Play className="w-3 h-3 mr-1" />
                Open
              </a>
            </div>
          </div>
        </div>
      )}

      {/* Footer */}
      <div className="flex items-center justify-between text-xs text-gray-500">
        <span>{new Date(project.created_at).toLocaleDateString()}</span>
        <div className="flex items-center space-x-2">
          {hasRepo && (
            <span className="flex items-center text-green-600">
              <GitBranch className="w-3 h-3 mr-1" />
              Repo
            </span>
          )}
          {isRunning && (
            <span className="flex items-center text-green-600">
              <Play className="w-3 h-3 mr-1" />
              Live
            </span>
          )}
        </div>
      </div>

      {/* Action Buttons */}
      {!selectionMode && (
        <div className="mt-3 flex items-center space-x-2">
          <button
            onClick={(e) => {
              e.stopPropagation()
              onViewDetails(project.id)
            }}
            className="flex-1 py-2 px-3 text-sm text-blue-600 bg-blue-50 hover:bg-blue-100 rounded-lg transition-colors flex items-center justify-center focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2"
            aria-label={`View details for ${project.name}`}
          >
            <Eye className="w-4 h-4 mr-1.5" />
            Details
          </button>
          {isRunning && (
            <button
              onClick={(e) => {
                e.stopPropagation()
                onStop(deployment.container_name)
              }}
              disabled={isStopping}
              className="py-2 px-3 text-sm text-red-600 bg-red-50 hover:bg-red-100 rounded-lg transition-colors flex items-center justify-center focus:outline-none focus:ring-2 focus:ring-red-500 focus:ring-offset-2 disabled:opacity-50"
              aria-label={`Stop ${project.name}`}
            >
              {isStopping ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <Square className="w-4 h-4" />
              )}
            </button>
          )}
        </div>
      )}
    </div>
  )
}

const Projects = () => {
  const [deletingId, setDeletingId] = useState(null)
  const [stoppingName, setStoppingName] = useState(null)
  const [selectionMode, setSelectionMode] = useState(false)
  const [selectedIds, setSelectedIds] = useState(new Set())

  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const toast = useToast()

  // Fetch projects — extract .items from paginated response
  const {
    data: projectsData,
    isLoading,
    isError,
    error,
    refetch,
  } = useQuery({
    queryKey: ['projects'],
    queryFn: getProjects,
  })

  const projects = projectsData?.items ?? []

  // Fetch all running deployments to merge with projects
  const { data: deploymentsData } = useQuery({
    queryKey: ['deployments'],
    queryFn: () => getDeployments(),
    refetchInterval: 15000,
  })

  // Build a map of project_id -> deployment for quick lookup
  const deploymentsByProject = {}
  for (const dep of deploymentsData?.items ?? []) {
    if (dep.project_id) {
      deploymentsByProject[dep.project_id] = dep
    }
  }

  const deleteMutation = useMutation({
    mutationFn: (projectId) => deleteProjects([projectId]),
    onMutate: (projectId) => setDeletingId(projectId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['projects'] })
      setDeletingId(null)
    },
    onError: (err) => {
      setDeletingId(null)
      toast.error('Delete Failed', `Could not delete project: ${err.message}`)
    },
  })

  const batchDeleteMutation = useMutation({
    mutationFn: (ids) => deleteProjects(ids.length === projects.length ? null : [...ids]),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['projects'] })
      setSelectionMode(false)
      setSelectedIds(new Set())
    },
    onError: (err) => {
      toast.error('Delete Failed', `Could not delete projects: ${err.message}`)
    },
  })

  const stopMutation = useMutation({
    mutationFn: stopDeployment,
    onMutate: (containerName) => setStoppingName(containerName),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['deployments'] })
      queryClient.invalidateQueries({ queryKey: ['projects'] })
      setStoppingName(null)
    },
    onError: (err) => {
      setStoppingName(null)
      toast.error('Stop Failed', `Could not stop deployment: ${err.message}`)
    },
  })

  const toggleSelection = (id) => {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const toggleSelectAll = () => {
    if (selectedIds.size === projects.length) {
      setSelectedIds(new Set())
    } else {
      setSelectedIds(new Set(projects.map((p) => p.id)))
    }
  }

  const exitSelectionMode = () => {
    setSelectionMode(false)
    setSelectedIds(new Set())
  }

  const handleBatchDelete = () => {
    if (selectedIds.size === 0) return
    const label = selectedIds.size === projects.length ? 'all' : selectedIds.size
    if (window.confirm(`Delete ${label} project${selectedIds.size === 1 ? '' : 's'}?\n\nThis will permanently delete the selected projects and their Gitea repositories. This cannot be undone.`)) {
      batchDeleteMutation.mutate(selectedIds)
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader title="Projects" subtitle="View your created projects and their repositories.">
        <div className="flex items-center gap-2">
          {!isLoading && projects.length > 0 && (
            <button
              onClick={() => selectionMode ? exitSelectionMode() : setSelectionMode(true)}
              className={`p-1.5 rounded-lg transition-colors ${
                selectionMode
                  ? 'bg-blue-100 text-blue-600 hover:bg-blue-200'
                  : 'text-gray-400 hover:text-gray-600 hover:bg-gray-100'
              }`}
              title={selectionMode ? 'Exit selection mode' : 'Select projects'}
            >
              {selectionMode ? <X className="w-4 h-4" /> : <CheckSquare className="w-4 h-4" />}
            </button>
          )}
          {!isLoading && <span className="text-sm text-gray-500">{projects.length} projects</span>}
        </div>
      </PageHeader>

      {/* Selection bar */}
      {selectionMode && projects.length > 0 && (
        <div className="flex items-center justify-between px-4 py-2 bg-blue-50 rounded-lg border border-blue-200">
          <div className="flex items-center gap-3">
            <button
              onClick={toggleSelectAll}
              className="text-sm text-blue-600 hover:text-blue-800 font-medium"
            >
              {selectedIds.size === projects.length ? 'Deselect all' : 'Select all'}
            </button>
            <span className="text-sm text-gray-500">{selectedIds.size} selected</span>
          </div>
          {selectedIds.size > 0 && (
            <button
              onClick={handleBatchDelete}
              disabled={batchDeleteMutation.isPending}
              className="flex items-center gap-1.5 px-3 py-1.5 text-sm text-white bg-red-600 hover:bg-red-700 rounded-lg transition-colors disabled:opacity-50 font-medium"
            >
              {batchDeleteMutation.isPending ? (
                <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
              ) : (
                <Trash2 className="w-4 h-4" />
              )}
              {batchDeleteMutation.isPending
                ? 'Deleting...'
                : `Delete ${selectedIds.size}`}
            </button>
          )}
        </div>
      )}

      {/* Loading */}
      {isLoading && (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {Array.from({ length: 6 }).map((_, i) => <SkeletonProjectCard key={i} />)}
        </div>
      )}

      {/* Error */}
      {isError && (
        <div className="flex flex-col items-center justify-center h-64 text-red-500">
          <AlertCircle className="w-12 h-12 mb-2" />
          <p className="text-lg font-medium">Failed to load projects</p>
          <p className="text-sm text-red-400">{error?.message || 'An unexpected error occurred'}</p>
          <button
            onClick={() => refetch()}
            className="mt-4 px-4 py-2 bg-blue-500 text-white rounded-lg hover:bg-blue-600 transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2"
          >
            Retry
          </button>
        </div>
      )}

      {/* Project Grid */}
      {!isLoading && !isError && (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {projects.map((project) => (
            <ProjectCard
              key={project.id}
              project={project}
              deployment={deploymentsByProject[project.id]}
              onDelete={(id) => deleteMutation.mutate(id)}
              isDeleting={deletingId === project.id}
              onViewDetails={(id) => navigate(`/projects/${id}`)}
              onStop={(containerName) => stopMutation.mutate(containerName)}
              isStopping={stoppingName === deploymentsByProject[project.id]?.container_name}
              selectionMode={selectionMode}
              isSelected={selectedIds.has(project.id)}
              onToggleSelect={toggleSelection}
            />
          ))}

          {projects.length === 0 && (
            <div className="col-span-full">
              <EmptyState
                icon={Folder}
                title="No projects yet"
                description="Start a conversation in Chat to create your first project."
                actionLabel="Go to Chat"
                actionTo="/chat"
              />
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export default Projects
