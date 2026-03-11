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
  router: { name: 'Router', icon: Brain, color: 'purple', description: 'Intent analysis', thinkingLabel: 'Analyzing intent...' },
  planner: { name: 'Planner', icon: Clock, color: 'blue', description: 'Execution planning', thinkingLabel: 'Planning execution...' },
  business_analyst: { name: 'Business Analyst', icon: ClipboardList, color: 'teal', description: 'Requirements gathering', thinkingLabel: 'Creating functional design...' },
  architect: { name: 'Architect', icon: Brain, color: 'indigo', description: 'System design', thinkingLabel: 'Creating technical design...' },
  developer: { name: 'Developer', icon: FileCode, color: 'green', description: 'Code generation', thinkingLabel: 'Writing code...' },
  code_generator: { name: 'Code Generator', icon: FileCode, color: 'green', description: 'Code generation', thinkingLabel: 'Writing code...' },
  devops: { name: 'DevOps', icon: Hammer, color: 'orange', description: 'Build & deploy', thinkingLabel: 'Preparing deployment...' },
  deployer: { name: 'Deployer', icon: Hammer, color: 'orange', description: 'Deployment', thinkingLabel: 'Deploying...' },
  git: { name: 'Git', icon: GitBranch, color: 'gray', description: 'Version control', thinkingLabel: 'Managing repository...' },
  reviewer: { name: 'Reviewer', icon: CheckCircle, color: 'teal', description: 'Code review', thinkingLabel: 'Reviewing code...' },
  tester: { name: 'Tester', icon: CheckCircle, color: 'cyan', description: 'Testing', thinkingLabel: 'Running tests...' },
  builder: { name: 'Builder', icon: Hammer, color: 'green', description: 'Code implementation', thinkingLabel: 'Building code...' },
  test_builder: { name: 'Test Builder', icon: CheckCircle, color: 'cyan', description: 'Test generation', thinkingLabel: 'Writing tests...' },
  test_executor: { name: 'Test Executor', icon: CheckCircle, color: 'cyan', description: 'Running & fixing tests', thinkingLabel: 'Running tests...' },
  builder_planner: { name: 'Builder Planner', icon: ClipboardList, color: 'indigo', description: 'Implementation planning', thinkingLabel: 'Creating implementation plan...', surfaceFileWrites: true },
}

export const getAgentConfig = (agentId) => {
  const key = agentId?.replace(/_agent$/, '')
  return AGENT_CONFIG[key] || AGENT_CONFIG[agentId] || {
    name: (key || agentId || '').replace(/_/g, ' '),
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

// Known tool name → friendly label map
const TOOL_LABELS = {
  'write_file': 'Write File',
  'batch_write_files': 'Write Files',
  'run_command': 'Run Command',
  'commit_and_push': 'Git Commit',
  'read_file': 'Read File',
  'list_directory': 'List Directory',
  'search_files': 'Search Files',
  'install_test_dependencies': 'Install Dependencies',
  'run_tests': 'Run Tests',
  'hitl_ask': 'Ask Question',
}

/**
 * Format a raw tool name into a user-friendly label.
 * Checks known tool names first, then strips server prefix and retries,
 * then falls back to: replace underscores with spaces, title-case.
 */
export const formatToolName = (toolName) => {
  if (!toolName) return 'Unknown Tool'
  if (TOOL_LABELS[toolName]) return TOOL_LABELS[toolName]
  const stripped = toolName.includes(':') ? toolName.split(':').pop() : toolName
  if (TOOL_LABELS[stripped]) return TOOL_LABELS[stripped]
  return stripped
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase())
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
