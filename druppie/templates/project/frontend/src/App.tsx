import { useEffect, useState } from "react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { ChatPanel } from "@/components/chat"

function App() {
  const [appName, setAppName] = useState("My App")
  const [tab, setTab] = useState<"home" | "chat">("home")

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

      {tab === "chat" && (
        <div className="flex-1 overflow-hidden">
          <ChatPanel />
        </div>
      )}
    </div>
  )
}

export default App
