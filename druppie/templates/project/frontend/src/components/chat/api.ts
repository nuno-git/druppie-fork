import type { ChatSession, ChatMessage } from "./types"

const BASE = "/api/chat"

export async function createSession(): Promise<ChatSession> {
  const r = await fetch(`${BASE}/sessions`, { method: "POST" })
  return r.json()
}

export async function listSessions(): Promise<ChatSession[]> {
  const r = await fetch(`${BASE}/sessions`)
  return r.json()
}

export async function getSession(id: number): Promise<ChatSession & { messages: ChatMessage[] }> {
  const r = await fetch(`${BASE}/sessions/${id}`)
  return r.json()
}

export async function deleteSession(id: number): Promise<void> {
  await fetch(`${BASE}/sessions/${id}`, { method: "DELETE" })
}

export async function renameSession(id: number, title: string): Promise<ChatSession> {
  const r = await fetch(`${BASE}/sessions/${id}/rename`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title }),
  })
  return r.json()
}

export async function sendMessage(sessionId: number, message: string): Promise<ChatMessage> {
  const r = await fetch(`${BASE}/sessions/${sessionId}/messages`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message }),
  })
  return r.json()
}
