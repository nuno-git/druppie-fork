# MCP Server Host (Model Context Protocol)

## 🎯 Selectie: Standardized MCP Container
Voor het ontsluiten van tools en data naar de AI-modellen gebruiken we het **Model Context Protocol (MCP)**. We implementeren dit als een gestandaardiseerde container-architectuur (de "MCP Host") op basis van de officiële **TypeScript** of **Python** SDK's.

### 💡 Onderbouwing van de Keuze
Waarom kiezen we voor losse MCP Servers in plaats van alle tools in de Core te bakken?

1.  **Isolatie & Security**: Elke set van tools draait in zijn eigen Pod (bijv. `mcp-database-tools` of `mcp-weather-tools`). We kunnen per server exact instellen waar hij bij mag. De `mcp-weather` pod mag wel naar internet (api.weather.com), maar *niet* naar de interne database. De `mcp-database` pod mag *wel* naar de DB, maar *niet* naar internet. Dit is **Security by Design**.
2.  **Taal Agnostisch**: Een data-scientist kan een tool schrijven in Python (met Pandas/Numpy), terwijl een web-developer een tool schrijft in TypeScript. MCP abstraheert dit weg; voor de AI is het protocol identiek.
3.  **Schaalbaarheid**: Als de "Video Processing Tool" veel CPU nodig heeft, schalen we alleen die specifieke container op, zonder de rest van het platform te belasten.
4.  **Standaardisatie**: Door het MCP protocol te volgen, kunnen we in de toekomst ook externe agents of lokale clients (zoals Claude Desktop) laten verbinden met onze tools.

---

## 🛠️ Installatie

Een MCP server is een eenvoudige webserver (meestal via Server-Sent Events - SSE). We rollen deze uit met een standaard Kubernetes Deployment.

### 1. Base Image
Druppie biedt standaard base frames voor developers:
*   `ghcr.io/waterschap/druppie-mcp-node:latest`
*   `ghcr.io/waterschap/druppie-mcp-python:latest`

### 2. Deployment Manifest
Een voorbeeld deployment voor een "Weer Service".

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: mcp-weather
spec:
  replicas: 2
  selector:
    matchLabels:
      app: mcp-weather
  template:
    metadata:
      labels:
        app: mcp-weather
    spec:
      containers:
      - name: server
        image: my-registry/mcp-weather:v1
        env:
        - name: API_KEY
          valueFrom:
            secretKeyRef:
              name: weather-api-key
              key: key
        ports:
        - containerPort: 3000 # Standaard SSE poort
```

We ontsluiten dit intern via een Service:
```yaml
apiVersion: v1
kind: Service
metadata:
  name: mcp-weather-svc
spec:
  selector:
    app: mcp-weather
  ports:
  - port: 80
    targetPort: 3000
```

---

## 🚀 Gebruik (Implementatie)

De **Builder Agent** kan de code genereren om een tool te maken. Hier is een voorbeeld in TypeScript.

### 1. Code (`index.ts`)
```typescript
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { SSEServerTransport } from "@modelcontextprotocol/sdk/server/sse.js";

// Maak de server
const server = new McpServer({
  name: "weather-server",
  version: "1.0.0",
});

// Definieer een Tool
server.tool(
  "get_forecast",
  { city: z.string(), days: z.number().max(5) },
  async ({ city, days }) => {
    // Voer de logica uit (API call naar externe weerdienst)
    const forecast = await fetchWeather(city, days);
    return {
      content: [{ type: "text", text: JSON.stringify(forecast) }],
    };
  }
);

// Start de server (SSE mode voor Kubernetes)
const transport = new SSEServerTransport("/sse", "/messages");
server.connect(transport);
```

### 2. Registratie
Om de tool beschikbaar te maken, voegen we hem toe aan de **Bouwblok Definities** (Registry).
```json
{
  "name": "Weer Tools",
  "type": "mcp",
  "endpoint": "http://mcp-weather-svc.default.svc.cluster.local/sse"
}
```

## 🔄 Integratie in Druppie
1.  **Discovery**: Bij het opstarten (of runtime) scant **Druppie Core** de registry.
2.  **Connection**: De Core maakt een SSE verbinding met `http://mcp-weather-svc...`.
3.  **Tool Listing**: De MCP server stuurt een lijst terug: `["get_forecast"]`.
4.  **Execution**:
    *   Gebruiker vraagt: "Gaat het morgen regenen in Zwolle?"
    *   Planner kiest tool `get_forecast`.
    *   Core stuurt JSON commando naar de MCP pod.
    *   MCP pod voert code uit en stuurt antwoord terug.
