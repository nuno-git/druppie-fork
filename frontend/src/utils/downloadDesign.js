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
