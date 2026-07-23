/**
 * Documentation Page - Browse documentation for all platform components
 *
 * Two views (tab-toggled):
 *   - Platform: ADRs / PRDs / Specs / Research / Guides from docs/ tree
 *     (served by GET /api/documentation/platform)
 *   - Applications: per-project docs/documentation.md from Gitea repos
 *     (served by GET /api/documentation)
 */

import { useMemo, useState, useEffect, useRef } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import {
  BookOpen, AlertCircle, Loader2, ChevronDown, ChevronRight, FileText,
  Puzzle, Bot, Cable, Wrench, Search, Filter, FolderTree, Boxes,
  Scale, FileCheck2, FlaskConical, Map, ScrollText, ArrowLeft, Link2,
} from 'lucide-react'
import { getDocumentation, getPlatformDocumentation } from '../services/api'
import PageHeader from '../components/shared/PageHeader'
import CodeBlock from '../components/CodeBlock'
import MermaidBlock from '../components/MermaidBlock'

// ─── Markdown rendering (shared) ────────────────────────────────────────────

/**
 * Strip a leading ``---\n...\n---`` YAML frontmatter block from a markdown
 * string. The backend returns the full file (frontmatter included) per the
 * API contract; react-markdown has no remark-frontmatter plugin, so without
 * stripping this the YAML keys render as visible body text.
 */
const stripFrontmatter = (text) => {
  if (!text.startsWith('---')) return text
  // Closing delimiter: a line containing only ``---`` (tolerant of CRLF/whitespace).
  const match = /\r?\n---\s*(\r?\n|$)/.exec(text)
  if (!match) return text
  return text.slice(match.index + match[0].length)
}

const docComponents = {
  pre({ children }) {
    return <div className="my-2">{children}</div>
  },
  code({ className, children }) {
    const match = /language-(\w+)/.exec(className || '')
    const codeString = String(children).replace(/\n$/, '')
    if (match && match[1] === 'mermaid') {
      return <MermaidBlock code={codeString} />
    }
    if (match || codeString.includes('\n')) {
      return <CodeBlock
        code={codeString}
        language={match ? match[1] : 'text'}
        showLineNumbers={codeString.split('\n').length > 10}
      />
    }
    return <code className="px-1.5 py-0.5 bg-gray-100 text-gray-800 rounded text-xs font-mono">{children}</code>
  },
  table({ children }) {
    return <div className="overflow-x-auto my-4">
      <table className="min-w-full text-sm border border-gray-200 rounded-lg overflow-hidden">{children}</table>
    </div>
  },
  thead({ children }) {
    return <thead className="bg-gray-50">{children}</thead>
  },
  th({ children }) {
    return <th className="px-3 py-2 text-left text-xs font-semibold text-gray-600 uppercase tracking-wide border-b border-gray-200">{children}</th>
  },
  td({ children }) {
    return <td className="px-3 py-2 text-sm text-gray-700 border-b border-gray-100">{children}</td>
  },
  h1({ children }) {
    return <h1 className="text-2xl font-bold text-gray-900 mt-8 mb-4 pb-2 border-b border-gray-200">{children}</h1>
  },
  h2({ children }) {
    return <h2 className="text-xl font-semibold text-gray-900 mt-8 mb-3 pb-1.5 border-b border-gray-100">{children}</h2>
  },
  h3({ children }) {
    return <h3 className="text-lg font-semibold text-gray-900 mt-6 mb-2">{children}</h3>
  },
  p({ children }) {
    return <p className="text-sm text-gray-700 leading-relaxed mb-3">{children}</p>
  },
  ul({ children }) {
    return <ul className="list-disc list-outside ml-5 mb-3 space-y-1 text-sm text-gray-700">{children}</ul>
  },
  ol({ children }) {
    return <ol className="list-decimal list-outside ml-5 mb-3 space-y-1 text-sm text-gray-700">{children}</ol>
  },
  li({ children }) {
    return <li className="leading-relaxed">{children}</li>
  },
  blockquote({ children }) {
    return <blockquote className="border-l-4 border-blue-300 bg-blue-50/50 pl-4 py-2 my-3 text-sm text-gray-700 italic rounded-r">{children}</blockquote>
  },
  hr() {
    return <hr className="my-6 border-gray-200"/>
  },
  a({ href, children }) {
    return <a href={href} className="text-blue-600 hover:text-blue-800 underline decoration-blue-300" target="_blank" rel="noopener noreferrer">{children}</a>
  },
  strong({ children }) {
    return <strong className="font-semibold text-gray-900">{children}</strong>
  },
}

// ─── Type / status visual config ────────────────────────────────────────────
// Centralized so every badge in the page uses the same colour for a given type.

const TYPE_CONFIG = {
  adr:      { label: 'ADR',      long: 'Architecture Decision Record', Icon: Scale,        badge: 'bg-blue-50 text-blue-700 ring-blue-200',       dot: 'bg-blue-500'    },
  prd:      { label: 'PRD',      long: 'Product Requirements Doc',     Icon: FileCheck2,   badge: 'bg-purple-50 text-purple-700 ring-purple-200', dot: 'bg-purple-500'  },
  spec:     { label: 'SPEC',     long: 'Executable Spec (Gherkin)',    Icon: ScrollText,   badge: 'bg-cyan-50 text-cyan-700 ring-cyan-200',       dot: 'bg-cyan-500'    },
  research: { label: 'RESEARCH', long: 'Research Note',                Icon: FlaskConical, badge: 'bg-orange-50 text-orange-700 ring-orange-200', dot: 'bg-orange-500'  },
  guide:    { label: 'GUIDE',    long: 'Guide',                        Icon: Map,          badge: 'bg-teal-50 text-teal-700 ring-teal-200',       dot: 'bg-teal-500'    },
}

const STATUS_CONFIG = {
  accepted:    { label: 'Accepted',    cls: 'bg-emerald-50 text-emerald-700 ring-emerald-200',     dot: 'bg-emerald-500' },
  implemented: { label: 'Implemented', cls: 'bg-emerald-50 text-emerald-700 ring-emerald-200',     dot: 'bg-emerald-500' },
  approved:    { label: 'Approved',    cls: 'bg-emerald-50 text-emerald-700 ring-emerald-200',     dot: 'bg-emerald-500' },
  complete:    { label: 'Complete',    cls: 'bg-emerald-50 text-emerald-700 ring-emerald-200',     dot: 'bg-emerald-500' },
  proposed:    { label: 'Proposed',    cls: 'bg-amber-50 text-amber-700 ring-amber-200',           dot: 'bg-amber-500'   },
  draft:       { label: 'Draft',       cls: 'bg-amber-50 text-amber-700 ring-amber-200',           dot: 'bg-amber-500'   },
  superseded:  { label: 'Superseded',  cls: 'bg-gray-100 text-gray-600 ring-gray-200',             dot: 'bg-gray-400'    },
  deprecated:  { label: 'Deprecated',  cls: 'bg-gray-100 text-gray-600 ring-gray-200',             dot: 'bg-gray-400'    },
}

const statusConfig = (status) => STATUS_CONFIG[status?.toLowerCase()] || null

// ─── Small presentational helpers ───────────────────────────────────────────

const TypeBadge = ({ type }) => {
  const cfg = TYPE_CONFIG[type]
  if (!cfg) return null
  const { Icon } = cfg
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-xs font-semibold ring-1 ring-inset ${cfg.badge}`}>
      <Icon className="w-3 h-3" />
      {cfg.label}
    </span>
  )
}

const StatusBadge = ({ status }) => {
  const cfg = statusConfig(status)
  if (!cfg) return null
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-xs font-medium ring-1 ring-inset ${cfg.cls}`}>
      <span className={`w-1.5 h-1.5 rounded-full ${cfg.dot}`} />
      {cfg.label}
    </span>
  )
}

const IdBadge = ({ type, id }) => {
  if (!id) return null
  const cfg = TYPE_CONFIG[type] || {}
  return (
    <span className="inline-flex items-center px-2 py-0.5 rounded-md text-xs font-mono bg-gray-900 text-gray-100">
      {cfg.label || type.toUpperCase()} {id}
    </span>
  )
}

// ─── Platform doc list item (clickable → detail page) ──────────────────────

const PlatformDocListItem = ({ entry, onOpen }) => {
  const cfg = TYPE_CONFIG[entry.type] || {}
  return (
    <button
      onClick={onOpen}
      className="group w-full text-left p-4 border border-gray-200 rounded-xl bg-white hover:border-blue-300 hover:shadow-md transition-all"
    >
      <div className="flex items-start gap-3 min-w-0">
        <span className={`mt-0.5 flex-shrink-0 w-8 h-8 rounded-lg ${cfg.badge} ring-1 ring-inset flex items-center justify-center`}>
          <cfg.Icon className="w-4 h-4" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2 mb-1">
            <IdBadge type={entry.type} id={entry.id} />
            <TypeBadge type={entry.type} />
            {entry.status && <StatusBadge status={entry.status} />}
          </div>
          <h3 className="font-semibold text-gray-900 leading-snug truncate group-hover:text-blue-700 transition-colors">
            {entry.title}
          </h3>
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 mt-1 text-xs text-gray-500">
            {entry.author_or_deciders && <span>by {entry.author_or_deciders}</span>}
            {entry.date && <span>{entry.date}</span>}
            <span className="font-mono text-gray-400">{entry.filename}</span>
          </div>
        </div>
        <ChevronRight className="flex-shrink-0 w-4 h-4 text-gray-300 mt-1 group-hover:text-blue-500 group-hover:translate-x-0.5 transition-all" />
      </div>
    </button>
  )
}

// Resolve a `linked_*` path (e.g. "docs/adrs/002-foo.md") to a
// { type, filename } pair so the detail view can build a navigation URL.
// Returns null if the path is unrecognised.
const parseLinkedPath = (path) => {
  if (!path || typeof path !== 'string') return null
  const segs = path.split('/')
  const filename = segs[segs.length - 1]
  const dir = segs.length > 1 ? segs[segs.length - 2] : ''
  let type
  if (dir === 'adrs' || filename.toLowerCase().endsWith('.md') && /^adr/i.test(dir)) type = 'adr'
  else if (dir === 'prds') type = 'prd'
  else if (dir === 'specs') type = 'spec'
  else if (dir === 'research') type = 'research'
  else if (dir === 'guides') type = 'guide'
  else if (filename.toLowerCase().endsWith('.feature')) type = 'spec'
  if (!type) return null
  return { type, filename }
}

const LinkedChip = ({ label, path, onClick }) => {
  const fname = path?.split('/').pop() || path
  const Comp = onClick ? 'button' : 'span'
  return (
    <Comp
      onClick={onClick}
      className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-mono bg-gray-100 text-gray-700 ring-1 ring-inset ring-gray-200 ${
        onClick ? 'hover:bg-blue-50 hover:text-blue-700 hover:ring-blue-200 cursor-pointer transition-colors' : ''
      }`}
      title={path}
    >
      <span className="font-sans font-semibold text-gray-500">{label}:</span>
      {fname}
    </Comp>
  )
}

// ─── Empty / error states ───────────────────────────────────────────────────

const EmptyState = ({ icon: IconCmp, title, description }) => (
  <div className="flex flex-col items-center justify-center py-16 text-gray-400 border-2 border-dashed border-gray-200 rounded-xl bg-gray-50/50">
    <IconCmp className="w-10 h-10 mb-3 text-gray-300" />
    <p className="text-base font-medium text-gray-500">{title}</p>
    <p className="text-sm mt-1">{description}</p>
  </div>
)

// Legacy: kept for the Applications tab.
const LegacyDocCard = ({ entry }) => {
  const [expanded, setExpanded] = useState(false)
  const IconCmp = expanded ? ChevronDown : ChevronRight
  return (
    <div className="border border-gray-200 rounded-xl bg-white overflow-hidden">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between p-4 hover:bg-gray-50 transition-colors"
      >
        <div className="flex items-center gap-2">
          <FileText className="w-4 h-4 text-blue-500" />
          <span className="font-medium text-gray-900">{entry.title}</span>
        </div>
        <span className="text-gray-400"><IconCmp className="w-4 h-4" /></span>
      </button>
      {expanded && (
        <div className="border-t border-gray-100 p-6 bg-white max-w-none">
          <ReactMarkdown remarkPlugins={[remarkGfm]} components={docComponents}>
            {stripFrontmatter(entry.content)}
          </ReactMarkdown>
        </div>
      )}
    </div>
  )
}

// ─── Filter bar ─────────────────────────────────────────────────────────────

const TYPE_FILTERS = [
  { key: 'all',      label: 'All',      Icon: Boxes },
  { key: 'adr',      label: 'ADRs',     Icon: Scale },
  { key: 'prd',      label: 'PRDs',     Icon: FileCheck2 },
  { key: 'spec',     label: 'Specs',    Icon: ScrollText },
  { key: 'research', label: 'Research', Icon: FlaskConical },
  { key: 'guide',    label: 'Guides',   Icon: Map },
]

const FilterBar = ({
  typeFilter, setTypeFilter,
  statusFilter, setStatusFilter, statuses,
  query, setQuery,
  counts,
}) => (
  <div className="space-y-3">
    {/* Type toggle row */}
    <div className="flex flex-wrap items-center gap-2">
      {TYPE_FILTERS.map(({ key, label, Icon }) => {
        const active = typeFilter === key
        const count = key === 'all' ? counts.total : (counts.byType[key] || 0)
        return (
          <button
            key={key}
            onClick={() => setTypeFilter(key)}
            className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ring-1 ring-inset ${
              active
                ? 'bg-gray-900 text-white ring-gray-900'
                : 'bg-white text-gray-700 ring-gray-200 hover:bg-gray-50'
            }`}
          >
            <Icon className="w-3.5 h-3.5" />
            {label}
            <span className={`ml-1 px-1.5 py-0.5 rounded text-xs font-mono ${
              active ? 'bg-white/20 text-white' : 'bg-gray-100 text-gray-500'
            }`}>{count}</span>
          </button>
        )
      })}
    </div>

    {/* Search + status row */}
    <div className="flex flex-wrap items-center gap-3">
      <div className="relative flex-1 min-w-[220px] max-w-md">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400 pointer-events-none" />
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search by title, id, or filename..."
          className="w-full pl-9 pr-3 py-2 text-sm rounded-lg border border-gray-200 bg-white focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
        />
      </div>
      <div className="flex items-center gap-2">
        <Filter className="w-4 h-4 text-gray-400" />
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="text-sm rounded-lg border border-gray-200 bg-white py-2 pl-3 pr-8 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
        >
          <option value="all">All statuses</option>
          {statuses.map((s) => (
            <option key={s} value={s}>{STATUS_CONFIG[s]?.label || s}</option>
          ))}
        </select>
      </div>
    </div>
  </div>
)

// ─── Main page (list view) ──────────────────────────────────────────────────

const Documentation = () => {
  const navigate = useNavigate()
  const [activeTab, setActiveTab] = useState('platform')
  const [typeFilter, setTypeFilter] = useState('all')
  const [statusFilter, setStatusFilter] = useState('all')
  const [query, setQuery] = useState('')

  const platformQ = useQuery({
    queryKey: ['documentation-platform'],
    queryFn: getPlatformDocumentation,
    refetchInterval: 60000,
  })
  const appsQ = useQuery({
    queryKey: ['documentation'],
    queryFn: getDocumentation,
    refetchInterval: 60000,
  })

  const platformDocs = platformQ.data || []

  // Derive status list + counts once per data change.
  const statuses = useMemo(() => {
    const s = new Set()
    for (const d of platformDocs) if (d.status) s.add(d.status)
    return Array.from(s).sort()
  }, [platformDocs])

  const counts = useMemo(() => {
    const byType = {}
    for (const d of platformDocs) byType[d.type] = (byType[d.type] || 0) + 1
    return { total: platformDocs.length, byType }
  }, [platformDocs])

  // Apply all filters client-side.
  const filteredDocs = useMemo(() => {
    const q = query.trim().toLowerCase()
    return platformDocs.filter((d) => {
      if (typeFilter !== 'all' && d.type !== typeFilter) return false
      if (statusFilter !== 'all' && (d.status || '') !== statusFilter) return false
      if (q) {
        const hay = `${d.title || ''} ${d.id || ''} ${d.filename || ''} ${d.author_or_deciders || ''}`.toLowerCase()
        if (!hay.includes(q)) return false
      }
      return true
    })
  }, [platformDocs, typeFilter, statusFilter, query])

  const openDetail = (entry) => {
    const docId = encodeURIComponent(entry.filename)
    navigate(`/documentation/${entry.type}/${docId}`)
  }

  const apps = appsQ.data || []
  const isLoading = activeTab === 'platform' ? platformQ.isLoading : appsQ.isLoading
  const isError  = activeTab === 'platform' ? platformQ.isError  : appsQ.isError
  const error    = activeTab === 'platform' ? platformQ.error    : appsQ.error
  const refetch  = activeTab === 'platform' ? platformQ.refetch  : appsQ.refetch

  return (
    <div className="space-y-6">
      <PageHeader
        title="Documentation Portal"
        subtitle="ADRs, PRDs, Specs, Research, Guides — plus per-project application docs"
      >
        <span className="text-sm text-gray-500">{counts.total} platform docs</span>
      </PageHeader>

      {/* Tabs */}
      <div className="flex items-center gap-1 border-b border-gray-200">
        <TabButton
          active={activeTab === 'platform'}
          onClick={() => setActiveTab('platform')}
          Icon={FolderTree}
          label="Platform Docs"
          count={platformDocs.length}
        />
        <TabButton
          active={activeTab === 'applications'}
          onClick={() => setActiveTab('applications')}
          Icon={BookOpen}
          label="Applications"
          count={apps.length}
        />
      </div>

      {isLoading ? (
        <div className="flex items-center justify-center h-64">
          <Loader2 className="w-8 h-8 animate-spin text-gray-400" />
        </div>
      ) : isError ? (
        <div className="flex flex-col items-center justify-center h-64 text-red-500">
          <AlertCircle className="w-12 h-12 mb-2" />
          <p className="text-lg font-medium">Failed to load documentation</p>
          <p className="text-sm text-red-400">{error?.message || 'An unexpected error occurred'}</p>
          <button
            onClick={() => refetch()}
            className="mt-4 px-4 py-2 bg-blue-500 text-white rounded-lg hover:bg-blue-600 transition-colors"
          >Retry</button>
        </div>
      ) : activeTab === 'platform' ? (
        <div className="space-y-5">
          <FilterBar
            typeFilter={typeFilter} setTypeFilter={setTypeFilter}
            statusFilter={statusFilter} setStatusFilter={setStatusFilter}
            statuses={statuses}
            query={query} setQuery={setQuery}
            counts={counts}
          />
          {filteredDocs.length === 0 ? (
            <EmptyState
              icon={FolderTree}
              title="No documents match your filters"
              description={platformDocs.length === 0
                ? 'No platform documents found. Check that docs/ is mounted into the backend container.'
                : 'Try clearing the search or selecting "All" for type and status.'}
            />
          ) : (
            <>
              <p className="text-sm text-gray-500">
                Showing <span className="font-medium text-gray-700">{filteredDocs.length}</span> of {platformDocs.length} documents
              </p>
              <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
                {filteredDocs.map((entry, idx) => (
                  <PlatformDocListItem
                    key={`${entry.type}-${entry.id || entry.filename}-${idx}`}
                    entry={entry}
                    onOpen={() => openDetail(entry)}
                  />
                ))}
              </div>
            </>
          )}
        </div>
      ) : (
        // Applications tab — preserves the legacy Gitea-docs view
        <div className="space-y-6">
          <div className="space-y-3">
            <div className="flex items-center gap-2 border-b border-gray-200 pb-2">
              <BookOpen className="w-5 h-5 text-gray-500" />
              <h2 className="text-lg font-semibold text-gray-800">Applications</h2>
            </div>
            {apps.length > 0 ? (
              <div className="space-y-3">
                {apps.map((e) => <LegacyDocCard key={e.source_id} entry={e} />)}
              </div>
            ) : (
              <EmptyState
                icon={BookOpen}
                title="No application documentation"
                description="Create an application with a docs/documentation.md file to see it here."
              />
            )}
          </div>
          {/* Preserve the empty placeholders so the page shape is unchanged. */}
          <EmptySection title="Agents" icon={Bot} description="No agent documentation yet." />
          <EmptySection title="Modules" icon={Puzzle} description="No module documentation yet." />
          <EmptySection title="MCPs" icon={Cable} description="No MCP documentation yet." />
          <EmptySection title="Tools" icon={Wrench} description="No tool documentation yet." />
        </div>
      )}
    </div>
  )
}

const TabButton = ({ active, onClick, Icon, label, count }) => (
  <button
    onClick={onClick}
    className={`inline-flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 -mb-px transition-colors ${
      active
        ? 'border-blue-500 text-blue-600'
        : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
    }`}
  >
    <Icon className="w-4 h-4" />
    {label}
    <span className="ml-1 px-1.5 py-0.5 rounded text-xs font-mono bg-gray-100 text-gray-600">{count}</span>
  </button>
)

const EmptySection = ({ title, icon: IconCmp, description }) => (
  <div className="space-y-3">
    <div className="flex items-center gap-2 border-b border-gray-200 pb-2">
      <IconCmp className="w-5 h-5 text-gray-500" />
      <h2 className="text-lg font-semibold text-gray-800">{title}</h2>
    </div>
    <EmptyState icon={IconCmp} title={`No ${title.toLowerCase()} documentation yet`} description={description} />
  </div>
)

// ─── Documentation detail page (full-bleed) ─────────────────────────────────
//
// Renders a single document full-width (NavRail still visible). Used by the
// /documentation/:docType/:docId route which lives outside the max-w-7xl padded
// wrapper, so doc content is allowed to use the full available reading width.
//
// The doc is looked up from the cached platform-docs list; on direct-URL access
// (no cached list yet) we fetch the full list and pick the matching entry.

const DetailNotFound = ({ onBack }) => (
  <div className="min-h-[60vh] flex flex-col items-center justify-center text-center px-6">
    <AlertCircle className="w-12 h-12 text-amber-500 mb-4" />
    <h2 className="text-xl font-bold text-gray-900 mb-1">Document not found</h2>
    <p className="text-sm text-gray-500 mb-6">
      The document you're looking for doesn't exist or hasn't been indexed.
    </p>
    <button
      onClick={onBack}
      className="inline-flex items-center gap-2 px-4 py-2 bg-gray-900 text-white rounded-lg hover:bg-gray-700 transition-colors"
    >
      <ArrowLeft className="w-4 h-4" />
      Back to Documentation
    </button>
  </div>
)

const DetailError = ({ message, onBack }) => (
  <div className="min-h-[60vh] flex flex-col items-center justify-center text-center px-6">
    <AlertCircle className="w-12 h-12 text-red-500 mb-4" />
    <h2 className="text-xl font-bold text-gray-900 mb-1">Failed to load document</h2>
    <p className="text-sm text-red-400 mb-6">{message || 'An unexpected error occurred'}</p>
    <button
      onClick={onBack}
      className="inline-flex items-center gap-2 px-4 py-2 bg-gray-900 text-white rounded-lg hover:bg-gray-700 transition-colors"
    >
      <ArrowLeft className="w-4 h-4" />
      Back to Documentation
    </button>
  </div>
)

export const DocumentationDetail = () => {
  const { docType, docId } = useParams()
  const navigate = useNavigate()
  const contentRef = useRef(null)

  const decodedFilename = docId ? decodeURIComponent(docId) : ''

  const platformQ = useQuery({
    queryKey: ['documentation-platform'],
    queryFn: getPlatformDocumentation,
    refetchInterval: 60000,
  })

  const platformDocs = platformQ.data || []
  const entry = platformDocs.find((d) => d.type === docType && d.filename === decodedFilename)

  // Scroll to top whenever the targeted doc changes (e.g. following a linked chip).
  useEffect(() => {
    if (contentRef.current) contentRef.current.scrollTop = 0
    window.scrollTo({ top: 0 })
  }, [docType, docId])

  const handleBack = () => navigate('/documentation')

  const goToLinked = (path) => {
    const parsed = parseLinkedPath(path)
    if (!parsed) return
    navigate(`/documentation/${parsed.type}/${encodeURIComponent(parsed.filename)}`)
  }

  if (platformQ.isLoading) {
    return (
      <div className="flex items-center justify-center h-[60vh]">
        <Loader2 className="w-8 h-8 animate-spin text-gray-400" />
      </div>
    )
  }

  if (platformQ.isError) {
    return <DetailError message={platformQ.error?.message} onBack={handleBack} />
  }

  if (!entry) {
    return <DetailNotFound onBack={handleBack} />
  }

  const isSpec = entry.type === 'spec'
  const cfg = TYPE_CONFIG[entry.type] || {}
  const hasLinks = entry.linked_prd || entry.linked_research || entry.linked_adrs?.length || entry.linked_specs?.length

  return (
    <div className="min-h-full bg-gray-50">
      <div className="sticky top-0 z-10 bg-white/95 backdrop-blur border-b border-gray-200">
        <div className="max-w-6xl mx-auto px-6 sm:px-8 lg:px-12 py-4">
          <button
            onClick={handleBack}
            className="inline-flex items-center gap-1.5 text-sm text-gray-600 hover:text-blue-700 transition-colors mb-3 -ml-1"
          >
            <ArrowLeft className="w-4 h-4" />
            Back to Documentation
          </button>
          <div className="flex flex-wrap items-center gap-2 mb-3">
            <IdBadge type={entry.type} id={entry.id} />
            <TypeBadge type={entry.type} />
            {entry.status && <StatusBadge status={entry.status} />}
          </div>
          <h1 className="text-3xl font-bold text-gray-900 leading-tight mb-2">{entry.title}</h1>
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-gray-500">
            {entry.author_or_deciders && (
              <span className="flex items-center gap-1">
                <span className="font-medium text-gray-700">{entry.author_or_deciders}</span>
              </span>
            )}
            {entry.date && <span>{entry.date}</span>}
            <span className="font-mono text-xs text-gray-400">{entry.filename}</span>
          </div>
        </div>
      </div>

      <div ref={contentRef} className="max-w-6xl mx-auto px-6 sm:px-8 lg:px-12 py-8">
        {hasLinks && (
          <div className="flex flex-wrap items-center gap-2 mb-8 p-4 bg-white rounded-xl border border-gray-200">
            <Link2 className="w-4 h-4 text-gray-400 flex-shrink-0" />
            <span className="text-xs font-semibold text-gray-500 uppercase tracking-wide mr-1">Linked</span>
            {entry.linked_prd && (
              <LinkedChip label="PRD" path={entry.linked_prd} onClick={() => goToLinked(entry.linked_prd)} />
            )}
            {entry.linked_research && (
              <LinkedChip label="Research" path={entry.linked_research} onClick={() => goToLinked(entry.linked_research)} />
            )}
            {entry.linked_adrs?.map((p, i) => (
              <LinkedChip key={`adr-${i}`} label="ADR" path={p} onClick={() => goToLinked(p)} />
            ))}
            {entry.linked_specs?.map((p, i) => (
              <LinkedChip key={`spec-${i}`} label="Spec" path={p} onClick={() => goToLinked(p)} />
            ))}
          </div>
        )}

        <div className="bg-white rounded-xl border border-gray-200 px-6 sm:px-8 lg:px-10 py-8">
          {isSpec ? (
            <CodeBlock
              code={entry.content}
              language="gherkin"
              filename={entry.filename}
              showLineNumbers={entry.content.split('\n').length > 10}
            />
          ) : (
            <div className="markdown-content max-w-none prose prose-gray max-w-none">
              <ReactMarkdown remarkPlugins={[remarkGfm]} components={docComponents}>
                {stripFrontmatter(entry.content)}
              </ReactMarkdown>
            </div>
          )}
        </div>

        <div className="mt-8 pt-6 border-t border-gray-200">
          <button
            onClick={handleBack}
            className="inline-flex items-center gap-2 px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-200 rounded-lg hover:border-blue-300 hover:text-blue-700 hover:shadow-sm transition-all"
          >
            <ArrowLeft className="w-4 h-4" />
            Back to Documentation
          </button>
        </div>
      </div>
    </div>
  )
}

export default Documentation
