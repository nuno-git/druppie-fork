import React, { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Cpu, Bot, Languages, CheckCircle, XCircle, RefreshCw, Zap,
  ChevronDown, ChevronRight, RotateCcw, Save, Loader2, AlertTriangle,
  Server, Activity, Terminal,
} from 'lucide-react'
import {
  getModelManagement, setAgentModelOverride, removeAgentModelOverride,
  setTranslationModelOverride, removeTranslationModelOverride, validateProvider,
  getLocalModelStatus, getLocalModelLogs, loadModel,
} from '../services/api'
import PageHeader from '../components/shared/PageHeader'
import VersionBadge from '../components/shared/VersionBadge'

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

const ProviderCard = ({ provider, onValidate, validating, cooldown, validationResult }) => {
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
          disabled={!isConfigured || validating || cooldown}
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

const OverrideForm = ({ providers, currentProvider, currentModel, currentFallbackProvider, currentFallbackModel, onSave, onCancel, saving }) => {
  const [provider, setProvider] = useState(currentProvider || '')
  const [model, setModel] = useState(currentModel || '')
  const [customFallback, setCustomFallback] = useState(!!currentFallbackProvider)
  const [fbProvider, setFbProvider] = useState(currentFallbackProvider || '')
  const [fbModel, setFbModel] = useState(currentFallbackModel || '')

  const selectedProvider = providers.find(p => p.provider === provider)
  const availableModels = selectedProvider?.available_models || []

  const fbProviderData = providers.find(p => p.provider === fbProvider)
  const fbAvailableModels = fbProviderData?.available_models || []

  const handleProviderChange = (newProvider) => {
    setProvider(newProvider)
    const newProviderData = providers.find(p => p.provider === newProvider)
    const models = newProviderData?.available_models || []
    const newModel = (models.length > 0 && !models.includes(model)) ? models[0] : model
    if (newModel !== model) setModel(newModel)
    if (newProvider === fbProvider) { setFbProvider(''); setFbModel('') }
  }

  const handleFbProviderChange = (newFbProvider) => {
    setFbProvider(newFbProvider)
    const newProviderData = providers.find(p => p.provider === newFbProvider)
    const models = (newProviderData?.available_models || [])
      .filter(m => !(newFbProvider === provider && m === model))
    if (models.length > 0 && !models.includes(fbModel)) {
      setFbModel(models[0])
    } else if (models.length === 0) {
      setFbModel('')
    }
  }

  return (
    <div className="mt-2 space-y-2">
      <div className="flex items-center gap-2">
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
          onChange={e => {
            setModel(e.target.value)
            if (fbProvider === provider && fbModel === e.target.value) setFbModel('')
          }}
          disabled={!provider}
          className="text-xs border rounded px-2 py-1.5 bg-white flex-1 min-w-0 disabled:opacity-40"
        >
          <option value="">Select model...</option>
          {availableModels.map(m => (
            <option key={m} value={m}>{m}</option>
          ))}
        </select>
        <button
          onClick={() => onSave(provider, model, customFallback ? fbProvider : null, customFallback ? fbModel : null)}
          disabled={!provider || !model || (customFallback && (!fbProvider || !fbModel)) || saving}
          className="text-xs px-2 py-1.5 rounded bg-purple-600 text-white hover:bg-purple-700 disabled:opacity-40 flex items-center gap-1"
        >
          {saving ? <Loader2 className="w-3 h-3 animate-spin" /> : <Save className="w-3 h-3" />}
          Save
        </button>
        <button onClick={onCancel} className="text-xs px-2 py-1.5 rounded border hover:bg-gray-50">
          Cancel
        </button>
      </div>
      <label className="flex items-center gap-1.5 text-xs text-gray-500 cursor-pointer select-none">
        <input
          type="checkbox"
          checked={customFallback}
          onChange={e => {
            setCustomFallback(e.target.checked)
            if (!e.target.checked) { setFbProvider(''); setFbModel('') }
          }}
          className="rounded border-gray-300"
        />
        Custom fallback model
      </label>
      {customFallback && (
        <div className="flex items-center gap-2 pl-5">
          <select
            value={fbProvider}
            onChange={e => handleFbProviderChange(e.target.value)}
            className="text-xs border rounded px-2 py-1.5 bg-white"
          >
            <option value="">Select fallback provider...</option>
            {providers.filter(p => p.api_key_configured && p.provider !== provider).map(p => (
              <option key={p.provider} value={p.provider}>{p.provider}</option>
            ))}
          </select>
          <select
            value={fbModel}
            onChange={e => setFbModel(e.target.value)}
            disabled={!fbProvider}
            className="text-xs border rounded px-2 py-1.5 bg-white flex-1 min-w-0 disabled:opacity-40"
          >
            <option value="">Select model...</option>
            {fbAvailableModels
              .filter(m => !(fbProvider === provider && m === model))
              .map(m => (
              <option key={m} value={m}>{m}</option>
            ))}
          </select>
        </div>
      )}
    </div>
  )
}

const AgentRow = ({ agent, providers, onOverride, onReset, saving, error, onClearError }) => {
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
          {!agent.override_unavailable && agent.suggested_fallback && agent.override && (
            <div className="mt-0.5 text-xs text-gray-400">
              Fallback: <code>{agent.suggested_fallback}</code>
              {agent.fallback_is_custom && !agent.fallback_unavailable && (
                <span className="ml-1 text-purple-500 font-medium">(custom)</span>
              )}
            </div>
          )}
          {agent.fallback_unavailable && agent.override && (
            <div className="mt-1 px-2 py-1 rounded bg-amber-50 border border-amber-200 text-xs text-amber-700 flex items-center gap-1.5">
              <AlertTriangle className="w-3 h-3 flex-shrink-0" />
              <span>Custom fallback provider <strong>{agent.override.fallback_provider}</strong> API key is not configured — using auto-detected fallback.</span>
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
      {error && (
        <div className="mt-2 mx-3 px-2 py-1.5 rounded bg-red-50 border border-red-200 text-xs text-red-700 flex items-center gap-1.5">
          <XCircle className="w-3.5 h-3.5 flex-shrink-0" />
          <span>{error}</span>
        </div>
      )}
      {editing && (
        <OverrideForm
          providers={providers}
          currentProvider={agent.override?.provider || agent.resolved_provider}
          currentModel={agent.override?.model || agent.resolved_model || ''}
          currentFallbackProvider={agent.override?.fallback_provider || null}
          currentFallbackModel={agent.override?.fallback_model || null}
          onSave={(provider, model, fbProvider, fbModel) => {
            if (onClearError) onClearError()
            onOverride(agent.agent_id, provider, model, fbProvider, fbModel, () => setEditing(false))
          }}
          onCancel={() => { setEditing(false); if (onClearError) onClearError() }}
          saving={saving}
        />
      )}
    </div>
  )
}

const MODEL_LABELS = {
  'deepseek-v4-flash': 'DeepSeek V4 Flash',
  'qwen3.6-27b': 'Qwen 3.6 27B',
  'qwen3.6-35b-a3b': 'Qwen 3.6 35B A3B',
}

const LocalModelsSection = () => {
  const [showLogs, setShowLogs] = useState({})
  const [loadingModel, setLoadingModel] = useState(null)
  const [loadResult, setLoadResult] = useState(null)
  const queryClient = useQueryClient()
  const { data: status, isLoading: statusLoading } = useQuery({
    queryKey: ['local-model-status'],
    queryFn: getLocalModelStatus,
    refetchInterval: 3000,
  })

  const { data: logsData } = useQuery({
    queryKey: ['local-model-logs'],
    queryFn: () => getLocalModelLogs(30),
    refetchInterval: 5000,
  })

  const services = status?.services || {}
  const switching = status?.switching
  const currentMode = status?.current_mode
  const activeModels = status?.active_models || []
  const availableModels = status?.available_models || []

  const modelToService = {
    'deepseek-v4-flash': 'deepseek-v4-flash',
    'qwen3.6-27b': 'qwen-27b',
    'qwen3.6-35b-a3b': 'qwen-35b',
  }

  const getServiceForModel = (modelId) => modelToService[modelId] || modelId

  const handleLoadModel = async (modelId) => {
    setLoadingModel(modelId)
    setLoadResult(null)
    try {
      const result = await loadModel(modelId)
      setLoadResult({ model: modelId, success: true, data: result })
      queryClient.invalidateQueries({ queryKey: ['local-model-status'] })
    } catch (e) {
      setLoadResult({ model: modelId, success: false, error: e.message })
    } finally {
      setLoadingModel(null)
    }
  }

  return (
    <SectionCard title="Local GPU Models" icon={Server}>
      {/* Mode banner */}
      <div className="flex items-center gap-3 mb-4">
        {switching ? (
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-amber-50 border border-amber-200">
            <Loader2 className="w-4 h-4 animate-spin text-amber-500" />
            <span className="text-sm text-amber-700">
              Switching to <strong>{switching}</strong> mode…
            </span>
          </div>
        ) : currentMode ? (
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-green-50 border border-green-200">
            <CheckCircle className="w-4 h-4 text-green-500" />
            <span className="text-sm text-green-700">
              Active: <strong className="capitalize">{currentMode}</strong> mode
              <span className="text-green-500 font-normal ml-1">
                ({activeModels.map(m => MODEL_LABELS[m] || m).join(', ')})
              </span>
            </span>
          </div>
        ) : (
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-gray-50 border border-gray-200">
            <Server className="w-4 h-4 text-gray-400" />
            <span className="text-sm text-gray-500">Idle — no model loaded</span>
          </div>
        )}
      </div>

      {/* Load model buttons */}
      {!switching && (
        <div className="flex flex-wrap items-center gap-2 mb-4">
          <span className="text-xs text-gray-400 font-medium mr-1">Load:</span>
          {availableModels.map(modelId => {
            const isActive = activeModels.includes(modelId)
            const isLoading = loadingModel === modelId
            return (
              <button
                key={modelId}
                onClick={() => handleLoadModel(modelId)}
                disabled={isActive || isLoading || !!loadingModel}
                className={`text-xs px-3 py-1.5 rounded-lg border flex items-center gap-1.5 transition-colors ${
                  isActive
                    ? 'bg-green-100 border-green-300 text-green-700 cursor-default'
                    : 'bg-white border-gray-200 hover:bg-gray-50 text-gray-700 disabled:opacity-40 disabled:cursor-not-allowed'
                }`}
              >
                {isLoading ? (
                  <Loader2 className="w-3 h-3 animate-spin" />
                ) : isActive ? (
                  <CheckCircle className="w-3 h-3" />
                ) : (
                  <Zap className="w-3 h-3" />
                )}
                {MODEL_LABELS[modelId] || modelId}
              </button>
            )
          })}
        </div>
      )}

      {/* Load result */}
      {loadResult && (
        <div className={`mb-4 px-3 py-2 rounded-lg text-xs ${
          loadResult.success
            ? 'bg-green-50 border border-green-200 text-green-700'
            : 'bg-red-50 border border-red-200 text-red-700'
        }`}>
          {loadResult.success ? (
            <div className="flex items-center gap-2">
              <CheckCircle className="w-3.5 h-3.5 flex-shrink-0" />
              <span>
                <strong>{MODEL_LABELS[loadResult.model] || loadResult.model}</strong> loaded in{' '}
                <strong>{loadResult.data?.elapsed_seconds || '?'}s</strong>
                — mode: <strong>{loadResult.data?.mode}</strong>
              </span>
            </div>
          ) : (
            <div className="flex items-center gap-2">
              <XCircle className="w-3.5 h-3.5 flex-shrink-0" />
              <span>Failed to load: {loadResult.error}</span>
            </div>
          )}
        </div>
      )}

      {/* Model grid */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        {availableModels.map(modelId => {
          const svcName = getServiceForModel(modelId)
          const svc = services[svcName]
          const isReady = svc?.ready
          const isLoaded = (svc?.replicas || 0) > 0
          const isOther = currentMode && !isLoaded && !switching
          const label = MODEL_LABELS[modelId] || modelId

          return (
            <div
              key={modelId}
              className={`rounded-lg border p-3 ${
                isReady ? 'border-green-200 bg-green-50/30' :
                isLoaded ? 'border-amber-200 bg-amber-50/30' :
                'border-gray-200 bg-gray-50/30'
              }`}
            >
              <div className="flex items-center justify-between mb-1">
                <span className="font-medium text-sm">{label}</span>
                <div className={`w-2.5 h-2.5 rounded-full ${
                  isReady ? 'bg-green-500' :
                  isLoaded ? 'bg-amber-400 animate-pulse' :
                  'bg-gray-300'
                }`} />
              </div>
              <div className="text-xs text-gray-500">
                {isReady ? (
                  <span className="text-green-600 flex items-center gap-1">
                    <CheckCircle className="w-3 h-3" /> Ready
                  </span>
                ) : isLoaded ? (
                  <span className="text-amber-600 flex items-center gap-1">
                    <Loader2 className="w-3 h-3 animate-spin" /> Loading…
                  </span>
                ) : isOther ? (
                  <span className="text-gray-400">Idle</span>
                ) : (
                  <span className="text-gray-400">Not deployed</span>
                )}
              </div>
              {isLoaded && logsData?.services?.[svcName] && (
                <button
                  onClick={() => setShowLogs(prev => ({ ...prev, [svcName]: !prev[svcName] }))}
                  className="mt-2 text-xs text-gray-400 hover:text-gray-600 flex items-center gap-1"
                >
                  <Terminal className="w-3 h-3" />
                  {showLogs[svcName] ? 'Hide' : 'Show'} logs
                </button>
              )}
              {showLogs[svcName] && logsData?.services?.[svcName] && (
                <div className="mt-2 max-h-48 overflow-y-auto rounded bg-gray-900 p-2">
                  {(logsData.services[svcName].logs || []).map((line, i) => (
                    <div key={i} className="text-[10px] font-mono text-gray-300 whitespace-pre-wrap break-all leading-tight">
                      {line}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )
        })}
      </div>

      {status?.error && (
        <div className="mt-3 px-3 py-2 rounded bg-red-50 border border-red-200 text-xs text-red-600">
          {status.error}
        </div>
      )}
    </SectionCard>
  )
}


const ModelManagement = () => {
  const queryClient = useQueryClient()
  const [validating, setValidating] = useState({})
  const [cooldown, setCooldown] = useState({})
  const [validationResults, setValidationResults] = useState({})

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['model-management'],
    queryFn: getModelManagement,
  })

  const [agentError, setAgentError] = useState({})
  const agentOverrideMutation = useMutation({
    mutationFn: ({ agentId, provider, model, fallbackProvider, fallbackModel }) =>
      setAgentModelOverride(agentId, provider, model, fallbackProvider, fallbackModel),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['model-management'] }),
    onError: (err, { agentId }) => setAgentError(prev => ({ ...prev, [agentId]: err.message })),
  })

  const agentResetMutation = useMutation({
    mutationFn: (agentId) => removeAgentModelOverride(agentId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['model-management'] }),
  })

  const [translationError, setTranslationError] = useState(null)
  const translationOverrideMutation = useMutation({
    mutationFn: ({ provider, model, fallbackProvider, fallbackModel }) => setTranslationModelOverride(provider, model, fallbackProvider, fallbackModel),
    onSuccess: () => {
      setTranslationError(null)
      queryClient.invalidateQueries({ queryKey: ['model-management'] })
    },
    onError: (err) => setTranslationError(err.message),
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
      setCooldown(prev => ({ ...prev, [provider]: true }))
      setTimeout(() => setCooldown(prev => ({ ...prev, [provider]: false })), 5000)
    }
  }

  const [editingTranslation, setEditingTranslation] = useState(false)
  const [bulkEditing, setBulkEditing] = useState(false)
  const [bulkSaving, setBulkSaving] = useState(false)
  const [bulkError, setBulkError] = useState(null)

  const handleBulkOverride = async (provider, model, fbProvider, fbModel) => {
    setBulkSaving(true)
    setBulkError(null)
    try {
      const agentIds = (data?.agents || []).map(a => a.agent_id)
      await Promise.all(agentIds.map(id =>
        setAgentModelOverride(id, provider, model, fbProvider, fbModel)
      ))
      queryClient.invalidateQueries({ queryKey: ['model-management'] })
      setBulkEditing(false)
    } catch (e) {
      setBulkError(e.message)
    } finally {
      setBulkSaving(false)
    }
  }

  const handleBulkReset = async () => {
    setBulkSaving(true)
    setBulkError(null)
    try {
      const overridden = (data?.agents || []).filter(a => a.override).map(a => a.agent_id)
      await Promise.all(overridden.map(id => removeAgentModelOverride(id)))
      queryClient.invalidateQueries({ queryKey: ['model-management'] })
    } catch (e) {
      setBulkError(e.message)
    } finally {
      setBulkSaving(false)
    }
  }

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
    || translationOverrideMutation.isPending || translationResetMutation.isPending || bulkSaving

  return (
    <div className="space-y-8">
      <PageHeader title="Model Management" subtitle="Configure LLM providers and model assignments per agent.">
        <VersionBadge />
        <button
          onClick={() => refetch()}
          className="flex items-center gap-1 text-sm text-gray-500 hover:text-gray-700"
        >
          <RefreshCw className={`w-4 h-4 ${isLoading ? 'animate-spin' : ''}`} />
          Refresh
        </button>
      </PageHeader>

      {/* Local GPU Models — live status */}
      <LocalModelsSection />

      {/* Providers */}
      <SectionCard title={`Providers (${providers.length})`} icon={Cpu}>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          {providers.map(p => (
            <ProviderCard
              key={p.provider}
              provider={p}
              onValidate={handleValidate}
              validating={!!validating[p.provider]}
              cooldown={!!cooldown[p.provider]}
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
              {translation.fallback_is_custom && translation.override && (
                <div className="flex items-center gap-1.5 mt-0.5">
                  <span className="text-xs text-gray-400">
                    Fallback: <code>{translation.override.fallback_provider}/{translation.override.fallback_model || 'default'}</code>
                  </span>
                  <span className="text-xs text-purple-500 font-medium">(custom)</span>
                  {translation.fallback_unavailable && (
                    <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full text-xs font-medium bg-amber-100 text-amber-700">
                      <AlertTriangle className="w-3 h-3" /> Key missing
                    </span>
                  )}
                </div>
              )}
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
              {translationError && (
                <div className="mt-2 px-2 py-1.5 rounded bg-red-50 border border-red-200 text-xs text-red-700 flex items-center gap-1.5">
                  <XCircle className="w-3.5 h-3.5 flex-shrink-0" />
                  <span>{translationError}</span>
                </div>
              )}
              {editingTranslation && (
                <OverrideForm
                  providers={providers}
                  currentProvider={translation.override?.provider || translation.provider}
                  currentModel={translation.override?.model || translation.model}
                  currentFallbackProvider={translation.override?.fallback_provider}
                  currentFallbackModel={translation.override?.fallback_model}
                  onSave={(provider, model, fallbackProvider, fallbackModel) => {
                    setTranslationError(null)
                    translationOverrideMutation.mutate({ provider, model, fallbackProvider, fallbackModel }, {
                      onSuccess: () => setEditingTranslation(false),
                    })
                  }}
                  onCancel={() => { setEditingTranslation(false); setTranslationError(null) }}
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
            <div className="flex items-center gap-2 mb-3 -mt-1">
              <button
                onClick={() => { setBulkEditing(!bulkEditing); setBulkError(null) }}
                disabled={bulkSaving}
                className="text-xs px-3 py-1.5 rounded border border-purple-200 hover:bg-purple-50 text-purple-600 flex items-center gap-1"
              >
                {bulkSaving ? <Loader2 className="w-3 h-3 animate-spin" /> : <Zap className="w-3 h-3" />}
                {bulkEditing ? 'Close' : 'Set All'}
              </button>
              {agents.some(a => a.override) && (
                <button
                  onClick={handleBulkReset}
                  disabled={isSaving}
                  className="text-xs px-3 py-1.5 rounded border border-gray-200 hover:bg-gray-50 text-gray-500 flex items-center gap-1"
                >
                  <RotateCcw className="w-3 h-3" /> Reset All
                </button>
              )}
            </div>
            {bulkError && (
              <div className="mb-3 px-2 py-1.5 rounded bg-red-50 border border-red-200 text-xs text-red-700 flex items-center gap-1.5">
                <XCircle className="w-3.5 h-3.5 flex-shrink-0" />
                <span>{bulkError}</span>
              </div>
            )}
            {bulkEditing && (
              <div className="mb-3 p-3 rounded-lg bg-purple-50/50 border border-purple-100">
                <p className="text-xs text-purple-600 font-medium mb-2">Apply to all {agents.length} agents:</p>
                <OverrideForm
                  providers={providers}
                  currentProvider=""
                  currentModel=""
                  currentFallbackProvider={null}
                  currentFallbackModel={null}
                  onSave={handleBulkOverride}
                  onCancel={() => { setBulkEditing(false); setBulkError(null) }}
                  saving={bulkSaving}
                />
              </div>
            )}
            <div className="space-y-1">
              {sortedAgents.map(agent => (
                <AgentRow
                  key={agent.agent_id}
                  agent={agent}
                  providers={providers}
                  onOverride={(agentId, provider, model, fallbackProvider, fallbackModel, onSuccess) =>
                    agentOverrideMutation.mutate({ agentId, provider, model, fallbackProvider, fallbackModel }, { onSuccess })
                  }
                  onReset={(agentId) => agentResetMutation.mutate(agentId)}
                  saving={isSaving}
                  error={agentError[agent.agent_id]}
                  onClearError={() => setAgentError(prev => { const next = { ...prev }; delete next[agent.agent_id]; return next })}
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
