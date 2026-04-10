import { useState, useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { FileText } from 'lucide-react'
import CodeBlock from '../CodeBlock'
import MermaidBlock from '../MermaidBlock'
import AskArchitectFooter from './AskArchitectFooter'
import { getArchitectureDocs, getArchitectureDoc } from '../../services/api'

// Markdown components matching the chat rendering quality
const docMarkdownComponents = {
  pre({ children }) {
    return <>{children}</>
  },
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
    return (
      <code className="px-1.5 py-0.5 bg-gray-100 text-gray-800 rounded text-[13px] font-mono" {...props}>
        {children}
      </code>
    )
  },
  table({ children }) {
    return (
      <div className="overflow-x-auto my-4">
        <table className="min-w-full text-sm border border-gray-200 rounded-lg overflow-hidden">
          {children}
        </table>
      </div>
    )
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
  h4({ children }) {
    return <h4 className="text-base font-medium text-gray-800 mt-4 mb-1.5">{children}</h4>
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
    return <hr className="my-6 border-gray-200" />
  },
  a({ href, children }) {
    return <a href={href} className="text-blue-600 hover:text-blue-800 underline decoration-blue-300" target="_blank" rel="noopener noreferrer">{children}</a>
  },
  strong({ children }) {
    return <strong className="font-semibold text-gray-900">{children}</strong>
  },
}

const DocsTab = () => {
  const [selectedDoc, setSelectedDoc] = useState(null)

  const { data: docsData, isLoading: docsLoading } = useQuery({
    queryKey: ['architecture-docs'],
    queryFn: getArchitectureDocs,
  })

  const { data: docContent, isLoading: contentLoading } = useQuery({
    queryKey: ['architecture-doc', selectedDoc],
    queryFn: () => getArchitectureDoc(selectedDoc),
    enabled: !!selectedDoc,
  })

  const docs = docsData?.docs || []

  // Auto-select first doc once loaded
  useEffect(() => {
    if (docs.length > 0 && !selectedDoc) {
      setSelectedDoc(docs[0].id)
    }
  }, [docs, selectedDoc])

  return (
    <div className="space-y-6">
      <div className="bg-white rounded-xl border border-gray-100 overflow-hidden" style={{ minHeight: '700px' }}>
        <div className="flex" style={{ minHeight: '700px' }}>
          {/* Sidebar */}
          <div className="w-60 flex-shrink-0 border-r border-gray-100 bg-gray-50/30">
            <div className="p-4">
              <h3 className="text-xs font-medium text-gray-400 uppercase tracking-wide mb-3">Documenten</h3>
              {docsLoading ? (
                <div className="space-y-2">
                  {Array.from({ length: 4 }).map((_, i) => (
                    <div key={i} className="h-9 bg-gray-200 rounded-lg animate-pulse" />
                  ))}
                </div>
              ) : docs.length === 0 ? (
                <p className="text-xs text-gray-400">Geen documenten gevonden.</p>
              ) : (
                <div className="space-y-1">
                  {docs.map(doc => (
                    <button
                      key={doc.id}
                      onClick={() => setSelectedDoc(doc.id)}
                      className={`w-full flex items-center gap-2.5 px-3 py-2.5 text-left rounded-lg text-sm transition-colors ${
                        selectedDoc === doc.id
                          ? 'bg-blue-50 text-blue-700 font-medium border border-blue-200'
                          : 'text-gray-600 hover:bg-gray-100'
                      }`}
                    >
                      <FileText className={`w-4 h-4 flex-shrink-0 ${selectedDoc === doc.id ? 'text-blue-500' : 'text-gray-400'}`} />
                      <span className="truncate">{doc.name}</span>
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* Content */}
          <div className="flex-1 overflow-y-auto">
            {contentLoading ? (
              <div className="p-8 animate-pulse space-y-4">
                <div className="h-8 bg-gray-200 rounded w-64" />
                <div className="h-px bg-gray-200 w-full" />
                <div className="space-y-2">
                  <div className="h-4 bg-gray-100 rounded w-full" />
                  <div className="h-4 bg-gray-100 rounded w-5/6" />
                  <div className="h-4 bg-gray-100 rounded w-4/6" />
                </div>
                <div className="h-4 bg-gray-100 rounded w-full mt-4" />
                <div className="h-4 bg-gray-100 rounded w-3/4" />
              </div>
            ) : docContent?.content ? (
              <div className="p-8 max-w-4xl">
                <ReactMarkdown remarkPlugins={[remarkGfm]} components={docMarkdownComponents}>
                  {docContent.content}
                </ReactMarkdown>
              </div>
            ) : selectedDoc ? (
              <div className="p-8">
                <p className="text-gray-400 text-sm">Document niet gevonden.</p>
              </div>
            ) : (
              <div className="flex items-center justify-center h-full">
                <div className="text-center">
                  <FileText className="w-12 h-12 text-gray-300 mx-auto mb-3" />
                  <p className="text-gray-500 text-sm">Selecteer een document om te lezen.</p>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>

      <AskArchitectFooter />
    </div>
  )
}

export default DocsTab
