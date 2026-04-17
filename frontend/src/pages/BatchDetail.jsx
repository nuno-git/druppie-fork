import { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  ArrowLeft,
  Loader2,
  AlertCircle,
  CheckCircle2,
  XCircle,
  ChevronDown,
  ChevronUp,
  Clock,
} from 'lucide-react'
import {
  PieChart, Pie, Cell, BarChart, Bar, XAxis, YAxis,
  CartesianGrid, Tooltip, ResponsiveContainer, Legend,
} from 'recharts'
import { getAnalyticsBatchDetail } from '../services/api'

const COLORS = {
  passed: '#22c55e',
  failed: '#ef4444',
}

const formatDuration = (ms) => {
  if (ms === null || ms === undefined) return '-'
  if (ms < 1000) return `${ms}ms`
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`
  const mins = Math.floor(ms / 60000)
  const secs = ((ms % 60000) / 1000).toFixed(0)
  return `${mins}m ${secs}s`
}

const StatusIcon = ({ status }) =>
  status === 'passed' ? (
    <CheckCircle2 className="w-5 h-5 text-green-500" />
  ) : (
    <XCircle className="w-5 h-5 text-red-500" />
  )

const AssertionRow = ({ ar }) => (
  <div className="flex items-start gap-2 py-1 pl-8 text-sm">
    {ar.passed ? (
      <CheckCircle2 className="w-4 h-4 text-green-400 mt-0.5 shrink-0" />
    ) : (
      <XCircle className="w-4 h-4 text-red-400 mt-0.5 shrink-0" />
    )}
    <div>
      <span className="font-medium text-gray-700">
        {ar.assertion_type}: {ar.agent_id && `${ar.agent_id} `}
        {ar.tool_name && `${ar.tool_name} `}
        {ar.eval_name && `[${ar.eval_name}]`}
      </span>
      {ar.message && <span className="text-gray-500 ml-2">{ar.message}</span>}
      {ar.judge_reasoning && (
        <div className="text-gray-400 mt-1 italic text-xs">{ar.judge_reasoning}</div>
      )}
    </div>
  </div>
)

const TestResultRow = ({ test }) => {
  const [expanded, setExpanded] = useState(false)
  const hasAssertions = test.assertion_results?.length > 0

  return (
    <div className="border-b last:border-0">
      <button
        onClick={() => hasAssertions && setExpanded(!expanded)}
        className="w-full flex items-center justify-between py-3 px-4 hover:bg-gray-50 text-left"
      >
        <div className="flex items-center gap-3">
          <StatusIcon status={test.status} />
          <span className="font-medium">{test.test_name}</span>
          {test.hitl_profile && (
            <span className="text-xs bg-purple-100 text-purple-700 px-2 py-0.5 rounded-full">
              {test.hitl_profile}
            </span>
          )}
          {test.judge_profile && (
            <span className="text-xs bg-blue-100 text-blue-700 px-2 py-0.5 rounded-full">
              {test.judge_profile}
            </span>
          )}
        </div>
        <div className="flex items-center gap-4 text-sm text-gray-500">
          <span className="flex items-center gap-1">
            <Clock className="w-3.5 h-3.5" />
            {formatDuration(test.duration_ms)}
          </span>
          {test.assertions_total != null && (
            <span>
              {test.assertions_passed}/{test.assertions_total} assertions
            </span>
          )}
          {hasAssertions && (expanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />)}
        </div>
      </button>
      {expanded && test.assertion_results?.length > 0 && (
        <div className="pb-3 bg-gray-50">
          {test.assertion_results.map((ar, i) => (
            <AssertionRow key={i} ar={ar} />
          ))}
        </div>
      )}
    </div>
  )
}

export default function BatchDetail() {
  const { batchId } = useParams()
  const navigate = useNavigate()
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [batch, setBatch] = useState(null)

  useEffect(() => {
    let cancelled = false
    const load = async () => {
      setLoading(true)
      try {
        const data = await getAnalyticsBatchDetail(batchId)
        if (!cancelled) setBatch(data)
      } catch (err) {
        if (!cancelled) setError(err.message || 'Failed to load batch')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
    return () => { cancelled = true }
  }, [batchId])

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="w-8 h-8 animate-spin text-indigo-500" />
      </div>
    )
  }

  if (error || !batch) {
    return (
      <div className="flex items-center justify-center h-64 text-red-500">
        <AlertCircle className="w-6 h-6 mr-2" />
        {error || 'Batch not found'}
      </div>
    )
  }

  const pieData = [
    { name: 'Passed', value: batch.passed, fill: COLORS.passed },
    { name: 'Failed', value: batch.failed, fill: COLORS.failed },
  ].filter((d) => d.value > 0)

  return (
    <div className="max-w-7xl mx-auto space-y-8">
      {/* Header */}
      <div className="flex items-center gap-3">
        <button onClick={() => navigate('/admin/tests/analytics')} className="p-2 hover:bg-gray-100 rounded">
          <ArrowLeft className="w-5 h-5" />
        </button>
        <div>
          <h1 className="text-2xl font-bold">Batch Detail</h1>
          <p className="text-sm text-gray-500">
            {batch.created_at ? new Date(batch.created_at).toLocaleString() : batch.batch_id}
          </p>
        </div>
      </div>

      {/* Summary */}
      <div className={`flex items-center gap-4 px-6 py-4 rounded-lg border ${
        batch.passed === batch.total ? 'bg-green-50 border-green-200' : 'bg-red-50 border-red-200'
      }`}>
        {batch.passed === batch.total ? (
          <CheckCircle2 className="w-8 h-8 text-green-500" />
        ) : (
          <XCircle className="w-8 h-8 text-red-500" />
        )}
        <div>
          <div className="text-xl font-bold">
            {batch.passed}/{batch.total} passed ({batch.pass_rate}%)
          </div>
          <div className="text-sm text-gray-500">Duration: {formatDuration(batch.duration_ms)}</div>
        </div>
      </div>

      {/* Charts row */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Pie: Pass/Fail */}
        <div className="bg-white rounded-lg border p-6">
          <h2 className="text-lg font-semibold mb-4">Pass / Fail</h2>
          <ResponsiveContainer width="100%" height={250}>
            <PieChart>
              <Pie data={pieData} cx="50%" cy="50%" innerRadius={60} outerRadius={100} dataKey="value" label={({ name, value }) => `${name}: ${value}`}>
                {pieData.map((entry, i) => (
                  <Cell key={i} fill={entry.fill} />
                ))}
              </Pie>
              <Legend />
              <Tooltip />
            </PieChart>
          </ResponsiveContainer>
        </div>

        {/* Bar: By Agent */}
        {batch.by_agent?.length > 0 && (
          <div className="bg-white rounded-lg border p-6">
            <h2 className="text-lg font-semibold mb-4">By Agent</h2>
            <ResponsiveContainer width="100%" height={250}>
              <BarChart data={batch.by_agent}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="agent" tick={{ fontSize: 11 }} />
                <YAxis />
                <Tooltip />
                <Legend />
                <Bar dataKey="passed" stackId="a" fill={COLORS.passed} name="Passed" />
                <Bar dataKey="failed" stackId="a" fill={COLORS.failed} name="Failed" />
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>

      {/* By Eval bar chart */}
      {batch.by_eval?.length > 0 && (
        <div className="bg-white rounded-lg border p-6">
          <h2 className="text-lg font-semibold mb-4">By Eval</h2>
          <ResponsiveContainer width="100%" height={Math.max(200, batch.by_eval.length * 36)}>
            <BarChart data={batch.by_eval} layout="vertical" margin={{ left: 150 }}>
              <CartesianGrid strokeDasharray="3 3" horizontal={false} />
              <XAxis type="number" />
              <YAxis dataKey="eval_name" type="category" width={140} tick={{ fontSize: 11 }} />
              <Tooltip />
              <Legend />
              <Bar dataKey="passed" stackId="a" fill={COLORS.passed} name="Passed" />
              <Bar dataKey="failed" stackId="a" fill={COLORS.failed} name="Failed" />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Test Results Table */}
      <div className="bg-white rounded-lg border">
        <h2 className="text-lg font-semibold p-6 pb-0">Test Results</h2>
        <div className="mt-4">
          {batch.by_test?.map((test, i) => (
            <TestResultRow key={i} test={test} />
          ))}
        </div>
      </div>
    </div>
  )
}
