# Druppie Helm Chart

Deploy Druppie Core to a Kubernetes cluster using Helm.

## Prerequisites

- Kubernetes 1.19+
- Helm 3.0+
- PV provisioner support in the underlying infrastructure (for persistence)

## Installation

1. Navigate to the chart directory:
   ```bash
   cd core/deploy/helm
   ```

2. Install the chart:
   ```bash
   helm install druppie . -n druppie --create-namespace
   ```

3. Watch the deployment status:
   ```bash
   kubectl get pods -n druppie -w
   ```

## Configuration

The following table lists the configurable parameters of the Druppie chart and their default values. The chart is structured to allow full configuration of the Druppie application via the `config` section.

| Parameter | Description | Default |
|-----------|-------------|---------|
| `image.repository` | Docker image repository | `druppie` |
| `image.tag` | Docker image tag | `latest` |
| `persistence.enabled` | Enable persistent storage for plans/plugins | `true` |
| `persistence.size` | Size of persistent volume | `1Gi` |
| `config.server.port` | Application server port | `"8080"` |
| `config.llm.providers` | LLM Provider configurations | `gemini` (see values.yaml) |
| `config.iam.provider` | Identity provider (`local`, `keycloak`, `demo`) | `local` |
| `config.build.provider` | Build provider (`tekton`, `docker`, `local`) | `tekton` |
| `env.GEMINI_API_KEY` | API Key for Gemini (if using Gemini provider) | `change-me` |

### Detailed Configuration Guide

The `config` section maps directly to the application's configuration. Here are the available options for each component:

#### LLM Providers (`config.llm`)
You can configure multiple LLM providers. Supported types: `gemini`, `ollama`, `openrouter`.

**Example: Using Ollama (Local)**
```yaml
config:
  llm:
    default_provider: ollama
    providers:
      ollama:
        type: ollama
        model: llama3
        url: "http://ollama-service:11434" # URL to your Ollama instance
        price_per_prompt_token: 0
        price_per_completion_token: 0
```

**Example: Using OpenRouter**
```yaml
config:
  llm:
    default_provider: openrouter
    providers:
      openrouter:
        type: openrouter
        model: "anthropic/claude-3-opus"
        # Set api_key via environment variable OPENROUTER_API_KEY in 'env' section
```

#### Build Providers (`config.build`)
Controls how code execution and plugin building is handled.

*   `tekton`: Uses Kubernetes Tekton Pipelines (Recommended for Cluster).
*   `docker`: Uses local Docker socket (Recommended for local testing).
*   `local`: Runs commands directly on the host (Not recommended for production).

```yaml
config:
  build:
    default_provider: tekton
    providers:
      tekton:
        type: tekton
        namespace: druppie-pipelines # Namespace where Tekton Tasks/Pipelines run
```

#### IAM Providers (`config.iam`)
Identity and Access Management configuration.

*   `local`: Simple file-based user management (stored in persistence).
*   `keycloak`: Integration with Keycloak OIDC.
*   `demo`: No authentication (Dangerous! Use only for isolated demos).

```yaml
config:
  iam:
    provider: keycloak
    keycloak:
      url: "https://auth.example.com"
      realm: "druppie"
      client_id: "druppie-core"
```

#### Advanced Settings

**Approval Groups** defines who can approve sensitive actions:
```yaml
config:
    approval_groups:
        security: ["ciso", "group-admin"]
        legal: ["legal", "group-admin"]
        compliance: ["compliance","group-admin"]
        privacy: ["privacy","group-admin"]
```

**Memory & Planning defaults**:
```yaml
config:
  memory:
    max_window_tokens: 16000
    summarize_after: 30
  planner:
    max_agent_selection: 5
```

Then install using:
```bash
helm install druppie . -f my-values.yaml
```

## Persistence

By default, the chart creates a PersistentVolumeClaim to store the `.druppie` directory (containing Plans and Plugins). This ensures that your agent interactions and created plugins persist across Pod restarts.

To disable persistence (for testing only):
```bash
helm install druppie . --set persistence.enabled=false
```
