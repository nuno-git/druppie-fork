/**
 * Agent Editor Page - Create or edit custom agent definitions
 */

import React, { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import Markdown from 'react-markdown'
import {
  ArrowLeft,
  Save,
  Loader2,
  AlertCircle,
  Bot,
  Rocket,
  FileCode,
  Download,
  X,
  Copy,
  CheckCircle,
  Eye,
  Edit3,
} from 'lucide-react'
import {
  getCustomAgent,
  createCustomAgent,
  getAgentMetadata,
  deployCustomAgent,
  validateForFoundry,
  getCustomAgentYaml,
} from '../services/api'

const SectionCard = ({ title, subtitle, children }) => (
  <div className="bg-white rounded-xl border border-gray-100 p-6">
    <div className="mb-4">
      <h3 className="text-sm font-medium text-gray-400 uppercase tracking-wide">{title}</h3>
      {subtitle && <p className="text-xs text-gray-500 mt-1">{subtitle}</p>}
    </div>
    {children}
  </div>
)

const CATEGORIES = [
  { value: 'execution', label: 'Execution' },
  { value: 'planning', label: 'Planning' },
  { value: 'review', label: 'Review' },
  { value: 'analysis', label: 'Analysis' },
  { value: 'deployment', label: 'Deployment' },
]

const FOUNDRY_TOOLS = [
  { id: 'code_interpreter', label: 'Code Interpreter', desc: 'Run Python code in a sandbox', status: 'ready' },
  { id: 'file_search', label: 'File Search', desc: 'Search through uploaded files using embeddings', status: 'ready' },
  { id: 'bing_grounding', label: 'Bing Grounding', desc: 'Ground responses with web search results', status: 'portal', note: 'Requires Bing connection in Foundry portal' },
  { id: 'browser_automation', label: 'Browser Automation', desc: 'Automate browser interactions', status: 'coming' },
  { id: 'deep_research', label: 'Deep Research', desc: 'In-depth research across multiple sources', status: 'coming' },
]

const AgentEditor = () => {
  const { agentId } = useParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const isEdit = !!agentId

  const [form, setForm] = useState({
    agent_id: '',
    name: '',
    description: '',
    category: 'execution',
    system_prompt: '',
    foundry_tools: [],
    llm_profile: '',
    max_tokens: '',
    max_iterations: '',
  })
  const [errors, setErrors] = useState({})
  const [promptTab, setPromptTab] = useState('edit') // 'edit' | 'preview'

  const { data: metadata, isLoading: metaLoading } = useQuery({
    queryKey: ['agent-metadata'],
    queryFn: getAgentMetadata,
  })

  const { data: existingAgent, isLoading: agentLoading } = useQuery({
    queryKey: ['custom-agent', agentId],
    queryFn: () => getCustomAgent(agentId),
    enabled: isEdit,
  })

  useEffect(() => {
    if (existingAgent) {
      setForm({
        agent_id: existingAgent.agent_id || '',
        name: existingAgent.name || '',
        description: existingAgent.description || '',
        category: existingAgent.category || 'execution',
        system_prompt: existingAgent.system_prompt || '',
        foundry_tools: existingAgent.foundry_tools || [],
        llm_profile: existingAgent.llm_profile || '',
        max_tokens: existingAgent.max_tokens || '',
        max_iterations: existingAgent.max_iterations || '',
      })
    }
  }, [existingAgent])

  const createMutation = useMutation({
    mutationFn: (data) => createCustomAgent(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['custom-agents'] })
      navigate('/agents')
    },
    onError: (err) => setErrors({ submit: err.message }),
  })

  const isSaving = createMutation.isPending

  const validate = () => {
    const errs = {}
    if (!form.agent_id.trim()) errs.agent_id = 'Agent ID is required'
    else if (!/^[a-z0-9]+(-[a-z0-9]+)*$/.test(form.agent_id))
      errs.agent_id = 'Must be kebab-case (e.g. my-agent)'
    if (!form.name.trim()) errs.name = 'Name is required'
    if (!form.category) errs.category = 'Category is required'
    setErrors(errs)
    return Object.keys(errs).length === 0
  }

  const handleSubmit = (e) => {
    e.preventDefault()
    if (!validate()) return
    const payload = {
      ...form,
      max_tokens: form.max_tokens ? parseInt(form.max_tokens, 10) : undefined,
      max_iterations: form.max_iterations ? parseInt(form.max_iterations, 10) : undefined,
    }
    if (!payload.max_tokens) delete payload.max_tokens
    if (!payload.max_iterations) delete payload.max_iterations
    if (isEdit) return // Update not supported for Foundry agents
    createMutation.mutate(payload)
  }

  const updateField = (field, value) => {
    setForm((prev) => ({ ...prev, [field]: value }))
    if (errors[field]) setErrors((prev) => ({ ...prev, [field]: undefined }))
  }

  const toggleArrayItem = (field, item) => {
    setForm((prev) => ({
      ...prev,
      [field]: prev[field].includes(item)
        ? prev[field].filter((i) => i !== item)
        : [...prev[field], item],
    }))
  }


  if ((isEdit && agentLoading) || metaLoading) {
    return (
      <div className="space-y-6">
        <div className="flex items-center gap-4">
          <div className="animate-pulse bg-gray-200 w-9 h-9 rounded-lg" />
          <div className="animate-pulse bg-gray-200 h-7 w-48 rounded" />
        </div>
        {[1, 2, 3].map((i) => (
          <div key={i} className="bg-white rounded-xl border border-gray-100 p-6 animate-pulse">
            <div className="h-5 bg-gray-200 rounded w-32 mb-4" />
            <div className="h-10 bg-gray-100 rounded" />
          </div>
        ))}
      </div>
    )
  }

  const metaLlmProfiles = metadata?.llm_profiles || []

  return (
    <div className="space-y-6 max-w-5xl">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center space-x-4">
          <button
            onClick={() => navigate('/agents')}
            className="p-2 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded-lg transition-colors"
          >
            <ArrowLeft className="w-5 h-5" />
          </button>
          <Bot className="w-6 h-6 text-gray-400" />
          <h1 className="text-2xl font-bold text-gray-900">
            {isEdit ? `Edit Agent: ${agentId}` : 'Create Agent'}
          </h1>
        </div>
        {isEdit && (
          <div className="flex items-center gap-2">
            <YamlViewerButton agentId={agentId} />
            <DeployButton agentId={agentId} />
          </div>
        )}
      </div>

      {errors.submit && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-4 flex items-start gap-3">
          <AlertCircle className="w-5 h-5 text-red-500 flex-shrink-0 mt-0.5" />
          <p className="text-sm text-red-700">{errors.submit}</p>
        </div>
      )}

      <form onSubmit={handleSubmit} className="space-y-6">
        {/* Identity — compact row */}
        <SectionCard title="Identity">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div>
              <label className="block text-xs font-medium text-gray-500 mb-1">Agent ID</label>
              <input
                type="text"
                value={form.agent_id}
                onChange={(e) => updateField('agent_id', e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, '-'))}
                disabled={isEdit}
                placeholder="my-custom-agent"
                className={`w-full px-3 py-2 text-sm border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent disabled:bg-gray-50 disabled:text-gray-500 ${
                  errors.agent_id ? 'border-red-300' : 'border-gray-200'
                }`}
              />
              {errors.agent_id && <p className="text-xs text-red-500 mt-1">{errors.agent_id}</p>}
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-500 mb-1">Display Name</label>
              <input
                type="text"
                value={form.name}
                onChange={(e) => updateField('name', e.target.value)}
                placeholder="My Custom Agent"
                className={`w-full px-3 py-2 text-sm border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent ${
                  errors.name ? 'border-red-300' : 'border-gray-200'
                }`}
              />
              {errors.name && <p className="text-xs text-red-500 mt-1">{errors.name}</p>}
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-500 mb-1">Category</label>
              <select
                value={form.category}
                onChange={(e) => updateField('category', e.target.value)}
                className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              >
                {CATEGORIES.map((cat) => (
                  <option key={cat.value} value={cat.value}>{cat.label}</option>
                ))}
              </select>
            </div>
          </div>
        </SectionCard>

        {/* Description — full width, proper height */}
        <SectionCard title="Description" subtitle="A short summary of what this agent does. Shown in the agent list.">
          <textarea
            value={form.description}
            onChange={(e) => updateField('description', e.target.value)}
            placeholder="Describe the agent's purpose and capabilities..."
            rows={4}
            className="w-full px-4 py-3 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent resize-vertical leading-relaxed"
          />
        </SectionCard>

        {/* System Prompt — with markdown preview */}
        <SectionCard title="System Prompt" subtitle="The instructions that define this agent's behavior. Supports markdown.">
          <div className="border border-gray-200 rounded-lg overflow-hidden">
            {/* Tab bar */}
            <div className="flex items-center border-b border-gray-200 bg-gray-50 px-1">
              <button
                type="button"
                onClick={() => setPromptTab('edit')}
                className={`inline-flex items-center gap-1.5 px-3 py-2 text-xs font-medium border-b-2 -mb-px transition-colors ${
                  promptTab === 'edit'
                    ? 'border-blue-500 text-blue-600'
                    : 'border-transparent text-gray-500 hover:text-gray-700'
                }`}
              >
                <Edit3 className="w-3.5 h-3.5" />
                Edit
              </button>
              <button
                type="button"
                onClick={() => setPromptTab('preview')}
                className={`inline-flex items-center gap-1.5 px-3 py-2 text-xs font-medium border-b-2 -mb-px transition-colors ${
                  promptTab === 'preview'
                    ? 'border-blue-500 text-blue-600'
                    : 'border-transparent text-gray-500 hover:text-gray-700'
                }`}
              >
                <Eye className="w-3.5 h-3.5" />
                Preview
              </button>
            </div>
            {/* Content */}
            {promptTab === 'edit' ? (
              <textarea
                value={form.system_prompt}
                onChange={(e) => updateField('system_prompt', e.target.value)}
                placeholder="Enter the system prompt for this agent..."
                className="w-full px-4 py-3 text-sm border-none focus:outline-none focus:ring-0 resize-vertical font-mono leading-relaxed"
                style={{ minHeight: '400px' }}
              />
            ) : (
              <div
                className="px-6 py-4 prose prose-sm prose-gray max-w-none overflow-auto"
                style={{ minHeight: '400px' }}
              >
                {form.system_prompt ? (
                  <Markdown>{form.system_prompt}</Markdown>
                ) : (
                  <p className="text-gray-400 italic">No system prompt yet.</p>
                )}
              </div>
            )}
          </div>
        </SectionCard>

        {/* Two-column layout for tools and settings */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Left column — Foundry Tools */}
          <SectionCard title="Azure Foundry Tools" subtitle="Sent to Azure on deploy. These run inside the Foundry runtime.">
            <div className="space-y-2">
              {FOUNDRY_TOOLS.map((tool) => (
                <label
                  key={tool.id}
                  className={`flex items-start gap-3 p-3 rounded-lg border transition-colors ${
                    form.foundry_tools.includes(tool.id)
                      ? 'border-purple-200 bg-purple-50'
                      : 'border-gray-100 hover:border-gray-200'
                  } ${tool.status === 'coming' ? 'opacity-50' : 'cursor-pointer'}`}
                >
                  <input
                    type="checkbox"
                    checked={form.foundry_tools.includes(tool.id)}
                    onChange={() => tool.status !== 'coming' && toggleArrayItem('foundry_tools', tool.id)}
                    disabled={tool.status === 'coming'}
                    className="w-4 h-4 mt-0.5 text-purple-600 border-gray-300 rounded focus:ring-purple-500"
                  />
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium text-gray-900">{tool.label}</span>
                      {tool.status === 'ready' && (
                        <span className="px-1.5 py-0.5 text-[10px] font-medium bg-green-100 text-green-700 rounded">Ready</span>
                      )}
                      {tool.status === 'portal' && (
                        <span className="px-1.5 py-0.5 text-[10px] font-medium bg-amber-100 text-amber-700 rounded">Needs Setup</span>
                      )}
                      {tool.status === 'coming' && (
                        <span className="px-1.5 py-0.5 text-[10px] font-medium bg-gray-100 text-gray-500 rounded">Coming Soon</span>
                      )}
                    </div>
                    <p className="text-xs text-gray-500 mt-0.5">{tool.desc}</p>
                    {tool.note && form.foundry_tools.includes(tool.id) && (
                      <p className="text-xs text-amber-600 mt-1">{tool.note}</p>
                    )}
                  </div>
                </label>
              ))}
            </div>
          </SectionCard>

          {/* Right column — LLM Settings */}
          <SectionCard title="LLM Settings" subtitle="Foundry mapping: standard = gpt-4.1-mini, cheap = gpt-4.1-nano.">
            <div className="space-y-4">
              <div>
                <label className="block text-xs font-medium text-gray-500 mb-1">LLM Profile</label>
                {metaLlmProfiles.length > 0 ? (
                  <select
                    value={form.llm_profile}
                    onChange={(e) => updateField('llm_profile', e.target.value)}
                    className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                  >
                    <option value="">Default (standard)</option>
                    {metaLlmProfiles.map((profile) => {
                      const val = typeof profile === 'string' ? profile : profile.name || profile.id
                      return <option key={val} value={val}>{val}</option>
                    })}
                  </select>
                ) : (
                  <input
                    type="text"
                    value={form.llm_profile}
                    onChange={(e) => updateField('llm_profile', e.target.value)}
                    placeholder="standard"
                    className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                  />
                )}
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs font-medium text-gray-500 mb-1">Max Tokens</label>
                  <input
                    type="number"
                    value={form.max_tokens}
                    onChange={(e) => updateField('max_tokens', e.target.value)}
                    placeholder="4096"
                    className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-500 mb-1">Max Iterations</label>
                  <input
                    type="number"
                    value={form.max_iterations}
                    onChange={(e) => updateField('max_iterations', e.target.value)}
                    placeholder="10"
                    className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                  />
                </div>
              </div>
            </div>
          </SectionCard>
        </div>

        {/* Save bar — only shown for new agents (update not supported for Foundry agents) */}
        {!isEdit && (
          <div className="sticky bottom-0 bg-white/80 backdrop-blur-sm border-t border-gray-100 -mx-6 px-6 py-4 flex items-center gap-3">
            <button
              type="submit"
              disabled={isSaving}
              className="inline-flex items-center gap-2 px-5 py-2.5 text-sm font-medium text-white bg-blue-600 rounded-lg hover:bg-blue-700 disabled:opacity-50 transition-colors"
            >
              {isSaving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
              Create Agent
            </button>
            <button
              type="button"
              onClick={() => navigate('/agents')}
              className="px-5 py-2.5 text-sm font-medium text-gray-700 bg-white border border-gray-200 rounded-lg hover:bg-gray-50 transition-colors"
            >
              Cancel
            </button>
          </div>
        )}
      </form>
    </div>
  )
}

const YamlViewerButton = ({ agentId }) => {
  const [open, setOpen] = useState(false)
  const [yaml, setYaml] = useState(null)
  const [loading, setLoading] = useState(false)
  const [copied, setCopied] = useState(false)

  const handleOpen = async () => {
    setOpen(true)
    setLoading(true)
    try {
      const result = await getCustomAgentYaml(agentId)
      setYaml(result.yaml)
    } catch {
      setYaml('# Failed to load YAML')
    } finally {
      setLoading(false)
    }
  }

  const handleDownload = () => {
    if (!yaml) return
    const blob = new Blob([yaml], { type: 'application/x-yaml' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${agentId}.yaml`
    a.click()
    URL.revokeObjectURL(url)
  }

  const handleCopy = () => {
    if (!yaml) return
    navigator.clipboard.writeText(yaml)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <>
      <button
        type="button"
        onClick={handleOpen}
        className="inline-flex items-center gap-2 px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-200 rounded-lg hover:bg-gray-50 transition-colors"
      >
        <FileCode className="w-4 h-4" />
        YAML
      </button>

      {open && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={() => setOpen(false)}>
          <div className="bg-white rounded-xl shadow-xl w-full max-w-3xl max-h-[80vh] flex flex-col m-4" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between px-6 py-4 border-b">
              <h3 className="text-sm font-medium text-gray-900">{agentId}.yaml</h3>
              <div className="flex items-center gap-2">
                <button onClick={handleCopy} className="p-1.5 text-gray-400 hover:text-blue-600 rounded transition-colors" title="Copy">
                  {copied ? <CheckCircle className="w-4 h-4 text-green-500" /> : <Copy className="w-4 h-4" />}
                </button>
                <button onClick={handleDownload} className="p-1.5 text-gray-400 hover:text-blue-600 rounded transition-colors" title="Download">
                  <Download className="w-4 h-4" />
                </button>
                <button onClick={() => setOpen(false)} className="p-1.5 text-gray-400 hover:text-gray-600 rounded transition-colors">
                  <X className="w-4 h-4" />
                </button>
              </div>
            </div>
            <div className="flex-1 overflow-auto p-6">
              {loading ? (
                <div className="flex items-center justify-center py-12">
                  <Loader2 className="w-5 h-5 animate-spin text-gray-400" />
                </div>
              ) : (
                <pre className="text-sm font-mono text-gray-800 whitespace-pre-wrap">{yaml}</pre>
              )}
            </div>
          </div>
        </div>
      )}
    </>
  )
}

const DeployButton = ({ agentId }) => {
  const [phase, setPhase] = useState('idle') // idle | validating | validated | deploying
  const [validation, setValidation] = useState(null)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)

  const handleValidate = async () => {
    setPhase('validating')
    setError(null)
    setResult(null)
    setValidation(null)
    try {
      const data = await validateForFoundry(agentId)
      setValidation(data)
      setPhase('validated')
    } catch (err) {
      setError(err.message || 'Validation failed')
      setPhase('idle')
    }
  }

  const handleDeploy = async () => {
    setPhase('deploying')
    setError(null)
    try {
      const data = await deployCustomAgent(agentId)
      setResult(data)
      setPhase('idle')
      setValidation(null)
    } catch (err) {
      setError(err.message || 'Deployment failed')
      setPhase('idle')
    }
  }

  const handleClose = () => {
    setPhase('idle')
    setValidation(null)
    setError(null)
  }

  return (
    <div className="relative">
      <button
        type="button"
        onClick={handleValidate}
        disabled={phase === 'validating' || phase === 'deploying'}
        className="inline-flex items-center gap-2 px-4 py-2 text-sm font-medium text-white bg-purple-600 rounded-lg hover:bg-purple-700 disabled:opacity-50 transition-colors"
      >
        {phase === 'validating' || phase === 'deploying'
          ? <Loader2 className="w-4 h-4 animate-spin" />
          : <Rocket className="w-4 h-4" />}
        {phase === 'deploying' ? 'Deploying...' : 'Deploy'}
      </button>

      {result && <span className="ml-2 text-sm text-green-600">Deployed</span>}
      {error && !validation && <span className="ml-2 text-sm text-red-600 max-w-xs truncate" title={error}>{error}</span>}

      {/* Validation results dialog */}
      {phase === 'validated' && validation && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={handleClose}>
          <div className="bg-white rounded-xl shadow-xl w-full max-w-lg m-4" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between px-6 py-4 border-b">
              <h3 className="text-sm font-medium text-gray-900">Foundry Deployment Validation</h3>
              <button onClick={handleClose} className="p-1.5 text-gray-400 hover:text-gray-600 rounded transition-colors">
                <X className="w-4 h-4" />
              </button>
            </div>

            <div className="px-6 py-4 space-y-4">
              {/* Status */}
              <div className={`flex items-center gap-2 text-sm font-medium ${validation.valid ? 'text-green-700' : 'text-red-700'}`}>
                {validation.valid
                  ? <><CheckCircle className="w-5 h-5" /> Ready to deploy</>
                  : <><AlertCircle className="w-5 h-5" /> Cannot deploy — fix errors below</>}
              </div>

              {/* Model info */}
              <div className="text-sm text-gray-600">
                Foundry model: <span className="font-mono font-medium">{validation.foundry_model}</span>
              </div>

              {/* Deployable tools */}
              {validation.deployable_tools?.length > 0 && (
                <div className="text-sm text-gray-600">
                  Tools: {validation.deployable_tools.map(t => (
                    <span key={t} className="inline-block px-2 py-0.5 mr-1 bg-purple-50 text-purple-700 rounded text-xs font-medium">{t}</span>
                  ))}
                </div>
              )}

              {/* Errors */}
              {validation.errors?.length > 0 && (
                <div className="space-y-1.5">
                  <p className="text-xs font-medium text-red-600 uppercase tracking-wide">Errors</p>
                  {validation.errors.map((e, i) => (
                    <div key={i} className="flex items-start gap-2 text-sm text-red-700 bg-red-50 rounded-lg px-3 py-2">
                      <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" />
                      {e}
                    </div>
                  ))}
                </div>
              )}

              {/* Warnings */}
              {validation.warnings?.length > 0 && (
                <div className="space-y-1.5">
                  <p className="text-xs font-medium text-amber-600 uppercase tracking-wide">Warnings</p>
                  {validation.warnings.map((w, i) => (
                    <div key={i} className="flex items-start gap-2 text-sm text-amber-700 bg-amber-50 rounded-lg px-3 py-2">
                      <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" />
                      {w}
                    </div>
                  ))}
                </div>
              )}

              {error && (
                <div className="flex items-start gap-2 text-sm text-red-700 bg-red-50 rounded-lg px-3 py-2">
                  <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" />
                  {error}
                </div>
              )}
            </div>

            <div className="flex items-center justify-end gap-3 px-6 py-4 border-t bg-gray-50 rounded-b-xl">
              <button
                onClick={handleClose}
                className="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-200 rounded-lg hover:bg-gray-50 transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleDeploy}
                disabled={!validation.valid}
                className="inline-flex items-center gap-2 px-4 py-2 text-sm font-medium text-white bg-purple-600 rounded-lg hover:bg-purple-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              >
                <Rocket className="w-4 h-4" />
                Confirm Deploy
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default AgentEditor
