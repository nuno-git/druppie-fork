import React, { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { BookOpen, AlertCircle, Loader2, ChevronDown, ChevronRight, FileText, Puzzle, Bot, Cable, Wrench } from 'lucide-react'

import { getDocumentation } from '../services/api'
import PageHeader from '../components/shared/PageHeader'

function DocCard({ entry }) {
  const [expanded, setExpanded] = useState(false)
  if (!entry) return null

  const icon = React.createElement(expanded ? ChevronDown : ChevronRight, { className: 'w-4 h-4' })

  return React.createElement('div', { className: 'border border-gray-200 rounded-xl bg-white overflow-hidden' },
    React.createElement('button', {
      onClick: () => setExpanded(!expanded),
      className: 'w-full flex items-center justify-between p-4 hover:bg-gray-50 transition-colors'
    },
      React.createElement('div', { className: 'flex items-center gap-2' },
        React.createElement(FileText, { className: 'w-4 h-4 text-blue-500' }),
        React.createElement('span', { className: 'font-medium text-gray-900' }, entry.project_name)
      ),
      React.createElement('span', { className: 'text-gray-400' }, icon)
    ),
    expanded ? React.createElement('div', { className: 'border-t border-gray-100 p-4 bg-gray-50' },
      React.createElement('pre', { className: 'text-sm text-gray-700 whitespace-pre-wrap font-mono leading-relaxed' }, entry.content)
    ) : null
  )
}

function EmptySection({ icon, title, description }) {
  return React.createElement('div', { className: 'flex flex-col items-center justify-center py-16 text-gray-400 border-2 border-dashed border-gray-200 rounded-xl bg-gray-50/50' },
    React.createElement(icon, { className: 'w-10 h-10 mb-3 text-gray-300' }),
    React.createElement('p', { className: 'text-base font-medium text-gray-500' }, title),
    React.createElement('p', { className: 'text-sm mt-1' }, description)
  )
}

function DocSection({ title, icon, children }) {
  return React.createElement('div', { className: 'space-y-3' },
    React.createElement('div', { className: 'flex items-center gap-2 border-b border-gray-200 pb-2' },
      React.createElement(icon, { className: 'w-5 h-5 text-gray-500' }),
      React.createElement('h2', { className: 'text-lg font-semibold text-gray-800' }, title)
    ),
    children
  )
}

function Documentation() {
  const { data: docs, isLoading, isError, error, refetch } = useQuery({
    queryKey: ['documentation'],
    queryFn: getDocumentation,
    refetchInterval: 60000,
  })

  if (isLoading) {
    return React.createElement('div', { className: 'space-y-6' },
      React.createElement(PageHeader, { title: 'Documentation Portal', subtitle: 'Browse documentation for all platform components' }),
      React.createElement('div', { className: 'flex items-center justify-center h-64' },
        React.createElement(Loader2, { className: 'w-8 h-8 animate-spin text-gray-400' })
      )
    )
  }

  if (isError) {
    return React.createElement('div', { className: 'space-y-6' },
      React.createElement(PageHeader, { title: 'Documentation Portal', subtitle: 'Browse documentation for all platform components' }),
      React.createElement('div', { className: 'flex flex-col items-center justify-center h-64 text-red-500' },
        React.createElement(AlertCircle, { className: 'w-12 h-12 mb-2' }),
        React.createElement('p', { className: 'text-lg font-medium' }, 'Failed to load documentation'),
        React.createElement('p', { className: 'text-sm text-red-400' }, error && error.message ? error.message : 'An unexpected error occurred'),
        React.createElement('button', {
          onClick: () => refetch(),
          className: 'mt-4 px-4 py-2 bg-blue-500 text-white rounded-lg hover:bg-blue-600 transition-colors'
        }, 'Retry')
      )
    )
  }

  const entries = docs || []
  const appCards = entries.map(function(e) {
    return React.createElement(DocCard, { key: e.project_id, entry: e })
  })

  return React.createElement('div', { className: 'space-y-8' },
    React.createElement(PageHeader, { title: 'Documentation Portal', subtitle: 'Browse documentation for all platform components' },
      React.createElement('span', { className: 'text-sm text-gray-500' }, String(entries.length) + ' application docs')
    ),
    React.createElement(DocSection, { title: 'Agents', icon: Bot },
      React.createElement(EmptySection, { icon: Bot, title: 'No agent documentation yet', description: 'Agent documentation will appear here once available.' })
    ),
    React.createElement(DocSection, { title: 'Modules', icon: Puzzle },
      React.createElement(EmptySection, { icon: Puzzle, title: 'No module documentation yet', description: 'Module documentation will appear here once available.' })
    ),
    React.createElement(DocSection, { title: 'Applications', icon: BookOpen },
      appCards.length > 0
        ? React.createElement.apply(null, ['div', { className: 'space-y-3' }].concat(appCards))
        : React.createElement(EmptySection, { icon: BookOpen, title: 'No application documentation', description: 'Create an application with a docs/documentation.md file to see it here.' })
    ),
    React.createElement(DocSection, { title: 'MCPs', icon: Cable },
      React.createElement(EmptySection, { icon: Cable, title: 'No MCP documentation yet', description: 'MCP documentation will appear here once available.' })
    ),
    React.createElement(DocSection, { title: 'Tools', icon: Wrench },
      React.createElement(EmptySection, { icon: Wrench, title: 'No tool documentation yet', description: 'Tool documentation will appear here once available.' })
    )
  )
}

export default Documentation
