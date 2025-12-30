# Druppie Core

Druppie Core is the central orchestration service for the Druppie Platform. It functions as an autonomous agent system designed to plan, build, deploy, and govern software workloads.

## 🏗️ Build

### Docker
To build the production image:
```bash
docker build -t druppie-core .
```

### Local CLI
To build the CLI tool for local testing:
```bash
go build -o druppie-core ./cmd
```

or just run :
```bash
go run ./cmd
```

### Gemini Setup

To use Google Gemini, you need to configure OAuth credentials:

1.  Go to **Google Cloud Console** > **APIs & Services** > **Credentials**.
2.  Click **Create Credentials** > **OAuth client ID**.
3.  Select **Web application** as the application type.
4.  Add `http://localhost:8085/oauth2callback` to **Authorized redirect URIs**.
5.  Click **Create** and copy the **Client ID** and **Client Secret**.
6.  Update your `config.yaml`:
    ```yaml
    llm:
      providers:
        gemini:
          project_id: "your-project-id-string"
          client_id: "YOUR_CLIENT_ID"
          client_secret: "YOUR_CLIENT_SECRET"
    ```

## 🚀 Usage

### Local Testing (CLI)

1.  **Registry Dump**: List all loaded capabilities.
    ```bash
    ./druppie-core registry
    ```

2.  **Reactive Chat**: Talk to the mock agents.
    ```bash
    ./druppie-core chat
    ```

3.  **Plan Generation**: Generate a plan for a specific intent.
    ```bash
    ./druppie-core plan "create a new project with golang"
    ```
    

### Server Mode (New Features)

### Local CLI
To build the WebServer tool for local testing:
```bash
go build -o druppie-server ./cmd
```

Start the REST API server:
```bash
go run ./cmd
```

**Testing Config API:**
```bash
# Get Config
curl localhost:8080/v1/config

# Update Config (Switch to Real Gemni)
curl -X PUT -d '{"llm":{"provider":"gemini","model":"gemini-pro"},"server":{"port":"8080"}}' localhost:8080/v1/config
```

**Testing Build Trigger:**
```bash
curl -X POST -d '{"repo_url":"https://github.com/my/repo", "commit_hash":"HEAD"}' localhost:8080/v1/build
```

**Endpoins:**
- `GET /v1/registry`: List all building blocks.
- `GET /v1/agents`: List available agents.
- `GET /v1/mcps`: List available MCP servers. 
- `GET /v1/skills`: List available skills.
- `PUT /v1/config`: Update configuration.
- `POST /v1/chat/completions`: Analyze intent and generate plans.

## 📦 Git Configuration

Druppie Core requires a Git repository to store project code. You can use the internal Gitea instance (default) or an external provider.

### Option A: Internal Gitea (Default)
Use the Gitea instance running inside the same Kubernetes cluster.

1. **Create Token Secret**:
   ```bash
   kubectl create secret generic gitea-token --from-literal=token=YOUR_GITEA_TOKEN
   ```

2. **Install Chart**:
   ```bash
   helm install druppie-core ./deploy/helm \
     --set git.provider="gitea" \
     --set git.url="http://gitea-http.gitea.svc.cluster.local:3000" \
     --set git.user="my-org" \
     --set git.tokenSecretName="gitea-token"
   ```
   *(Note: These are the default values, but shown here for clarity)*

### Option B: External (GitHub/GitLab)
Use an external provider like GitHub.

1. **Create Token Secret**:
   ```bash
   kubectl create secret generic github-token --from-literal=token=YOUR_GITHUB_TOKEN
   ```

2. **Install Chart** (with overrides):
   ```bash
   helm install druppie-core ./deploy/helm \
     --set git.provider="github" \
     --set git.url="https://api.github.com" \
     --set git.user="my-org" \
     --set git.tokenSecretName="github-token"
   ```

## 🧩 Architecture

- **Registry**: Loads capabilities from `../blocks`, `../mcp`, `../agents`, and `../skills`.
- **Router**: Analyzes user intent using LLM.
- **Planner**: Generates execution plans.
- **API**: Exposes functionality via HTTP.
