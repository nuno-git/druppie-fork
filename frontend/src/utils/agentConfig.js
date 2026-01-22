/**
 * Agent configuration and styling utilities
 */

import {
  Brain,
  Clock,
  FileCode,
  Hammer,
  GitBranch,
  CheckCircle,
  Bot,
} from 'lucide-react'

// Agent name formatting and icons
export const AGENT_CONFIG = {
  router: { name: 'Router', icon: Brain, color: 'purple', description: 'Intent analysis' },
  router_agent: { name: 'Router', icon: Brain, color: 'purple', description: 'Intent analysis' },
  planner: { name: 'Planner', icon: Clock, color: 'blue', description: 'Execution planning' },
  planner_agent: { name: 'Planner', icon: Clock, color: 'blue', description: 'Execution planning' },
  developer: { name: 'Developer', icon: FileCode, color: 'green', description: 'Code generation' },
  developer_agent: { name: 'Developer', icon: FileCode, color: 'green', description: 'Code generation' },
  code_generator: { name: 'Code Generator', icon: FileCode, color: 'green', description: 'Code generation' },
  code_generator_agent: { name: 'Code Generator', icon: FileCode, color: 'green', description: 'Code generation' },
  devops: { name: 'DevOps', icon: Hammer, color: 'orange', description: 'Build & deploy' },
  devops_agent: { name: 'DevOps', icon: Hammer, color: 'orange', description: 'Build & deploy' },
  git_agent: { name: 'Git', icon: GitBranch, color: 'gray', description: 'Version control' },
  reviewer: { name: 'Reviewer', icon: CheckCircle, color: 'teal', description: 'Code review' },
  reviewer_agent: { name: 'Reviewer', icon: CheckCircle, color: 'teal', description: 'Code review' },
}

export const getAgentConfig = (agentId) => {
  return AGENT_CONFIG[agentId] || {
    name: agentId.replace('_agent', '').replace(/_/g, ' '),
    icon: Bot,
    color: 'gray',
    description: 'AI Agent',
  }
}

export const getAgentColorClasses = (color) => {
  const colors = {
    purple: 'bg-purple-100 text-purple-700 border-purple-200',
    blue: 'bg-blue-100 text-blue-700 border-blue-200',
    green: 'bg-green-100 text-green-700 border-green-200',
    orange: 'bg-orange-100 text-orange-700 border-orange-200',
    gray: 'bg-gray-100 text-gray-700 border-gray-200',
    teal: 'bg-teal-100 text-teal-700 border-teal-200',
  }
  return colors[color] || colors.gray
}
