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
  // Track which run we're polling so late responses from a previous run
  // don't clobber state for the current one.
  const activeRunRef = useRef(null)

  const pollRunStatus = useCallback((runId) => {
    // Clear any previous interval before starting a new one
    if (intervalRef.current) {
      clearInterval(intervalRef.current)
      intervalRef.current = null
    }

    activeRunRef.current = runId
    let notFoundCount = 0
    let networkErrorCount = 0

    // Save the interval ID to the ref IMMEDIATELY — before the first
    // tick fires — so cleanup always has a handle to clear.
    const id = setInterval(async () => {
      // Guard: if we've been superseded by a newer poll, bail out
      if (activeRunRef.current !== runId) {
        clearInterval(id)
        return
      }

      try {
        const status = await getRunStatus(runId)

        // Double-check we're still the active run after the await
        if (activeRunRef.current !== runId) return

        if (status.status === 'completed') {
          clearInterval(id)
          intervalRef.current = null
          activeRunRef.current = null
          setIsRunning(false)
          setRunMessage(null)
          setRunProgress(null)
          setRunResult(status.results)
          setRefreshKey((k) => k + 1)
        } else if (status.status === 'error') {
          clearInterval(id)
          intervalRef.current = null
          activeRunRef.current = null
          setIsRunning(false)
          setRunMessage(null)
          setRunProgress(null)
          setRunResult({ error: true, message: status.message })
          setRefreshKey((k) => k + 1)
        } else if (status.status === 'not_found') {
          // Backend might have restarted — wait a few polls before giving up
          notFoundCount++
          if (notFoundCount >= 3) {
            clearInterval(id)
            intervalRef.current = null
            activeRunRef.current = null
            setIsRunning(false)
            setRunMessage(null)
            setRunProgress(null)
            setRunResult({ error: true, message: 'Test run lost — the backend may have restarted. Check Test Results for partial results.' })
            setRefreshKey((k) => k + 1)
          }
        } else {
          notFoundCount = 0
          networkErrorCount = 0
          setRunMessage(status.message || 'Running tests...')
          setRunProgress({
            current_test: status.current_test,
            completed_tests: status.completed_tests || [],
            total_tests: status.total_tests || 0,
          })
        }
      } catch {
        // Tolerate brief network blips — give up after 3 consecutive failures
        networkErrorCount++
        if (networkErrorCount >= 3) {
          clearInterval(id)
          intervalRef.current = null
          activeRunRef.current = null
          setIsRunning(false)
          setRunMessage(null)
          setRunProgress(null)
          setRunResult({ error: true, message: 'Failed to check test run status after multiple retries' })
        }
      }
    }, 2000)

    intervalRef.current = id
  }, [setIsRunning, setRunMessage, setRunProgress, setRunResult, setRefreshKey])

  // Clean up interval on unmount to prevent setState on unmounted component
  useEffect(() => {
    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current)
        intervalRef.current = null
      }
      activeRunRef.current = null
    }
  }, [])

  return { pollRunStatus }
}
