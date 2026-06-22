/**
 * Module-level store for pending chat messages during the
 * NewSessionPanel → SessionDetail transition.
 *
 * Survives React re-renders because it lives outside the component tree.
 */

let _pending = null

export function setPending(sessionId, message, attachments = []) {
  _pending = { sessionId, message, attachments }
}

export function consumePending(sessionId) {
  if (_pending && _pending.sessionId === sessionId) {
    const val = _pending
    _pending = null
    return val
  }
  return null
}
