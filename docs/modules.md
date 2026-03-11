# Druppie Module Convention — Design Research

> **Status**: Design / brainstorm phase
> **Date**: 2026-02-24
> **Author**: Druppie team
> **User Story**: Als Druppie-teamlid wil ik een gestandaardiseerd format/contract voor core-modules, zodat uitbreidingen op een uniforme manier worden toegevoegd ongeacht wie ze bouwt.

---

## Table of Contents

1. [What Is a Module?](#1-what-is-a-module)
2. [Five Approaches to Module Design](#2-five-approaches-to-module-design)
   - [Approach A: Built-in MCP Servers](#approach-a-built-in-mcp-servers)
   - [Approach B: Library / Import Pattern](#approach-b-library--import-pattern)
   - [Approach C: SDK + MCP Hybrid (Thin Client, Remote Logic)](#approach-c-sdk--mcp-hybrid)
   - [Approach D: Template-Based Code Generation](#approach-d-template-based-code-generation)
   - [Approach E: Composable MCP with Shared DB + API Gateway](#approach-e-composable-mcp-with-shared-db--api-gateway)
3. [Comparative Analysis](#3-comparative-analysis)
4. [Test Cases](#4-test-cases)
5. [Authentication: OBO Token Exchange](#5-authentication-obo-token-exchange)
6. [Governance & Cost Tracking](#6-governance--cost-tracking)
7. [Agent Roles in Module Development](#7-agent-roles-in-module-development)
8. [Impact on Current Environment](#8-impact-on-current-environment)
9. [Recommendation](#9-recommendation)
10. [Sources](#10-sources)

---

## 1. What Is a Module?

Druppie builds applications for users through AI agents. These applications need reusable capabilities — OCR, document classification, cost tracking, authentication templates, etc. Modules are the **building blocks that Druppie uses in the applications he builds**. Think of them as the standard parts in a toolbox: when Druppie builds an invoice processor, he grabs the OCR module; when he builds a document portal, he grabs the classifier module. The modules live in the Druppie core, and every application Druppie creates can use them.

A module is a **self-contained, reusable capability** that:

1. Is a **building block for applications** — Druppie integrates modules into the apps he builds for users
2. Exposes a **well-defined contract** (input/output schema) so any application can use it the same way
3. Can be **added to the core** — extending Druppie's platform capabilities for all future applications
4. Is **generic** — works across different application types, not tied to one specific use case
5. Supports **governance** — cost tracking, access control, and audit per user
6. Is **invocable** by both Druppie agents (during build-time) and generated applications (at runtime via SDK)

This document explores **five fundamentally different approaches** to defining these modules and recommends the best fit for Druppie's architecture.

### Test Cases for Validation

Throughout this document, we validate each approach against two concrete modules:

| Module | Description | Complexity |
|--------|-------------|------------|
| **OCR Module** | Extracts text from PDF, Word, JPG/PNG with standardized JSON output | High (binary processing, ML models, GPU optional) |
| **Document Classifier** | Determines document category (e.g., "vergunning") with confidence score | Medium (ML inference, configurable categories) |

### Module vs. Existing Concepts

| Concept | What it is | How a module differs |
|---------|-----------|---------------------|
| **MCP Server** | A containerized tool provider (coding, docker, web) | A module IS an MCP server, but with a standardized contract, DB schema, and SDK integration |
| **Skill** | A reusable prompt fragment with tool permissions | Skills are agent instructions; modules are runnable services |
| **Agent** | A YAML-defined AI persona with tool access | Agents USE modules; they don't contain module logic |
| **Builtin Tool** | In-process tools (done, invoke_skill) | No HTTP overhead, but no isolation; modules run in containers |

### Module Scoping: When to Split vs. Combine

The OCR and Document Classifier are two separate modules, not one "document-processing" module. This is intentional and illustrates the scoping principle:

**Split into separate modules when:**
- They have **different runtime dependencies** (OCR needs Tesseract/GPU, classifier needs an ML model)
- They have **independent release cycles** (OCR can get a bugfix without touching the classifier)
- They can be **used independently** (not every app that needs OCR also needs classification)
- They need **different scaling** (OCR may need GPU, classifier may not)

**Combine into one module when:**
- The tools share the **same heavy dependencies** and would duplicate them in separate containers
- The tools operate on the **same internal state or DB schema**
- One tool without the other **makes no sense** in any realistic use case

**What about pipelines (OCR → Classifier → Storage)?** A pipeline is NOT a module. Pipelines are orchestrated by the application or by agent skills. Modules are the individual steps. If you find yourself building a module that mainly calls other modules, you're building orchestration — that belongs in the application layer or as a skill, not as a module.

**Anti-patterns to avoid:**
- **God module**: a module that implements an entire business flow (e.g., "document-processing" that does upload, OCR, classification, storage). Too big, not reusable.
- **Nano module**: a module that wraps a single utility function without own state or heavy dependencies. The container overhead is not justified — use a builtin tool instead.
- **Facade module**: a module that only calls other modules without adding its own logic. That's orchestration, not a module.

---

## 2. Five Approaches to Module Design

### Approach A: Built-in MCP Servers

**Core idea**: Each module IS a standalone MCP server deployed as a Docker container. Applications built by Druppie make standard MCP tool calls (JSON-RPC over HTTP) to use modules. This is the natural extension of how Druppie already works.

#### How It Works

Each module follows the existing MCP server pattern with `module.py` (business logic) + `server.py` (FastMCP HTTP wrapper):

```
druppie/mcp-servers/module-ocr/
  ├── module.py           # Pure OCR business logic
  ├── server.py           # FastMCP tool definitions
  ├── Dockerfile
  └── requirements.txt
```

Registration in `mcp_config.yaml`:

```yaml
mcps:
  ocr:
    url: ${MCP_OCR_URL:-http://module-ocr:9010}
    description: "OCR text extraction for images and documents"
    inject:
      session_id:
        from: session.id
        hidden: true
      user_id:
        from: session.user_id
        hidden: true
    tools:
      - name: extract_text
        description: "Extract text from an image or PDF"
        requires_approval: false
        parameters:
          type: object
          properties:
            image_url:
              type: string
              description: "URL or path to the image"
            language:
              type: string
              description: "OCR language (default: auto-detect)"
          required: [image_url]
```

#### How Druppie-Built Apps Use It

The generated application makes HTTP calls to the MCP server:

```python
# In the Druppie-built application
async def extract_text_from_invoice(image_path: str) -> dict:
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "http://module-ocr:9010/mcp",
            json={
                "jsonrpc": "2.0",
                "method": "tools/call",
                "params": {
                    "name": "extract_text",
                    "arguments": {"image_url": image_path, "language": "nl"}
                },
                "id": 1
            },
            headers={"Authorization": f"Bearer {obo_token}"}
        )
        return response.json()["result"]
```

#### Pros

| Advantage | Why it matters |
|-----------|---------------|
| **Protocol alignment** | Druppie already uses MCP for everything — no new protocol |
| **Full isolation** | Each module runs in its own container with own dependencies |
| **Existing infrastructure** | `MCPHttp`, `ToolExecutor`, injection rules, approval system work unchanged |
| **Hot-pluggable** | Adding a module = adding a container + YAML config block |
| **Language agnostic** | Modules can be written in any language that speaks JSON-RPC |
| **AI-native** | LLMs naturally understand tool calls |

#### Cons

| Disadvantage | Impact |
|-------------|--------|
| **Network overhead** | Every module call is an HTTP round-trip (~1-10ms) |
| **No shared state** | Data must be passed via arguments or shared storage |
| **Schema rigidity** | MCP tool schemas are flat JSON; no native streaming or binary support |
| **Resource cost** | Each module is a running container consuming memory when idle |
| **No built-in discovery** | Applications need to know which MCP servers exist at deploy time |

#### Fitness for Test Cases

- **OCR Module**: Natural fit. Heavy processing justifies container isolation. GPU can be attached to the OCR container specifically.
- **Document Classifier**: Good fit. ML model stays loaded in the container, shared across requests.

---

### Approach B: Library / Import Pattern

**Core idea**: Modules are importable Python packages (like Django apps or Flask blueprints) that the AI agent drops into generated applications. Each package contains models, routes, business logic, and configuration.

#### How It Works

```
druppie-modules/
  ├── druppie_ocr/
  │   ├── __init__.py
  │   ├── module.py        # Module registration (like Django apps.py)
  │   ├── routes.py        # FastAPI routes (auto-mounted)
  │   ├── models.py        # SQLAlchemy models (auto-created)
  │   ├── services.py      # Business logic
  │   └── config.py        # Configuration schema
  └── druppie_classifier/
      └── ...
```

Module registration follows the Django pattern:

```python
# druppie_ocr/module.py
class OcrModule(DruppieModule):
    name = "ocr"
    version = "1.0.0"
    description = "OCR text extraction from images and documents"

    config_schema = {
        "ocr_engine": {"type": "string", "default": "tesseract"},
        "default_language": {"type": "string", "default": "auto"},
    }

    dependencies = ["Pillow>=10.0", "pytesseract>=0.3"]
```

#### How Druppie-Built Apps Use It

```python
# In the generated application
from druppie_ocr import OcrModule
from druppie_classifier import ClassifierModule

app = FastAPI()

ocr = OcrModule(config={"ocr_engine": "tesseract", "default_language": "nl"})
classifier = ClassifierModule(config={"model": "bert-base-dutch"})

app.include_router(ocr.routes())
app.include_router(classifier.routes())
```

#### Pros

| Advantage | Why it matters |
|-----------|---------------|
| **Zero network overhead** | In-process function calls, no HTTP latency |
| **Shared database** | Modules use the same DB, enabling cross-module transactions |
| **Type safety** | IDE autocompletion, compile-time checks |
| **Familiar pattern** | Every developer knows Django apps / Flask blueprints |
| **Simple deployment** | Single container with all modules included |
| **Easy testing** | Import and test directly, no HTTP mocking |

#### Cons

| Disadvantage | Impact |
|-------------|--------|
| **Language lock-in** | Modules must match the application's language (Python only) |
| **Dependency conflicts** | Module A needs `numpy 1.24`, Module B needs `numpy 1.26` — breaks |
| **No isolation** | Crashing module crashes the entire application |
| **Tight coupling** | Updates require redeployment of every application using the module |
| **Heavy applications** | Each app bundles all module code, increasing container size |
| **Agent complexity** | AI must understand how to properly import, configure, and wire modules |

#### Fitness for Test Cases

- **OCR Module**: Poor fit. OCR requires heavy dependencies (Tesseract, Pillow, ML models) that bloat every application container.
- **Document Classifier**: Moderate fit. Lighter dependencies, but still couples ML model lifecycle to the application.

---

### Approach C: SDK + MCP Hybrid

**Core idea**: A thin client SDK (`druppie-sdk`) that Druppie always generates into applications, which handles OBO auth, retries, and calls to remote MCP module servers. The SDK is the "library" but all actual logic is remote. This mirrors how Stripe SDK, AWS SDK, and Twilio SDK work.

#### How It Works

The SDK is a lightweight package (~50KB) with no heavy dependencies:

```python
# druppie_sdk/client.py — The thin SDK
class DruppieClient:
    """Firebase pattern: auto-discovers config from environment.
    Supabase pattern: unified access to all modules.
    Stripe pattern: thin client, remote logic, idempotency."""

    def __init__(
        self,
        gateway_url: str | None = None,      # Auto from DRUPPIE_GATEWAY_URL
        session_token: str | None = None,     # Auto from DRUPPIE_SESSION_TOKEN
    ):
        self.gateway_url = gateway_url or os.environ.get(
            "DRUPPIE_GATEWAY_URL", "http://druppie-gateway:8000"
        )
        self.session_token = session_token or os.environ.get("DRUPPIE_SESSION_TOKEN")
        self.modules = ModuleClient(self)
        self.costs = CostTracker()

    @property
    def ocr(self) -> OCRModule:
        return OCRModule(self)

    @property
    def classifier(self) -> ClassifierModule:
        return ClassifierModule(self)
```

The SDK provides typed convenience methods per module:

```python
# In a Druppie-generated application
from druppie_sdk import DruppieClient

druppie = DruppieClient()  # Zero-config (reads env vars)

# Typed, ergonomic API
text = await druppie.ocr.extract("invoice.png", language="nl")
category = await druppie.classifier.classify(text, ["invoice", "receipt", "contract"])

# Check costs
print(druppie.costs.summary())
# {"total_cents": 1.50, "by_module": {"ocr": {"calls": 1, "cost_cents": 1.0}, ...}}
```

Behind the scenes, the SDK:
1. Handles OBO token exchange with Keycloak
2. Makes JSON-RPC calls to MCP module servers
3. Retries with exponential backoff + jitter (AWS pattern)
4. Supports idempotency keys (Stripe pattern)
5. Tracks costs per module call

#### Relationship to Existing Code

The SDK's `ModuleClient.call()` is the user-facing equivalent of the internal `MCPHttp.call()` at `druppie/execution/mcp_http.py`. The difference: `MCPHttp` is called by the orchestrator during agent execution; `DruppieClient` is called by generated applications at runtime.

#### Pros

| Advantage | Why it matters |
|-----------|---------------|
| **Best of both worlds** | Library ergonomics with remote execution |
| **Zero-config** | Firebase pattern: reads `DRUPPIE_*` env vars automatically |
| **Thin client** | No heavy deps — SDK is ~50KB, no ML models, no Tesseract |
| **Consistent across apps** | Every Druppie-generated app uses the same SDK |
| **Built-in governance** | Cost tracking, auth, retries are handled once in the SDK |
| **Easy for agents** | AI just generates `from druppie_sdk import DruppieClient` + simple calls |
| **Module isolation** | Actual processing stays in isolated MCP containers |

#### Cons

| Disadvantage | Impact |
|-------------|--------|
| **SDK maintenance** | Must be versioned and kept in sync with module API changes |
| **Extra abstraction** | Another layer between app code and modules |
| **Python/JS only** | SDK must be built per language (but most Druppie apps are Python) |
| **Network dependency** | Apps need connectivity to the gateway at runtime |

#### Fitness for Test Cases

- **OCR Module**: Excellent. App gets `druppie.ocr.extract()` — clean API, zero OCR dependencies in the app container.
- **Document Classifier**: Excellent. `druppie.classifier.classify(text, categories)` — one line of code.

---

### Approach D: Template-Based Code Generation

**Core idea**: Instead of runtime modules, the AI agent holds templates/snippets for common integration patterns. When building an app that needs OCR, the agent generates the full integration code from a template — producing standalone code that calls MCP modules correctly.

#### How It Works

Templates are YAML files with Jinja2 content:

```yaml
# druppie/modules/templates/ocr-python.yaml
id: ocr-integration
module_id: ocr
description: "OCR text extraction using Druppie OCR module"
language: python

variables:
  service_name: "ocr_service"
  default_language: "en"

dependencies:
  druppie-sdk: ">=0.1.0"

required_mcp_tools:
  - "ocr:extract_text"

files:
  "services/{{ service_name }}.py": |
    """OCR Service — generated by Druppie template: ocr-integration"""
    from druppie_sdk import DruppieClient

    class OCRService:
        def __init__(self, druppie: DruppieClient):
            self.client = druppie

        async def extract_text(self, image_path: str, language: str = "{{ default_language }}"):
            result = await self.client.modules.call("ocr", "extract_text", {
                "image_path": image_path, "language": language,
            })
            if not result.get("success"):
                raise RuntimeError(f"OCR failed: {result.get('error')}")
            return {
                "text": result["extracted_text"],
                "confidence": result.get("confidence", 0.0),
            }

  "tests/test_{{ service_name }}.py": |
    """Tests for OCR service — generated by Druppie template."""
    import pytest
    from unittest.mock import AsyncMock
    from services.{{ service_name }} import OCRService

    @pytest.fixture
    def mock_client():
        client = AsyncMock()
        client.modules.call.return_value = {
            "success": True, "extracted_text": "Hello", "confidence": 0.95,
        }
        return client

    @pytest.mark.asyncio
    async def test_extract_text(mock_client):
        service = OCRService(mock_client)
        result = await service.extract_text("test.png")
        assert result["text"] == "Hello"
```

A `TemplateRegistry` discovers templates at planning time:

```python
class TemplateRegistry:
    def find_for_task(self, task_description: str, language: str) -> list[ModuleTemplate]:
        """AI agent queries this during planning to find relevant templates."""
        ...

    def render(self, template_id: str, variables: dict) -> dict[str, str]:
        """Render template into {file_path: content} dict."""
        ...
```

#### How It Integrates with Existing Druppie

This extends the `execute_coding_task` tool. Currently, the sandbox agent receives a free-form prompt. With templates, the planner includes structured template content in the prompt:

```
"IMPLEMENTATION TASK: Build an invoice processor.

AVAILABLE TEMPLATES (use these as starting points):
- ocr-integration: OCR text extraction integration
  Files: services/ocr_service.py, tests/test_ocr_service.py
  Dependencies: druppie-sdk>=0.1.0

Generate code based on these templates."
```

#### Pros

| Advantage | Why it matters |
|-----------|---------------|
| **Consistent output** | Every app gets the same proven integration pattern |
| **Test included** | Templates generate tests alongside implementation |
| **Reduces hallucination** | Agent follows a template instead of inventing integration code |
| **Versionable** | Templates are YAML in git — track changes, review diffs |
| **Composable** | Multiple templates can be combined for complex apps |

#### Cons

| Disadvantage | Impact |
|-------------|--------|
| **Template maintenance** | Templates must be updated when module APIs change |
| **Less flexible** | Templates cover predicted patterns; novel integrations require custom code |
| **Build-time only** | No runtime benefit — template is consumed during code generation |
| **Duplication** | Generated code may diverge from template over time as developers modify it |

#### Fitness for Test Cases

- **OCR Module**: Good. Template generates a clean `OCRService` wrapper with tests.
- **Document Classifier**: Good. Template generates `ClassifierService` with category configuration.

---

### Approach E: Composable MCP with Shared DB + API Gateway

**Core idea**: Modules are MCP servers that share Druppie's PostgreSQL database (with schema isolation) and sit behind a shared API gateway. The gateway handles authentication, rate limiting, cost tracking, and routing — providing a single entry point for all module access.

#### How It Works

**Schema Isolation**: Each module gets its own PostgreSQL schema:

```sql
-- Module's own tables (full read/write)
CREATE SCHEMA module_ocr;

CREATE TABLE module_ocr.extraction_jobs (
    id UUID PRIMARY KEY,
    session_id UUID NOT NULL,     -- References public.sessions
    image_path VARCHAR NOT NULL,
    extracted_text TEXT,
    confidence FLOAT,
    cost_cents FLOAT DEFAULT 0.0,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Module can READ shared Druppie tables
GRANT SELECT ON public.sessions TO druppie_module_ocr;
GRANT SELECT ON public.projects TO druppie_module_ocr;
GRANT SELECT ON public.users TO druppie_module_ocr;
```

**API Gateway**: A single gateway service routes all module traffic:

```
Applications  ──>  API Gateway (port 9050)  ──>  Module MCP Servers
                   ├── Auth (OBO validation)      ├── module-ocr:9010
                   ├── Rate limiting               ├── module-classifier:9011
                   ├── Cost tracking               └── module-storage:9012
                   └── Circuit breaking
```

Applications call one URL:

```python
# Generated application code
from druppie_sdk import DruppieClient

druppie = DruppieClient()  # Connects to gateway

# Gateway routes to the right module, handles auth, tracks costs
text = await druppie.ocr.extract("invoice.png")
```

**Docker Compose for a module with schema isolation:**

```yaml
services:
  module-ocr:
    build: ./modules/ocr
    environment:
      MODULE_DB_URL: postgresql://druppie_module_ocr:${OCR_DB_PASSWORD}@druppie-db/druppie
      MODULE_SCHEMA: module_ocr
    networks:
      - druppie-new-network
    labels:
      druppie.module: "ocr"
      druppie.mcp.port: "9010"
```

#### Event-Driven Communication (Optional Enhancement)

Modules can communicate via events using PostgreSQL LISTEN/NOTIFY:

```python
# OCR module publishes after extraction:
await event_bus.publish(ModuleEvent(
    event_type="ocr.text_extracted",
    module_id="ocr",
    session_id=session_id,
    payload={"extracted_text": text, "confidence": 0.95},
))

# Classifier subscribes and auto-classifies:
event_bus.subscribe("ocr.text_extracted", handle_text_extracted)

async def handle_text_extracted(event: ModuleEvent):
    text = event.payload["extracted_text"]
    category = await classify(text, ["invoice", "receipt", "contract"])
    await event_bus.publish(ModuleEvent(
        event_type="classifier.document_classified",
        module_id="classifier",
        session_id=event.session_id,
        payload={"category": category, "confidence": 0.87},
    ))
```

#### Pros

| Advantage | Why it matters |
|-----------|---------------|
| **Centralized governance** | Single gateway for auth, rate limiting, cost tracking, observability |
| **DB access with isolation** | Modules can read Druppie core data (sessions, users) while keeping own tables isolated |
| **Simple client code** | One gateway URL — apps never need to know individual module URLs |
| **Cross-module pipelines** | Event bus enables OCR → Classifier → Storage chains |
| **Module pooling** | Multiple applications share the same module instances |
| **Full audit trail** | Events table records every inter-module interaction |

#### Cons

| Disadvantage | Impact |
|-------------|--------|
| **Gateway = single point of failure** | Needs HA deployment for production |
| **Additional latency** | Extra network hop through gateway (~1-5ms) |
| **Schema management** | PostgreSQL role/grant management adds operational complexity |
| **Configuration surface** | Gateway routing, schema grants, event subscriptions to maintain |

#### Fitness for Test Cases

- **OCR Module**: Excellent. Schema isolation stores extraction results. Gateway tracks per-user OCR costs. Event bus enables OCR → Classifier pipeline.
- **Document Classifier**: Excellent. Reads from public.sessions for context. Writes classification results to module_classifier schema. Subscribes to OCR events for auto-classification.

---

## 3. Comparative Analysis

### How Each Approach Handles the Full Lifecycle

| Aspect | A: MCP Server | B: Library | C: SDK+MCP | D: Templates | E: Composable+Gateway |
|--------|--------------|-----------|------------|-------------|---------------------|
| **Module runs** | Own container | In-app process | Own container | N/A (build-time) | Own container + gateway |
| **App integration** | Raw HTTP calls | Python import | SDK method call | Generated code | SDK via gateway |
| **Auth model** | Token in header | In-process (trusted) | OBO via SDK | Generated auth code | OBO via gateway |
| **Cost tracking** | ToolExecutor | In-process middleware | SDK CostTracker | Generated hooks | Gateway middleware |
| **DB access** | Separate DB | Shared DB | Separate DB | App's own DB | Shared DB (schema isolation) |
| **Discovery** | mcp_config.yaml | requirements.txt | SDK auto-discovery | Template registry | Gateway config |
| **Agent effort** | Write HTTP calls | Wire imports/config | `import druppie_sdk` | Use templates | `import druppie_sdk` |
| **Isolation** | Container | None | Container | N/A | Container + schema |

### Complexity for the AI Agent to Generate Integration Code

| Approach | What the agent generates | Lines of code | Error-prone? |
|----------|------------------------|---------------|-------------|
| A: MCP Server | Raw JSON-RPC HTTP calls | ~20 per integration | Medium (protocol details) |
| B: Library | Import + config + wiring | ~15 per integration | High (dependency management) |
| C: SDK+MCP | `druppie.ocr.extract()` | ~3 per integration | **Low** |
| D: Templates | Render template, adjust | ~5 per integration | Low (but rigid) |
| E: Composable+Gateway | `druppie.ocr.extract()` | ~3 per integration | **Low** |

### Operational Cost

| Approach | Containers per module | New infra to build | Config surface |
|----------|----------------------|-------------------|----------------|
| A: MCP Server | 1 | None (existing infra) | mcp_config.yaml entry |
| B: Library | 0 (bundled in app) | SDK framework | requirements.txt |
| C: SDK+MCP | 1 | SDK package | SDK config + mcp_config |
| D: Templates | 0 | Template registry | Template YAML files |
| E: Composable+Gateway | 1 + gateway | Gateway service, schema manager | Gateway + DB grants |

---

## 4. Test Cases

### OCR Module Through Each Approach

**Input**: Image file path (PDF, JPG, PNG)
**Output**: `{ "text": "...", "confidence": 0.95, "language": "nl" }`

| Approach | How the app calls OCR | Where OCR logic runs | Dependencies in app container |
|----------|----------------------|---------------------|------------------------------|
| A | `POST http://module-ocr:9010/mcp` | OCR container (Tesseract + GPU) | `httpx` only |
| B | `from druppie_ocr import extract` | App container (shared process) | Tesseract, Pillow, ML models (~2GB) |
| C | `await druppie.ocr.extract("img.png")` | OCR container | `druppie-sdk` (~50KB) |
| D | Generated `OCRService` class | OCR container (via SDK) | `druppie-sdk` (~50KB) |
| E | `await druppie.ocr.extract("img.png")` | OCR container (via gateway) | `druppie-sdk` (~50KB) |

**Winner for OCR**: Approaches C/E — cleanest API, minimal app dependencies, full container isolation for heavy OCR processing.

### Document Classifier Through Each Approach

**Input**: Document text + category list
**Output**: `{ "category": "vergunning", "confidence": 0.87 }`

| Approach | How the app classifies | Where ML inference runs | Cost tracking |
|----------|----------------------|------------------------|---------------|
| A | JSON-RPC tool call | Classifier container | Via ToolExecutor |
| B | `classifier.classify(text, cats)` | App process (shared) | In-process middleware |
| C | `await druppie.classifier.classify(...)` | Classifier container | SDK CostTracker |
| D | Generated `ClassifierService.classify()` | Classifier container (via SDK) | Generated hooks |
| E | `await druppie.classifier.classify(...)` | Classifier container (via gateway) | Gateway middleware |

**Winner for Classifier**: Approaches C/E — same reasoning. The classifier model stays loaded in a dedicated container, shared across all applications.

---

## 5. Authentication: OBO Token Exchange

Regardless of which approach is chosen, applications need to call modules **on behalf of users**. Keycloak 26.2+ supports RFC 8693 Standard Token Exchange natively.

### The Flow

```
User (browser)
  │ Keycloak JWT (user_token)
  ▼
Druppie-Built Application
  │ POST /realms/druppie/protocol/openid-connect/token
  │   grant_type=urn:ietf:params:oauth:grant-type:token-exchange
  │   subject_token={user_token}
  │   audience=druppie-modules
  ▼
Keycloak
  │ Returns: module_token (audience=druppie-modules, sub=original_user)
  ▼
Druppie-Built Application
  │ Authorization: Bearer {module_token}
  ▼
Module MCP Server (or Gateway)
  │ Validates token, extracts user identity
  │ Records usage under user's account
  ▼
Response with results
```

### SDK Handles This Automatically

```python
# druppie_sdk/auth.py
class DruppieAuth:
    async def exchange_token(self, user_token: str) -> str:
        """Exchange user token for module-scoped OBO token."""
        response = await self._http.post(
            self.token_endpoint,
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
                "subject_token": user_token,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "audience": "druppie-modules",
            },
        )
        data = response.json()
        self._token = data["access_token"]
        self._token_expiry = time.time() + data.get("expires_in", 300) - 30
        return self._token

    async def get_token(self, user_token: str) -> str:
        """Get valid token, auto-refreshing if expired."""
        if self._token and time.time() < self._token_expiry:
            return self._token
        return await self.exchange_token(user_token)
```

### What This Enables

- **Per-user cost attribution**: Module knows which user triggered each call
- **Scope restriction**: OBO tokens can have reduced scopes (e.g., `ocr:read` only)
- **Tenant isolation**: Keycloak Organizations feature supports multi-org setups
- **Audit trail**: Token exchange chain is recorded in Keycloak

---

## 6. Governance & Cost Tracking

### Where Cost Tracking Happens Per Approach

| Approach | Cost tracking point | How it works |
|----------|-------------------|-------------|
| A: MCP Server | `ToolExecutor` | Every tool call is a `ToolCall` record with timing + cost metadata |
| B: Library | In-process middleware | Middleware wraps each module call |
| C: SDK+MCP | SDK `CostTracker` | SDK records cost from each response |
| E: Gateway | Gateway middleware | All traffic flows through gateway — single metering point |

### Cost Tracking with DB Access (Approach E)

With shared DB access, the cost-tracking module can directly write usage records:

```sql
-- module_billing schema
CREATE TABLE module_billing.usage_records (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL,              -- From OBO token
    module_id VARCHAR(100) NOT NULL,    -- Which module was called
    tool_name VARCHAR(100) NOT NULL,    -- Which tool
    cost_cents FLOAT NOT NULL,          -- Computed cost
    session_id UUID,                    -- References public.sessions
    project_id UUID,                    -- References public.projects
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Dashboard query: cost per user per month
SELECT user_id, module_id,
       SUM(cost_cents) as total_cents,
       COUNT(*) as call_count
FROM module_billing.usage_records
WHERE created_at >= date_trunc('month', NOW())
GROUP BY user_id, module_id;
```

---

## 7. Agent Roles in Module Development

### Which agents are involved when adding a new module?

| Agent Role | Involvement | What they do |
|-----------|-------------|-------------|
| **Business Analyst (BA)** | Required | Defines module requirements, acceptance criteria, use cases |
| **Architect (AR)** | Required | Designs module contract (input/output schema), validates against convention |
| **Developer (DEV)** | Required | Implements module logic, MCP server, tests |
| **Reviewer** | Required | Reviews module code against convention, security, performance |
| **Planner** | Optional | Orchestrates multi-agent workflow if module is complex |
| **Tester** | Required | Validates module against contract, integration tests |
| **Deployer** | Required | Deploys module container, registers in configuration |

### Module Acceptance: Who Decides?

Not everything should become a module. Before development starts, a module proposal must pass these criteria:

| Criterion | Question |
|-----------|----------|
| **Reuse** | Will at least 2 different applications use this capability? |
| **Genericity** | Is it domain-independent, or tied to one specific client/use case? |
| **Independence** | Can it function as a standalone service, or does it only make sense inside a larger flow? |
| **Ownership** | Is there a team or person committed to maintaining it long-term? |
| **No overlap** | Does a similar module already exist? Could this be a new tool on an existing module instead? |

The **Architect (AR)** is responsible for evaluating scope and overlap. Module proposals that pass these criteria proceed to development. Proposals that don't are either scoped differently or implemented as application-specific services instead.

### Agents as Primary Consumers

Modules are not just infrastructure for developers — **agents are the first consumers**. The Architect agent needs to discover which modules exist and understand how to use them without manual system prompt updates. This means:

- `MODULE.yaml` must contain enough structured metadata for an agent to decide "this module is relevant for my task" (see `agent_metadata` in the specification)
- New modules should be **automatically discoverable** by agents through the registry, not through manual YAML edits to agent definitions
- Module descriptions, use cases, and examples must be written with LLM comprehension in mind, not just human readability

### Module Development Workflow

```
1. BA defines requirements  → MODULE_SPEC.md
2. AR evaluates fit         → Check acceptance criteria, no overlap
3. AR designs contract      → tools.yaml (input/output schema)
4. DEV implements           → module.py + server.py + tests
5. Reviewer validates       → Code review against module convention
6. Tester runs suite        → Contract tests + integration tests
7. Deployer deploys         → Docker container + mcp_config.yaml update (+ registry)
8. Module is discoverable   → Available to all agents and applications (via registry)
```

---

## 8. Impact on Current Environment

### What Changes When a Module Is Added

| Component | Impact | Level |
|-----------|--------|-------|
| `docker-compose.yaml` | New service block for module container | Low — additive only |
| `mcp_config.yaml` | New MCP entry with tools, injection rules | Low — additive only |
| Agent YAML definitions | Add module tools to relevant agents' tool lists | Low — additive |
| PostgreSQL | New schema (if Approach E) + grants | Low — no existing table changes |
| `druppie-sdk` | New typed module accessor (if adding convenience methods) | Low — backwards compatible |
| Template registry | New template files (if Approach D) | Low — additive |
| API Gateway | New routing rule (if Approach E) | Low — additive |
| CI/CD | New Docker build + push for module image | Medium — pipeline addition |
| Monitoring | New container to monitor, new metrics | Low — additive |

### What Does NOT Change

- Existing MCP servers (coding, docker, web) — unchanged
- Existing agent definitions — unchanged (unless agent needs new module tools)
- Frontend — unchanged (modules are backend-only)
- Database schema for core tables — unchanged
- Authentication flow — unchanged (OBO extends, doesn't modify)

---

## 9. Recommendation

### The Layered Approach: C with direct MCP access (without shared DB, without gateway proxy)

Based on the analysis, the strongest approach for Druppie is **Approach C (SDK + MCP Hybrid)** enhanced with templates from Approach D. We reject Approach E's shared database (each module owns its own storage) and its gateway proxy (apps connect directly to modules via the SDK as an MCP client).

```
┌─────────────────────────────────────────────────────────┐
│  Layer 2: Templates (build-time)                        │
│  AI agent uses templates to generate correct SDK calls  │
├─────────────────────────────────────────────────────────┤
│  Layer 1: Druppie SDK (runtime MCP client)              │
│  druppie-sdk package in every generated application     │
│  Connects directly to module MCP servers                │
│  Handles: auth, retries, usage reporting, typed methods │
├─────────────────────────────────────────────────────────┤
│  Layer 0: MCP Module Servers (execution)                │
│  Each module = FastMCP server + own database (or none)  │
│  Reports usage via MCP response _meta                   │
│  Validates Keycloak tokens for auth                     │
└─────────────────────────────────────────────────────────┘

Supporting infrastructure (on Druppie backend, not in the call path):
  - Usage recording API (POST /api/usage — called by SDK after each module call)
  - App access control API (GET /api/applications/{id}/users/{id}/roles)
  - Module registry API (GET /api/modules — for discovery)
```

### Why NOT Shared DB (Approach E's Schema Isolation)

The shared database with schema isolation from Approach E was rejected because:

- **Hidden coupling**: Modules that `SELECT FROM public.sessions` break when Druppie renames a column
- **Not portable**: Can't develop, test, or run a module without Druppie's full schema
- **Reset fragility**: Druppie's "reset DB" workflow can break modules reading `public.*`
- **Not self-contained**: Contradicts the core module principle of independence

Instead, modules receive Druppie context (user_id, project_id, app_id) through **standard MCP tool arguments**. Cost tracking is recorded by the caller (core or SDK), not the module.

### Why NOT a Gateway Proxy

A separate gateway between apps and modules was rejected because:

- **Extra hop**: Adds latency for every module call
- **Single point of failure**: Gateway down = all module calls fail
- **Unnecessary**: Auth is handled by Keycloak tokens (modules validate JWTs themselves), usage is reported by the SDK to the backend asynchronously

### Why This Combination

| Requirement | How it's met |
|------------|-------------|
| **Generic** | All MCP servers use FastMCP (official protocol); SDK is an MCP client |
| **Addable to core** | New module = new container + YAML config (additive only) |
| **Usable by Druppie** | AI agent generates `druppie_sdk` calls using templates |
| **Governed** | Modules report usage via `_meta`; SDK reports to backend; Keycloak handles auth |
| **Self-contained** | Each module owns its own database (or is stateless). Context comes via standard MCP arguments |
| **Easy for agents** | 3 lines of code per integration via SDK |

### What to Build First

1. **MCP upgrade** (Layer 0): Migrate existing MCP servers (coding, docker, etc.) to FastMCP
2. **Druppie SDK** (Layer 1): `DruppieClient` as MCP client + auth + usage reporting
3. **First module** (Layer 0): Pick OCR or Document Classifier as the pilot module
4. **Usage tracking** (backend): `module_usage` table + API routes
5. **App access control** (backend): `applications`, `application_roles`, `application_user_roles` tables + API routes
6. **Templates** (Layer 2): 2-3 integration templates for the pilot module

---

## 10. Sources

### MCP Protocol & Architecture
- [MCP Architecture Overview](https://modelcontextprotocol.io/docs/learn/architecture)
- [MCP Architecture Patterns for Multi-Agent AI Systems (IBM)](https://developer.ibm.com/articles/mcp-architecture-patterns-ai-systems/)
- [MCP Transports Specification](https://modelcontextprotocol.io/specification/2025-06-18/basic/transports)
- [MCP Streamable HTTP](https://thenewstack.io/how-mcp-uses-streamable-http-for-real-time-ai-tool-interaction/)
- [MCP Specification 2025-11-25](https://modelcontextprotocol.io/specification/2025-11-25)

### Authentication & Token Exchange
- [Standard Token Exchange in Keycloak 26.2](https://www.keycloak.org/2025/05/standard-token-exchange-kc-26-2)
- [Keycloak Token Exchange Documentation](https://www.keycloak.org/securing-apps/token-exchange)
- [Keycloak Organizations for Multi-Tenancy](https://www.keycloak.org/2024/06/announcement-keycloak-organizations)

### SDK Design Patterns
- [Stripe Integrations Core API Concepts](https://stripe.com/sessions/2025/stripe-integrations-deconstructed-core-api-concepts)
- [Stripe SDKs Documentation](https://docs.stripe.com/sdks)
- [AWS SDK Retry Behavior](https://docs.aws.amazon.com/sdkref/latest/guide/feature-retry-behavior.html)
- [Firebase Web Setup](https://firebase.google.com/docs/web/setup)
- [Supabase Client Libraries](https://supabase.com/docs/guides/api/rest/client-libs)

### Module & Plugin Patterns
- [Django Apps vs Flask Blueprints](https://blog.appseed.us/flask-blueprints-vs-django-apps/)
- [NestJS Modules](https://docs.nestjs.com/modules)
- [Grafana Plugin Lifecycle](https://grafana.com/developers/plugin-tools/key-concepts/plugin-lifecycle)
- [WordPress Activation/Deactivation Hooks](https://developer.wordpress.org/plugins/plugin-basics/activation-deactivation-hooks/)

### Database Patterns
- [PostgreSQL Schemas Documentation](https://www.postgresql.org/docs/current/ddl-schemas.html)
- [Crunchy Data: PostgreSQL Multi-Tenancy](https://www.crunchydata.com/blog/designing-your-postgres-database-for-multi-tenancy)
- [AWS: Multi-tenant PostgreSQL RLS](https://aws.amazon.com/blogs/database/multi-tenant-data-isolation-with-postgresql-row-level-security/)

### Event-Driven Architecture
- [Microservices.io: Event Sourcing Pattern](https://microservices.io/patterns/data/event-sourcing.html)
- [Microsoft: CQRS Pattern](https://learn.microsoft.com/en-us/azure/architecture/patterns/cqrs)
- [Confluent: Event-Driven Architecture](https://www.confluent.io/learn/event-driven-architecture/)

### Code Generation
- [Cookiecutter vs Yeoman](https://www.cookiecutter.io/article-post/compare-cookiecutter-to-yeoman)
- [Copilot Workspace (GitHub Next)](https://githubnext.com/projects/copilot-workspace)
