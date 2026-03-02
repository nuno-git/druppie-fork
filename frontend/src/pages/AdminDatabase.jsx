/**
 * Admin Database Browser
 *
 * Full database exploration with navigation between linked records.
 */

import React, { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  Database,
  ChevronDown,
  ChevronRight,
  ChevronLeft,
  ChevronsLeft,
  ChevronsRight,
  RefreshCw,
  AlertCircle,
  Loader2,
  ExternalLink,
  ArrowLeft,
  Table,
  Link2,
  X,
} from 'lucide-react'
import { getAdminTables, getAdminTableData, getAdminRecord } from '../services/api'

// Format dates for display
const formatDate = (dateStr) => {
  if (!dateStr) return '-'
  try {
    return new Date(dateStr).toLocaleString()
  } catch {
    return dateStr
  }
}

// Truncate long strings
const truncate = (str, maxLen = 50) => {
  if (str === null || str === undefined) return '-'
  const s = String(str)
  return s.length > maxLen ? s.substring(0, maxLen) + '...' : s
}

// Check if a value looks like a UUID
const isUUID = (val) => {
  if (!val || typeof val !== 'string') return false
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(val)
}

// Status badge component
const StatusBadge = ({ value }) => {
  if (!value) return <span className="text-gray-400">-</span>
  const colors = {
    active: 'bg-green-100 text-green-700',
    completed: 'bg-blue-100 text-blue-700',
    paused: 'bg-blue-100 text-blue-700',
    paused_crashed: 'bg-red-100 text-red-700',
    paused_approval: 'bg-blue-100 text-blue-700',
    paused_hitl: 'bg-blue-100 text-blue-700',
    paused_tool: 'bg-blue-100 text-blue-700',
    failed: 'bg-red-100 text-red-700',
    pending: 'bg-blue-100 text-blue-700',
    approved: 'bg-green-100 text-green-700',
    rejected: 'bg-red-100 text-red-700',
    answered: 'bg-green-100 text-green-700',
    running: 'bg-green-100 text-green-700',
    success: 'bg-green-100 text-green-700',
    building: 'bg-blue-100 text-blue-700',
    executing: 'bg-blue-100 text-blue-700',
  }
  const colorClass = colors[value] || 'bg-gray-100 text-gray-700'
  return (
    <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${colorClass}`}>
      {value}
    </span>
  )
}

// Cell renderer based on column type and value
const CellValue = ({ column, value, relations, onNavigate }) => {
  // Check if this field is a foreign key
  const relation = relations?.[column]
  const isLink = relation && value && isUUID(value)

  if (column === 'status' || column === 'approval_type' || column === 'question_type') {
    return <StatusBadge value={value} />
  }

  if (column.endsWith('_at') || column === 'created_at' || column === 'updated_at') {
    return <span className="text-gray-600 text-xs">{formatDate(value)}</span>
  }

  if (column === 'id') {
    return (
      <code className="text-xs bg-gray-100 px-1 py-0.5 rounded font-mono text-blue-600">
        {truncate(value, 8)}
      </code>
    )
  }

  if (isLink) {
    const [targetTable] = relation
    return (
      <button
        onClick={() => onNavigate(targetTable, value)}
        className="text-blue-600 hover:text-blue-800 hover:underline text-xs font-mono flex items-center gap-1"
        title={`Go to ${targetTable}: ${value}`}
      >
        <Link2 className="w-3 h-3" />
        {truncate(value, 8)}
      </button>
    )
  }

  if (typeof value === 'object' && value !== null) {
    return (
      <code className="text-xs bg-gray-50 px-1 py-0.5 rounded text-gray-600">
        {truncate(JSON.stringify(value), 40)}
      </code>
    )
  }

  return <span className="text-sm">{truncate(value)}</span>
}

// Pagination component
const Pagination = ({ page, totalPages, total, onPageChange }) => {
  if (totalPages <= 1) return null

  return (
    <div className="flex items-center justify-between px-4 py-3 border-t border-gray-100">
      <span className="text-sm text-gray-600">
        Page {page} of {totalPages} ({total} records)
      </span>
      <div className="flex items-center gap-1">
        <button onClick={() => onPageChange(1)} disabled={page === 1} className="p-1 rounded hover:bg-gray-200 disabled:opacity-30">
          <ChevronsLeft className="w-4 h-4" />
        </button>
        <button onClick={() => onPageChange(page - 1)} disabled={page === 1} className="p-1 rounded hover:bg-gray-200 disabled:opacity-30">
          <ChevronLeft className="w-4 h-4" />
        </button>
        <span className="px-3 text-sm">{page}</span>
        <button onClick={() => onPageChange(page + 1)} disabled={page === totalPages} className="p-1 rounded hover:bg-gray-200 disabled:opacity-30">
          <ChevronRight className="w-4 h-4" />
        </button>
        <button onClick={() => onPageChange(totalPages)} disabled={page === totalPages} className="p-1 rounded hover:bg-gray-200 disabled:opacity-30">
          <ChevronsRight className="w-4 h-4" />
        </button>
      </div>
    </div>
  )
}

// Record detail panel
const RecordDetail = ({ table, recordId, onClose, onNavigate }) => {
  const { data, isLoading, isError } = useQuery({
    queryKey: ['admin-record', table, recordId],
    queryFn: () => getAdminRecord(table, recordId),
  })

  if (isLoading) {
    return (
      <div className="p-8 flex items-center justify-center">
        <Loader2 className="w-6 h-6 animate-spin text-blue-500" />
      </div>
    )
  }

  if (isError || !data) {
    return (
      <div className="p-8 text-red-500 text-center">
        <AlertCircle className="w-8 h-8 mx-auto mb-2" />
        Failed to load record
      </div>
    )
  }

  const { record, relations, reverse_relations } = data

  return (
    <div className="bg-white border rounded-lg shadow-lg max-h-[80vh] overflow-auto">
      <div className="sticky top-0 bg-white border-b px-4 py-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Table className="w-5 h-5 text-blue-600" />
          <span className="font-semibold">{table}</span>
          <code className="text-xs bg-gray-100 px-2 py-0.5 rounded">{truncate(recordId, 12)}</code>
        </div>
        <button onClick={onClose} className="p-1 hover:bg-gray-100 rounded">
          <X className="w-5 h-5" />
        </button>
      </div>

      <div className="p-4 space-y-4">
        {/* All fields */}
        <div>
          <h3 className="text-sm font-semibold text-gray-700 mb-2">Fields</h3>
          <div className="bg-gray-50 rounded border overflow-hidden">
            <table className="w-full text-sm">
              <tbody>
                {Object.entries(record).map(([key, value]) => {
                  const relation = relations?.[key]
                  const isLink = relation && value && isUUID(value)
                  return (
                    <tr key={key} className="border-b last:border-0">
                      <td className="px-3 py-2 font-medium text-gray-600 bg-gray-100 w-40">{key}</td>
                      <td className="px-3 py-2">
                        {isLink ? (
                          <button
                            onClick={() => onNavigate(relation[0], value)}
                            className="text-blue-600 hover:underline flex items-center gap-1"
                          >
                            <Link2 className="w-3 h-3" />
                            <span className="font-mono text-xs">{value}</span>
                            <span className="text-gray-400 text-xs">({relation[0]})</span>
                          </button>
                        ) : key.endsWith('_at') ? (
                          formatDate(value)
                        ) : typeof value === 'object' ? (
                          <pre className="text-xs bg-white p-2 rounded border max-h-40 overflow-auto">
                            {JSON.stringify(value, null, 2)}
                          </pre>
                        ) : (
                          <span className="font-mono text-xs break-all">{String(value ?? '-')}</span>
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>

        {/* Reverse relations */}
        {Object.keys(reverse_relations).length > 0 && (
          <div>
            <h3 className="text-sm font-semibold text-gray-700 mb-2">Related Records</h3>
            <div className="grid grid-cols-2 gap-2">
              {Object.entries(reverse_relations).map(([refTable, refs]) =>
                refs.map((ref, idx) => (
                  <button
                    key={`${refTable}-${idx}`}
                    onClick={() => onNavigate(refTable, null, { filterField: ref.field, filterValue: recordId })}
                    className="flex items-center justify-between px-3 py-2 bg-blue-50 hover:bg-blue-100 rounded border border-blue-200 text-sm"
                  >
                    <span className="flex items-center gap-2">
                      <ExternalLink className="w-4 h-4 text-blue-600" />
                      <span className="font-medium">{refTable}</span>
                    </span>
                    <span className="bg-blue-200 text-blue-800 px-2 py-0.5 rounded-full text-xs">
                      {ref.count}
                    </span>
                  </button>
                ))
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

// Table browser component
const TableBrowser = ({ table, filterField, filterValue, onNavigate, onSelectRecord }) => {
  const [page, setPage] = useState(1)
  const [expandedRows, setExpandedRows] = useState(new Set())

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['admin-table', table, page, filterField, filterValue],
    queryFn: () => getAdminTableData(table, page, 50, { filterField, filterValue }),
  })

  const toggleRow = (id) => {
    setExpandedRows(prev => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })
  }

  if (isLoading) {
    return (
      <div className="p-8 flex items-center justify-center">
        <Loader2 className="w-6 h-6 animate-spin text-blue-500" />
        <span className="ml-2 text-gray-600">Loading {table}...</span>
      </div>
    )
  }

  if (isError) {
    return (
      <div className="p-8 text-center text-red-500">
        <AlertCircle className="w-8 h-8 mx-auto mb-2" />
        <p>Failed to load table</p>
        <button onClick={() => refetch()} className="mt-2 px-4 py-2 bg-blue-500 text-white rounded">
          Retry
        </button>
      </div>
    )
  }

  const { columns, rows, relations, total, total_pages } = data

  return (
    <div className="bg-white rounded-lg border overflow-hidden">
      {/* Header */}
      <div className="px-4 py-3 border-b border-gray-100 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Table className="w-5 h-5 text-blue-600" />
          <span className="font-semibold">{table}</span>
          <span className="text-gray-500 text-sm">({total} records)</span>
          {filterField && (
            <span className="text-xs bg-blue-100 text-blue-700 px-2 py-0.5 rounded">
              {filterField} = {truncate(filterValue, 12)}
            </span>
          )}
        </div>
        <button onClick={() => refetch()} className="p-2 hover:bg-gray-200 rounded" title="Refresh">
          <RefreshCw className="w-4 h-4" />
        </button>
      </div>

      {/* Table */}
      {rows.length === 0 ? (
        <div className="p-8 text-center text-gray-500">
          <Database className="w-12 h-12 mx-auto mb-2 text-gray-300" />
          No records found
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="border-b border-gray-100">
              <tr>
                <th className="px-2 py-2.5 w-8"></th>
                {columns.map(col => (
                  <th key={col} className="px-3 py-2.5 text-left text-xs font-medium text-gray-400">
                    {col.replace(/_/g, ' ')}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, idx) => {
                const rowId = row.id || `row-${idx}`
                const isExpanded = expandedRows.has(rowId)
                return (
                  <React.Fragment key={rowId}>
                    <tr
                      className={`border-b border-gray-50 hover:bg-blue-50/50 cursor-pointer ${isExpanded ? 'bg-blue-50/50' : idx % 2 === 1 ? 'bg-gray-50/50' : ''}`}
                      onClick={() => row.id && onSelectRecord(table, row.id)}
                    >
                      <td className="px-2 py-2" onClick={(e) => { e.stopPropagation(); toggleRow(rowId) }}>
                        {isExpanded ? <ChevronDown className="w-4 h-4 text-gray-500" /> : <ChevronRight className="w-4 h-4 text-gray-500" />}
                      </td>
                      {columns.map(col => (
                        <td key={col} className="px-3 py-2" onClick={(e) => e.stopPropagation()}>
                          <CellValue
                            column={col}
                            value={row[col]}
                            relations={relations}
                            onNavigate={onNavigate}
                          />
                        </td>
                      ))}
                    </tr>
                    {isExpanded && (
                      <tr className="bg-gray-50 border-b">
                        <td colSpan={columns.length + 1} className="px-4 py-3">
                          <pre className="text-xs bg-white p-3 rounded border overflow-x-auto max-h-60">
                            {JSON.stringify(row, null, 2)}
                          </pre>
                        </td>
                      </tr>
                    )}
                  </React.Fragment>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      <Pagination page={page} totalPages={total_pages} total={total} onPageChange={setPage} />
    </div>
  )
}

// Main component
const AdminDatabase = () => {
  const [currentTable, setCurrentTable] = useState('sessions')
  const [filterField, setFilterField] = useState(null)
  const [filterValue, setFilterValue] = useState(null)
  const [selectedRecord, setSelectedRecord] = useState(null) // { table, id }
  const [history, setHistory] = useState([]) // navigation history

  const { data: tablesData, isLoading: tablesLoading } = useQuery({
    queryKey: ['admin-tables'],
    queryFn: getAdminTables,
  })

  const handleNavigate = (table, recordId = null, filter = null) => {
    // Save current state to history
    setHistory(prev => [...prev, { table: currentTable, filterField, filterValue, selectedRecord }])

    setCurrentTable(table)
    if (filter) {
      setFilterField(filter.filterField)
      setFilterValue(filter.filterValue)
    } else {
      setFilterField(null)
      setFilterValue(null)
    }

    if (recordId) {
      setSelectedRecord({ table, id: recordId })
    } else {
      setSelectedRecord(null)
    }
  }

  const handleBack = () => {
    if (history.length === 0) return
    const prev = history[history.length - 1]
    setHistory(h => h.slice(0, -1))
    setCurrentTable(prev.table)
    setFilterField(prev.filterField)
    setFilterValue(prev.filterValue)
    setSelectedRecord(prev.selectedRecord)
  }

  const handleSelectTable = (table) => {
    setHistory([])
    setCurrentTable(table)
    setFilterField(null)
    setFilterValue(null)
    setSelectedRecord(null)
  }

  const handleSelectRecord = (table, id) => {
    setSelectedRecord({ table, id })
  }

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Database className="w-6 h-6 text-blue-600" />
          <h1 className="text-2xl font-bold">Database Browser</h1>
        </div>
        {history.length > 0 && (
          <button
            onClick={handleBack}
            className="flex items-center gap-1 px-3 py-1.5 text-sm bg-gray-100 hover:bg-gray-200 rounded"
          >
            <ArrowLeft className="w-4 h-4" />
            Back
          </button>
        )}
      </div>

      {/* Table tabs */}
      {tablesLoading ? (
        <div className="flex items-center gap-2 text-gray-500">
          <Loader2 className="w-4 h-4 animate-spin" />
          Loading tables...
        </div>
      ) : (
        <div className="flex flex-wrap gap-1 p-1.5 bg-gray-50 rounded-lg border border-gray-100">
          {tablesData?.tables.map(t => (
            <button
              key={t.name}
              onClick={() => handleSelectTable(t.name)}
              className={`px-3 py-1.5 text-sm rounded transition-colors ${
                currentTable === t.name
                  ? 'bg-blue-600 text-white'
                  : 'bg-white hover:bg-gray-50 text-gray-700'
              }`}
            >
              {t.name}
              <span className={`ml-1 text-xs ${currentTable === t.name ? 'text-blue-200' : 'text-gray-400'}`}>
                ({t.count})
              </span>
            </button>
          ))}
        </div>
      )}

      {/* Content area */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Table browser */}
        <div className={selectedRecord ? 'lg:col-span-1' : 'lg:col-span-2'}>
          <TableBrowser
            key={`${currentTable}-${filterField}-${filterValue}`}
            table={currentTable}
            filterField={filterField}
            filterValue={filterValue}
            onNavigate={handleNavigate}
            onSelectRecord={handleSelectRecord}
          />
        </div>

        {/* Record detail panel */}
        {selectedRecord && (
          <div className="lg:col-span-1">
            <RecordDetail
              table={selectedRecord.table}
              recordId={selectedRecord.id}
              onClose={() => setSelectedRecord(null)}
              onNavigate={handleNavigate}
            />
          </div>
        )}
      </div>
    </div>
  )
}

export default AdminDatabase
