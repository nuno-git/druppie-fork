import { useEffect, useState } from "react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { ChatPanel } from "@/components/chat"

interface SearchResult {
  title: string
  url: string
  snippet: string
}

function App() {
  const [appName, setAppName] = useState("My App")
  const [tab, setTab] = useState<"home" | "search" | "chat">("home")

  useEffect(() => {
    fetch("/api/info")
      .then((res) => res.json())
      .then((data) => setAppName(data.app_name))
      .catch(() => {})
  }, [])

  return (
    <div className="min-h-screen bg-background flex flex-col">
      <header className="border-b bg-card shrink-0">
        <div className="container mx-auto flex h-14 items-center justify-between px-4">
          <h1 className="text-lg font-bold">{appName}</h1>
          <div className="flex gap-1">
            <Button variant={tab === "home" ? "default" : "ghost"} size="sm" onClick={() => setTab("home")}>
              Home
            </Button>
            <Button variant={tab === "search" ? "default" : "ghost"} size="sm" onClick={() => setTab("search")}>
              Web Search
            </Button>
            <Button variant={tab === "chat" ? "default" : "ghost"} size="sm" onClick={() => setTab("chat")}>
              Assistent
            </Button>
          </div>
        </div>
      </header>

      {tab === "home" && (
        <main className="container mx-auto px-4 py-8 max-w-2xl">
          <Card>
            <CardHeader>
              <CardTitle>{appName}</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-muted-foreground">
                Welkom! Klik op <strong>Assistent</strong> om te chatten met de AI-assistent,
                of pas deze pagina aan voor je eigen applicatie.
              </p>
            </CardContent>
          </Card>
        </main>
      )}

      {tab === "search" && <SearchPage />}

      {tab === "chat" && (
        <div className="flex-1 overflow-hidden">
          <ChatPanel />
        </div>
      )}
    </div>
  )
}

function SearchPage() {
  const [query, setQuery] = useState("")
  const [results, setResults] = useState<SearchResult[]>([])
  const [loading, setLoading] = useState(false)
  const [searched, setSearched] = useState(false)

  const search = async () => {
    if (!query.trim()) return
    setLoading(true)
    setSearched(true)
    try {
      const r = await fetch("/api/ai/search", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: query.trim() }),
      })
      const data = await r.json()
      setResults(data.results || [])
    } catch {
      setResults([])
    } finally {
      setLoading(false)
    }
  }

  return (
    <main className="container mx-auto px-4 py-8 max-w-2xl space-y-4">
      <Card>
        <CardHeader>
          <CardTitle>Web Search</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex gap-2">
            <Input
              value={query}
              onChange={e => setQuery(e.target.value)}
              onKeyDown={e => e.key === "Enter" && search()}
              placeholder="Zoek op het web..."
              disabled={loading}
            />
            <Button onClick={search} disabled={loading || !query.trim()}>
              {loading ? "Zoeken..." : "Zoek"}
            </Button>
          </div>
        </CardContent>
      </Card>

      {searched && (
        <Card>
          <CardContent className="pt-5">
            {loading ? (
              <p className="text-center text-muted-foreground py-4">Zoeken...</p>
            ) : results.length === 0 ? (
              <p className="text-center text-muted-foreground py-4">Geen resultaten gevonden.</p>
            ) : (
              <div className="divide-y">
                {results.map((r, i) => (
                  <div key={i} className="py-3">
                    <a href={r.url} target="_blank" rel="noopener noreferrer" className="text-primary hover:underline font-medium">
                      {r.title}
                    </a>
                    <p className="text-xs text-muted-foreground mt-0.5">{r.url}</p>
                    <p className="text-sm mt-1">{r.snippet}</p>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      )}
    </main>
  )
}

export default App
