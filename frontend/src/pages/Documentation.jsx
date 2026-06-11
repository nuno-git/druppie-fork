/**
 * Documentation Page - Browse documentation for all platform components
 */

import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { BookOpen, AlertCircle, Loader2, ChevronDown, ChevronRight, FileText, Puzzle, Bot, Cable, Wrench } from 'lucide-react'

import { getDocumentation } from '../services/api'
import PageHeader from '../components/shared/PageHeader'
import CodeBlock from '../components/CodeBlock'
import MermaidBlock from '../components/MermaidBlock'

const docComponents = {
  pre({ children }) {
    return <div className="my-2">{children}</div>
  },
  code({ className, children }) {
    const match = /language-(\w+)/.exec(className || '')
    const codeString = String(children).replace(/\n$/, '')
    if (match && match[1] === 'mermaid') {
      return <MermaidBlock code={codeString} />
    }
    if (match || codeString.includes('\n')) {
      return <CodeBlock
        code={codeString}
        language={match ? match[1] : 'text'}
        showLineNumbers={codeString.split('\n').length > 10}
      />
    }
    return <code className="px-1.5 py-0.5 bg-gray-100 text-gray-800 rounded text-xs font-mono">{children}</code>
  },
  table({ children }) {
    return <div className="overflow-x-auto my-4">
      <table className="min-w-full text-sm border border-gray-200 rounded-lg overflow-hidden">{children}</table>
    </div>
  },
  thead({ children }) {
    return <thead className="bg-gray-50">{children}</thead>
  },
  th({ children }) {
    return <th className="px-3 py-2 text-left text-xs font-semibold text-gray-600 uppercase tracking-wide border-b border-gray-200">{children}</th>
  },
  td({ children }) {
    return <td className="px-3 py-2 text-sm text-gray-700 border-b border-gray-100">{children}</td>
  },
  h1({ children }) {
    return <h1 className="text-2xl font-bold text-gray-900 mt-8 mb-4 pb-2 border-b border-gray-200">{children}</h1>
  },
  h2({ children }) {
    return <h2 className="text-xl font-semibold text-gray-900 mt-8 mb-3 pb-1.5 border-b border-gray-100">{children}</h2>
  },
  h3({ children }) {
    return <h3 className="text-lg font-semibold text-gray-900 mt-6 mb-2">{children}</h3>
  },
  p({ children }) {
    return <p className="text-sm text-gray-700 leading-relaxed mb-3">{children}</p>
  },
  ul({ children }) {
    return <ul className="list-disc list-outside ml-5 mb-3 space-y-1 text-sm text-gray-700">{children}</ul>
  },
  ol({ children }) {
    return <ol className="list-decimal list-outside ml-5 mb-3 space-y-1 text-sm text-gray-700">{children}</ol>
  },
  li({ children }) {
    return <li className="leading-relaxed">{children}</li>
  },
  blockquote({ children }) {
    return <blockquote className="border-l-4 border-blue-300 bg-blue-50/50 pl-4 py-2 my-3 text-sm text-gray-700 italic rounded-r">{children}</blockquote>
  },
  hr() {
    return <hr className="my-6 border-gray-200"/>
  },
  a({ href, children }) {
    return <a href={href} className="text-blue-600 hover:text-blue-800 underline decoration-blue-300" target="_blank" rel="noopener noreferrer">{children}</a>
  },
  strong({ children }) {
    return <strong className="font-semibold text-gray-900">{children}</strong>
  },
}

const DocCard = ({ entry }) => {
  const [expanded, setExpanded] = useState(false)
  if (!entry) return null

  const IconCmp = expanded ? ChevronDown : ChevronRight

  return (
    <div className="border border-gray-200 rounded-xl bg-white overflow-hidden">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between p-4 hover:bg-gray-50 transition-colors"
      >
        <div className="flex items-center gap-2">
          <FileText className="w-4 h-4 text-blue-500" />
          <span className="font-medium text-gray-900">{entry.title}</span>
        </div>
        <span className="text-gray-400"><IconCmp className="w-4 h-4" /></span>
      </button>
      {expanded && <div className="border-t border-gray-100 p-6 bg-white max-w-none">
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          components={docComponents}
        >{entry.content}</ReactMarkdown>
      </div>}
    </div>
  )
}

const EmptySection = ({ icon: IconCmp, title, description }) => {
  return (
    <div className="flex flex-col items-center justify-center py-16 text-gray-400 border-2 border-dashed border-gray-200 rounded-xl bg-gray-50/50">
      <IconCmp className="w-10 h-10 mb-3 text-gray-300" />
      <p className="text-base font-medium text-gray-500">{title}</p>
      <p className="text-sm mt-1">{description}</p>
    </div>
  )
}

const DocSection = ({ title, icon: IconCmp, children }) => {
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 border-b border-gray-200 pb-2">
        <IconCmp className="w-5 h-5 text-gray-500" />
        <h2 className="text-lg font-semibold text-gray-800">{title}</h2>
      </div>
      {children}
    </div>
  )
}

const Documentation = () => {
  const { data: docs, isLoading, isError, error, refetch } = useQuery({
    queryKey: ['documentation'],
    queryFn: getDocumentation,
    refetchInterval: 60000,
  })

  if (isLoading) {
    return (
      <div className="space-y-6">
        <PageHeader title="Documentation Portal" subtitle="Browse documentation for all platform components" />
        <div className="flex items-center justify-center h-64">
          <Loader2 className="w-8 h-8 animate-spin text-gray-400" />
        </div>
      </div>
    )
  }

  if (isError) {
    return (
      <div className="space-y-6">
        <PageHeader title="Documentation Portal" subtitle="Browse documentation for all platform components" />
        <div className="flex flex-col items-center justify-center h-64 text-red-500">
          <AlertCircle className="w-12 h-12 mb-2" />
          <p className="text-lg font-medium">Failed to load documentation</p>
          <p className="text-sm text-red-400">{error?.message || 'An unexpected error occurred'}</p>
          <button
            onClick={() => refetch()}
            className="mt-4 px-4 py-2 bg-blue-500 text-white rounded-lg hover:bg-blue-600 transition-colors"
          >Retry</button>
        </div>
      </div>
    )
  }

  const entries = docs || []
  const appCards = entries.map((e) => (
    <DocCard key={e.source_id} entry={e} />
  ))

  return (
    <div className="space-y-8">
      <PageHeader title="Documentation Portal" subtitle="Browse documentation for all platform components">
        <span className="text-sm text-gray-500">{entries.length} application docs</span>
      </PageHeader>
      <DocSection title="Agents" icon={Bot}>
        <EmptySection icon={Bot} title="No agent documentation yet" description="Agent documentation will appear here once available." />
      </DocSection>
      <DocSection title="Modules" icon={Puzzle}>
        <EmptySection icon={Puzzle} title="No module documentation yet" description="Module documentation will appear here once available." />
      </DocSection>
      <DocSection title="Applications" icon={BookOpen}>
        {appCards.length > 0 ? (
          <div className="space-y-3">
            {appCards}
          </div>
        ) : (
          <EmptySection icon={BookOpen} title="No application documentation" description="Create an application with a docs/documentation.md file to see it here." />
        )}
      </DocSection>
      <DocSection title="MCPs" icon={Cable}>
        <EmptySection icon={Cable} title="No MCP documentation yet" description="MCP documentation will appear here once available." />
      </DocSection>
      <DocSection title="Tools" icon={Wrench}>
        <EmptySection icon={Wrench} title="No tool documentation yet" description="Tool documentation will appear here once available." />
      </DocSection>
    </div>
  )
}

export default Documentation
