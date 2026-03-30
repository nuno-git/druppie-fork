import { useState, useEffect } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import {
  ArrowLeft,
  Loader2,
  AlertCircle,
  CheckCircle2,
  XCircle,
  TrendingUp,
  BarChart3,
  Clock,
} from 'lucide-react'
import {
  LineChart, Line, BarChart, Bar, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, Cell,
} from 'recharts'
import {
  getAnalyticsSummary,
  getAnalyticsTrends,
  getAnalyticsByAgent,
  getAnalyticsByEval,
  getAnalyticsByTool,
  getAnalyticsByTest,
  getTestBatches,
} from '../services/api'

const COLORS = {
  passed: '#22c55e',
  failed: '#ef4444',
  line: '#6366f1',
  bar: '#8b5cf6',
}

const StatCard = ({ label, value, icon: Icon, color = 'text-gray-700' }) => (
  <div className="bg-white rounded-lg border p-4 flex items-center gap-3">
    <Icon className={`w-8 h-8 ${color}`} />
    <div>
      <div className="text-sm text-gray-500">{label}</div>
      <div className={`text-2xl font-bold ${color}`}>{value}</div>
    </div>
  </div>
)

const formatDuration = (ms) => {
  if (ms === null || ms === undefined) return '-'
  if (ms < 1000) return `${ms}ms`
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`
  const mins = Math.floor(ms / 60000)
  const secs = ((ms % 60000) / 1000).toFixed(0)
  return `${mins}m ${secs}s`
}

const PassRateBar = ({ data, nameKey, onClick }) => (
  <ResponsiveContainer width="100%" height={Math.max(200, data.length * 36)}>
    <BarChart data={data} layout="vertical" margin={{ left: 120, right: 20, top: 5, bottom: 5 }}>
      <CartesianGrid strokeDasharray="3 3" horizontal={false} />
      <XAxis type="number" domain={[0, 100]} tickFormatter={(v) => `${v}%`} />
      <YAxis
        dataKey={nameKey}
        type="category"
        width={110}
        tick={{ fontSize: 12 }}
      />
      <Tooltip formatter={(v) => [`${v}%`, 'Pass Rate']} />
      <Bar dataKey="pass_rate" radius={[0, 4, 4, 0]} onClick={onClick}>
        {data.map((entry, i) => (
          <Cell key={i} fill={entry.pass_rate >= 80 ? COLORS.passed : entry.pass_rate >= 50 ? '#f59e0b' : COLORS.failed} />
        ))}
      </Bar>
    </BarChart>
  </ResponsiveContainer>
)

export default function Analytics() {
  const navigate = useNavigate()
  const [days, setDays] = useState(30)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [summary, setSummary] = useState(null)
  const [trends, setTrends] = useState([])
  const [byAgent, setByAgent] = useState([])
  const [byEval, setByEval] = useState([])
  const [byTool, setByTool] = useState([])
  const [byTest, setByTest] = useState([])
  const [batches, setBatches] = useState([])

  useEffect(() => {
    const load = async () => {
      setLoading(true)
      setError(null)
      try {
        const [s, t, a, e, tl, tt, b] = await Promise.all([
          getAnalyticsSummary(days),
          getAnalyticsTrends(days),
          getAnalyticsByAgent(),
          getAnalyticsByEval(),
          getAnalyticsByTool(),
          getAnalyticsByTest(),
          getTestBatches(1, 10),
        ])
        setSummary(s)
        setTrends(t)
        setByAgent(a)
        setByEval(e)
        setByTool(tl)
        setByTest(tt.sort((a, b) => (b.avg_duration_ms || 0) - (a.avg_duration_ms || 0)).slice(0, 10))
        setBatches(b.items || [])
      } catch (err) {
        setError(err.message || 'Failed to load analytics')
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [days])

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="w-8 h-8 animate-spin text-indigo-500" />
        <span className="ml-3 text-gray-500">Loading analytics...</span>
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex items-center justify-center h-64 text-red-500">
        <AlertCircle className="w-6 h-6 mr-2" />
        {error}
      </div>
    )
  }

  return (
    <div className="max-w-7xl mx-auto space-y-8">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <button onClick={() => navigate('/admin/evaluations')} className="p-2 hover:bg-gray-100 rounded">
            <ArrowLeft className="w-5 h-5" />
          </button>
          <h1 className="text-2xl font-bold">Test Analytics</h1>
        </div>
        <select
          value={days}
          onChange={(e) => setDays(Number(e.target.value))}
          className="border rounded-lg px-3 py-2 text-sm"
        >
          <option value={7}>Last 7 days</option>
          <option value={14}>Last 14 days</option>
          <option value={30}>Last 30 days</option>
          <option value={90}>Last 90 days</option>
        </select>
      </div>

      {/* Summary Cards */}
      {summary && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <StatCard label="Total Runs" value={summary.total_runs} icon={BarChart3} />
          <StatCard label="Passed" value={summary.total_passed} icon={CheckCircle2} color="text-green-600" />
          <StatCard label="Failed" value={summary.total_failed} icon={XCircle} color="text-red-600" />
          <StatCard label="Pass Rate" value={`${summary.pass_rate}%`} icon={TrendingUp} color="text-indigo-600" />
        </div>
      )}

      {/* Trend Line */}
      {trends.length > 0 && (
        <div className="bg-white rounded-lg border p-6">
          <h2 className="text-lg font-semibold mb-4">Pass Rate Over Time</h2>
          <ResponsiveContainer width="100%" height={300}>
            <LineChart data={trends}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="date" tick={{ fontSize: 12 }} />
              <YAxis domain={[0, 100]} tickFormatter={(v) => `${v}%`} />
              <Tooltip formatter={(v) => [`${v}%`, 'Pass Rate']} />
              <Line type="monotone" dataKey="pass_rate" stroke={COLORS.line} strokeWidth={2} dot={{ r: 4 }} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* By Agent + By Eval (side by side) */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {byAgent.length > 0 && (
          <div className="bg-white rounded-lg border p-6">
            <h2 className="text-lg font-semibold mb-4">Results by Agent</h2>
            <PassRateBar data={byAgent} nameKey="agent" />
          </div>
        )}
        {byEval.length > 0 && (
          <div className="bg-white rounded-lg border p-6">
            <h2 className="text-lg font-semibold mb-4">Results by Eval</h2>
            <PassRateBar data={byEval} nameKey="eval_name" />
          </div>
        )}
      </div>

      {/* By Tool */}
      {byTool.length > 0 && (
        <div className="bg-white rounded-lg border p-6">
          <h2 className="text-lg font-semibold mb-4">Results by Tool</h2>
          <PassRateBar data={byTool} nameKey="tool" />
        </div>
      )}

      {/* Slowest Tests */}
      {byTest.length > 0 && (
        <div className="bg-white rounded-lg border p-6">
          <h2 className="text-lg font-semibold mb-4 flex items-center gap-2">
            <Clock className="w-5 h-5" /> Slowest Tests
          </h2>
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-gray-500 border-b">
                <th className="pb-2 pr-4">#</th>
                <th className="pb-2 pr-4">Test</th>
                <th className="pb-2 pr-4">Avg Duration</th>
                <th className="pb-2 pr-4">Runs</th>
                <th className="pb-2">Pass Rate</th>
              </tr>
            </thead>
            <tbody>
              {byTest.map((t, i) => (
                <tr key={t.test_name} className="border-b last:border-0">
                  <td className="py-2 pr-4 text-gray-400">{i + 1}</td>
                  <td className="py-2 pr-4 font-medium">{t.test_name}</td>
                  <td className="py-2 pr-4">{formatDuration(t.avg_duration_ms)}</td>
                  <td className="py-2 pr-4">{t.total}</td>
                  <td className="py-2">
                    <span className={t.pass_rate >= 80 ? 'text-green-600' : t.pass_rate >= 50 ? 'text-yellow-600' : 'text-red-600'}>
                      {t.pass_rate}%
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Recent Batches */}
      {batches.length > 0 && (
        <div className="bg-white rounded-lg border p-6">
          <h2 className="text-lg font-semibold mb-4">Recent Batches</h2>
          <div className="space-y-2">
            {batches.map((b) => {
              const passed = b.tests?.filter(t => t.status === 'passed').length || 0
              const total = b.tests?.length || b.total || 0
              const allPassed = passed === total && total > 0
              return (
                <Link
                  key={b.batch_id}
                  to={`/admin/tests/batch/${b.batch_id}`}
                  className="flex items-center justify-between p-3 rounded-lg border hover:bg-gray-50 transition-colors"
                >
                  <div className="flex items-center gap-3">
                    {allPassed ? (
                      <CheckCircle2 className="w-5 h-5 text-green-500" />
                    ) : (
                      <XCircle className="w-5 h-5 text-red-500" />
                    )}
                    <span className="font-medium">{b.batch_id?.slice(0, 8)}...</span>
                    <span className="text-sm text-gray-500">
                      {b.created_at ? new Date(b.created_at).toLocaleString() : ''}
                    </span>
                  </div>
                  <span className={`font-medium ${allPassed ? 'text-green-600' : 'text-red-600'}`}>
                    {passed}/{total} passed
                  </span>
                </Link>
              )
            })}
          </div>
        </div>
      )}

      {/* Empty state */}
      {!summary?.total_runs && (
        <div className="text-center text-gray-400 py-16">
          No test data yet. Run some tests from the Tests page to see analytics.
        </div>
      )}
    </div>
  )
}
