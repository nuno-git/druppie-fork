# MCP Versioning & SBOM Implementation Plan

**Author:** Claude Code
**Date:** 2026-02-10
**Status:** Planning

---

## Executive Summary

This plan implements comprehensive MCP versioning and Software Bill of Materials (SBOM) generation for the Druppie AI agent governance platform. The solution uses **CycloneDX v1.6 in JSON format** to track all technologies, MCP servers, agents, and their dependencies with full version history.

### Key Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| **SBOM Format** | CycloneDX v1.6 JSON | Security-focused, ML-BOM support, service component type for MCPs |
| **Versioning** | Semantic Versioning (SemVer) | Industry standard (MAJOR.MINOR.PATCH) |
| **Storage** | PostgreSQL + filesystem | DB for queries, files for archival |
| **Component Types** | service (MCPs), framework (agents), library (dependencies) | Aligns with CycloneDX taxonomy |

---

## 1. Current State Analysis

### 1.1 What Exists Today

**Project Model** (`druppie/db/models/project.py`):
```python
class Project(Base):
    name: str
    description: str
    repo_url: str
    clone_url: str
    status: "active" | "archived"
    # NO version tracking
    # NO technology stack
    # NO SBOM data
```

**MCP Configuration** (`druppie/core/mcp_config.yaml`):
```yaml
mcps:
  coding:
    url: ${MCP_CODING_URL:-http://mcp-coding:9001}
    # NO version field
    # NO hash for verification
  docker:
    url: ${MCP_DOCKER_URL:-http://mcp-docker:9002}
```

**Agent Definitions** (`druppie/agents/definitions/*.yaml`):
```yaml
id: developer
name: Developer Agent
# NO version field
mcps:
  coding: [read_file, write_file, ...]
```

### 1.2 Gaps Identified

- ❌ No version tracking for MCP servers
- ❌ No version tracking for agent definitions
- ❌ No technology stack detection for projects
- ❌ No dependency tracking between components
- ❌ No SBOM generation or export capability
- ❌ No hash verification for integrity

---

## 2. Proposed Solution

### 2.1 Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    SBOM Generation Flow                     │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  1. CONFIG LAYER                                            │
│     ├─ mcp_config.yaml (add version, hash)                 │
│     └─ agent/*.yaml (add version)                          │
│              ↓                                              │
│  2. SERVICE LAYER                                           │
│     ├─ SbomGeneratorService                                │
│     │   ├─ load_mcp_configs()                              │
│     │   ├─ load_agent_definitions()                        │
│     │   ├─ detect_technologies()                           │
│     │   └─ generate_cyclonedx_sbom()                       │
│     └─ VersionTrackingService                              │
│         ├─ record_mcp_version()                            │
│         └─ record_agent_version()                          │
│              ↓                                              │
│  3. API LAYER                                               │
│     GET /api/sbom?scope={platform|project|session}         │
│     GET /api/projects/{id}/sbom                            │
│     GET /api/sessions/{id}/sbom                            │
│              ↓                                              │
│  4. STORAGE LAYER                                           │
│     ├─ Database (querying, history)                        │
│     └─ Filesystem (archival SBOMs)                         │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 CycloneDX Document Structure

```json
{
  "bomFormat": "CycloneDX",
  "specVersion": "1.6",
  "serialNumber": "urn:uuid:{uuid}",
  "version": 1,
  "metadata": {
    "timestamp": "2026-02-10T12:00:00Z",
    "tools": [{
      "vendor": "Druppie",
      "name": "druppie-sbom-generator",
      "version": "1.0.0"
    }],
    "component": {
      "type": "framework",
      "name": "druppie-agent-platform",
      "version": "0.1.0",
      "description": "AI Agent Governance Platform"
    }
  },
  "components": [
    {
      "type": "service",
      "name": "coding",
      "version": "1.0.0",
      "description": "MCP server for git and file operations",
      "group": "druppie.mcp-servers",
      "licenses": [{"license": {"id": "MIT"}}],
      "externalReferences": [{
        "type": "website",
        "url": "http://mcp-coding:9001"
      }],
      "properties": [
        {"name": "cdx:mcp:endpoint", "value": "http://mcp-coding:9001/mcp"},
        {"name": "cdx:mcp:transport", "value": "http"},
        {"name": "cdx:mcp:tools", "value": "read_file,write_file,commit_and_push"}
      ],
      "hashes": [{"alg": "SHA-256", "content": "abc123..."}]
    },
    {
      "type": "framework",
      "name": "developer",
      "version": "1.2.0",
      "description": "Developer agent for coding tasks",
      "group": "druppie.agents",
      "properties": [
        {"name": "cdx:druppie:model", "value": "glm-4"},
        {"name": "cdx:druppie:mcps", "value": "coding,docker,filesearch"}
      ]
    }
  ],
  "dependencies": [
    {
      "ref": "developer",
      "dependsOn": ["coding", "docker", "filesearch"]
    }
  ]
}
```

---

## 3. Database Schema Changes

### 3.1 New Tables

```python
# druppie/db/models/mcp_version.py

class MCPServerVersion(Base):
    """Track MCP server versions with hash verification."""
    __tablename__ = "mcp_server_versions"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False, unique=False)  # "coding"
    version = Column(String(50), nullable=False)  # "1.0.0"
    hash = Column(String(64))  # SHA-256 hex
    endpoint = Column(String(500))  # Full URL
    transport = Column(String(50))  # "http", "stdio"
    tools = Column(JSON)  # [{"name": "write_file", "version": "1.0.0"}]
    license_id = Column(String(50))  # SPDX license ID
    description = Column(Text)
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        Index('ix_mcp_version_name_version', 'name', 'version'),
    )


class AgentVersion(Base):
    """Track agent definition versions with hash verification."""
    __tablename__ = "agent_versions"

    id = Column(Integer, primary_key=True)
    agent_id = Column(String(100), nullable=False)  # "developer"
    version = Column(String(50), nullable=False)  # "1.2.0"
    definition_hash = Column(String(64))  # SHA-256 of YAML content
    name = Column(String(200))  # "Developer Agent"
    description = Column(Text)
    model = Column(String(100))  # "glm-4"
    temperature = Column(Float)
    max_tokens = Column(Integer)
    mcps = Column(JSON)  # {"coding": ["read_file", "write_file"]}
    approval_overrides = Column(JSON)  # Tool approval rules
    builtin_tools = Column(JSON)  # Extra builtin tools
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        Index('ix_agent_version_id_version', 'agent_id', 'version'),
    )


class ProjectTechnology(Base):
    """Track technology stack for projects."""
    __tablename__ = "project_technologies"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    language = Column(String(50))  # "python", "javascript"
    framework = Column(String(100))  # "fastapi", "react"
    package_manager = Column(String(50))  # "pip", "npm"
    dependencies = Column(JSON)  # [{"name": "fastapi", "version": "0.104.1"}]
    detected_at = Column(DateTime, server_default=func.now())

    project = relationship("Project", back_populates="technologies")


class SBOMRecord(Base):
    """Track SBOM generation history."""
    __tablename__ = "sbom_records"

    id = Column(Integer, primary_key=True)
    scope = Column(String(50), nullable=False)  # "platform", "project", "session"
    scope_id = Column(Integer)  # project_id or session_id (NULL for platform)
    format = Column(String(50), default="cyclonedx")  # "cyclonedx", "spdx"
    format_version = Column(String(10), default="1.6")  # "1.4", "1.5", "1.6"
    serial_number = Column(String(100), unique=True)  # "urn:uuid:..."
    file_path = Column(String(500))  # Path to stored SBOM file
    component_count = Column(Integer)  # Number of components
    generated_at = Column(DateTime, server_default=func.now())
    generated_by = Column(Integer, ForeignKey("users.id"))
```

### 3.2 Modify Existing Tables

```python
# druppie/db/models/project.py

class Project(Base):
    # ... existing fields ...

    # NEW FIELDS
    technology_stack = Column(JSON)  # Quick access tech summary
    last_sbom_id = Column(Integer, ForeignKey("sbom_records.id"))
    current_sbom = relationship("SBOMRecord", foreign_keys=[last_sbom_id])
    technologies = relationship("ProjectTechnology", back_populates="project")


# druppie/db/models/session.py

class Session(Base):
    # ... existing fields ...

    # NEW FIELDS
    sbom_record_id = Column(Integer, ForeignKey("sbom_records.id"))
    sbom_record = relationship("SBOMRecord")
    technologies_used = Column(JSON)  # Snapshot of tech used in session
```

---

## 4. Configuration Changes

### 4.1 MCP Config with Versioning

**File:** `druppie/core/mcp_config.yaml`

```yaml
mcps:
  coding:
    url: ${MCP_CODING_URL:-http://mcp-coding:9001}
    version: 1.0.0  # NEW
    hash: sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855  # NEW
    transport: http  # NEW
    license: MIT  # NEW
    description: "MCP server for git and file operations"  # NEW
    tools:
      read_file:
        version: 1.0.0  # Optional per-tool versioning
      write_file:
        version: 1.0.0
      batch_write_files:
        version: 1.0.0
      commit_and_push:
        version: 1.0.0

  docker:
    url: ${MCP_DOCKER_URL:-http://mcp-docker:9002}
    version: 1.0.0
    hash: sha256:...  # Calculate on first load
    transport: http
    license: MIT
    description: "MCP server for Docker container management"
    tools:
      build_image:
        version: 1.0.0
      run_container:
        version: 1.0.0

  bestand-zoeker:
    url: ${MCP_BESTAND_ZOEKER_URL:-http://mcp-bestand-zoeker:9005}
    version: 1.0.0
    hash: sha256:...
    transport: http
    license: MIT
    description: "MCP server for file search and web browsing"
```

### 4.2 Agent Definitions with Versioning

**File:** `druppie/agents/definitions/developer.yaml`

```yaml
id: developer
version: 1.2.0  # NEW - SemVer
name: Developer Agent
description: "Developer agent for coding tasks, builds, and deployment"
model: glm-4
temperature: 0.7
max_tokens: 2000

# MCP access - unchanged structure
mcps:
  coding:
    - read_file
    - write_file
    - batch_write_files
    - commit_and_push
  docker:
    - build_image
    - run_container
  bestand-zoeker:
    - search_files
    - list_directory

# Approval overrides - unchanged
approval_overrides:
  auto_approve:
    - read_file
    - search_files
    - list_directory

  require_approval:
    - write_file
    - delete_file
    - run_container

# Extra builtin tools - unchanged
builtin_tools:
  - ask_question
  - ask_multiple_choice_question
```

---

## 5. Service Layer

### 5.1 SBOM Generator Service

**File:** `druppie/services/sbom_generator.py`

```python
"""Service for generating CycloneDX SBOM documents."""

import hashlib
import json
import uuid
from datetime import datetime
from typing import Literal

from cyclonedx.model import Bom
from cyclonedx.model.component import Component, ComponentType
from cyclonedx.model.dependency import Dependency
from cyclonedx.model.tool import Tool
from cyclonedx.output import get_instance

from druppie.core.mcp_config import MCPConfig
from druppie.domain.agent import AgentDefinition
from druppie.repositories.mcp_repository import MCPRepository
from druppie.repositories.agent_repository import AgentRepository


class SbomGeneratorService:
    """Generate CycloneDX SBOMs for platform, projects, and sessions."""

    def __init__(
        self,
        mcp_repository: MCPRepository,
        agent_repository: AgentRepository
    ):
        self.mcp_repository = mcp_repository
        self.agent_repository = agent_repository

    def generate_sbom(
        self,
        scope: Literal["platform", "project", "session"] = "platform",
        scope_id: int | None = None,
        format_version: str = "1.6"
    ) -> dict:
        """
        Generate CycloneDX SBOM in JSON format.

        Args:
            scope: "platform", "project", or "session"
            scope_id: project_id or session_id (None for platform)
            format_version: CycloneDX spec version (1.4, 1.5, 1.6)

        Returns:
            CycloneDX JSON document as dict
        """
        # Create BOM
        bom = Bom()
        serial_number = f"urn:uuid:{uuid.uuid4()}"

        # Add metadata
        bom.metadata.tools = [
            Tool(
                vendor="Druppie",
                name="druppie-sbom-generator",
                version="1.0.0"
            )
        ]
        bom.metadata.timestamp = datetime.utcnow()

        # Add root component (the platform itself)
        root_component = Component(
            name="druppie-agent-platform",
            type=ComponentType.Framework,
            version="0.1.0",
            description="AI Agent Governance Platform with MCP Tools"
        )
        bom.metadata.component = root_component

        # Add MCP server components
        mcp_configs = self.mcp_repository.get_all_active()
        for mcp_config in mcp_configs:
            component = self._mcp_to_component(mcp_config)
            bom.components.add(component)

            # Add dependency from root to MCP
            bom.dependencies.add(
                Dependency(ref=root_component, depends_on=[component])
            )

        # Add agent components
        agents = self.agent_repository.get_all_active()
        for agent in agents:
            component = self._agent_to_component(agent)
            bom.components.add(component)

            # Add dependency from root to agent
            bom.dependencies.add(
                Dependency(ref=root_component, depends_on=[component])
            )

            # Add agent's dependency on MCPs
            if agent.mcps:
                mcp_refs = [
                    bom.get_component_by_name(mcp_name)
                    for mcp_name in agent.mcps.keys()
                ]
                bom.dependencies.add(
                    Dependency(ref=component, depends_on=mcp_refs)
                )

        # Output as JSON
        output = get_instance(bom, format_version=format_version)
        return json.loads(output.output_as_json())

    def _mcp_to_component(self, mcp_config: MCPConfig) -> Component:
        """Convert MCP config to CycloneDX component."""
        component = Component(
            name=mcp_config.name,
            type=ComponentType.Service,  # MCPs are services
            version=mcp_config.version,
            description=mcp_config.description,
            group="druppie.mcp-servers"
        )

        # Add license
        if mcp_config.license:
            component.licenses = [mcp_config.license]

        # Add hash
        if mcp_config.hash:
            component.hashes = [mcp_config.hash]

        # Add external reference (endpoint URL)
        if mcp_config.endpoint:
            component.external_references = [
                {"type": "website", "url": mcp_config.endpoint}
            ]

        # Add MCP-specific properties
        properties = [
            {"name": "cdx:mcp:endpoint", "value": mcp_config.endpoint},
            {"name": "cdx:mcp:transport", "value": mcp_config.transport or "http"},
        ]

        # Add tools list
        if mcp_config.tools:
            tool_names = ",".join(mcp_config.tools.keys())
            properties.append({
                "name": "cdx:mcp:tools",
                "value": tool_names
            })

        component.properties = properties
        return component

    def _agent_to_component(self, agent: AgentDefinition) -> Component:
        """Convert agent definition to CycloneDX component."""
        component = Component(
            name=agent.id,
            type=ComponentType.Framework,  # Agents are frameworks
            version=agent.version,
            description=agent.description,
            group="druppie.agents"
        )

        # Add properties
        properties = [
            {"name": "cdx:druppie:model", "value": agent.model},
            {"name": "cdx:druppie:temperature", "value": str(agent.temperature)},
        ]

        # Add MCP access list
        if agent.mcps:
            mcp_list = ",".join(agent.mcps.keys())
            properties.append({
                "name": "cdx:druppie:mcps",
                "value": mcp_list
            })

        component.properties = properties
        return component

    def calculate_file_hash(self, file_path: str) -> str:
        """Calculate SHA-256 hash of a file."""
        sha256 = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                sha256.update(chunk)
        return f"sha256:{sha256.hexdigest()}"
```

### 5.2 Version Tracking Service

**File:** `druppie/services/version_tracking.py`

```python
"""Service for tracking MCP and agent versions."""

from typing import Optional

from sqlalchemy.orm import Session

from druppie.db.models.mcp_version import MCPServerVersion
from druppie.db.models.agent_version import AgentVersion
from druppie.core.mcp_config import MCPConfig
from druppie.domain.agent import AgentDefinition


class VersionTrackingService:
    """Track and manage versions of MCP servers and agents."""

    def __init__(self, db: Session):
        self.db = db

    def record_mcp_version(
        self,
        mcp_config: MCPConfig,
        definition_hash: str
    ) -> MCPServerVersion:
        """Record or update MCP server version."""
        # Check if version already exists
        existing = (
            self.db.query(MCPServerVersion)
            .filter(
                MCPServerVersion.name == mcp_config.name,
                MCPServerVersion.version == mcp_config.version
            )
            .first()
        )

        if existing:
            return existing

        # Create new version record
        mcp_version = MCPServerVersion(
            name=mcp_config.name,
            version=mcp_config.version,
            hash=definition_hash,
            endpoint=mcp_config.url,
            transport=mcp_config.transport,
            tools=mcp_config.tools,
            license_id=mcp_config.license,
            description=mcp_config.description,
            active=True
        )

        self.db.add(mcp_version)
        self.db.commit()
        self.db.refresh(mcp_version)
        return mcp_version

    def record_agent_version(
        self,
        agent: AgentDefinition,
        definition_hash: str
    ) -> AgentVersion:
        """Record or update agent definition version."""
        # Check if version already exists
        existing = (
            self.db.query(AgentVersion)
            .filter(
                AgentVersion.agent_id == agent.id,
                AgentVersion.version == agent.version
            )
            .first()
        )

        if existing:
            return existing

        # Create new version record
        agent_version = AgentVersion(
            agent_id=agent.id,
            version=agent.version,
            definition_hash=definition_hash,
            name=agent.name,
            description=agent.description,
            model=agent.model,
            temperature=agent.temperature,
            max_tokens=agent.max_tokens,
            mcps=agent.mcps,
            approval_overrides=agent.approval_overrides,
            builtin_tools=agent.builtin_tools,
            active=True
        )

        self.db.add(agent_version)
        self.db.commit()
        self.db.refresh(agent_version)
        return agent_version
```

---

## 6. API Layer

### 6.1 SBOM Routes

**File:** `druppie/api/routes/sbom.py`

```python
"""API routes for SBOM export and management."""

from fastapi import APIRouter, Query, Depends, HTTPException
from fastapi.responses import JSONResponse

from druppie.api.dependencies import get_current_user, get_db
from druppie.services.sbom_generator import SbomGeneratorService
from druppie.repositories.sbom_repository import SBOMRepository

router = APIRouter(prefix="/api/sbom", tags=["sbom"])


@router.get("")
async def export_sbom(
    scope: str = Query("platform", enum=["platform", "project", "session"]),
    scope_id: int | None = Query(None, description="project_id or session_id"),
    format: str = Query("cyclonedx", enum=["cyclonedx", "spdx"]),
    version: str = Query("1.6", enum=["1.4", "1.5", "1.6"]),
    current_user = Depends(get_current_user),
    db = Depends(get_db)
):
    """
    Export SBOM in CycloneDX or SPDX format.

    - **scope**: platform, project, or session
    - **scope_id**: required for project/session scope
    - **format**: cyclonedx (recommended) or spdx
    - **version**: CycloneDX spec version (1.4, 1.5, 1.6)
    """
    # Validate scope_id
    if scope in ["project", "session"] and scope_id is None:
        raise HTTPException(
            status_code=400,
            detail=f"scope_id required for {scope} scope"
        )

    # Generate SBOM
    sbom_repo = SBOMRepository(db)
    generator = SbomGeneratorService(
        mcp_repository=sbom_repo.get_mcp_repository(),
        agent_repository=sbom_repo.get_agent_repository()
    )

    sbom_data = generator.generate_sbom(
        scope=scope,
        scope_id=scope_id,
        format_version=version
    )

    # Record SBOM generation
    sbom_repo.record_generation(
        scope=scope,
        scope_id=scope_id,
        format=format,
        format_version=version,
        serial_number=sbom_data["serialNumber"],
        component_count=len(sbom_data.get("components", [])),
        user_id=current_user.id
    )

    return JSONResponse(
        content=sbom_data,
        media_type="application/json"
    )


@router.get("/history")
async def list_sbom_history(
    scope: str | None = Query(None, enum=["platform", "project", "session"]),
    scope_id: int | None = Query(None),
    limit: int = Query(10, ge=1, le=100),
    current_user = Depends(get_current_user),
    db = Depends(get_db)
):
    """List historical SBOM records."""
    sbom_repo = SBOMRepository(db)
    records = sbom_repo.list_history(
        scope=scope,
        scope_id=scope_id,
        limit=limit
    )
    return records


@router.get("/projects/{project_id}")
async def get_project_sbom(
    project_id: int,
    version: str = Query("1.6", enum=["1.4", "1.5", "1.6"]),
    current_user = Depends(get_current_user),
    db = Depends(get_db)
):
    """Get latest SBOM for a specific project."""
    # Implementation...
    pass


@router.get("/sessions/{session_id}")
async def get_session_sbom(
    session_id: int,
    version: str = Query("1.6", enum=["1.4", "1.5", "1.6"]),
    current_user = Depends(get_current_user),
    db = Depends(get_db)
):
    """Get SBOM for a specific session."""
    # Implementation...
    pass
```

---

## 7. Domain Models

**File:** `druppie/domain/sbom.py`

```python
"""Domain models for SBOM data."""

from pydantic import BaseModel
from typing import Optional, Literal
from datetime import datetime


class SBOMMetadata(BaseModel):
    """Metadata about an SBOM document."""
    serial_number: str
    timestamp: datetime
    format: Literal["cyclonedx", "spdx"]
    format_version: str
    component_count: int


class MCPComponentSummary(BaseModel):
    """Summary of MCP server component."""
    name: str
    version: str
    description: Optional[str]
    endpoint: str
    transport: str
    tool_count: int


class AgentComponentSummary(BaseModel):
    """Summary of agent component."""
    id: str
    version: str
    name: str
    description: Optional[str]
    model: str
    mcp_count: int


class SBOMSummary(BaseModel):
    """Summary view of SBOM."""
    metadata: SBOMMetadata
    mcp_components: list[MCPComponentSummary]
    agent_components: list[AgentComponentSummary]


class TechnologyStack(BaseModel):
    """Technology stack for a project."""
    language: str
    framework: Optional[str]
    package_manager: Optional[str]
    dependencies: list[dict]
```

---

## 8. Implementation Phases

### Phase 1: Foundation (Week 1)

**Goal:** Add version fields to configuration files

**Tasks:**
1. ✅ Add `version` and `hash` fields to `mcp_config.yaml`
2. ✅ Add `version` field to all agent YAML definitions
3. ✅ Update `MCPConfig` class to parse version fields
4. ✅ Update `AgentDefinition` domain model to include version
5. ✅ Add `cyclonedx-python-lib` to `requirements.txt`

**Deliverables:**
- Updated configuration files with versions
- Modified config loading classes

### Phase 2: Database Schema (Week 1)

**Goal:** Create tables for version tracking

**Tasks:**
1. ✅ Create `MCPServerVersion` model
2. ✅ Create `AgentVersion` model
3. ✅ Create `ProjectTechnology` model
4. ✅ Create `SBOMRecord` model
5. ✅ Add relationships to `Project` and `Session`
6. ✅ Reset database (no migrations per project rules)

**Deliverables:**
- New SQLAlchemy models
- Database reset script

### Phase 3: Service Layer (Week 2)

**Goal:** Implement SBOM generation logic

**Tasks:**
1. ✅ Create `SbomGeneratorService`
2. ✅ Implement `generate_cyclonedx_sbom()`
3. ✅ Create `VersionTrackingService`
4. ✅ Implement component serialization
5. ✅ Add hash calculation utilities
6. ✅ Create repository classes for MCP/Agent versions

**Deliverables:**
- Working SBOM generation service
- Unit tests for SBOM structure

### Phase 4: API Layer (Week 2)

**Goal:** Expose SBOM endpoints

**Tasks:**
1. ✅ Create `druppie/api/routes/sbom.py`
2. ✅ Implement `GET /api/sbom` endpoint
3. ✅ Implement `GET /api/sbom/history` endpoint
4. ✅ Implement `GET /api/projects/{id}/sbom` endpoint
5. ✅ Add authentication/authorization
6. ✅ Add error handling

**Deliverables:**
- Working SBOM export API
- API documentation

### Phase 5: Technology Detection (Week 3)

**Goal:** Auto-detect project technology stacks

**Tasks:**
1. ✅ Create technology detection service
2. ✅ Implement language detection (file extensions)
3. ✅ Implement framework detection (config files)
4. ✅ Implement dependency parsing (package.json, requirements.txt)
5. ✅ Add technology recording to agent execution flow

**Deliverables:**
- Technology detection service
- Database population on project builds

### Phase 6: Frontend Integration (Week 3-4)

**Goal:** Display SBOM data in UI

**Tasks:**
1. ✅ Create SBOM viewer page
2. ✅ Add SBOM download button to project settings
3. ✅ Display version information for MCPs
4. ✅ Display version information for agents
5. ✅ Show technology stack for projects
6. ✅ Add dependency graph visualization

**Deliverables:**
- React components for SBOM display
- Download/export functionality

### Phase 7: Testing & Documentation (Week 4)

**Goal:** Ensure quality and usability

**Tasks:**
1. ✅ Write unit tests for services
2. ✅ Write integration tests for API
3. ✅ Write E2E tests with Playwright
4. ✅ Update CLAUDE.md with SBOM commands
5. ✅ Create user documentation
6. ✅ Create API documentation

**Deliverables:**
- Test suite
- Documentation

---

## 9. Dependencies

### Python Packages

Add to `druppie/requirements.txt`:

```
cyclonedx-python-lib==8.0.0
packageurl-python==0.15.0
```

### Development Dependencies

Add to `druppie/requirements-dev.txt`:

```
pytest-cyclonedx==0.1.0
```

---

## 10. Testing Strategy

### Unit Tests

```python
# tests/services/test_sbom_generator.py

def test_generate_platform_sbom():
    """Test platform SBOM generation."""
    service = SbomGeneratorService(mcp_repo, agent_repo)
    sbom = service.generate_sbom(scope="platform")

    assert sbom["bomFormat"] == "CycloneDX"
    assert sbom["specVersion"] == "1.6"
    assert len(sbom["components"]) > 0


def test_mcp_to_component_conversion():
    """Test MCP config to CycloneDX component."""
    mcp_config = MCPConfig(
        name="coding",
        version="1.0.0",
        url="http://mcp-coding:9001"
    )
    component = service._mcp_to_component(mcp_config)

    assert component.type == ComponentType.Service
    assert component.name == "coding"
    assert component.version == "1.0.0"
```

### Integration Tests

```python
# tests/api/test_sbom_routes.py

def test_export_sbom_platform(client, auth_headers):
    """Test SBOM export API."""
    response = client.get(
        "/api/sbom?scope=platform",
        headers=auth_headers
    )

    assert response.status_code == 200
    data = response.json()
    assert "components" in data
```

### E2E Tests

```typescript
// frontend/tests/e2e/sbom.spec.ts

test('should display SBOM for platform', async ({ page }) => {
  await page.goto('/settings/sbom');
  await page.waitForSelector('text=CycloneDX SBOM');

  // Check MCP components are displayed
  await expect(page.locator('text=coding')).toBeVisible();
  await expect(page.locator('text=1.0.0')).toBeVisible();

  // Test download
  const downloadPromise = page.waitForEvent('download');
  await page.click('button:has-text("Download SBOM")');
  const download = await downloadPromise;
});
```

---

## 11. Security Considerations

### 11.1 Hash Verification

All MCP servers and agent definitions must include SHA-256 hashes:

```python
def verify_component_integrity(component: Component, expected_hash: str) -> bool:
    """Verify component hasn't been tampered with."""
    actual_hash = calculate_file_hash(component.source_file)
    return actual_hash == expected_hash
```

### 11.2 Access Control

SBOM export endpoints respect existing role-based access:

- **admin**: Full access to all SBOMs
- **architect**: Read-only access to platform SBOM
- **developer**: Access to project SBOMs they own
- **analyst**: Read-only access to project SBOMs
- **user**: No SBOM access

### 11.3 SBOM Storage

- Store SBOMs in `druppie/sboms/` with restricted permissions
- Keep latest 10 SBOMs for historical tracking
- Archive old SBOMs to cold storage

---

## 12. Performance Considerations

### Caching Strategy

- Cache platform SBOM for 5 minutes (MCPs/agents change infrequently)
- Cache project SBOM for 1 hour (unless new build detected)
- Invalidate cache on MCP/agent version updates

### Database Indexing

```python
# Critical indexes for SBOM queries
Index('ix_sbom_scope_id', SBOMRecord.scope, SBOMRecord.scope_id)
Index('ix_mcp_name_version', MCPServerVersion.name, MCPServerVersion.version)
Index('ix_agent_id_version', AgentVersion.agent_id, AgentVersion.version)
```

---

## 13. Monitoring & Observability

### Metrics to Track

1. SBOM generation count (by scope, user)
2. SBOM generation latency
3. Component count per SBOM
4. Version change frequency
5. Technology detection accuracy

### Logging

```python
logger.info(
    "SBOM generated",
    extra={
        "scope": scope,
        "scope_id": scope_id,
        "component_count": len(components),
        "user_id": user.id,
        "duration_ms": duration
    }
)
```

---

## 14. Rollout Plan

### Stage 1: Internal Testing (Week 5)
- Deploy to dev environment
- Generate SBOMs for existing projects
- Validate data integrity
- Fix bugs

### Stage 2: Beta Testing (Week 6)
- Deploy to staging environment
- Invite select users to test
- Gather feedback
- Iterate on UX

### Stage 3: Production Release (Week 7)
- Deploy to production
- Monitor performance
- Enable feature flags
- Update documentation

### Stage 4: Enhancement (Week 8+)
- Add vulnerability scanning integration
- Implement dependency update notifications
- Create SBOM diff view
- Add compliance reporting

---

## 15. Success Criteria

### Functional Requirements
- ✅ Generate CycloneDX v1.6 SBOMs for platform/projects/sessions
- ✅ Track semantic versions for all MCP servers
- ✅ Track semantic versions for all agent definitions
- ✅ Auto-detect technology stack for projects
- ✅ Export SBOMs via REST API
- ✅ Display SBOM data in frontend

### Non-Functional Requirements
- ✅ SBOM generation completes in < 2 seconds
- ✅ API responses have < 100ms latency (cached)
- ✅ Hash verification for all components
- ✅ Role-based access control
- ✅ Full test coverage (> 80%)

### Business Outcomes
- ✅ Transparency into AI agent dependencies
- ✅ Compliance with SBOM regulations (CISA 2025)
- ✅ Security audit capabilities
- ✅ Supply chain risk management

---

## 16. Open Questions

1. **Should we automatically detect MCP/agent version changes?**
   - Proposal: Yes, watch config files for changes

2. **Should SBOMs be versioned themselves?**
   - Proposal: Yes, auto-increment on each generation

3. **Should we support SPDX format?**
   - Proposal: Phase 2 feature (CycloneDX is priority)

4. **How should we handle deprecated MCPs/agents?**
   - Proposal: Mark `active=False` but keep in history

5. **Should we integrate vulnerability scanning?**
   - Proposal: Yes, use OSV or GitHub Advisory Database in Phase 2

---

## 17. References

### Standards
- [CycloneDX Specification v1.6](https://cyclonedx.org/capabilities/overview/)
- [CISA 2025 SBOM Minimum Elements](https://www.cisa.gov/sbom)
- [SPDX v3.0.1](https://spdx.dev/wp-content/uploads/sites/31/2024/12/SPDX-3.0.1-1.pdf)

### MCP Versioning
- [MCP Registry Versioning Guide](https://modelcontextprotocol.io/registry/versioning)
- [MCP Best Practices](https://steipete.me/posts/2025/mcp-best-practices)

### Tools
- [cyclonedx-python-lib](https://github.com/CycloneDX/cyclonedx-python-lib)
- [Microsoft SBOM Tool](https://github.com/microsoft/sbom-tool)

---

## Appendix A: Example SBOM Output

See section 2.2 for complete CycloneDX JSON structure example.

## Appendix B: Migration Script

Since this project doesn't use migrations, use database reset:

```bash
docker compose --profile reset-db run --rm reset-db
```

## Appendix C: API Examples

```bash
# Get platform SBOM
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/sbom?scope=platform&format=cyclonedx&version=1.6"

# Get project SBOM
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/sbom?scope=project&scope_id=1"

# Get SBOM history
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/sbom/history?limit=20"
```

---

**Document Version:** 1.0
**Last Updated:** 2026-02-10
**Status:** Ready for Review
