/**
 * Workspace Page - File browser for created projects
 */

import React, { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  Folder,
  File,
  FileText,
  FileCode,
  ChevronRight,
  Download,
  Eye,
  X,
} from 'lucide-react'
import { getWorkspaceFiles, getWorkspaceFile, getPlans } from '../services/api'

const getFileIcon = (filename) => {
  const ext = filename.split('.').pop().toLowerCase()
  const codeExts = ['py', 'js', 'ts', 'jsx', 'tsx', 'go', 'rs', 'java', 'cpp', 'c', 'h']
  const textExts = ['md', 'txt', 'yaml', 'yml', 'json', 'xml', 'html', 'css']

  if (codeExts.includes(ext)) return FileCode
  if (textExts.includes(ext)) return FileText
  return File
}

const FilePreview = ({ path, onClose }) => {
  const { data, isLoading, error } = useQuery({
    queryKey: ['file', path],
    queryFn: () => getWorkspaceFile(path),
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

const Workspace = () => {
  const [selectedPlan, setSelectedPlan] = useState(null)
  const [currentPath, setCurrentPath] = useState('')
  const [previewFile, setPreviewFile] = useState(null)

  const { data: plans = [] } = useQuery({
    queryKey: ['plans'],
    queryFn: getPlans,
  })

  const { data: workspace, isLoading } = useQuery({
    queryKey: ['workspace', selectedPlan, currentPath],
    queryFn: () => getWorkspaceFiles(selectedPlan),
    enabled: true,
  })

  const completedPlans = plans.filter((p) => p.status === 'completed')

  const navigateToPath = (path) => {
    setCurrentPath(path)
  }

  const breadcrumbs = currentPath ? currentPath.split('/').filter(Boolean) : []

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Workspace</h1>
        <p className="text-gray-500 mt-1">Browse files created by your plans.</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
        {/* Plan Selector */}
        <div className="lg:col-span-1">
          <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-4">
            <h2 className="font-semibold mb-4">Projects</h2>

            <div className="space-y-2">
              <button
                onClick={() => {
                  setSelectedPlan(null)
                  setCurrentPath('')
                }}
                className={`w-full text-left p-3 rounded-lg transition-colors ${
                  !selectedPlan
                    ? 'bg-blue-50 border border-blue-200'
                    : 'hover:bg-gray-50 border border-transparent'
                }`}
              >
                <div className="flex items-center">
                  <Folder className="w-4 h-4 mr-2 text-blue-500" />
                  <span className="font-medium">All Files</span>
                </div>
              </button>

              {completedPlans.map((plan) => (
                <button
                  key={plan.id}
                  onClick={() => {
                    setSelectedPlan(plan.id)
                    setCurrentPath('')
                  }}
                  className={`w-full text-left p-3 rounded-lg transition-colors ${
                    selectedPlan === plan.id
                      ? 'bg-blue-50 border border-blue-200'
                      : 'hover:bg-gray-50 border border-transparent'
                  }`}
                >
                  <div className="flex items-center">
                    <Folder className="w-4 h-4 mr-2 text-yellow-500" />
                    <span className="text-sm truncate">{plan.name}</span>
                  </div>
                  <p className="text-xs text-gray-500 mt-1">
                    {new Date(plan.created_at).toLocaleDateString()}
                  </p>
                </button>
              ))}

              {completedPlans.length === 0 && (
                <p className="text-sm text-gray-500 text-center py-4">
                  No completed plans yet
                </p>
              )}
            </div>
          </div>
        </div>

        {/* File Browser */}
        <div className="lg:col-span-3">
          <div className="bg-white rounded-xl shadow-sm border border-gray-200">
            {/* Breadcrumb */}
            <div className="p-4 border-b flex items-center text-sm">
              <button
                onClick={() => navigateToPath('')}
                className="text-blue-600 hover:underline"
              >
                workspace
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
                  <p className="text-sm">Create a project in Chat to see files here</p>
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
                            onClick={() => setPreviewFile(filePath)}
                            className="p-1.5 text-gray-500 hover:text-blue-600 hover:bg-blue-50 rounded"
                            title="Preview"
                          >
                            <Eye className="w-4 h-4" />
                          </button>
                          <a
                            href={`/api/workspace/download?path=${encodeURIComponent(filePath)}`}
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
      </div>

      {/* File Preview Modal */}
      {previewFile && (
        <FilePreview path={previewFile} onClose={() => setPreviewFile(null)} />
      )}
    </div>
  )
}

export default Workspace
