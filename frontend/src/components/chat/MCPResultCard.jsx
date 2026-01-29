/**
 * MCPResultCard - Displays formatted MCP tool results
 */

import React, { useState } from 'react'
import { File, Folder, Copy, ChevronDown, ChevronUp, Search, Database, Terminal, Container, CheckCircle, XCircle, FileText, GitBranch, PlayCircle, FolderOpen } from 'lucide-react'

const MCPResultCard = ({ data }) => {
  const [expanded, setExpanded] = useState(true)

  // Handle both formats: {mcp_action, prompt, answer} and {action, prompt, answer}
  const mcpAction = data.mcp_action || data.action
  const prompt = data.prompt
  const answer = data.answer

  console.log('[MCPResultCard] Rendering with data:', data)
  console.log('[MCPResultCard] mcpAction:', mcpAction, 'answer:', answer?.substring(0, 100))

  const getMCPConfig = (action) => {
    console.log('[MCPResultCard] getMCPConfig called with:', action)

    switch (action) {
      case 'use_bestand_zoeker':
      case 'use_bestand_zoeker_search':
        return {
          name: 'Bestand Zoeker',
          icon: Search,
          color: 'text-blue-600',
          bgColor: 'bg-blue-50',
          borderColor: 'border-blue-200'
        }
      case 'use_filesearch':
      case 'use_filesearch_search_files':
        return {
          name: 'File Search',
          icon: Database,
          color: 'text-purple-600',
          bgColor: 'bg-purple-50',
          borderColor: 'border-purple-200'
        }
      case 'use_coding':
      case 'use_coding_read_file':
      case 'use_coding_write_file':
      case 'use_coding_list_dir':
        return {
          name: 'Coding MCP',
          icon: FileText,
          color: 'text-green-600',
          bgColor: 'bg-green-50',
          borderColor: 'border-green-200'
        }
      case 'use_coding_run_command':
      case 'use_coding_run_tests':
        return {
          name: 'Terminal',
          icon: Terminal,
          color: 'text-gray-700',
          bgColor: 'bg-gray-900',
          borderColor: 'border-gray-700'
        }
      case 'use_coding_get_git_status':
        return {
          name: 'Git Status',
          icon: GitBranch,
          color: 'text-orange-600',
          bgColor: 'bg-orange-50',
          borderColor: 'border-orange-200'
        }
      case 'use_docker':
      case 'use_docker_run':
      case 'use_docker_build':
        return {
          name: 'Docker',
          icon: Container,
          color: 'text-cyan-600',
          bgColor: 'bg-cyan-50',
          borderColor: 'border-cyan-200'
        }
      case 'use_docker_logs':
        return {
          name: 'Docker Logs',
          icon: PlayCircle,
          color: 'text-cyan-600',
          bgColor: 'bg-gray-900',
          borderColor: 'border-gray-700'
        }
      default:
        return {
          name: action?.replace('use_', '').replace(/_/g, ' ') || 'MCP Tool',
          icon: File,
          color: 'text-gray-600',
          bgColor: 'bg-gray-50',
          borderColor: 'border-gray-200'
        }
    }
  }

  const config = getMCPConfig(mcpAction)
  const ConfigIcon = config.icon

  const parseBestandZoekerResult = (text) => {
    const result = {
      summary: '',
      files: [],
      additionalFiles: [],
      structure: null
    }

    if (!text) return result

    const lines = text.split('\n')
    let currentFile = null
    let inAdditionalFiles = false
    let inPermitExample = false
    let currentPermit = null

    lines.forEach(line => {
      const trimmedLine = line.trim()

      if (trimmedLine.startsWith('Naam:')) {
        currentFile = {
          name: trimmedLine.replace(/^[^:]+:\s*/, '').trim(),
          path: '',
          type: '',
          size: ''
        }
        result.files.push(currentFile)
      } else if (trimmedLine.startsWith('Pad:') && currentFile) {
        currentFile.path = trimmedLine.replace(/^[^:]+:\s*/, '').trim()
      } else if (trimmedLine.startsWith('Type:') && currentFile) {
        currentFile.type = trimmedLine.replace(/^[^:]+:\s*/, '').trim()
      } else if (trimmedLine.startsWith('Grootte:') && currentFile) {
        currentFile.size = trimmedLine.replace(/^[^:]+:\s*/, '').trim()
      } else if (trimmedLine.includes('Andere bestanden') || trimmedLine.includes('andere bestanden')) {
        inAdditionalFiles = true
      } else if (inAdditionalFiles && trimmedLine.startsWith('-')) {
        const fileMatch = trimmedLine.replace(/^-/, '').trim()
        const nameSizeMatch = fileMatch.match(/^(.+)\s+\(([^)]+)\)$/)
        if (nameSizeMatch) {
          result.additionalFiles.push({
            name: nameSizeMatch[1].trim(),
            size: nameSizeMatch[2]
          })
        }
      } else if (trimmedLine.startsWith('- Map:')) {
        result.structure = {
          path: trimmedLine.replace(/^- Map:\s*/, '').trim(),
          count: null,
          years: []
        }
      } else if (trimmedLine.startsWith('- Aantal permits:') && result.structure) {
        const countMatch = trimmedLine.match(/(\d+)/)
        if (countMatch) {
          result.structure.count = countMatch[1]
          const yearMatch = trimmedLine.match(/\((\d{4}-\d{4})\)/)
          if (yearMatch) {
            result.structure.years = yearMatch[1]
          }
        }
      } else if (trimmedLine.startsWith('Voorbeeld permit:') && !inPermitExample) {
        inPermitExample = true
        currentPermit = {
          name: trimmedLine.replace('Voorbeeld permit:', '').trim(),
          files: []
        }
        result.examplePermit = currentPermit
      } else if (inPermitExample && trimmedLine.startsWith('-')) {
        const fileMatch = trimmedLine.replace(/^-/, '').trim()
        const nameSizeMatch = fileMatch.match(/^(.+)\s+\(([^)]+)\)$/)
        if (nameSizeMatch && currentPermit) {
          currentPermit.files.push({
            name: nameSizeMatch[1].trim(),
            size: nameSizeMatch[2]
          })
        } else if (currentPermit) {
          currentPermit.files.push({
            name: fileMatch,
            size: ''
          })
        }
      } else if (!inAdditionalFiles && trimmedLine && !trimmedLine.includes('Naam:') &&
                 !trimmedLine.includes('Pad:') && !trimmedLine.includes('Type:') &&
                 !trimmedLine.includes('Grootte:') && !trimmedLine.startsWith('- Map:') &&
                 !trimmedLine.startsWith('- Aantal permits:') &&
                 !trimmedLine.startsWith('Voorbeeld permit:') &&
                 !inPermitExample && result.summary === '') {
        result.summary = trimmedLine
      }
    })

    return result
  }

  const parseFileSearchResult = (data) => {
    if (typeof data === 'string') {
      try {
        data = JSON.parse(data)
      } catch {
        return null
      }
    }

    if (data?.files && Array.isArray(data.files)) {
      return {
        files: data.files.map(f => ({
          name: f.name || f.path?.split('/').pop() || 'unknown',
          path: f.path || f.name || '',
          size: f.size ? `${(f.size / 1024).toFixed(1)} KB` : '',
          matches: f.matches || 0
        })),
        summary: `Found ${data.files.length} file${data.files.length !== 1 ? 's' : ''}`
      }
    }

    return null
  }

  const parseCommandOutput = (data) => {
    if (typeof data === 'string') {
      return {
        output: data,
        success: !data.toLowerCase().includes('error') && !data.toLowerCase().includes('failed')
      }
    }

    return {
      output: data?.output || data?.stdout || data?.message || JSON.stringify(data, null, 2),
      success: data?.success !== false && data?.exit_code === 0,
      exitCode: data?.exit_code,
      error: data?.stderr || data?.error
    }
  }

  const parseGitStatus = (data) => {
    if (typeof data === 'string') {
      try {
        data = JSON.parse(data)
      } catch {
        return null
      }
    }

    return {
      branch: data?.branch || 'main',
      staged: data?.staged || [],
      modified: data?.modified || [],
      untracked: data?.untracked || [],
      ahead: data?.ahead || 0,
      behind: data?.behind || 0
    }
  }

  const parseDockerResult = (data) => {
    if (typeof data === 'string') {
      try {
        data = JSON.parse(data)
      } catch {
        return {
          raw: data
        }
      }
    }

    return {
      success: data?.success !== false,
      containerId: data?.container_id || data?.id,
      containerName: data?.container_name,
      imageName: data?.image_name,
      port: data?.port || data?.ports?.[0],
      url: data?.url,
      logs: data?.logs,
      raw: JSON.stringify(data, null, 2)
    }
  }

  const copyToClipboard = (text) => {
    navigator.clipboard.writeText(text)
  }

  const formatFileSize = (sizeStr) => {
    if (!sizeStr) return ''
    return sizeStr.replace(/~/g, '').trim()
  }

  const isBestandZoeker = mcpAction?.includes('bestand_zoeker')
  const parsedData = isBestandZoeker ? parseBestandZoekerResult(answer) : null

  if (!answer) {
    console.log('[MCPResultCard] No answer to display')
    return null
  }

  return (
    <div className={`mt-3 rounded-lg border ${config.borderColor} ${config.bgColor} overflow-hidden`}>
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full px-4 py-3 flex items-center justify-between hover:bg-white/50 transition-colors"
      >
        <div className="flex items-center gap-2">
          <ConfigIcon className={`w-4 h-4 ${config.color}`} />
          <span className="text-sm font-semibold text-gray-700">{config.name}</span>
          {prompt && (
            <span className="text-xs text-gray-500 truncate max-w-xs">
              - {prompt.substring(0, 50)}{prompt.length > 50 ? '...' : ''}
            </span>
          )}
        </div>
        {expanded ? <ChevronUp className="w-4 h-4 text-gray-400" /> : <ChevronDown className="w-4 h-4 text-gray-400" />}
      </button>

      {expanded && (
        <div className="px-4 pb-4">
          {isBestandZoeker && parsedData && (parsedData.files.length > 0 || parsedData.structure) ? (
            <>
              {parsedData.summary && (
                <p className="text-sm text-gray-700 mb-3">{parsedData.summary}</p>
              )}

              {parsedData.structure && (
                <div className="bg-white rounded-lg border border-gray-200 p-3 mb-3">
                  <div className="flex items-start gap-3">
                    <Folder className="w-5 h-5 text-blue-500 flex-shrink-0 mt-0.5" />
                    <div className="flex-1 min-w-0 space-y-1">
                      <div className="font-medium text-gray-900">{parsedData.structure.path}</div>
                      <div className="text-xs text-gray-600">
                        {parsedData.structure.count} permits {parsedData.structure.years && `(${parsedData.structure.years})`}
                      </div>
                    </div>
                  </div>
                </div>
              )}

              {parsedData.examplePermit && (
                <div className="bg-white rounded-lg border border-gray-200 p-3 mb-3">
                  <div className="flex items-start gap-3 mb-2">
                    <FolderOpen className="w-5 h-5 text-orange-500 flex-shrink-0 mt-0.5" />
                    <div className="flex-1">
                      <div className="font-medium text-gray-900">{parsedData.examplePermit.name}</div>
                      <div className="text-xs text-gray-500 mt-1">Voorbeeld permit</div>
                    </div>
                  </div>
                  <div className="space-y-1">
                    {parsedData.examplePermit.files.map((file, idx) => (
                      <div key={idx} className="flex items-center gap-2 text-sm text-gray-600 pl-8">
                        <File className="w-3.5 h-3.5 text-gray-400 flex-shrink-0" />
                        <span className="truncate">{file.name}</span>
                        {file.size && <span className="text-xs text-gray-400 flex-shrink-0">({file.size})</span>}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {parsedData.files.map((file, idx) => (
                <div key={idx} className="bg-white rounded-lg border border-gray-200 p-3 mb-2">
                  <div className="flex items-start gap-3">
                    <File className="w-5 h-5 text-blue-500 flex-shrink-0 mt-0.5" />
                    <div className="flex-1 min-w-0 space-y-1.5">
                      <div className="flex items-center justify-between gap-2">
                        <span className="font-medium text-gray-900 truncate">{file.name}</span>
                        <span className="text-xs text-gray-500 flex-shrink-0">{formatFileSize(file.size)}</span>
                      </div>

                      <div className="flex items-center gap-2">
                        <Folder className="w-3.5 h-3.5 text-gray-400 flex-shrink-0" />
                        <span className="text-xs text-gray-600 truncate font-mono">{file.path}</span>
                        <button
                          onClick={() => copyToClipboard(file.path)}
                          className="flex-shrink-0 p-1 hover:bg-gray-100 rounded transition-colors"
                          title="Kopieer pad"
                        >
                          <Copy className="w-3.5 h-3.5 text-gray-400" />
                        </button>
                      </div>

                      {file.type && (
                        <div className="text-xs text-gray-500">
                          Type: <span className="font-medium">{file.type}</span>
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              ))}

              {parsedData.additionalFiles.length > 0 && (
                <div className="mt-3 pt-3 border-t border-gray-200">
                  <p className="text-xs font-semibold text-gray-600 mb-2">Andere bestanden in deze map:</p>
                  <div className="space-y-1">
                    {parsedData.additionalFiles.map((file, idx) => (
                      <div key={idx} className="flex items-center gap-2 text-sm text-gray-600">
                        <File className="w-3.5 h-3.5 text-gray-400 flex-shrink-0" />
                        <span className="truncate">{file.name}</span>
                        <span className="text-xs text-gray-400 flex-shrink-0">({file.size})</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </>
          ) : isBestandZoeker && (!parsedData || !parsedData.files.length) ? (
            <div className="bg-white rounded-lg border border-gray-200 p-3">
              <div className="flex items-start gap-3">
                <File className="w-5 h-5 text-blue-500 flex-shrink-0 mt-0.5" />
                <div className="flex-1 min-w-0">
                  <div className="font-medium text-gray-900 truncate">{answer}</div>
                  <div className="text-xs text-gray-500 mt-1">Bestandsnaam gevonden</div>
                </div>
              </div>
            </div>
          ) : mcpAction?.includes('filesearch') ? (
            (() => {
              const fileSearchData = parseFileSearchResult(answer)
              if (fileSearchData && fileSearchData.files) {
                return (
                  <>
                    <p className="text-sm text-gray-700 mb-3">{fileSearchData.summary}</p>
                    <div className="space-y-2">
                      {fileSearchData.files.map((file, idx) => (
                        <div key={idx} className="bg-white rounded-lg border border-gray-200 p-3">
                          <div className="flex items-start gap-3">
                            <FileText className="w-5 h-5 text-purple-500 flex-shrink-0 mt-0.5" />
                            <div className="flex-1 min-w-0">
                              <div className="font-medium text-gray-900 truncate">{file.name}</div>
                              <div className="flex items-center gap-2 mt-1">
                                <span className="text-xs text-gray-600 font-mono truncate">{file.path}</span>
                                <button
                                  onClick={() => copyToClipboard(file.path)}
                                  className="flex-shrink-0 p-1 hover:bg-gray-100 rounded transition-colors"
                                >
                                  <Copy className="w-3.5 h-3.5 text-gray-400" />
                                </button>
                              </div>
                              {file.matches > 0 && (
                                <span className="inline-block mt-1 text-xs bg-purple-100 text-purple-700 px-2 py-0.5 rounded-full">
                                  {file.matches} match{file.matches !== 1 ? 'es' : ''}
                                </span>
                              )}
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  </>
                )
              }
              return (
                <pre className="text-xs text-gray-700 whitespace-pre-wrap break-words">
                  {answer || 'No result data'}
                </pre>
              )
            })()
          ) : mcpAction?.includes('run_command') || mcpAction?.includes('run_tests') ? (
            (() => {
              const cmdResult = parseCommandOutput(answer)
              return (
                <div className={`rounded-lg p-3 ${config.bgColor === 'bg-gray-900' ? 'bg-gray-900' : 'bg-gray-900'}`}>
                  <div className="flex items-center gap-2 mb-2">
                    {cmdResult.success ? (
                      <CheckCircle className="w-4 h-4 text-green-400" />
                    ) : (
                      <XCircle className="w-4 h-4 text-red-400" />
                    )}
                    <span className="text-xs text-gray-400">
                      Exit code: {cmdResult.exitCode ?? 'N/A'}
                    </span>
                  </div>
                  <pre className={`text-xs font-mono whitespace-pre-wrap break-words ${config.bgColor === 'bg-gray-900' ? 'text-green-400' : 'text-gray-100'}`}>
                    {cmdResult.output}
                  </pre>
                  {cmdResult.error && (
                    <pre className="text-xs font-mono text-red-400 whitespace-pre-wrap break-words mt-2">
                      {cmdResult.error}
                    </pre>
                  )}
                </div>
              )
            })()
          ) : mcpAction?.includes('git_status') ? (
            (() => {
              const gitData = parseGitStatus(answer)
              if (!gitData) {
                return (
                  <pre className="text-xs text-gray-700 whitespace-pre-wrap break-words">
                    {answer || 'No git status data'}
                  </pre>
                )
              }
              return (
                <div className="space-y-3">
                  <div className="flex items-center gap-2">
                    <GitBranch className="w-4 h-4 text-orange-500" />
                    <span className="text-sm font-medium text-gray-900">{gitData.branch}</span>
                    {gitData.ahead > 0 && (
                      <span className="text-xs bg-green-100 text-green-700 px-2 py-0.5 rounded-full">
                        +{gitData.ahead} ahead
                      </span>
                    )}
                    {gitData.behind > 0 && (
                      <span className="text-xs bg-yellow-100 text-yellow-700 px-2 py-0.5 rounded-full">
                        -{gitData.behind} behind
                      </span>
                    )}
                  </div>

                  {gitData.staged.length > 0 && (
                    <div>
                      <p className="text-xs font-semibold text-gray-600 mb-1">Staged changes</p>
                      <div className="space-y-1">
                        {gitData.staged.map((file, idx) => (
                          <div key={idx} className="flex items-center gap-2 text-sm text-green-700">
                            <CheckCircle className="w-3.5 h-3.5 flex-shrink-0" />
                            <span className="truncate">{file}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {gitData.modified.length > 0 && (
                    <div>
                      <p className="text-xs font-semibold text-gray-600 mb-1">Modified</p>
                      <div className="space-y-1">
                        {gitData.modified.map((file, idx) => (
                          <div key={idx} className="flex items-center gap-2 text-sm text-orange-700">
                            <span className="text-orange-500 font-medium">M</span>
                            <span className="truncate">{file}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {gitData.untracked.length > 0 && (
                    <div>
                      <p className="text-xs font-semibold text-gray-600 mb-1">Untracked</p>
                      <div className="space-y-1">
                        {gitData.untracked.map((file, idx) => (
                          <div key={idx} className="flex items-center gap-2 text-sm text-gray-600">
                            <span className="text-gray-400">?</span>
                            <span className="truncate">{file}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              )
            })()
          ) : mcpAction?.includes('docker') ? (
            (() => {
              const dockerData = parseDockerResult(answer)
              if (dockerData.url) {
                return (
                  <div className="bg-white rounded-lg border border-gray-200 p-4">
                    <div className="flex items-center gap-2 mb-2">
                      <CheckCircle className="w-5 h-5 text-green-500" />
                      <span className="font-medium text-gray-900">Container Running</span>
                    </div>
                    <div className="space-y-1 text-sm text-gray-700">
                      {dockerData.containerName && (
                        <div><span className="text-gray-500">Name:</span> {dockerData.containerName}</div>
                      )}
                      {dockerData.imageName && (
                        <div><span className="text-gray-500">Image:</span> {dockerData.imageName}</div>
                      )}
                      {dockerData.port && (
                        <div><span className="text-gray-500">Port:</span> {dockerData.port}</div>
                      )}
                    </div>
                    <a
                      href={dockerData.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="mt-3 inline-flex items-center gap-2 px-4 py-2 bg-cyan-600 text-white rounded-lg hover:bg-cyan-700 transition-colors text-sm font-medium"
                    >
                      <CheckCircle className="w-4 h-4" />
                      Open App
                    </a>
                  </div>
                )
              }
              if (dockerData.logs) {
                return (
                  <div className="bg-gray-900 rounded-lg p-3">
                    <pre className="text-xs font-mono text-cyan-400 whitespace-pre-wrap break-words">
                      {dockerData.logs}
                    </pre>
                  </div>
                )
              }
              return (
                <pre className="text-xs text-gray-700 whitespace-pre-wrap break-words">
                  {dockerData.raw || answer || 'No docker data'}
                </pre>
              )
            })()
          ) : (
            <pre className="text-xs text-gray-700 whitespace-pre-wrap break-words">
              {answer || 'No result data'}
            </pre>
          )}
        </div>
      )}
    </div>
  )
}

export default MCPResultCard
