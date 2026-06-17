/**
 * File upload button for chat input bars.
 * Renders a paperclip icon that opens a file picker.
 * Uploads go through the module-level uploadManager so they survive component unmounts.
 */

import { useRef, useState, useEffect } from 'react'
import { Paperclip, Loader2 } from 'lucide-react'
import { startUpload, drainCompleted, drainErrors, isUploading, getStatusText, subscribe } from '../../services/uploadManager'

const ACCEPT = '.txt,.md,.csv,.py,.js,.ts,.jsx,.tsx,.html,.css,.xml,.json,.yaml,.yml,.pdf'
const MAX_SIZE = 50 * 1024 * 1024 // 50 MB

const FileUploadButton = ({ onUpload, onError, sessionId = null, scope = 'chat', disabled = false }) => {
  const fileRef = useRef(null)
  const [uploading, setUploading] = useState(() => isUploading(sessionId, scope))
  const [statusText, setStatusText] = useState(() => getStatusText(sessionId, scope))

  const onUploadRef = useRef(onUpload)
  const onErrorRef = useRef(onError)
  onUploadRef.current = onUpload
  onErrorRef.current = onError

  useEffect(() => {
    const drain = () => {
      for (const result of drainCompleted(sessionId, scope)) {
        onUploadRef.current?.(result)
      }
      for (const err of drainErrors(sessionId, scope)) {
        onErrorRef.current?.(err)
      }
      setUploading(isUploading(sessionId, scope))
      setStatusText(getStatusText(sessionId, scope))
    }
    drain()
    return subscribe(drain)
  }, [sessionId, scope])

  const handleFiles = (files) => {
    if (!files.length) return
    for (const file of files) {
      if (file.size > MAX_SIZE) {
        onError?.(`${file.name} is too large (max 50 MB)`)
        continue
      }
      startUpload(file, sessionId, scope)
    }
    if (fileRef.current) fileRef.current.value = ''
  }

  return (
    <>
      <input
        ref={fileRef}
        type="file"
        multiple
        accept={ACCEPT}
        className="hidden"
        onChange={(e) => handleFiles(Array.from(e.target.files))}
      />
      {uploading ? (
        <span className="flex items-center gap-1.5 px-2 py-1 text-xs text-gray-500">
          <Loader2 className="w-3.5 h-3.5 animate-spin text-gray-400" />
          {statusText}
        </span>
      ) : (
        <button
          type="button"
          onClick={() => fileRef.current?.click()}
          disabled={disabled}
          className="flex-shrink-0 p-2 rounded-xl text-gray-400 hover:text-gray-600 hover:bg-gray-100 disabled:opacity-30 transition-colors"
          aria-label="Attach file"
        >
          <Paperclip className="w-4 h-4" />
        </button>
      )}
    </>
  )
}

export default FileUploadButton
