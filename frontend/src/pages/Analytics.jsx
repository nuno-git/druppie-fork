import { useState, useEffect } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import {
  ArrowLeft, Loader2, AlertCircle, CheckCircle2, XCircle,
  TrendingUp, BarChart3, Clock, ChevronDown, ChevronUp, Eye, Filter, X,
} from 'lucide-react'
import { getTestBatches, getBatchAssertions, getBatchFilters } from '../services/api'

const fmt = (ms) => {
  if (ms == null) return '-'
  if (ms < 1000) return `${ms}ms`
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`
  return `${Math.floor(ms / 60000)}m ${((ms % 60000) / 1000).toFixed(0)}s`
}
const fmtDate = (d) => d ? new Date(d).toLocaleString([], { dateStyle: 'short', timeStyle: 'short' }) : ''

const Badge = ({ p, t, color }) => {
  if (!t) return <span className="text-gray-300 text-xs">—</span>
  return <span className={`font-mono text-xs font-semibold ${p === t ? color : 'text-red-600'}`}>{p}/{t}</span>
}

const TypeBadge = ({ type }) => {
  const styles = {
    judge_check: 'bg-yellow-50 text-yellow-700',
    judge_eval: 'bg-orange-50 text-orange-700',
    completed: 'bg-blue-50 text-blue-700',
    tool: 'bg-blue-50 text-blue-700',
  }
  const labels = { judge_check: 'judge', judge_eval: 'judge eval', completed: 'assertion', tool: 'assertion' }
  return <span className={`px-1 py-0.5 rounded font-mono text-xs ${styles[type] || 'bg-gray-50 text-gray-600'}`}>{labels[type] || type}</span>
}

// ---- Check Filter Panel ----
const CheckFilterPanel = ({ filters, activeCheck, onSelectCheck, onClear }) => {
  const [expanded, setExpanded] = useState(false)
  const checks = filters?.checks || []
  const judges = checks.filter(c => c.type === 'judge_check' || c.type === 'judge_eval')
  const assertions = checks.filter(c => c.type === 'completed' || c.type === 'tool')

  if (!checks.length) return null

  return (
    <div className="bg-white rounded-lg border">
      <button onClick={() => setExpanded(!expanded)} className="w-full px-4 py-3 flex items-center justify-between hover:bg-gray-50">
        <span className="text-sm font-semibold flex items-center gap-2">
          <Filter className="w-4 h-4" /> Check Explorer
          {activeCheck && <span className="text-xs text-indigo-600">(filtered)</span>}
        </span>
        {expanded ? <ChevronUp className="w-4 h-4 text-gray-400" /> : <ChevronDown className="w-4 h-4 text-gray-400" />}
      </button>
      {expanded && (
        <div className="border-t divide-y max-h-96 overflow-y-auto">
          {activeCheck && (
            <button onClick={onClear} className="w-full px-4 py-2 text-xs text-indigo-600 hover:bg-indigo-50 flex items-center gap-1">
              <X className="w-3 h-3" /> Clear filter
            </button>
          )}
          {judges.length > 0 && (
            <div>
              <div className="px-4 py-1.5 bg-yellow-50 text-xs font-semibold text-yellow-700">LLM Judge & Judge Eval ({judges.length})</div>
              {judges.map((c, i) => (
                <button key={`j${i}`} onClick={() => onSelectCheck(c.text)}
                  className={`w-full px-4 py-2 text-left text-xs hover:bg-gray-50 flex items-center gap-2 ${activeCheck === c.text ? 'bg-indigo-50' : ''}`}>
                  <TypeBadge type={c.type} />
                  <span className="flex-1 truncate">{c.text.slice(0, 80)}{c.text.length > 80 ? '...' : ''}</span>
                  <Badge p={c.passed} t={c.total} color="text-green-600" />
                  <span className="text-gray-400 text-xs">{c.test_runs.length} test{c.test_runs.length > 1 ? 's' : ''}</span>
                </button>
              ))}
            </div>
          )}
          {assertions.length > 0 && (
            <div>
              <div className="px-4 py-1.5 bg-blue-50 text-xs font-semibold text-blue-700">Assertions ({assertions.length})</div>
              {assertions.map((c, i) => (
                <button key={`a${i}`} onClick={() => onSelectCheck(c.text)}
                  className={`w-full px-4 py-2 text-left text-xs hover:bg-gray-50 flex items-center gap-2 ${activeCheck === c.text ? 'bg-indigo-50' : ''}`}>
                  <TypeBadge type={c.type} />
                  {c.agents.length > 0 && <span className="font-medium text-gray-600">{c.agents.join(', ')}</span>}
                  <span className="flex-1 truncate">{c.text.slice(0, 60)}{c.text.length > 60 ? '...' : ''}</span>
                  <Badge p={c.passed} t={c.total} color="text-green-600" />
                </button>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ---- Assertion Row ----
const AssertionRow = ({ ar, isExpanded, onToggle }) => (
  <div className="border-b last:border-0">
    <button onClick={onToggle} className="w-full px-3 py-2 flex items-center gap-2 text-left hover:bg-gray-50 text-xs">
      {ar.passed ? <CheckCircle2 className="w-3.5 h-3.5 text-green-500 shrink-0" /> : <XCircle className="w-3.5 h-3.5 text-red-500 shrink-0" />}
      <TypeBadge type={ar.assertion_type} />
      {ar.agent_id && <span className="font-medium text-gray-700">{ar.agent_id}</span>}
      <span className="flex-1 text-gray-500 truncate">{ar.message}</span>
      {isExpanded ? <ChevronUp className="w-3 h-3 text-gray-400" /> : <ChevronDown className="w-3 h-3 text-gray-400" />}
    </button>
    {isExpanded && (
      <div className="px-3 pb-3 ml-6 space-y-2">
        {ar.judge_reasoning && (
          <div className={`p-2 rounded text-xs ${ar.assertion_type === 'judge_eval' ? 'bg-orange-50' : 'bg-yellow-50'}`}>
            <span className="font-medium">Reasoning:</span> {ar.judge_reasoning}
          </div>
        )}
        {ar.judge_raw_input && (
          <details className="text-xs"><summary className="cursor-pointer text-indigo-600 hover:underline">Show judge prompt</summary>
            <pre className="mt-1 bg-gray-900 text-green-400 p-2 rounded overflow-x-auto max-h-64 overflow-y-auto whitespace-pre-wrap">{ar.judge_raw_input}</pre>
          </details>
        )}
        {ar.judge_raw_output && (
          <details className="text-xs"><summary className="cursor-pointer text-indigo-600 hover:underline">Show judge response</summary>
            <pre className="mt-1 bg-gray-900 text-yellow-400 p-2 rounded overflow-x-auto max-h-32 overflow-y-auto whitespace-pre-wrap">{ar.judge_raw_output}</pre>
          </details>
        )}
        <details className="text-xs"><summary className="cursor-pointer text-indigo-600 hover:underline">Show raw data</summary>
          <pre className="mt-1 bg-gray-900 text-green-400 p-2 rounded overflow-x-auto max-h-48 overflow-y-auto whitespace-pre-wrap">{JSON.stringify(ar, null, 2)}</pre>
        </details>
      </div>
    )}
  </div>
)

// ---- Test Run Drill-down ----
const TestRunDrillDown = ({ run }) => {
  const [expanded, setExpanded] = useState(new Set())
  const toggle = (k) => { const n = new Set(expanded); n.has(k) ? n.delete(k) : n.add(k); setExpanded(n) }
  const assertions = run.assertions || []
  const code = assertions.filter(a => a.assertion_type === 'completed' || a.assertion_type === 'tool')
  const judge = assertions.filter(a => a.assertion_type === 'judge_check')
  const eval_ = assertions.filter(a => a.assertion_type === 'judge_eval')
  const sections = [
    { items: code, label: 'Assertions', color: 'bg-blue-50 text-blue-700', prefix: 'c' },
    { items: judge, label: 'LLM Judge', color: 'bg-yellow-50 text-yellow-700', prefix: 'j' },
    { items: eval_, label: 'Judge Eval', color: 'bg-orange-50 text-orange-700', prefix: 'e' },
  ].filter(s => s.items.length > 0)

  return (
    <div className="p-4 space-y-3 bg-gray-50 border-t">
      <div className="flex items-center justify-between">
        <div className="text-sm">
          <span className="font-medium">{run.test_description || run.test_name}</span>
          <span className={`ml-2 px-1.5 py-0.5 rounded text-xs font-medium ${run.mode === 'agent' ? 'bg-purple-100 text-purple-700' : 'bg-blue-100 text-blue-700'}`}>
            {run.mode === 'agent' ? 'Agent (LLM)' : 'Tool Replay'}
          </span>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-xs text-gray-400">{fmt(run.duration_ms)}</span>
          {run.session_id && <Link to={`/session/${run.session_id}`} className="text-xs text-indigo-600 hover:underline flex items-center gap-1"><Eye className="w-3 h-3" />Session</Link>}
        </div>
      </div>
      {sections.map(({ items, label, color, prefix }) => (
        <div key={prefix} className="bg-white rounded border">
          <div className={`px-3 py-1.5 border-b text-xs font-semibold ${color}`}>{label} ({items.filter(a => a.passed).length}/{items.length})</div>
          {items.map((ar, i) => <AssertionRow key={i} ar={ar} isExpanded={expanded.has(`${prefix}${i}`)} onToggle={() => toggle(`${prefix}${i}`)} />)}
        </div>
      ))}
      {assertions.length === 0 && <div className="text-xs text-gray-400">No assertions</div>}
    </div>
  )
}

// ---- Main ----
export default function Analytics() {
  const navigate = useNavigate()
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [batches, setBatches] = useState([])
  const [selectedBatchId, setSelectedBatchId] = useState(null)
  const [batchData, setBatchData] = useState(null)
  const [batchFilters, setBatchFilters] = useState(null)
  const [batchLoading, setBatchLoading] = useState(false)
  const [expandedRun, setExpandedRun] = useState(null)

  // Filters
  const [filterType, setFilterType] = useState(null)
  const [filterAgent, setFilterAgent] = useState(null)
  const [filterCheck, setFilterCheck] = useState(null)

  // Load batches
  useEffect(() => {
    getTestBatches(1, 50)
      .then(data => { setBatches(data.items || []); if (data.items?.length) setSelectedBatchId(data.items[0].batch_id) })
      .catch(err => setError(err.message))
      .finally(() => setLoading(false))
  }, [])

  // Load batch data when batch or filters change
  useEffect(() => {
    if (!selectedBatchId) return
    setBatchLoading(true)
    const filters = {}
    if (filterType) filters.assertion_type = filterType
    if (filterAgent) filters.agent_id = filterAgent
    if (filterCheck) filters.check_text = filterCheck
    Promise.all([
      getBatchAssertions(selectedBatchId, filters),
      getBatchFilters(selectedBatchId),
    ])
      .then(([data, f]) => { setBatchData(data); setBatchFilters(f) })
      .catch(err => setError(err.message))
      .finally(() => setBatchLoading(false))
  }, [selectedBatchId, filterType, filterAgent, filterCheck])

  const selectedBatch = batches.find(b => b.batch_id === selectedBatchId)
  const summary = batchData?.summary || {}
  const batchRuns = batchData?.runs || []
  const allAgents = batchFilters?.agents || []
  const hasActiveFilter = filterType || filterAgent || filterCheck

  const clearFilters = () => { setFilterType(null); setFilterAgent(null); setFilterCheck(null); setExpandedRun(null) }

  if (!loading && batches.length === 0) {
    return (
      <div className="max-w-7xl mx-auto">
        <div className="flex items-center gap-3 mb-8">
          <button onClick={() => navigate('/admin/evaluations')} className="p-2 hover:bg-gray-100 rounded"><ArrowLeft className="w-5 h-5" /></button>
          <h1 className="text-2xl font-bold">Test Analytics</h1>
        </div>
        <div className="text-center text-gray-400 py-16">No test batches yet.</div>
      </div>
    )
  }

  return (
    <div className="max-w-7xl mx-auto space-y-5">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <button onClick={() => navigate('/admin/evaluations')} className="p-2 hover:bg-gray-100 rounded"><ArrowLeft className="w-5 h-5" /></button>
          <h1 className="text-2xl font-bold">Test Analytics</h1>
        </div>
        <select value={selectedBatchId || ''} onChange={(e) => { setSelectedBatchId(e.target.value); clearFilters() }}
          className="border rounded-lg px-3 py-2 text-sm max-w-lg">
          {batches.map(b => {
            const ok = b.passed === b.test_count
            const label = b.test_count === 1 ? b.runs?.[0]?.test_name || b.batch_id.slice(0, 8) : `${b.test_count} tests`
            return <option key={b.batch_id} value={b.batch_id}>{ok ? '✓' : '✗'} {label} — {b.passed}/{b.test_count} — {fmtDate(b.started_at)}</option>
          })}
        </select>
      </div>

      {(loading || batchLoading) && <div className="flex items-center justify-center h-32"><Loader2 className="w-6 h-6 animate-spin text-indigo-500" /></div>}
      {error && <div className="text-red-500 flex items-center gap-2"><AlertCircle className="w-5 h-5" />{error}</div>}

      {!loading && !batchLoading && selectedBatch && batchData && (
        <>
          {/* Summary Cards */}
          <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
            <div className="bg-white rounded-lg border p-3 flex items-center gap-3">
              <BarChart3 className={`w-6 h-6 ${selectedBatch.passed === selectedBatch.test_count ? 'text-green-600' : 'text-red-600'}`} />
              <div><div className="text-xs text-gray-500">Tests</div><div className="text-lg font-bold">{selectedBatch.passed}/{selectedBatch.test_count}</div></div>
            </div>
            <button onClick={() => { setFilterType(filterType === 'assertions' ? null : 'assertions'); setFilterCheck(null) }}
              className={`bg-white rounded-lg border p-3 flex items-center gap-3 hover:bg-blue-50 text-left ${filterType === 'assertions' ? 'ring-2 ring-blue-400' : ''}`}>
              <CheckCircle2 className="w-6 h-6 text-blue-600" />
              <div><div className="text-xs text-gray-500">Assertions</div><div className="text-lg font-bold text-blue-600"><Badge p={summary.assertions_passed} t={summary.assertions} color="text-blue-600" /></div></div>
            </button>
            <button onClick={() => { setFilterType(filterType === 'judge_check' ? null : 'judge_check'); setFilterCheck(null) }}
              className={`bg-white rounded-lg border p-3 flex items-center gap-3 hover:bg-yellow-50 text-left ${filterType === 'judge_check' ? 'ring-2 ring-yellow-400' : ''}`}>
              <TrendingUp className="w-6 h-6 text-yellow-600" />
              <div><div className="text-xs text-gray-500">LLM Judge</div><div className="text-lg font-bold text-yellow-600"><Badge p={summary.judge_passed} t={summary.judge} color="text-yellow-600" /></div></div>
            </button>
            <button onClick={() => { setFilterType(filterType === 'judge_eval' ? null : 'judge_eval'); setFilterCheck(null) }}
              className={`bg-white rounded-lg border p-3 flex items-center gap-3 hover:bg-orange-50 text-left ${filterType === 'judge_eval' ? 'ring-2 ring-orange-400' : ''}`}>
              <Eye className="w-6 h-6 text-orange-600" />
              <div><div className="text-xs text-gray-500">Judge Eval</div><div className="text-lg font-bold text-orange-600"><Badge p={summary.judge_eval_passed} t={summary.judge_eval} color="text-orange-600" /></div></div>
            </button>
            <div className="bg-white rounded-lg border p-3 flex items-center gap-3">
              <Clock className="w-6 h-6 text-gray-500" />
              <div><div className="text-xs text-gray-500">Duration</div><div className="text-lg font-bold">{fmt(selectedBatch.total_duration_ms)}</div></div>
            </div>
          </div>

          {/* Check Explorer — filter by specific check */}
          <CheckFilterPanel
            filters={batchFilters}
            activeCheck={filterCheck}
            onSelectCheck={(text) => { setFilterCheck(filterCheck === text ? null : text); setFilterType(null); setExpandedRun(null) }}
            onClear={() => { setFilterCheck(null); setExpandedRun(null) }}
          />

          {/* Filter bar */}
          <div className="flex items-center gap-3 flex-wrap">
            <Filter className="w-4 h-4 text-gray-400" />
            <select value={filterType || ''} onChange={e => { setFilterType(e.target.value || null); setFilterCheck(null); setExpandedRun(null) }}
              className="px-2 py-1 border rounded text-xs bg-white">
              <option value="">All types</option>
              <option value="assertions">Assertions</option>
              <option value="judge_check">LLM Judge</option>
              <option value="judge_eval">Judge Eval</option>
            </select>
            {allAgents.length > 0 && (
              <select value={filterAgent || ''} onChange={e => { setFilterAgent(e.target.value || null); setExpandedRun(null) }}
                className="px-2 py-1 border rounded text-xs bg-white">
                <option value="">All agents</option>
                {allAgents.map(a => <option key={a} value={a}>{a}</option>)}
              </select>
            )}
            {hasActiveFilter && (
              <button onClick={clearFilters} className="text-xs text-gray-500 hover:text-gray-700 underline flex items-center gap-1">
                <X className="w-3 h-3" /> Clear all filters
              </button>
            )}
            <div className="flex-1" />
            {(() => {
              const tool = batchRuns.filter(r => r.mode === 'tool').length
              const agent = batchRuns.filter(r => r.mode === 'agent').length
              return <>
                {tool > 0 && <span className="px-2 py-0.5 bg-blue-50 text-blue-700 rounded text-xs">{tool} tool replay</span>}
                {agent > 0 && <span className="px-2 py-0.5 bg-purple-50 text-purple-700 rounded text-xs">{agent} agent (LLM)</span>}
              </>
            })()}
          </div>

          {/* Test Runs */}
          <div className="bg-white rounded-lg border overflow-hidden">
            <div className="px-4 py-2.5 border-b bg-gray-50 text-sm font-semibold">
              Test Runs ({batchRuns.filter(r => (r.assertions || []).length > 0).length}/{batchRuns.length} with results)
            </div>
            {batchRuns.map(run => {
              const isExpanded = expandedRun === run.test_run_id
              const assertions = run.assertions || []
              if (hasActiveFilter && assertions.length === 0) return null  // hide empty when filtered
              const code = assertions.filter(a => a.assertion_type === 'completed' || a.assertion_type === 'tool')
              const judge = assertions.filter(a => a.assertion_type === 'judge_check')
              const eval_ = assertions.filter(a => a.assertion_type === 'judge_eval')

              return (
                <div key={run.test_run_id} className="border-b last:border-0">
                  <button onClick={() => setExpandedRun(isExpanded ? null : run.test_run_id)}
                    className="w-full px-4 py-3 flex items-center gap-3 text-left hover:bg-gray-50 transition-colors">
                    {run.status === 'passed' ? <CheckCircle2 className="w-4 h-4 text-green-500 shrink-0" /> : <XCircle className="w-4 h-4 text-red-500 shrink-0" />}
                    <span className="font-medium text-sm flex-1">{run.test_name}</span>
                    <span className={`px-1.5 py-0.5 rounded text-xs font-medium ${run.mode === 'agent' ? 'bg-purple-100 text-purple-700' : 'bg-blue-100 text-blue-700'}`}>
                      {run.mode === 'agent' ? 'Agent' : 'Tool'}
                    </span>
                    {code.length > 0 && <Badge p={code.filter(a => a.passed).length} t={code.length} color="text-blue-600" />}
                    {judge.length > 0 && <Badge p={judge.filter(a => a.passed).length} t={judge.length} color="text-yellow-600" />}
                    {eval_.length > 0 && <Badge p={eval_.filter(a => a.passed).length} t={eval_.length} color="text-orange-600" />}
                    <span className="text-xs text-gray-400 w-14 text-right">{fmt(run.duration_ms)}</span>
                    {run.session_id && <Link to={`/session/${run.session_id}`} onClick={e => e.stopPropagation()} className="text-xs text-indigo-500 hover:underline">Session</Link>}
                    {isExpanded ? <ChevronUp className="w-4 h-4 text-gray-400" /> : <ChevronDown className="w-4 h-4 text-gray-400" />}
                  </button>
                  {isExpanded && <TestRunDrillDown run={run} />}
                </div>
              )
            })}
            {batchRuns.length === 0 && <div className="p-8 text-center text-gray-400 text-sm">No test runs.</div>}
          </div>
        </>
      )}
    </div>
  )
}
