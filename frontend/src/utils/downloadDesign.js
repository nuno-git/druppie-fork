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

  const canvas = await html2canvas(element, {
    scale: 2,
    useCORS: true,
    logging: false,
    backgroundColor: '#ffffff',
  })

  const pdf = new jsPDF('p', 'mm', 'a4')
  const margin = 10
  const contentW = pdf.internal.pageSize.getWidth() - margin * 2
  const contentH = pdf.internal.pageSize.getHeight() - margin * 2
  const pxToMm = contentW / canvas.width
  const pageHeightPx = Math.floor(contentH / pxToMm)

  const ctx = canvas.getContext('2d')
  let pixels = null
  try {
    pixels = ctx.getImageData(0, 0, canvas.width, canvas.height).data
  } catch { /* tainted canvas */ }

  const stride = canvas.width * 4
  const cols = []
  for (let i = 1; i <= 10; i++) cols.push(Math.floor(canvas.width * i / 11))

  // Strict per-column check: every sample point must be nearly pure white.
  // This rejects rows with even faint anti-aliased text edges (which the
  // old average-brightness approach let through at ~253).
  function isGapRow(y) {
    if (!pixels || y < 0 || y >= canvas.height) return false
    const base = y * stride
    for (const col of cols) {
      const idx = base + col * 4
      if (pixels[idx] < 252 || pixels[idx + 1] < 252 || pixels[idx + 2] < 252) return false
    }
    return true
  }

  // Find 20+ consecutive gap rows (a real inter-line space).
  // Returns the middle of the run so both pages get whitespace margin.
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

  let srcY = 0
  let page = 0

  while (srcY < canvas.height) {
    if (page++ > 0) pdf.addPage()

    const idealEnd = srcY + pageHeightPx
    if (idealEnd >= canvas.height) {
      const h = canvas.height - srcY
      const slice = document.createElement('canvas')
      slice.width = canvas.width; slice.height = h
      slice.getContext('2d').drawImage(canvas, 0, srcY, canvas.width, h, 0, 0, canvas.width, h)
      pdf.addImage(slice.toDataURL('image/png'), 'PNG', margin, margin, contentW, h * pxToMm)
      break
    }

    const gap = findGap(idealEnd, srcY)
    const endY = gap !== null ? gap : Math.round(idealEnd)
    const h = Math.min(endY - srcY, canvas.height - srcY)
    if (h <= 0) break

    const slice = document.createElement('canvas')
    slice.width = canvas.width; slice.height = h
    slice.getContext('2d').drawImage(canvas, 0, srcY, canvas.width, h, 0, 0, canvas.width, h)
    pdf.addImage(slice.toDataURL('image/png'), 'PNG', margin, margin, contentW, h * pxToMm)
    srcY += h
  }

  pdf.save(filename)
}

// Pre-render mermaid code blocks to raster images for reliable PDF capture.
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

    try {
      const id = `pdf-mermaid-${++counter}-${Date.now()}`
      const { svg } = await mermaid.render(id, code)

      const dataUrl = `data:image/svg+xml;base64,${btoa(unescape(encodeURIComponent(svg)))}`
      const img = new Image()
      await new Promise((resolve, reject) => {
        img.onload = resolve
        img.onerror = reject
        img.src = dataUrl
      })

      const c = document.createElement('canvas')
      c.width = img.naturalWidth * 2
      c.height = img.naturalHeight * 2
      const ctx = c.getContext('2d')
      ctx.fillStyle = '#ffffff'
      ctx.fillRect(0, 0, c.width, c.height)
      ctx.drawImage(img, 0, 0, c.width, c.height)

      const replacement = document.createElement('img')
      replacement.src = c.toDataURL('image/png')
      replacement.style.cssText = 'max-width:100%;height:auto;display:block;margin:16px 0;'
      pre.replaceWith(replacement)
    } catch {
      // Keep the raw code block if mermaid rendering fails
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

export async function downloadContentAsPdf(markdownContent, path) {
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
    await downloadElementAsPdf(container.firstElementChild, path)
  } finally {
    document.body.removeChild(container)
  }
}
