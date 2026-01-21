/**
 * CodeBlock Component - Syntax highlighted code display with copy functionality
 */

import React, { useEffect, useRef, useState } from 'react'
import Prism from 'prismjs'

// Import Prism languages
import 'prismjs/components/prism-python'
import 'prismjs/components/prism-javascript'
import 'prismjs/components/prism-typescript'
import 'prismjs/components/prism-jsx'
import 'prismjs/components/prism-tsx'
import 'prismjs/components/prism-json'
import 'prismjs/components/prism-yaml'
import 'prismjs/components/prism-bash'
import 'prismjs/components/prism-css'
import 'prismjs/components/prism-markup'
import 'prismjs/components/prism-markdown'
import 'prismjs/components/prism-go'
import 'prismjs/components/prism-rust'
import 'prismjs/components/prism-java'
import 'prismjs/components/prism-c'
import 'prismjs/components/prism-cpp'
import 'prismjs/components/prism-sql'
import 'prismjs/components/prism-docker'

// Line numbers plugin
import 'prismjs/plugins/line-numbers/prism-line-numbers'

import { Copy, Check } from 'lucide-react'

// Language mapping for file extensions
const extensionToLanguage = {
  py: 'python',
  js: 'javascript',
  jsx: 'jsx',
  ts: 'typescript',
  tsx: 'tsx',
  json: 'json',
  yaml: 'yaml',
  yml: 'yaml',
  sh: 'bash',
  bash: 'bash',
  zsh: 'bash',
  css: 'css',
  scss: 'css',
  html: 'markup',
  htm: 'markup',
  xml: 'markup',
  svg: 'markup',
  md: 'markdown',
  markdown: 'markdown',
  go: 'go',
  rs: 'rust',
  java: 'java',
  c: 'c',
  h: 'c',
  cpp: 'cpp',
  cc: 'cpp',
  cxx: 'cpp',
  hpp: 'cpp',
  sql: 'sql',
  dockerfile: 'docker',
}

// Get language from filename or explicit language prop
const getLanguage = (language, filename) => {
  if (language) {
    return language
  }
  if (filename) {
    const ext = filename.split('.').pop()?.toLowerCase()
    if (ext && extensionToLanguage[ext]) {
      return extensionToLanguage[ext]
    }
    // Handle special filenames
    const lowerFilename = filename.toLowerCase()
    if (lowerFilename === 'dockerfile') {
      return 'docker'
    }
    if (lowerFilename === 'makefile') {
      return 'bash'
    }
  }
  return 'text'
}

const CodeBlock = ({ code, language, filename, showLineNumbers = true }) => {
  const codeRef = useRef(null)
  const [copied, setCopied] = useState(false)

  const resolvedLanguage = getLanguage(language, filename)

  useEffect(() => {
    if (codeRef.current) {
      Prism.highlightElement(codeRef.current)
    }
  }, [code, resolvedLanguage])

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(code)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch (err) {
      console.error('Failed to copy:', err)
    }
  }

  const lines = code.split('\n')
  const lineCount = lines.length

  return (
    <div className="relative rounded-lg overflow-hidden bg-gray-900 border border-gray-700">
      {/* Header with language badge and copy button */}
      <div className="flex items-center justify-between px-4 py-2 bg-gray-800 border-b border-gray-700">
        <div className="flex items-center space-x-2">
          {filename && (
            <span className="text-sm text-gray-400 font-mono">{filename}</span>
          )}
          <span className="px-2 py-0.5 text-xs font-medium rounded bg-gray-700 text-gray-300">
            {resolvedLanguage}
          </span>
        </div>
        <button
          onClick={handleCopy}
          className="flex items-center px-2 py-1 text-xs text-gray-400 hover:text-white hover:bg-gray-700 rounded transition-colors"
          title="Copy code"
        >
          {copied ? (
            <>
              <Check className="w-4 h-4 mr-1 text-green-400" />
              <span className="text-green-400">Copied!</span>
            </>
          ) : (
            <>
              <Copy className="w-4 h-4 mr-1" />
              <span>Copy</span>
            </>
          )}
        </button>
      </div>

      {/* Code content with line numbers */}
      <div className="overflow-x-auto">
        <div className="flex min-w-full">
          {/* Line numbers column */}
          {showLineNumbers && (
            <div className="flex-shrink-0 py-4 px-2 text-right select-none bg-gray-800/50 border-r border-gray-700">
              {lines.map((_, index) => (
                <div
                  key={index}
                  className="text-xs text-gray-500 font-mono leading-6 px-2"
                >
                  {index + 1}
                </div>
              ))}
            </div>
          )}

          {/* Code content */}
          <div className="flex-1 overflow-x-auto">
            <pre className="p-4 m-0 text-sm leading-6">
              <code
                ref={codeRef}
                className={`language-${resolvedLanguage} font-mono`}
              >
                {code}
              </code>
            </pre>
          </div>
        </div>
      </div>
    </div>
  )
}

export default CodeBlock
