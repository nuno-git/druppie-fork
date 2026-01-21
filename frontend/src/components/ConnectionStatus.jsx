/**
 * ConnectionStatus Component
 * Displays WebSocket connection status indicator in the bottom-right corner
 */

import React, { useState, useEffect } from 'react'
import { Loader2 } from 'lucide-react'
import { getConnectionStatus, onConnectionStatusChange } from '../services/socket'

// Status configurations
const statusConfig = {
  connected: {
    dotClass: 'bg-green-500',
    label: 'Connected',
    tooltip: 'Real-time connection is active',
  },
  disconnected: {
    dotClass: 'bg-red-500',
    label: 'Disconnected',
    tooltip: 'Real-time connection lost. Some features may not update automatically.',
  },
  connecting: {
    dotClass: 'bg-orange-500',
    label: 'Connecting',
    tooltip: 'Establishing real-time connection...',
    showSpinner: true,
  },
  reconnecting: {
    dotClass: 'bg-orange-500',
    label: 'Reconnecting',
    tooltip: 'Attempting to restore real-time connection...',
    showSpinner: true,
  },
}

const ConnectionStatus = () => {
  const [status, setStatus] = useState(getConnectionStatus)
  const [showTooltip, setShowTooltip] = useState(false)

  useEffect(() => {
    const unsubscribe = onConnectionStatusChange((newStatus) => {
      setStatus(newStatus)
    })

    return () => unsubscribe()
  }, [])

  const config = statusConfig[status] || statusConfig.disconnected

  return (
    <div className="fixed bottom-4 right-4 z-40">
      <div
        className="relative"
        onMouseEnter={() => setShowTooltip(true)}
        onMouseLeave={() => setShowTooltip(false)}
      >
        {/* Status indicator button */}
        <div className="flex items-center gap-2 px-3 py-2 bg-white rounded-full shadow-lg border border-gray-200 cursor-default hover:shadow-xl transition-shadow">
          {/* Status dot or spinner */}
          {config.showSpinner ? (
            <Loader2 className="w-3 h-3 text-orange-500 animate-spin" />
          ) : (
            <span className={`w-3 h-3 rounded-full ${config.dotClass}`} />
          )}
          <span className="text-xs font-medium text-gray-600">{config.label}</span>
        </div>

        {/* Tooltip */}
        {showTooltip && (
          <div className="absolute bottom-full right-0 mb-2 w-64">
            <div className="bg-gray-900 text-white text-xs rounded-lg px-3 py-2 shadow-lg">
              {config.tooltip}
              {/* Arrow */}
              <div className="absolute top-full right-4 w-0 h-0 border-l-4 border-r-4 border-t-4 border-l-transparent border-r-transparent border-t-gray-900" />
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

export default ConnectionStatus
