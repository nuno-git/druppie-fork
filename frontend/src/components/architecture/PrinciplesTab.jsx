import { useState } from 'react'
import { ChevronDown, ChevronRight, Layers, ShieldCheck, GitBranch, Database } from 'lucide-react'
import MermaidBlock from '../MermaidBlock'
import AskArchitectFooter from './AskArchitectFooter'

const SectionCard = ({ title, icon: Icon, children, defaultOpen = false }) => {
  const [expanded, setExpanded] = useState(defaultOpen)

  return (
    <div className="bg-white rounded-xl border border-gray-100 p-6">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between"
      >
        <div className="flex items-center space-x-2">
          <Icon className="w-4 h-4 text-gray-400" />
          <h2 className="text-sm font-medium text-gray-400 uppercase tracking-wide">{title}</h2>
        </div>
        {expanded ? <ChevronDown className="w-4 h-4 text-gray-400" /> : <ChevronRight className="w-4 h-4 text-gray-400" />}
      </button>
      {expanded && <div className="mt-4">{children}</div>}
    </div>
  )
}

const Principle = ({ title, description }) => (
  <div className="py-2">
    <h4 className="text-sm font-medium text-gray-900">{title}</h4>
    <p className="text-sm text-gray-500 mt-0.5">{description}</p>
  </div>
)

const DESIGN_LOOP_DIAGRAM = `sequenceDiagram
    participant P as Planner
    participant BA as Business Analyst
    participant A as Architect
    participant U as Gebruiker

    P->>BA: Start requirements verzameling
    BA->>U: Stel vragen (HITL)
    U->>BA: Antwoorden
    BA->>BA: Schrijf functional_design.md
    BA->>A: Design klaar voor review
    alt Feedback nodig
        A->>BA: DESIGN_FEEDBACK (specifieke items)
        BA->>BA: Pas design aan
        BA->>A: Herzien design
    end
    A->>A: Schrijf technical_design.md
    A->>P: DESIGN_APPROVED`

const TDD_LOOP_DIAGRAM = `sequenceDiagram
    participant P as Planner
    participant BP as Builder Planner
    participant TB as Test Builder
    participant B as Builder
    participant TE as Test Executor
    participant U as Gebruiker

    P->>BP: Plan implementatie
    BP->>BP: Schrijf builder_plan.md
    BP->>TB: Red Phase
    TB->>TB: Genereer tests
    TB->>B: Green Phase
    B->>B: Implementeer code
    B->>TE: Run tests
    alt Tests slagen
        TE->>P: PASS
    else Tests falen (retry < 3)
        TE->>B: FAIL + feedback
        B->>TE: Opnieuw
    else Tests falen (retry >= 3)
        TE->>P: Escaleer
        P->>U: HITL keuze
        alt Doorgaan met instructies
            U->>B: Specifieke aanwijzingen
        else Deploy met waarschuwing
            P->>P: Plan Deployer
        else Afbreken
            P->>P: Plan Summarizer
        end
    end`

const DATA_MODEL_DIAGRAM = `erDiagram
    Session ||--o{ AgentRun : bevat
    Session ||--o{ Message : bevat
    Session }o--|| Project : hoort_bij
    AgentRun ||--o{ ToolCall : bevat
    AgentRun ||--o{ LLMCall : bevat
    ToolCall ||--o| Approval : vereist
    Project ||--o{ Deployment : heeft
    Session ||--o{ SandboxSession : heeft

    Session {
        uuid id PK
        string status
        string intent
        datetime created_at
    }
    AgentRun {
        uuid id PK
        string agent_id
        string status
        int iteration_count
    }
    ToolCall {
        uuid id PK
        string tool_name
        string mcp_server
        string status
    }
    Approval {
        uuid id PK
        string status
        string required_role
    }
    Project {
        uuid id PK
        string name
        string repo_name
    }`

const PrinciplesTab = () => (
  <div className="space-y-6">
    <SectionCard title="Architectuurprincipes" icon={Layers} defaultOpen={true}>
      <div className="divide-y divide-gray-50">
        <Principle
          title="Layered Architecture"
          description="Strikte scheiding in lagen: Repository (data access) → Domain Model (Pydantic) → Service (business logic) → API Route (HTTP). Data stroomt altijd in één richting."
        />
        <Principle
          title="Summary / Detail Patroon"
          description="Domain models gebruiken Summary voor lijsten (lichtgewicht) en Detail voor individuele items (volledig). Bijvoorbeeld: SessionSummary vs SessionDetail."
        />
        <Principle
          title="Agents Act Only Through Tools"
          description="Elke actie die een agent neemt gaat via een tool call - MCP tools (externe servers) of builtin tools (platform). Hierdoor kan elke actie worden gelogd, geïnspecteerd en achter een approval workflow worden gezet."
        />
        <Principle
          title="YAML-First Configuratie"
          description="Agent definities staan in YAML bestanden, niet in de database. Dit maakt versioning via git mogelijk en houdt configuratie declaratief en leesbaar."
        />
        <Principle
          title="Geen Database Migraties"
          description="SQLAlchemy models worden direct bijgewerkt. Database wordt gereset met docker compose --profile reset-db. Geen migratiebestanden, geen Alembic."
        />
        <Principle
          title="Geen JSON/JSONB Kolommen"
          description="Alle data wordt genormaliseerd in relationele tabellen. Geen semi-gestructureerde data in de database."
        />
        <Principle
          title="Geen Legacy/Fallback Code"
          description="Schone architectuur zonder backwards compatibility hacks. Code wordt direct aangepast, niet omheen gewerkt."
        />
      </div>
    </SectionCard>

    <SectionCard title="Governance Model" icon={ShieldCheck} defaultOpen={true}>
      <div className="divide-y divide-gray-50">
        <Principle
          title="Layered Approval Systeem"
          description="Twee lagen: globale defaults in mcp_config.yaml en agent-specifieke overrides in agent YAML bestanden. Agents kunnen de approval regels aanscherpen (nooit versoepelen ten opzichte van global)."
        />
        <Principle
          title="Role-Based Access Control"
          description="Keycloak rollen bepalen wie wat mag goedkeuren. Rollen: admin (alles), architect (designs), developer (Docker/PRs), business_analyst (functionele designs). Admins kunnen altijd alles goedkeuren."
        />
        <Principle
          title="Human-in-the-Loop (HITL)"
          description="Agents kunnen pauzeren om de gebruiker vragen te stellen via hitl_ask_question (vrije tekst) of hitl_ask_multiple_choice_question (keuzes). De workflow hervat pas na een antwoord."
        />
        <Principle
          title="Tool Call Transparantie"
          description="Elke tool call wordt opgeslagen in de database met volledige argumenten en resultaten. De chat timeline toont alle acties chronologisch, inclusief approval status."
        />
      </div>
    </SectionCard>

    <SectionCard title="Agent Samenwerkingspatronen" icon={GitBranch}>
      <div className="space-y-6">
        <div>
          <h3 className="text-sm font-medium text-gray-900 mb-2">Design Loop (BA ↔ Architect)</h3>
          <p className="text-sm text-gray-500 mb-3">
            De Business Analyst verzamelt requirements en schrijft een functioneel design.
            De Architect reviewed dit en stuurt feedback terug als het niet aan de standaarden voldoet.
            Deze loop herhaalt tot het design goedgekeurd is.
          </p>
          <MermaidBlock code={DESIGN_LOOP_DIAGRAM} />
        </div>

        <div>
          <h3 className="text-sm font-medium text-gray-900 mb-2">TDD Loop (Test Builder → Builder → Test Executor)</h3>
          <p className="text-sm text-gray-500 mb-3">
            Test-Driven Development: eerst worden tests geschreven (Red Phase), dan code om de tests te laten slagen (Green Phase),
            en ten slotte worden tests uitgevoerd met automatische retry en escalatie bij herhaald falen.
          </p>
          <MermaidBlock code={TDD_LOOP_DIAGRAM} />
        </div>
      </div>
    </SectionCard>

    <SectionCard title="Data Model" icon={Database}>
      <p className="text-sm text-gray-500 mb-3">
        Het datamodel draait om Sessions die AgentRuns bevatten. Elke AgentRun heeft ToolCalls en LLMCalls.
        ToolCalls kunnen Approvals vereisen. Sessions zijn gekoppeld aan Projects met Deployments.
      </p>
      <MermaidBlock code={DATA_MODEL_DIAGRAM} />
    </SectionCard>

    <AskArchitectFooter />
  </div>
)

export default PrinciplesTab
