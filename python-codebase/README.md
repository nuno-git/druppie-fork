# Druppie - Governance AI Platform

A Python-based AI governance platform that enables teams to build solutions for end users through intelligent orchestration.

## Philosophy

**Governance-first.** Druppie is not just a workflow runner - it's a platform that allows an AI team to create solutions for end users:

1. **Router** - Analyzes user intent and routes appropriately
2. **Planner** - Generates execution plans using specialized agents
3. **Agents** - Specialized roles (Developer, Architect, Business Analyst, Compliance)
4. **Executors** - Execute actions with MCP tools
5. **Task Manager** - Orchestrates plan execution with human-in-the-loop support

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                      DRUPPIE GOVERNANCE PLATFORM                            │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  User Request                                                               │
│       │                                                                     │
│       ▼                                                                     │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐                     │
│  │   Router    │───►│   Planner   │───►│Task Manager │                     │
│  │(Intent)     │    │(Plan)       │    │(Execution)  │                     │
│  └─────────────┘    └─────────────┘    └─────────────┘                     │
│                            │                  │                             │
│                            ▼                  ▼                             │
│  ┌───────────────────────────────────────────────────────────────────────┐ │
│  │                       AGENT REGISTRY                                  │ │
│  │  ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌────────────┐      │ │
│  │  │ Developer  │  │ Architect  │  │  Business  │  │ Compliance │      │ │
│  │  │            │  │            │  │  Analyst   │  │            │      │ │
│  │  └────────────┘  └────────────┘  └────────────┘  └────────────┘      │ │
│  └───────────────────────────────────────────────────────────────────────┘ │
│                                     │                                       │
│                                     ▼                                       │
│  ┌───────────────────────────────────────────────────────────────────────┐ │
│  │                        EXECUTOR DISPATCH                              │ │
│  │  ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌────────────┐      │ │
│  │  │  MCP       │  │ Developer  │  │ Architect  │  │ Compliance │      │ │
│  │  │ Executor   │  │ Executor   │  │ Executor   │  │ Executor   │      │ │
│  │  └────────────┘  └────────────┘  └────────────┘  └────────────┘      │ │
│  └───────────────────────────────────────────────────────────────────────┘ │
│                                     │                                       │
│                                     ▼                                       │
│  ┌───────────────────────────────────────────────────────────────────────┐ │
│  │                         MCP REGISTRY                                  │ │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐              │ │
│  │  │filesystem│  │zaaksysteem│  │  email   │  │   ...    │              │ │
│  │  └──────────┘  └──────────┘  └──────────┘  └──────────┘              │ │
│  └───────────────────────────────────────────────────────────────────────┘ │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Key Components

### Router
Analyzes user input and determines intent:
- **create_project**: User wants to create something new
- **update_project**: User wants to modify existing work
- **query_registry**: User wants to search capabilities
- **orchestrate_complex**: Complex multi-agent task
- **general_chat**: Simple Q&A (direct response)

### Planner
Generates execution plans from intent:
1. Selects relevant agents based on the task
2. Creates steps with proper dependencies
3. Assigns steps to agents with specific actions

### Agents
Specialized AI roles defined in YAML:

| Agent | Type | Description |
|-------|------|-------------|
| **Developer** | execution | Creates and modifies code |
| **Architect** | spec | Designs systems, creates documentation |
| **Business Analyst** | spec | Analyzes requirements, creates user stories |
| **Compliance** | support | Validates against policies and regulations |

### Executors
Execute step actions:
- **MCPExecutor**: Invokes MCP tools
- **DeveloperExecutor**: Creates files and code
- **ArchitectExecutor**: Generates designs and docs
- **BusinessAnalystExecutor**: Analyzes requirements
- **ComplianceExecutor**: Validates compliance

### Task Manager
Orchestrates plan execution:
- Manages step dependencies
- Handles human-in-the-loop approvals
- Tracks progress and results
- Supports cancellation

## Quick Start

### Installation

```bash
cd python-codebase
pip install -e ".[dev]"
```

### Start the Server

```bash
druppie serve
```

### Make a Request

```bash
curl -X POST http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{"role": "user", "content": "Create a Python FastAPI project with user authentication"}]
  }'
```

## Project Structure

```
python-codebase/
├── src/druppie/
│   ├── core/
│   │   └── models.py           # Core data models (Plan, Step, Intent, Agent)
│   ├── router/
│   │   └── router.py           # Intent analysis
│   ├── planner/
│   │   └── planner.py          # Plan generation
│   ├── executor/
│   │   ├── dispatcher.py       # Routes steps to executors
│   │   ├── developer.py        # Developer actions
│   │   ├── architect.py        # Architect actions
│   │   ├── business_analyst.py # BA actions
│   │   ├── compliance.py       # Compliance actions
│   │   └── mcp_executor.py     # MCP tool invocation
│   ├── task_manager/
│   │   └── task_manager.py     # Plan execution orchestration
│   ├── registry/
│   │   └── agent_registry.py   # Agent definition loading
│   ├── mcp/
│   │   ├── registry.py         # MCP server definitions
│   │   └── client.py           # MCP tool invocation
│   ├── store/
│   │   └── file_store.py       # JSON file persistence
│   ├── api/
│   │   └── main.py             # FastAPI application
│   └── cli.py                  # Command-line interface
├── registry/
│   ├── agents/                 # Agent definitions (YAML)
│   │   ├── developer.yaml
│   │   ├── architect.yaml
│   │   ├── business_analyst.yaml
│   │   └── compliance.yaml
│   └── mcp/                    # MCP server definitions (YAML)
│       ├── filesystem.yaml
│       └── zaaksysteem.yaml
└── tests/
```

## API Endpoints

### Chat (Main Interface)
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/v1/chat/completions` | Main AI interface |

### Agents
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/v1/agents` | List available agents |
| GET | `/v1/agents/{id}` | Get agent details |

### Plans
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/v1/plans` | List execution plans |
| GET | `/v1/plans/{id}` | Get plan details |
| POST | `/v1/plans` | Create plan manually |
| DELETE | `/v1/plans/{id}` | Delete plan |
| POST | `/v1/plans/{id}/feedback` | Submit feedback |
| POST | `/v1/plans/{id}/cancel` | Cancel running plan |

### MCP
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/v1/mcp/servers` | List MCP servers |
| GET | `/v1/mcp/tools` | List available tools |
| POST | `/v1/mcp/invoke` | Invoke tool directly |

### Tasks (HITL)
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/v1/tasks` | List pending approvals |
| POST | `/v1/tasks/{plan}/{step}/approve` | Approve task |
| POST | `/v1/tasks/{plan}/{step}/reject` | Reject task |

## Adding Agents

Create a YAML file in `registry/agents/`:

```yaml
id: my_agent
name: My Agent
type: execution_agent  # spec_agent, execution_agent, support_agent
description: What this agent does
priority: 1.0

instructions: |
  System prompt for this agent...

skills:
  - skill_one
  - skill_two

tools:
  - filesystem.read_file
  - filesystem.write_file
```

## Adding MCP Servers

Create a YAML file in `registry/mcp/`:

```yaml
id: my_server
name: My Server
description: What this server does
transport: stdio
command: python
args:
  - -m
  - mymodule.server

tools:
  - name: my_tool
    description: What this tool does
    input_schema:
      type: object
      properties:
        param1:
          type: string
```

## Execution Flow

```
1. User submits request via POST /v1/chat/completions
   │
2. Router analyzes intent
   │
   ├─► general_chat? → Direct response, done
   │
3. Planner selects agents
   │
4. Planner generates steps
   │
5. Task Manager starts execution
   │
   ├─► For each step:
   │   ├─► Check dependencies
   │   ├─► Get executor from dispatcher
   │   ├─► Execute step
   │   ├─► If HITL required, wait for approval
   │   └─► Update results
   │
6. Plan completed
```

## Comparison with Go Codebase

| Aspect | Go (original) | Python (this) |
|--------|---------------|---------------|
| Framework | Custom | LangGraph-compatible |
| Architecture | Similar | Similar (Router → Planner → Executor) |
| Agents | YAML + Go code | YAML + Python code |
| Tools | Skills + MCP | MCP only |
| Complexity | Higher | Moderate |
| Extensibility | Requires Go | Standard Python |

## License

MIT
