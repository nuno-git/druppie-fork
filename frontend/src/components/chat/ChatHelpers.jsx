/**
 * Shared helpers and small components for Chat
 */

import { createContext, useContext, useState } from 'react'
import { Copy, Check } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import CodeBlock from '../CodeBlock'
import MermaidBlock from '../MermaidBlock'
import { getAgentConfig } from '../../utils/agentConfig'

// --- Contexts for rewriting relative links in rendered markdown ---
//
// ProjectRepoContext  — set by SessionDetail to {repo_url, default_branch}
// SourceFileContext   — set per file preview (e.g. `docs/functional-design.md`)
//                       so `./foo.md` in that file resolves relative to the
//                       file's directory, like Gitea/GitHub do.
//
// MarkdownLink below uses both to turn `./foo.md` into a working Gitea
// file URL.

export const ProjectRepoContext = createContext(null)
export const SourceFileContext = createContext(null)

const isExternalHref = (href) =>
  !href ||
  /^https?:\/\//i.test(href) ||
  href.startsWith('mailto:') ||
  href.startsWith('tel:') ||
  href.startsWith('#')

// Resolve a markdown link href against the directory of the source file it
// appears in. Mirrors how Gitea/GitHub resolve relative links in rendered
// markdown:
//   sourcePath = "docs/functional-design.md", href = "./foo.md"  -> "docs/foo.md"
//   sourcePath = "docs/functional-design.md", href = "foo.md"    -> "docs/foo.md"
//   sourcePath = "docs/a/b.md",               href = "../foo.md" -> "docs/foo.md"
//   any sourcePath,                           href = "/foo.md"   -> "foo.md"
export const resolveRelativePath = (sourcePath, href) => {
  const hrefSegments = href.split('/')
  if (hrefSegments[0] === '') {
    // Absolute from repo root (leading slash). Drop the empty first segment.
    return hrefSegments.slice(1).filter(Boolean).join('/')
  }
  const baseDir = sourcePath ? sourcePath.split('/').slice(0, -1) : []
  const segments = [...baseDir]
  for (const seg of hrefSegments) {
    if (seg === '' || seg === '.') continue
    if (seg === '..') segments.pop()
    else segments.push(seg)
  }
  return segments.join('/')
}

export const rewriteRelativeLink = (href, repo, sourcePath) => {
  if (!repo || !repo.repo_url) return null
  if (isExternalHref(href)) return null
  const resolved = resolveRelativePath(sourcePath, href)
  const branch = repo.default_branch || 'main'
  const base = repo.repo_url.replace(/\/$/, '')
  return `${base}/src/branch/${branch}/${resolved}`
}

const MarkdownLink = ({ href, children, ...props }) => {
  const repo = useContext(ProjectRepoContext)
  const sourcePath = useContext(SourceFileContext)
  const rewritten = rewriteRelativeLink(href, repo, sourcePath)
  if (rewritten) {
    return (
      <a href={rewritten} target="_blank" rel="noopener noreferrer" {...props}>
        {children}
      </a>
    )
  }
  // External or no context — keep as-is but open in new tab for external links
  const target = isExternalHref(href) ? '_blank' : undefined
  const rel = target ? 'noopener noreferrer' : undefined
  return (
    <a href={href} target={target} rel={rel} {...props}>
      {children}
    </a>
  )
}

// --- Markdown components (code blocks with syntax highlighting + copy) ---

export const chatMarkdownComponents = {
  pre({ children }) {
    return <>{children}</>
  },
  a: MarkdownLink,
  code({ className, children, ...props }) {
    const match = /language-(\w+)/.exec(className || '')
    const codeString = String(children).replace(/\n$/, '')
    if (match?.[1] === 'mermaid') {
      return <MermaidBlock code={codeString} />
    }
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

// --- Extract test results from agent run's tool calls ---

export const extractTestResults = (agentRun) => {
  const results = []
  agentRun?.llm_calls?.forEach((llm) => {
    llm.tool_calls?.forEach((tc) => {
      if (tc.tool_name === 'run_tests' && tc.status === 'completed' && tc.result) {
        try {
          const raw = typeof tc.result === 'string' ? JSON.parse(tc.result) : tc.result
          if (raw) results.push(raw)
        } catch { /* malformed result JSON — skip */ }
      }
      // Also extract from test_report builtin tool calls
      if (tc.tool_name === 'test_report' && tc.status === 'completed' && tc.result) {
        try {
          const raw = typeof tc.result === 'string' ? JSON.parse(tc.result) : tc.result
          // Convert test_report format to run_tests format for TestResultCard
          if (raw && tc.arguments) {
            const args = typeof tc.arguments === 'string' ? JSON.parse(tc.arguments) : tc.arguments
            const passed = parseInt(args.passed_count) || 0
            const failed = parseInt(args.failed_count) || 0
            const testResult = {
              success: args.tests_passed || false,
              framework: 'unknown',
              exit_code: args.tests_passed ? 0 : 1,
              stdout: args.summary || '',
              stderr: '',
              elapsed_seconds: null,
              results: {
                total: passed + failed,
                passed: passed,
                failed: failed,
                skipped: 0,
                failed_tests: [],
              },
              coverage: null,
            }
            results.push(testResult)
          }
        } catch { /* malformed JSON — skip */ }
      }
    })
  })
  return results
}

// --- Extract per-test error messages from test output ---

export const extractTestErrors = (stdout, stderr, framework, failedTestNames) => {
  const errors = {}
  if (!failedTestNames?.length) return errors
  const output = (stdout || '') + '\n' + (stderr || '')
  const fw = framework?.toLowerCase()

  if (fw === 'pytest') {
    // Try to extract from FAILURES section first
    const failureSection = output.split(/={3,} FAILURES ={3,}/)[1]
    if (failureSection) {
      for (const testName of failedTestNames) {
        // Find the test's section: ___ test_name ___
        const shortName = testName.split('::').pop()
        const pattern = new RegExp(`_{3,}\\s*${shortName.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\s*_{3,}([\\s\\S]*?)(?=_{3,}|={3,}|$)`)
        const match = failureSection.match(pattern)
        if (match) {
          // Extract E lines (pytest assertion details)
          const eLines = match[1].match(/^E\s+.+$/gm)
          if (eLines) {
            errors[testName] = eLines.slice(0, 3).map(l => l.replace(/^E\s+/, '')).join('\n')
            continue
          }
          // Fallback: find AssertionError or last meaningful line
          const assertMatch = match[1].match(/(?:AssertionError|AssertError|assert).*$/m)
          if (assertMatch) {
            errors[testName] = assertMatch[0].trim()
            continue
          }
        }
        // Fallback: scan for FAILED lines
        const failedLine = output.match(new RegExp(`FAILED.*${shortName.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}.*?-\\s*(.+)$`, 'm'))
        if (failedLine) {
          errors[testName] = failedLine[1].trim()
        }
      }
    } else {
      // No FAILURES section, try FAILED summary lines
      for (const testName of failedTestNames) {
        const shortName = testName.split('::').pop()
        const failedLine = output.match(new RegExp(`FAILED.*${shortName.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}.*?-\\s*(.+)$`, 'm'))
        if (failedLine) {
          errors[testName] = failedLine[1].trim()
        }
      }
    }
  } else if (fw === 'vitest' || fw === 'jest') {
    for (const testName of failedTestNames) {
      const escaped = testName.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
      // Find test name followed by error details
      const pattern = new RegExp(`[✗×✕❌]\\s*${escaped}[\\s\\S]*?(?:Expected|Error|Received|thrown)[\\s\\S]*?$`, 'm')
      const match = output.match(pattern)
      if (match) {
        // Extract the meaningful error lines after the test name
        const afterName = match[0].split('\n').slice(1).filter(l => l.trim()).slice(0, 3)
        if (afterName.length) {
          errors[testName] = afterName.map(l => l.trim()).join('\n')
          continue
        }
      }
      // Fallback: look for "Error:" or "Expected" near the test name
      const idx = output.indexOf(testName)
      if (idx !== -1) {
        const context = output.substring(idx, idx + 500)
        const errLine = context.match(/(?:Error|Expected|Received|AssertionError):?\s*.+$/m)
        if (errLine) {
          errors[testName] = errLine[0].trim()
        }
      }
    }
  }

  return errors
}

// --- Extract sandbox results from agent run's tool calls ---

export const extractSandboxResults = (agentRun) => {
  const results = []
  agentRun?.llm_calls?.forEach((llm) => {
    llm.tool_calls?.forEach((tc) => {
      if (tc.tool_name === 'execute_coding_task' && tc.status !== 'waiting_sandbox' && tc.status !== 'pending' && tc.result) {
        let raw
        try {
          raw = typeof tc.result === 'string' ? JSON.parse(tc.result) : tc.result
        } catch {
          return
        }
        if (raw?.sandbox_session_id) results.push(raw)
      }
    })
  })
  return results
}

// --- Extract surfaced file writes from agent runs with surfaceFileWrites config ---

export const extractSurfacedFileWrites = (agentRun) => {
  const config = getAgentConfig(agentRun?.agent_id)
  if (!config.surfaceFileWrites) return []

  const files = []
  agentRun?.llm_calls?.forEach((llm) => {
    llm.tool_calls?.forEach((tc) => {
      if (tc.approval) return
      if (tc.status !== 'completed') return

      const toolName = tc.tool_name || ''
      const args = tc.arguments || {}

      if (toolName.includes('write_file') && !toolName.includes('batch')) {
        if (args.path && args.content) {
          files.push({ path: args.path, content: args.content })
        }
      } else if (toolName.includes('batch_write_files')) {
        const batchFiles = args.files
        if (batchFiles && typeof batchFiles === 'object') {
          Object.entries(batchFiles).forEach(([path, content]) => {
            files.push({ path, content })
          })
        }
      }
    })
  })
  return files
}

// --- Extract dependency install results from agent run's tool calls ---

export const extractDependencyInstalls = (agentRun) => {
  const results = []
  agentRun?.llm_calls?.forEach((llm) => {
    llm.tool_calls?.forEach((tc) => {
      if (tc.tool_name?.includes('install_test_dependencies') && tc.status === 'completed' && tc.result) {
        try {
          const raw = typeof tc.result === 'string' ? JSON.parse(tc.result) : tc.result
          if (raw) results.push(raw)
        } catch { /* malformed JSON — skip */ }
      }
    })
  })
  return results
}

// --- Extract all notable items from an agent run in tool call order ---

export const extractOrderedItems = (agentRun, hasFollowingMessage) => {
  const items = []
  agentRun?.llm_calls?.forEach((llm) => {
    llm.tool_calls?.forEach((tc) => {
      // Approvals (only when no following message)
      if (!hasFollowingMessage && tc.approval && tc.approval.status !== 'pending') {
        items.push({ type: 'approval', tc })
      }
      // HITL questions
      if (tc.tool_name?.includes('hitl_ask')) {
        items.push({ type: 'question', tc, agentId: agentRun.agent_id })
      }
      // Test results
      if (tc.tool_name === 'run_tests' && tc.status === 'completed' && tc.result) {
        try {
          const raw = typeof tc.result === 'string' ? JSON.parse(tc.result) : tc.result
          if (raw) items.push({ type: 'test', data: raw })
        } catch { /* skip */ }
      }
      // Sandbox results
      if (tc.tool_name === 'execute_coding_task' && tc.status !== 'waiting_sandbox' && tc.status !== 'pending' && tc.result) {
        try {
          const raw = typeof tc.result === 'string' ? JSON.parse(tc.result) : tc.result
          if (raw?.sandbox_session_id) items.push({ type: 'sandbox', data: raw })
        } catch { /* skip */ }
      }
      // Pi coding run results (vendored pi_agent)
      if (tc.tool_name === 'execute_coding_task_pi' && tc.status === 'completed' && tc.result) {
        try {
          const raw = typeof tc.result === 'string' ? JSON.parse(tc.result) : tc.result
          if (raw?.run_id || raw?.pi_coding_run_id) items.push({ type: 'pi_coding', data: raw })
        } catch { /* skip */ }
      }
      // Pi coding run — LIVE view while the tool is in flight. pi_agent
      // is synchronous (the tool_call is "executing" until the subprocess
      // returns), so we render the event stream from the PiCodingRun row
      // until we flip to the completed summary above.
      if (tc.tool_name === 'execute_coding_task_pi' && tc.status === 'executing') {
        items.push({ type: 'pi_coding_live', toolCallId: tc.id })
      }
    })
  })
  return items
}

// Statuses that indicate a session is actively doing work or waiting for external input
// Note: These are SessionStatus values. 'running' is an AgentRunStatus, not included here.
export const ACTIVE_STATUSES = new Set([
  'active', 'paused', 'paused_hitl', 'paused_tool',
  'paused_approval', 'paused_sandbox', 'paused_crashed',
  'waiting_approval', 'waiting_answer',
])
