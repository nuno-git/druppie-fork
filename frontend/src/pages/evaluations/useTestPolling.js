import { useRef, useCallback, useEffect } from 'react'
import { getRunStatus } from '../../services/api'

/**
 * Custom hook that encapsulates the setInterval-based polling logic
 * for monitoring a background test run until completion.
 *
 * Returns { pollRunStatus } — call it with a run_id to start polling.
 * The hook calls the provided callbacks as status changes occur.
 */
export default function useTestPolling({
  setIsRunning,
  setRunMessage,
  setRunProgress,
  setRunResult,
  setRefreshKey,
}) {
  const intervalRef = useRef(null)

  const pollRunStatus = useCallback((runId) => {
    // Clear any previous interval
    if (intervalRef.current) {
      clearInterval(intervalRef.current)
    }

    let notFoundCount = 0
    const pollInterval = setInterval(async () => {
      try {
        const status = await getRunStatus(runId)
        if (status.status === 'completed') {
          clearInterval(pollInterval)
          intervalRef.current = null
          setIsRunning(false)
          setRunMessage(null)
          setRunProgress(null)
          setRunResult(status.results)
          setRefreshKey((k) => k + 1)
        } else if (status.status === 'error') {
          clearInterval(pollInterval)
          intervalRef.current = null
          setIsRunning(false)
          setRunMessage(null)
          setRunProgress(null)
          setRunResult({ error: true, message: status.message })
          setRefreshKey((k) => k + 1)
        } else if (status.status === 'not_found') {
          // Backend might have restarted — wait a few polls before giving up
          notFoundCount++
          if (notFoundCount >= 3) {
            clearInterval(pollInterval)
            intervalRef.current = null
            setIsRunning(false)
            setRunMessage(null)
            setRunProgress(null)
            setRunResult({ error: true, message: 'Test run lost — the backend may have restarted. Check Test Results for partial results.' })
            setRefreshKey((k) => k + 1)
          }
        } else {
          notFoundCount = 0
          setRunMessage(status.message || 'Running tests...')
          setRunProgress({
            current_test: status.current_test,
            completed_tests: status.completed_tests || [],
            total_tests: status.total_tests || 0,
          })
        }
      } catch {
        clearInterval(pollInterval)
        intervalRef.current = null
        setIsRunning(false)
        setRunMessage(null)
        setRunProgress(null)
        setRunResult({ error: true, message: 'Failed to check test run status' })
      }
    }, 2000)

    intervalRef.current = pollInterval
  }, [setIsRunning, setRunMessage, setRunProgress, setRunResult, setRefreshKey])

  // Clean up interval on unmount to prevent setState on unmounted component
  useEffect(() => {
    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current)
        intervalRef.current = null
      }
    }
  }, [])

  return { pollRunStatus }
}
