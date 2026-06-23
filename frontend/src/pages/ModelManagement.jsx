import React, { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Cpu, Bot, Languages, CheckCircle, XCircle, RefreshCw, Zap,
  ChevronDown, ChevronRight, RotateCcw, Save, Loader2, AlertTriangle,
} from 'lucide-react'
import {
  getModelManagement, setAgentModelOverride, removeAgentModelOverride,
  setTranslationModelOverride, removeTranslationModelOverride, validateProvider,
} from '../services/api'
import PageHeader from '../components/shared/PageHeader'

const SectionCard = ({ title, icon: Icon, children }) => (
  <div className="bg-white rounded-xl border border-gray-100 p-6">
    <div className="flex items-center space-x-2 mb-4">
      <Icon className="w-4 h-4 text-gray-400" />
      <h2 className="text-sm font-medium text-gray-400 uppercase tracking-wide">{title}</h2>
    </div>
    {children}
  </div>
)

const SourceBadge = ({ source }) => {
  const colors = {
    db_override: 'bg-purple-100 text-purple-700',
    override: 'bg-orange-100 text-orange-700',
    profile: 'bg-blue-100 text-blue-700',
    global_default: 'bg-gray-100 text-gray-600',
    env: 'bg-blue-100 text-blue-700',
    legacy: 'bg-yellow-100 text-yellow-700',
    fallback: 'bg-gray-100 text-gray-600',
    unavailable: 'bg-red-100 text-red-700',
  }
  const labels = {
    db_override: 'Override',
    override: 'Env Override',
    profile: 'Profile',
    global_default: 'Default',
    env: 'Env Config',
    legacy: 'Legacy',
    fallback: 'Fallback',
    unavailable: 'Unavailable',
  }
  return (
    <span className={`inline-flex px-2 py-0.5 rounded-full text-xs font-medium ${colors[source] || 'bg-gray-100 text-gray-600'}`}>
      {labels[source] || source}
    </span>
  )
}

const ProviderCard = ({ provider, onValidate, validating, validationResult }) => {
  const isConfigured = provider.api_key_configured
  const models = provider.available_models || []
  const [selectedModel, setSelectedModel] = useState(provider.default_model || '')

  return (
    <div className={`rounded-lg border p-4 ${isConfigured ? 'border-green-200 bg-green-50/30' : 'border-gray-200 bg-gray-50/30'}`}>
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <div className={`w-2.5 h-2.5 rounded-full ${isConfigured ? 'bg-green-500' : 'bg-red-400'}`} />
          <span className="font-medium text-sm">{provider.provider}</span>
        </div>
        <span className="text-xs text-gray-400"><code>{provider.api_key_env}</code></span>
      </div>
      <div className="flex items-center gap-2 mt-2">
        <select
          value={selectedModel}
          onChange={e => setSelectedModel(e.target.value)}
          disabled={!isConfigured}
          className="text-xs border rounded px-2 py-1.5 bg-white flex-1 min-w-0 disabled:opacity-40"
        >
          {models.map(m => (
            <option key={m} value={m}>{m}</option>
          ))}
        </select>
        <button
          onClick={() => onValidate(provider.provider, selectedModel)}
          disabled={!isConfigured || validating}
          className="text-xs px-2.5 py-1.5 rounded bg-white border border-gray-200 hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed flex items-center gap-1"
        >
          {validating ? <Loader2 className="w-3 h-3 animate-spin" /> : <Zap className="w-3 h-3" />}
          Test
        </button>
      </div>
      {validationResult && (
        <div className={`mt-2 text-xs rounded px-2 py-1.5 ${validationResult.valid ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'}`}>
          {validationResult.valid
            ? <span className="flex items-center gap-1"><CheckCircle className="w-3 h-3" /> {validationResult.model} — valid ({validationResult.latency_ms}ms)</span>
            : <span className="flex items-center gap-1"><XCircle className="w-3 h-3" /> {validationResult.error}</span>
          }
        </div>
      )}
    </div>
  )
}

const OverrideForm = ({ providers, currentProvider, currentModel, onSave, onCancel, saving }) => {
  const [provider, setProvider] = useState(currentProvider || '')
  const [model, setModel] = useState(currentModel || '')

  const selectedProvider = providers.find(p => p.provider === provider)
  const availableModels = selectedProvider?.available_models || []

  // When provider changes, auto-select current model if it's available, otherwise pick the first
  const handleProviderChange = (newProvider) => {
    setProvider(newProvider)
    const newProviderData = providers.find(p => p.provider === newProvider)
    const models = newProviderData?.available_models || []
    if (models.length > 0 && !models.includes(model)) {
      setModel(models[0])
    }
  }

  return (
    <div className="flex items-center gap-2 mt-2">
      <select
        value={provider}
        onChange={e => handleProviderChange(e.target.value)}
        className="text-xs border rounded px-2 py-1.5 bg-white"
      >
        <option value="">Select provider...</option>
        {providers.filter(p => p.api_key_configured).map(p => (
          <option key={p.provider} value={p.provider}>{p.provider}</option>
        ))}
      </select>
      <select
        value={model}
        onChange={e => setModel(e.target.value)}
        disabled={!provider}
        className="text-xs border rounded px-2 py-1.5 bg-white flex-1 min-w-0 disabled:opacity-40"
      >
        <option value="">Select model...</option>
        {availableModels.map(m => (
          <option key={m} value={m}>{m}</option>
        ))}
      </select>
      <button
        onClick={() => onSave(provider, model)}
        disabled={!provider || !model || saving}
        className="text-xs px-2 py-1.5 rounded bg-purple-600 text-white hover:bg-purple-700 disabled:opacity-40 flex items-center gap-1"
      >
        {saving ? <Loader2 className="w-3 h-3 animate-spin" /> : <Save className="w-3 h-3" />}
        Save
      </button>
      <button onClick={onCancel} className="text-xs px-2 py-1.5 rounded border hover:bg-gray-50">
        Cancel
      </button>
    </div>
  )
}

const AgentRow = ({ agent, providers, onOverride, onReset, saving }) => {
  const [editing, setEditing] = useState(false)
  const categoryColors = {
    system: 'text-blue-600', execution: 'text-green-600',
    quality: 'text-orange-600', deployment: 'text-purple-600',
  }

  return (
    <div className="rounded-lg hover:bg-gray-50/50 transition-colors px-3 py-2.5">
      <div className="flex items-center gap-3">
        <Bot className={`w-4 h-4 flex-shrink-0 ${categoryColors[agent.category] || 'text-gray-600'}`} />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="font-medium text-sm text-gray-900">{agent.agent_name.replace(/ Agent$/, '')}</span>
            <span className="text-xs text-gray-400 capitalize">{agent.category}</span>
          </div>
          <div className="flex items-center gap-2 mt-0.5">
            <code className="text-xs text-gray-500">
              {agent.resolved_provider}/{agent.resolved_model || 'default'}
            </code>
            <SourceBadge source={agent.source} />
            {agent.override_unavailable && (
              <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-red-100 text-red-700">
                <AlertTriangle className="w-3 h-3" /> Unavailable
              </span>
            )}
          </div>
          {agent.override_unavailable && (
            <div className="mt-1 px-2 py-1.5 rounded bg-amber-50 border border-amber-200 text-xs text-amber-800 flex items-center gap-1.5">
              <AlertTriangle className="w-3.5 h-3.5 flex-shrink-0" />
              <span>
                Provider <strong>{agent.resolved_provider}</strong> API key is not configured.
                {agent.suggested_fallback
                  ? <> Suggested fallback: <code className="font-semibold">{agent.suggested_fallback}</code>. Remove the override or configure the API key.</>
                  : <> Remove the override or configure the API key.</>
                }
              </span>
            </div>
          )}
        </div>
        <div className="flex items-center gap-1">
          {agent.override && (
            <button
              onClick={() => onReset(agent.agent_id)}
              disabled={saving}
              className="text-xs px-2 py-1 rounded border border-gray-200 hover:bg-gray-50 text-gray-500 flex items-center gap-1"
              title="Reset to profile default"
            >
              <RotateCcw className="w-3 h-3" />
            </button>
          )}
          <button
            onClick={() => setEditing(!editing)}
            className="text-xs px-2 py-1 rounded border border-purple-200 hover:bg-purple-50 text-purple-600"
          >
            {editing ? 'Close' : 'Override'}
          </button>
        </div>
      </div>
      {editing && (
        <OverrideForm
          providers={providers}
          currentProvider={agent.override?.provider || agent.resolved_provider}
          currentModel={agent.override?.model || agent.resolved_model || ''}
          onSave={(provider, model) => {
            onOverride(agent.agent_id, provider, model)
            setEditing(false)
          }}
          onCancel={() => setEditing(false)}
          saving={saving}
        />
      )}
    </div>
  )
}

const ModelManagement = () => {
  const queryClient = useQueryClient()
  const [validating, setValidating] = useState({})
  const [validationResults, setValidationResults] = useState({})

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['model-management'],
    queryFn: getModelManagement,
  })

  const agentOverrideMutation = useMutation({
    mutationFn: ({ agentId, provider, model }) => setAgentModelOverride(agentId, provider, model),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['model-management'] }),
  })

  const agentResetMutation = useMutation({
    mutationFn: (agentId) => removeAgentModelOverride(agentId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['model-management'] }),
  })

  const translationOverrideMutation = useMutation({
    mutationFn: ({ provider, model }) => setTranslationModelOverride(provider, model),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['model-management'] }),
  })

  const translationResetMutation = useMutation({
    mutationFn: () => removeTranslationModelOverride(),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['model-management'] }),
  })

  const handleValidate = async (provider, model) => {
    setValidating(prev => ({ ...prev, [provider]: true }))
    try {
      const result = await validateProvider(provider, model)
      setValidationResults(prev => ({ ...prev, [provider]: result }))
    } catch (e) {
      setValidationResults(prev => ({ ...prev, [provider]: { valid: false, error: e.message, latency_ms: 0 } }))
    } finally {
      setValidating(prev => ({ ...prev, [provider]: false }))
    }
  }

  const [editingTranslation, setEditingTranslation] = useState(false)

  if (isLoading) {
    return (
      <div className="space-y-8">
        <PageHeader title="Model Management" subtitle="Configure LLM providers and model assignments." />
        <div className="flex justify-center py-12">
          <Loader2 className="w-6 h-6 animate-spin text-gray-400" />
        </div>
      </div>
    )
  }

  if (isError) {
    return (
      <div className="space-y-8">
        <PageHeader title="Model Management" subtitle="Configure LLM providers and model assignments." />
        <div className="text-center py-12">
          <AlertTriangle className="w-8 h-8 text-red-400 mx-auto mb-2" />
          <p className="text-sm text-red-500 mb-2">Failed to load model configuration</p>
          <button onClick={() => refetch()} className="text-sm text-blue-600 hover:text-blue-700 font-medium">Retry</button>
        </div>
      </div>
    )
  }

  const { agents = [], translation, providers = [] } = data || {}

  const categoryOrder = { system: 0, execution: 1, quality: 2, deployment: 3 }
  const sortedAgents = [...agents].sort((a, b) =>
    (categoryOrder[a.category] ?? 99) - (categoryOrder[b.category] ?? 99) || a.agent_name.localeCompare(b.agent_name)
  )

  const isSaving = agentOverrideMutation.isPending || agentResetMutation.isPending
    || translationOverrideMutation.isPending || translationResetMutation.isPending

  return (
    <div className="space-y-8">
      <PageHeader title="Model Management" subtitle="Configure LLM providers and model assignments per agent.">
        <button
          onClick={() => refetch()}
          className="flex items-center gap-1 text-sm text-gray-500 hover:text-gray-700"
        >
          <RefreshCw className={`w-4 h-4 ${isLoading ? 'animate-spin' : ''}`} />
          Refresh
        </button>
      </PageHeader>

      {/* Providers */}
      <SectionCard title={`Providers (${providers.length})`} icon={Cpu}>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          {providers.map(p => (
            <ProviderCard
              key={p.provider}
              provider={p}
              onValidate={handleValidate}
              validating={!!validating[p.provider]}
              validationResult={validationResults[p.provider]}
            />
          ))}
        </div>
      </SectionCard>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Translation Model */}
        <SectionCard title="Translation Model" icon={Languages}>
          {translation ? (
            <div>
              <div className="flex items-center gap-2 mb-1">
                <code className="text-sm text-gray-700">{translation.provider}/{translation.model}</code>
                <SourceBadge source={translation.source} />
                {translation.override_unavailable && (
                  <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-red-100 text-red-700">
                    <AlertTriangle className="w-3 h-3" /> Unavailable
                  </span>
                )}
              </div>
              {translation.override_unavailable && (
                <div className="mt-1 mb-2 px-2 py-1.5 rounded bg-amber-50 border border-amber-200 text-xs text-amber-800 flex items-center gap-1.5">
                  <AlertTriangle className="w-3.5 h-3.5 flex-shrink-0" />
                  <span>
                    Provider <strong>{translation.provider}</strong> API key is not configured.
                    {translation.suggested_fallback
                      ? <> Suggested fallback: <code className="font-semibold">{translation.suggested_fallback}</code>. Remove the override or configure the API key.</>
                      : <> Remove the override or configure the API key.</>
                    }
                  </span>
                </div>
              )}
              {!translation.override_unavailable && translation.source === 'unavailable' && (
                <p className="text-xs text-red-500 mt-1">No provider available for translation. Configure an API key.</p>
              )}
              <div className="flex items-center gap-2 mt-3">
                <button
                  onClick={() => setEditingTranslation(!editingTranslation)}
                  className="text-xs px-3 py-1.5 rounded border border-purple-200 hover:bg-purple-50 text-purple-600"
                >
                  {editingTranslation ? 'Close' : 'Override'}
                </button>
                {translation.override && (
                  <button
                    onClick={() => translationResetMutation.mutate()}
                    disabled={isSaving}
                    className="text-xs px-3 py-1.5 rounded border border-gray-200 hover:bg-gray-50 text-gray-500 flex items-center gap-1"
                  >
                    <RotateCcw className="w-3 h-3" /> Reset
                  </button>
                )}
              </div>
              {editingTranslation && (
                <OverrideForm
                  providers={providers}
                  currentProvider={translation.override?.provider || translation.provider}
                  currentModel={translation.override?.model || translation.model}
                  onSave={(provider, model) => {
                    translationOverrideMutation.mutate({ provider, model })
                    setEditingTranslation(false)
                  }}
                  onCancel={() => setEditingTranslation(false)}
                  saving={isSaving}
                />
              )}
            </div>
          ) : (
            <p className="text-sm text-gray-400">No translation configuration found.</p>
          )}
        </SectionCard>

        {/* Agent Models */}
        <div className="lg:col-span-2">
          <SectionCard title={`Agent Models (${agents.length})`} icon={Bot}>
            <div className="space-y-1">
              {sortedAgents.map(agent => (
                <AgentRow
                  key={agent.agent_id}
                  agent={agent}
                  providers={providers}
                  onOverride={(agentId, provider, model) =>
                    agentOverrideMutation.mutate({ agentId, provider, model })
                  }
                  onReset={(agentId) => agentResetMutation.mutate(agentId)}
                  saving={isSaving}
                />
              ))}
            </div>
          </SectionCard>
        </div>
      </div>
    </div>
  )
}

export default ModelManagement
