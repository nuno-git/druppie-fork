# Druppie

Druppie is an AI-powered task orchestration platform with support for multiple LLM providers, workflow management, and a web-based chat interface.

## Prerequisites

- Go 1.24+ (see installation below)
- Optional: Ollama for local LLM inference
- Optional: API keys for cloud LLM providers (Gemini, OpenRouter, Z.AI)

## Installing Go

```bash
# Download and install Go 1.24.4
wget https://go.dev/dl/go1.24.4.linux-amd64.tar.gz -O /tmp/go.tar.gz
mkdir -p ~/go-install
tar -C ~/go-install -xzf /tmp/go.tar.gz

# Add to your shell profile (~/.bashrc or ~/.zshrc)
export PATH=$HOME/go-install/go/bin:$PATH
export GOPATH=$HOME/go
```

## Building

```bash
cd core
go mod download
go build -o druppie/druppie ./druppie
```

## Running

```bash
cd core
./druppie/druppie serve
```

The server starts on port 8080 by default. Access the UI at: http://localhost:8080

## Default Login

- **Username:** `admin`
- **Password:** `admin`

## Configuration

On first run, Druppie automatically creates `.druppie/config.yaml` from `core/config_default.yaml`.

Edit `.druppie/config.yaml` to configure:

### LLM Providers

```yaml
llm:
  default_provider: ollama  # or gemini, openrouter, zai
  providers:
    gemini:
      api_key: "your-gemini-api-key"
    openrouter:
      api_key: "your-openrouter-api-key"
    ollama:
      url: http://localhost:11434
      model: qwen3:8b
```

### Server Port

```yaml
general:
  server_port: "8080"
```

## Project Structure

```
core/           # Go backend
  druppie/      # Main application entry point
  internal/     # Internal packages (router, planner, executor, etc.)
ui/             # Web chat interface
sherpa-server/  # TTS server (optional)
.druppie/       # Runtime data (auto-created, gitignored)
  config.yaml   # Your configuration
  plans/        # Execution plans
  iam/          # User/session data
```

## Available Commands

```bash
./druppie/druppie serve      # Start API server (default)
./druppie/druppie chat       # Interactive chat mode
./druppie/druppie run        # Run a plan for a prompt
./druppie/druppie registry   # Dump loaded registry
./druppie/druppie mcp        # Manage MCP integrations
./druppie/druppie login      # Login to local provider
./druppie/druppie logout     # Logout from session
```
