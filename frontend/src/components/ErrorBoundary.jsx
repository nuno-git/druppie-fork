/**
 * Error Boundary Component
 * Catches JavaScript errors in child components and displays a fallback UI
 */

import React from 'react'
import { AlertTriangle, RefreshCw, ChevronDown, ChevronUp } from 'lucide-react'

/**
 * ErrorBoundary - Class component that catches errors in child components
 */
class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props)
    this.state = {
      hasError: false,
      error: null,
      errorInfo: null,
      showDetails: false,
    }
  }

  static getDerivedStateFromError(error) {
    // Update state so the next render shows the fallback UI
    return { hasError: true, error }
  }

  componentDidCatch(error, errorInfo) {
    // Log error details for debugging
    console.error('ErrorBoundary caught an error:', error, errorInfo)
    this.setState({ errorInfo })
  }

  handleRetry = () => {
    this.setState({
      hasError: false,
      error: null,
      errorInfo: null,
      showDetails: false,
    })
  }

  toggleDetails = () => {
    this.setState((prev) => ({ showDetails: !prev.showDetails }))
  }

  render() {
    if (this.state.hasError) {
      const { error, errorInfo, showDetails } = this.state

      return (
        <div className="min-h-[400px] flex items-center justify-center p-8">
          <div className="max-w-lg w-full bg-white rounded-xl shadow-lg border border-gray-200 p-8">
            {/* Error Icon */}
            <div className="flex justify-center mb-6">
              <div className="w-16 h-16 bg-red-100 rounded-full flex items-center justify-center">
                <AlertTriangle className="w-8 h-8 text-red-500" />
              </div>
            </div>

            {/* Error Message */}
            <div className="text-center mb-6">
              <h2 className="text-xl font-semibold text-gray-900 mb-2">
                Something went wrong
              </h2>
              <p className="text-gray-600">
                An unexpected error occurred. Please try again or contact support if the problem persists.
              </p>
            </div>

            {/* Retry Button */}
            <div className="flex justify-center mb-6">
              <button
                onClick={this.handleRetry}
                className="inline-flex items-center gap-2 px-6 py-3 bg-blue-600 text-white font-medium rounded-lg hover:bg-blue-700 transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2"
              >
                <RefreshCw className="w-4 h-4" />
                Try Again
              </button>
            </div>

            {/* Error Details Toggle */}
            <div className="border-t border-gray-200 pt-4">
              <button
                onClick={this.toggleDetails}
                className="w-full flex items-center justify-between text-sm text-gray-500 hover:text-gray-700 transition-colors"
              >
                <span>Error Details</span>
                {showDetails ? (
                  <ChevronUp className="w-4 h-4" />
                ) : (
                  <ChevronDown className="w-4 h-4" />
                )}
              </button>

              {showDetails && (
                <div className="mt-4 p-4 bg-gray-50 rounded-lg overflow-auto max-h-64">
                  <div className="mb-3">
                    <p className="text-xs font-medium text-gray-500 uppercase mb-1">
                      Error Message
                    </p>
                    <p className="text-sm text-red-600 font-mono">
                      {error?.message || 'Unknown error'}
                    </p>
                  </div>
                  {errorInfo?.componentStack && (
                    <div>
                      <p className="text-xs font-medium text-gray-500 uppercase mb-1">
                        Component Stack
                      </p>
                      <pre className="text-xs text-gray-600 font-mono whitespace-pre-wrap">
                        {errorInfo.componentStack}
                      </pre>
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        </div>
      )
    }

    return this.props.children
  }
}

/**
 * ErrorMessage - Inline error component for query/fetch errors
 * Use this for displaying errors within the normal page flow
 */
export const ErrorMessage = ({
  title = 'Error',
  message = 'Something went wrong',
  onRetry,
  className = '',
}) => {
  return (
    <div
      className={`flex items-start gap-3 p-4 bg-red-50 border border-red-200 rounded-lg ${className}`}
      role="alert"
    >
      <AlertTriangle className="w-5 h-5 text-red-500 flex-shrink-0 mt-0.5" />
      <div className="flex-1 min-w-0">
        <p className="font-medium text-red-800">{title}</p>
        <p className="text-sm text-red-700 mt-0.5">{message}</p>
        {onRetry && (
          <button
            onClick={onRetry}
            className="mt-3 inline-flex items-center gap-1.5 text-sm font-medium text-red-700 hover:text-red-800 transition-colors"
          >
            <RefreshCw className="w-3.5 h-3.5" />
            Retry
          </button>
        )}
      </div>
    </div>
  )
}

export default ErrorBoundary
