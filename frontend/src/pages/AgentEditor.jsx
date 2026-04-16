/**
 * Agent Editor Page - Create or edit custom agent definitions
 */

import React, { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  ArrowLeft,
  Save,
  Loader2,
  AlertCircle,
  Plus,
  Trash2,
  Bot,
  Rocket,
  FileCode,
  Download,
  X,
  Copy,
  CheckCircle,
} from 'lucide-react'
import {
  getCustomAgent,
  createCustomAgent,
  updateCustomAgent,
  getAgentMetadata,
  deployCustomAgent,
  getCustomAgentYaml,
} from '../services/api'

const SectionCard = ({ title, children }) => (
  <div className="bg-white rounded-xl border border-gray-100 p-6">
    <h3 className="text-sm font-medium text-gray-400 uppercase tracking-wide mb-4">{title}</h3>
    {children}
  </div>
)

const CATEGORIES = [
  { value: 'execution', label: 'Execution' },
  { value: 'quality', label: 'Quality' },
  { value: 'deployment', label: 'Deployment' },
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
    system_prompt_fragments: [],
    mcps: [],
    mcp_tool_filters: {},
    builtin_tools: [],
    skills: [],
    foundry_tools: [],
    llm_profile: '',
    temperature: 0.7,
    max_tokens: '',
    max_iterations: '',
    approval_overrides: [],
  })
  const [errors, setErrors] = useState({})

  // Load metadata for dropdown options
  const { data: metadata, isLoading: metaLoading } = useQuery({
    queryKey: ['agent-metadata'],
    queryFn: getAgentMetadata,
  })

  // Load existing agent when editing
  const { data: existingAgent, isLoading: agentLoading } = useQuery({
    queryKey: ['custom-agent', agentId],
    queryFn: () => getCustomAgent(agentId),
    enabled: isEdit,
  })

  // Populate form when agent loads
  useEffect(() => {
    if (existingAgent) {
      setForm({
        agent_id: existingAgent.agent_id || '',
        name: existingAgent.name || '',
        description: existingAgent.description || '',
        category: existingAgent.category || 'execution',
        system_prompt: existingAgent.system_prompt || '',
        system_prompt_fragments: existingAgent.system_prompt_fragments || [],
        mcps: existingAgent.mcps || [],
        mcp_tool_filters: existingAgent.mcp_tool_filters || {},
        builtin_tools: existingAgent.builtin_tools || [],
        skills: existingAgent.skills || [],
        foundry_tools: existingAgent.foundry_tools || [],
        llm_profile: existingAgent.llm_profile || '',
        temperature: existingAgent.temperature ?? 0.7,
        max_tokens: existingAgent.max_tokens || '',
        max_iterations: existingAgent.max_iterations || '',
        approval_overrides: existingAgent.approval_overrides || [],
      })
    }
  }, [existingAgent])

  const createMutation = useMutation({
    mutationFn: (data) => createCustomAgent(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['custom-agents'] })
      navigate('/agents')
    },
    onError: (err) => {
      setErrors({ submit: err.message })
    },
  })

  const updateMutation = useMutation({
    mutationFn: (data) => updateCustomAgent(agentId, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['custom-agents'] })
      queryClient.invalidateQueries({ queryKey: ['custom-agent', agentId] })
      navigate('/agents')
    },
    onError: (err) => {
      setErrors({ submit: err.message })
    },
  })

  const isSaving = createMutation.isPending || updateMutation.isPending

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
      temperature: parseFloat(form.temperature) || 0.7,
      max_tokens: form.max_tokens ? parseInt(form.max_tokens, 10) : undefined,
      max_iterations: form.max_iterations ? parseInt(form.max_iterations, 10) : undefined,
      approval_overrides: form.approval_overrides.filter((o) => o.tool_key.trim()),
    }

    // Clean undefined fields
    if (!payload.max_tokens) delete payload.max_tokens
    if (!payload.max_iterations) delete payload.max_iterations

    if (isEdit) {
      updateMutation.mutate(payload)
    } else {
      createMutation.mutate(payload)
    }
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

  const toggleMcpTool = (mcpName, toolName) => {
    setForm((prev) => {
      const filters = { ...prev.mcp_tool_filters }
      const current = filters[mcpName] || []
      if (current.includes(toolName)) {
        filters[mcpName] = current.filter((t) => t !== toolName)
        if (filters[mcpName].length === 0) delete filters[mcpName]
      } else {
        filters[mcpName] = [...current, toolName]
      }
      return { ...prev, mcp_tool_filters: filters }
    })
  }

  const addApprovalOverride = () => {
    setForm((prev) => ({
      ...prev,
      approval_overrides: [
        ...prev.approval_overrides,
        { tool_key: '', requires_approval: true, required_role: '' },
      ],
    }))
  }

  const updateApprovalOverride = (index, field, value) => {
    setForm((prev) => ({
      ...prev,
      approval_overrides: prev.approval_overrides.map((item, i) =>
        i === index ? { ...item, [field]: value } : item
      ),
    }))
  }

  const removeApprovalOverride = (index) => {
    setForm((prev) => ({
      ...prev,
      approval_overrides: prev.approval_overrides.filter((_, i) => i !== index),
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

  const metaSystemPrompts = metadata?.system_prompts || []
  const metaMcps = metadata?.mcps || []
  const metaBuiltinTools = metadata?.builtin_tools || []
  const metaSkills = metadata?.skills || []
  const metaFoundryTools = metadata?.foundry_tools || []
  const metaLlmProfiles = metadata?.llm_profiles || []

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center space-x-4">
        <button
          onClick={() => navigate('/agents')}
          className="p-2 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded-lg transition-colors"
          aria-label="Back to agents"
        >
          <ArrowLeft className="w-5 h-5" />
        </button>
        <Bot className="w-6 h-6 text-gray-400" />
        <h1 className="text-2xl font-bold text-gray-900">
          {isEdit ? `Edit Agent: ${agentId}` : 'Create Agent'}
        </h1>
      </div>

      {errors.submit && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-4 flex items-start gap-3">
          <AlertCircle className="w-5 h-5 text-red-500 flex-shrink-0 mt-0.5" />
          <p className="text-sm text-red-700">{errors.submit}</p>
        </div>
      )}

      <form onSubmit={handleSubmit} className="space-y-6">
        {/* Basic Info */}
        <SectionCard title="Basic Info">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Agent ID</label>
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
              {errors.agent_id && (
                <p className="text-xs text-red-500 mt-1">{errors.agent_id}</p>
              )}
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Name</label>
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
            <div className="md:col-span-2">
              <label className="block text-sm font-medium text-gray-700 mb-1">Description</label>
              <textarea
                value={form.description}
                onChange={(e) => updateField('description', e.target.value)}
                placeholder="What does this agent do?"
                rows={2}
                className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent resize-vertical"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Category</label>
              <select
                value={form.category}
                onChange={(e) => updateField('category', e.target.value)}
                className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              >
                {CATEGORIES.map((cat) => (
                  <option key={cat.value} value={cat.value}>
                    {cat.label}
                  </option>
                ))}
              </select>
            </div>
          </div>
        </SectionCard>

        {/* System Prompt */}
        <SectionCard title="System Prompt">
          <textarea
            value={form.system_prompt}
            onChange={(e) => updateField('system_prompt', e.target.value)}
            placeholder="Enter the system prompt for this agent..."
            rows={12}
            className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent resize-vertical font-mono"
            style={{ minHeight: '300px' }}
          />
        </SectionCard>

        {/* System Prompt Fragments */}
        {metaSystemPrompts.length > 0 && (
          <SectionCard title="System Prompt Fragments">
            <p className="text-xs text-gray-500 mb-3">
              Select reusable prompt fragments to include with this agent.
            </p>
            <div className="space-y-2">
              {metaSystemPrompts.map((fragment) => {
                const key = typeof fragment === 'string' ? fragment : fragment.id || fragment.name
                const label = typeof fragment === 'string' ? fragment : fragment.name || fragment.id
                return (
                  <label key={key} className="flex items-center gap-2 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={form.system_prompt_fragments.includes(key)}
                      onChange={() => toggleArrayItem('system_prompt_fragments', key)}
                      className="w-4 h-4 text-blue-600 border-gray-300 rounded focus:ring-blue-500"
                    />
                    <span className="text-sm text-gray-700">{label}</span>
                  </label>
                )
              })}
            </div>
          </SectionCard>
        )}

        {/* MCP Servers */}
        {metaMcps.length > 0 && (
          <SectionCard title="MCP Servers">
            <p className="text-xs text-gray-500 mb-3">
              Select which MCP servers this agent can access.
            </p>
            <div className="space-y-3">
              {metaMcps.map((mcp) => {
                const mcpName = typeof mcp === 'string' ? mcp : mcp.name || mcp.id
                const mcpTools = typeof mcp === 'object' ? mcp.tools || [] : []
                const isChecked = form.mcps.includes(mcpName)
                return (
                  <div key={mcpName}>
                    <label className="flex items-center gap-2 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={isChecked}
                        onChange={() => toggleArrayItem('mcps', mcpName)}
                        className="w-4 h-4 text-blue-600 border-gray-300 rounded focus:ring-blue-500"
                      />
                      <span className="text-sm text-gray-700 font-medium">{mcpName}</span>
                    </label>
                    {isChecked && mcpTools.length > 0 && (
                      <div className="ml-6 mt-1.5 flex flex-wrap gap-x-4 gap-y-1">
                        {mcpTools.map((tool) => {
                          const toolName = typeof tool === 'string' ? tool : tool.name
                          const selectedTools = form.mcp_tool_filters[mcpName] || []
                          return (
                            <label
                              key={toolName}
                              className="flex items-center gap-1.5 cursor-pointer"
                            >
                              <input
                                type="checkbox"
                                checked={selectedTools.includes(toolName)}
                                onChange={() => toggleMcpTool(mcpName, toolName)}
                                className="w-3.5 h-3.5 text-blue-600 border-gray-300 rounded focus:ring-blue-500"
                              />
                              <span className="text-xs text-gray-500">{toolName}</span>
                            </label>
                          )
                        })}
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          </SectionCard>
        )}

        {/* Builtin Tools */}
        {metaBuiltinTools.length > 0 && (
          <SectionCard title="Built-in Tools">
            <div className="flex flex-wrap gap-x-4 gap-y-2">
              {metaBuiltinTools.map((tool) => {
                const toolName = typeof tool === 'string' ? tool : tool.name || tool.id
                return (
                  <label key={toolName} className="flex items-center gap-2 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={form.builtin_tools.includes(toolName)}
                      onChange={() => toggleArrayItem('builtin_tools', toolName)}
                      className="w-4 h-4 text-blue-600 border-gray-300 rounded focus:ring-blue-500"
                    />
                    <span className="text-sm text-gray-700">{toolName}</span>
                  </label>
                )
              })}
            </div>
          </SectionCard>
        )}

        {/* Skills */}
        {metaSkills.length > 0 && (
          <SectionCard title="Skills">
            <div className="flex flex-wrap gap-x-4 gap-y-2">
              {metaSkills.map((skill) => {
                const skillName = typeof skill === 'string' ? skill : skill.name || skill.id
                return (
                  <label key={skillName} className="flex items-center gap-2 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={form.skills.includes(skillName)}
                      onChange={() => toggleArrayItem('skills', skillName)}
                      className="w-4 h-4 text-blue-600 border-gray-300 rounded focus:ring-blue-500"
                    />
                    <span className="text-sm text-gray-700">{skillName}</span>
                  </label>
                )
              })}
            </div>
          </SectionCard>
        )}

        {/* Foundry Tools */}
        {metaFoundryTools.length > 0 && (
          <SectionCard title="Foundry Tools">
            <p className="text-xs text-gray-500 mb-3">
              Azure AI Foundry native tools for deployed agents.
            </p>
            <div className="flex flex-wrap gap-x-4 gap-y-2">
              {metaFoundryTools.map((tool) => (
                <label key={tool} className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={form.foundry_tools.includes(tool)}
                    onChange={() => toggleArrayItem('foundry_tools', tool)}
                    className="w-4 h-4 text-purple-600 border-gray-300 rounded focus:ring-purple-500"
                  />
                  <span className="text-sm text-gray-700">{tool}</span>
                </label>
              ))}
            </div>
          </SectionCard>
        )}

        {/* LLM Settings */}
        <SectionCard title="LLM Settings">
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">LLM Profile</label>
              {metaLlmProfiles.length > 0 ? (
                <select
                  value={form.llm_profile}
                  onChange={(e) => updateField('llm_profile', e.target.value)}
                  className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                >
                  <option value="">Default</option>
                  {metaLlmProfiles.map((profile) => {
                    const val = typeof profile === 'string' ? profile : profile.name || profile.id
                    return (
                      <option key={val} value={val}>
                        {val}
                      </option>
                    )
                  })}
                </select>
              ) : (
                <input
                  type="text"
                  value={form.llm_profile}
                  onChange={(e) => updateField('llm_profile', e.target.value)}
                  placeholder="e.g. gpt-4o"
                  className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                />
              )}
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Temperature</label>
              <input
                type="number"
                value={form.temperature}
                onChange={(e) => updateField('temperature', e.target.value)}
                min="0"
                max="1"
                step="0.1"
                className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Max Tokens</label>
              <input
                type="number"
                value={form.max_tokens}
                onChange={(e) => updateField('max_tokens', e.target.value)}
                placeholder="e.g. 4096"
                className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Max Iterations
              </label>
              <input
                type="number"
                value={form.max_iterations}
                onChange={(e) => updateField('max_iterations', e.target.value)}
                placeholder="e.g. 10"
                className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              />
            </div>
          </div>
        </SectionCard>

        {/* Approval Overrides */}
        <SectionCard title="Approval Overrides">
          <p className="text-xs text-gray-500 mb-3">
            Override default approval settings for specific tools.
          </p>
          {form.approval_overrides.length > 0 && (
            <div className="space-y-2 mb-3">
              {form.approval_overrides.map((override, index) => (
                <div key={index} className="flex items-center gap-3 bg-gray-50 rounded-lg p-3">
                  <div className="flex-1">
                    <input
                      type="text"
                      value={override.tool_key}
                      onChange={(e) =>
                        updateApprovalOverride(index, 'tool_key', e.target.value)
                      }
                      placeholder="e.g. coding:write_file"
                      className="w-full px-3 py-1.5 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent font-mono"
                    />
                  </div>
                  <label className="flex items-center gap-1.5 cursor-pointer flex-shrink-0">
                    <input
                      type="checkbox"
                      checked={override.requires_approval}
                      onChange={(e) =>
                        updateApprovalOverride(index, 'requires_approval', e.target.checked)
                      }
                      className="w-4 h-4 text-blue-600 border-gray-300 rounded focus:ring-blue-500"
                    />
                    <span className="text-xs text-gray-600">Requires Approval</span>
                  </label>
                  <div className="w-40">
                    <input
                      type="text"
                      value={override.required_role}
                      onChange={(e) =>
                        updateApprovalOverride(index, 'required_role', e.target.value)
                      }
                      placeholder="Required role"
                      className="w-full px-3 py-1.5 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                    />
                  </div>
                  <button
                    type="button"
                    onClick={() => removeApprovalOverride(index)}
                    className="p-1.5 text-gray-400 hover:text-red-600 hover:bg-red-50 rounded transition-colors"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>
              ))}
            </div>
          )}
          <button
            type="button"
            onClick={addApprovalOverride}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm text-gray-600 bg-gray-100 rounded-lg hover:bg-gray-200 transition-colors"
          >
            <Plus className="w-4 h-4" />
            Add Override
          </button>
        </SectionCard>

        {/* Actions */}
        <div className="flex items-center gap-3 pt-2">
          <button
            type="submit"
            disabled={isSaving}
            className="inline-flex items-center gap-2 px-5 py-2.5 text-sm font-medium text-white bg-blue-600 rounded-lg hover:bg-blue-700 disabled:opacity-50 transition-colors"
          >
            {isSaving ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Save className="w-4 h-4" />
            )}
            {isEdit ? 'Update Agent' : 'Create Agent'}
          </button>
          <button
            type="button"
            onClick={() => navigate('/agents')}
            className="px-5 py-2.5 text-sm font-medium text-gray-700 bg-white border border-gray-200 rounded-lg hover:bg-gray-50 transition-colors"
          >
            Cancel
          </button>
          {isEdit && (
            <>
              <YamlViewerButton agentId={agentId} />
              <DeployButton agentId={agentId} />
            </>
          )}
        </div>
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
        className="inline-flex items-center gap-2 px-5 py-2.5 text-sm font-medium text-gray-700 bg-white border border-gray-200 rounded-lg hover:bg-gray-50 transition-colors"
      >
        <FileCode className="w-4 h-4" />
        View YAML
      </button>

      {open && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={() => setOpen(false)}>
          <div className="bg-white rounded-xl shadow-xl w-full max-w-3xl max-h-[80vh] flex flex-col m-4" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between px-6 py-4 border-b">
              <h3 className="text-sm font-medium text-gray-900">Agent Definition — {agentId}.yaml</h3>
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
  const [deploying, setDeploying] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)

  const handleDeploy = async () => {
    setDeploying(true)
    setError(null)
    setResult(null)
    try {
      const data = await deployCustomAgent(agentId)
      setResult(data)
    } catch (err) {
      setError(err.message || 'Deployment failed')
    } finally {
      setDeploying(false)
    }
  }

  return (
    <div className="ml-auto flex items-center gap-3">
      <button
        type="button"
        onClick={handleDeploy}
        disabled={deploying}
        className="inline-flex items-center gap-2 px-5 py-2.5 text-sm font-medium text-white bg-purple-600 rounded-lg hover:bg-purple-700 disabled:opacity-50 transition-colors"
      >
        {deploying ? (
          <Loader2 className="w-4 h-4 animate-spin" />
        ) : (
          <Rocket className="w-4 h-4" />
        )}
        Deploy to Foundry
      </button>
      {result && (
        <span className="text-sm text-green-600">
          Deployed v{result.version || '1'}
        </span>
      )}
      {error && (
        <span className="text-sm text-red-600">{error}</span>
      )}
    </div>
  )
}

export default AgentEditor
