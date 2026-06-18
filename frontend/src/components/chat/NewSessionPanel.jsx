/**
 * New Session Panel - shown when no session is selected in Chat
 */

import { useState, useRef, useEffect } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Send, Shield, Loader2, FileType, FileText } from 'lucide-react'
import { sendChat } from '../../services/api'
import { setPending } from '../../services/pendingChat'
import FileUploadButton from './FileUploadButton'
import AttachmentChips from './AttachmentChips'

const NEW_SESSION_SUGGESTIONS = [
  'Start een nieuw project',
  'Beoordeel mijn code-architectuur',
  'Help me een app te deployen',
  'Schrijf een feature-specificatie',
]

const NewSessionPanel = ({ onSessionCreated }) => {
  const [input, setInput] = useState('')
  const [attachments, setAttachments] = useState([])
  const [uploadError, setUploadError] = useState(null)
  const inputRef = useRef(null)
  const pendingMessageRef = useRef(null)
  const pendingAttachmentsRef = useRef([])
  const queryClient = useQueryClient()

  const mutation = useMutation({
    mutationFn: ({ message, attachmentIds }) => sendChat(message, null, null, attachmentIds),
    onSuccess: (data) => {
      const msg = pendingMessageRef.current
      pendingMessageRef.current = null
      setInput('')
      setAttachments([])
      queryClient.invalidateQueries({ queryKey: ['sessions'] })
      if (data.session_id) {
        setPending(data.session_id, msg, pendingAttachmentsRef.current)
        onSessionCreated(data.session_id)
      }
    },
  })

  // Auto-resize textarea
  useEffect(() => {
    if (inputRef.current) {
      inputRef.current.style.height = 'auto'
      inputRef.current.style.height = Math.min(inputRef.current.scrollHeight, 160) + 'px'
    }
  }, [input])

  const handleSend = (text) => {
    const trimmed = (text || input).trim()
    if (!trimmed && !attachments.length) return
    setUploadError(null)
    const fallback = attachments.length
      ? attachments.map((a) => a.original_filename).join(', ')
      : 'See attached'
    const message = trimmed || fallback
    pendingMessageRef.current = message
    pendingAttachmentsRef.current = attachments.map((a) => ({ id: a.id, original_filename: a.original_filename, content_type: a.content_type }))
    mutation.mutate({ message, attachmentIds: attachments.map((a) => a.id) })
  }

  if (mutation.isPending) {
    const atts = pendingAttachmentsRef.current
    const isAttachmentOnly = atts.length > 0 && (pendingMessageRef.current === atts.map((a) => a.original_filename).join(', ') || pendingMessageRef.current === 'See attached')
    return (
      <div className="flex flex-col h-full">
        <div className="flex-1 overflow-y-auto">
          <div className="max-w-3xl mx-auto px-4 py-6 space-y-6">
            <div className="flex justify-end gap-2">
              <div className="max-w-[85%] rounded-2xl px-4 py-2.5 text-sm bg-gray-100 text-gray-900 overflow-hidden">
                {!isAttachmentOnly && (
                  <div className="whitespace-pre-wrap break-words">{pendingMessageRef.current}</div>
                )}
                {atts.length > 0 && (
                  <div className={`flex flex-wrap gap-1.5${isAttachmentOnly ? '' : ' mt-2'}`}>
                    {atts.map((att) => {
                      const Icon = att.content_type === 'application/pdf' ? FileType : FileText
                      return (
                        <span key={att.id} className="inline-flex items-center gap-1.5 px-2.5 py-1 bg-white/60 rounded-lg text-xs text-gray-600">
                          <Icon className="w-3.5 h-3.5 text-gray-400" />
                          <span className="truncate max-w-[120px]">{att.original_filename}</span>
                        </span>
                      )
                    })}
                  </div>
                )}
              </div>
            </div>
            <div className="flex items-center py-1">
              <Loader2 className="w-3.5 h-3.5 text-gray-400 animate-spin" />
            </div>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full">
      {/* Center greeting */}
      <div className="flex-1 flex flex-col items-center justify-center px-4">
        <div className="w-12 h-12 bg-blue-600 rounded-xl flex items-center justify-center mb-6">
          <Shield className="w-7 h-7 text-white" />
        </div>
        <h1 className="text-2xl font-semibold text-gray-900 mb-2">
          Wat wil je bouwen?
        </h1>
        <p className="text-gray-400 text-sm mb-8">
          Start een nieuwe governance-sessie
        </p>
        <div className="flex flex-wrap justify-center gap-2 max-w-lg">
          {NEW_SESSION_SUGGESTIONS.map((s) => (
            <button
              key={s}
              onClick={() => handleSend(s)}
              className="px-4 py-2 text-sm border border-gray-200 rounded-full text-gray-600 hover:bg-gray-50 hover:border-gray-300 transition-colors"
            >
              {s}
            </button>
          ))}
        </div>
      </div>

      {/* Floating input bar */}
      <div className="px-4 pb-4 pt-2 flex-shrink-0">
        <div className="max-w-3xl mx-auto">
          <div className="border border-gray-200 rounded-2xl shadow-lg px-4 py-3 bg-white focus-within:border-gray-300 focus-within:shadow-xl transition-shadow">
            <AttachmentChips
              attachments={attachments}
              onRemove={(id) => setAttachments((prev) => prev.filter((a) => a.id !== id))}
            />
            <div className="flex items-end gap-2">
              <FileUploadButton
                onUpload={(att) => { setUploadError(null); setAttachments((prev) => [...prev, att]) }}
                onError={setUploadError}
              />
              <textarea
                ref={inputRef}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault()
                    handleSend()
                  }
                }}
                placeholder="Beschrijf wat je wilt bouwen..."
                rows={1}
                className="flex-1 resize-none bg-transparent outline-none text-sm leading-6 py-1 max-h-40"
              />
              <button
                onClick={() => handleSend()}
                disabled={!input.trim() && !attachments.length}
                className="flex-shrink-0 p-2 rounded-xl bg-gray-900 text-white hover:bg-gray-700 disabled:opacity-30 disabled:hover:bg-gray-900 transition-colors"
              >
                <Send className="w-4 h-4" />
              </button>
            </div>
          </div>
          {(mutation.isError || uploadError) && (
            <p className="mt-2 text-xs text-red-600 text-center">
              {mutation.error?.message || uploadError}
            </p>
          )}
        </div>
      </div>
    </div>
  )
}

export default NewSessionPanel
