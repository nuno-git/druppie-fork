/**
 * Shared CopyButton component - replaces duplicated implementations
 *
 * Supports icon-only (default) or labeled button via showLabel prop.
 * Pass className to override styling for different contexts.
 */

import { useState } from 'react'
import { Copy, CheckCircle } from 'lucide-react'

const fallbackCopy = (text) => {
  try {
    const textarea = document.createElement('textarea')
    textarea.value = text
    textarea.style.position = 'fixed'
    textarea.style.left = '-9999px'
    document.body.appendChild(textarea)
    textarea.select()
    document.execCommand('copy')
    document.body.removeChild(textarea)
    return true
  } catch {
    return false
  }
}

const CopyButton = ({ text, label = 'Copy', showLabel = false, className }) => {
  const [copied, setCopied] = useState(false)

  const handleCopy = async (e) => {
    e?.stopPropagation()
    if (text === undefined || text === null) return
    const textToCopy = typeof text === 'string' ? text : JSON.stringify(text, null, 2)
    let success = false
    if (navigator.clipboard?.writeText) {
      try { await navigator.clipboard.writeText(textToCopy); success = true } catch {}
    }
    if (!success) success = fallbackCopy(textToCopy)
    if (success) {
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    }
  }

  const defaultClassName = showLabel
    ? `inline-flex items-center gap-1 px-2 py-0.5 text-xs rounded hover:bg-gray-200 transition-colors ${
        copied ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-600'
      }`
    : 'p-1.5 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500'

  return (
    <button
      onClick={handleCopy}
      className={className || defaultClassName}
      aria-label={copied ? `${label} copied` : `Copy ${label}`}
      title={copied ? 'Copied!' : `Copy ${label}`}
    >
      {copied ? (
        showLabel ? <CheckCircle className="w-3 h-3" /> : <CheckCircle className="w-4 h-4 text-green-500" />
      ) : (
        <Copy className={showLabel ? 'w-3 h-3' : 'w-4 h-4'} />
      )}
      {showLabel && <span>{copied ? 'Copied!' : label}</span>}
    </button>
  )
}

export default CopyButton
