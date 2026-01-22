/**
 * DeploymentCard - Shows deployment result with prominent URL link
 */

import React from 'react'
import { ExternalLink, Server, Terminal, CheckCircle } from 'lucide-react'

const DeploymentCard = ({ url, containerName }) => {
  if (!url) return null

  return (
    <div className="mt-3 p-4 bg-gradient-to-r from-green-50 to-emerald-50 border border-green-200 rounded-xl">
      <div className="flex items-center gap-2 mb-3">
        <div className="w-8 h-8 rounded-full bg-green-500 flex items-center justify-center">
          <CheckCircle className="w-5 h-5 text-white" />
        </div>
        <span className="font-semibold text-green-800">Deployment Successful!</span>
      </div>

      <div className="space-y-2">
        {/* Primary CTA - Visit the deployed app */}
        <a
          href={url}
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center justify-center gap-2 w-full px-4 py-3 bg-green-600 hover:bg-green-700 text-white font-medium rounded-lg transition-colors shadow-md hover:shadow-lg"
        >
          <ExternalLink className="w-5 h-5" />
          Open Application
        </a>

        {/* URL display */}
        <div className="flex items-center gap-2 px-3 py-2 bg-white rounded-lg border border-green-200">
          <Server className="w-4 h-4 text-green-600 flex-shrink-0" />
          <code className="text-sm text-green-800 truncate flex-1">{url}</code>
          <button
            onClick={() => navigator.clipboard.writeText(url)}
            className="text-xs text-green-600 hover:text-green-800 px-2 py-1 rounded hover:bg-green-100 transition-colors"
          >
            Copy
          </button>
        </div>

        {/* Container info */}
        {containerName && (
          <div className="flex items-center gap-2 px-3 py-2 bg-white/50 rounded-lg text-sm text-gray-600">
            <Terminal className="w-4 h-4 flex-shrink-0" />
            <span>Container: <code className="font-mono">{containerName}</code></span>
          </div>
        )}
      </div>
    </div>
  )
}

export default DeploymentCard
