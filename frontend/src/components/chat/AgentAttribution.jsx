/**
 * AgentAttribution - Shows prominently which agents contributed to the response
 */

import React from 'react'
import { getAgentConfig, getAgentColorClasses } from '../../utils/agentConfig'

const AgentAttribution = ({ events }) => {
  if (!events || events.length === 0) return null

  // Extract unique agents from events
  const agents = [...new Set(events
    .filter(e => e.data?.agent_id)
    .map(e => e.data.agent_id)
  )]

  // Also check for specific event types that indicate agent work
  const hasRouter = events.some(e =>
    e.event_type === 'router_analyzing' ||
    e.event_type === 'intent_detected' ||
    e.data?.agent_id?.includes('router')
  )
  const hasPlanner = events.some(e =>
    e.event_type === 'plan_ready' ||
    e.event_type === 'plan_creating' ||
    e.data?.agent_id?.includes('planner')
  )
  const hasCodeGen = events.some(e =>
    e.event_type === 'llm_generating' ||
    e.event_type === 'files_created' ||
    e.data?.agent_id?.includes('developer') ||
    e.data?.agent_id?.includes('code_generator')
  )

  // Add inferred agents if not already present
  if (hasRouter && !agents.some(a => a.includes('router'))) {
    agents.unshift('router_agent')
  }
  if (hasPlanner && !agents.some(a => a.includes('planner'))) {
    agents.push('planner_agent')
  }
  if (hasCodeGen && !agents.some(a => a.includes('developer') || a.includes('code'))) {
    agents.push('developer_agent')
  }

  if (agents.length === 0) return null

  return (
    <div className="flex items-center gap-2 mb-2 flex-wrap">
      <span className="text-xs text-gray-500 font-medium">Powered by:</span>
      {agents.slice(0, 4).map(agentId => {
        const config = getAgentConfig(agentId)
        const AgentIcon = config.icon
        const colorClasses = getAgentColorClasses(config.color)

        return (
          <span
            key={agentId}
            className={`inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium rounded-full border ${colorClasses}`}
            title={config.description}
          >
            <AgentIcon className="w-3.5 h-3.5" />
            {config.name}
          </span>
        )
      })}
      {agents.length > 4 && (
        <span className="text-xs text-gray-400">+{agents.length - 4} more</span>
      )}
    </div>
  )
}

export default AgentAttribution
