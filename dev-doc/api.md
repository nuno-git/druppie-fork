# HTTP API Reference

Druppie Core exposes a RESTful API on port `8080`.

## Base URL
`http://localhost:8080`

## Authentication
If an IAM provider (Keycloak) is configured, requests must include a `Authorization: Bearer <token>` header.
For local/demo usage, auth is often bypassed or handled via Mock tokens.

---

## 💬 Chat & Interaction

### `POST /v1/chat/completions`
Send a user prompt to start or continue a plan.

**Request Body:**
```json
{
  "prompt": "Create a new video for instagram",
  "plan_id": "plan-12345"  // Optional: to continue existing conversation
}
```

**Response:**
Returns the Plan ID immediately. The actual processing happens asynchronously (Polling required).
```json
{
  "intent": { "action": "analyzing" },
  "plan": { "id": "plan-12345", "status": "running" }
}
```

---

## 📋 Plans

### `GET /v1/plans`
List all execution plans visible to the user.

**Response:** Array of Plan objects.

### `GET /v1/plans/{id}`
Get details of a specific plan, including all steps and logs.

---

## 🛠️ MCP (Model Context Protocol)

### `GET /v1/mcp/servers`
List connected MCP servers and their capabilities.

### `POST /v1/mcp/servers`
Register a new MCP server dynamically.
```json
{
  "name": "my-server",
  "url": "http://localhost:3000"
}
```

---

## ⚙️ Configuration

### `GET /v1/config`
Retrieve current system configuration (sanitized).

### `PUT /v1/config`
Update system configuration (e.g. switch LLM provider).
