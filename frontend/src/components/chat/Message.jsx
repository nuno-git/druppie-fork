/**
 * Message - Single chat message display with agent attribution and interactions
 */

import React, { useState } from 'react'
import { Bot, User, Info, CheckCircle, XCircle } from 'lucide-react'
import WorkflowTimeline from './WorkflowTimeline'
import QuestionCard from './QuestionCard'
import ApprovalCard from './ApprovalCard'
import DeploymentCard from './DeploymentCard'
import MCPResultCard from './MCPResultCard'
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
  const isSystem = message.role === 'system'
  const [eventsExpanded, setEventsExpanded] = useState(false)

  // Get agent config for assistant messages with agent_id
  const agentId = message.agent_id || null
  const agentConfig = agentId ? getAgentConfig(agentId) : null
  const AgentIcon = agentConfig?.icon || Bot
  const colors = agentConfig ? getAgentMessageColors(agentConfig.color) : null

  // Detect MCP results in message content
  const detectMCPResults = (content) => {
    if (!content || typeof content !== 'string') return []

    const results = []
    const lines = content.split('\n')
    let jsonBuffer = []
    let inJsonBlock = false
    let braceDepth = 0

    console.log('[MCPResultCard] === Starting MCP detection ===')
    console.log('[MCPResultCard] Full content:', content)
    console.log('[MCPResultCard] Content length:', content.length)

    for (let i = 0; i < lines.length; i++) {
      const line = lines[i]
      const trimmedLine = line.trim()

      // Track brace depth to handle multi-line JSON/Python dicts
      for (const char of line) {
        if (char === '{' || char === '[') braceDepth++
        if (char === '}' || char === ']') braceDepth--
      }

      if ((trimmedLine.startsWith('{') || trimmedLine.startsWith('[')) && jsonBuffer.length === 0) {
        inJsonBlock = true
        jsonBuffer = [line]
        console.log('[MCPResultCard] Started JSON block at line', i, ':', line.substring(0, 100))
      } else if (inJsonBlock) {
        jsonBuffer.push(line)
        if (braceDepth === 0 && (trimmedLine.endsWith('}') || trimmedLine.endsWith(']'))) {
          inJsonBlock = false
          let parsed
          const jsonStr = jsonBuffer.join('\n')

          try {
            try {
              parsed = JSON.parse(jsonStr)
              console.log('[MCPResultCard] ✓ Parsed as JSON')
            } catch (jsonError) {
              console.log('[MCPResultCard] JSON parse failed, trying Python dict format...')
              console.log('[MCPResultCard] Error:', jsonError.message)
              
              let converted = jsonStr
                .replace(/\bNone\b/g, 'null')
                .replace(/\bTrue\b/g, 'true')
                .replace(/\bFalse\b/g, 'false')
              
              converted = converted.replace(/'/g, '"')
              
              console.log('[MCPResultCard] Converted string:', converted.substring(0, 500))
              parsed = JSON.parse(converted)
              console.log('[MCPResultCard] ✓ Parsed as Python dict')
            }

            console.log('[MCPResultCard] Parsed object:', parsed)
            console.log('[MCPResultCard] Parsed object keys:', Object.keys(parsed))

            const isMCPResult = parsed.mcp_action ||
                               parsed.action === 'use_mcp'

            console.log('[MCPResultCard] isMCPResult:', isMCPResult)
            console.log('[MCPResultCard] mcp_action:', parsed.mcp_action)
            console.log('[MCPResultCard] action:', parsed.action)
            console.log('[MCPResultCard] answer:', parsed.answer ? parsed.answer.substring(0, 100) : 'null/undefined')

            if (isMCPResult) {
              console.log('[MCPResultCard] ✓✓✓ ADDING MCP RESULT TO LIST')
              results.push(parsed)
            }
          } catch (e) {
            console.log('[MCPResultCard] ✗ Failed to parse:', e.message)
            console.log('[MCPResultCard] Buffer lines:', jsonBuffer.length)
            console.log('[MCPResultCard] Buffer preview:', jsonStr.substring(0, 500))
          }
          jsonBuffer = []
          braceDepth = 0
        }
      }
    }

    console.log('[MCPResultCard] === Detection complete, found:', results.length, 'results ===')
    return results
  }

  const mcpResults = detectMCPResults(message.content)

  // Clean content by removing MCP JSON blocks and showing only answers
  const cleanContent = (() => {
    if (!message.content) return ''

    const lines = message.content.split('\n')
    const cleanedLines = []
    let braceDepth = 0
    let inJsonBlock = false
    let lastMcpAnswer = null

    for (let i = 0; i < lines.length; i++) {
      const line = lines[i]
      const trimmedLine = line.trim()

      // Track brace depth to identify JSON blocks
      for (const char of line) {
        if (char === '{' || char === '[') braceDepth++
        if (char === '}' || char === ']') braceDepth--
      }

      if ((trimmedLine.startsWith('{') || trimmedLine.startsWith('[')) && braceDepth === 1) {
        inJsonBlock = true

        // Try to parse this JSON to extract answer
        try {
          let jsonStr = line
          let j = i + 1
          while (j < lines.length && braceDepth > 0) {
            for (const char of lines[j]) {
              if (char === '{' || char === '[') braceDepth++
              if (char === '}' || char === ']') braceDepth--
            }
            jsonStr += '\n' + lines[j]
            if (braceDepth === 0) break
            j++
          }

          const parsed = JSON.parse(jsonStr)
          if (parsed.answer) {
            lastMcpAnswer = parsed.answer
          }
          i = j
        } catch (e) {
          // If parsing fails, keep the line
        }
      } else if (!inJsonBlock) {
        cleanedLines.push(line)
      }

      if (braceDepth === 0) {
        inJsonBlock = false
      }
    }

    // If we found an MCP answer, show that instead of cleaned content
    if (lastMcpAnswer) {
      return lastMcpAnswer
    }

    return cleanedLines.join('\n').trim()
  })()

  // Debug: log message structure
  console.log('[Message] Message structure:', {
    role: message.role,
    hasContent: !!message.content,
    contentPreview: message.content?.substring(0, 200),
    mcpResultsCount: mcpResults.length,
    fullMessage: message
  })

  // System messages (approval notifications) have a distinct style
  if (isSystem) {
    const isApproval = message.content?.includes('✅')
    const isRejection = message.content?.includes('🚫')
    const SystemIcon = isApproval ? CheckCircle : isRejection ? XCircle : Info
    const bgColor = isApproval ? 'bg-green-50 border-green-200' : isRejection ? 'bg-red-50 border-red-200' : 'bg-blue-50 border-blue-200'
    const iconColor = isApproval ? 'text-green-600' : isRejection ? 'text-red-600' : 'text-blue-600'
    const textColor = isApproval ? 'text-green-800' : isRejection ? 'text-red-800' : 'text-blue-800'

    return (
      <div className="flex justify-center mb-3">
        <div className={`inline-flex items-center gap-2 px-4 py-2 rounded-full border ${bgColor}`}>
          <SystemIcon className={`w-4 h-4 ${iconColor}`} />
          <span className={`text-sm ${textColor}`}>
            {message.content?.replace(/[✅🚫]/g, '').replace(/\*\*/g, '').replace(/`/g, '')}
          </span>
        </div>
      </div>
    )
  }

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

            {/* Main content - only show if we don't have MCP results (MCPResultCard handles display) */}
            {cleanContent && mcpResults.length === 0 && (
              <div className={`whitespace-pre-wrap text-sm ${colors ? colors.text : ''}`}>
                {cleanContent}
              </div>
            )}

            {/* MCP Results - display formatted MCP tool results */}
            {!isUser && mcpResults.length > 0 && mcpResults.map((result, idx) => (
              <MCPResultCard key={`mcp-${idx}`} data={result} />
            ))}

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
