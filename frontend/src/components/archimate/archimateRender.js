/**
 * Shared resolver for ```archimate code blocks → SVG string.
 *
 * Used by both ArchimateBlock (chat) and the PDF export (downloadDesign.js)
 * so they render identically. Sources the .archimate XML from the session
 * workspace first (the architect's commit may not have reached Gitea yet
 * during an approval preview) and falls back to the Gitea ref.
 *
 * The returned SVG uses native <text> labels (no <foreignObject>), so it
 * survives the browser's image-context sandbox when rasterised for a PDF.
 */

import { getProjectFile, getProjectFileFromWorkspace, getProjectFileChanges } from '../../services/api'
import { parseEmbedSpec, parseArchimateXML, computeLayout, renderViewToSVG } from './archimateParser'

/**
 * Resolve an archimate embed spec to an SVG string.
 *
 * @param {string} code  the code-block body (`view-id:` / `file:` spec)
 * @param {{id:string, default_branch?:string, session_id?:string}} repo
 * @param {{highlightIds?:Iterable<string>}} [opts]
 * @returns {Promise<{svg:string, viewName:string, changeCount:number, lastCommitMessage?:string}>}
 */
export async function renderArchimateSpecToSvg(code, repo, opts = {}) {
  const spec = parseEmbedSpec(code)
  if (!spec) throw new Error('Missing view-id in code block')
  if (!repo?.id) throw new Error('No project context — open this TD inside a project session')

  const branch = repo.default_branch || 'main'

  const fetchArchimateFile = async () => {
    if (repo.session_id) {
      try {
        return await getProjectFileFromWorkspace(repo.id, repo.session_id, spec.file)
      } catch (err) {
        if (err.status && err.status !== 404) throw err
      }
    }
    return getProjectFile(repo.id, spec.file, branch)
  }

  const [response, changes] = await Promise.all([
    fetchArchimateFile(),
    getProjectFileChanges(repo.id, spec.file, branch).catch(() => null),
  ])
  const xml = response?.content ?? response
  if (typeof xml !== 'string') {
    throw new Error('Unexpected response shape from project file API')
  }

  const model = parseArchimateXML(xml)
  const view = model.views.get(spec.viewId)
  if (!view) throw new Error(`View '${spec.viewId}' not found in ${spec.file}`)

  const laidOut = await computeLayout(view)
  const deltaIds = new Set([
    ...(opts.highlightIds || []),
    ...((changes?.added_identifiers) || []),
  ])
  const svg = renderViewToSVG(laidOut, model, {
    highlightIds: deltaIds.size ? deltaIds : undefined,
  })

  return {
    svg,
    viewName: view.name,
    changeCount: (changes?.added_identifiers || []).length,
    lastCommitMessage: changes?.last_commit_message,
  }
}
