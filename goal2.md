# AI Governance Platform - Complete Detailed Specification

## **Core Architecture**

### **1. Infrastructure Stack**
```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          Docker Host                                        │
├─────────────────────────────────────────────────────────────────────────────┤
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │                          K3s Cluster                                 │  │
│  │  ┌─────────────────┐  ┌─────────────────┐  ┌──────────────────┐     │  │
│  │  │   Control Plane │  │     PostgreSQL  │  │     Keycloak     │     │  │
│  │  │   (k3s server)  │  │  ┌───────────┐  │  │ • SSO Auth       │     │  │
│  │  │                 │  │  │  App DB   │  │  │ • OBO Tokens     │     │  │
│  │  └─────────────────┘  │  └───────────┘  │  │ • User Management│     │  │
│  │                       │  ┌───────────┐  │  └──────────────────┘     │  │
│  │  ┌─────────────────┐  │  │Keycloak DB│  │                           │  │
│  │  │   Worker Node   │  │  └───────────┘  │  ┌──────────────────┐     │  │
│  │  │  (k3s agent)    │  │  ┌───────────┐  │  │      Gitea       │     │  │
│  │  └─────────────────┘  │  │  Gitea DB │  │  │ • User Repos     │     │  │
│  │                       │  └───────────┘  │  │ • Branch Mgmt    │     │  │
│  │  ┌─────────────────┐  └─────────────────┘  └──────────────────┘     │  │
│  │  │   PostgreSQL    │                                                 │  │
│  │  │ • Agent State   │  ┌─────────────────┐  ┌──────────────────┐     │  │
│  │  │ • Message Queue │  │  Flask Backend  │  │  Vite Frontend   │     │  │
│  │  └─────────────────┘  │ • REST API      │  │ • Dashboard      │     │  │
│  │                       │ • WebSockets    │  │ • Chat Interface │     │  │
│  │  ┌─────────────────┐  │ • Auth          │  │ • Approval UI    │     │  │
│  │  │  MCP Gateway    │  └─────────────────┘  └──────────────────┘     │  │
│  │  │ • Central Auth  │                                                 │  │
│  │  │ • Permission    │  ┌─────────────────┐  ┌──────────────────┐     │  │
│  │  │ • Tool Routing  │  │Agent Orchestrator│ │   Agent Pool     │     │  │
│  │  └─────────────────┘  │ • Workflow Mgmt │ │ • Long-running   │     │  │
│  │                       │ • Agent Control │ │ • YAML-defined    │     │  │
│  │  ┌─────────────────┐  └─────────────────┘ └──────────────────┘     │  │
│  │  │   Sandbox       │                                                 │  │
│  │  │ • Code Exec     │  ┌─────────────────┐  ┌──────────────────┐     │  │
│  │  │ • K8s Isolation │  │  Nginx Ingress  │  │  MCP Servers     │     │  │
│  │  └─────────────────┘  │ • Routing       │  │ • Coding MCP     │     │  │
│  │                       │ • SSL/TLS       │  │ • Git MCP        │     │  │
│  │                       └─────────────────┘  │ • Ask User MCP   │     │  │
│  │                                            │ • Deployment MCP │     │  │
│  │                                            └──────────────────┘     │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
```

### **2. MCP Server Ecosystem**

#### **Core MCP Servers (Required from Day 1):**

**1. Coding MCP**
```
Endpoint: mcp://coding/
Tools:
  • write_file(path, content, overwrite) → needs approval for some agents
  • read_file(path) → always allowed
  • execute_command(command, cwd, timeout) → sandboxed, needs approval
  • list_files(directory) → always allowed
  • install_packages(packages) → needs approval
  • create_project_structure(template) → always allowed
Permissions: Default no approval, agent-specific overrides possible
```

**2. Git MCP** (Gitea Integration)
```
Endpoint: mcp://git/
Tools:
  • create_repository(name, description, private) → auto for user repos
  • create_branch(repo, from_branch, new_branch) → always allowed
  • commit_changes(repo, branch, message, files) → needs approval
  • push_changes(repo, branch) → always allowed
  • create_pull_request(repo, from_branch, to_branch, title) → needs approval
  • merge_pull_request(pr_id) → needs approval from infra engineer
  • get_repository_status(repo) → always allowed
```

**3. Ask User MCP** (Human-in-the-loop)
```
Endpoint: mcp://ask-user/
Tools:
  • ask_question(question, options, timeout) → waits for user response
  • request_approval(context, deadline) → creates approval task
  • notify_user(message, urgency) → sends notification
  • upload_file(prompt, accepted_types) → requests file from user
Special: Maintains state across days, can resume conversations
```

**4. Deployment MCP**
```
Endpoint: mcp://deploy/
Tools:
  • deploy_project(repo, branch, environment) → needs infra approval
  • get_deployment_status(deployment_id) → always allowed
  • scale_deployment(deployment_id, replicas) → needs infra approval
  • get_logs(deployment_id, lines) → always allowed
  • stop_deployment(deployment_id) → needs infra approval
  • create_preview_url(project, branch) → always allowed
```

**5. Documentation MCP** (External/Context7)
```
Endpoint: mcp://documentation/
Tools:
  • search_docs(query, sources) → external API call
  • get_api_reference(technology, version) → external
  • get_best_practices(topic) → external
Permissions: No approval needed, external service
```

**6. Agent MCP** (Agent-to-Agent Communication)
```
Endpoint: mcp://agent/
Tools:
  • call_agent(agent_id, task, context) → triggers another agent
  • get_agent_status(agent_instance_id) → check status
  • cancel_agent_task(task_id) → stop execution
Special: Orchestrator manages the handoffs
```

**7. File Storage MCP** (Future: SharePoint integration)
```
Endpoint: mcp://storage/
Tools:
  • list_files(path) → with OBO user tokens
  • upload_file(path, content) → with OBO
  • download_file(path) → with OBO
  • share_file(path, users) → with OBO
Permissions: User-context specific via OBO tokens
```

### **3. Complete Workflow Details**

#### **Create Project Flow:**
```
1. User Message: "Create a React dashboard for sales data"
   ↓
2. Router Agent: Classifies as "create_project" intent
   ↓
3. Planner Agent: Creates execution plan:
   ┌─────────────────────────────────────────────────────┐
   │ 1. Business Analyst: Talk to user, gather details   │
   │ 2. Architect: Create technical design               │
   │ 3. Developer: Write code                            │
   │ 4. Deployment: Deploy to preview                    │
   └─────────────────────────────────────────────────────┘
   ↓
4. Business Analyst Agent (via Ask User MCP):
   • Asks clarifying questions: "What charts needed? Auth required?"
   • Creates functional specification document
   • Requests user approval via Approval Dashboard
   ↓
5. Architect Agent (if approved):
   • Creates technical design using Documentation MCP
   • Defines stack: React + TypeScript + Tailwind + API
   • Creates architecture diagram
   • Triggers approval from Architect role users
   ↓
6. Developer Agent (if approved):
   • Creates project structure via Coding MCP
   • Writes components, tests, configuration
   • Commits to Gitea via Git MCP (user's repo)
   • Runs tests in sandbox
   ↓
7. Deployment Agent:
   • Creates preview deployment via Deployment MCP
   • Gets URL: jan-sales-dashboard.preview.platform.com
   • Triggers approval from Infra Engineer role
   ↓
8. Final Deployment (if approved):
   • Deploys to production: jan-sales-dashboard.platform.com
   • User notified with live URL and repo link
```

#### **Update Project Flow:**
```
1. User: "Add dark mode to my sales dashboard"
   ↓
2. Router: Sees user has project "sales-dashboard", intent "update_project"
   ↓
3. Planner: Creates update plan:
   ┌─────────────────────────────────────────────────────┐
   │ 1. Developer: Create feature branch                 │
   │ 2. Developer: Implement dark mode                   │
   │ 3. Deployment: Deploy to preview                    │
   │ 4. Business Analyst: Get user testing feedback      │
   │ 5. Deployment: Merge and redeploy if approved       │
   └─────────────────────────────────────────────────────┘
   ↓
4. Developer Agent:
   • Creates branch: feature/dark-mode-123
   • Implements changes using Coding MCP
   • Commits to branch via Git MCP
   ↓
5. Deployment Agent:
   • Deploys branch to preview: jan-sales-dashboard-dark-mode.preview...
   ↓
6. Business Analyst:
   • Asks user to test via Ask User MCP
   • "Please test the dark mode at [URL]. Type 'approve' if good."
   ↓
7. If user approves:
   • Git MCP merges branch to main
   • Deployment MCP redeploys main
   • Branch marked as merged in database
```

### **4. Detailed Agent Specifications**

#### **Business Analyst Agent:**
```yaml
agent_id: business_analyst
name: "Business Analyst"
description: "Gathers detailed requirements and creates functional specifications"

llm:
  provider: deepinfra
  model: llama-3-70b-instruct
  max_tokens: 8000
  temperature: 0.3
  max_iterations: 15

tools:
  - mcp_server: "ask_user"
    tool_name: "ask_question"
    requires_approval: false
    
  - mcp_server: "ask_user"
    tool_name: "request_approval"
    requires_approval: false
    
  - mcp_server: "documentation"
    tool_name: "search_docs"
    requires_approval: false
    
  - mcp_server: "coding"
    tool_name: "write_file"
    requires_approval: true
    approval_rules:
      - entity_type: "role"
        entity_value: "architect"
        count: 1

prompt_template: |
  You are an expert Business Analyst for software projects.
  
  PROJECT: {project_name}
  USER REQUEST: {user_request}
  
  Your tasks:
  1. Ask clarifying questions to understand:
     • Business goals
     • User personas
     • Functional requirements
     • Non-functional requirements
     • Success criteria
     
  2. Create a detailed functional specification including:
     • User stories
     • Wireframes/descriptions
     • Data models
     • API endpoints needed
     
  3. Get formal approval from the user.
  
  4. Once approved, pass to Architect agent with complete context.
  
  Available tools: {available_tools}
  Conversation history: {history}
  
  Instructions: Be thorough, ask one question at a time, document everything.
```

#### **Architect Agent:**
```yaml
agent_id: architect
name: "Technical Architect"
description: "Creates technical designs and architecture specifications"

llm:
  provider: glm
  model: glm-4-plus
  max_tokens: 12000
  temperature: 0.2
  max_iterations: 10

tools:
  - mcp_server: "documentation"
    tool_name: "search_docs"
    
  - mcp_server: "documentation"
    tool_name: "get_best_practices"
    
  - mcp_server: "coding"
    tool_name: "write_file"
    requires_approval: true
    approval_rules:
      - entity_type: "role"
        entity_value: "architect"
        count: 1
      - entity_type: "role"
        entity_value: "senior_developer"
        count: 1
  
  - mcp_server: "agent"
    tool_name: "call_agent"
    parameters:
      allowed_agents: ["developer"]

prompt_template: |
  You are a Senior Technical Architect.
  
  PROJECT: {project_name}
  FUNCTIONAL SPEC: {functional_spec}
  
  Your tasks:
  1. Analyze requirements and create technical design:
     • Technology stack selection
     • System architecture diagram
     • Database schema
     • API design
     • Deployment architecture
     • Security considerations
     
  2. Create detailed technical specification document.
  
  3. The specification MUST be approved by architect role users.
  
  4. Once approved, trigger Developer agent with complete technical plan.
  
  Constraints:
  • Must use approved technologies from platform stack
  • Must include monitoring and logging
  • Must consider scalability from day 1
  • Must document all decisions
```

#### **Developer Agent:**
```yaml
agent_id: developer
name: "Full Stack Developer"
description: "Implements code based on technical specifications"

llm:
  provider: glm
  model: glm-4-coding
  max_tokens: 16000
  temperature: 0.1
  max_iterations: 20

tools:
  - mcp_server: "coding"
    tool_name: "write_file"
    requires_approval: true
    approval_rules:
      - entity_type: "role"
        entity_value: "senior_developer"
        count: 1
  
  - mcp_server: "coding"
    tool_name: "execute_command"
    requires_approval: true
    approval_rules:
      - entity_type: "role"
        entity_value: "infra_engineer"
        count: 1
  
  - mcp_server: "git"
    tool_name: "create_branch"
    
  - mcp_server: "git"
    tool_name: "commit_changes"
    requires_approval: true
    approval_rules:
      - entity_type: "role"
        entity_value: "senior_developer"
        count: 1
  
  - mcp_server: "agent"
    tool_name: "call_agent"
    parameters:
      allowed_agents: ["deployment"]

prompt_template: |
  You are a Senior Full Stack Developer.
  
  PROJECT: {project_name}
  TECHNICAL DESIGN: {technical_design}
  
  Your tasks:
  1. Implement the complete application:
     • Set up project structure
     • Write all components/services
     • Implement tests
     • Configure CI/CD
     
  2. Work in a sandboxed environment.
  
  3. All file writes need senior developer approval.
  
  4. All command execution needs infra engineer approval.
  
  5. Commit changes to Git branch.
  
  6. Once complete, trigger Deployment agent.
  
  Coding standards:
  • TypeScript for frontend
  • Python/Flask for backend
  • Tailwind CSS for styling
  • PostgreSQL for database
  • Docker for containerization
  • Include comprehensive tests
  • Document all complex logic
```

#### **Deployment Agent:**
```yaml
agent_id: deployment
name: "Deployment Engineer"
description: "Manages deployment and infrastructure"

llm:
  provider: deepinfra
  model: llama-3-70b-instruct
  max_tokens: 4000
  temperature: 0.1
  max_iterations: 8

tools:
  - mcp_server: "deploy"
    tool_name: "deploy_project"
    requires_approval: true
    approval_rules:
      - entity_type: "role"
        entity_value: "infra_engineer"
        count: 1
  
  - mcp_server: "deploy"
    tool_name: "create_preview_url"
    
  - mcp_server: "git"
    tool_name: "merge_pull_request"
    requires_approval: true
    approval_rules:
      - entity_type: "role"
        entity_value: "infra_engineer"
        count: 1
  
  - mcp_server: "ask_user"
    tool_name: "notify_user"

prompt_template: |
  You are a Deployment Engineer.
  
  PROJECT: {project_name}
  BRANCH: {branch_name}
  REPO: {repo_url}
  
  Your tasks:
  1. Deploy the project/branch to appropriate environment.
  2. Generate preview URL for testing.
  3. Notify relevant users of deployment.
  4. Monitor deployment status.
  5. Handle merge to main after approval.
  
  Rules:
  • Production deployments need infra engineer approval
  • Branch merges need infra engineer approval
  • Always create preview URLs for feature branches
  • Notify Business Analyst when deployment is ready for user testing
```

### **5. Approval System Details**

#### **Approval Dashboard Features:**
```
┌─────────────────────────────────────────────────────────────────┐
│                        APPROVAL DASHBOARD                       │
├─────────────────────────────────────────────────────────────────┤
│ Pending Approvals (3)                                           │
│ ┌─────────────────────────────────────────────────────────────┐ │
│ │ 1. Architect Approval - Technical Design                    │ │
│ │    Project: Sales Dashboard                                 │ │
│ │    Requested by: Business Analyst Agent                     │ │
│ │    Required: 1 Architect                                    │ │
│ │    [View Design] [Approve] [Reject with Reason]             │ │
│ └─────────────────────────────────────────────────────────────┘ │
│                                                                 │
│ │ 2. Senior Developer Approval - Code Implementation          │ │
│ │    Project: Sales Dashboard                                 │ │
│ │    File: src/components/Dashboard.tsx                       │ │
│ │    Diff: +120 lines, -15 lines                              │ │
│ │    Required: 1 Senior Developer                             │ │
│ │    [View Diff] [Approve] [Request Changes]                  │ │
│ └─────────────────────────────────────────────────────────────┘ │
│                                                                 │
│ Approval History                                                │
│ ┌─────────────────────────────────────────────────────────────┐ │
│ │ Date       | Role          | Project       | Decision       │ │
│ │ 2024-01-15 | Architect     | CRM System    | Approved       │ │
│ │ 2024-01-14 | Infra Engineer| API Gateway   | Rejected       │ │
│ └─────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

#### **Approval Rules Configuration:**
```yaml
# In agent.yaml or separate approval_rules.yaml
approval_config:
  default_timeout: "72h"  # Auto-reject if not approved
  
  rules:
    technical_design:
      name: "Technical Design Approval"
      triggers: ["architect.write_file"]
      requirements:
        - role: "architect"
          count: 1
        - role: "senior_developer"
          count: 1
      sequential: false
      
    production_deployment:
      name: "Production Deployment Approval"
      triggers: ["deployment.deploy_project"]
      requirements:
        - role: "infra_engineer"
          count: 2
        - specific_user: "security_lead@company.com"
          count: 1
      sequential: true  # Infra first, then security
      
    critical_code_change:
      name: "Critical Code Change"
      triggers: ["developer.write_file"]
      when: "file_path matches 'src/core/**'"
      requirements:
        - role: "senior_developer"
          count: 2
        - role: "architect"
          count: 1
```

### **6. OBO Token Flow Implementation**

```
┌─────────┐   1. Login     ┌──────────┐   2. Store     ┌──────────┐
│  User   │───────────────▶│ Keycloak │───────────────▶│PostgreSQL│
│         │◀────Tokens─────│          │◀─Session Data─│          │
└─────────┘                └──────────┘                └──────────┘
                                                              │
┌──────────┐   6. Return    ┌──────────┐   5. Call MCP   │   3. Request
│   User   │◀───Results─────│   Agent  │◀────with───────┼───Token
│  Browser │                │          │     Token      │
└──────────┘                └──────────┘                ▼
                             4. Validate/Refresh  ┌──────────┐
                                                  │ MCP Gateway│
                                                  │ • Validate │
                                                  │ • Log      │
                                                  │ • Route    │
                                                  └──────────┘
                                                        │
                                                  ┌──────────┐
                                                  │  MCP     │
                                                  │ Server   │
                                                  └──────────┘
```

**Token Management Service:**
```python
class TokenManager:
    def get_user_token(user_id: str, mcp_server: str) -> str:
        # 1. Check PostgreSQL for valid token
        # 2. If expired, refresh using refresh_token
        # 3. If refresh fails, force user re-auth
        # 4. Return fresh token with MCP permissions
        # 5. Log token usage for audit
```

### **7. Cost Tracking & Analytics**

#### **Metrics Tracked:**
```
┌─────────────────────────────────────────────────────────────┐
│                     COST DASHBOARD                          │
├─────────────────────────────────────────────────────────────┤
│ Total This Month: $243.78                                   │
│                                                             │
│ Breakdown by Project:                                       │
│ • Sales Dashboard: $124.50 (2,450,000 tokens)              │
│   - Business Analyst: $45.20 (890K tokens)                 │
│   - Architect: $32.10 (630K tokens)                        │
│   - Developer: $47.20 (930K tokens)                        │
│                                                             │
│ Breakdown by LLM Provider:                                  │
│ • DeepInfra: $156.30 (Llama-3-70b)                         │
│ • GLM: $87.48 (GLM-4-Coding)                               │
│                                                             │
│ Token Efficiency:                                           │
│ • Input tokens: 1,840,000 (75%)                            │
│ • Output tokens: 613,333 (25%)                             │
│ • Cost per 1K tokens: $0.099                               │
└─────────────────────────────────────────────────────────────┘
```

#### **Database Tables for Cost Tracking:**
```sql
-- Detailed token tracking
CREATE TABLE llm_usage (
    id UUID PRIMARY KEY,
    agent_task_id UUID,
    provider VARCHAR(50),
    model VARCHAR(100),
    prompt_tokens INTEGER,
    completion_tokens INTEGER,
    total_tokens INTEGER,
    cost DECIMAL(10,6),
    timestamp TIMESTAMP
);

-- MCP call tracking
CREATE TABLE mcp_usage (
    id UUID PRIMARY KEY,
    tool_call_id UUID,
    mcp_server VARCHAR(100),
    tool_name VARCHAR(200),
    duration_ms INTEGER,
    success BOOLEAN,
    error_message TEXT,
    token_usage INTEGER, -- if MCP uses tokens
    timestamp TIMESTAMP
);

-- Resource usage (K8s)
CREATE TABLE resource_usage (
    id UUID PRIMARY KEY,
    project_id UUID,
    container_name VARCHAR(200),
    cpu_seconds DECIMAL(10,2),
    memory_mb INTEGER,
    network_bytes INTEGER,
    storage_bytes INTEGER,
    cost DECIMAL(10,6),
    period_start TIMESTAMP,
    period_end TIMESTAMP
);
```

### **8. Debug & Monitoring Panel**

```
┌─────────────────────────────────────────────────────────────────┐
│                    DEBUG PANEL - Conversation 123               │
├─────────────────────────────────────────────────────────────────┤
│ Conversation Flow:                                              │
│ ┌──────┐    ┌──────────┐    ┌─────────┐    ┌──────────┐       │
│ │User  │───▶│Business  │───▶│Architect│───▶│Developer │       │
│ │Input │    │Analyst   │    │(Waiting)│    │(Pending) │       │
│ └──────┘    └──────────┘    └─────────┘    └──────────┘       │
│                                                                 │
│ Agent Execution Details:                                        │
│ • Business Analyst Agent                                        │
│   - Duration: 2m 34s                                            │
│   - Tokens: 12,450 ($0.42)                                     │
│   - Tool Calls:                                                 │
│     1. ask_user: "What charts do you need?"                    │
│     2. ask_user: "Should it have user authentication?"         │
│     3. write_file: Created functional_spec.md                  │
│                                                                 │
│ Current State:                                                  │
│ • Waiting for Architect approval                                │
│ • Approval ID: 456                                              │
│ • Required approvers: 1 Architect                               │
│ • Timeout: 48h from now                                         │
│                                                                 │
│ Full Context Window (last 10K tokens):                          │
│ [User]: Create sales dashboard                                  │
│ [BA]: What timeframe for data?                                  │
│ [User]: Last 12 months                                          │
│ ...                                                             │
└─────────────────────────────────────────────────────────────────┘
```

### **9. One-Command Setup Script**

```bash
#!/bin/bash
# setup.sh - Complete AI Governance Platform Installation

echo "🚀 Starting AI Governance Platform Setup..."
echo "=========================================="

# 1. Check prerequisites
echo "🔍 Checking prerequisites..."
docker --version || { echo "Docker not installed"; exit 1; }
docker compose version || { echo "Docker Compose not installed"; exit 1; }

# 2. Create directory structure
echo "📁 Creating directory structure..."
mkdir -p {database,backend,frontend,agents,mcps,kubernetes,scripts,logs}

# 3. Generate configuration files
echo "⚙️  Generating configuration files..."
cat > .env << EOF
# Platform Configuration
PLATFORM_DOMAIN=localhost
PLATFORM_HTTPS=false

# Database
POSTGRES_APP_DB=ai_governance
POSTGRES_APP_USER=platform
POSTGRES_APP_PASSWORD=$(openssl rand -hex 16)

POSTGRES_KEYCLOAK_DB=keycloak
POSTGRES_KEYCLOAK_USER=keycloak
POSTGRES_KEYCLOAK_PASSWORD=$(openssl rand -hex 16)

POSTGRES_GITEA_DB=gitea
POSTGRES_GITEA_USER=gitea
POSTGRES_GITEA_PASSWORD=$(openssl rand -hex 16)

# Keycloak
KEYCLOAK_ADMIN=admin
KEYCLOAK_ADMIN_PASSWORD=$(openssl rand -hex 16)
KEYCLOAK_FRONTEND_URL=http://localhost:8080

# Gitea
GITEA_ADMIN_USER=platform-admin
GITEA_ADMIN_PASSWORD=$(openssl rand -hex 16)
GITEA_DOMAIN=gitea.localhost

# PostgreSQL (for agent state and message queue)
POSTGRES_STATE_DB=agent_state
POSTGRES_STATE_USER=agent_state
POSTGRES_STATE_PASSWORD=$(openssl rand -hex 16)

# LLM Providers
DEEPINFRA_API_KEY=${DEEPINFRA_API_KEY:-""}
GLM_API_KEY=${GLM_API_KEY:-""}

# MCP Gateway
MCP_GATEWAY_SECRET=$(openssl rand -hex 32)
EOF

# 4. Generate docker-compose.yml
echo "🐳 Generating Docker Compose configuration..."
# [Will output the full docker-compose.yml]

# 5. Generate database initialization
echo "🗄️  Creating database schemas..."
# [Will output init.sql]

# 6. Generate Kubernetes manifests
echo "☸️  Generating Kubernetes manifests..."
# [Will output k8s deployment files]

# 7. Generate agent configurations
echo "🤖 Creating default agent configurations..."
mkdir -p agents/configs
# [Will output agent YAML files]

# 8. Generate MCP server configurations
echo "🔌 Configuring MCP servers..."
mkdir -p mcps/servers
# [Will output MCP server configs]

# 9. Start the platform
echo "🚀 Starting platform..."
docker compose up -d

echo ""
echo "✅ Setup complete!"
echo ""
echo "📋 Access URLs:"
echo "   • Platform Frontend: http://localhost:5173"
echo "   • Keycloak Admin:    http://localhost:8080/admin"
echo "   • Gitea:             http://localhost:3000"
echo "   • API Documentation: http://localhost:5000/docs"
echo ""
echo "🔑 Initial credentials:"
echo "   • Keycloak: admin / $(grep KEYCLOAK_ADMIN_PASSWORD .env | cut -d= -f2)"
echo "   • Gitea:    platform-admin / $(grep GITEA_ADMIN_PASSWORD .env | cut -d= -f2)"
echo ""
echo "📝 Next steps:"
echo "   1. Access Keycloak and configure realm"
echo "   2. Set up LLM API keys in platform settings"
echo "   3. Create initial users and roles"
echo "   4. Start your first project!"
```

### **10. File Structure (Complete)**
ai-governance-platform/
├── docker-compose.yml                    # Single Docker Compose with K3s
├── setup.sh                             # One-command setup script
├── .env                                 # Environment variables
├── .env.example                         # Example env file
├── README.md                            # Setup and usage instructions
├── database/
│   └── schema.sql                      # Single source of truth for database
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── src/
│       ├── main.py                     # Flask app entry point
│       ├── config.py                   # Configuration
│       ├── models.py                   # All SQLAlchemy models
│       ├── auth.py                     # Keycloak authentication
│       ├── api/
│       │   ├── __init__.py
│       │   ├── auth.py                # Auth endpoints
│       │   ├── projects.py            # Project management
│       │   ├── conversations.py       # Chat/conversation endpoints
│       │   ├── agents.py              # Agent management
│       │   └── approvals.py           # Approval system
│       ├── services/
│       │   ├── agent_orchestrator.py  # Manages agent execution flow
│       │   ├── mcp_gateway.py         # Central MCP gateway
│       │   ├── token_manager.py       # OBO token handling
│       │   ├── cost_tracker.py        # Token/cost tracking
│       │   ├── gitea_client.py        # Gitea integration
│       │   └── deployment_service.py  # K8s deployment
│       └── agents/
│           ├── base_agent.py          # Base agent class
│           ├── business_analyst.py
│           ├── architect.py
│           ├── developer.py
│           ├── deployment.py
│           ├── router.py              # Intent router
│           └── planner.py             # Workflow planner
├── frontend/
│   ├── Dockerfile
│   ├── package.json
│   ├── vite.config.ts
│   ├── tsconfig.json
│   ├── index.html
│   └── src/
│       ├── main.ts
│       ├── App.vue
│       ├── router.ts
│       ├── stores/                    # Pinia stores
│       │   ├── auth.ts
│       │   ├── projects.ts
│       │   └── conversations.ts
│       ├── components/
│       │   ├── ui/                    # ShadCN components
│       │   ├── Button.vue
│       │   ├── Card.vue
│       │   ├── Dialog.vue
│       │   ├── Table.vue
│       │   └── ...
│       │   ├── layout/
│       │   │   ├── Header.vue
│       │   │   ├── Sidebar.vue
│       │   │   └── MainLayout.vue
│       │   ├── chat/
│       │   │   ├── ChatWindow.vue
│       │   │   ├── MessageBubble.vue
│       │   │   ├── AgentMessage.vue
│       │   │   └── ToolCall.vue
│       │   ├── dashboard/
│       │   │   ├── ProjectCard.vue
│       │   │   ├── CostChart.vue
│       │   │   └── StatusBadge.vue
│       │   └── approvals/
│       │       ├── ApprovalQueue.vue
│       │       ├── ApprovalCard.vue
│       │       └── ApprovalDecision.vue
│       └── pages/
│           ├── Dashboard.vue
│           ├── Projects.vue
│           ├── ProjectDetail.vue
│           ├── Conversation.vue
│           ├── Approvals.vue
│           └── Settings.vue
├── agents/
│   ├── configs/                       # Agent YAML configurations
│   │   ├── business_analyst.yaml
│   │   ├── architect.yaml
│   │   ├── developer.yaml
│   │   ├── deployment.yaml
│   │   ├── router.yaml
│   │   └── planner.yaml
│   └── prompts/                       # Prompt templates
│       ├── business_analyst.txt
│       ├── architect.txt
│       ├── developer.txt
│       └── deployment.txt
├── mcps/
│   ├── gateway/                       # MCP Gateway service
│   │   ├── Dockerfile
│   │   ├── server.py
│   │   ├── auth.py
│   │   └── config.yaml               # MCP server registry
│   └── servers/                       # Built-in MCP servers
│       ├── coding/
│       │   ├── Dockerfile
│       │   ├── server.py
│       │   └── tools.py
│       ├── git/
│       │   ├── Dockerfile
│       │   ├── server.py
│       │   └── gitea_client.py
│       ├── ask_user/
│       │   ├── Dockerfile
│       │   ├── server.py
│       │   └── websocket_handler.py
│       ├── deploy/
│       │   ├── Dockerfile
│       │   ├── server.py
│       │   └── kubernetes_client.py
│       └── documentation/
│           ├── Dockerfile
│           ├── server.py
│           └── context7_client.py
├── kubernetes/                        # K3s manifests
│   ├── namespace.yaml
│   ├── deployments/
│   │   ├── backend.yaml
│   │   ├── frontend.yaml
│   │   └── mcp-gateway.yaml
│   ├── services/
│   │   ├── backend.yaml
│   │   ├── frontend.yaml
│   │   └── mcp-gateway
