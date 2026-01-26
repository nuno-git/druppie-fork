/**
 * Message - Single chat message display with workflow events and interactions
 */

import React, { useState } from 'react'
import { Bot, User } from 'lucide-react'
import WorkflowTimeline from './WorkflowTimeline'
import QuestionCard from './QuestionCard'
import ApprovalCard from './ApprovalCard'
import AgentAttribution from './AgentAttribution'
import DeploymentCard from './DeploymentCard'

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
  const [eventsExpanded, setEventsExpanded] = useState(true)

  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'} mb-4`}>
      <div
        className={`max-w-[85%] rounded-2xl px-4 py-3 ${
          isUser
            ? 'bg-blue-600 text-white rounded-br-none'
            : 'bg-white border border-gray-200 rounded-bl-none shadow-sm'
        }`}
      >
        <div className="flex items-start space-x-2">
          {!isUser && (
            <div className="w-8 h-8 rounded-full bg-gradient-to-br from-blue-500 to-purple-600 flex items-center justify-center flex-shrink-0">
              <Bot className="w-5 h-5 text-white" />
            </div>
          )}
          <div className="flex-1 min-w-0">
            {/* Agent attribution header - prominent display of which agents contributed */}
            {!isUser && message.workflowEvents && message.workflowEvents.length > 0 && (
              <AgentAttribution events={message.workflowEvents} />
            )}

            {/* Main content */}
            {message.content && (
              <div className="whitespace-pre-wrap text-sm">{message.content}</div>
            )}

            {/* Deployment Card - shows when deployment is complete with URL */}
            {!isUser && message.deploymentUrl && (
              <DeploymentCard
                url={message.deploymentUrl}
                containerName={message.containerName}
              />
            )}

            {/* Workflow Events Timeline */}
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
