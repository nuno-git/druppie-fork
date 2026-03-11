# Druppie Module Convention — Research & Decision Records

> **Status**: Reference / historical record
> **Date**: 2026-02-24 (initial brainstorm) to 2026-03-11 (iterative design)
> **Author**: Druppie team
> **User Story**: Als Druppie-teamlid wil ik een gestandaardiseerd format/contract voor core-modules, zodat uitbreidingen op een uniforme manier worden toegevoegd ongeacht wie ze bouwt.
> **Related**: `docs/module-specification.md` (technical contract), `docs/plans/2026-03-11-auth-governance-design.md` (auth & governance design)

This document captures the full design journey for Druppie's module convention: the original research exploring five architectural approaches, the comparative analysis and test cases that drove the recommendation, and all subsequent design decisions made during specification development. It is the "why" behind the decisions — the "what" lives in the specification.

---

## Table of Contents

### Part I — Foundational Research

1. [What Is a Module?](#1-what-is-a-module)
2. [Five Approaches to Module Design](#2-five-approaches-to-module-design)
3. [Comparative Analysis](#3-comparative-analysis)
4. [Test Cases](#4-test-cases)
5. [Authentication: OBO Token Exchange](#5-authentication-obo-token-exchange)
6. [Governance & Cost Tracking](#6-governance--cost-tracking)
7. [Agent Roles in Module Development](#7-agent-roles-in-module-development)
8. [Impact on Current Environment](#8-impact-on-current-environment)
9. [Recommendation: Layered C + D](#9-recommendation-layered-c--d)

### Part II — Design Decisions

10. [Versioning Strategy](#10-versioning-strategy)
11. [Database Ownership](#11-database-ownership)
12. [Gateway vs Direct Connection](#12-gateway-vs-direct-connection)
13. [Module Registry](#13-module-registry)
14. [Metadata & Source of Truth](#14-metadata--source-of-truth)
15. [Authentication & Token Strategy](#15-authentication--token-strategy)
16. [Argument Handling in tools.py vs module.py](#16-argument-handling-in-toolspy-vs-modulepy)
17. [Module Code Structure Strictness](#17-module-code-structure-strictness)
18. [SDK Location & Distribution](#18-sdk-location--distribution)
19. [Project Template Design](#19-project-template-design)
20. [MCP Server Categories](#20-mcp-server-categories)
21. [RBAC Location](#21-rbac-location)
22. [Usage Tracking & Cost Attribution](#22-usage-tracking--cost-attribution)
23. [Resource Metrics Discovery](#23-resource-metrics-discovery)
24. [Sunset & End-of-Life Policy](#24-sunset--end-of-life-policy)
25. [Decision Timeline](#25-decision-timeline)
26. [Sources](#26-sources)

---

# Part I — Foundational Research

The design started with a brainstorming phase (2026-02-24) that explored five fundamentally different module architectures, compared them with test cases, and arrived at the layered recommendation.

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

**What about pipelines (OCR -> Classifier -> Storage)?** A pipeline is NOT a module. Pipelines are orchestrated by the application or by agent skills. Modules are the individual steps. If you find yourself building a module that mainly calls other modules, you're building orchestration — that belongs in the application layer or as a skill, not as a module.

**Anti-patterns to avoid:**
- **God module**: a module that implements an entire business flow (e.g., "document-processing" that does upload, OCR, classification, storage). Too big, not reusable.
- **Nano module**: a module that wraps a single utility function without own state or heavy dependencies. The container overhead is not justified — use a builtin tool instead.
- **Facade module**: a module that only calls other modules without adding its own logic. That's orchestration, not a module.

---

## 2. Five Approaches to Module Design

### Approach A: Built-in MCP Servers

**Core idea**: Each module IS a standalone MCP server deployed as a Docker container. Applications built by Druppie make standard MCP tool calls (JSON-RPC over HTTP) to use modules. This is the natural extension of how Druppie already works.

**Decision verdict**: Strong foundation but raw HTTP calls are tedious for generated apps. Forms the base layer (Layer 0) of the chosen approach.

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

**Decision verdict**: **Rejected.** OCR module is a particularly poor fit — Tesseract, Pillow, and ML models (~2GB) would bloat every application container. Dependency conflicts between modules are inevitable at scale.

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

**Decision verdict**: **Chosen as Layer 1.** Provides the cleanest developer experience while keeping all heavy processing in isolated containers.

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

**Decision verdict**: Adopted as **Layer 2** (build-time guidance for the AI agent), but not as the primary mechanism. Templates complement the SDK, not replace it.

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

**Decision verdict**: **Rejected.** Both the shared DB and gateway proxy were rejected for specific reasons (see Sections 11 and 12). However, the concept of MCP types and the event-driven ideas influenced later design choices.

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
Applications  -->  API Gateway (port 9050)  -->  Module MCP Servers
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
| **Cross-module pipelines** | Event bus enables OCR -> Classifier -> Storage chains |
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

- **OCR Module**: Excellent. Schema isolation stores extraction results. Gateway tracks per-user OCR costs. Event bus enables OCR -> Classifier pipeline.
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
  | Keycloak JWT (user_token)
  v
Druppie-Built Application
  | POST /realms/druppie/protocol/openid-connect/token
  |   grant_type=urn:ietf:params:oauth:grant-type:token-exchange
  |   subject_token={user_token}
  |   audience=druppie-modules
  v
Keycloak
  | Returns: module_token (audience=druppie-modules, sub=original_user)
  v
Druppie-Built Application
  | Authorization: Bearer {module_token}
  v
Module MCP Server (or Gateway)
  | Validates token, extracts user identity
  | Records usage under user's account
  v
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
1. BA defines requirements  -> MODULE_SPEC.md
2. AR evaluates fit         -> Check acceptance criteria, no overlap
3. AR designs contract      -> tools.yaml (input/output schema)
4. DEV implements           -> module.py + server.py + tests
5. Reviewer validates       -> Code review against module convention
6. Tester runs suite        -> Contract tests + integration tests
7. Deployer deploys         -> Docker container + mcp_config.yaml update (+ registry)
8. Module is discoverable   -> Available to all agents and applications (via registry)
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

## 9. Recommendation: Layered C + D

### The Layered Approach: C with direct MCP access (without shared DB, without gateway proxy)

Based on the analysis, the strongest approach for Druppie is **Approach C (SDK + MCP Hybrid)** enhanced with templates from Approach D. We reject Approach E's shared database (each module owns its own storage) and its gateway proxy (apps connect directly to modules via the SDK as an MCP client).

```
+---------------------------------------------------------+
|  Layer 2: Templates (build-time)                        |
|  AI agent uses templates to generate correct SDK calls  |
+---------------------------------------------------------+
|  Layer 1: Druppie SDK (runtime MCP client)              |
|  druppie-sdk package in every generated application     |
|  Connects directly to module MCP servers                |
|  Handles: auth, retries, usage reporting, typed methods |
+---------------------------------------------------------+
|  Layer 0: MCP Module Servers (execution)                |
|  Each module = FastMCP server + own database (or none)  |
|  Reports usage via MCP response _meta                   |
|  Validates Keycloak tokens for auth                     |
+---------------------------------------------------------+

Supporting infrastructure (on Druppie backend, not in the call path):
  - Usage recording API (POST /api/usage — called by SDK after each module call)
  - App access control API (GET /api/applications/{id}/users/{id}/roles)
  - Module registry API (GET /api/modules — for discovery)
```

**Key insight**: The decision wasn't just "pick one approach" but rather "combine the best parts of multiple approaches into layers." The initial instinct was to evaluate them as mutually exclusive, but the layered combination proved stronger than any single approach.

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

# Part II — Design Decisions

The following sections document specific design decisions made during the specification phase (2026-03-10 to 2026-03-11). Each section records the alternatives considered and the reasoning behind the final choice.

---

## 10. Versioning Strategy

### The Problem

The initial module specification defined SemVer rules and a Stripe-inspired transformer system for version compatibility, but never specified:
- How versioned code is organized in the filesystem
- What happens when you bump a major version
- How the database evolves across versions
- How routing selects the right version

### Approaches Considered

#### A: Stripe-Style Transformers (Initially Chosen, Then Rejected)

Inspired by [Stripe's API versioning](https://stripe.com/blog/api-versioning), this approach uses a chain of transformers to convert between API versions:

```
Client (v1) -> Transformer v2->v1 -> Transformer v3->v2 -> Current Code (v3)
```

| Strengths | Weaknesses |
|-----------|------------|
| Single codebase (latest version only) | Transformer chain grows linearly with versions |
| Tested at scale (Stripe uses this) | Each transformer is a maintenance burden |
| Consistent behavior guarantees | Debugging through transformer chains is hard |
| Compact codebase | Complex — requires understanding entire chain |

**Why rejected**: Stripe has a large team maintaining transformers. For Druppie modules (small team, AI-built), the complexity of maintaining a transformer chain per module is disproportionate. Each transformer is essentially a translation layer that must be tested and maintained forever.

#### B: Independent Version Directories (Chosen)

Each major version gets its own directory (`v1/`, `v2/`) with fully independent code:

```
module-ocr/
├── server.py      # Routes /v1/mcp -> v1/, /v2/mcp -> v2/
├── v1/
│   ├── module.py  # v1 business logic (complete, independent)
│   └── tools.py   # v1 tool definitions
└── v2/
    ├── module.py  # v2 business logic (complete, independent)
    └── tools.py   # v2 tool definitions
```

| Strengths | Weaknesses |
|-----------|------------|
| Simple — each version is self-contained | Some code duplication between versions |
| No translation layers to maintain | Bug in shared logic must be fixed per version |
| Easy to reason about | More files overall |
| Each version can evolve independently | |
| Path-based routing (no headers) | |

**Why chosen**: Simplicity wins. Code duplication between versions is a minor cost compared to the complexity of maintaining transformers. When v2 diverges from v1 (which is the whole point of a major version), the duplication quickly becomes irrelevant because the code is actually different.

#### C: Version Headers (Rejected)

Route based on HTTP headers (`X-Module-Version: 1`) rather than path.

**Why rejected**: Path-based routing is simpler, more visible in logs, and works with any HTTP client without special header configuration. MCP protocol doesn't define version headers.

#### D: Single Codebase with Feature Flags (Rejected)

Use feature flags or if/else blocks to handle different version behaviors in a single codebase.

**Why rejected**: Leads to spaghetti code. Difficult to reason about which code path serves which version. Testing becomes combinatorial.

### SemVer Interpretation

Based on research from [Stripe](https://stripe.com/blog/api-versioning), [Google AIP-180](https://google.aip.dev/180), and [Zalando API guidelines](https://github.com/zalando/restful-api-guidelines):

| Change | Bump | Directory impact |
|--------|------|-----------------|
| Remove/rename tool, parameter, field | **MAJOR** | New `vN+1/` directory |
| Change field type or semantics | **MAJOR** | New `vN+1/` directory |
| Make optional param required | **MAJOR** | New `vN+1/` directory |
| New tool, new optional param (with default) | **MINOR** | Update in-place in `vN/` |
| Bug fix, performance improvement | **PATCH** | Update in-place in `vN/` |

---

## 11. Database Ownership

### Approaches Considered

#### A: Shared Druppie Database with Schema Isolation (Approach E's model, Rejected)

Each module gets its own PostgreSQL schema within Druppie's database:

```sql
CREATE SCHEMA module_ocr;
GRANT SELECT ON public.sessions TO druppie_module_ocr;
```

| Problem | Impact |
|---------|--------|
| Schema coupling | Module does `SELECT FROM public.sessions` -> Druppie renames a column -> module breaks |
| Not portable | Can't develop, test, or run a module without a copy of Druppie's full schema |
| Not self-contained | Contradicts the core module principle of independence |
| Reset fragility | Druppie's "reset DB" workflow (common in dev) breaks modules reading `public.*` |
| Permission complexity | PostgreSQL role/grant management adds operational overhead |

#### B: Module-Owned Storage (Chosen)

Each module manages its own data storage independently:
- **Stateful modules** get their own PostgreSQL container (`module-ocr-db`)
- **Stateless modules** don't need any database
- **Druppie context** comes through injected MCP arguments, not DB queries

**Why chosen**: Self-contained modules are the core principle. A module must be developable, testable, and runnable without any Druppie infrastructure except the MCP protocol.

### Database Rules for Multi-Version Modules

Since multiple major versions run simultaneously against the same module database:

1. **One database per module** (not per version)
2. **Additive-only changes** — add columns (with defaults), add tables, add indexes
3. **Never destructive** — no `DROP`, `RENAME`, `ALTER TYPE` while any version uses the affected object
4. **Every new column has a `DEFAULT`** — older version code can INSERT without specifying it
5. **No `SELECT *`** — explicit column selection so new columns don't break old versions

This was directly informed by the versioning decision: independent version directories sharing a database requires strict additive-only rules.

---

## 12. Gateway vs Direct Connection

### Gateway Proxy (Rejected)

A single gateway service between applications and modules:

```
Apps -> API Gateway (port 9050) -> Module MCP Servers
         ├── Auth validation
         ├── Rate limiting
         ├── Cost tracking
         └── Circuit breaking
```

| Problem | Impact |
|---------|--------|
| Extra hop | Adds 1-5ms latency per module call |
| Single point of failure | Gateway down = all module calls fail |
| Unnecessary | Auth: Keycloak JWTs (modules validate themselves). Usage: SDK reports async to backend |
| Operational overhead | Another service to deploy, monitor, scale |

### Direct MCP Connection via SDK (Chosen)

```
App (SDK = MCP client) ---- MCP protocol ----> Module (MCP server)
```

The SDK is an MCP client that connects directly to module servers. Auth, retries, and usage reporting are handled by the SDK, not a proxy.

**Key question that led to this decision**: *"Why not have apps make direct connection to the MCP? The SDK does this."*

**Answer**: There's no benefit to proxying through a gateway when:
- Auth is token-based (modules validate Keycloak JWTs themselves)
- Usage reporting is async (SDK POSTs to backend after each call)
- Rate limiting can be per-module (modules handle their own)
- Circuit breaking is in the SDK (retries with backoff)

---

## 13. Module Registry

### Database Registry (Initially Included, Then Removed)

The original module specification included a full registry with database tables:

```sql
CREATE TABLE modules (id, name, description, author, category, ...);
CREATE TABLE module_versions (module_id, version, ...);
CREATE TABLE module_tool_schemas (version_id, tool_name, input_schema, output_schema, ...);
CREATE TABLE application_module_bindings (app_id, module_id, version, ...);
```

### Why It Was Removed

The registry was duplicating what MCP already provides. The critical question was:

*"Why is this here? We can just use the MCP things directly, right? Why do we have to save it in the DB?"*

Analysis showed that every field in the registry tables was already available through the MCP protocol:
- Module name, description -> MCP `initialize` response (`serverInfo.name`)
- Tool schemas -> MCP `tools/list` response
- Version info -> `meta` field in `@mcp.tool()` decorator
- Agent guidance -> `FastMCP(instructions="...")`

### What Replaced It

- **Discovery**: `mcp_config.yaml` lists all modules + live MCP `initialize`/`tools/list` calls
- **Usage tracking**: Plain string fields (`module_id`, `module_version`) in `module_usage` table — no FK to registry tables
- **App bindings**: SDK config determines which versions an app uses — no DB binding table needed

**Follow-up question**: *"If removing it, how would we do module_usage?"*

**Answer**: `module_usage` uses plain strings for `module_id` and `module_version`, not foreign keys. The module's identity is established by its `MODULE.yaml` and MCP server info, not by a registry row.

### Cached Display Fields

For the discovery API (so the frontend doesn't need to call every module's MCP endpoint), a thin cache approach was adopted:
- On module registration/startup, Druppie caches `display_name`, `instructions`, `meta_json` from the MCP `initialize` response
- This is refreshed periodically, not treated as the source of truth

---

## 14. Metadata & Source of Truth

### Approaches Considered

#### A: MODULE.yaml as Complete Manifest

The original design had `MODULE.yaml` containing everything: module ID, name, description, author, license, category, tool schemas, agent metadata, infrastructure config, needs_database flag.

**Problem**: This created duplication with the FastMCP code. Tool schemas were defined in both `MODULE.yaml` and `@mcp.tool()` decorators. Description was in both `MODULE.yaml` and `FastMCP(name=...)`.

#### B: MODULE.yaml + Per-Version manifest.yaml (Intermediate Step)

Split into root `MODULE.yaml` (identity) + per-version `manifest.yaml` (tool schemas).

**Problem**: Still duplicated what the MCP protocol provides. `manifest.yaml` tool schemas must match the `@mcp.tool()` decorators exactly — any drift causes bugs.

#### C: MODULE.yaml (Minimal) + MCP as Source of Truth (Chosen)

```yaml
# MODULE.yaml — the ONLY YAML file in the module
id: ocr
latest_version: "2.0.0"
versions:
  - "1.0.0"
  - "2.0.0"
```

Three fields. Everything else comes from the MCP protocol:

| What | Where it's defined | How it's discovered |
|------|-------------------|-------------------|
| Server name | `FastMCP("OCR Module v1")` | MCP `initialize` -> `serverInfo.name` |
| Server version | `FastMCP(..., version="1.2.0")` | MCP `initialize` -> `serverInfo.version` |
| Agent guidance | `FastMCP(..., instructions="...")` | MCP `initialize` -> `instructions` |
| Tool schemas | `@mcp.tool(name=..., description=...)` | MCP `tools/list` |
| Resource metrics | `@mcp.tool(meta={...})` | MCP `tools/list` -> `meta` |

**Key insight from FastMCP documentation**: The `meta` field in `@mcp.tool()` can carry arbitrary metadata, including version info and resource metric definitions. This eliminated the need for a separate manifest file.

### Fields Removed from MODULE.yaml During Iteration

| Removed Field | Reason |
|---------------|--------|
| `name`, `description`, `author` | Available from MCP `initialize` (`serverInfo`) |
| `license` | Not relevant at runtime |
| `category`, `is_core` | Replaced by `type` in `mcp_config.yaml` |
| `needs_database` | Infrastructure detail — just define it in code |
| `infrastructure.port`, `infrastructure.db_schema` | Docker Compose handles this |
| `agent_metadata` (use_when, dont_use_when, examples) | Moved to `FastMCP(instructions="...")` |
| Per-version `manifest.yaml` | Tool schemas are in `@mcp.tool()` decorators |

---

## 15. Authentication & Token Strategy

### The Core Question

*"How do applications built by Druppie authenticate when calling modules? And how does this work in the sandbox where agents test the apps?"*

### Approaches Considered

#### A: Gateway-Mediated Auth (Rejected with Gateway)

Gateway validates tokens, modules trust the gateway. Rejected along with the gateway concept.

#### B: Module-Level Token Validation (Chosen)

Each module validates Keycloak JWTs directly:
- App user logs in via Keycloak -> gets JWT
- SDK includes JWT in MCP calls
- Module validates against Keycloak JWKS endpoint

#### Sandbox Security

**Problem**: Agents run in sandboxes that must not have long-lived credentials. The same pattern already used for GitHub and LLM proxies applies.

**Solution**: Short-lived OBO (On-Behalf-Of) tokens:
1. Before sandbox launch, Druppie core requests a short-lived OBO token from Keycloak (TTL: 15 minutes)
2. Token stored in credential store (existing infrastructure)
3. Injected into sandbox as `DRUPPIE_MODULE_TOKEN` env var
4. Carries original user's identity (`sub` = user_id) for usage attribution

**Design principle**: *"Token for identity, arguments for context."* The token proves who the user is. Standard arguments provide the calling context (session, project, app). These are separate concerns.

### OBO Token Exchange (Keycloak 26.2+)

```
User (browser) -> App -> Keycloak (token exchange) -> Module (validates JWT)
```

Uses RFC 8693 Standard Token Exchange, natively supported in Keycloak 26.2+. The exchanged token has:
- `audience=druppie-modules` (scoped to module access)
- `sub=original_user_id` (preserves user identity)
- Reduced scopes (e.g., `ocr:read` only)

---

## 16. Argument Handling in tools.py vs module.py

### The Evolution

This went through three iterations:

#### Iteration 1: Strict Separation

`tools.py` separates arguments into "business" and "standard" and only passes business args to `module.py`:

```python
# tools.py — filters arguments
async def extract_text(image_url: str, language: str, user_id: str, session_id: str):
    result = await module.extract_text(image_url, language)  # Only business args
    # Handle user_id, session_id here
```

**Problem raised**: *"Why are we changing things without asking questions? Why don't we just pass everything along? Why do we need this separation?"*

#### Iteration 2: Selective Passing (Stateful vs Stateless)

`tools.py` passes standard args only when the module needs them (e.g., stateful modules that store data by session):

```python
# Stateless: tools.py doesn't pass standard args
await module.extract_text(image_url, language)

# Stateful: tools.py passes session_id because module stores results
await module.extract_text(image_url, language, session_id=session_id)
```

**Problem**: This created ambiguity — developers had to decide per-argument which to pass. Edge cases were unclear.

#### Iteration 3: Pass Everything (Chosen)

`tools.py` passes ALL arguments to `module.py`. The module uses what it needs and ignores the rest:

```python
# tools.py — passes everything
async def extract_text(image_url, language, user_id, project_id, session_id, app_id):
    result = await module.extract_text(
        image_url=image_url, language=language,
        user_id=user_id, project_id=project_id,
        session_id=session_id, app_id=app_id,
    )
```

**Why chosen**: Simplest rule, no ambiguity. `tools.py` is a thin passthrough + usage reporting. `module.py` receives everything and uses what it needs.

### Argument Types (Final Design)

| Type | Examples | Who provides | Purpose |
|------|----------|-------------|---------|
| **Business args** | `image_url`, `language` | Caller (agent or app) | What the tool does |
| **Standard args** | `user_id`, `project_id`, `session_id`, `app_id` | Core injects (agents), SDK passes (apps) | Governance: who, from where |

---

## 17. Module Code Structure Strictness

### The Question

*"Why is module.py so strictly defined? Sometimes we might need an entire codebase for a complicated module, right?"*

### Approaches Considered

#### A: module.py as Entry Point / Public API (Chosen)

`module.py` is the public API — one method per MCP tool. Complex modules have sibling files:

```
v1/
├── module.py          # Public API — tools.py imports from here
├── tools.py           # FastMCP definitions
├── parser.py          # Internal: document parsing logic
├── pipeline.py        # Internal: processing pipeline
├── models/
│   └── classifier.py  # Internal: ML model wrapper
```

**Rule**: `tools.py` ONLY imports from `module.py`. Internal structure is flexible.

#### B: No module.py Convention (Rejected)

Let each module organize however it wants.

**Why rejected**: Without a consistent entry point, developers (and AI agents) don't know where to look. The convention makes modules predictable.

#### C: Strict Single-File module.py (Rejected)

All business logic must be in one file.

**Why rejected**: Unrealistic for complex modules (OCR with parsers, ML models, pipelines).

**Key constraint preserved**: `module.py` and anything it imports MUST NOT depend on FastMCP, Starlette, or any HTTP framework — enabling independent testing.

---

## 18. SDK Location & Distribution

### Approaches Considered

#### A: Monorepo at `druppie/sdk/` (Chosen)

SDK lives in the Druppie monorepo, pip-installable:

```
druppie/sdk/
├── druppie_sdk/
│   ├── __init__.py
│   ├── client.py
│   └── usage.py
└── pyproject.toml
```

In Docker (deploy time), the SDK is copied from the Druppie repo:

```dockerfile
COPY druppie/sdk/ /tmp/druppie-sdk/
RUN pip install /tmp/druppie-sdk/
```

#### B: Separate Repository / PyPI Package (Rejected)

Publish `druppie-sdk` to PyPI, install via `pip install druppie-sdk`.

**Why rejected**: Adds release management overhead. Version synchronization between SDK and modules becomes an explicit concern. For now, monorepo keeps everything in sync.

#### C: Bundled in Module Containers (Rejected)

Each module includes the SDK.

**Why rejected**: SDK is for *applications*, not modules. Modules don't need the SDK — they ARE MCP servers.

**Decision**: The project template pre-installs the SDK. Builder agents just `from druppie_sdk import DruppieClient`.

---

## 19. Project Template Design

### Evolution

The project template concept emerged from the question: *"How does the builder agent know to use the SDK?"*

#### Initial Idea: Agent Generates Everything

The builder agent generates auth code, SDK setup, and business logic from scratch.

**Problem**: Repetitive, error-prone. Auth integration (Keycloak login/logout/refresh/session) is complex and the same for every app.

#### Chosen Approach: Template as Working App

Every new Druppie project starts from `druppie/templates/project/` — a **working application out of the box**:

What the template handles (agent does NOT code):
- **Keycloak authentication** — login, logout, token refresh, session middleware
- **RBAC** — role tables, user-role assignments, admin page
- **Landing page** — company-styled default page
- **SDK** — `DruppieClient` initialized, module connections configured
- **Health endpoint** — standard `/health` for deployer agent
- **Dockerfile** — production-ready, SDK pre-installed

What the builder agent adds:
- Routes, pages, business logic
- Module calls via `from druppie_sdk import DruppieClient`
- Does NOT implement auth, SDK setup, or infrastructure

**Expansion triggered by**: *"In each project template also say that authentication using Keycloak is automatically handled so the agents don't have to code this. Also a landing page in our company's style."*

---

## 20. MCP Server Categories

### The Problem

Some MCP servers are only for agents (coding, docker), some are only for apps (app-specific modules), and some are for both. The original design didn't distinguish.

### Approaches Considered

#### A: Two Types — core and module

Initial proposal:
- `core` = agents only (coding, docker, etc.)
- `module` = agents + apps (OCR, classifier, etc.)

**Problem raised**: *"But what about modules for both core and modules?"* — the terminology was confusing. "module" meant "available to apps" but the name implied it was only for modules.

#### B: Three Types — core, module, both (Chosen)

| Type | Used by | Examples |
|------|---------|----------|
| `core` | Agents only | coding, docker, filesearch, archimate |
| `module` | Apps only | App-specific modules with no agent use case |
| `both` | Agents + Apps | OCR, classifier |

**Key differences in behavior**:
- `core`: Druppie core injects standard args (session_id, project_id) from session context
- `module`: SDK passes standard args explicitly (user_id, project_id, app_id from env vars)
- `both`: Both paths — core injects for agents, SDK passes for apps

Core MCPs are invisible to the SDK. Module and both MCPs are discoverable by apps.

---

## 21. RBAC Location

### The Problem

*"Where do application roles (viewer, editor, admin) and user-role assignments live?"*

### Approaches Considered

#### A: Druppie Core Database (Initially Chosen, Then Rejected)

```sql
-- In Druppie's database
CREATE TABLE application_roles (app_id, name, description, ...);
CREATE TABLE application_user_roles (app_id, user_id, role, ...);
```

**Problems**:
- Coupling: app access control depends on Druppie being available
- Inflexible: different apps need different role models
- Doesn't scale: every RBAC change requires Druppie API calls

#### B: App's Own Database (Chosen)

Each app manages its own RBAC. The project template provides:
- `roles` and `user_roles` tables (in the app's own database)
- Admin page for managing roles
- Auth helpers for role checking
- Keycloak login/logout already wired

**Why chosen**: App is self-contained — works even if Druppie is down. Role checks are local (no network call). Apps can extend with custom permissions.

**Follow-up question**: *"But what about changing it? How would an admin on Druppie change roles/access in a specific app?"*

**Answer**: Future consideration — apps can expose a `/druppie/access` endpoint (added to the template) that Druppie calls to list/modify roles. This keeps apps self-contained while enabling central oversight when needed.

---

## 22. Usage Tracking & Cost Attribution

### Design Principle: Caller Records, Module Reports

The module includes usage info in the MCP response `_meta` field. The *caller* (core or SDK) writes the usage record:

```
Module -> _meta.usage in response -> Caller -> INSERT module_usage (or POST /api/usage)
```

### Why Not Module-Side Recording?

- Modules don't know about Druppie's database (self-contained principle)
- Cost attribution requires caller context (which app? which project?) that the module doesn't have
- Decouples usage tracking from module logic

### The module_usage Table

Key design decisions:
- `module_id` and `module_version` are **plain strings**, not foreign keys to a registry
- `resources` is **TEXT** (JSON string), not JSONB — follows Druppie's "NO JSON/JSONB" rule
- `session_id` XOR `app_id` — exactly one must be set, distinguishing core vs app calls
- Usage data is fire-and-forget for the SDK — failures are logged but don't affect the caller

---

## 23. Resource Metrics Discovery

### The Problem

*"How do we know how to extract different text fields with module-specific resource usage? For example a v1 vs v2 of a module."*

### Approaches Considered

#### A: Registry-Based (Rejected with Registry)

Store metric definitions in the module registry database.

#### B: FastMCP `meta` Field (Chosen)

Modules declare their resource metrics in the `@mcp.tool(meta={...})` decorator:

```python
@mcp.tool(
    name="extract_text",
    meta={
        "resource_metrics": {
            "bytes_processed": {"type": "integer", "unit": "bytes"},
            "processing_ms": {"type": "integer", "unit": "milliseconds"},
        },
    },
)
```

The analytics layer:
1. Reads `module_usage` record (plain JSON string in `resources` field)
2. Calls MCP `tools/list` on the module to get metric definitions for that version
3. Uses definitions (name, type, unit) to label and format the data

**Key insight**: This was discovered when reading FastMCP documentation — the `meta` field supports arbitrary key-value pairs, including versioning info and metric schemas.

---

## 24. Sunset & End-of-Life Policy

### Approaches Considered

#### A: Kubernetes-Style Deprecation Policy

Versions get deprecated, then removed after a grace period. 410 Gone responses for removed versions.

**Why rejected**: Adds complexity (deprecation dates, migration warnings, 410 handlers). For Druppie's current scale, not worth it.

#### B: No Sunset (Chosen)

All versions stay running indefinitely. If a version exists in `MODULE.yaml`, it is served. No deprecation mechanism, no 410 responses.

**Rationale**: Simpler. If a version needs to be removed, it's a manual process (remove from `MODULE.yaml`, delete the directory, redeploy). This is an operational decision, not a protocol feature.

---

## 25. Decision Timeline

| Date | Decision | Alternatives Rejected |
|------|----------|----------------------|
| 2026-02-24 | **Approach C (SDK + MCP Hybrid)** as primary architecture | B (Library), D alone (Templates), E alone (Gateway) |
| 2026-02-24 | **Layered approach** (C + D + A as layers) | Single-approach designs |
| 2026-03 | **Module scoping guidelines** (split vs combine) | No scoping rules |
| 2026-03 | **Agent discovery** via MODULE.yaml `agent_metadata` | Manual YAML edits to agent definitions |
| 2026-03-10 | **Independent version directories** (`v1/`, `v2/`) | Stripe-style transformers, feature flags, version headers |
| 2026-03-10 | **No sunset/EOL** — all versions run indefinitely | Kubernetes-style deprecation |
| 2026-03-10 | **Additive-only DB** — shared across versions | Per-version databases, destructive migrations |
| 2026-03-11 | **Module-owned storage** — separate DB per module | Shared DB with schema isolation |
| 2026-03-11 | **Direct MCP connection** via SDK | API gateway proxy |
| 2026-03-11 | **Remove module registry** — MCP is source of truth | Database registry tables |
| 2026-03-11 | **MODULE.yaml minimal** (3 fields) + MCP for everything else | Full manifest YAML, per-version manifest.yaml |
| 2026-03-11 | **Three MCP types** (core/module/both) | Two types (core/module) |
| 2026-03-11 | **Pass all arguments** from tools.py to module.py | Selective filtering, strict separation |
| 2026-03-11 | **module.py as entry point** (flexible internal structure) | Strict single-file, no convention |
| 2026-03-11 | **SDK in monorepo** (`druppie/sdk/`) | Separate repo, PyPI package |
| 2026-03-11 | **Project template** with auth, landing page, SDK pre-installed | Agent generates everything |
| 2026-03-11 | **RBAC in app's own database** | Druppie core database |
| 2026-03-11 | **Caller records usage** (not module) | Module writes to Druppie DB |
| 2026-03-11 | **FastMCP `meta`** for resource metric definitions | Registry-based metric schemas |

---

## 26. Sources

### MCP Protocol & Architecture
- [MCP Architecture Overview](https://modelcontextprotocol.io/docs/learn/architecture)
- [MCP Architecture Patterns for Multi-Agent AI Systems (IBM)](https://developer.ibm.com/articles/mcp-architecture-patterns-ai-systems/)
- [MCP Transports Specification](https://modelcontextprotocol.io/specification/2025-06-18/basic/transports)
- [MCP Streamable HTTP](https://thenewstack.io/how-mcp-uses-streamable-http-for-real-time-ai-tool-interaction/)
- [MCP Specification 2025-11-25](https://modelcontextprotocol.io/specification/2025-11-25)
- [MCP Versioning Specification](https://modelcontextprotocol.io/specification/versioning)
- [MCP Tool Versioning Discussion (#1915)](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/1915)

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

### Versioning & Compatibility
- [Stripe: APIs as Infrastructure — Future-Proofing with Versioning](https://stripe.com/blog/api-versioning)
- [Google AIP-180: Backwards Compatibility](https://google.aip.dev/180)
- [Zalando RESTful API Guidelines — Compatibility](https://github.com/zalando/restful-api-guidelines/blob/main/chapters/compatibility.adoc)
- [Kubernetes Deprecation Policy](https://kubernetes.io/docs/reference/using-api/deprecation-policy/)

### Module & Plugin Patterns
- [Django Apps vs Flask Blueprints](https://blog.appseed.us/flask-blueprints-vs-django-apps/)
- [NestJS Modules](https://docs.nestjs.com/modules)
- [Grafana Plugin Lifecycle](https://grafana.com/developers/plugin-tools/key-concepts/plugin-lifecycle)
- [WordPress Activation/Deactivation Hooks](https://developer.wordpress.org/plugins/plugin-basics/activation-deactivation-hooks/)

### Database Patterns
- [PostgreSQL Schemas Documentation](https://www.postgresql.org/docs/current/ddl-schemas.html)
- [Crunchy Data: PostgreSQL Multi-Tenancy](https://www.crunchydata.com/blog/designing-your-postgres-database-for-multi-tenancy)
- [AWS: Multi-tenant PostgreSQL RLS](https://aws.amazon.com/blogs/database/multi-tenant-data-isolation-with-postgresql-row-level-security/)
- [12-Factor App: Backing Services](https://12factor.net/backing-services)

### Event-Driven Architecture
- [Microservices.io: Event Sourcing Pattern](https://microservices.io/patterns/data/event-sourcing.html)
- [Microsoft: CQRS Pattern](https://learn.microsoft.com/en-us/azure/architecture/patterns/cqrs)
- [Confluent: Event-Driven Architecture](https://www.confluent.io/learn/event-driven-architecture/)

### Code Generation
- [Cookiecutter vs Yeoman](https://www.cookiecutter.io/article-post/compare-cookiecutter-to-yeoman)
- [Copilot Workspace (GitHub Next)](https://githubnext.com/projects/copilot-workspace)
