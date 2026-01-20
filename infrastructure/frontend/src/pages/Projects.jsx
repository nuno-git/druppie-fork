/**
 * Projects Page - View and manage created projects with repo URLs and status
 */

import React, { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Folder,
  File,
  FileText,
  FileCode,
  ChevronRight,
  Download,
  Eye,
  X,
  ExternalLink,
  GitBranch,
  Play,
  Square,
  CheckCircle,
  Clock,
  AlertCircle,
  Copy,
  Server,
  Trash2,
} from 'lucide-react'
import { getWorkspaceFiles, getWorkspaceFile, getWorkspaceDownloadUrl, getPlans, getProjectStatus, getProjects, deleteProject } from '../services/api'

const getFileIcon = (filename) => {
  const ext = filename.split('.').pop().toLowerCase()
  const codeExts = ['py', 'js', 'ts', 'jsx', 'tsx', 'go', 'rs', 'java', 'cpp', 'c', 'h']
  const textExts = ['md', 'txt', 'yaml', 'yml', 'json', 'xml', 'html', 'css']

  if (codeExts.includes(ext)) return FileCode
  if (textExts.includes(ext)) return FileText
  return File
}

const StatusBadge = ({ status, hasRepo, isRunning }) => {
  if (isRunning) {
    return (
      <span className="inline-flex items-center px-2 py-1 rounded-full text-xs font-medium bg-green-100 text-green-700">
        <span className="w-2 h-2 bg-green-500 rounded-full mr-1.5 animate-pulse" />
        Running
      </span>
    )
  }

  if (status === 'completed' && hasRepo) {
    return (
      <span className="inline-flex items-center px-2 py-1 rounded-full text-xs font-medium bg-blue-100 text-blue-700">
        <CheckCircle className="w-3 h-3 mr-1" />
        Ready
      </span>
    )
  }

  if (status === 'completed') {
    return (
      <span className="inline-flex items-center px-2 py-1 rounded-full text-xs font-medium bg-gray-100 text-gray-700">
        <CheckCircle className="w-3 h-3 mr-1" />
        Completed
      </span>
    )
  }

  if (status === 'executing') {
    return (
      <span className="inline-flex items-center px-2 py-1 rounded-full text-xs font-medium bg-yellow-100 text-yellow-700">
        <Clock className="w-3 h-3 mr-1 animate-spin" />
        Building
      </span>
    )
  }

  return (
    <span className="inline-flex items-center px-2 py-1 rounded-full text-xs font-medium bg-gray-100 text-gray-600">
      <Clock className="w-3 h-3 mr-1" />
      {status || 'Pending'}
    </span>
  )
}

const CopyButton = ({ text, label }) => {
  const [copied, setCopied] = useState(false)

  const handleCopy = async () => {
    await navigator.clipboard.writeText(text)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <button
      onClick={handleCopy}
      className="p-1.5 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded transition-colors"
      title={`Copy ${label}`}
    >
      {copied ? (
        <CheckCircle className="w-4 h-4 text-green-500" />
      ) : (
        <Copy className="w-4 h-4" />
      )}
    </button>
  )
}

const FilePreview = ({ path, planId, onClose }) => {
  const { data, isLoading, error } = useQuery({
    queryKey: ['file', path, planId],
    queryFn: () => getWorkspaceFile(path, planId),
    enabled: !!path,
  })

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-xl max-w-4xl w-full max-h-[80vh] flex flex-col">
        <div className="flex items-center justify-between p-4 border-b">
          <h3 className="font-semibold">{path.split('/').pop()}</h3>
          <button onClick={onClose} className="p-1 hover:bg-gray-100 rounded">
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="flex-1 overflow-auto p-4">
          {isLoading ? (
            <div className="flex items-center justify-center py-8">
              <div className="w-8 h-8 border-4 border-blue-600 border-t-transparent rounded-full animate-spin" />
            </div>
          ) : error ? (
            <div className="text-red-500 text-center py-8">
              Error loading file: {error.message}
            </div>
          ) : data?.binary ? (
            <div className="text-center py-8 text-gray-500">Binary file - cannot preview</div>
          ) : (
            <pre className="bg-gray-900 text-gray-100 p-4 rounded-lg overflow-x-auto text-sm font-mono">
              {data?.content}
            </pre>
          )}
        </div>
      </div>
    </div>
  )
}

const ProjectCard = ({ plan, isSelected, onSelect, projectStatus, onDelete, isDeleting }) => {
  const repoUrl = plan.result?.repo_url
  const appUrl = plan.result?.app_url || projectStatus?.url
  const hasRepo = !!repoUrl
  const isRunning = projectStatus?.status === 'running'

  const handleDelete = (e) => {
    e.stopPropagation()
    if (window.confirm(`Are you sure you want to delete "${plan.name}"?\n\nThis will permanently delete:\n- All project files\n- The Git repository\n- Any running containers`)) {
      onDelete(plan.id)
    }
  }

  return (
    <div
      className={`p-4 rounded-xl border-2 transition-all cursor-pointer relative group ${
        isSelected
          ? 'border-blue-500 bg-blue-50 shadow-md'
          : 'border-gray-200 bg-white hover:border-gray-300 hover:shadow-sm'
      } ${isDeleting ? 'opacity-50 pointer-events-none' : ''}`}
      onClick={onSelect}
    >
      {/* Delete Button */}
      <button
        onClick={handleDelete}
        disabled={isDeleting}
        className="absolute top-2 right-2 p-1.5 text-gray-400 hover:text-red-600 hover:bg-red-50 rounded-lg opacity-0 group-hover:opacity-100 transition-all"
        title="Delete project"
      >
        {isDeleting ? (
          <div className="w-4 h-4 border-2 border-red-600 border-t-transparent rounded-full animate-spin" />
        ) : (
          <Trash2 className="w-4 h-4" />
        )}
      </button>

      {/* Header */}
      <div className="flex items-start justify-between mb-3 pr-8">
        <div className="flex items-center">
          <Folder className={`w-5 h-5 mr-2 ${isSelected ? 'text-blue-500' : 'text-yellow-500'}`} />
          <h3 className="font-semibold text-gray-900 truncate">{plan.name}</h3>
        </div>
        <StatusBadge status={plan.status} hasRepo={hasRepo} isRunning={isRunning} />
      </div>

      {/* Description */}
      {plan.description && (
        <p className="text-sm text-gray-600 mb-3 line-clamp-2">{plan.description}</p>
      )}

      {/* Repo URL - Prominent Display */}
      {repoUrl && (
        <div className="mb-3 p-2 bg-gray-50 rounded-lg border border-gray-200">
          <div className="flex items-center justify-between">
            <div className="flex items-center min-w-0 flex-1">
              <GitBranch className="w-4 h-4 text-gray-500 mr-2 flex-shrink-0" />
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
                className="p-1.5 text-gray-400 hover:text-blue-600 hover:bg-blue-50 rounded transition-colors"
              >
                <ExternalLink className="w-4 h-4" />
              </a>
            </div>
          </div>
        </div>
      )}

      {/* App URL if running */}
      {appUrl && (
        <div className="mb-3 p-2 bg-green-50 rounded-lg border border-green-200">
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
                className="flex items-center px-2 py-1 bg-green-500 text-white text-xs rounded hover:bg-green-600 transition-colors"
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
        <span>{new Date(plan.created_at).toLocaleDateString()}</span>
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
    </div>
  )
}

const Projects = () => {
  const [selectedPlan, setSelectedPlan] = useState(null)
  const [currentPath, setCurrentPath] = useState('')
  const [previewFile, setPreviewFile] = useState(null)
  const [previewPlanId, setPreviewPlanId] = useState(null)
  const [viewMode, setViewMode] = useState('grid') // 'grid' or 'list'
  const [deletingId, setDeletingId] = useState(null)

  const queryClient = useQueryClient()

  const { data: plans = [] } = useQuery({
    queryKey: ['plans'],
    queryFn: getPlans,
  })

  const deleteMutation = useMutation({
    mutationFn: deleteProject,
    onMutate: (projectId) => {
      setDeletingId(projectId)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['plans'] })
      queryClient.invalidateQueries({ queryKey: ['allProjectStatuses'] })
      setDeletingId(null)
      // If we deleted the selected project, deselect it
      if (selectedPlan === deletingId) {
        setSelectedPlan(null)
      }
    },
    onError: (error) => {
      setDeletingId(null)
      alert(`Failed to delete project: ${error.message}`)
    },
  })

  const handleDelete = (projectId) => {
    deleteMutation.mutate(projectId)
  }

  const { data: workspace, isLoading } = useQuery({
    queryKey: ['workspace', selectedPlan, currentPath],
    queryFn: () => getWorkspaceFiles(selectedPlan),
    enabled: true,
  })

  const { data: projectStatus } = useQuery({
    queryKey: ['projectStatus', selectedPlan],
    queryFn: () => getProjectStatus(selectedPlan),
    enabled: !!selectedPlan,
    refetchInterval: 10000,
  })

  // Get all project statuses for the grid view
  const projectStatuses = useQuery({
    queryKey: ['allProjectStatuses'],
    queryFn: async () => {
      const statuses = {}
      for (const plan of plans.filter(p => p.status === 'completed')) {
        try {
          const status = await getProjectStatus(plan.id)
          statuses[plan.id] = status
        } catch (e) {
          statuses[plan.id] = null
        }
      }
      return statuses
    },
    enabled: plans.length > 0,
    refetchInterval: 15000,
  })

  const completedPlans = plans.filter((p) => p.status === 'completed')
  const selectedPlanData = plans.find((p) => p.id === selectedPlan)
  const repoUrl = selectedPlanData?.result?.repo_url
  const appUrl = selectedPlanData?.result?.app_url || projectStatus?.url

  const navigateToPath = (path) => {
    setCurrentPath(path)
  }

  const breadcrumbs = currentPath ? currentPath.split('/').filter(Boolean) : []

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Projects</h1>
          <p className="text-gray-500 mt-1">View your created projects and their repositories.</p>
        </div>
        <div className="flex items-center space-x-2">
          <span className="text-sm text-gray-500">{completedPlans.length} projects</span>
        </div>
      </div>

      {/* Projects Grid */}
      {!selectedPlan && (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {completedPlans.map((plan) => (
            <ProjectCard
              key={plan.id}
              plan={plan}
              isSelected={false}
              onSelect={() => {
                setSelectedPlan(plan.id)
                setCurrentPath('')
              }}
              projectStatus={projectStatuses.data?.[plan.id]}
              onDelete={handleDelete}
              isDeleting={deletingId === plan.id}
            />
          ))}

          {completedPlans.length === 0 && (
            <div className="col-span-full text-center py-16">
              <Folder className="w-16 h-16 mx-auto mb-4 text-gray-300" />
              <h3 className="text-lg font-medium text-gray-900 mb-2">No projects yet</h3>
              <p className="text-gray-500">Create a project in Chat to see it here.</p>
            </div>
          )}
        </div>
      )}

      {/* Selected Project View */}
      {selectedPlan && (
        <div className="space-y-4">
          {/* Back Button & Project Header */}
          <div className="flex items-center justify-between">
            <button
              onClick={() => {
                setSelectedPlan(null)
                setCurrentPath('')
              }}
              className="flex items-center px-3 py-2 text-gray-600 hover:text-gray-900 hover:bg-gray-100 rounded-lg transition-colors"
            >
              <ChevronRight className="w-4 h-4 rotate-180 mr-1" />
              Back to Projects
            </button>
            <button
              onClick={() => {
                if (window.confirm(`Are you sure you want to delete "${selectedPlanData?.name}"?\n\nThis will permanently delete:\n- All project files\n- The Git repository\n- Any running containers`)) {
                  handleDelete(selectedPlan)
                  setSelectedPlan(null)
                }
              }}
              disabled={deletingId === selectedPlan}
              className="flex items-center px-3 py-2 text-red-600 hover:text-red-700 hover:bg-red-50 rounded-lg transition-colors"
            >
              {deletingId === selectedPlan ? (
                <div className="w-4 h-4 border-2 border-red-600 border-t-transparent rounded-full animate-spin mr-2" />
              ) : (
                <Trash2 className="w-4 h-4 mr-2" />
              )}
              Delete Project
            </button>
          </div>

          {/* Project Details Card */}
          <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
            <div className="flex items-start justify-between mb-4">
              <div>
                <h2 className="text-xl font-bold text-gray-900">{selectedPlanData?.name}</h2>
                <p className="text-gray-500 mt-1">{selectedPlanData?.description}</p>
              </div>
              <StatusBadge
                status={selectedPlanData?.status}
                hasRepo={!!repoUrl}
                isRunning={projectStatus?.status === 'running'}
              />
            </div>

            {/* Repository URL - Prominent */}
            {repoUrl && (
              <div className="mb-4 p-4 bg-gradient-to-r from-blue-50 to-indigo-50 rounded-xl border border-blue-200">
                <div className="flex items-center mb-2">
                  <GitBranch className="w-5 h-5 text-blue-600 mr-2" />
                  <span className="font-semibold text-blue-900">Git Repository</span>
                </div>
                <div className="flex items-center justify-between bg-white rounded-lg p-3 border border-blue-200">
                  <code className="text-sm text-gray-800 font-mono truncate flex-1">{repoUrl}</code>
                  <div className="flex items-center space-x-2 ml-3">
                    <CopyButton text={repoUrl} label="URL" />
                    <a
                      href={repoUrl}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="flex items-center px-3 py-1.5 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700 transition-colors"
                    >
                      <ExternalLink className="w-4 h-4 mr-1" />
                      Open
                    </a>
                  </div>
                </div>
                <p className="mt-2 text-xs text-blue-700">
                  Clone: <code className="bg-blue-100 px-1 py-0.5 rounded">git clone {repoUrl}</code>
                </p>
              </div>
            )}

            {/* App URL if running */}
            {appUrl && (
              <div className="mb-4 p-4 bg-gradient-to-r from-green-50 to-emerald-50 rounded-xl border border-green-200">
                <div className="flex items-center mb-2">
                  <Server className="w-5 h-5 text-green-600 mr-2" />
                  <span className="font-semibold text-green-900">Running Application</span>
                  <span className="ml-2 w-2 h-2 bg-green-500 rounded-full animate-pulse" />
                </div>
                <div className="flex items-center justify-between bg-white rounded-lg p-3 border border-green-200">
                  <code className="text-sm text-gray-800 font-mono truncate flex-1">{appUrl}</code>
                  <a
                    href={appUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex items-center px-3 py-1.5 bg-green-600 text-white text-sm rounded-lg hover:bg-green-700 transition-colors ml-3"
                  >
                    <Play className="w-4 h-4 mr-1" />
                    Open App
                  </a>
                </div>
              </div>
            )}

            {/* Project Status */}
            {projectStatus && (
              <div className="flex items-center space-x-4 text-sm text-gray-600">
                <span className="flex items-center">
                  <span className={`w-2 h-2 rounded-full mr-2 ${
                    projectStatus.status === 'running' ? 'bg-green-500' :
                    projectStatus.status === 'built' ? 'bg-blue-500' :
                    'bg-gray-400'
                  }`} />
                  Status: {projectStatus.status}
                </span>
                {projectStatus.port && (
                  <span>Port: {projectStatus.port}</span>
                )}
              </div>
            )}
          </div>

          {/* File Browser */}
          <div className="bg-white rounded-xl shadow-sm border border-gray-200">
            {/* Breadcrumb */}
            <div className="p-4 border-b flex items-center text-sm">
              <button
                onClick={() => navigateToPath('')}
                className="text-blue-600 hover:underline"
              >
                {selectedPlanData?.name || 'project'}
              </button>
              {breadcrumbs.map((crumb, index) => (
                <React.Fragment key={index}>
                  <ChevronRight className="w-4 h-4 mx-1 text-gray-400" />
                  <button
                    onClick={() =>
                      navigateToPath(breadcrumbs.slice(0, index + 1).join('/'))
                    }
                    className="text-blue-600 hover:underline"
                  >
                    {crumb}
                  </button>
                </React.Fragment>
              ))}
            </div>

            {/* Files */}
            <div className="p-4">
              {isLoading ? (
                <div className="flex items-center justify-center py-12">
                  <div className="w-8 h-8 border-4 border-blue-600 border-t-transparent rounded-full animate-spin" />
                </div>
              ) : !workspace?.files?.length && !workspace?.directories?.length ? (
                <div className="text-center py-12 text-gray-500">
                  <Folder className="w-16 h-16 mx-auto mb-4 opacity-30" />
                  <p>No files yet</p>
                  <p className="text-sm">Files will appear here once the project is built</p>
                </div>
              ) : (
                <div className="space-y-1">
                  {/* Directories */}
                  {workspace?.directories?.map((dir) => (
                    <button
                      key={dir.name}
                      onClick={() => navigateToPath(`${currentPath}/${dir.name}`.replace(/^\//, ''))}
                      className="w-full flex items-center p-3 hover:bg-gray-50 rounded-lg transition-colors"
                    >
                      <Folder className="w-5 h-5 text-yellow-500 mr-3" />
                      <span className="font-medium">{dir.name}</span>
                    </button>
                  ))}

                  {/* Files */}
                  {workspace?.files?.map((file) => {
                    const FileIcon = getFileIcon(file.name)
                    const filePath = `${currentPath}/${file.name}`.replace(/^\//, '')

                    return (
                      <div
                        key={file.name}
                        className="flex items-center justify-between p-3 hover:bg-gray-50 rounded-lg group"
                      >
                        <div className="flex items-center">
                          <FileIcon className="w-5 h-5 text-gray-400 mr-3" />
                          <span>{file.name}</span>
                          <span className="text-xs text-gray-400 ml-2">
                            {(file.size / 1024).toFixed(1)} KB
                          </span>
                        </div>

                        <div className="flex items-center space-x-2 opacity-0 group-hover:opacity-100 transition-opacity">
                          <button
                            onClick={() => {
                              setPreviewFile(filePath)
                              setPreviewPlanId(selectedPlan)
                            }}
                            className="p-1.5 text-gray-500 hover:text-blue-600 hover:bg-blue-50 rounded"
                            title="Preview"
                          >
                            <Eye className="w-4 h-4" />
                          </button>
                          <a
                            href={getWorkspaceDownloadUrl(filePath, selectedPlan)}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="p-1.5 text-gray-500 hover:text-green-600 hover:bg-green-50 rounded"
                            title="Download"
                          >
                            <Download className="w-4 h-4" />
                          </a>
                        </div>
                      </div>
                    )
                  })}
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* File Preview Modal */}
      {previewFile && (
        <FilePreview
          path={previewFile}
          planId={previewPlanId}
          onClose={() => {
            setPreviewFile(null)
            setPreviewPlanId(null)
          }}
        />
      )}
    </div>
  )
}

export default Projects
