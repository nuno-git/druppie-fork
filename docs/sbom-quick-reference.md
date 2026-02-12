# SBOM Implementation Quick Reference

**For developers working on MCP versioning and SBOM generation**

---

## Quick Start

### 1. Add Version to MCP Config

```yaml
# druppie/core/mcp_config.yaml
mcps:
  coding:
    url: ${MCP_CODING_URL:-http://mcp-coding:9001}
    version: 1.0.0                    # NEW
    hash: sha256:abc123...            # NEW - calculate once
    transport: http                   # NEW
    license: MIT                      # NEW
    description: "MCP server for git" # NEW
```

### 2. Add Version to Agent Definition

```yaml
# druppie/agents/definitions/developer.yaml
id: developer
version: 1.2.0                        # NEW - SemVer
name: Developer Agent
# ... rest of definition
```

### 3. Generate SBOM

```bash
# Platform SBOM
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/sbom?scope=platform" \
  -o sbom-platform.json

# Project SBOM
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/sbom?scope=project&scope_id=1" \
  -o sbom-project-1.json

# Session SBOM
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/sbom?scope=session&scope_id=42" \
  -o sbom-session-42.json
```

### 4. Reset Database (after schema changes)

```bash
docker compose --profile reset-db run --rm reset-db
```

---

## Semantic Versioning (SemVer)

Format: `MAJOR.MINOR.PATCH`

### When to Bump Versions

| Change | Example | Version Bump |
|--------|---------|--------------|
| **Incompatible changes** | Remove tool, change signature | `1.0.0` → `2.0.0` |
| **New features** | Add new tool | `1.0.0` → `1.1.0` |
| **Bug fixes** | Fix tool behavior | `1.0.0` → `1.0.1` |

### MCP Server Version Examples

```
1.0.0 - Initial release with read_file, write_file
1.1.0 - Add commit_and_push tool
2.0.0 - Remove write_file (breaking change)
2.0.1 - Fix commit_and_push bug
```

### Agent Definition Version Examples

```
1.0.0 - Initial developer agent
1.1.0 - Add docker MCP access
1.2.0 - Update system prompt
2.0.0 - Change from glm-4 to gpt-4 (model change)
```

---

## CycloneDX Component Types

```python
from cyclonedx.model.component import ComponentType

# MCP servers → Service
ComponentType.Service

# Agents → Framework
ComponentType.Framework

# Dependencies → Library (default)
ComponentType.Library

# Platform/Frameworks → Framework
ComponentType.Framework
```

---

## Common Tasks

### Calculate File Hash

```python
import hashlib

def calculate_hash(file_path: str) -> str:
    """Calculate SHA-256 hash of a file."""
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            sha256.update(chunk)
    return f"sha256:{sha256.hexdigest()}"

# Usage
hash = calculate_hash("druppie/core/mcp_config.yaml")
```

### Create SBOM Component

```python
from cyclonedx.model.component import Component, ComponentType

component = Component(
    name="coding",
    type=ComponentType.Service,
    version="1.0.0",
    description="MCP server for git operations",
    group="druppie.mcp-servers"
)

# Add properties
component.properties = [
    {"name": "cdx:mcp:endpoint", "value": "http://mcp-coding:9001"},
    {"name": "cdx:mcp:transport", "value": "http"}
]
```

### Record Version in Database

```python
from druppie.services.version_tracking import VersionTrackingService

service = VersionTrackingService(db)

# Record MCP version
mcp_version = service.record_mcp_version(
    mcp_config=mcp_config,
    definition_hash="sha256:abc123..."
)

# Record agent version
agent_version = service.record_agent_version(
    agent=agent_definition,
    definition_hash="sha256:def456..."
)
```

---

## File Locations

```
druppie/
├── core/
│   └── mcp_config.yaml              # MCP configs with versions
│
├── agents/
│   └── definitions/
│       ├── developer.yaml           # Agent defs with versions
│       ├── planner.yaml
│       └── ...
│
├── db/
│   └── models/
│       ├── mcp_version.py           # MCPServerVersion model
│       ├── agent_version.py         # AgentVersion model
│       └── sbom.py                  # SBOMRecord, ProjectTechnology
│
├── domain/
│   └── sbom.py                      # SBOM domain models
│
├── services/
│   ├── sbom_generator.py            # SBOM generation logic
│   └── version_tracking.py          # Version tracking logic
│
├── api/
│   └── routes/
│       └── sbom.py                  # SBOM API endpoints
│
├── repositories/
│   ├── mcp_repository.py            # MCP data access
│   └── sbom_repository.py           # SBOM data access
│
└── sboms/                           # Archived SBOM files
    ├── sbom-platform-20250210.json
    └── sbom-project-1-20250210.json
```

---

## API Endpoints

### Export SBOM

```python
GET /api/sbom
Query Parameters:
  - scope: "platform" | "project" | "session"
  - scope_id: int (required for project/session)
  - format: "cyclonedx" | "spdx"
  - version: "1.4" | "1.5" | "1.6"

Response: CycloneDX JSON document
```

### Get SBOM History

```python
GET /api/sbom/history
Query Parameters:
  - scope: "platform" | "project" | "session" (optional)
  - scope_id: int (optional)
  - limit: int (default: 10, max: 100)

Response: List of SBOMRecord summaries
```

### Get Project SBOM

```python
GET /api/projects/{project_id}/sbom
Query Parameters:
  - version: "1.4" | "1.5" | "1.6"

Response: Project-specific CycloneDX JSON
```

---

## Database Queries

### Get Active MCP Versions

```python
from druppie.db.models.mcp_version import MCPServerVersion

active_mcps = (
    db.query(MCPServerVersion)
    .filter(MCPServerVersion.active == True)
    .order_by(MCPServerVersion.name, MCPServerVersion.created_at.desc())
    .all()
)
```

### Get Latest Agent Version

```python
from druppie.db.models.agent_version import AgentVersion

latest_developer = (
    db.query(AgentVersion)
    .filter(
        AgentVersion.agent_id == "developer",
        AgentVersion.active == True
    )
    .order_by(AgentVersion.created_at.desc())
    .first()
)
```

### Get Project Technology Stack

```python
from druppie.db.models.sbom import ProjectTechnology

tech_stack = (
    db.query(ProjectTechnology)
    .filter(ProjectTechnology.project_id == project_id)
    .order_by(ProjectTechnology.detected_at.desc())
    .first()
)
```

---

## Testing

### Unit Test: SBOM Generation

```python
def test_generate_platform_sbom(db_session):
    """Test platform SBOM generation."""
    # Setup
    generator = SbomGeneratorService(mcp_repo, agent_repo)

    # Execute
    sbom = generator.generate_sbom(scope="platform")

    # Assert
    assert sbom["bomFormat"] == "CycloneDX"
    assert sbom["specVersion"] == "1.6"
    assert "serialNumber" in sbom
    assert len(sbom["components"]) > 0
    assert any(c["name"] == "coding" for c in sbom["components"])
```

### Integration Test: API Endpoint

```python
def test_export_sbom_api(client, auth_headers):
    """Test SBOM export API endpoint."""
    response = client.get(
        "/api/sbom?scope=platform",
        headers=auth_headers
    )

    assert response.status_code == 200
    data = response.json()
    assert "components" in data
    assert "dependencies" in data
```

### E2E Test: Frontend Download

```typescript
test('download platform SBOM', async ({ page }) => {
  await page.goto('/settings/sbom');

  const downloadPromise = page.waitForEvent('download');
  await page.click('button:has-text("Download SBOM")');
  const download = await downloadPromise;

  expect(download.suggestedFilename()).toMatch(/sbom-platform.*\.json/);
});
```

---

## CycloneDX Properties Reference

### Standard MCP Properties

```python
# Endpoint URL
{"name": "cdx:mcp:endpoint", "value": "http://mcp-coding:9001/mcp"}

# Transport protocol
{"name": "cdx:mcp:transport", "value": "http"}

# Available tools (comma-separated)
{"name": "cdx:mcp:tools", "value": "read_file,write_file,commit"}
```

### Druppie-Specific Properties

```python
# Is this a builtin tool?
{"name": "cdx:druppie:builtin", "value": "false"}

# Approval requirement
{"name": "cdx:druppie:approval", "value": "require_approval"}

# Required role for approval
{"name": "cdx:druppie:approval:role", "value": "developer"}

# LLM model for agents
{"name": "cdx:druppie:model", "value": "glm-4"}

# Temperature setting
{"name": "cdx:druppie:temperature", "value": "0.7"}

# MCPs used by agent
{"name": "cdx:druppie:mcps", "value": "coding,docker,filesearch"}
```

---

## Troubleshooting

### SBOM Missing Components

**Problem:** SBOM doesn't include expected MCPs or agents.

**Solutions:**
1. Check versions are set in config files
2. Verify `active=True` in database
3. Check MCP config loading: `MCPConfig.load()`
4. Check agent definition loading: `AgentDefinition.load()`

### Hash Verification Fails

**Problem:** Component hash doesn't match stored hash.

**Solutions:**
1. Recalculate hash: `calculate_hash(file_path)`
2. Update config with new hash
3. Check for file modifications

### API Returns 401 Unauthorized

**Problem:** Can't access SBOM endpoint.

**Solutions:**
1. Check authentication token is valid
2. Verify user has appropriate role
3. Check RBAC rules in API route

---

## Performance Tips

### Cache Platform SBOM

```python
from functools import lru_cache

@lru_cache(maxsize=1, timeout=300)  # 5 minutes
def get_platform_sbom():
    return generator.generate_sbom(scope="platform")
```

### Optimize Database Queries

```python
# Use joinedload for relationships
from sqlalchemy.orm import joinedload

versions = (
    db.query(MCPServerVersion)
    .options(joinedload(MCPServerVersion.tools))
    .all()
)
```

### Index Critical Columns

```python
# In model
__table_args__ = (
    Index('ix_sbom_scope_id', SBOMRecord.scope, SBOMRecord.scope_id),
)
```

---

## Resources

- [CycloneDX Specification](https://cyclonedx.org/capabilities/overview/)
- [CycloneDX Python Lib](https://github.com/CycloneDX/cyclonedx-python-lib)
- [MCP Registry Versioning](https://modelcontextprotocol.io/registry/versioning)
- [CISA SBOM Guidelines](https://www.cisa.gov/sbom)

---

## Checklist

- [ ] Add versions to all MCP configs
- [ ] Add versions to all agent definitions
- [ ] Calculate SHA-256 hashes
- [ ] Create database models
- [ ] Reset database
- [ ] Implement SbomGeneratorService
- [ ] Implement VersionTrackingService
- [ ] Create API endpoints
- [ ] Write tests
- [ ] Update frontend
- [ ] Document API
- [ ] Deploy to dev

---

**Last Updated:** 2026-02-10
