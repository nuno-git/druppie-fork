/**
 * Shared helpers and small components for Chat
 */

import { useState } from 'react'
import { Copy, Check } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import CodeBlock from '../CodeBlock'

// --- Markdown components (code blocks with syntax highlighting + copy) ---

export const chatMarkdownComponents = {
  pre({ children }) {
    return <>{children}</>
  },
  code({ className, children, ...props }) {
    const match = /language-(\w+)/.exec(className || '')
    const codeString = String(children).replace(/\n$/, '')
    if (match || codeString.includes('\n')) {
      return (
        <CodeBlock
          code={codeString}
          language={match?.[1] || 'text'}
          showLineNumbers={codeString.split('\n').length > 10}
        />
      )
    }
    return <code className={className} {...props}>{children}</code>
  },
}

// --- Helpers ---

export const timeAgo = (dateStr) => {
  if (!dateStr) return ''
  const seconds = Math.floor((Date.now() - new Date(dateStr).getTime()) / 1000)
  if (seconds < 60) return 'just now'
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`
  return `${Math.floor(seconds / 86400)}d ago`
}

export const copyToClipboard = async (text) => {
  try {
    await navigator.clipboard.writeText(text)
  } catch {
    const textarea = document.createElement('textarea')
    textarea.value = text
    textarea.style.position = 'fixed'
    textarea.style.left = '-9999px'
    document.body.appendChild(textarea)
    textarea.select()
    document.execCommand('copy')
    document.body.removeChild(textarea)
  }
}

export const CopyJsonButton = ({ getData, label = 'Copy JSON' }) => {
  const [copied, setCopied] = useState(false)

  const handleCopy = async () => {
    const json = getData()
    await copyToClipboard(JSON.stringify(json, null, 2))
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <button
      onClick={handleCopy}
      className={`inline-flex items-center gap-1 px-2 py-1 text-xs rounded transition-colors ${
        copied
          ? 'bg-green-100 text-green-700'
          : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
      }`}
      title={label}
    >
      {copied ? <Check className="w-3 h-3" /> : <Copy className="w-3 h-3" />}
      {copied ? 'Copied!' : label}
    </button>
  )
}

/**
 * Build a JSON snapshot reflecting exactly what's expanded in the UI.
 */
export const buildVisibleJson = (data, containerEl) => {
  const result = {
    id: data.id,
    title: data.title,
    status: data.status,
    ...(data.created_at && { created_at: data.created_at }),
    ...(data.project_id && { project_id: data.project_id }),
    ...(data.project_name && { project_name: data.project_name }),
    ...(data.repo_url && { repo_url: data.repo_url }),
    ...(data.token_usage && { token_usage: data.token_usage }),
    timeline: [],
  }

  if (!containerEl || !data.timeline) return result

  data.timeline.forEach((entry) => {
    if (entry.type === 'message' && entry.message) {
      const m = entry.message
      result.timeline.push({
        type: 'message',
        role: m.role,
        content: m.content,
        ...(m.agent_id && { agent_id: m.agent_id }),
      })
      return
    }

    if (entry.type === 'agent_run' && entry.agent_run) {
      const run = entry.agent_run
      const runEntry = {
        type: 'agent_run',
        agent_id: run.agent_id,
        status: run.status,
        sequence_number: run.sequence_number,
      }
      if (run.llm_calls?.length) {
        runEntry.llm_calls = run.llm_calls.map((llm) => ({
          model: llm.model,
          total_tokens: llm.token_usage?.total_tokens || 0,
          tool_calls: llm.tool_calls?.map((tc) => ({
            tool_name: tc.tool_name,
            status: tc.status,
          })),
        }))
      }
      result.timeline.push(runEntry)
    }
  })

  return result
}

// --- Extract approvals from LLM calls ---

export const extractSurfacedApprovals = (llmCalls) => {
  const items = []
  llmCalls?.forEach((llm) => {
    llm.tool_calls?.forEach((tc) => {
      if (tc.approval) {
        items.push({ type: 'approval', tc })
      }
    })
  })
  return items
}

// --- Extract HITL questions from an agent run's LLM calls ---

export const extractQuestions = (agentRun) => {
  const questions = []
  agentRun.llm_calls?.forEach((llm) => {
    llm.tool_calls?.forEach((tc) => {
      if (tc.tool_name?.includes('hitl_ask')) {
        questions.push({ tc, agentId: agentRun.agent_id })
      }
    })
  })
  return questions
}

// --- Find the pending question across the entire timeline ---

export const findPendingQuestion = (timeline) => {
  if (!timeline) return null
  for (const entry of timeline) {
    if (entry.type !== 'agent_run' || !entry.agent_run) continue
    for (const llm of entry.agent_run.llm_calls || []) {
      for (const tc of llm.tool_calls || []) {
        if (tc.tool_name?.includes('hitl_ask') && tc.status === 'waiting_answer') {
          return { tc, agentId: entry.agent_run.agent_id }
        }
      }
    }
  }
  return null
}

export const ACTIVE_STATUSES = new Set(['running', 'paused_hitl', 'paused_tool', 'waiting_approval', 'waiting_answer'])
