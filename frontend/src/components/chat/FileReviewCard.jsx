/**
 * FileReviewCard - Informational card displaying files written by an agent.
 *
 * Pure display component (no mutations/approval logic).
 * Props: { files: Array<{ path: string, content: string }> }
 */

import { useState } from 'react'
import {
  FileText,
  ChevronDown,
  ChevronRight,
  Eye,
} from 'lucide-react'
import { FilePreviewModal } from './ApprovalCard'

const FileReviewCard = ({ files }) => {
  const [isExpanded, setIsExpanded] = useState(false)
  const [previewFiles, setPreviewFiles] = useState(null)

  if (!files?.length) return null

  const totalLines = files.reduce(
    (sum, f) => sum + (f.content?.split('\n').length || 0),
    0
  )

  return (
    <div className="rounded-xl border bg-gray-50 border-gray-200 border-l-4 border-l-indigo-400 transition-all">
      {/* Header */}
      <div className="px-4 pt-3 pb-2">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <FileText className="w-4 h-4 text-indigo-500" />
            <span className="text-sm font-medium text-gray-800">
              {files.length === 1 ? 'File Generated' : `${files.length} Files Generated`}
            </span>
          </div>
          <button
            onClick={() => setIsExpanded(!isExpanded)}
            className="flex items-center gap-1 text-xs text-gray-400 hover:text-gray-600 transition-colors"
          >
            {isExpanded ? (
              <ChevronDown className="w-3.5 h-3.5" />
            ) : (
              <ChevronRight className="w-3.5 h-3.5" />
            )}
            {isExpanded ? 'Collapse' : 'Details'}
          </button>
        </div>

        {/* Summary line */}
        <div className="mt-1.5 flex items-center gap-1 text-xs text-gray-500 flex-wrap">
          {files.map((f, i) => (
            <span key={i} className="flex items-center gap-1">
              {i > 0 && <span className="text-gray-300">&middot;</span>}
              <span className="font-mono">{f.path.split('/').pop()}</span>
            </span>
          ))}
          <span className="text-gray-300 mx-0.5">|</span>
          <span>{totalLines} lines</span>
        </div>
      </div>

      {/* Expanded: file list with preview buttons */}
      {isExpanded && (
        <div className="px-4 pb-3 border-t border-gray-200">
          <div className="divide-y divide-gray-100">
            {files.map((file, i) => (
              <div key={i} className="py-2 flex items-center justify-between">
                <div className="flex items-center gap-2 min-w-0">
                  <FileText className="w-3.5 h-3.5 text-gray-400 flex-shrink-0" />
                  <span className="text-xs font-mono text-gray-700 truncate">
                    {file.path}
                  </span>
                  <span className="text-xs text-gray-400">
                    {file.content?.split('\n').length || 0} lines
                  </span>
                </div>
                <button
                  onClick={() => setPreviewFiles([file])}
                  className="flex items-center gap-1 text-xs text-indigo-600 hover:text-indigo-800 transition-colors flex-shrink-0"
                >
                  <Eye className="w-3 h-3" />
                  View
                </button>
              </div>
            ))}
          </div>

          {/* View all button when multiple files */}
          {files.length > 1 && (
            <button
              onClick={() => setPreviewFiles(files)}
              className="mt-2 flex items-center gap-1.5 text-xs text-indigo-600 hover:text-indigo-800 transition-colors font-medium"
            >
              <Eye className="w-3.5 h-3.5" />
              View all {files.length} files
            </button>
          )}
        </div>
      )}

      {/* File preview modal */}
      {previewFiles && (
        <FilePreviewModal
          files={previewFiles}
          onClose={() => setPreviewFiles(null)}
        />
      )}
    </div>
  )
}

export default FileReviewCard
