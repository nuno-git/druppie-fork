# AI Platform Governance Architecture

## Kernprincipe: Uitbreiding van Bestaande Systemen

Dit document beschrijft hoe we **AI-applicaties** (zoals de Vergunning Zoeker) bouwen door de bestaande Druppie architectuur uit te breiden met het concept van **WorkflowTemplate**.

---

## 1. Het Probleem

| Concept | ExecutionPlan (bestaand) | Vergunning Zoeker (gewenst) |
|---------|--------------------------|------------------------------|
| **Type** | Eenmalige taak | Draaiende applicatie |
| **Runs** | 1x uitvoeren, klaar | Continu/periodiek |
| **Trigger** | Gebruiker typt iets | Schedule of event |
| **Items** | 1 taak | Per document een verwerking |

**ExecutionPlan** is ontworpen voor eenmalige taken. Voor een **applicatie** die continu draait hebben we iets anders nodig.

---

## 2. De Oplossing: WorkflowTemplate

Een **WorkflowTemplate** is een herbruikbare workflow-definitie die:
1. In de **Registry** staat (YAML)
2. Door de **Scheduler** getriggerd kan worden
3. Per item (document, event) een **ExecutionPlan** aanmaakt

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           WORKFLOW TEMPLATE                                  │
│                    (YAML in registry/workflows/)                             │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  id: vergunning-zoeker                                                      │
│  name: Vergunning Zoeker                                                    │
│  schedule: "0 2 * * *"  (elke nacht om 2:00)                               │
│                                                                             │
│  discovery:              ◄── Stap 1: Vind items om te verwerken            │
│    agent: filesystem_scanner                                                │
│    params: { path: "/mnt/s-schijf", patterns: ["*vergunning*"] }           │
│                                                                             │
│  steps:                  ◄── Stap 2+: Per item uitvoeren                   │
│    - agent: document_analyzer                                               │
│      action: classify                                                       │
│    - agent: policy_engine                                                   │
│      action: evaluate                                                       │
│    - agent: human_reviewer        ◄── HITL als confidence < 0.90           │
│      condition: "confidence < 0.90"                                         │
│    - agent: zaaksysteem_agent                                               │
│      action: create_case                                                    │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    │ Scheduler triggert
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           WORKFLOW EXECUTION                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  1. Discovery draait → vindt 50 documenten                                  │
│                                                                             │
│  2. Per document wordt een ExecutionPlan aangemaakt:                        │
│                                                                             │
│     ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐       │
│     │ ExecutionPlan    │  │ ExecutionPlan    │  │ ExecutionPlan    │       │
│     │ doc-001          │  │ doc-002          │  │ doc-003          │       │
│     │ Status: running  │  │ Status: HITL     │  │ Status: completed│       │
│     └──────────────────┘  └──────────────────┘  └──────────────────┘       │
│              ...                  ...                  ...                  │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Nieuwe Types

### 3.1 WorkflowTemplate (nieuw in Registry)

```go
// WorkflowTemplate defines a reusable, triggerable workflow
type WorkflowTemplate struct {
    ID          string            `json:"id" yaml:"id"`
    Name        string            `json:"name" yaml:"name"`
    Description string            `json:"description" yaml:"description"`

    // Governance (voor ontwikkelproces)
    Status      string            `json:"status" yaml:"status"`       // draft, review, approved, production, deprecated
    Version     string            `json:"version" yaml:"version"`

    // Trigger configuratie
    Schedule    string            `json:"schedule,omitempty" yaml:"schedule,omitempty"`     // Cron expression
    Trigger     TriggerConfig     `json:"trigger,omitempty" yaml:"trigger,omitempty"`       // Of event-based

    // Discovery: hoe vinden we items om te verwerken?
    Discovery   DiscoveryConfig   `json:"discovery,omitempty" yaml:"discovery,omitempty"`

    // Steps: wat doen we per item?
    Steps       []WorkflowStep    `json:"steps" yaml:"steps"`

    // MCP servers die nodig zijn
    MCPServers  []string          `json:"mcp_servers,omitempty" yaml:"mcp_servers,omitempty"`

    // Access control
    AuthGroups  []string          `json:"auth_groups,omitempty" yaml:"auth_groups,omitempty"`
}

type TriggerConfig struct {
    Type        string            `json:"type" yaml:"type"`           // schedule, webhook, manual, event
    Source      string            `json:"source,omitempty" yaml:"source,omitempty"`         // Voor event: welke bron
}

type DiscoveryConfig struct {
    Agent       string            `json:"agent" yaml:"agent"`         // Agent die discovery doet
    Action      string            `json:"action" yaml:"action"`       // Action op die agent
    Params      map[string]any    `json:"params,omitempty" yaml:"params,omitempty"`
}

type WorkflowStep struct {
    ID          string            `json:"id,omitempty" yaml:"id,omitempty"`
    Agent       string            `json:"agent" yaml:"agent"`
    Action      string            `json:"action" yaml:"action"`
    Params      map[string]any    `json:"params,omitempty" yaml:"params,omitempty"`

    // Conditionele uitvoering
    Condition   string            `json:"condition,omitempty" yaml:"condition,omitempty"`   // CEL expression

    // HITL configuratie
    RequiresApproval bool         `json:"requires_approval,omitempty" yaml:"requires_approval,omitempty"`
    AssignedGroup    string       `json:"assigned_group,omitempty" yaml:"assigned_group,omitempty"`

    // Dependencies
    DependsOn   []string          `json:"depends_on,omitempty" yaml:"depends_on,omitempty"`
}
```

### 3.2 WorkflowJob (nieuw in Scheduler)

```go
// WorkflowJob executes a WorkflowTemplate on schedule
type WorkflowJob struct {
    WorkflowID   string
    Template     *model.WorkflowTemplate
    CronSchedule string

    // Dependencies
    Registry     *registry.Registry
    Planner      *planner.Planner
    TaskManager  *TaskManager
    MCPManager   *mcp.Manager
}

func (j *WorkflowJob) Name() string {
    return fmt.Sprintf("Workflow: %s", j.Template.Name)
}

func (j *WorkflowJob) Schedule() string {
    return j.CronSchedule
}

func (j *WorkflowJob) Run(ctx context.Context) error {
    // 1. Run discovery om items te vinden
    items, err := j.runDiscovery(ctx)
    if err != nil {
        return err
    }

    // 2. Per item een ExecutionPlan maken en starten
    for _, item := range items {
        plan := j.createPlanForItem(item)
        j.TaskManager.StartTask(ctx, plan)
    }

    return nil
}
```

### 3.3 ExecutionPlan Uitbreiding (minimaal)

```go
type ExecutionPlan struct {
    // ... bestaande velden ...

    // Link naar workflow (indien van toepassing)
    WorkflowID      string          `json:"workflow_id,omitempty"`
    WorkflowRunID   string          `json:"workflow_run_id,omitempty"`   // Batch identifier
    ItemRef         string          `json:"item_ref,omitempty"`          // Welk item wordt verwerkt

    // Review systeem (voor governance en feedback)
    Reviews         []Review        `json:"reviews,omitempty"`

    // Runtime feedback
    Feedback        []FeedbackItem  `json:"feedback,omitempty"`
}

// Review represents a comment on a plan (van architect, legal, etc.)
type Review struct {
    ID          string     `json:"id"`
    AuthorID    string     `json:"author_id"`
    AuthorRole  string     `json:"author_role"`       // architect, legal, security, ops
    StepID      *int       `json:"step_id,omitempty"` // Optioneel: specifieke step
    Content     string     `json:"content"`
    Status      string     `json:"status"`            // open, resolved, wont_fix
    CreatedAt   time.Time  `json:"created_at"`
}

// FeedbackItem represents runtime feedback from end users
type FeedbackItem struct {
    ID             string         `json:"id"`
    StepID         int            `json:"step_id"`
    Type           string         `json:"type"`              // correction, bug, false_positive
    UserComment    string         `json:"user_comment"`
    ExpectedOutput map[string]any `json:"expected_output,omitempty"`
    Status         string         `json:"status"`            // new, triaged, resolved
    CreatedAt      time.Time      `json:"created_at"`
}
```

---

## 4. Vergunning Zoeker als WorkflowTemplate

```yaml
# registry/workflows/vergunning-zoeker.yaml

id: vergunning_zoeker
name: Vergunning Zoeker
description: |
  Zoekt verloren vergunningen op file shares en verwerkt ze naar het Zaaksysteem.
  Draait elke nacht om 02:00.

status: production
version: "1.0.0"

# Wanneer draait dit?
schedule: "0 2 * * *"   # Elke nacht om 02:00

# Welke MCP servers zijn nodig?
mcp_servers:
  - filesystem_mcp
  - zaaksysteem_mcp

# Stap 1: Discovery - vind documenten om te verwerken
discovery:
  agent: filesystem_scanner
  action: discover_files
  params:
    paths:
      - "/mnt/s-schijf/vergunningen"
      - "/mnt/sharepoint/oud-archief"
    patterns:
      - "*vergunning*"
      - "*beschikking*"
      - "*ontheffing*"
    extensions:
      - ".pdf"
      - ".docx"
    exclude_processed: true   # Skip bestanden die al verwerkt zijn

# Stap 2+: Per gevonden document
steps:
  # De Analist: Classificeer document
  - id: classify
    agent: document_analyzer
    action: classify_document
    params:
      categories:
        - Watervergunning
        - Leggerwijziging
        - Ontheffing
        - Niet_Vergunning

  # De Analist: Extracteer metadata
  - id: extract
    agent: document_analyzer
    action: extract_metadata
    depends_on: [classify]
    params:
      fields:
        - type
        - huisnummer
        - perceel
        - datum
        - aanvrager
        - bsn           # PII detectie

  # De Beslisser: Evalueer confidence
  - id: evaluate
    agent: policy_engine
    action: evaluate_confidence
    depends_on: [extract]
    params:
      rules:
        - condition: "classification == 'Niet_Vergunning'"
          action: skip
          reason: "Geen vergunning"
        - condition: "confidence >= 0.90 && !contains_bsn"
          action: auto_approve
        - condition: "confidence >= 0.90 && contains_bsn"
          action: require_review
          assigned_group: privacy_officers
          reason: "BSN gedetecteerd - privacy review vereist"
        - condition: "confidence < 0.90"
          action: require_review
          assigned_group: vergunning_medewerkers
          reason: "Lage confidence - handmatige controle"

  # HITL: Handmatige review (conditioneel)
  - id: human_review
    agent: human_reviewer
    action: manual_review
    depends_on: [evaluate]
    condition: "evaluate.action == 'require_review'"
    requires_approval: true
    assigned_group: "{{evaluate.assigned_group}}"
    params:
      show_fields:
        - classification
        - confidence
        - extracted_metadata
        - document_preview

  # De Uitvoerder: Registreer in Zaaksysteem
  - id: register
    agent: zaaksysteem_agent
    action: create_case
    depends_on: [human_review]
    condition: "evaluate.action != 'skip'"
    params:
      case_type: "{{classify.result}}"
      metadata: "{{extract.result}}"
      document: "{{item.file_path}}"
      confidential: "{{extract.contains_bsn}}"

  # De Uitvoerder: Quarantine origineel bestand
  - id: quarantine
    agent: filesystem_agent
    action: move_file
    depends_on: [register]
    params:
      source: "{{item.file_path}}"
      destination: "/mnt/s-schijf/PROCESSED_QUARANTINE"
      retention_days: 30

  # Audit logging
  - id: audit
    agent: audit_agent
    action: log_completion
    depends_on: [quarantine]
    params:
      message: "Bestand '{{item.filename}}' verwerkt naar Zaak {{register.case_id}}"
      level: info
```

---

## 5. Governance Flow voor WorkflowTemplates

WorkflowTemplates hebben hun eigen governance flow (voor het **ontwikkelproces**, niet de runtime):

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    WORKFLOW TEMPLATE LIFECYCLE                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   DRAFT ──► ARCHITECT_REVIEW ──► LEGAL_CHECK ──► SECURITY_REVIEW           │
│                                                        │                    │
│                                                        ▼                    │
│                              OPS_APPROVAL ◄─── CHANGES_REQUESTED            │
│                                   │                                         │
│                                   ▼                                         │
│                              STAGING (test met mock data)                   │
│                                   │                                         │
│                                   ▼                                         │
│                              PRODUCTION                                     │
│                                   │                                         │
│                                   ▼                                         │
│                              DEPRECATED (na end-of-life)                    │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

Dit wordt geïmplementeerd als een **ExecutionPlan** met review steps:

```yaml
# Governance plan voor vergunning-zoeker (automatisch gegenereerd)
plan_id: governance-vergunning-zoeker-v1
intent:
  prompt: "Review en deploy WorkflowTemplate: vergunning-zoeker"

steps:
  - step_id: 1
    agent_id: intake_agent
    action: validate_workflow_template
    params:
      template_id: vergunning_zoeker
    status: completed

  - step_id: 2
    agent_id: architect_reviewer
    action: architecture_review
    status: requires_approval
    assigned_group: architects
    depends_on: [1]

  - step_id: 3
    agent_id: legal_reviewer
    action: compliance_check
    status: requires_approval
    assigned_group: legal
    depends_on: [2]
    params:
      check_items:
        - GDPR compliance
        - Archiefwet
        - Data retention

  - step_id: 4
    agent_id: security_reviewer
    action: security_review
    status: requires_approval
    assigned_group: security
    depends_on: [3]

  - step_id: 5
    agent_id: ops_reviewer
    action: deployment_approval
    status: requires_approval
    assigned_group: ops
    depends_on: [4]
    params:
      check_items:
        - Resource requirements
        - MCP server availability
        - Monitoring setup

  - step_id: 6
    agent_id: deployment_agent
    action: deploy_workflow
    status: pending
    depends_on: [5]
    params:
      template_id: vergunning_zoeker
      target: production
```

---

## 6. Runtime Feedback Loop

Eindgebruikers kunnen feedback geven op verwerkte items:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           FEEDBACK FLOW                                      │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  PRODUCTIE                                                                  │
│  ┌────────────────────────────────────────────────────────────────┐        │
│  │ Vergunning Zoeker verwerkt document                            │        │
│  │ Resultaat: "Watervergunning" (confidence: 0.87)                │        │
│  │ Zaak aangemaakt: Z-2025-001234                                 │        │
│  └────────────────────────────────────────────────────────────────┘        │
│                              │                                              │
│                              ▼                                              │
│  UI: FEEDBACK WIDGET                                                        │
│  ┌────────────────────────────────────────────────────────────────┐        │
│  │ Was dit resultaat correct?                                     │        │
│  │                                                                │        │
│  │ [👍 Correct]  [👎 Fout]  [⚠️ Deels correct]                   │        │
│  │                                                                │        │
│  │ Toelichting: _______________________________________________   │        │
│  │ Verwacht resultaat: [dropdown]                                 │        │
│  └────────────────────────────────────────────────────────────────┘        │
│                              │                                              │
│                              ▼                                              │
│  FEEDBACK AGGREGATIE                                                        │
│  ┌────────────────────────────────────────────────────────────────┐        │
│  │ Feedback opgeslagen in ExecutionPlan                           │        │
│  │                                                                │        │
│  │ Bij 5+ vergelijkbare klachten:                                 │        │
│  │ → Automatisch ticket aanmaken                                  │        │
│  │ → Development team notificeren                                 │        │
│  │ → Data toevoegen aan verbetering-set                           │        │
│  └────────────────────────────────────────────────────────────────┘        │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 7. MCP Servers

### 7.1 Filesystem MCP (mock voor development)

```yaml
# registry/mcp/filesystem-mcp.yaml
id: filesystem_mcp
name: Filesystem Scanner
transport: stdio
command: ./mcp-servers/filesystem-mcp
tools:
  - name: discover_files
    description: Scan directories for files matching patterns
  - name: read_file
    description: Read file contents (with OCR for PDFs)
  - name: move_file
    description: Move file to new location
  - name: delete_file
    description: Delete file (quarantine supported)
```

### 7.2 Zaaksysteem MCP (mock voor development)

```yaml
# registry/mcp/zaaksysteem-mcp.yaml
id: zaaksysteem_mcp
name: Zaaksysteem Integration
transport: stdio
command: ./mcp-servers/zaaksysteem-mcp
tools:
  - name: create_case
    description: Create new case with document
  - name: upload_document
    description: Upload document to existing case
  - name: update_metadata
    description: Update case metadata
  - name: search_cases
    description: Search existing cases
```

---

## 8. Agents

### 8.1 Document Analyzer Agent

```yaml
# registry/agents/document-analyzer.yaml
id: document_analyzer
name: Document Analyzer
type: execution_agent
description: Analyseert documenten, classificeert ze en extraheert metadata

instructions: |
  Je bent een document analyse specialist. Je taken:
  1. Classificeer documenten naar type (Watervergunning, Leggerwijziging, etc.)
  2. Extracteer metadata (datum, aanvrager, perceel, etc.)
  3. Detecteer PII (BSN nummers, persoonlijke gegevens)
  4. Geef een confidence score (0.0 - 1.0)

  Wees conservatief met hoge scores. Bij twijfel, geef lage confidence.

skills:
  - document_classification
  - metadata_extraction
  - pii_detection

tools:
  - ocr_service
```

### 8.2 Policy Engine Agent

```yaml
# registry/agents/policy-engine.yaml
id: policy_engine
name: Policy Engine
type: system_agent
description: Evalueert resultaten tegen business rules en bepaalt vervolgacties

instructions: |
  Je evalueert classificatie-resultaten tegen voorgedefinieerde regels.
  Output altijd JSON met:
  - action: "auto_approve" | "require_review" | "skip" | "reject"
  - reason: korte uitleg
  - assigned_group: (alleen bij require_review)
```

---

## 9. Implementatie Overzicht

### Nieuwe bestanden:

| Bestand | Doel |
|---------|------|
| `core/internal/model/workflow.go` | WorkflowTemplate type |
| `core/internal/registry/workflows.go` | Workflow registry loading |
| `core/internal/scheduler/workflow_job.go` | WorkflowJob implementatie |
| `core/druppie/workflow_manager.go` | Workflow execution logic |

### Te wijzigen bestanden:

| Bestand | Wijziging |
|---------|-----------|
| `core/internal/model/types.go` | Review, FeedbackItem toevoegen |
| `core/internal/model/types.go` | ExecutionPlan uitbreiden |
| `core/internal/registry/registry.go` | Workflows map toevoegen |
| `core/druppie/main.go` | Workflow endpoints, WorkflowJob registratie |
| `core/internal/config/manager.go` | Workflow config support |

### Nieuwe directories:

| Directory | Inhoud |
|-----------|--------|
| `registry/workflows/` | WorkflowTemplate YAML's |
| `mcp-servers/filesystem-mcp/` | Mock filesystem MCP |
| `mcp-servers/zaaksysteem-mcp/` | Mock zaaksysteem MCP |

---

## 10. API Endpoints

### Workflow Management

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/v1/workflows` | List all workflow templates |
| GET | `/v1/workflows/{id}` | Get workflow template details |
| POST | `/v1/workflows/{id}/trigger` | Manually trigger workflow |
| GET | `/v1/workflows/{id}/runs` | List workflow runs |
| GET | `/v1/workflows/{id}/runs/{runId}` | Get run details (alle plans) |

### Review & Feedback

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/v1/plans/{id}/reviews` | Add review comment |
| PUT | `/v1/plans/{id}/reviews/{reviewId}` | Update review (resolve) |
| POST | `/v1/plans/{id}/feedback` | Submit user feedback |
| GET | `/v1/feedback/aggregated` | Get aggregated feedback for improvement |

---

## 11. Samenvatting

**Kern concept:**
- **WorkflowTemplate** = applicatie definitie (YAML in registry)
- **WorkflowJob** = scheduler job die de template triggert
- **ExecutionPlan** = per-item instantie van de workflow

**Voor Vergunning Zoeker:**
1. WorkflowTemplate definieert de volledige flow
2. Scheduler triggert elke nacht
3. Discovery vindt documenten op file shares
4. Per document wordt een ExecutionPlan aangemaakt
5. HITL bij lage confidence of BSN detectie
6. Resultaat naar Zaaksysteem, origineel naar quarantine

**Governance:**
1. WorkflowTemplate heeft eigen status (draft → production)
2. Review via ExecutionPlan met approval steps
3. Feedback van eindgebruikers wordt verzameld en geaggregeerd

**Herbruikbaar voor andere use-cases:**
- Drone Detection: andere discovery (video stream), andere agents
- HR Onboarding: andere trigger (event), andere steps
- Zelfde WorkflowTemplate structuur, MCP servers, en feedback loop
