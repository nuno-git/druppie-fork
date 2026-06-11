/**
 * Attachment chips - shows a row of attached files with remove buttons.
 * Used in chat input bars before sending.
 */

import { FileText, FileType, X } from 'lucide-react'

const formatSize = (bytes) => {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

const getIcon = (contentType) => {
  if (contentType === 'application/pdf') return FileType
  return FileText
}

const AttachmentChips = ({ attachments = [], onRemove }) => {
  if (!attachments.length) return null

  return (
    <div className="flex flex-wrap gap-1.5 px-1 pb-2">
      {attachments.map((att) => {
        const Icon = getIcon(att.content_type)
        return (
          <div
            key={att.id}
            className="inline-flex items-center gap-1.5 pl-2.5 pr-1 py-1 bg-gray-100 rounded-lg text-xs text-gray-600 max-w-[200px]"
          >
            <Icon className="w-3.5 h-3.5 flex-shrink-0 text-gray-400" />
            <span className="truncate">{att.original_filename}</span>
            <span className="text-gray-400 flex-shrink-0">{formatSize(att.file_size)}</span>
            {onRemove && (
              <button
                type="button"
                onClick={() => onRemove(att.id)}
                className="flex-shrink-0 p-0.5 rounded hover:bg-gray-200 transition-colors"
                aria-label={`Remove ${att.original_filename}`}
              >
                <X className="w-3 h-3" />
              </button>
            )}
          </div>
        )
      })}
    </div>
  )
}

export default AttachmentChips
