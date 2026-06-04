import { useState } from 'react'
import { FileCode, ExternalLink } from 'lucide-react'
import { FilePreviewModal } from './ApprovalCard'

const SurfacedFileCard = ({ files }) => {
  const [showPreview, setShowPreview] = useState(false)
  if (!files || files.length === 0) return null

  const label = files.length === 1
    ? files[0].path.split('/').pop()
    : `${files.length} bestanden`

  return (
    <div className="mt-2 pl-8">
      <button
        onClick={() => setShowPreview(true)}
        className="flex items-center gap-2 px-3 py-2 text-sm rounded-lg border border-gray-200 bg-white hover:bg-gray-50 hover:border-gray-300 transition-colors text-gray-700"
      >
        <FileCode className="w-4 h-4 text-blue-500 flex-shrink-0" />
        <span className="truncate">{label}</span>
        <ExternalLink className="w-3 h-3 text-gray-400 flex-shrink-0" />
      </button>
      {showPreview && (
        <FilePreviewModal files={files} onClose={() => setShowPreview(false)} />
      )}
    </div>
  )
}

export default SurfacedFileCard
