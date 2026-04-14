import { useState } from 'react'
import PageHeader from '../components/shared/PageHeader'
import OverviewTab from '../components/architecture/OverviewTab'
import AgentsTab from '../components/architecture/AgentsTab'
import PermissionsTab from '../components/architecture/PermissionsTab'
import DocsTab from '../components/architecture/DocsTab'

const TABS = [
  { id: 'overview', label: 'Overzicht' },
  { id: 'agents', label: 'Agents' },
  { id: 'permissions', label: 'MCP & Permissies' },
  { id: 'docs', label: 'Documentatie' },
]

const Architecture = () => {
  const [activeTab, setActiveTab] = useState('overview')

  return (
    <div className="space-y-6">
      <PageHeader
        title="Platform Architectuur"
        subtitle="Systeem overzicht, agent catalogus, tools en governance configuratie."
      />

      {/* Tab bar */}
      <div className="border-b border-gray-200">
        <nav className="flex gap-6" aria-label="Tabs">
          {TABS.map(tab => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`pb-3 text-sm font-medium border-b-2 transition-colors ${
                activeTab === tab.id
                  ? 'border-blue-500 text-gray-900'
                  : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
              }`}
            >
              {tab.label}
            </button>
          ))}
        </nav>
      </div>

      {/* Tab content */}
      {activeTab === 'overview' && <OverviewTab />}
      {activeTab === 'agents' && <AgentsTab />}
      {activeTab === 'permissions' && <PermissionsTab />}
      {activeTab === 'docs' && <DocsTab />}
    </div>
  )
}

export default Architecture
