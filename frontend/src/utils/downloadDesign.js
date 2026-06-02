/**
 * Download design documents as Markdown or PDF.
 *
 * - Markdown: direct Blob download of the raw content.
 * - PDF (from DOM element): html2canvas captures the rendered preview,
 *   jsPDF paginates it onto A4 pages.
 * - PDF (from raw content): markdown is converted to styled HTML via
 *   `marked`, rendered off-screen, then captured the same way.
 *
 * jspdf, html2canvas, and marked are loaded via dynamic import() so they
 * never enter the initial bundle.
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

export async function downloadElementAsPdf(element, path) {
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
  const pageW = pdf.internal.pageSize.getWidth()
  const pageH = pdf.internal.pageSize.getHeight()
  const margin = 10
  const contentW = pageW - margin * 2
  const contentH = pageH - margin * 2

  const scale = contentW / canvas.width
  const totalH = canvas.height * scale
  const pages = Math.ceil(totalH / contentH)

  for (let i = 0; i < pages; i++) {
    if (i > 0) pdf.addPage()

    const srcY = Math.round((i * contentH) / scale)
    const srcH = Math.min(Math.round(contentH / scale), canvas.height - srcY)
    if (srcH <= 0) break

    const slice = document.createElement('canvas')
    slice.width = canvas.width
    slice.height = srcH
    slice.getContext('2d').drawImage(
      canvas, 0, srcY, canvas.width, srcH, 0, 0, canvas.width, srcH,
    )

    pdf.addImage(slice.toDataURL('image/png'), 'PNG', margin, margin, contentW, srcH * scale)
  }

  pdf.save(filename)
}

/**
 * Build a markdown transcript of the full chat session.
 *
 * Two visual levels:
 * - "## Conversation" entries (### headings): messages the user sees and
 *   participates in — user messages, agent chat messages, and HITL
 *   questions with answers.
 * - "Agent output" entries (blockquotes): internal agent actions that
 *   drive the session forward — completion summaries, approval gates,
 *   and tool results.  These are rendered as indented blockquotes so
 *   a reader can scan the conversation flow without getting lost in
 *   agent internals.
 */
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
    // ── Conversation messages (user + agent chat bubbles) ──
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

    // ── Agent runs (tool calls, approvals, done summaries) ──
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

          // HITL questions are conversation — the user interacts with them
          if (toolName.includes('hitl_ask')) {
            const q = tc.arguments?.question || tc.arguments?.message || ''
            const choices = tc.arguments?.choices
            lines.push(`### ${agentName}  —  ${runTime}\n`)
            lines.push(`${q}\n`)
            if (choices?.length) {
              for (const c of choices) lines.push(`- ${c}`)
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

          // Everything below is agent output — rendered as blockquotes
          if (tc.approval) {
            const path = tc.arguments?.path || ''
            const status = tc.approval.status || 'pending'
            const reason = tc.approval.reason || ''
            lines.push(`> **${agentName}** *(${runTime})* — approval gate (${status})`)
            if (path) lines.push(`> File: \`${path}\``)
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
  const { marked } = await import('marked')
  const html = marked.parse(markdownContent)

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
    await downloadElementAsPdf(container.firstElementChild, path)
  } finally {
    document.body.removeChild(container)
  }
}
