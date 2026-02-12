# SBOM Architecture Diagrams

## 1. System Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              DRUPPIE PLATFORM                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌──────────────────┐      ┌──────────────────┐      ┌──────────────────┐  │
│  │   CONFIG LAYER   │      │   SERVICE LAYER  │      │    API LAYER     │  │
│  ├──────────────────┤      ├──────────────────┤      ├──────────────────┤  │
│  │                  │      │                  │      │                  │  │
│  │ ┌──────────────┐ │      │ ┌──────────────┐ │      │ ┌──────────────┐ │  │
│  │ │mcp_config    │ │      │ │SbomGenerator │ │      │ │GET /api/sbom │ │  │
│  │ │.yaml         │ │      │ │Service       │ │      │ │              │ │  │
│  │ │              │ │──────▶││              │ │──────▶││              │ │  │
│  │ │+ version     │ │      │ │+ generate()  │ │      │ │+ export()    │ │  │
│  │ │+ hash        │ │      │ │+ _mcp_to_comp│ │      │ │+ history()   │ │  │
│  │ └──────────────┘ │      │ └──────────────┘ │      │ └──────────────┘ │  │
│  │                  │      │                  │      │                  │  │
│  │ ┌──────────────┐ │      │ ┌──────────────┐ │      │ ┌──────────────┐ │  │
│  │ │agent/        │ │      │ │VersionTrack  │ │      │ │GET /api/     │ │  │
│  │ │definitions/  │ │      │ │Service       │ │      │ │ projects/:id │ │  │
│  │ │*.yaml        │ │      │ │              │ │      │ │ /sbom        │ │  │
│  │ │              │ │──────▶││+ record_mcp()│ │      │ │              │ │  │
│  │ │+ version     │ │      │ │+ record_agent│ │      │ │              │ │  │
│  │ └──────────────┘ │      │ └──────────────┘ │      │ └──────────────┘ │  │
│  └──────────────────┘      └──────────────────┘      └──────────────────┘  │
│           │                         │                         │            │
└───────────┼─────────────────────────┼─────────────────────────┼────────────┘
            │                         │                         │
            ▼                         ▼                         ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           STORAGE LAYER                                     │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │                        POSTGRESQL DATABASE                            │  │
│  ├──────────────────────────────────────────────────────────────────────┤  │
│  │                                                                      │  │
│  │  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐   │  │
│  │  │MCP Server        │  │Agent Version     │  │SBOM Record       │   │  │
│  │  │Versions          │  │                  │  │                  │   │  │
│  │  ├──────────────────┤  ├──────────────────┤  ├──────────────────┤   │  │
│  │  │• name            │  │• agent_id        │  │• scope           │   │  │
│  │  │• version         │  │• version         │  │• scope_id        │   │  │
│  │  │• hash            │  │• definition_hash │  │• serial_number   │   │  │
│  │  │• endpoint        │  │• model           │  │• file_path       │   │  │
│  │  │• tools (JSON)    │  │• mcps (JSON)     │  │• generated_at    │   │  │
│  │  └──────────────────┘  └──────────────────┘  └──────────────────┘   │  │
│  │                                                                      │  │
│  │  ┌──────────────────┐  ┌──────────────────┐                         │  │
│  │  │Project           │  │Project Technology│                         │  │
│  │  │(modified)        │  │                  │                         │  │
│  │  ├──────────────────┤  ├──────────────────┤                         │  │
│  │  │+ technology_stack│  │• language        │                         │  │
│  │  │+ last_sbom_id    │  │• framework       │                         │  │
│  │  └──────────────────┘  │• dependencies    │                         │  │
│  └─────────────────────────┴──────────────────┘                         │  │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
                       ┌─────────────────────────────┐
                       │  FILESYSTEM (ARCHIVAL)      │
                       ├─────────────────────────────┤
                       │ druppie/sboms/              │
                       │  • sbom-platform-{ts}.json  │
                       │  • sbom-project-{id}-{ts}.json│
                       │  • sbom-session-{id}-{ts}.json│
                       └─────────────────────────────┘
```

## 2. SBOM Generation Flow

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                           SBOM GENERATION FLOW                               │
└──────────────────────────────────────────────────────────────────────────────┘

 USER REQUEST
     │
     │  GET /api/sbom?scope=platform
     ▼
┌─────────────────────┐
│   API ROUTING       │
├─────────────────────┤
│ • Validate scope    │
│ • Check auth        │
│ • Parse params      │
└──────────┬──────────┘
           │
           ▼
┌───────────────────────────────────────────────────────────────────┐
│                    SbomGeneratorService                            │
├───────────────────────────────────────────────────────────────────┤
│                                                                   │
│  1. LOAD CONFIGURATIONS                                          │
│     ┌──────────────┐      ┌──────────────┐                       │
│     │ MCP configs  │      │ Agent defs   │                       │
│     │ (with vers)  │      │ (with vers)  │                       │
│     └──────┬───────┘      └──────┬───────┘                       │
│            │                     │                                │
│            ▼                     ▼                                │
│  2. CREATE COMPONENTS                                          │
│     ┌─────────────────────────────────────────────────┐          │
│     │ for each MCP:                                   │          │
│     │   Component(type=service, name, version, ...)   │          │
│     └─────────────────────────────────────────────────┘          │
│     ┌─────────────────────────────────────────────────┐          │
│     │ for each Agent:                                 │          │
│     │   Component(type=framework, name, version, ...) │          │
│     └─────────────────────────────────────────────────┘          │
│                                                                   │
│  3. BUILD DEPENDENCY GRAPH                                       │
│     Platform ──depends_on──▶ [MCPs, Agents]                      │
│       Agent  ──depends_on──▶ [MCPs it uses]                      │
│                                                                   │
│  4. ADD METADATA                                                 │
│     • timestamp                                                  │
│     • generator tool info                                        │
│     • serial number (UUID)                                       │
│                                                                   │
│  5. OUTPUT CYCLONEDX JSON                                       │
└───────────────────────────┬───────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                        CycloneDX BOM                            │
├─────────────────────────────────────────────────────────────────┤
│ {                                                               │
│   "bomFormat": "CycloneDX",                                     │
│   "specVersion": "1.6",                                         │
│   "serialNumber": "urn:uuid:...",                               │
│   "metadata": { "timestamp", "tools", "component" },            │
│   "components": [                                               │
│     { "type": "service", "name": "coding", "version": "1.0.0" } │
│   ],                                                            │
│   "dependencies": [...]                                         │
│ }                                                               │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼
                  ┌─────────────────────┐
                  │   RESPONSE          │
                  ├─────────────────────┤
                  │ • Save to DB        │
                  │ • Save to file      │
                  │ • Return JSON       │
                  └─────────────────────┘
```

## 3. Data Flow: Project Build with SBOM

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                    PROJECT BUILD WITH SBOM CAPTURE                          │
└──────────────────────────────────────────────────────────────────────────────┘

 USER STARTS BUILD
      │
      ▼
 ┌────────────────┐
 │ Developer Agent│
 │ Executes       │
 └────────┬───────┘
          │
          │ 1. DETECT TECHNOLOGY
          ▼
 ┌──────────────────────────────────┐
 │  TechnologyDetectionService      │
 ├──────────────────────────────────┤
 │  • Scan file extensions          │
 │  • Find config files             │
 │    (package.json, pyproject.toml)│
 │  • Parse dependencies            │
 │  • Identify frameworks           │
 └────────┬─────────────────────────┘
          │
          │ Returns: TechnologyStack
          │  { language: "python",
          │    framework: "fastapi",
          │    dependencies: [...] }
          ▼
 ┌────────────────┐
 │ Build & Deploy │
 └────────┬───────┘
          │
          │ 2. RECORD IN DATABASE
          ▼
 ┌──────────────────────────────────┐
 │  VersionTrackingService          │
 ├──────────────────────────────────┤
│  • record_agent_version()         │
│  • record_mcp_versions()          │
│  • save_project_technology()      │
└────────┬─────────────────────────┘
          │
          │ 3. GENERATE SBOM
          ▼
 ┌──────────────────────────────────┐
 │  SbomGeneratorService            │
 ├──────────────────────────────────┤
│  • generate_sbom(                 │
│      scope="project",             │
│      scope_id=project_id          │
│    )                              │
│  • Includes:                      │
│    - MCP servers used             │
│    - Agent definitions used       │
│    - Technology stack             │
│    - Dependencies                 │
└────────┬─────────────────────────┘
          │
          ▼
    ┌──────────┐
    │ STORE    │
    │ SBOM     │
    └──────────┘
```

## 4. Component Classification

```
┌───────────────────────────────────────────────────────────────────────┐
│                   CYCLONEDX COMPONENT TYPE MAPPING                     │
└───────────────────────────────────────────────────────────────────────┘

 DRUPPIE COMPONENTS          CYCLONEDX TYPE            REASON
 ──────────────────          ─────────────            ──────
 ┌─────────────────┐
 │  coding MCP     │  ───▶  │  service          │     HTTP endpoints
 │  docker MCP     │  ───▶  │  service          │     Container service
 │  filesearch MCP │  ───▶  │  service          │     Search service
 │  hitl MCP       │  ───▶  │  service          │     Interaction service
 └─────────────────┘

 ┌─────────────────┐
 │  developer      │  ───▶  │  framework        │     Agent orchestration
 │  planner        │  ───▶  │  framework        │     Planning framework
 │  deployer       │  ───▶  │  framework        │     Deployment framework
 │  reviewer       │  ───▶  │  framework        │     Review framework
 └─────────────────┘

 ┌─────────────────┐
 │  fastapi        │  ───▶  │  framework        │     Web framework
 │  react          │  ───▶  │  library          │     UI library
 │  pytest         │  ───▶  │  library          │     Testing library
 └─────────────────┘
```

## 5. Property Taxonomy for MCP Components

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                    CUSTOM CYCLONEDX PROPERTIES FOR MCPs                      │
└──────────────────────────────────────────────────────────────────────────────┘

 Standard CycloneDX Properties:
 ─────────────────────────────
 cdx:mcp:endpoint          → "http://mcp-coding:9001/mcp"
 cdx:mcp:transport         → "http" | "stdio"
 cdx:mcp:tools             → "read_file,write_file,commit_and_push"

 Druppie-Specific Properties:
 ───────────────────────────
 cdx:druppie:builtin       → true | false
 cdx:druppie:approval      → "auto_approve" | "require_approval"
 cdx:druppie:role          → "admin" | "developer" | ...

 Example Component:
 ──────────────────
 {
   "type": "service",
   "name": "coding",
   "version": "1.0.0",
   "properties": [
     {"name": "cdx:mcp:endpoint", "value": "http://mcp-coding:9001/mcp"},
     {"name": "cdx:mcp:transport", "value": "http"},
     {"name": "cdx:mcp:tools", "value": "read_file,write_file,commit_and_push"},
     {"name": "cdx:druppie:builtin", "value": "false"},
     {"name": "cdx:druppie:approval:role", "value": "developer"}
   ]
 }
```

## 6. Database Schema Relationships

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                        DATABASE RELATIONSHIPS                               │
└──────────────────────────────────────────────────────────────────────────────┘

 users
   │ 1
   │
   │ N
 ▼
 sbom_records ──────────────────────┐
   │                                  │
   │ N                                │
   │                                  │
   │ 1                                │ N
   ▼                                  │
 projects ◀────────────────────────────┤
   │ 1                                │
   │                                  │
   │ N                                │
   │                                  │
 ▼                                    │
 project_technologies ◀────────────────┘
   (language, framework, dependencies)

 sessions
   │ 1
   │
   │ N
   ▼
 sbom_records

 mcp_server_versions
   │ N
   │
   │ tracked in
   │
   ▼
 sbom_records (components)

 agent_versions
   │ N
   │
   │ tracked in
   │
   ▼
 sbom_records (components)
```

## 7. API Request/Response Flow

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                         API REQUEST FLOW                                    │
└──────────────────────────────────────────────────────────────────────────────┘

 CLIENT                          API                            SERVICE
  │                               │                               │
  │  GET /api/sbom?               │                               │
  │    scope=platform             │                               │
  │    format=cyclonedx           │                               │
  │    version=1.6                │                               │
  ├──────────────────────────────▶│                               │
  │                               │                               │
  │                               │  validate_auth()              │
  │                               │  validate_params()            │
  │                               │                               │
  │                               │  ┌─────────────────────────┐  │
  │                               │  │ SbomGeneratorService    │  │
  │                               │  │                         │  │
  │                               │  │ generate_sbom(          │  │
  │                               │  │   scope="platform"      │  │
  │                               │  │ )                       │  │
  │                               │  └─────────────────────────┘  │
  │                               │                               │
  │                               │  load_mcp_configs()          │
  │                               │  load_agent_definitions()    │
  │                               │  build_cyclonedx_bom()       │
  │                               │                               │
  │                               │  ┌─────────────────────────┐  │
  │                               │  │ Record in DB            │  │
  │                               │  │ sbom_records            │  │
  │                               │  └─────────────────────────┘  │
  │                               │                               │
  │  ◀────────────────────────────│ JSON Response                 │
  │                               │ {                             │
  │                               │   "bomFormat": "CycloneDX",   │
  │                               │   "specVersion": "1.6",       │
  │                               │   "components": [...],        │
  │                               │   "dependencies": [...]       │
  │                               │ }                             │
```
