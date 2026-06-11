import { useState, useRef, useEffect } from 'react'
import { Download, FileText, FileType, ChevronDown, Loader2 } from 'lucide-react'

const DownloadMenu = ({ onDownloadMd, onDownloadPdf, loading = false, variant = 'light' }) => {
  const [open, setOpen] = useState(false)
  const ref = useRef(null)

  useEffect(() => {
    if (!open) return
    const close = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false) }
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [open])

  const dark = variant === 'dark'

  return (
    <div className="relative inline-block" ref={ref}>
      <button
        onClick={(e) => { e.stopPropagation(); setOpen(!open) }}
        disabled={loading}
        className={`flex items-center gap-1.5 px-2.5 py-1 text-xs rounded-md transition-colors border ${
          dark
            ? 'text-gray-400 hover:text-gray-200 hover:bg-gray-700 border-gray-600'
            : 'text-blue-600 hover:text-blue-800 hover:bg-blue-50 border-blue-200'
        } ${loading ? 'opacity-50 cursor-not-allowed' : ''}`}
      >
        {loading
          ? <Loader2 className="w-3.5 h-3.5 animate-spin" />
          : <Download className="w-3.5 h-3.5" />}
        {loading ? 'Generating…' : 'Download'}
        <ChevronDown className="w-3 h-3" />
      </button>

      {open && (
        <div className={`absolute top-full mt-1 w-48 rounded-lg shadow-lg z-50 py-1 ${
          dark
            ? 'bg-gray-800 border border-gray-600 right-0'
            : 'bg-white border border-gray-200 left-0'
        }`}>
          <button
            onClick={(e) => { e.stopPropagation(); onDownloadMd(); setOpen(false) }}
            className={`w-full flex items-center gap-2 px-3 py-2 text-sm transition-colors ${
              dark ? 'text-gray-200 hover:bg-gray-700' : 'text-gray-700 hover:bg-gray-50'
            }`}
          >
            <FileText className="w-4 h-4 text-gray-400" />
            Markdown (.md)
          </button>
          <button
            onClick={(e) => { e.stopPropagation(); onDownloadPdf(); setOpen(false) }}
            className={`w-full flex items-center gap-2 px-3 py-2 text-sm transition-colors ${
              dark ? 'text-gray-200 hover:bg-gray-700' : 'text-gray-700 hover:bg-gray-50'
            }`}
          >
            <FileType className="w-4 h-4 text-red-400" />
            PDF (.pdf)
          </button>
        </div>
      )}
    </div>
  )
}

export default DownloadMenu
