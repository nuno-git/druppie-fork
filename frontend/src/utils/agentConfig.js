/**
 * Agent configuration and styling utilities
 */

import {
  Brain,
  Clock,
  ClipboardList,
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
  business_analyst: { name: 'Business Analyst', icon: ClipboardList, color: 'teal', description: 'Requirements gathering' },
  business_analyst_agent: { name: 'Business Analyst', icon: ClipboardList, color: 'teal', description: 'Requirements gathering' },
  architect: { name: 'Architect', icon: Brain, color: 'indigo', description: 'System design' },
  architect_agent: { name: 'Architect', icon: Brain, color: 'indigo', description: 'System design' },
  developer: { name: 'Developer', icon: FileCode, color: 'green', description: 'Code generation' },
  developer_agent: { name: 'Developer', icon: FileCode, color: 'green', description: 'Code generation' },
  code_generator: { name: 'Code Generator', icon: FileCode, color: 'green', description: 'Code generation' },
  code_generator_agent: { name: 'Code Generator', icon: FileCode, color: 'green', description: 'Code generation' },
  devops: { name: 'DevOps', icon: Hammer, color: 'orange', description: 'Build & deploy' },
  devops_agent: { name: 'DevOps', icon: Hammer, color: 'orange', description: 'Build & deploy' },
  deployer: { name: 'Deployer', icon: Hammer, color: 'orange', description: 'Deployment' },
  deployer_agent: { name: 'Deployer', icon: Hammer, color: 'orange', description: 'Deployment' },
  git_agent: { name: 'Git', icon: GitBranch, color: 'gray', description: 'Version control' },
  reviewer: { name: 'Reviewer', icon: CheckCircle, color: 'teal', description: 'Code review' },
  reviewer_agent: { name: 'Reviewer', icon: CheckCircle, color: 'teal', description: 'Code review' },
  tester: { name: 'Tester', icon: CheckCircle, color: 'cyan', description: 'Testing' },
  tester_agent: { name: 'Tester', icon: CheckCircle, color: 'cyan', description: 'Testing' },
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
    indigo: 'bg-indigo-100 text-indigo-700 border-indigo-200',
    cyan: 'bg-cyan-100 text-cyan-700 border-cyan-200',
  }
  return colors[color] || colors.gray
}

// Get message bubble colors for agent-specific chat messages
export const getAgentMessageColors = (color) => {
  const colors = {
    purple: { bg: 'bg-purple-50', border: 'border-purple-200', text: 'text-purple-900', accent: 'text-purple-700' },
    blue: { bg: 'bg-blue-50', border: 'border-blue-200', text: 'text-blue-900', accent: 'text-blue-700' },
    green: { bg: 'bg-green-50', border: 'border-green-200', text: 'text-green-900', accent: 'text-green-700' },
    orange: { bg: 'bg-orange-50', border: 'border-orange-200', text: 'text-orange-900', accent: 'text-orange-700' },
    gray: { bg: 'bg-gray-50', border: 'border-gray-200', text: 'text-gray-900', accent: 'text-gray-700' },
    teal: { bg: 'bg-teal-50', border: 'border-teal-200', text: 'text-teal-900', accent: 'text-teal-700' },
    indigo: { bg: 'bg-indigo-50', border: 'border-indigo-200', text: 'text-indigo-900', accent: 'text-indigo-700' },
    cyan: { bg: 'bg-cyan-50', border: 'border-cyan-200', text: 'text-cyan-900', accent: 'text-cyan-700' },
  }
  return colors[color] || colors.gray
}
