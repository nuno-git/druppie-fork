# Module Versioning Design

> **Status**: Approved design
> **Date**: 2026-03-10
> **Context**: Replaces sections 5 and 6 of `docs/module-specification.md`

---

## Problem

The module specification defines SemVer rules and a Stripe-inspired transformer system for version compatibility, but never specifies:

- How versioned code is organized in the filesystem
- What happens to the folder when you bump a major version
- How the database evolves across versions
- How routing selects the right version

This design answers all of those.

---

## Core Principle

Each major version is an independent, self-contained codebase within the module directory. No translation between versions, no shared business logic. Simple and explicit.

---

## Folder Structure

```
druppie/mcp-servers/module-<name>/
├── MODULE.yaml              # Identity + version listing
├── Dockerfile               # One container, all versions
├── requirements.txt         # Combined dependencies
├── server.py                # Entrypoint: routes /v1/mcp, /v2/mcp, /mcp → latest
├── v1/
│   ├── manifest.yaml        # v1 version metadata + tool schemas
│   ├── module.py            # v1 business logic (fully independent)
│   ├── tools.py             # v1 @mcp.tool() definitions
│   ├── schema/
│   │   ├── 001_initial.sql
│   │   └── current.sql      # Full schema snapshot (for fresh installs)
│   └── tests/
│       └── test_module.py
├── v2/
│   ├── manifest.yaml        # v2 version metadata + tool schemas
│   ├── module.py            # v2 business logic (fully independent)
│   ├── tools.py             # v2 @mcp.tool() definitions
│   ├── schema/
│   │   ├── 001_add_pages_table.sql
│   │   ├── 002_add_source_column.sql
│   │   └── current.sql
│   └── tests/
│       └── test_module.py
└── tests/
    └── test_routing.py      # Verifies /v1 and /v2 both work
```

### What Lives Where

| Location | Contains | Shared? |
|----------|----------|---------|
| Root `MODULE.yaml` | Module identity (id, name, author, description), list of active versions, latest version pointer | N/A |
| Root `server.py` | HTTP entrypoint, path-based routing, DB connection setup, config loading | Yes — infrastructure only |
| Root `Dockerfile` | Container definition | Yes |
| Root `requirements.txt` | Union of all version dependencies | Yes |
| `vN/manifest.yaml` | Version number, tool schemas (input/output JSON Schema), per-tool metadata | No — owned by version |
| `vN/module.py` | All business logic for this version | No — owned by version |
| `vN/tools.py` | MCP tool definitions delegating to module.py | No — owned by version |
| `vN/schema/` | SQL migration files for this version's DB changes | No — owned by version |
| `vN/tests/` | Tests for this version's contract | No — owned by version |
| Root `tests/` | Cross-version tests (routing, coexistence) | N/A |

### Sharing Rule

Infrastructure code (DB connection, config loading, logging, server setup) lives at the root and is shared. Business logic is never shared — each version owns its full implementation, even if some lines are identical across versions.

---

## Routing

Path-based only. No version headers, no version negotiation protocol.

| Request path | Routes to |
|-------------|-----------|
| `/v1/mcp` | `v1/tools.py` |
| `/v2/mcp` | `v2/tools.py` |
| `/mcp` | Latest version (e.g., `v2/tools.py`) |

`server.py` at the root handles this routing. It reads `MODULE.yaml` to know which versions exist and what the latest is.

---

## SemVer Rules

### Within a Major Version

`v1/` always contains the **latest 1.x.y** code. Minor and patch bumps update code in-place within the `v1/` directory. The `v1/manifest.yaml` version field tracks the current 1.x.y.

Example: v1 goes from 1.0.0 → 1.1.0 → 1.2.0. All changes happen inside `v1/`. No new directories.

### What Constitutes Each Bump

| Change type | Version bump | Examples |
|------------|-------------|---------|
| **MAJOR** | New `vN+1/` directory | Rename parameter, change response structure, remove tool |
| **MINOR** | Update in-place in `vN/` | New optional parameter (with default), new response field, new tool |
| **PATCH** | Update in-place in `vN/` | Bug fix, performance improvement, dependency update |

### What's Breaking vs. Non-Breaking

**Breaking (requires new major directory):**
- Removing a tool, parameter, or response field
- Renaming a tool, parameter, or response field
- Changing a field's type (e.g., `string` → `integer`)
- Changing field semantics (e.g., UTC → local time)
- Making an optional input parameter required
- Making a required output field optional/nullable
- Removing an enum value from an input parameter

**Non-breaking (minor bump, in-place):**
- Adding a new tool
- Adding a new optional input parameter (with default)
- Adding a new field to response output
- Adding a new enum value to an input parameter
- Relaxing validation (e.g., increasing max length)

---

## Major Version Bump Procedure

When going from v1 to v2:

1. Create `v2/` directory
2. Copy `v1/` contents as starting point
3. Make breaking changes in `v2/module.py`, `v2/tools.py`
4. Write `v2/manifest.yaml` with new schemas
5. Write `v2/schema/` migrations for any DB additions
6. Write `v2/tests/`
7. Update root `MODULE.yaml`: add `"2.0.0"` to versions, set `latest_version: "2.0.0"`
8. Update `server.py` to register `/v2/mcp` route
9. `v1/` is untouched — still serves its clients at `/v1/mcp`

---

## No Transformers

Each version runs its own code independently. There is no translation layer between versions. A v1 client calls `/v1/mcp` and gets a v1 response from `v1/module.py`. A v2 client calls `/v2/mcp` and gets a v2 response from `v2/module.py`.

If a bug exists in shared logic, it is fixed independently in each version directory.

---

## No Sunset / End of Life

All versions stay running indefinitely. There is no sunset mechanism, no deprecation dates, no 410 Gone responses. If a version exists in `MODULE.yaml`, it is served.

---

## Database & Schema Management

### Rules

1. **One PostgreSQL schema per module** — `module_<name>` (e.g., `module_ocr`)
2. **Shared across all major versions** — v1 and v2 read/write the same schema
3. **Additive-only changes** — add columns (with defaults), add tables, add indexes
4. **Never destructive** — no `DROP`, `RENAME`, or `ALTER TYPE` while any version uses the affected object
5. **Every new column has a `DEFAULT`** — older version code can INSERT without specifying it
6. **No `SELECT *`** — version code selects explicit columns so new columns don't break it

### Why Additive-Only

Both v1 and v2 run simultaneously against the same database schema. If v2 drops a column that v1 uses, v1 breaks. Additive-only guarantees that older versions keep working regardless of what newer versions add.

### Migration Files

Each version directory has a `schema/` folder with numbered SQL migration files:

```
v1/schema/
├── 001_initial.sql                # CREATE TABLE module_ocr.extractions (...)
├── 002_add_output_format.sql      # ALTER TABLE ... ADD COLUMN output_format VARCHAR DEFAULT 'plain'
└── current.sql                    # Full schema snapshot (for fresh installs)
```

```
v2/schema/
├── 001_add_pages_table.sql        # CREATE TABLE module_ocr.extraction_pages (...)
├── 002_add_source_column.sql      # ALTER TABLE ... ADD COLUMN source VARCHAR DEFAULT ''
└── current.sql                    # Full schema = v1 final state + v2 additions
```

### Migration Tracking

A tracking table records which migrations have been applied:

```sql
CREATE TABLE module_<name>._migrations (
    id SERIAL PRIMARY KEY,
    version_dir VARCHAR NOT NULL,     -- 'v1' or 'v2'
    filename VARCHAR NOT NULL,        -- '001_initial.sql'
    applied_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(version_dir, filename)
);
```

### Fresh Install vs. Upgrade

| Scenario | What runs |
|----------|-----------|
| Fresh install | `v1/schema/current.sql` then `v2/schema/current.sql` |
| Upgrade v1 (1.0 → 1.2) | Unapplied `v1/schema/00N_*.sql` files in order |
| Add v2 to existing v1 | All `v2/schema/00N_*.sql` files in order |

Migrations always run in order: all v1 migrations first, then v2 migrations. v2's schema builds on v1's final state.

---

## MODULE.yaml (Root)

```yaml
id: ocr
name: OCR Module
description: "Extract text from images and documents"
author: druppie-team
license: MIT
latest_version: "2.0.0"
versions:
  - "1.0.0"
  - "2.0.0"
infrastructure:
  port: 9010
  db_schema: module_ocr
```

Small file. Identity and version listing only. Tool schemas live in per-version manifests.

---

## manifest.yaml (Per-Version)

```yaml
# v1/manifest.yaml
version: "1.2.0"
tools:
  - name: extract_text
    description: "Extract text from an image or document"
    requires_approval: false
    input_schema:
      type: object
      properties:
        image_url:
          type: string
          description: "URL or path to the image"
        language:
          type: string
          default: "auto"
      required: [image_url]
    output_schema:
      type: object
      properties:
        text: { type: string }
        confidence: { type: number }
      required: [text, confidence]
```

```yaml
# v2/manifest.yaml
version: "2.0.0"
tools:
  - name: extract_text
    description: "Extract text from a document using URL, path, or base64 data"
    requires_approval: false
    input_schema:
      type: object
      properties:
        source:
          type: string
          description: "URL, file path, or base64 data of the document"
        language:
          type: string
          default: "auto"
        output_format:
          type: string
          enum: ["plain", "markdown", "html"]
          default: "plain"
      required: [source]
    output_schema:
      type: object
      properties:
        document:
          type: object
          properties:
            text: { type: string }
            format: { type: string }
            language: { type: string }
        confidence: { type: number }
        pages:
          type: array
          items:
            type: object
            properties:
              page_number: { type: integer }
              text: { type: string }
      required: [document, confidence]
```

---

## Decision Summary

| Decision | Choice |
|----------|--------|
| Code organization | Versioned subdirectories (`v1/`, `v2/`) |
| Version split depth | Major-only (minor/patch evolve in-place) |
| Shared vs. owned | Infrastructure shared (root), business logic owned per version |
| Manifests | Root MODULE.yaml for identity; per-version manifest.yaml for tool schemas |
| Routing | Path-based (`/v1/mcp`, `/v2/mcp`, `/mcp` → latest), no headers |
| Transformers | None — each version runs its own code |
| Sunset/EOL | None — all versions stay running |
| Database | One schema per module, shared across all major versions |
| DB changes | Additive-only, every column has a default, no `SELECT *` |
| Migrations | Numbered SQL files per version dir, tracking table |

---

## What This Replaces in module-specification.md

This design replaces:
- **Section 2** (File Structure) — new folder structure with version directories
- **Section 5** (Version System) — simplified: no version negotiation, no headers
- **Section 6** (Backwards Compatibility Layer) — removed entirely: no transformers
- **Section 12** (Complete Example) — updated to show versioned directory structure
- Parts of **Section 3** (MODULE.yaml) — split into root MODULE.yaml + per-version manifest.yaml
