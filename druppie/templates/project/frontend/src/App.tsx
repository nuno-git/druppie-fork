import { useEffect, useState } from "react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"

function App() {
  const [appName, setAppName] = useState("My App")

  useEffect(() => {
    fetch("/api/info")
      .then((res) => res.json())
      .then((data) => setAppName(data.app_name))
      .catch(() => {})
  }, [])

  return (
    <div className="min-h-screen bg-background">
      <header className="border-b">
        <div className="container mx-auto flex h-16 items-center px-4">
          <h1 className="text-xl font-bold">{appName}</h1>
        </div>
      </header>
      <main className="container mx-auto px-4 py-8">
        <Card className="mx-auto max-w-2xl">
          <CardHeader>
            <CardTitle>Welcome to {appName}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <p className="text-muted-foreground">
              Your application is up and running. Start building by editing the
              source code.
            </p>
            <Button>Get Started</Button>
          </CardContent>
        </Card>
      </main>
    </div>
  )
}

export default App
