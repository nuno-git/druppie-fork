---
id: "003"
title: "Druppie Module Convention"
status: complete
author: Druppie team
date: 2026-03-11
outcome: null
---

# Druppie Module Convention — Research & Decision Records

> **Status**: Reference / historical record
> **Date**: 2026-02-24 (initial brainstorm) to 2026-03-11 (iterative design)
> **Author**: Druppie team
> **User Story**: Als Druppie-teamlid wil ik een gestandaardiseerd format/contract voor core-modules, zodat uitbreidingen op een uniforme manier worden toegevoegd ongeacht wie ze bouwt.
> **Related**: `docs/adrs/019-module-system-architecture.md` (architectural decisions — ADR), and the auth & governance design (design doc, not yet migrated). The full technical contract that resulted from this research lives in Part III below.

This document captures the full design journey for Druppie's module convention: the original research exploring five architectural approaches (Part I), the comparative analysis and test cases that drove the recommendation, the design decisions made during specification development (Part II), and the resulting technical specification (Part III) — file layout, MODULE.yaml contract, DB schemas, SDK interface, auth flow, and the OCR v1.0→v2.0 worked example that ADR 019 commits to. It is the "why" and the "what" behind the decisions.

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

### Part III — Resulting Technical Specification

27. [Module Definition](#27-module-definition)
28. [File Structure & Contract](#28-file-structure--contract)
29. [MODULE.yaml & MCP as Source of Truth](#29-moduleyaml--mcp-as-source-of-truth)
30. [Module Code Contract](#30-module-code-contract)
31. [Version System](#31-version-system)
32. [Module-Owned Storage](#32-module-owned-storage)
33. [MCP Protocol & Categories](#33-mcp-protocol--categories)
34. [Standard Module Arguments](#34-standard-module-arguments)
35. [Authentication](#35-authentication)
36. [Usage Tracking & Analytics](#36-usage-tracking--analytics)
37. [Application Access Control (RBAC)](#37-application-access-control-rbac)
38. [Database Tables (Druppie Core)](#38-database-tables-druppie-core)
39. [Druppie SDK](#39-druppie-sdk)
40. [Backend API for Modules](#40-backend-api-for-modules)
41. [Agent Module Discovery](#41-agent-module-discovery)
42. [Module Lifecycle](#42-module-lifecycle)
43. [Worked Example — OCR Module v1.0 → v2.0](#43-worked-example--ocr-module-v10--v20)
44. [Impact on Existing Code](#44-impact-on-existing-code)

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
| **Business Analyst (BA)** | Required | Defines functional requirements and acceptance criteria in the FD (Functional Design). Provides a possible solution direction — does NOT decide whether a module should be built |
| **Architect (AR)** | Required | Determines whether a new module is needed. Creates the **module specification** by combining functional requirements (from the BA's FD) with technical requirements. Designs the module contract (input/output schema) and validates against the module convention |
| **Developer (DEV)** | Required | Implements module logic, MCP server, tests |
| **Reviewer** | Required | Reviews module code against convention, security, performance |
| **Planner** | Optional | Orchestrates multi-agent workflow if module is complex |
| **Tester** | Required | Validates module against contract, integration tests |
| **Deployer** | Required | Deploys module container, registers in configuration |

### BA vs. Architect: Responsibility Split

The BA and Architect have distinct, sequential responsibilities:

| Aspect | BA (Functional Design) | Architect (Module Specification) |
|--------|--------------------------|----------------------------------|
| **Focus** | What the user needs | How the platform delivers it |
| **Output** | FD with functional requirements and acceptance criteria | MODULE_SPEC.md with functional + technical requirements |
| **Module decision** | Suggests a possible solution direction | Decides whether a module is the right approach |
| **Scope** | End-to-end problem description | Module-specific contract and constraints |

The BA describes the problem and what a solution must achieve. The Architect reads the FD, decides whether an existing module covers it or a new module is needed, and if so, writes the module specification that combines the BA's functional requirements with the technical requirements needed for the module convention.

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

### When and How Modules Are Created

Modules are created through the **update core** flow — the Architect adds new modules directly to the Druppie core codebase via a PR workflow.

**The trigger**: During the design phase of any project, the Architect reviews the BA's FD and determines that a reusable capability is needed that doesn't exist yet (or that an existing module needs a new major version). This is the moment a module is born.

**The flow**:

```
1. BA writes the FD          -> Functional requirements, acceptance criteria,
                                possible solution direction

2. AR reads the FD            -> Determines: can existing modules cover this,
                                or is a new module needed?

3. AR writes module spec      -> MODULE_SPEC.md combining:
                                - Functional requirements (from FD)
                                - Technical requirements (from AR)
                                - Module contract (input/output schema)
                                - Version strategy

4. AR uses "update core"      -> Triggers the update_core intent, which:
                                - Creates a feature branch on the Druppie repo
                                - Implements the module following the convention
                                - Creates a PR targeting colab-dev
                                - PR is always reviewed and merged by humans

5. Module lands in core       -> After PR merge, module is available to all
                                future applications
```

**Why update core?** Modules live in the Druppie core (`druppie/mcp-servers/module-<name>/`). Adding a new module means modifying the core codebase — adding the module directory, updating `docker-compose.yaml`, updating `mcp_config.yaml`, etc. The update core flow (see the update-core-flow design doc, not yet migrated) provides the mechanism for agents to safely modify the core through PRs that require human review.

**Timing**: Module creation happens *before* the application that needs it is built. The Architect first ensures the required modules exist in core, then the application development can proceed with those modules available.

### Agents as Primary Consumers

Modules are not just infrastructure for developers — **agents are the first consumers**. The Architect agent needs to discover which modules exist and understand how to use them without manual system prompt updates. This means:

- `MODULE.yaml` must contain enough structured metadata for an agent to decide "this module is relevant for my task" (see `agent_metadata` in the specification)
- New modules should be **automatically discoverable** by agents through the registry, not through manual YAML edits to agent definitions
- Module descriptions, use cases, and examples must be written with LLM comprehension in mind, not just human readability

### Module Development Workflow

```
1. BA defines requirements    -> FD with functional reqs and acceptance criteria
2. AR decides module needed   -> Evaluates acceptance criteria, checks for overlap
3. AR writes module spec      -> MODULE_SPEC.md (functional + technical reqs)
4. AR triggers update core    -> Creates branch + PR on Druppie core repo
5. DEV implements             -> module.py + server.py + tests (within the PR)
6. Reviewer validates         -> Code review against module convention
7. Tester runs suite          -> Contract tests + integration tests
8. PR merged by human         -> Module lands in core codebase
9. Module is discoverable     -> Available to all agents and applications
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

---

# Part III — Resulting Technical Specification

This section captures the technical specification that resulted from the design decisions in Parts I and II. It is the implementation contract that ADR 019 commits to: file layout, MODULE.yaml reference, version rules, DB schemas, SDK interface, auth flow, code templates, the OCR v1.0→v2.0 worked example, and impact on existing code. ADR 019 records the eight architectural decisions at a summary level; this part records what those decisions produce. Bracketed references like `[R003 §31]` in ADR 019 point back into this section.

The section numbers continue from Part II. Sections 27–44 below were previously sections 1–18 of ADR 019; cross-references inside Part III have been renumbered accordingly (e.g., what was `§4` is now `§30`).

---

## 27. Module Definition

A **Druppie module** is a containerized MCP server that:

1. Exposes tools via the MCP protocol (JSON-RPC over HTTP).
2. Has a `MODULE.yaml` manifest declaring its identity and active versions.
3. Follows the versioned directory pattern: `server.py` (root router) +
   `vN/module.py` (business logic per major version).
4. Manages its own data storage independently (own database or stateless). It
   receives Druppie context (`user`, `session`, `project`) through injected MCP
   parameters — never by querying Druppie's database directly.
5. Is callable by both Druppie agents (build-time) and generated applications
   (runtime via SDK).
6. Supports multiple major versions running simultaneously via path-based
   routing (`/v1/mcp`, `/v2/mcp`).

A module is **not** a Python library imported into applications (Approach B —
rejected), not a free-form microservice (must follow the MCP tool protocol),
not a standalone application (modules are building blocks), not a pipeline or
orchestrator (if it mainly calls other modules, it belongs in the application
layer or as a skill), and not a thin wrapper around a single utility function
(if it has no own state or heavy dependencies, use a builtin tool instead).

## 28. File Structure & Contract

Every module lives in `druppie/mcp-servers/module-<name>/` with versioned
subdirectories per major version:

```
druppie/mcp-servers/module-<name>/
├── MODULE.yaml              # Identity + version listing (root-level only)
├── Dockerfile               # One container serves all versions
├── requirements.txt         # Combined dependencies for all versions
├── server.py                # Entrypoint: routes /v1/mcp, /v2/mcp, /mcp → latest
├── db.py                    # Shared DB connection (if module needs a database)
├── auth.py                  # Shared Keycloak JWT validation
├── v1/
│   ├── __init__.py
│   ├── module.py            # v1 public API: one method per MCP tool
│   ├── tools.py             # v1 FastMCP tool definitions (name, description, schema, meta)
│   ├── ...                  # Any internal modules (parsers, pipelines, models, etc.)
│   ├── schema/
│   │   ├── 001_initial.sql  # First migration
│   │   └── current.sql      # Full schema snapshot (for fresh installs)
│   └── tests/
│       └── test_module.py   # v1-specific tests
├── v2/
│   ├── __init__.py
│   ├── module.py            # v2 public API: one method per MCP tool
│   ├── tools.py             # v2 FastMCP tool definitions
│   ├── ...
│   ├── schema/
│   │   ├── 001_add_pages_table.sql
│   │   ├── 002_add_source_column.sql
│   │   └── current.sql      # Full schema = v1 final + v2 additions
│   └── tests/
│       └── test_module.py   # v2-specific tests
└── tests/
    └── test_routing.py      # Cross-version routing tests
```

**What lives where:**

| Location | Contains | Shared? |
|----------|----------|---------|
| Root `MODULE.yaml` | Module ID, list of active versions, latest version pointer | N/A — one file |
| Root `server.py` | HTTP entrypoint, path-based routing to version dirs, config loading | Yes — infrastructure only |
| Root `db.py` | Database connection pool to the module's own database (if needed) | Yes — infrastructure only |
| Root `auth.py` | Keycloak JWT validation middleware | Yes — infrastructure only |
| Root `Dockerfile` | Container definition, installs all deps | Yes |
| Root `requirements.txt` | Union of all version dependencies | Yes |
| `vN/module.py` | Public API for this version (one method per tool). Imports from sibling files for complex modules | No — owned by version |
| `vN/tools.py` | FastMCP tool definitions: name, description, input schema, `meta` (version, resource_metrics) — the **single source of truth** for the tool contract | No — owned by version |
| `vN/schema/` | SQL migration files for this version's DB changes | No — owned by version |
| `vN/tests/` | Tests for this version's contract | No — owned by version |
| Root `tests/` | Cross-version tests (routing, coexistence) | N/A |

**Sharing rule.** Infrastructure code lives at the root and is shared across
all versions: `server.py` (routing), `db.py` (database connection pool),
`auth.py` (JWT validation). **Business logic is never shared** — each version
owns its full implementation in `vN/`, even if some code is identical across
versions. If a bug exists in shared infrastructure, it is fixed once at the
root. If a bug exists in business logic, it is fixed independently in each
version directory.

**Naming convention:**

| Item | Pattern | Example |
|------|---------|---------|
| Directory | `module-<name>` | `module-ocr` |
| Module ID | `<name>` (lowercase, hyphens OK) | `ocr`, `document-classifier` |
| Version directory | `v<major>` | `v1`, `v2` |
| Container name | `druppie-module-<name>` | `druppie-module-ocr` |
| Docker Compose service | `module-<name>` | `module-ocr` |
| Port | 9010-9099 (9001-9009 reserved for core MCP servers) | `9010` |
| DB container (if needed) | `druppie-module-<name>-db` | `druppie-module-ocr-db` |
| DB name (if needed) | `module_<name>` | `module_ocr` |

## 29. MODULE.yaml & MCP as Source of Truth

**Define once.** Module metadata lives in exactly one place — no duplication
between YAML and code.

- **MODULE.yaml** contains only what the MCP protocol cannot provide: module
  ID and version routing.
- **Everything else** — name, description, tool schemas, agent guidance,
  resource metrics — is defined in the FastMCP server code (`vN/tools.py`) and
  discovered via the MCP protocol (`initialize`, `tools/list`).

**MODULE.yaml** is the only YAML file in the module. Minimal — just version
routing:

```yaml
id: ocr                                    # Unique module identifier (required)
latest_version: "2.0.0"                   # The version served at /mcp (required)
versions:                                  # All active major versions (required)
  - "1.0.0"                               # Served at /v1/mcp
  - "2.0.0"                               # Served at /v2/mcp
```

Three fields, read by `server.py` for routing. Everything else comes from the
MCP server instead:

| What | Where it's defined | How it's discovered |
|------|-------------------|-------------------|
| Server name | `FastMCP("OCR Module v1")` | MCP `initialize` → `serverInfo.name` |
| Server version | `FastMCP(..., version="1.2.0")` | MCP `initialize` → `serverInfo.version` |
| Agent guidance | `FastMCP(..., instructions="...")` | MCP `initialize` → `instructions` |
| Tool name, description, input schema | `@mcp.tool(name=..., description=...)` | MCP `tools/list` |
| Tool version, resource metrics | `@mcp.tool(meta={...})` | MCP `tools/list` → `meta` |
| Approval rules, required roles | `mcp_config.yaml` | Druppie-specific, not in MCP |

## 30. Module Code Contract

#### `vN/module.py` — Public API (Per-Version)

`module.py` is the **entry point** to the version's business logic — not
necessarily the entire codebase. It exposes one public method per MCP tool,
and `tools.py` only imports from `module.py`.

For simple modules, all logic lives in `module.py`. For complex modules
(document pipelines, ML models, multiple processing stages), `module.py`
imports from sibling files:

```
v1/
├── module.py          # Public API — tools.py imports from here
├── tools.py           # FastMCP definitions
├── parser.py          # Internal: document parsing logic
├── pipeline.py        # Internal: processing pipeline
├── models/
│   └── classifier.py  # Internal: ML model wrapper
├── schema/
└── tests/
```

`module.py` and anything it imports **must not** depend on FastMCP, Starlette,
or any HTTP framework — so it can be tested independently.

```python
"""<Module Name> Module v1 — Public API.

Entry point for v1 business logic. One public method per MCP tool.
Imported by v1/tools.py for MCP exposure.
Can import from sibling files for complex logic.
"""

import logging
from typing import Any

logger = logging.getLogger("<module-id>-mcp.v1")


class <ModuleName>Module:
    """v1 business logic for <description>.

    All public methods correspond 1:1 to MCP tools defined in tools.py.
    """

    def __init__(self, config_param: str = "default"):
        self.config_param = config_param

    async def tool_name(
        self,
        required_param: str,
        optional_param: str = "default",
        user_id: str = "",
        project_id: str = "",
        session_id: str = "",
        app_id: str = "",
    ) -> dict[str, Any]:
        """Execute tool operation."""
        result = self._internal_processing(required_param)
        return {
            "field1": result["value"],
            "field2": result["score"],
        }
```

Rules:

- One public async method per MCP tool, receiving all arguments (business +
  standard).
- Method names match tool names in `vN/tools.py`.
- Raise exceptions on failure (don't return error dicts — let `tools.py`
  handle formatting).
- No `SELECT *` in database queries — always select explicit columns so new
  columns from other versions don't break this version.

#### `vN/tools.py` — MCP Tool Definitions (Per-Version)

Each version directory contains its own `tools.py` that wraps module methods
as MCP tools. `tools.py` is a thin layer with two responsibilities:

1. **Pass all arguments** to `module.py` (business args + standard args).
2. **Usage reporting**: measure timing, wrap the result with `_meta`.

Every MCP tool receives two kinds of arguments. `tools.py` passes all of them
to `module.py` — the module uses what it needs and ignores the rest:

| Type | Examples | Who provides them | Purpose |
|------|----------|-------------------|---------|
| **Business args** | `image_url`, `language` | The caller (agent prompt or app code) | What the tool actually does |
| **Standard args** | `user_id`, `project_id`, `session_id`, `app_id` | Core injects them (agents), SDK passes them (apps) | Governance: who called, from where |

```python
"""<Module Name> v1 — MCP Tool Definitions.

Wraps v1/module.py business logic as MCP tools via FastMCP.
This file is the SINGLE SOURCE OF TRUTH for the tool contract:
- Tool name, description, input schema → via @mcp.tool() decorator
- Version, resource metrics → via @mcp.tool(meta={...})
- Agent guidance → via FastMCP(instructions=...)
All discoverable by MCP clients via initialize + tools/list.
"""

import os
import time
from fastmcp import FastMCP
from .module import <ModuleName>Module

MODULE_ID = "<module-id>"
MODULE_VERSION = "1.2.0"

mcp = FastMCP(
    "<Module Name> v1",
    version=MODULE_VERSION,
    instructions="""<Description of what this module does and when to use it.>

Use when:
- <scenario 1>
- <scenario 2>

Don't use when:
- <scenario where this module is not appropriate>
""",
)

module = <ModuleName>Module(
    config_param=os.getenv("CONFIG_PARAM", "default"),
)


@mcp.tool(
    name="tool_name",
    description="Tool description — this is what agents and SDK users see.",
    meta={
        "module_id": MODULE_ID,
        "version": MODULE_VERSION,
        "resource_metrics": {
            "processing_ms": {"type": "integer", "unit": "milliseconds"},
        },
    },
)
async def tool_name(
    required_param: str,
    optional_param: str = "default",
    user_id: str = "",
    project_id: str = "",
    session_id: str = "",
    app_id: str = "",
) -> dict:
    start = time.time()
    result = await module.tool_name(
        required_param=required_param,
        optional_param=optional_param,
        user_id=user_id,
        project_id=project_id,
        session_id=session_id,
        app_id=app_id,
    )
    elapsed_ms = int((time.time() - start) * 1000)
    return {
        **result,
        "_meta": {
            "module_id": MODULE_ID,
            "module_version": MODULE_VERSION,
            "usage": {
                "cost_cents": 0.0,
                "resources": {"processing_ms": elapsed_ms},
            },
        },
    }
```

#### `server.py` — Root Router

The root `server.py` is the entrypoint. It mounts each version's MCP app at
its path and handles routing:

```python
"""<Module Name> MCP Server — Version Router.

Routes requests to the correct version:
  /v1/mcp → v1/tools.py
  /v2/mcp → v2/tools.py
  /mcp    → latest version
"""

import logging
import os
from pathlib import Path

import yaml
import uvicorn
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("<module-id>-mcp")

# Read MODULE.yaml for version info
MANIFEST_PATH = Path(__file__).parent / "MODULE.yaml"
with open(MANIFEST_PATH) as f:
    manifest = yaml.safe_load(f)

latest_version = manifest["latest_version"]
major_latest = latest_version.split(".")[0]

# Import version-specific MCP apps
from v1.tools import mcp as v1_mcp
from v2.tools import mcp as v2_mcp

version_apps = {
    "1": v1_mcp.http_app(),
    "2": v2_mcp.http_app(),
}


async def health(request):
    """Aggregate health: reports status of all active versions."""
    return JSONResponse({
        "status": "healthy",
        "module_id": manifest["id"],
        "latest_version": latest_version,
        "active_versions": manifest["versions"],
    })


async def version_health(request):
    """Per-version health check."""
    major = request.path_params["major"]
    if major not in version_apps:
        return JSONResponse({"status": "not_found"}, status_code=404)
    return JSONResponse({
        "status": "healthy",
        "module_id": manifest["id"],
        "version": f"v{major}",
    })


# Build routes: /v1/mcp, /v1/health, /v2/mcp, /v2/health, /mcp → latest
routes = [
    Route("/health", health, methods=["GET"]),
    Route("/v{major}/health", version_health, methods=["GET"]),
]
for major, app in version_apps.items():
    routes.append(Mount(f"/v{major}", app=app))

# /mcp → latest version
routes.append(Mount("/", app=version_apps[major_latest]))

app = Starlette(routes=routes)

if __name__ == "__main__":
    port = int(os.getenv("MCP_PORT", "9010"))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
```

**Routing summary:**

| Request path | Routes to |
|-------------|-----------|
| `/v1/mcp` | `v1/tools.py` |
| `/v1/health` | v1 health check |
| `/v2/mcp` | `v2/tools.py` |
| `/v2/health` | v2 health check |
| `/mcp` | Latest version (from `MODULE.yaml` `latest_version`) |
| `/health` | Aggregate health (all versions) |

#### `db.py` — Shared Database Connection (Optional)

Modules that need a database define the connection at the root level. All
versions share the same connection pool and the same database:

```python
"""<Module Name> — Shared Database Connection.

Provides a connection pool to the module's OWN database.
This is NOT Druppie's database — it's a separate PostgreSQL instance
owned by this module (see docker-compose service module-<name>-db).

All versions (v1, v2, ...) share this connection and the same database.
"""

import os
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

MODULE_DB_URL = os.getenv("MODULE_DB_URL")

if MODULE_DB_URL:
    engine = create_async_engine(MODULE_DB_URL, pool_size=5, max_overflow=10)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
else:
    engine = None
    SessionLocal = None
```

Version code imports it:

```python
# v1/module.py
from db import SessionLocal

class OCRModule:
    async def extract_text(self, image_url: str, ...) -> dict:
        async with SessionLocal() as session:
            # Query the module's own database
            ...
```

#### `auth.py` — Shared JWT Validation

All versions share the same Keycloak JWT validation logic:

```python
"""<Module Name> — Shared Keycloak JWT Validation.

Validates incoming Keycloak tokens. Modules validate tokens themselves
(no gateway proxy). The token proves user identity; context (project_id,
app_id, session_id) comes via standard MCP tool arguments.
"""

import os
from jose import jwt, JWTError
from jose.backends import RSAKey
import httpx

KEYCLOAK_URL = os.getenv("KEYCLOAK_SERVER_URL", "http://keycloak:8080")
KEYCLOAK_REALM = os.getenv("KEYCLOAK_REALM", "druppie")
JWKS_URL = f"{KEYCLOAK_URL}/realms/{KEYCLOAK_REALM}/protocol/openid-connect/certs"

_jwks_cache = None

async def _get_jwks():
    global _jwks_cache
    if _jwks_cache is None:
        async with httpx.AsyncClient() as client:
            response = await client.get(JWKS_URL)
            _jwks_cache = response.json()
    return _jwks_cache

async def validate_token(token: str) -> dict:
    """Validate Keycloak JWT and extract user identity.

    Returns: {"user_id": "uuid", "username": "...", "roles": [...]}
    Raises: JWTError if token is invalid.
    """
    jwks = await _get_jwks()
    payload = jwt.decode(
        token,
        jwks,
        algorithms=["RS256"],
        issuer=f"{KEYCLOAK_URL}/realms/{KEYCLOAK_REALM}",
    )
    return {
        "user_id": payload["sub"],
        "username": payload.get("preferred_username"),
        "roles": payload.get("realm_access", {}).get("roles", []),
    }
```

#### Dockerfile & Docker Compose Templates

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# System dependencies (customize per module)
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy all module code (root + version dirs)
COPY . .

ENV MCP_PORT=9010

EXPOSE 9010

HEALTHCHECK --interval=10s --timeout=5s --retries=10 --start-period=30s \
    CMD curl -f http://localhost:9010/health || exit 1

CMD ["python", "server.py"]
```

```yaml
  # Module's own database (only if module needs persistent storage)
  module-<name>-db:
    image: postgres:16-alpine
    container_name: druppie-module-<name>-db
    profiles: [infra, dev, prod]
    environment:
      POSTGRES_DB: module_<name>
      POSTGRES_USER: module_<name>
      POSTGRES_PASSWORD: ${MODULE_<NAME>_DB_PASSWORD:-module_<name>_dev}
    volumes:
      - module-<name>-db-data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U module_<name>"]
      interval: 10s
      timeout: 5s
      retries: 5
    networks:
      - druppie-new-network

  module-<name>:
    build:
      context: ./druppie/mcp-servers/module-<name>
      dockerfile: Dockerfile
    container_name: druppie-module-<name>
    profiles: [infra, dev, prod]
    environment:
      MCP_PORT: "9010"
      CONFIG_PARAM: ${MODULE_<NAME>_CONFIG:-default}
      # Module's own database (not Druppie's):
      MODULE_DB_URL: postgresql://module_<name>:${MODULE_<NAME>_DB_PASSWORD:-module_<name>_dev}@module-<name>-db:5432/module_<name>
    ports:
      - "${MODULE_<NAME>_PORT:-9010}:9010"
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:9010/health"]
      interval: 10s
      timeout: 5s
      retries: 10
      start_period: 30s
    networks:
      - druppie-new-network
    depends_on:
      module-<name>-db:
        condition: service_healthy
```

> Stateless modules (e.g., a module that wraps an external API) don't need a
> database container at all — omit the `module-<name>-db` service and the
> `MODULE_DB_URL` environment variable.

#### `mcp_config.yaml` Entry Template

```yaml
  <module-id>:
    url: ${MCP_<MODULE>_URL:-http://module-<name>:9010}
    type: module                               # "module" = apps only, "both" = agents + apps, "core" = agents only
    description: "Module description from MODULE.yaml"
    inject:                                    # Core-only injection (for agent calls)
      session_id:
        from: session.id
        hidden: true
      user_id:
        from: session.user_id
        hidden: true
      project_id:
        from: project.id
        hidden: true
    tools:
      - name: tool_name
        description: "Tool description"
        requires_approval: false
        parameters:
          type: object
          properties:
            required_param:
              type: string
              description: "Description"
          required: [required_param]
```

## 31. Version System

**Core principle.** Each major version is an independent, self-contained
codebase. No translation between versions, no shared business logic. `v1/`
always contains the latest 1.x.y code; `v2/` always contains the latest 2.x.y
code. Minor and patch bumps update code in-place within their major version
directory.

**Semantic versioning.** Modules use SemVer 2.0.0 with Druppie-specific
interpretations:

| Change Type | Version Bump | What Happens |
|------------|-------------|-------------|
| **MAJOR** | New `vN+1/` directory | Create new version directory, copy from previous, make breaking changes |
| **MINOR** | Update in-place in `vN/` | New optional parameter (with default), new response field, new tool |
| **PATCH** | Update in-place in `vN/` | Bug fix, performance improvement, dependency update |

**Breaking (requires new major version directory):**

- Removing a tool, parameter, or response field
- Renaming a tool, parameter, or response field
- Changing a field's type (e.g., `string` → `integer`)
- Changing field semantics (e.g., UTC → local time)
- Making an optional input parameter required
- Making a required output field optional/nullable
- Removing an enum value from an input parameter
- Changing a tool's description significantly (breaks LLM callers)

**Non-breaking (minor bump, in-place in `vN/`):**

- Adding a new tool
- Adding a new optional input parameter (with default)
- Adding a new field to response output
- Adding a new enum value to an input parameter
- Relaxing validation (e.g., increasing max length)

**Internal (patch bump, in-place in `vN/`):**

- Bug fixes that don't change the API contract
- Performance improvements
- Logging changes
- Dependency updates

**Major version bump procedure** (going from v1 to v2):

1. Create `v2/` directory.
2. Copy `v1/` contents as starting point.
3. Make breaking changes in `v2/module.py`, `v2/tools.py`.
4. Update version and meta in `v2/tools.py` (FastMCP constructor +
   `@mcp.tool(meta={...})`).
5. Write `v2/schema/` migrations for any DB additions (additive-only).
6. Write `v2/tests/`.
7. Update root `MODULE.yaml`: add `"2.0.0"` to `versions`, set
   `latest_version: "2.0.0"`.
8. Update root `server.py` to import and mount `v2/tools.py`.
9. `v1/` is untouched — still serves its clients at `/v1/mcp`.

**No transformers.** Each version runs its own code independently. There is
no translation layer between versions. A v1 client calls `/v1/mcp` and gets a
v1 response from `v1/module.py`. A v2 client calls `/v2/mcp` and gets a v2
response from `v2/module.py`.

**No sunset / end of life.** All versions stay running indefinitely. There is
no sunset mechanism, no deprecation dates, no 410 Gone responses. If a version
exists in `MODULE.yaml`, it is served. Removing a version is a manual
operational decision (remove from `MODULE.yaml`, delete the directory,
redeploy), not a protocol feature.

**Application version selection.** The SDK selects which major version to call
via the path:

```python
# Application calls v1 endpoint
druppie = DruppieClient(
    module_versions={
        "ocr": "v1",              # Calls /v1/mcp
        "classifier": "v2",      # Calls /v2/mcp
    }
)

result = await druppie.ocr.extract("invoice.png")
# SDK calls: POST http://module-ocr:9010/v1/mcp

# Or call latest (default — hits /mcp which routes to latest)
druppie = DruppieClient()
result = await druppie.ocr.extract("invoice.png")
# SDK calls: POST http://module-ocr:9010/mcp
```

## 32. Module-Owned Storage

**Design principle.** Each module manages its own data storage independently.
Modules **never** connect to Druppie's PostgreSQL database. Instead:

- **Stateful modules** get their own database container (PostgreSQL, SQLite,
  or whatever fits).
- **Stateless modules** don't need any database at all.
- **Druppie context** (`user_id`, `session_id`, `project_id`) is received
  through injected MCP parameters, not by querying Druppie's tables.
- **Cost tracking** is the caller's responsibility (core or SDK reports to the
  Druppie backend), not the module's.

**Why not shared DB.** Sharing Druppie's PostgreSQL (even with schema
isolation) creates hidden coupling:

| Problem | Impact |
|---------|--------|
| **Schema coupling** | Module does `SELECT * FROM public.sessions` → Druppie renames a column → module breaks |
| **Not portable** | Can't develop, test, or run a module without a copy of Druppie's schema |
| **Not self-contained** | Contradicts the core module principle of independence |
| **Reset fragility** | Druppie's "reset DB" workflow can break modules that read from `public.*` |
| **Permission complexity** | PostgreSQL role/grant management adds operational overhead |

**What modules need (and how they get it):**

| Need | How | Example |
|------|-----|---------|
| Know which user called | Injected MCP parameter `user_id` | Already in `mcp_config.yaml` inject rules |
| Know which session | Injected MCP parameter `session_id` | Already in `mcp_config.yaml` inject rules |
| Project context | Passed as tool argument | `project_id` in tool input schema |
| Persistent state | Module's own database | `module-ocr-db` PostgreSQL container |
| Cost tracking | Caller (core/SDK) records usage | SDK reports to Druppie backend after each call |

**Database rules for versioned modules.** Since multiple major versions of a
module run simultaneously against the module's own database, strict rules
apply:

1. **One database per module** — `module_<name>` (e.g., `module_ocr`).
2. **Shared across all major versions of that module** — v1 and v2 read/write
   the same database.
3. **Additive-only changes** — add columns (with defaults), add tables, add
   indexes.
4. **Never destructive** — no `DROP`, `RENAME`, or `ALTER TYPE` while any
   version uses the affected object.
5. **Every new column has a `DEFAULT`** — older version code can INSERT
   without specifying it.
6. **No `SELECT *`** — version code selects explicit columns so new columns
   don't break it.

Both v1 and v2 run simultaneously against the same module database. If v2
drops a column that v1 uses, v1 breaks. Additive-only guarantees that older
versions keep working regardless of what newer versions add.

**Migration files.** Each version directory has a `schema/` folder with
numbered SQL migration files:

```
v1/schema/
├── 001_initial.sql                # CREATE TABLE extractions (...)
├── 002_add_output_format.sql      # ALTER TABLE ... ADD COLUMN output_format VARCHAR DEFAULT 'plain'
└── current.sql                    # Full schema snapshot (for fresh installs)
```

```
v2/schema/
├── 001_add_pages_table.sql        # CREATE TABLE extraction_pages (...)
├── 002_add_source_column.sql      # ALTER TABLE ... ADD COLUMN source VARCHAR DEFAULT ''
└── current.sql                    # Full schema = v1 final state + v2 additions
```

**Migration tracking.** A tracking table records which migrations have been
applied:

```sql
CREATE TABLE _migrations (
    id SERIAL PRIMARY KEY,
    version_dir VARCHAR NOT NULL,     -- 'v1' or 'v2'
    filename VARCHAR NOT NULL,        -- '001_initial.sql'
    applied_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(version_dir, filename)
);
```

**Fresh install vs. upgrade:**

| Scenario | What runs |
|----------|-----------|
| Fresh install | `v1/schema/current.sql` then `v2/schema/current.sql` |
| Upgrade v1 (1.0 → 1.2) | Unapplied `v1/schema/00N_*.sql` files in order |
| Add v2 to existing v1 | All `v2/schema/00N_*.sql` files in order |

Migrations always run in order: all v1 migrations first, then v2 migrations.
v2's schema builds on v1's final state.

## 33. MCP Protocol & Categories

**Protocol upgrade.** All MCP servers use **FastMCP** (official Python MCP
SDK). Both Druppie core and the Druppie SDK use the official MCP client
library. This replaces the custom HTTP servers with hand-rolled JSON-RPC and
the `MCPClient`/`MCPHttp` in `druppie/core/`.

- **Server side:** every MCP server becomes a proper FastMCP server (see the
  `tools.py` template in §30).
- **Client side — Druppie Core:** replace `MCPHttp` with the official MCP
  client, wrapped with Druppie-specific features:

  ```python
  class DruppieToolExecutor:
      """Wraps official MCP client with Druppie-specific features.

      1. Argument injection (core-only: session_id, project_id, etc.)
      2. Approval checking (existing flow, unchanged)
      3. Usage recording (reads _meta.usage, writes to module_usage table)
      """
  ```

- **Client side — Druppie SDK:** the SDK is also an MCP client, but without
  injection — apps pass arguments explicitly (see §37).

**What stays in `mcp_config.yaml`:** tool lists, approval rules, injection
mappings, and the `type` field.

**MCP server categories:**

| Type | Used by | Argument handling | Examples |
|------|---------|-------------------|----------|
| `core` | Agents only | Druppie core injects session_id, project_id, repo_name, etc. from session context | coding, docker, filesearch, archimate |
| `module` | Apps only | SDK passes standard args explicitly | App-specific modules with no agent use case |
| `both` | Agents + Apps | **Core**: injects standard args for agents. **SDK**: passes standard args explicitly for apps | OCR, classifier |

How to decide:

- If the MCP only makes sense during an agent session (needs repo access,
  workspace, session state) → `core`.
- If the MCP is only used by generated apps, not by agents → `module`.
- If the MCP is used by both agents and apps → `both`.

Core MCPs are invisible to the SDK. Module and both MCPs are discoverable by
apps via the SDK.

## 34. Standard Module Arguments

Every `module` or `both` type MCP call includes these standard arguments. They
enable usage tracking, cost attribution, and analytics without modules needing
to know about Druppie's internal database.

**Argument definitions:**

| Argument | Type | Core (agent) | App (SDK) | Purpose |
|----------|------|-------------|-----------|---------|
| `user_id` | UUID | **REQUIRED** — injected by core from session | **REQUIRED** — extracted from Keycloak token by SDK | Identifies who made the call |
| `project_id` | UUID or null | **OPTIONAL** — injected by core, null for `general_chat` sessions | **REQUIRED** — from SDK config (`DRUPPIE_PROJECT_ID` env var) | Links usage to a project |
| `session_id` | UUID or null | **REQUIRED** — injected by core from session | **MUST be null** | Identifies the agent session |
| `app_id` | UUID or null | **MUST be null** | **REQUIRED** — from SDK config (`DRUPPIE_APP_ID` env var) | Identifies the calling application |

**Validation rules:**

1. `user_id` is always required.
2. Exactly one of `session_id` or `app_id` must be set (never both, never
   neither).
3. `project_id` is required for apps, optional for core (null when agent has
   no project, e.g., `general_chat` intent).

**How each caller provides them:**

- **Core (agents):** arguments are injected by `DruppieToolExecutor` before
  the MCP call, using the existing injection mechanism defined in
  `mcp_config.yaml`. The agent and module never see the injection — it happens
  transparently.
- **SDK (apps):** the SDK reads `user_id` from the Keycloak token and
  `project_id`/`app_id` from environment variables set at deploy time. It
  passes them as regular MCP tool arguments on every call.

**Context detection.** Modules don't need a separate `context` field. The
presence of `session_id` vs `app_id` tells the calling context:

| `session_id` | `app_id` | Context |
|-------------|---------|---------|
| set | null | Core / agent call |
| null | set | App call |
| set | set | **Invalid** — module should reject |
| null | null | **Invalid** — module should reject |

## 35. Authentication

**Single identity provider.** Keycloak is the sole identity provider for
everything: Druppie core, apps built by Druppie, and module MCP servers. All
users exist in the `druppie` realm.

**How each component authenticates:**

| Component | How it gets a token | Token audience |
|-----------|-------------------|----------------|
| Druppie core (agents) | User logs into frontend → Keycloak JWT. For sandbox: short-lived OBO token | `druppie-backend` |
| Druppie-built app | User logs into app → Keycloak JWT (same realm, app-specific client) | `druppie-modules` |
| Module MCP server | Receives token in request → validates against Keycloak JWKS endpoint | Validates `druppie-modules` or `druppie-backend` |

Module-side token validation uses the shared `auth.py` at the module root
(see §30).

**Sandbox security — short-lived tokens.** Agents run in sandboxes that must
not have long-lived credentials. The same pattern used for GitHub and LLM
proxies applies here:

1. Before sandbox launch, Druppie core requests a **short-lived OBO token**
   from Keycloak (`grant_type=urn:ietf:params:oauth:grant-type:token-exchange`,
   `audience=druppie-modules`, TTL: 15 minutes).
2. Token is stored in the **credential store** (existing infrastructure).
3. Token is injected into the sandbox as `DRUPPIE_MODULE_TOKEN` env var.
4. SDK inside the sandbox uses this token for module calls.
5. Modules validate it as a normal Keycloak JWT — no special handling.

The token carries the original user's identity (`sub` = user_id), so usage is
attributed to the correct user even when an agent acts on their behalf.

> **Token for identity, arguments for context.** The token proves who the user
> is. The standard arguments (`session_id`, `project_id`, etc.) provide the
> calling context. These are separate concerns.

## 36. Usage Tracking & Analytics

**End-to-end flow:**

```
Module MCP Server                    Caller (Core or SDK)              Druppie DB
       │                                      │                           │
       │  MCP response with _meta.usage       │                           │
       │─────────────────────────────────────►│                           │
       │                                      │  INSERT module_usage      │
       │                                      │──────────────────────────►│
       │                                      │                           │
       │                                      │  (SDK: POST /api/usage)   │
       │                                      │──────────────────────────►│
```

**Step 1 — Module reports usage in `_meta`.** Every module includes usage
information in the MCP response `_meta` field (see the `tools.py` template in
§30).

Required `_meta` fields:

- `module_id` — the module's identifier from `MODULE.yaml`.
- `module_version` — the version string from `tools.py`.
- `usage.cost_cents` — the cost of this call in cents (`0.0` if free).

Optional `_meta` fields:

- `usage.resources` — module-specific resource usage (object with arbitrary
  keys, defined in the tool's `meta.resource_metrics`).

**Step 2 — Caller records usage.** The **caller** writes the usage record —
not the module:

- **Core** (`DruppieToolExecutor`): reads `_meta` from the MCP response,
  inserts a `module_usage` record directly into the Druppie database.
- **SDK** (`DruppieClient`): reads `_meta` from the MCP response, sends it to
  the Druppie backend via `POST /api/usage` (see §37 for the SDK
  implementation).

Modules don't need to know about the Druppie database. They report usage in
`_meta` and the caller handles storage.

**Step 3 — Analytics queries.** Usage can be sliced by user, module, app, or
context:

```sql
-- Per user, per module, this month
SELECT user_id, module_id, SUM(cost_cents) as total_cost, COUNT(*) as calls
FROM module_usage
WHERE created_at >= date_trunc('month', NOW())
GROUP BY user_id, module_id;

-- Core (agent) vs app usage
SELECT
    CASE WHEN app_id IS NOT NULL THEN 'app' ELSE 'core' END as context,
    module_id, SUM(cost_cents) as total_cost, COUNT(*) as calls
FROM module_usage
GROUP BY context, module_id;
```

**Resource metric definitions.** Modules declare what resource metrics they
report in the `meta` field of their `@mcp.tool()` decorator. This allows the
analytics UI to correctly label, format, and display module-specific resource
data. The definitions are discoverable via MCP `tools/list`.

The full chain:

1. **Module** returns `_meta` with `module_id`, `module_version`, and `usage`
   (including `resources`).
2. **Caller** (core or SDK) copies the usage data into a `module_usage` record
   (see §38).
3. **Analytics layer** reads `module_usage`, calls MCP `tools/list` on the
   module to get `resource_metrics` definitions for that version.
4. **Analytics UI** uses the metric definitions (name, type, unit) to label
   and format the resource data.

The `resources` field in `module_usage` is a plain text string
(JSON-serialized) — never queried by sub-field. The MCP server provides the
schema for interpreting it via `tools/list` `meta.resource_metrics`.

## 37. Application Access Control (RBAC)

Every Druppie-built app has its own role-based access control. Roles and user
assignments live in the **app's own database**, not in Druppie's core DB. The
project template provides RBAC tables, helpers, and an admin page out of the
box.

**Why roles live in the app.** Access control is application-specific.
Different apps need different roles and permissions. Keeping it in the app:

- App is self-contained — works even if Druppie is down.
- Role checks are local (no network call to Druppie backend).
- Apps can extend with custom permissions without touching Druppie.
- No coupling between Druppie's DB and app-specific data.

**How it works:**

1. Druppie builds an app → project template includes RBAC tables and admin
   page.
2. App admin defines roles (e.g., "viewer", "editor", "admin") via the
   built-in admin page.
3. App admin assigns Keycloak users to roles (same Keycloak realm, same
   users).
4. User logs into the app → gets a Keycloak JWT (standard flow, same realm).
5. App checks roles locally against its own DB.
6. App uses roles to gate access to features.

**What the project template provides.** The RBAC system is part of the project
template (`druppie/templates/project/`). Apps get it for free:

- `roles` and `user_roles` tables (created by template migrations).
- Admin page for managing roles and user assignments.
- Auth helpers for role checking in routes.
- Keycloak login/logout already wired up.

**Future: central management.** If Druppie needs to manage access across apps
centrally, each app can expose a `/druppie/access` endpoint (added to the
project template) that Druppie calls to list/modify roles. This keeps apps
self-contained while enabling central oversight.

## 38. Database Tables (Druppie Core)

These tables live in Druppie's core database (not in module databases).

#### `module_usage`

Records every module call with full context:

```sql
CREATE TABLE module_usage (
    id UUID PRIMARY KEY,

    -- Who
    user_id UUID NOT NULL REFERENCES users(id),

    -- Context (session XOR app)
    session_id UUID REFERENCES sessions(id),
    app_id UUID REFERENCES applications(id),
    project_id UUID REFERENCES projects(id),

    -- What
    module_id VARCHAR(100) NOT NULL,
    tool_name VARCHAR(100) NOT NULL,
    module_version VARCHAR(20),

    -- Result
    success BOOLEAN NOT NULL,
    error_message TEXT,

    -- Cost & resources
    cost_cents FLOAT NOT NULL DEFAULT 0.0,
    resources TEXT,              -- JSON string (NOT JSONB), schema from MCP tools/list meta

    -- When
    started_at TIMESTAMPTZ NOT NULL,
    duration_ms INTEGER,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

> `resources` is stored as Text (JSON string), not JSONB — following Druppie's
> "NO JSON/JSONB columns" rule. It's never queried by sub-field, only
> displayed. The schema for interpreting it comes from the module's MCP
> `tools/list` `meta.resource_metrics`.

#### `applications`

```sql
CREATE TABLE applications (
    id UUID PRIMARY KEY,
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    owner_id UUID NOT NULL REFERENCES users(id),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
```

> `application_roles` and `application_user_roles` live in each app's own
> database (provided by the project template), not in Druppie's core DB. See
> §37.

## 39. Druppie SDK

The SDK is a lightweight Python package included in every Druppie-generated
application. It is an **MCP client** that connects directly to module MCP
servers (no gateway proxy). It handles authentication, standard argument
injection, usage reporting, version routing, and retries.

**Location.** The SDK lives in the Druppie monorepo at `druppie/sdk/`. It is a
pip-installable Python package.

```
druppie/sdk/
├── druppie_sdk/
│   ├── __init__.py          # DruppieClient
│   ├── client.py            # Main client — MCP client wrapper
│   ├── usage.py             # Usage reporting to Druppie backend
│   └── py.typed             # PEP 561 marker
├── pyproject.toml
└── README.md
```

**How apps get the SDK.** Every Druppie-generated project starts from a
**project template** (see below) that already has the SDK installed. The
builder agent doesn't install it — it just
`from druppie_sdk import DruppieClient` in the code it writes.

In Docker (deploy time), the SDK is copied from the Druppie repo and
installed:

```dockerfile
COPY druppie/sdk/ /tmp/druppie-sdk/
RUN pip install /tmp/druppie-sdk/
```

**Project template.** Every new Druppie project starts from a template at
`druppie/templates/project/`. This is copied into the project's repo at
creation time, before the builder agent starts writing code.

```
druppie/templates/project/
├── requirements.txt          # druppie-sdk, fastapi, uvicorn, etc.
├── druppie.config.yaml       # Module connections, app identity (populated at deploy)
├── Dockerfile                # SDK install baked in
├── app/
│   ├── main.py               # FastAPI app with DruppieClient, auth, health
│   ├── auth.py               # Keycloak login/logout, token refresh, session middleware
│   └── static/
│       └── ...               # Company-style landing page assets
└── templates/
    ├── base.html             # Base layout in company style
    └── landing.html          # Default landing page
```

The template is a **working application out of the box** — authentication, a
landing page, health endpoint, and SDK wiring are all done. The builder agent
only adds business logic on top.

What the template handles (agent does NOT need to code these):

- **Keycloak authentication** — login, logout, token refresh, session
  middleware. Users log in with existing Druppie/Keycloak credentials.
  Already wired up.
- **RBAC** — role tables, user-role assignments, admin page for managing
  access. Each app owns its own roles in its own database.
- **Landing page** — company-styled default page. Agent can replace or extend
  it.
- **SDK** — `DruppieClient` initialized, module connections configured.
- **Health endpoint** — standard `/health` for deployer agent.
- **Dockerfile** — production-ready, SDK and dependencies pre-installed.
- **`druppie.config.yaml`** — module URLs and app identity, populated at
  deploy time.

What the builder agent does:

- Adds routes, pages, and business logic.
- Calls modules via `from druppie_sdk import DruppieClient`.
- Does NOT implement auth, SDK setup, or infrastructure.

> **Python only for now.** The project template and SDK are Python. Non-Python
> app support may be added later.
> **Expandable.** The template will grow over time (e.g., WebSocket support,
> notification system, common UI components).

**Core client:**

```python
# druppie_sdk/client.py

class DruppieClient:
    """MCP client for Druppie-generated applications.

    Connects directly to module MCP servers (no gateway proxy).
    Zero-config: reads DRUPPIE_* environment variables automatically.

    Usage:
        druppie = DruppieClient()
        result = await druppie.modules.call("ocr", "extract_text", {"source": "img.png"})
    """

    def __init__(
        self,
        druppie_url: str | None = None,
        module_versions: dict[str, str] | None = None,
    ):
        # Druppie backend URL (for usage reporting + app role checks)
        self.druppie_url = druppie_url or os.environ.get(
            "DRUPPIE_URL", "http://druppie-backend:8000"
        )
        # App identity (set at deploy time)
        self.app_id = os.environ.get("DRUPPIE_APP_ID")
        self.project_id = os.environ.get("DRUPPIE_PROJECT_ID")
        # Auth token (Keycloak JWT or short-lived sandbox token)
        self._token = os.environ.get("DRUPPIE_MODULE_TOKEN")

        self.module_versions = module_versions or {}
        self.modules = ModuleClient(self)
        self._usage = UsageReporter(self)

    @property
    def ocr(self) -> OCRAccessor:
        return OCRAccessor(self)

    @property
    def classifier(self) -> ClassifierAccessor:
        return ClassifierAccessor(self)


class ModuleClient:
    """MCP client that calls module servers directly."""

    def __init__(self, client: DruppieClient):
        self._client = client

    async def call(
        self,
        module: str,
        tool: str,
        args: dict,
    ) -> dict:
        """Call a module MCP tool directly.

        1. Resolves module URL from config
        2. Adds standard arguments (user_id, project_id, app_id)
        3. Makes MCP tool call (official protocol)
        4. Extracts _meta.usage and reports to Druppie backend
        5. Returns the business result (without _meta)
        """
        # Add standard arguments
        user_id = self._get_user_id_from_token()
        args = {
            **args,
            "user_id": user_id,
            "project_id": self._client.project_id or "",
            "app_id": self._client.app_id or "",
            "session_id": "",  # Always empty for app calls
        }

        # Build MCP endpoint URL with version routing
        module_url = self._resolve_module_url(module)
        pinned = self._client.module_versions.get(module)
        if pinned:
            url = f"{module_url}/{pinned}/mcp"
        else:
            url = f"{module_url}/mcp"

        # Make MCP tool call with retry
        started_at = time.time()
        result = await self._mcp_call_with_retry(url, tool, args)
        duration_ms = int((time.time() - started_at) * 1000)

        # Extract and report usage
        meta = result.pop("_meta", {})
        if meta.get("usage"):
            await self._client._usage.report(
                module_id=meta.get("module_id", module),
                module_version=meta.get("module_version"),
                tool_name=tool,
                user_id=user_id,
                cost_cents=meta["usage"].get("cost_cents", 0.0),
                resources=meta["usage"].get("resources"),
                success=True,
                duration_ms=duration_ms,
            )

        return result
```

**Usage reporting:**

```python
# druppie_sdk/usage.py

class UsageReporter:
    """Reports module usage to Druppie backend asynchronously."""

    def __init__(self, client: DruppieClient):
        self._client = client

    async def report(
        self,
        module_id: str,
        module_version: str | None,
        tool_name: str,
        user_id: str,
        cost_cents: float,
        resources: dict | None,
        success: bool,
        duration_ms: int,
    ):
        """POST usage record to Druppie backend.

        Fire-and-forget: failures are logged but don't affect the caller.
        """
        try:
            async with httpx.AsyncClient(timeout=5.0) as http:
                await http.post(
                    f"{self._client.druppie_url}/api/usage",
                    json={
                        "user_id": user_id,
                        "app_id": self._client.app_id,
                        "project_id": self._client.project_id,
                        "session_id": None,
                        "module_id": module_id,
                        "module_version": module_version,
                        "tool_name": tool_name,
                        "cost_cents": cost_cents,
                        "resources": json.dumps(resources) if resources else None,
                        "success": success,
                        "duration_ms": duration_ms,
                    },
                    headers={"Authorization": f"Bearer {self._client._token}"},
                )
        except Exception:
            logger.warning(f"Failed to report usage for {module_id}:{tool_name}")
```

**Typed module accessors:**

```python
class OCRAccessor:
    """Typed convenience accessor for OCR module."""

    def __init__(self, client: DruppieClient):
        self._client = client

    async def extract(self, source: str, language: str = "auto", output_format: str = "plain") -> dict:
        return await self._client.modules.call("ocr", "extract_text", {
            "source": source, "language": language, "output_format": output_format,
        })


class ClassifierAccessor:
    """Typed convenience accessor for classifier module."""

    def __init__(self, client: DruppieClient):
        self._client = client

    async def classify(self, text: str, categories: list[str]) -> dict:
        return await self._client.modules.call("classifier", "classify_document", {
            "content": text, "categories": categories,
        })
```

## 40. Backend API for Modules

Apps connect directly to module MCP servers (no gateway proxy). The Druppie
backend provides supporting API routes for usage reporting, module discovery,
and app access control.

**Module routes:**

```python
# druppie/api/routes/modules.py

router = APIRouter(prefix="/api/modules", tags=["modules"])

@router.get("/")
async def list_modules(category: str = None):
    """List all available modules (for discovery)."""
    ...

@router.get("/{module_id}/info")
async def module_info(module_id: str):
    """Get module metadata including active versions and tools."""
    ...
```

**Usage routes:**

```python
# druppie/api/routes/usage.py

router = APIRouter(prefix="/api/usage", tags=["usage"])

@router.post("/")
async def record_usage(payload: UsageRecord, user: dict = Depends(get_current_user)):
    """Record a module usage event (called by SDK after each module call)."""
    ...

@router.get("/")
async def get_usage(
    module_id: str = None, app_id: str = None, user_id: str = None,
    period: str = "month",
):
    """Query usage analytics with filters."""
    ...
```

> Application access control (roles, user assignments) is managed by each app
> in its own database via the project template. No Druppie backend endpoints
> needed. See §37.

## 41. Agent Module Discovery

Agents (AR, BA) need to discover and inspect available modules during
conversations — for example, to check if a capability already exists before
proposing a new module, or to understand what tools a module exposes.

**Builtin tool: `list_druppie_modules`.** Added to the **Architect (AR)** and
**Business Analyst (BA)** agent tool sets. Not needed for Developer agents —
they can read the code directly.

```python
# druppie/agents/builtin_tools.py

@tool
def list_druppie_modules(
    category: str = None,
    module_id: str = None,
    version: str = None,
) -> str:
    """List available Druppie modules or inspect a specific module version.

    Without arguments: returns a summary of all modules (name, available versions, category, description).
    With category: filters by MCP type (core, module, both).
    With module_id: returns detailed info for a specific module.
    With module_id + version: returns full tool schemas for that specific version.

    Args:
        category: Filter by MCP type — "core", "module", or "both". Optional.
        module_id: Inspect a specific module. Optional.
        version: Major version to inspect (e.g. "v1", "v2"). Requires module_id. Optional, defaults to latest.
    """
    ...
```

How it works:

1. Reads `mcp_config.yaml` to get all registered modules and their endpoints.
2. Reads each module's `MODULE.yaml` to get available versions and latest
   version.
3. Calls MCP `initialize` on the latest version to get description.
4. When inspecting a specific version, calls MCP `tools/list` to get full tool
   schemas.

**Summary mode** (no `module_id`):

```
Modules (3 found):

  ocr — type: both
    Versions: v1, v2 (latest: v2)
    "Extract text and structured data from images and PDFs"

  document-classifier — type: both
    Versions: v1 (latest: v1)
    "Classify documents into categories using ML"

  code-analysis — type: core
    Versions: v1 (latest: v1)
    "Static code analysis tools for quality checks"
```

**Detail mode** (`module_id="ocr"`) — defaults to latest version:

```
Module: ocr
Type: both
Versions: v1 (v1.4.2), v2 (v2.1.0)
Showing: v2 (latest)

Tool: extract_text
  Extract text from an image or PDF file.
  Args:
    - file_path (string, required): Path to the file
    - language (string, optional): OCR language hint (default: "auto")
    - user_id (string, required): Druppie user ID
    - project_id (string, optional): Druppie project ID
    - session_id (string, optional): Build session ID
    - app_id (string, optional): Application ID

Tool: extract_structured
  Extract structured key-value data from a document.
  Args:
    - file_path (string, required): Path to the file
    - template (string, required): Extraction template name
    - user_id (string, required): Druppie user ID
    ...
```

This gives AR/BA full visibility into the module ecosystem without leaving
the conversation. AR uses it during module proposal evaluation (step 0 of the
lifecycle) to check for overlap. BA uses it to understand what capabilities
are already available when gathering requirements.

## 42. Module Lifecycle

**Module creation flow.** Modules are created when the **Architect** determines
that a new reusable capability is needed. The BA does not decide whether a
module should be built — the BA provides the functional requirements in the FD
(Functional Design), and the Architect decides how to fulfill them.

```
BA writes FD               Functional requirements, acceptance criteria,
                            possible solution direction
        │
        ▼
AR reads FD                 Determines: can existing modules cover this?
        │                   Or is a new module needed?
        │
        ├─ Existing module  → Proceed with application development
        │   covers it
        │
        └─ New module       → AR writes MODULE_SPEC.md
           needed              (functional reqs from FD + technical reqs from AR)
                │
                ▼
        AR triggers          Uses the "update core" intent to create
        update core          a branch + PR on the Druppie core repo
                │            (see update-core-flow design doc)
                ▼
        Module developed     DEV implements within the PR, following
        & reviewed           the module convention
                │
                ▼
        PR merged            Human reviews and merges into colab-dev
                │
                ▼
        Module in core       Available for all applications
```

The **module specification** (`MODULE_SPEC.md`) is owned by the Architect and
combines:

- **Functional requirements** from the BA's FD (what the capability must do,
  acceptance criteria).
- **Technical requirements** from the Architect (contract schema, version
  strategy, dependencies, performance constraints).

This separation ensures the BA focuses on *what* the user needs without
making platform-level decisions, while the Architect translates those needs
into module-level technical design.

**From proposal to running:**

```
0. ACCEPT      Module proposal evaluated against acceptance criteria
                AR validates: reuse, genericity, no overlap, ownership
                AR writes MODULE_SPEC.md (functional + technical reqs)
                (See "Module Acceptance" in Research 003)

1. UPDATE CORE  AR triggers update_core intent → creates branch + PR
                on Druppie core repo (colab-dev)

2. DEVELOP      Create module directory with v1/ subdirectory:
                v1/module.py, v1/tools.py, v1/schema/
                Root: MODULE.yaml, server.py, db.py, auth.py, Dockerfile, requirements.txt
                Test locally: python server.py (no Docker needed)

3. REGISTER     Add docker-compose service + mcp_config.yaml entry

4. PR REVIEW    Human reviews module PR against convention
                PR merged into colab-dev

5. DEPLOY       docker compose --profile dev up -d module-<name>
                Container starts, health check passes

6. CONFIGURE    Agent YAML files updated to include module tools
                Injection rules added to mcp_config.yaml

7. AVAILABLE    Module tools appear in agent tool lists
                SDK can call module directly at /v1/mcp or /mcp
```

**Updating a module.**

*Non-breaking update (MINOR/PATCH)* — changes within `vN/`:

1. Update `vN/module.py`, `vN/tools.py`.
2. Bump version in `vN/tools.py` (FastMCP constructor + tool meta).
3. Add migration file to `vN/schema/` if DB changes needed (additive-only,
   with defaults).
4. Update `vN/tests/`.
5. Rebuild and restart container.
6. All applications continue working — no changes needed.

*Breaking update (MAJOR)* — create new `vN+1/` directory:

1. Create `vN+1/` directory.
2. Copy `vN/` contents as starting point.
3. Make breaking changes in `vN+1/module.py`, `vN+1/tools.py`.
4. Update version and meta in `vN+1/tools.py`.
5. Write `vN+1/schema/` migrations for any DB additions (additive-only).
6. Write `vN+1/tests/`.
7. Update root `MODULE.yaml`: add new version to `versions`, update
   `latest_version`.
8. Update root `server.py` to import and mount `vN+1/tools.py`.
9. Rebuild and restart container.
10. `vN/` is untouched — all existing clients at `/vN/mcp` continue working.

## 43. Worked Example — OCR Module v1.0 → v2.0

This example demonstrates the version system end-to-end.

#### v1.0.0 — Initial Release

Folder structure:

```
druppie/mcp-servers/module-ocr/
├── MODULE.yaml
├── Dockerfile
├── requirements.txt
├── server.py
├── db.py
├── auth.py
├── v1/
│   ├── module.py
│   ├── tools.py
│   ├── schema/
│   │   ├── 001_initial.sql
│   │   └── current.sql
│   └── tests/
│       └── test_module.py
└── tests/
    └── test_routing.py
```

`MODULE.yaml`:

```yaml
id: ocr
latest_version: "1.0.0"
versions:
  - "1.0.0"
```

`v1/tools.py` (single source of truth for the tool contract):

```python
from fastmcp import FastMCP
from .module import OCRModule

mcp = FastMCP(
    "OCR Module v1",
    version="1.0.0",
    instructions="Extract text from images and documents (PDF, JPG, PNG). Use when processing scanned or photographed documents.",
)

module = OCRModule()

@mcp.tool(
    name="extract_text",
    description="Extract text from an image or document",
    meta={
        "module_id": "ocr",
        "version": "1.0.0",
        "resource_metrics": {
            "bytes_processed": {"type": "integer", "unit": "bytes"},
            "processing_ms": {"type": "integer", "unit": "milliseconds"},
        },
    },
)
async def extract_text(
    image_url: str,
    language: str = "auto",
    user_id: str = "",
    project_id: str = "",
    session_id: str = "",
    app_id: str = "",
) -> dict:
    start = time.time()
    result = await module.extract_text(
        image_url=image_url, language=language,
        user_id=user_id, project_id=project_id,
        session_id=session_id, app_id=app_id,
    )
    elapsed_ms = int((time.time() - start) * 1000)
    return {
        **result,
        "_meta": {
            "module_id": "ocr",
            "module_version": "1.0.0",
            "usage": {"cost_cents": 0.0, "resources": {"bytes_processed": 0, "processing_ms": elapsed_ms}},
        },
    }
```

`v1/module.py`:

```python
class OCRModule:
    async def extract_text(self, image_url: str, language: str = "auto",
                           user_id: str = "", project_id: str = "",
                           session_id: str = "", app_id: str = "") -> dict:
        result = self._run_ocr(image_url, language)
        await self._save_extraction(session_id, image_url, result)
        return {"text": result["text"], "confidence": result["confidence"]}
```

`v1/schema/001_initial.sql` (runs against module's own database, not
Druppie's):

```sql
CREATE TABLE extractions (
    id UUID PRIMARY KEY,
    session_id UUID NOT NULL,     -- Passed via standard MCP argument
    image_url VARCHAR(500) NOT NULL,
    language VARCHAR(10) DEFAULT 'auto',
    extracted_text TEXT,
    confidence FLOAT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

SDK usage:

```python
druppie = DruppieClient()
result = await druppie.ocr.extract("invoice.png")
# SDK calls: POST http://module-ocr:9010/mcp (latest = v1)
# {"text": "Invoice #1234...", "confidence": 0.95}
```

#### v1.1.0 — Add `output_format` (non-breaking, in-place update)

Changes happen inside `v1/` — no new directory.

- `v1/tools.py`: bump version to `"1.1.0"` in FastMCP constructor and tool
  meta. Add `output_format` parameter to `@mcp.tool()`.
- `v1/module.py`: add `output_format` parameter with default `"plain"`.
- `v1/schema/002_add_output_format.sql`:

```sql
ALTER TABLE extractions
    ADD COLUMN output_format VARCHAR(20) DEFAULT 'plain';
```

Existing SDK callers: no changes needed. `output_format` defaults to
`"plain"`.

#### v1.2.0 — Add `bounding_boxes` to response (non-breaking, in-place update)

Changes happen inside `v1/` — no new directory.

- `v1/tools.py`: bump version to `"1.2.0"` in FastMCP constructor and tool
  meta.
- `v1/module.py`: include `bounding_boxes` in return dict.

Existing SDK callers: no changes needed. Extra field is ignored or used
optionally.

#### v2.0.0 — Rename `image_url`→`source`, restructure response (BREAKING)

A new `v2/` directory is created. `v1/` is untouched.

New folder structure:

```
druppie/mcp-servers/module-ocr/
├── MODULE.yaml              # Updated: latest_version: "2.0.0", versions: ["1.0.0", "2.0.0"]
├── server.py                # Updated: imports and mounts v2/tools.py at /v2
├── db.py                    # Shared DB connection (both versions use same database)
├── auth.py                  # Shared JWT validation
├── v1/                      # UNTOUCHED — still serves at /v1/mcp
│   ├── module.py
│   ├── tools.py             # Still at 1.2.0 (version in FastMCP constructor)
│   ├── schema/
│   │   ├── 001_initial.sql
│   │   ├── 002_add_output_format.sql
│   │   └── current.sql
│   └── tests/
├── v2/                      # NEW — serves at /v2/mcp
│   ├── module.py            # Breaking changes: source param, nested response
│   ├── tools.py             # version="2.0.0", new tool schemas in @mcp.tool()
│   ├── schema/
│   │   ├── 001_add_source_column.sql
│   │   ├── 002_add_pages_table.sql
│   │   └── current.sql
│   └── tests/
└── tests/
```

`MODULE.yaml` changes:

```yaml
latest_version: "2.0.0"
versions:
  - "1.0.0"
  - "2.0.0"
```

`v2/module.py`:

```python
class OCRModule:
    async def extract_text(self, source: str, language: str = "auto", output_format: str = "plain",
                           user_id: str = "", project_id: str = "",
                           session_id: str = "", app_id: str = "") -> dict:
        result = self._run_ocr(source, language)
        await self._save_extraction(session_id, source, result)
        return {
            "document": {"text": result["text"], "format": output_format, "language": result["detected_language"]},
            "confidence": result["confidence"],
            "pages": [{"page_number": 1, "text": result["text"]}],
        }
```

`v2/schema/001_add_source_column.sql` (additive — v1 still works):

```sql
ALTER TABLE extractions
    ADD COLUMN source VARCHAR(500) DEFAULT '';
```

`v2/schema/002_add_pages_table.sql`:

```sql
CREATE TABLE extraction_pages (
    id UUID PRIMARY KEY,
    extraction_id UUID NOT NULL REFERENCES extractions(id),
    page_number INTEGER NOT NULL,
    text TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

SDK callers using v1:

```python
# Still works — v1 code is untouched, running at /v1/mcp
druppie = DruppieClient(module_versions={"ocr": "v1"})
result = await druppie.ocr.extract("invoice.png")
# SDK calls: POST http://module-ocr:9010/v1/mcp
# {"text": "...", "confidence": 0.95, "bounding_boxes": [...]}
```

SDK callers using v2:

```python
druppie = DruppieClient(module_versions={"ocr": "v2"})
result = await druppie.ocr.extract("invoice.png")
# SDK calls: POST http://module-ocr:9010/v2/mcp
# {"document": {"text": "...", "format": "plain", "language": "nl"}, "confidence": 0.95, "pages": [...]}
```

SDK callers using latest (default):

```python
druppie = DruppieClient()  # No version pinning
result = await druppie.ocr.extract("invoice.png")
# SDK calls: POST http://module-ocr:9010/mcp → routes to v2 (latest)
```

## 44. Impact on Existing Code

**What changes:**

| Component | Change | Effort |
|-----------|--------|--------|
| `druppie/core/mcp_client.py` | Replace with official MCP client library, keep injection wrapper (`DruppieToolExecutor`) | High |
| `druppie/execution/tool_executor.py` | Add usage recording after MCP calls, read `_meta` | Medium |
| `druppie/core/mcp_config.yaml` | Add `type: core\|module\|both` to each MCP entry | Low |
| `druppie/mcp-servers/coding/` | Migrate to FastMCP server | High |
| `druppie/mcp-servers/docker/` | Migrate to FastMCP server | High |
| `druppie/mcp-servers/filesearch/` | Migrate to FastMCP server | Medium |
| `druppie/mcp-servers/archimate/` | Migrate to FastMCP server | Medium |
| `druppie/db/models/` | Add `module_usage`, `applications` tables (see §38) | Medium |
| `druppie/services/` | Add `UsageTrackingService` | Medium |
| `druppie/api/routes/` | Add usage endpoints (see §40) | Medium |
| `druppie-sdk/` | New package: MCP client + auth + usage reporting (see §39) | High |
| `druppie/agents/builtin_tools.py` | Update sandbox launch to include short-lived module token | Low |
| `iac/realm.yaml` | Add `druppie-modules` audience, configure token exchange | Low |
| Module `tools.py` | Add `resource_metrics` to `@mcp.tool(meta={...})` | Low per module |

**What does NOT change:**

- Keycloak realm structure (users, roles) — unchanged, just adding a
  client/audience.
- Frontend auth flow — unchanged.
- Agent YAML definitions — unchanged.
- Approval system — unchanged (still works through the tool executor).
- Database schema for existing core tables — unchanged.
