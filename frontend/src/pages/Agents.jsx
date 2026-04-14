/**
 * Agents Page - View built-in agents and manage custom agents
 */

import React, { useState, useCallback } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import {
  Bot,
  Plus,
  Trash2,
  Download,
  Search,
  Cpu,
  ChevronDown,
  ChevronRight,
  Loader2,
  AlertCircle,
  CheckCircle,
  XCircle,
  Rocket,
  FileCode,
  X,
  Copy,
  Save,
} from 'lucide-react'
import { getAgents, getCustomAgents, deleteCustomAgent, getCustomAgentYaml, deployCustomAgent, updateCustomAgent } from '../services/api'
import PageHeader from '../components/shared/PageHeader'

const CATEGORY_COLORS = {
  system: 'bg-purple-100 text-purple-700',
  execution: 'bg-blue-100 text-blue-700',
  quality: 'bg-green-100 text-green-700',
  deployment: 'bg-orange-100 text-orange-700',
}

const SectionCard = ({ title, icon: Icon, actions, children }) => (
  <div className="bg-white rounded-xl border border-gray-100 p-6">
    <div className="flex items-center justify-between mb-4">
      <div className="flex items-center space-x-2">
        <Icon className="w-4 h-4 text-gray-400" />
        <h2 className="text-sm font-medium text-gray-400 uppercase tracking-wide">{title}</h2>
      </div>
      {actions}
    </div>
    {children}
  </div>
)

const CategoryBadge = ({ category }) => (
  <span
    className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${
      CATEGORY_COLORS[category] || 'bg-gray-100 text-gray-700'
    }`}
  >
    {category}
  </span>
)

// Built-in agent row (read-only, expandable)
const BuiltinAgentRow = ({ agent }) => {
  const [expanded, setExpanded] = useState(false)

  return (
    <div className="rounded-lg hover:bg-gray-50/50 transition-colors">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center gap-3 px-3 py-2.5 text-left"
      >
        <Bot className="w-4 h-4 flex-shrink-0 text-gray-400" />
        <span className="font-medium text-sm text-gray-900 flex-1">{agent.name}</span>
        <CategoryBadge category={agent.category} />
        {expanded ? (
          <ChevronDown className="w-3.5 h-3.5 text-gray-400" />
        ) : (
          <ChevronRight className="w-3.5 h-3.5 text-gray-400" />
        )}
      </button>
      {expanded && (
        <div className="px-3 pb-2.5 pl-11 space-y-2">
          <p className="text-xs text-gray-500">{agent.description}</p>
          {agent.model && (
            <div className="flex flex-wrap gap-3 text-xs text-gray-400">
              <span className="flex items-center">
                <Cpu className="w-3 h-3 mr-1" />
                {agent.model}
              </span>
              {agent.temperature !== null && agent.temperature !== undefined && (
                <span>temp: {agent.temperature}</span>
              )}
              {agent.max_tokens && <span>max: {agent.max_tokens}</span>}
            </div>
          )}
          {agent.mcps?.length > 0 && (
            <div className="flex flex-wrap gap-1">
              {agent.mcps.map((mcp) => (
                <span
                  key={mcp}
                  className="px-2 py-0.5 bg-gray-100 text-gray-500 rounded text-xs"
                >
                  {mcp}
                </span>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// Custom agent card with deploy, YAML edit, download, delete, active toggle
const CustomAgentCard = ({ agent, onEdit, onDelete, onDownloadYaml, onDeploy, onViewYaml, onToggleActive, isDeleting, isDeploying }) => (
  <div
    onClick={() => onEdit(agent.agent_id)}
    className="bg-gray-50/70 rounded-lg p-4 border border-gray-100 hover:border-gray-200 hover:bg-gray-50 transition-colors cursor-pointer"
  >
    <div className="flex items-start justify-between">
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="font-medium text-gray-900 text-sm">{agent.name}</span>
          <CategoryBadge category={agent.category} />
          <button
            onClick={(e) => { e.stopPropagation(); onToggleActive(agent.agent_id, !agent.is_active) }}
            className={`inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full transition-colors ${
              agent.is_active
                ? 'bg-green-100 text-green-700 hover:bg-green-200'
                : 'bg-gray-100 text-gray-400 hover:bg-gray-200'
            }`}
            title={agent.is_active ? 'Click to deactivate' : 'Click to activate'}
          >
            {agent.is_active ? <CheckCircle className="w-3 h-3" /> : <XCircle className="w-3 h-3" />}
            {agent.is_active ? 'Active' : 'Inactive'}
          </button>
          {agent.deployment_status && (
            <span
              className={`inline-flex items-center gap-1 text-xs ${
                agent.deployment_status === 'deployed' ? 'text-green-600' :
                agent.deployment_status === 'failed' ? 'text-red-500' : 'text-gray-400'
              }`}
            >
              {agent.deployment_status === 'deployed' ? <CheckCircle className="w-3 h-3" /> :
               agent.deployment_status === 'failed' ? <XCircle className="w-3 h-3" /> : null}
              {agent.deployment_status}
            </span>
          )}
        </div>
        <p className="text-xs text-gray-500 mt-1 font-mono">{agent.agent_id}</p>
        {agent.llm_profile && (
          <p className="text-xs text-gray-400 mt-1">Profile: {agent.llm_profile}</p>
        )}
        {agent.description && (
          <p className="text-xs text-gray-500 mt-2 line-clamp-2">{agent.description}</p>
        )}
      </div>
      <div className="flex items-center gap-1 ml-3">
        <button
          onClick={(e) => { e.stopPropagation(); onDeploy(agent.agent_id) }}
          disabled={isDeploying}
          className="p-1.5 text-gray-400 hover:text-purple-600 hover:bg-purple-50 rounded transition-colors"
          title="Deploy to Foundry"
        >
          {isDeploying ? <Loader2 className="w-4 h-4 animate-spin" /> : <Rocket className="w-4 h-4" />}
        </button>
        <button
          onClick={(e) => { e.stopPropagation(); onViewYaml(agent.agent_id) }}
          className="p-1.5 text-gray-400 hover:text-blue-600 hover:bg-blue-50 rounded transition-colors"
          title="Edit YAML"
        >
          <FileCode className="w-4 h-4" />
        </button>
        <button
          onClick={(e) => { e.stopPropagation(); onDownloadYaml(agent.agent_id, agent.name) }}
          className="p-1.5 text-gray-400 hover:text-blue-600 hover:bg-blue-50 rounded transition-colors"
          title="Download YAML"
        >
          <Download className="w-4 h-4" />
        </button>
        <button
          onClick={(e) => { e.stopPropagation(); onDelete(agent.agent_id) }}
          disabled={isDeleting}
          className="p-1.5 text-gray-400 hover:text-red-600 hover:bg-red-50 rounded transition-colors"
          title="Delete agent"
        >
          {isDeleting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Trash2 className="w-4 h-4" />}
        </button>
      </div>
    </div>
  </div>
)

// YAML editor modal
const YamlEditorModal = ({ agentId, onClose, onSaved }) => {
  const [yaml, setYaml] = useState(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [copied, setCopied] = useState(false)
  const [error, setError] = useState(null)
  const [dirty, setDirty] = useState(false)

  const loadYaml = useCallback(async () => {
    try {
      const result = await getCustomAgentYaml(agentId)
      setYaml(result.yaml)
    } catch {
      setYaml('# Failed to load YAML')
    } finally {
      setLoading(false)
    }
  }, [agentId])

  useState(() => { loadYaml() })

  const handleSave = async () => {
    setSaving(true)
    setError(null)
    try {
      // Parse YAML to JSON and send as update
      const lines = yaml.split('\n')
      const parsed = {}
      let currentKey = null
      let multiline = []

      // Simple YAML parser for flat + multiline string fields
      for (const line of lines) {
        if (line.startsWith('#') || line.trim() === '') continue
        const match = line.match(/^(\w+):\s*(.*)$/)
        if (match) {
          if (currentKey && multiline.length > 0) {
            parsed[currentKey] = multiline.join('\n')
            multiline = []
          }
          currentKey = match[1]
          const val = match[2]
          if (val === '|' || val === '>') {
            multiline = []
          } else {
            parsed[currentKey] = val
            currentKey = null
          }
        } else if (currentKey) {
          multiline.push(line.replace(/^ {2}/, ''))
        }
      }
      if (currentKey && multiline.length > 0) {
        parsed[currentKey] = multiline.join('\n')
      }

      await updateCustomAgent(agentId, parsed)
      setDirty(false)
      onSaved?.()
    } catch (err) {
      setError(err.message || 'Failed to save')
    } finally {
      setSaving(false)
    }
  }

  const handleCopy = () => {
    if (!yaml) return
    navigator.clipboard.writeText(yaml)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
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

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={onClose}>
      <div className="bg-white rounded-xl shadow-xl w-full max-w-4xl max-h-[85vh] flex flex-col m-4" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between px-6 py-4 border-b">
          <h3 className="text-sm font-medium text-gray-900">{agentId}.yaml {dirty && <span className="text-yellow-500 ml-1">(unsaved)</span>}</h3>
          <div className="flex items-center gap-2">
            <button onClick={handleSave} disabled={saving || !dirty} className="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium text-white bg-blue-600 rounded-lg hover:bg-blue-700 disabled:opacity-50 transition-colors" title="Save">
              {saving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5" />}
              Save
            </button>
            <button onClick={handleCopy} className="p-1.5 text-gray-400 hover:text-blue-600 rounded transition-colors" title="Copy">
              {copied ? <CheckCircle className="w-4 h-4 text-green-500" /> : <Copy className="w-4 h-4" />}
            </button>
            <button onClick={handleDownload} className="p-1.5 text-gray-400 hover:text-blue-600 rounded transition-colors" title="Download">
              <Download className="w-4 h-4" />
            </button>
            <button onClick={onClose} className="p-1.5 text-gray-400 hover:text-gray-600 rounded transition-colors">
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>
        {error && (
          <div className="mx-6 mt-3 bg-red-50 border border-red-200 rounded-lg p-2">
            <p className="text-sm text-red-700">{error}</p>
          </div>
        )}
        <div className="flex-1 overflow-auto p-0">
          {loading ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="w-5 h-5 animate-spin text-gray-400" />
            </div>
          ) : (
            <textarea
              value={yaml}
              onChange={(e) => { setYaml(e.target.value); setDirty(true) }}
              className="w-full h-full min-h-[60vh] p-6 font-mono text-sm text-gray-800 border-none outline-none resize-none"
              spellCheck={false}
            />
          )}
        </div>
      </div>
    </div>
  )
}

const Agents = () => {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [filter, setFilter] = useState('')
  const [deletingId, setDeletingId] = useState(null)
  const [deployingId, setDeployingId] = useState(null)
  const [yamlEditorId, setYamlEditorId] = useState(null)

  const {
    data: builtinAgents = [],
    isLoading: builtinLoading,
    isError: builtinError,
    refetch: refetchBuiltin,
  } = useQuery({
    queryKey: ['agents'],
    queryFn: getAgents,
  })

  const {
    data: customAgentsData,
    isLoading: customLoading,
    isError: customError,
    refetch: refetchCustom,
  } = useQuery({
    queryKey: ['custom-agents'],
    queryFn: getCustomAgents,
  })

  const customAgents = customAgentsData?.agents || customAgentsData || []

  const deleteMutation = useMutation({
    mutationFn: deleteCustomAgent,
    onMutate: (agentId) => setDeletingId(agentId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['custom-agents'] })
      setDeletingId(null)
    },
    onError: () => {
      setDeletingId(null)
    },
  })

  const handleDelete = (agentId) => {
    if (window.confirm(`Delete custom agent "${agentId}"? This cannot be undone.`)) {
      deleteMutation.mutate(agentId)
    }
  }

  const handleDownloadYaml = async (agentId, agentName) => {
    try {
      const result = await getCustomAgentYaml(agentId)
      const blob = new Blob([result.yaml], { type: 'application/x-yaml' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `${agentId}.yaml`
      a.click()
      URL.revokeObjectURL(url)
    } catch {
      alert(`Failed to download YAML for ${agentName}`)
    }
  }

  const handleToggleActive = async (agentId, isActive) => {
    try {
      await updateCustomAgent(agentId, { is_active: isActive })
      queryClient.invalidateQueries({ queryKey: ['custom-agents'] })
    } catch (err) {
      alert(`Failed to update: ${err.message || 'Unknown error'}`)
    }
  }

  const handleDeploy = async (agentId) => {
    setDeployingId(agentId)
    try {
      await deployCustomAgent(agentId)
      queryClient.invalidateQueries({ queryKey: ['custom-agents'] })
    } catch (err) {
      alert(`Deploy failed: ${err.message || 'Unknown error'}`)
    } finally {
      setDeployingId(null)
    }
  }

  const filteredBuiltin = filter
    ? builtinAgents.filter(
        (a) =>
          a.name?.toLowerCase().includes(filter.toLowerCase()) ||
          a.id?.toLowerCase().includes(filter.toLowerCase()) ||
          a.category?.toLowerCase().includes(filter.toLowerCase())
      )
    : builtinAgents

  const filteredCustom = filter
    ? customAgents.filter(
        (a) =>
          a.name?.toLowerCase().includes(filter.toLowerCase()) ||
          a.agent_id?.toLowerCase().includes(filter.toLowerCase()) ||
          a.category?.toLowerCase().includes(filter.toLowerCase())
      )
    : customAgents

  return (
    <div className="space-y-8">
      <PageHeader
        title="Agents"
        subtitle="Manage built-in and custom agent definitions."
        icon={Bot}
      />

      {/* Search */}
      <div className="relative max-w-sm">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
        <input
          type="text"
          placeholder="Filter agents..."
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          className="w-full pl-9 pr-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
        />
      </div>

      {/* Built-in Agents */}
      <SectionCard title={`Built-in Agents (${filteredBuiltin.length})`} icon={Bot}>
        {builtinLoading ? (
          <div className="space-y-3">
            {[1, 2, 3].map((i) => (
              <div key={i} className="animate-pulse h-10 bg-gray-100 rounded-lg" />
            ))}
          </div>
        ) : builtinError ? (
          <div className="text-center py-4">
            <p className="text-sm text-red-500 mb-2">Failed to load built-in agents</p>
            <button
              onClick={() => refetchBuiltin()}
              className="text-sm text-blue-600 hover:text-blue-700 font-medium"
            >
              Retry
            </button>
          </div>
        ) : filteredBuiltin.length === 0 ? (
          <div className="text-gray-400 text-sm py-4 text-center">
            {filter ? 'No built-in agents match your filter.' : 'No built-in agents configured.'}
          </div>
        ) : (
          <div className="space-y-1">
            {filteredBuiltin.map((agent) => (
              <BuiltinAgentRow key={agent.id} agent={agent} />
            ))}
          </div>
        )}
      </SectionCard>

      {/* Custom Agents */}
      <SectionCard
        title={`Custom Agents (${filteredCustom.length})`}
        icon={Bot}
        actions={
          <button
            onClick={() => navigate('/agents/new')}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium text-white bg-blue-600 rounded-lg hover:bg-blue-700 transition-colors"
          >
            <Plus className="w-4 h-4" />
            Create Agent
          </button>
        }
      >
        {customLoading ? (
          <div className="space-y-3">
            {[1, 2, 3].map((i) => (
              <div key={i} className="animate-pulse h-20 bg-gray-100 rounded-lg" />
            ))}
          </div>
        ) : customError ? (
          <div className="text-center py-4">
            <p className="text-sm text-red-500 mb-2">Failed to load custom agents</p>
            <button
              onClick={() => refetchCustom()}
              className="text-sm text-blue-600 hover:text-blue-700 font-medium"
            >
              Retry
            </button>
          </div>
        ) : filteredCustom.length === 0 ? (
          <div className="text-center py-8 text-gray-400">
            <Bot className="w-10 h-10 mx-auto mb-2 opacity-30" />
            <p className="text-sm">
              {filter ? 'No custom agents match your filter.' : 'No custom agents yet.'}
            </p>
            {!filter && (
              <button
                onClick={() => navigate('/agents/new')}
                className="mt-3 text-sm text-blue-600 hover:text-blue-700 font-medium"
              >
                Create your first agent
              </button>
            )}
          </div>
        ) : (
          <div className="space-y-3">
            {filteredCustom.map((agent) => (
              <CustomAgentCard
                key={agent.agent_id}
                agent={agent}
                onEdit={(id) => navigate(`/agents/${id}/edit`)}
                onDelete={handleDelete}
                onDownloadYaml={handleDownloadYaml}
                onDeploy={handleDeploy}
                onViewYaml={(id) => setYamlEditorId(id)}
                onToggleActive={handleToggleActive}
                isDeleting={deletingId === agent.agent_id}
                isDeploying={deployingId === agent.agent_id}
              />
            ))}
          </div>
        )}
      </SectionCard>

      {yamlEditorId && (
        <YamlEditorModal
          agentId={yamlEditorId}
          onClose={() => setYamlEditorId(null)}
          onSaved={() => queryClient.invalidateQueries({ queryKey: ['custom-agents'] })}
        />
      )}
    </div>
  )
}

export default Agents
