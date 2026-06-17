/**
 * Download design documents as Markdown or PDF.
 *
 * jspdf, html2canvas, marked, and dompurify are loaded via dynamic import()
 * so they never enter the initial bundle.
 */

import { getAgentConfig } from './agentConfig'

const basename = (path) => path?.split('/').pop() || 'document'

export function downloadAsMarkdown(content, path) {
  const filename = basename(path)
  const blob = new Blob([content], { type: 'text/markdown;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename.endsWith('.md') ? filename : `${filename}.md`
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

async function downloadElementAsPdf(element, path) {
  const filename = basename(path).replace(/\.\w+$/, '') + '.pdf'

  const [{ default: html2canvas }, { jsPDF }] = await Promise.all([
    import('html2canvas'),
    import('jspdf'),
  ])

  const scale = 1.5
  const sourceWidth = element.scrollWidth
  const sourceHeight = element.scrollHeight
  const canvasWidth = Math.ceil(sourceWidth * scale)

  const pdf = new jsPDF('p', 'mm', 'a4')
  const margin = 10
  const contentW = pdf.internal.pageSize.getWidth() - margin * 2
  const contentH = pdf.internal.pageSize.getHeight() - margin * 2
  const pxToMm = contentW / canvasWidth
  const pageHeightPx = Math.floor(contentH / pxToMm)

  const MAX_SEGMENT_PIXELS = 16_000_000
  const maxSegCanvasH = Math.floor(MAX_SEGMENT_PIXELS / canvasWidth)
  const maxSegSourceH = Math.floor(maxSegCanvasH / scale)

  let absoluteSourceY = 0
  let page = 0

  while (absoluteSourceY < sourceHeight) {
    const segSourceH = Math.min(maxSegSourceH, sourceHeight - absoluteSourceY)
    const isLastSegment = absoluteSourceY + segSourceH >= sourceHeight

    const canvas = await html2canvas(element, {
      scale,
      useCORS: true,
      logging: false,
      backgroundColor: '#ffffff',
      y: absoluteSourceY,
      height: segSourceH,
    })

    let pixels = null
    try {
      pixels = canvas.getContext('2d').getImageData(0, 0, canvas.width, canvas.height).data
    } catch { /* tainted canvas */ }

    const stride = canvas.width * 4
    const cols = []
    for (let i = 1; i <= 10; i++) cols.push(Math.floor(canvas.width * i / 11))

    function isGapRow(y) {
      if (!pixels || y < 0 || y >= canvas.height) return false
      const base = y * stride
      for (const col of cols) {
        const idx = base + col * 4
        if (pixels[idx] < 252 || pixels[idx + 1] < 252 || pixels[idx + 2] < 252) return false
      }
      return true
    }

    function findGap(idealEnd, pageStart) {
      if (!pixels) return null
      const need = 20
      const hi = Math.min(Math.floor(idealEnd), canvas.height - 1)
      const lo = Math.max(Math.floor(pageStart + pageHeightPx * 0.5), 0)
      let run = 0
      for (let y = hi; y >= lo; y--) {
        if (isGapRow(y)) {
          if (++run >= need) return y + Math.floor(run / 2)
        } else {
          run = 0
        }
      }
      return null
    }

    let localY = 0

    while (localY < canvas.height) {
      const idealEnd = localY + pageHeightPx

      if (idealEnd >= canvas.height && isLastSegment) {
        if (page++ > 0) pdf.addPage()
        const h = canvas.height - localY
        if (h <= 0) break
        const slice = document.createElement('canvas')
        slice.width = canvas.width; slice.height = h
        slice.getContext('2d').drawImage(canvas, 0, localY, canvas.width, h, 0, 0, canvas.width, h)
        pdf.addImage(slice.toDataURL('image/jpeg', 0.85), 'JPEG', margin, margin, contentW, h * pxToMm, undefined, 'FAST')
        localY = canvas.height
        break
      }

      if (idealEnd > canvas.height) break

      if (page++ > 0) pdf.addPage()
      const gap = findGap(idealEnd, localY)
      const endY = gap !== null ? gap : Math.round(idealEnd)
      const h = Math.min(endY - localY, canvas.height - localY)
      if (h <= 0) break

      const slice = document.createElement('canvas')
      slice.width = canvas.width; slice.height = h
      slice.getContext('2d').drawImage(canvas, 0, localY, canvas.width, h, 0, 0, canvas.width, h)
      pdf.addImage(slice.toDataURL('image/jpeg', 0.85), 'JPEG', margin, margin, contentW, h * pxToMm, undefined, 'FAST')
      localY += h
    }

    absoluteSourceY += localY / scale
    pixels = null
    if (localY === 0) break
  }

  pdf.save(filename)
}

// Browsers skip <foreignObject> when rendering SVG as <img> (security sandbox).
// Mermaid puts text labels inside <foreignObject> by default (htmlLabels:true).
// Replace each one with a native SVG <text> so labels survive rasterisation.
// Uses regex on the raw SVG string to avoid DOMParser/XMLSerializer round-trip
// which can corrupt namespaces and break the image load.

function wordWrap(text, maxWidth, fontSize) {
  const avgCharWidth = fontSize * 0.6
  const maxChars = Math.max(1, Math.floor(maxWidth / avgCharWidth))
  const words = text.split(/\s+/)
  const lines = []
  let cur = ''
  for (const word of words) {
    if (!cur) {
      cur = word
    } else if ((cur + ' ' + word).length <= maxChars) {
      cur += ' ' + word
    } else {
      lines.push(cur)
      cur = word
    }
  }
  if (cur) lines.push(cur)
  return lines.length ? lines : [text]
}

function escapeXml(s) {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

function foreignObjectsToText(svgString) {
  return svgString.replace(
    /<foreignObject([^>]*)>([\s\S]*?)<\/foreignObject>/gi,
    (_match, attrs, content) => {
      const tmp = document.createElement('div')
      tmp.innerHTML = content
      const text = tmp.textContent.trim()
      if (!text) return ''

      const w = parseFloat((attrs.match(/width="([^"]+)"/) || [])[1]) || 0
      const h = parseFloat((attrs.match(/height="([^"]+)"/) || [])[1]) || 0
      const x = parseFloat((attrs.match(/\bx="([^"]+)"/) || [])[1]) || 0
      const y = parseFloat((attrs.match(/\by="([^"]+)"/) || [])[1]) || 0
      const fontSize = parseFloat((content.match(/font-size:\s*([\d.]+)/i) || [])[1]) || 14

      const cx = x + w / 2
      const pad = 8
      const lines = wordWrap(text, Math.max(w - pad * 2, fontSize * 2), fontSize)
      const lineH = fontSize * 1.35
      const totalH = lines.length * lineH
      const baseY = y + (h - totalH) / 2 + fontSize * 0.9

      const tspans = lines
        .map((line, i) => `<tspan x="${cx}" y="${baseY + i * lineH}">${escapeXml(line)}</tspan>`)
        .join('')

      return `<text text-anchor="middle" font-family="'trebuchet ms', verdana, arial, sans-serif" font-size="${fontSize}" fill="#333">${tspans}</text>`
    },
  )
}

// Content column inside the PDF container (800px − 2×48px padding). Diagrams
// are rasterised to fill this width (scaled down only when they'd be too tall),
// so they never come out tiny. The canvas renders at 2× for crisp output.
const PDF_CONTENT_WIDTH = 704
const PDF_MAX_DIAGRAM_HEIGHT = 1800

// Rasterise an SVG string to a page-width <img> for reliable PDF capture.
// Shared by the mermaid and archimate renderers. Drawing the (vector) SVG onto
// a larger canvas keeps it sharp even when the source diagram is small.
async function svgToPdfImage(svgString) {
  const svgBlob = new Blob([svgString], { type: 'image/svg+xml;charset=utf-8' })
  const svgUrl = URL.createObjectURL(svgBlob)
  try {
    const img = new Image()
    await new Promise((resolve, reject) => {
      img.onload = resolve
      img.onerror = reject
      img.src = svgUrl
    })

    const iw = img.naturalWidth || 800
    const ih = img.naturalHeight || 600
    let displayW = PDF_CONTENT_WIDTH
    let displayH = Math.round(ih * (displayW / iw))
    if (displayH > PDF_MAX_DIAGRAM_HEIGHT) {
      displayH = PDF_MAX_DIAGRAM_HEIGHT
      displayW = Math.round(iw * (displayH / ih))
    }

    const scale = 2
    const c = document.createElement('canvas')
    c.width = displayW * scale
    c.height = displayH * scale
    const ctx = c.getContext('2d')
    ctx.fillStyle = '#ffffff'
    ctx.fillRect(0, 0, c.width, c.height)
    ctx.drawImage(img, 0, 0, c.width, c.height)

    const replacement = document.createElement('img')
    replacement.src = c.toDataURL('image/jpeg', 0.90)
    replacement.width = displayW
    replacement.height = displayH
    replacement.style.cssText = 'max-width:100%;height:auto;display:block;margin:16px 0;'
    await replacement.decode().catch(() => {})
    return replacement
  } finally {
    URL.revokeObjectURL(svgUrl)
  }
}

async function renderMermaidForPdf(container) {
  const codeBlocks = container.querySelectorAll('pre > code.language-mermaid')
  if (codeBlocks.length === 0) return

  const { default: mermaid } = await import('mermaid')

  mermaid.initialize({
    startOnLoad: false,
    theme: 'default',
    securityLevel: 'strict',
    suppressErrorRendering: true,
    flowchart: { htmlLabels: false, useMaxWidth: false },
  })

  let counter = 0
  for (const codeEl of codeBlocks) {
    const pre = codeEl.parentElement
    const code = codeEl.textContent.trim()
    if (!code) continue

    const id = `pdf-mermaid-${++counter}-${Date.now()}`
    try {
      const { svg } = await mermaid.render(id, code)

      // Convert any <foreignObject> labels to SVG <text> so they survive
      // the browser's image-context sandbox (htmlLabels:false may not
      // take effect if mermaid was already initialised with htmlLabels:true)
      const cleanSvg = foreignObjectsToText(svg)

      const replacement = await svgToPdfImage(cleanSvg)
      pre.replaceWith(replacement)
    } catch (err) {
      console.warn(`[PDF] mermaid block ${counter} failed:`, err)
      document.querySelector(`#d${id}`)?.remove()
      document.querySelector(`#${id}`)?.remove()
    }
  }

  mermaid.initialize({
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
}

// Pre-render ```archimate code blocks to raster images for PDF capture.
// Reuses the same SVG the chat builds (via renderArchimateSpecToSvg) and the
// same rasterisation path as mermaid. Needs the project/session context to
// fetch the .archimate model; without it the raw code block is left intact.
async function renderArchimateForPdf(container, repoContext) {
  const codeBlocks = container.querySelectorAll('pre > code.language-archimate')
  if (codeBlocks.length === 0) return
  if (!repoContext?.id) {
    console.warn('[PDF] archimate blocks present but no project context — left as raw code')
    return
  }

  const { renderArchimateSpecToSvg } = await import('../components/archimate/archimateRender')

  let counter = 0
  for (const codeEl of codeBlocks) {
    const pre = codeEl.parentElement
    const code = codeEl.textContent.trim()
    if (!code) continue
    counter++
    try {
      const { svg } = await renderArchimateSpecToSvg(code, repoContext)
      const replacement = await svgToPdfImage(svg)
      pre.replaceWith(replacement)
    } catch (err) {
      console.warn(`[PDF] archimate block ${counter} failed:`, err)
      // leave the raw code block in place
    }
  }
}

export function buildChatTranscript(sessionData) {
  const title = sessionData.title || 'Untitled Session'
  const lines = [`# ${title}\n`]

  const created = sessionData.created_at
    ? new Date(sessionData.created_at).toLocaleString()
    : null
  if (created) lines.push(`**Session started:** ${created}\n`)
  if (sessionData.status) lines.push(`**Status:** ${sessionData.status}\n`)

  lines.push('---\n')

  for (const entry of sessionData.timeline || []) {
    if (entry.type === 'message' && entry.message) {
      const msg = entry.message
      const time = msg.created_at
        ? new Date(msg.created_at).toLocaleTimeString()
        : ''

      if (msg.role === 'user') {
        lines.push(`### User\n`)
        lines.push(`${msg.content}\n`)
      } else {
        const config = msg.agent_id ? getAgentConfig(msg.agent_id) : null
        const sender = config ? config.name : 'System'
        lines.push(`### ${sender}  —  ${time}\n`)
        lines.push(`${msg.content}\n`)
      }
      lines.push('---\n')
      continue
    }

    if (entry.type === 'agent_run' && entry.agent_run) {
      const run = entry.agent_run
      const config = getAgentConfig(run.agent_id)
      const agentName = config.name
      const runTime = run.started_at
        ? new Date(run.started_at).toLocaleTimeString()
        : ''
      const doneTime = run.completed_at
        ? new Date(run.completed_at).toLocaleTimeString()
        : runTime

      for (const llm of run.llm_calls || []) {
        for (const tc of llm.tool_calls || []) {
          const toolName = tc.tool_name || ''

          if (toolName.includes('hitl_ask')) {
            const q = tc.arguments?.question || tc.arguments?.message || ''
            const choices = tc.arguments?.choices || tc.arguments?.options
            lines.push(`### ${agentName}  —  ${runTime}\n`)
            lines.push(`${q}\n`)
            if (choices?.length) {
              for (const c of choices) {
                const label = typeof c === 'string' ? c : c.text || c.label || String(c)
                lines.push(`- ${label}`)
              }
              lines.push('')
            }
            if (tc.result) {
              let answer = ''
              try {
                const parsed = typeof tc.result === 'string' ? JSON.parse(tc.result) : tc.result
                answer = parsed?.answer || ''
              } catch { answer = tc.result }
              if (answer) lines.push(`### User\n\n${answer}\n`)
            }
            lines.push('---\n')
            continue
          }

          if (tc.approval) {
            const aPath = tc.arguments?.path || ''
            const status = tc.approval.status || 'pending'
            const reason = tc.approval.reason || ''
            lines.push(`> **${agentName}** *(${runTime})* — approval gate (${status})`)
            if (aPath) lines.push(`> File: \`${aPath}\``)
            if (reason) lines.push(`> Reason: ${reason}`)
            lines.push('\n')
            continue
          }

          if (toolName.endsWith('done') && tc.arguments?.summary) {
            lines.push(`> **${agentName}** *(${doneTime})* — completed`)
            lines.push(`> ${tc.arguments.summary}\n`)
            continue
          }
        }
      }
    }
  }

  return lines.join('\n')
}

export async function downloadContentAsPdf(markdownContent, path, repoContext = null) {
  const [{ marked }, { default: DOMPurify }] = await Promise.all([
    import('marked'),
    import('dompurify'),
  ])

  const rawHtml = marked.parse(markdownContent)
  const html = DOMPurify.sanitize(rawHtml)

  const container = document.createElement('div')
  container.style.cssText =
    'position:fixed;left:-9999px;top:0;width:800px;background:#fff;z-index:-1;'
  container.innerHTML = `<div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;line-height:1.7;color:#1a1a1a;padding:40px 48px;font-size:14px;">${html}</div>`

  const s = (sel, css) =>
    container.querySelectorAll(sel).forEach((el) => { el.style.cssText += css })

  s('table', 'border-collapse:collapse;width:100%;margin:16px 0;')
  s('th,td', 'border:1px solid #ddd;padding:8px 12px;text-align:left;')
  s('th', 'background:#f5f5f5;font-weight:600;')
  s('pre', 'background:#f5f5f5;padding:12px 16px;border-radius:6px;overflow-x:auto;font-size:13px;line-height:1.5;white-space:pre-wrap;word-break:break-word;')
  s('code', 'font-family:ui-monospace,SFMono-Regular,Menlo,Monaco,monospace;font-size:13px;')
  s('h1', 'font-size:24px;font-weight:700;margin:24px 0 12px;border-bottom:1px solid #eee;padding-bottom:8px;')
  s('h2', 'font-size:20px;font-weight:600;margin:20px 0 10px;border-bottom:1px solid #eee;padding-bottom:6px;')
  s('h3', 'font-size:16px;font-weight:600;margin:16px 0 8px;')
  s('blockquote', 'border-left:3px solid #ddd;padding-left:12px;margin:12px 0;color:#555;')
  s('ul,ol', 'padding-left:24px;margin:8px 0;')
  s('li', 'margin:4px 0;')
  s('p', 'margin:8px 0;')
  s('hr', 'border:none;border-top:1px solid #eee;margin:24px 0;')
  s('img', 'max-width:100%;')

  document.body.appendChild(container)
  try {
    await renderMermaidForPdf(container)
    await renderArchimateForPdf(container, repoContext)
    await downloadElementAsPdf(container.firstElementChild, path)
  } catch (err) {
    console.error('[PDF] generation failed:', err)
    alert('PDF generation failed for this document — try downloading as Markdown instead.')
  } finally {
    document.body.removeChild(container)
  }
}
