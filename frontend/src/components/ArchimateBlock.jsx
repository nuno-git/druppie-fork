/**
 * ArchimateBlock — renders ```archimate view-id=… file=… ``` code-blocks.
 *
 * The code-block body is a small metadata spec (Q4 decision):
 *
 *     view-id: <uuid>
 *     file: docs/architecture.archimate
 *
 * The component fetches the .archimate XML from the project repo via
 * the backend's Gitea proxy, parses it, runs elkjs auto-layout for
 * any view that lacks geometry, and renders an SVG with proper
 * ArchiMate notation. Pan & zoom mirror MermaidBlock's interactions.
 *
 * Delta-highlighting (task #16) is wired but disabled until we have
 * a way to obtain the diff. See highlightIds prop.
 */

import { useEffect, useState, useRef, useCallback, useContext } from 'react'
import { AlertTriangle, Code, Eye, ZoomIn, ZoomOut, Maximize2 } from 'lucide-react'
import { ProjectRepoContext } from './chat/ChatHelpers'
import { parseEmbedSpec } from './archimate/archimateParser'
import { renderArchimateSpecToSvg } from './archimate/archimateRender'

// --- Interactive pan/zoom (same UX as MermaidBlock) -----------------------

const InteractiveDiagram = ({ svg }) => {
  const containerRef = useRef(null)
  const [transform, setTransform] = useState({ x: 0, y: 0, scale: 1 })
  const dragRef = useRef({ dragging: false, startX: 0, startY: 0, startTx: 0, startTy: 0 })

  const handleWheel = useCallback((e) => {
    e.preventDefault()
    const delta = e.deltaY > 0 ? 0.9 : 1.1
    setTransform((t) => ({ ...t, scale: Math.min(Math.max(t.scale * delta, 0.2), 5) }))
  }, [])

  const handleMouseDown = useCallback((e) => {
    if (e.button !== 0) return
    dragRef.current = {
      dragging: true,
      startX: e.clientX, startY: e.clientY,
      startTx: transform.x, startTy: transform.y,
    }
    e.currentTarget.style.cursor = 'grabbing'
  }, [transform.x, transform.y])

  const handleMouseMove = useCallback((e) => {
    if (!dragRef.current.dragging) return
    const dx = e.clientX - dragRef.current.startX
    const dy = e.clientY - dragRef.current.startY
    setTransform((t) => ({ ...t, x: dragRef.current.startTx + dx, y: dragRef.current.startTy + dy }))
  }, [])

  const handleMouseUp = useCallback((e) => {
    dragRef.current.dragging = false
    if (e.currentTarget) e.currentTarget.style.cursor = 'grab'
  }, [])

  const resetZoom = useCallback(() => setTransform({ x: 0, y: 0, scale: 1 }), [])
  const zoomIn = useCallback(() => setTransform((t) => ({ ...t, scale: Math.min(t.scale * 1.3, 5) })), [])
  const zoomOut = useCallback(() => setTransform((t) => ({ ...t, scale: Math.max(t.scale * 0.7, 0.2) })), [])

  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    el.addEventListener('wheel', handleWheel, { passive: false })
    return () => el.removeEventListener('wheel', handleWheel)
  }, [handleWheel])

  return (
    <div className="relative">
      <div className="absolute top-2 right-2 z-10 flex items-center gap-0.5 bg-white/90 border border-gray-200 rounded-lg shadow-sm p-0.5">
        <button onClick={zoomIn} className="p-1.5 text-gray-500 hover:text-gray-700 hover:bg-gray-100 rounded transition-colors" title="Zoom in">
          <ZoomIn className="w-3.5 h-3.5" />
        </button>
        <button onClick={zoomOut} className="p-1.5 text-gray-500 hover:text-gray-700 hover:bg-gray-100 rounded transition-colors" title="Zoom out">
          <ZoomOut className="w-3.5 h-3.5" />
        </button>
        <button onClick={resetZoom} className="p-1.5 text-gray-500 hover:text-gray-700 hover:bg-gray-100 rounded transition-colors" title="Reset view">
          <Maximize2 className="w-3.5 h-3.5" />
        </button>
      </div>
      <div
        ref={containerRef}
        className="overflow-hidden bg-white rounded-b-lg"
        style={{ minHeight: '300px', cursor: 'grab' }}
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={handleMouseUp}
      >
        <div
          style={{
            transform: `translate(${transform.x}px, ${transform.y}px) scale(${transform.scale})`,
            transformOrigin: 'center center',
            transition: dragRef.current.dragging ? 'none' : 'transform 0.15s ease-out',
            padding: '24px',
            display: 'flex',
            justifyContent: 'center',
          }}
          dangerouslySetInnerHTML={{ __html: svg }}
        />
      </div>
    </div>
  )
}

// --- Main block -----------------------------------------------------------

const ArchimateBlock = ({ code, highlightIds }) => {
  const repo = useContext(ProjectRepoContext)
  const [state, setState] = useState({ status: 'loading', svg: null, error: null })
  const [showRaw, setShowRaw] = useState(false)

  const spec = parseEmbedSpec(code)

  useEffect(() => {
    let cancelled = false
    if (!spec) {
      setState({ status: 'error', error: 'Missing view-id in code block', svg: null })
      return
    }
    if (!repo?.id) {
      setState({ status: 'error', error: 'No project context — open this TD inside a project session', svg: null })
      return
    }

    setState({ status: 'loading', svg: null, error: null })

    ;(async () => {
      try {
        const { svg, viewName, changeCount, lastCommitMessage } =
          await renderArchimateSpecToSvg(code, repo, { highlightIds })
        if (!cancelled) {
          setState({ status: 'ready', svg, error: null, viewName, changeCount, lastCommitMessage })
        }
      } catch (err) {
        if (!cancelled) {
          setState({ status: 'error', error: err.message || String(err), svg: null })
        }
      }
    })()

    return () => { cancelled = true }
    // intentionally not depending on highlightIds — would re-fetch on identity change
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [code, repo?.id, repo?.default_branch, repo?.session_id])

  return (
    <div className="my-3 rounded-lg overflow-hidden border border-gray-200">
      <div className="flex items-center justify-between px-3 py-1.5 bg-gray-100 border-b border-gray-200">
        <div className="flex items-center gap-2">
          <span className="text-xs font-medium text-gray-600">archimate</span>
          {state.viewName && (
            <span className="text-xs text-gray-500 truncate max-w-xs" title={state.viewName}>
              · {state.viewName}
            </span>
          )}
          {state.changeCount > 0 && (
            <span
              className="inline-flex items-center gap-1 text-xs text-blue-700 bg-blue-50 border border-blue-200 px-1.5 py-0.5 rounded"
              title={state.lastCommitMessage || 'Elements highlighted are new in the last commit'}
            >
              {state.changeCount} new
            </span>
          )}
          {state.status === 'error' && (
            <span className="inline-flex items-center gap-1 text-xs text-amber-600">
              <AlertTriangle className="w-3 h-3" />
              render failed
            </span>
          )}
        </div>
        <div className="flex items-center gap-1">
          {state.svg && (
            <button
              onClick={() => setShowRaw(!showRaw)}
              className="flex items-center gap-1 px-2 py-0.5 text-xs rounded text-gray-500 hover:text-gray-700 hover:bg-gray-200 transition-colors"
            >
              {showRaw ? <Eye className="w-3 h-3" /> : <Code className="w-3 h-3" />}
              {showRaw ? 'Diagram' : 'Raw'}
            </button>
          )}
        </div>
      </div>

      {state.status === 'loading' && (
        <div className="p-4 bg-gray-50 text-center text-xs text-gray-400">
          Loading ArchiMate view…
        </div>
      )}

      {state.status === 'error' && (
        <div className="px-3 py-2 bg-amber-50 border-b border-amber-100 text-xs text-amber-700">
          {state.error}
        </div>
      )}

      {(showRaw || state.status === 'error') && (
        <pre className="p-3 bg-gray-900 text-gray-100 text-sm overflow-x-auto whitespace-pre font-mono leading-relaxed">
          {code}
        </pre>
      )}

      {state.svg && !showRaw && state.status === 'ready' && (
        <InteractiveDiagram svg={state.svg} />
      )}
    </div>
  )
}

export default ArchimateBlock
