/**
 * MermaidBlock - Renders mermaid diagram code into interactive SVG
 *
 * Lazy-loads mermaid on first use to avoid bloating the main bundle.
 * Features:
 *  - Toggle between rendered diagram and raw code
 *  - Pan & zoom via mouse wheel / drag
 *  - Helpful error message when agents produce invalid syntax
 *  - Reset zoom button
 */

import { useEffect, useRef, useState, useCallback } from 'react'
import { Code, Eye, ZoomIn, ZoomOut, Maximize2, AlertTriangle } from 'lucide-react'

let mermaidModule = null
let mermaidPromise = null
let idCounter = 0

const getMermaid = () => {
  if (mermaidModule) return Promise.resolve(mermaidModule)
  if (!mermaidPromise) {
    mermaidPromise = import('mermaid').then((mod) => {
      const m = mod.default
      m.initialize({
        startOnLoad: false,
        theme: 'default',
        securityLevel: 'strict',
        suppressErrorRendering: true,
        fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
        maxTextSize: 100000,
        flowchart: { useMaxWidth: false, htmlLabels: true, curve: 'basis' },
        sequence: { useMaxWidth: false },
        gantt: { useMaxWidth: false },
        class: { useMaxWidth: false },
        state: { useMaxWidth: false },
        er: { useMaxWidth: false },
        pie: { useMaxWidth: false },
      })
      mermaidModule = m
      return m
    })
  }
  return mermaidPromise
}

// --- Interactive SVG container with pan & zoom ---

const InteractiveDiagram = ({ svg }) => {
  const containerRef = useRef(null)
  const [transform, setTransform] = useState({ x: 0, y: 0, scale: 1 })
  const dragRef = useRef({ dragging: false, startX: 0, startY: 0, startTx: 0, startTy: 0 })

  const handleWheel = useCallback((e) => {
    e.preventDefault()
    const delta = e.deltaY > 0 ? 0.9 : 1.1
    setTransform((t) => {
      const newScale = Math.min(Math.max(t.scale * delta, 0.2), 5)
      return { ...t, scale: newScale }
    })
  }, [])

  const handleMouseDown = useCallback((e) => {
    if (e.button !== 0) return
    dragRef.current = { dragging: true, startX: e.clientX, startY: e.clientY, startTx: transform.x, startTy: transform.y }
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

  // Attach wheel listener with passive: false so we can preventDefault
  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    el.addEventListener('wheel', handleWheel, { passive: false })
    return () => el.removeEventListener('wheel', handleWheel)
  }, [handleWheel])

  return (
    <div className="relative">
      {/* Zoom controls */}
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
      {/* Diagram viewport */}
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

// --- Main MermaidBlock ---

const MermaidBlock = ({ code }) => {
  const [error, setError] = useState(null)
  const [svg, setSvg] = useState(null)
  const [showRaw, setShowRaw] = useState(false)

  useEffect(() => {
    if (!code?.trim()) return
    let cancelled = false

    const render = async () => {
      const id = `mermaid-${++idCounter}`
      try {
        const mermaid = await getMermaid()
        const { svg: rendered } = await mermaid.render(id, code.trim())
        if (!cancelled) {
          setSvg(rendered)
          setError(null)
        }
      } catch (err) {
        // Clean up mermaid's default error elements injected into the DOM
        document.querySelector(`#d${id}`)?.remove()
        document.querySelector(`#${id}`)?.remove()
        document.querySelector('.mermaid-error')?.remove()
        if (!cancelled) {
          setError(err.message || 'Failed to render diagram')
          setSvg(null)
        }
      }
    }

    render()
    return () => { cancelled = true }
  }, [code])

  // Loading state
  if (!svg && !error) {
    return (
      <div className="my-2 p-4 bg-gray-50 border border-gray-200 rounded-lg text-center text-xs text-gray-400">
        Rendering diagram...
      </div>
    )
  }

  return (
    <div className="my-3 rounded-lg overflow-hidden border border-gray-200">
      {/* Header bar */}
      <div className="flex items-center justify-between px-3 py-1.5 bg-gray-100 border-b border-gray-200">
        <div className="flex items-center gap-2">
          <span className="text-xs font-medium text-gray-600">mermaid</span>
          {error && (
            <span className="inline-flex items-center gap-1 text-xs text-amber-600">
              <AlertTriangle className="w-3 h-3" />
              syntax error
            </span>
          )}
        </div>
        <div className="flex items-center gap-1">
          {svg && (
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

      {/* Error hint */}
      {error && (
        <div className="px-3 py-2 bg-amber-50 border-b border-amber-100 text-xs text-amber-700">
          The AI agent produced mermaid syntax that could not be rendered. The raw code is shown below.
        </div>
      )}

      {/* Content: raw code or interactive diagram */}
      {error || showRaw ? (
        <pre className="p-3 bg-gray-900 text-gray-100 text-sm overflow-x-auto whitespace-pre font-mono leading-relaxed">
          {code}
        </pre>
      ) : (
        <InteractiveDiagram svg={svg} />
      )}
    </div>
  )
}

export default MermaidBlock
