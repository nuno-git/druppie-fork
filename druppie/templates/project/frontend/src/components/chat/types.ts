export interface ChatSession {
  id: number
  title: string
  created_at: string
  updated_at: string
  message_count: number
}

export interface AgentStep {
  type: string  // "search", "query", "tool", "reasoning"
  label: string
  detail: string | string[] | Record<string, unknown> | null
}

export interface ChatMessage {
  id: number
  role: "user" | "assistant"
  content: string
  steps: AgentStep[] | null
  created_at: string
}
