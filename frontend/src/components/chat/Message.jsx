/**
 * Message - Single chat message display with agent attribution and interactions
 */

import React, { useState } from 'react'
import { Bot, User } from 'lucide-react'
import WorkflowTimeline from './WorkflowTimeline'
import QuestionCard from './QuestionCard'
import ApprovalCard from './ApprovalCard'
import DeploymentCard from './DeploymentCard'
import { getAgentConfig, getAgentMessageColors } from '../../utils/agentConfig'

const Message = ({
  message,
  onAnswerQuestion,
  isAnsweringQuestion,
  onApproveTask,
  onRejectTask,
  isApprovingTask,
  currentUserId,
  sessionId,
  userRoles = [],
}) => {
  const isUser = message.role === 'user'
  const [eventsExpanded, setEventsExpanded] = useState(false) // Start collapsed

  // Get agent config for assistant messages with agent_id
  const agentId = message.agent_id || null
  const agentConfig = agentId ? getAgentConfig(agentId) : null
  const AgentIcon = agentConfig?.icon || Bot
  const colors = agentConfig ? getAgentMessageColors(agentConfig.color) : null

  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'} mb-4`}>
      <div
        className={`max-w-[85%] rounded-2xl px-4 py-3 ${
          isUser
            ? 'bg-blue-600 text-white rounded-br-none'
            : colors
              ? `${colors.bg} border ${colors.border} rounded-bl-none shadow-sm`
              : 'bg-white border border-gray-200 rounded-bl-none shadow-sm'
        }`}
      >
        <div className="flex items-start space-x-2">
          {!isUser && (
            <div className={`w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0 ${
              colors ? `${colors.bg} border ${colors.border}` : 'bg-gradient-to-br from-blue-500 to-purple-600'
            }`}>
              <AgentIcon className={`w-5 h-5 ${colors ? colors.accent : 'text-white'}`} />
            </div>
          )}
          <div className="flex-1 min-w-0">
            {/* Agent name header for assistant messages with agent_id */}
            {!isUser && agentConfig && (
              <div className={`text-xs font-semibold mb-1 ${colors?.accent || 'text-gray-500'}`}>
                {agentConfig.name} Agent
              </div>
            )}

            {/* Main content */}
            {message.content && (
              <div className={`whitespace-pre-wrap text-sm ${colors ? colors.text : ''}`}>
                {message.content}
              </div>
            )}

            {/* Deployment Card - shows when deployment is complete with URL */}
            {!isUser && message.deploymentUrl && (
              <DeploymentCard
                url={message.deploymentUrl}
                containerName={message.containerName}
              />
            )}

            {/* Workflow Events Timeline - collapsed by default, expandable */}
            {!isUser && message.workflowEvents && message.workflowEvents.length > 0 && (
              <WorkflowTimeline
                events={message.workflowEvents}
                isExpanded={eventsExpanded}
                onToggle={() => setEventsExpanded(!eventsExpanded)}
              />
            )}

            {/* Pending Approvals - Inline approval cards */}
            {message.pendingApprovals && message.pendingApprovals.length > 0 && (
              message.pendingApprovals.map((approval, i) => (
                <ApprovalCard
                  key={approval.task_id || i}
                  approval={approval}
                  onApprove={onApproveTask}
                  onReject={onRejectTask}
                  isProcessing={isApprovingTask}
                  currentUserId={currentUserId}
                  sessionId={sessionId || message.planId}
                  userRoles={userRoles}
                />
              ))
            )}

            {/* Pending Questions */}
            {message.pendingQuestions && message.pendingQuestions.length > 0 && (
              message.pendingQuestions.map((question) => (
                <QuestionCard
                  key={question.id}
                  question={question}
                  onAnswer={onAnswerQuestion}
                  isAnswering={isAnsweringQuestion}
                />
              ))
            )}
          </div>
          {isUser && (
            <div className="w-8 h-8 rounded-full bg-blue-500 flex items-center justify-center flex-shrink-0">
              <User className="w-5 h-5 text-white" />
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

export default Message
