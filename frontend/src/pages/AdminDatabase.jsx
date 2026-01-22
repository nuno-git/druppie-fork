/**
 * Admin Database Viewer Page
 *
 * Allows admins to view and explore database tables with pagination,
 * search, and expandable row details.
 */

import React, { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  Database,
  ChevronDown,
  ChevronRight,
  Search,
  RefreshCw,
  AlertCircle,
  Loader2,
  ChevronLeft,
  ChevronsLeft,
  ChevronsRight,
} from 'lucide-react'
import {
  getAdminStats,
  getAdminSessions,
  getAdminApprovals,
  getAdminProjects,
  getAdminWorkspaces,
  getAdminHitlQuestions,
  getAdminBuilds,
} from '../services/api'

// Table configuration with display names and fetch functions
const TABLES = {
  sessions: {
    label: 'Sessions',
    fetch: getAdminSessions,
    columns: ['id', 'user_id', 'status', 'project_id', 'created_at'],
    expandableField: 'state',
    statusField: 'status',
    statusOptions: ['active', 'paused', 'completed', 'failed'],
  },
  approvals: {
    label: 'Approvals',
    fetch: getAdminApprovals,
    columns: ['id', 'tool_name', 'status', 'danger_level', 'agent_id', 'created_at'],
    expandableField: 'arguments',
    statusField: 'status',
    statusOptions: ['pending', 'approved', 'rejected'],
  },
  projects: {
    label: 'Projects',
    fetch: getAdminProjects,
    columns: ['id', 'name', 'repo_name', 'status', 'owner_id', 'created_at'],
    expandableField: 'description',
    statusField: 'status',
    statusOptions: ['active', 'archived'],
  },
  workspaces: {
    label: 'Workspaces',
    fetch: getAdminWorkspaces,
    columns: ['id', 'session_id', 'project_id', 'branch', 'local_path', 'created_at'],
    expandableField: 'local_path',
    statusField: null,
    statusOptions: [],
  },
  hitl_questions: {
    label: 'HITL Questions',
    fetch: getAdminHitlQuestions,
    columns: ['id', 'agent_id', 'question', 'status', 'answer', 'created_at'],
    expandableField: 'choices',
    statusField: 'status',
    statusOptions: ['pending', 'answered', 'expired'],
  },
  builds: {
    label: 'Builds',
    fetch: getAdminBuilds,
    columns: ['id', 'project_id', 'branch', 'status', 'container_name', 'created_at'],
    expandableField: 'build_logs',
    statusField: 'status',
    statusOptions: ['pending', 'building', 'running', 'stopped', 'failed'],
  },
}

// Status badge colors
const STATUS_COLORS = {
  active: 'bg-green-100 text-green-700',
  completed: 'bg-blue-100 text-blue-700',
  paused: 'bg-yellow-100 text-yellow-700',
  failed: 'bg-red-100 text-red-700',
  pending: 'bg-yellow-100 text-yellow-700',
  approved: 'bg-green-100 text-green-700',
  rejected: 'bg-red-100 text-red-700',
  answered: 'bg-green-100 text-green-700',
  expired: 'bg-gray-100 text-gray-700',
  archived: 'bg-gray-100 text-gray-700',
  building: 'bg-blue-100 text-blue-700',
  running: 'bg-green-100 text-green-700',
  stopped: 'bg-gray-100 text-gray-700',
  low: 'bg-green-100 text-green-700',
  medium: 'bg-yellow-100 text-yellow-700',
  high: 'bg-orange-100 text-orange-700',
  critical: 'bg-red-100 text-red-700',
}

// Truncate long strings for display
const truncate = (str, maxLen = 40) => {
  if (!str) return '-'
  const s = String(str)
  return s.length > maxLen ? s.substring(0, maxLen) + '...' : s
}

// Format dates for display
const formatDate = (dateStr) => {
  if (!dateStr) return '-'
  try {
    return new Date(dateStr).toLocaleString()
  } catch {
    return dateStr
  }
}

// Status badge component
const StatusBadge = ({ status }) => {
  if (!status) return <span>-</span>
  const colorClass = STATUS_COLORS[status] || 'bg-gray-100 text-gray-700'
  return (
    <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${colorClass}`}>
      {status}
    </span>
  )
}

// Expandable row component
const ExpandableRow = ({ item, columns, expandableField, isExpanded, onToggle }) => {
  const hasExpandableData = item[expandableField] !== null && item[expandableField] !== undefined

  return (
    <>
      <tr
        className={`border-b border-gray-100 hover:bg-gray-50 cursor-pointer ${
          isExpanded ? 'bg-blue-50' : ''
        }`}
        onClick={onToggle}
      >
        <td className="px-4 py-3 w-8">
          {hasExpandableData ? (
            isExpanded ? (
              <ChevronDown className="w-4 h-4 text-gray-500" />
            ) : (
              <ChevronRight className="w-4 h-4 text-gray-500" />
            )
          ) : (
            <span className="w-4 h-4 inline-block" />
          )}
        </td>
        {columns.map((col) => (
          <td key={col} className="px-4 py-3 text-sm">
            {col === 'status' || col === 'danger_level' ? (
              <StatusBadge status={item[col]} />
            ) : col.endsWith('_at') ? (
              formatDate(item[col])
            ) : col === 'id' ? (
              <code className="text-xs bg-gray-100 px-1 py-0.5 rounded font-mono">
                {truncate(item[col], 12)}
              </code>
            ) : (
              truncate(item[col])
            )}
          </td>
        ))}
      </tr>
      {isExpanded && hasExpandableData && (
        <tr className="bg-gray-50 border-b border-gray-200">
          <td colSpan={columns.length + 1} className="px-4 py-3">
            <div className="text-sm">
              <div className="font-medium text-gray-700 mb-2">
                {expandableField.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())}:
              </div>
              <pre className="bg-white border border-gray-200 rounded p-3 overflow-x-auto text-xs max-h-96 overflow-y-auto">
                {typeof item[expandableField] === 'object'
                  ? JSON.stringify(item[expandableField], null, 2)
                  : String(item[expandableField])}
              </pre>
            </div>
          </td>
        </tr>
      )}
    </>
  )
}

// Pagination component
const Pagination = ({ pagination, onPageChange }) => {
  if (!pagination || pagination.total_pages <= 1) return null

  const { page, total_pages, total } = pagination

  return (
    <div className="flex items-center justify-between px-4 py-3 bg-gray-50 border-t border-gray-200">
      <div className="text-sm text-gray-600">
        Page {page} of {total_pages} ({total} total records)
      </div>
      <div className="flex items-center gap-1">
        <button
          onClick={() => onPageChange(1)}
          disabled={page === 1}
          className="p-1 rounded hover:bg-gray-200 disabled:opacity-50 disabled:cursor-not-allowed"
          title="First page"
        >
          <ChevronsLeft className="w-4 h-4" />
        </button>
        <button
          onClick={() => onPageChange(page - 1)}
          disabled={page === 1}
          className="p-1 rounded hover:bg-gray-200 disabled:opacity-50 disabled:cursor-not-allowed"
          title="Previous page"
        >
          <ChevronLeft className="w-4 h-4" />
        </button>
        <span className="px-3 py-1 text-sm">{page}</span>
        <button
          onClick={() => onPageChange(page + 1)}
          disabled={page === total_pages}
          className="p-1 rounded hover:bg-gray-200 disabled:opacity-50 disabled:cursor-not-allowed"
          title="Next page"
        >
          <ChevronRight className="w-4 h-4" />
        </button>
        <button
          onClick={() => onPageChange(total_pages)}
          disabled={page === total_pages}
          className="p-1 rounded hover:bg-gray-200 disabled:opacity-50 disabled:cursor-not-allowed"
          title="Last page"
        >
          <ChevronsRight className="w-4 h-4" />
        </button>
      </div>
    </div>
  )
}

// Table view component
const TableView = ({ tableKey, config }) => {
  const [page, setPage] = useState(1)
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [expandedRows, setExpandedRows] = useState(new Set())
  const [searchInput, setSearchInput] = useState('')

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ['admin', tableKey, page, search, statusFilter],
    queryFn: () => config.fetch(page, 20, statusFilter || null, search || null),
  })

  const handleSearch = (e) => {
    e.preventDefault()
    setSearch(searchInput)
    setPage(1)
  }

  const handleStatusChange = (e) => {
    setStatusFilter(e.target.value)
    setPage(1)
  }

  const toggleRow = (id) => {
    setExpandedRows((prev) => {
      const next = new Set(prev)
      if (next.has(id)) {
        next.delete(id)
      } else {
        next.add(id)
      }
      return next
    })
  }

  // Get the data array based on table type
  const getItems = () => {
    if (!data) return []
    // Different tables return different keys
    if (data.sessions) return data.sessions
    if (data.approvals) return data.approvals
    if (data.projects) return data.projects
    if (data.workspaces) return data.workspaces
    if (data.questions) return data.questions
    if (data.builds) return data.builds
    return []
  }

  const items = getItems()

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="w-8 h-8 animate-spin text-blue-500" />
        <span className="ml-2 text-gray-600">Loading {config.label}...</span>
      </div>
    )
  }

  if (isError) {
    return (
      <div className="flex flex-col items-center justify-center h-64 text-red-500">
        <AlertCircle className="w-12 h-12 mb-2" />
        <p className="text-lg font-medium">Failed to load {config.label}</p>
        <p className="text-sm text-red-400">{error?.message || 'An unexpected error occurred'}</p>
        <button
          onClick={() => refetch()}
          className="mt-4 px-4 py-2 bg-blue-500 text-white rounded-lg hover:bg-blue-600"
        >
          Retry
        </button>
      </div>
    )
  }

  return (
    <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
      {/* Search and filter bar */}
      <div className="p-4 border-b border-gray-200 flex items-center gap-4 bg-gray-50">
        <form onSubmit={handleSearch} className="flex items-center gap-2 flex-1">
          <div className="relative flex-1 max-w-md">
            <Search className="w-4 h-4 absolute left-3 top-1/2 transform -translate-y-1/2 text-gray-400" />
            <input
              type="text"
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              placeholder="Search..."
              className="w-full pl-9 pr-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            />
          </div>
          <button
            type="submit"
            className="px-4 py-2 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700"
          >
            Search
          </button>
        </form>

        {config.statusOptions.length > 0 && (
          <select
            value={statusFilter}
            onChange={handleStatusChange}
            className="px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-blue-500"
          >
            <option value="">All Statuses</option>
            {config.statusOptions.map((status) => (
              <option key={status} value={status}>
                {status.charAt(0).toUpperCase() + status.slice(1)}
              </option>
            ))}
          </select>
        )}

        <button
          onClick={() => refetch()}
          className="p-2 text-gray-600 hover:text-gray-900 hover:bg-gray-200 rounded-lg"
          title="Refresh"
        >
          <RefreshCw className="w-4 h-4" />
        </button>
      </div>

      {/* Table */}
      {items.length === 0 ? (
        <div className="text-center py-12 text-gray-500">
          <Database className="w-12 h-12 mx-auto mb-4 text-gray-300" />
          <p>No records found</p>
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead className="bg-gray-100 border-b border-gray-200">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase w-8"></th>
                {config.columns.map((col) => (
                  <th
                    key={col}
                    className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase"
                  >
                    {col.replace(/_/g, ' ')}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <ExpandableRow
                  key={item.id}
                  item={item}
                  columns={config.columns}
                  expandableField={config.expandableField}
                  isExpanded={expandedRows.has(item.id)}
                  onToggle={() => toggleRow(item.id)}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Pagination */}
      <Pagination pagination={data?.pagination} onPageChange={setPage} />
    </div>
  )
}

// Stats card component
const StatsCard = ({ table }) => (
  <div className="bg-white rounded-lg border border-gray-200 p-4">
    <div className="text-sm text-gray-500">{table.name.replace(/_/g, ' ')}</div>
    <div className="text-2xl font-bold text-gray-900">{table.count.toLocaleString()}</div>
  </div>
)

// Main component
const AdminDatabase = () => {
  const [activeTable, setActiveTable] = useState('sessions')

  const { data: stats, isLoading: statsLoading } = useQuery({
    queryKey: ['admin', 'stats'],
    queryFn: getAdminStats,
  })

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold flex items-center gap-2">
          <Database className="w-6 h-6 text-blue-600" />
          Database Viewer
        </h1>
        <p className="text-gray-500 mt-1">
          Explore and inspect database tables. Admin access only.
        </p>
      </div>

      {/* Stats */}
      {!statsLoading && stats && (
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
          {stats.tables.map((table) => (
            <StatsCard key={table.name} table={table} />
          ))}
        </div>
      )}

      {/* Table tabs */}
      <div className="border-b border-gray-200">
        <nav className="flex space-x-1 overflow-x-auto" aria-label="Tables">
          {Object.entries(TABLES).map(([key, config]) => (
            <button
              key={key}
              onClick={() => setActiveTable(key)}
              className={`px-4 py-2 text-sm font-medium rounded-t-lg whitespace-nowrap transition-colors ${
                activeTable === key
                  ? 'bg-blue-600 text-white'
                  : 'text-gray-600 hover:bg-gray-100'
              }`}
            >
              {config.label}
            </button>
          ))}
        </nav>
      </div>

      {/* Active table view */}
      <TableView tableKey={activeTable} config={TABLES[activeTable]} />
    </div>
  )
}

export default AdminDatabase
