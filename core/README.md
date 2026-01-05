# Druppie Core

Druppie Core is the central orchestration service for the Druppie Platform. It functions as an autonomous agent system designed to plan, build, deploy, and govern software workloads.

## 🏗️ Build

### Docker (Production)
Since Druppie Core includes the UI and depends on project root context, you must build the image **from the repository root**:

```bash
cd ..
docker build -t druppie .
```

### Local CLI
To build the CLI tool for local testing:
```bash
go build -o ../druppie ./druppie
```

or just run :
```bash
go run ./druppie
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

## � Deploy & Test (Docker)

Once built, you can run Druppie Core as a standalone server with the integrated UI.

### 1. Simple Run
To run quickly with ephemeral storage (data lost on restart):
```bash
docker run -p 8080:80 druppie
```
Access the UI at `http://localhost:8080`.

### 2. Full Development Setup (Recommended)
This command maps your local `.druppie` configuration/data directory to the container, creating a fully persistent environment where you can edit plans, logs, and config locally.

```bash
docker run -d \
  -p 8080:80 \
  -v $(pwd)/.druppie:/app/.druppie \
  --name druppie-server \
  druppie
```

*   **Portal**: `http://localhost:8080` (Process Flow)
*   **Chat UI**: `http://localhost:8080/ui/`
*   **Logs**: Check `./.druppie/plans/<id>/logs` locally to see execution logs.
*   **Plans**: Plans are persisted in `./.druppie/plans/<id>/plan.json`.
*   **Config**: Edit `./.druppie/config.yaml` to change settings (e.g., LLM provider).

### 3. Updating an Existing Container
If you’ve made changes to the code or UI and want to update your running `druppie-server`:

1.  **Rebuild the Image**:
    ```bash
    docker build -t druppie .
    ```

2.  **Stop & Remove Old Container**:
    ```bash
    docker stop druppie-server && docker rm druppie-server
    ```

3.  **Start New Container**:
    (Using the recommended persistent setup)
    ```bash
    docker run -d \
      -p 8080:80 \
      -v $(pwd)/.druppie:/app/.druppie \
      --name druppie-server \
      druppie
    ```

## �🚀 Usage

### Local Testing (CLI)

1.  **Registry Dump**: List all loaded capabilities.
    ```bash
    ./druppie registry
    ```

2.  **Reactive Chat**: Talk to the mock agents.
    ```bash
    ./druppie chat
    ```

3.  **Plan Generation**: Generate a plan for a specific intent.
    ```bash
    ./druppie run "create a new project with golang"
    ```


4.  **Resume Plan**: Resume a stopped or interrupted plan by ID.
    ```bash
    ./druppie resume plan-12345
    ```
### Server Mode (New Features)

### Local CLI
To build the WebServer tool for local testing:
```bash
go build -o ../druppie ./cmd
```

Start the REST API server:
```bash
go run ./druppie serve
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

## 🔐 Authentication & Access Control

Druppie Core now supports multiple Identity Access Management (IAM) providers and Role-Based Access Control (RBAC) for registry filtering.

### 1. IAM Providers
You can configure the IAM provider in `config.yaml` or via environment variables (`IAM_PROVIDER`).
*   **Local** (Default): Uses a local user store (`.druppie/iam/users.json`). Good for single-user or small team testing.
*   **Keycloak**: Integrates with an external Keycloak instance for enterprise SSO.
*   **Demo**: Disables authentication obstacles and grants full admin access.

### 2. Local CLI Authentication
When using the CLI locally, you must authenticate to access protected resources (like Planner or Chat) unless you are in Demo mode.

**Login:**
```bash
./druppie login
# Prompts for Username and Password
# Default Admin: admin / admin
```
This saves a session token to `~/.druppie/token`.

**Logout:**
```bash
./druppie logout
```

### 3. Demo Mode
For quick testing without login, use the `--demo` flag. This forces the application to treat you as a "root" admin user.

```bash
# Run server in demo mode
./druppie serve --demo

# Use CLI tools in demo mode (skip login)
./druppie chat --demo
./druppie run "deploy database" --demo
```

### 4. RBAC & Filtering
Registry items (Agents, Skills, Building Blocks) can now be restricted by user groups. Items with an `auth_groups` field in their frontmatter will only be visible to users belonging to those groups.
*   **Admin/Root**: Sees everything.
*   **Unauthenticated**: Sees only public items (no `auth_groups` defined).

### 5. Plan Access Control
Plans are now governed by granular access control:
*   **Ownership**: Plans created by a user are assigned a `creator_id` matching their username.
*   **Group Access**: Plans can be shared with specific groups via the `allowed_groups` field. Users in these groups can view and interact with the plan.
*   **Demo Mode Protection**: When enabled, the Demo provider bypasses these checks, making all plans visible for demonstration purposes.

**Management Commands (Chat UI):**
*   `/add_group <group>`: Grant access to a plan for a user group.
*   `/remove_group <group>`: Revoke group access.
*   `/list_groups`: View currently authorized groups for the active plan.

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
   helm install druppie ./deploy/helm \
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
   helm install druppie ./deploy/helm \
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
