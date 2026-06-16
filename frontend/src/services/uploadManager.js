/**
 * Module-level upload manager.
 *
 * Uploads survive React component unmounts — results are stored here
 * and drained by the component when it remounts.
 */

import { uploadAttachment } from './api'

const completed = new Map()
const errors = new Map()
const active = new Map()
const statusTexts = new Map()
const listeners = new Set()

function key(sessionId, scope = 'chat') {
  return `${sessionId || '__new__'}:${scope}`
}

function notify() {
  listeners.forEach((fn) => fn())
}

export function startUpload(file, sessionId, scope = 'chat') {
  const k = key(sessionId, scope)
  active.set(k, (active.get(k) || 0) + 1)

  const isPdf = file.type === 'application/pdf' || file.name?.toLowerCase().endsWith('.pdf')
  const status = isPdf ? 'Processing PDF…' : `Uploading ${file.name}…`
  statusTexts.set(k, status)
  notify()

  uploadAttachment(file, sessionId)
    .then((result) => {
      const list = completed.get(k) || []
      list.push(result)
      completed.set(k, list)
    })
    .catch((err) => {
      const list = errors.get(k) || []
      list.push(err.message || `Failed to upload ${file.name}`)
      errors.set(k, list)
    })
    .finally(() => {
      const count = Math.max(0, (active.get(k) || 1) - 1)
      active.set(k, count)
      if (count === 0) statusTexts.delete(k)
      notify()
    })
}

export function drainCompleted(sessionId, scope = 'chat') {
  const k = key(sessionId, scope)
  const results = completed.get(k) || []
  completed.delete(k)
  return results
}

export function drainErrors(sessionId, scope = 'chat') {
  const k = key(sessionId, scope)
  const errs = errors.get(k) || []
  errors.delete(k)
  return errs
}

export function isUploading(sessionId, scope = 'chat') {
  return (active.get(key(sessionId, scope)) || 0) > 0
}

export function getStatusText(sessionId, scope = 'chat') {
  return statusTexts.get(key(sessionId, scope)) || ''
}

export function subscribe(fn) {
  listeners.add(fn)
  return () => listeners.delete(fn)
}
