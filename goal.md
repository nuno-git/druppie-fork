# **Druppie: The Complete Development Platform with Unified Interface**

## **Ultimate Goal Vision**

Build **a complete development platform with multiple unified interfaces** where users can manage projects through natural conversation as the primary mode, while having full visibility and control through dedicated project management interfaces. The system seamlessly blends conversational AI with traditional development tooling.

---

## **The Complete Interface Ecosystem**

### **1. Multi-Interface Platform**
**Not just chat** - but chat as the **primary interaction mode** with full support interfaces:

```
┌─────────────────────────────────────────────────────────────────┐
│                          DRUPPIE PLATFORM                        │
│                                                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│  │    CHAT      │  │   PROJECTS   │  │     APPROVALS        │  │
│  │  Interface   │  │   Dashboard  │  │     Dashboard        │  │
│  │              │  │              │  │                      │  │
│  │ • Conversations│ • All projects │ • Pending approvals    │  │
│  │ • Natural lang│ • Quick stats  │ • Approval history     │  │
│  │ • Work status │ • Create new   │ • Team approvals       │  │
│  │ • Inline apps │ • Search/filter│ • Compliance tracking  │  │
│  └──────┬───────┘  └──────┬───────┘  └──────────┬───────────┘  │
│         │                  │                     │              │
│  ┌──────┴───────┐  ┌──────┴───────┐  ┌──────────┴───────────┐  │
│  │    DEBUG     │  │    PROJECT    │  │      SETTINGS       │  │
│  │    PANEL     │  │    DETAIL     │  │                     │  │
│  │              │  │              │  │                      │  │
│  │ • Full trace │ • Overview      │ • User management     │  │
│  │ • LLM calls  │ • Repository    │ • Permission config   │  │
│  │ • Tool execs │ • Environments  │ • Integration setup   │  │
│  │ • State      │ • History       │ • Security settings   │  │
│  │ • Audit log  │ • Conversations │ • Compliance rules    │  │
│  └──────────────┘  └──────────────┘  └──────────────────────┘  │
│                                                                  │
│                    ALL INTERFACES SHARE:                        │
│                    • Same backend engine                        │
│                    • Same agent system                          │
│                    • Same MCP tools                             │
│                    • Same approval flows                        │
│                    • Same audit trail                           │
│                    • Same project context                       │
└─────────────────────────────────────────────────────────────────┘
```

### **2. Chat: The Primary Interface (But Not The Only One)**
**Where you DO the work:**
- Natural language conversations with AI team
- Real-time progress updates as work happens
- Inline approval requests and decisions
- Agent questions and clarifications
- Code review and feedback
- Deployment status and URLs

**Projects Page: Where you MANAGE the work:**
- Overview of all projects (grid/list view)
- Quick stats: last activity, deployment status, open items
- Create new projects
- Search and filter projects
- Jump to project detail or start conversation

**Project Detail Page: Where you SEE the work:**
- Overview: description, tech stack, status
- Repository: commits, branches, PRs (integrated Gitea)
- Environments: preview URLs, production URLs, status
- History: timeline of all major actions
- Conversations: all chats about this project
- Settings: team, permissions, integrations

**Approvals Dashboard: Where you CONTROL the work:**
- Pending approvals requiring your action
- Approvals you've requested (and their status)
- Approval history and audit trail
- Filter by project, type, urgency
- Team-wide approval tracking

**Debug Panel: Where you UNDERSTAND the work:**
- Full execution trace of any conversation
- Every LLM call, tool execution, state change
- Expandable details at every level
- Search, filter, export capabilities
- Compliance and audit support

**Settings: Where you CONFIGURE the work:**
- User and team management
- Permission configurations
- Integration setup (Git, Docker, etc.)
- Security and compliance rules
- Platform-wide settings

### **3. Seamless Interface Transitions**
**Example User Journey:**
1. **Projects Page** → See all projects, click on "Inventory System"
2. **Project Detail** → Review current status, check recent commits
3. **Chat** → "Add user management with roles" → Work happens conversationally
4. **Approvals Dashboard** → Get notified when production deploy needs approval
5. **Debug Panel** → Investigate why a test failed during implementation
6. **Back to Chat** → "Also add audit logging" → Continue conversation

**Every interface shares:**
- Same project context
- Same user identity (Keycloak)
- Same MCP tool access
- Same approval rules
- Same audit trail

### **4. Interface-Specific Superpowers**

**Chat Interface:**
- Agent attribution (know who you're talking to)
- Rich message formatting with code blocks
- Inline file previews and diffs
- Real-time progress indicators
- Interactive approval buttons
- Collapsible detail sections

**Projects Interface:**
- Visual project status dashboard
- Quick action buttons (deploy, review, etc.)
- Team collaboration views
- Activity feeds across projects
- Health metrics and alerts

**Cross-Interface Features:**
- **Deep linking**: Click project in Projects → opens Chat about that project
- **Notifications**: Approval needed → appears in Approvals AND as chat notification
- **Context preservation**: Start in Chat, switch to Projects, return to same conversation
- **Real-time sync**: Changes in one interface instantly reflect in others

### **5. The Complete Development Lifecycle**

**Through Chat (Primary):**
```
User: "Build me a customer portal with authentication"
AI: [Conversation about requirements, implementation, deployment]
User: "Make the login form more accessible"
AI: [Updates made, preview provided]
```

**Through Projects (Management):**
- Monitor progress of all active developments
- Review code quality metrics
- Track deployment statuses
- Manage team permissions
- View project health dashboards

**Through Approvals (Governance):**
- Review and approve critical changes
- Track compliance requirements
- Monitor security-related actions
- Audit all approval decisions

**Through Debug (Transparency):**
- Understand exactly how decisions were made
- Troubleshoot issues with full context
- Verify compliance requirements met
- Learn from past implementations

### **6. The Unified Platform Experience**

**Key Principles:**
1. **Chat is primary but not exclusive** - Natural conversation for doing work
2. **Projects is for management** - Visual overview and control
3. **Approvals is for governance** - Security and compliance control
4. **Debug is for transparency** - Complete understanding and audit
5. **Settings is for configuration** - Platform and project setup

**Everything connects to:**
- Same agent orchestration engine
- Same MCP tool infrastructure
- Same state management system
- Same audit and compliance framework
- Same Druppie Core SDK for generated apps

### **7. The Complete Platform Value**

**For Developers/Users:**
- Start in Chat for natural development
- Switch to Projects for management
- Use Approvals for governance
- Check Debug for understanding
- All interfaces work together seamlessly

**For Organizations:**
- Natural language lowers barrier to development
- Multiple interfaces support different workflows
- Built-in governance at every level
- Complete audit trail across all interfaces
- Generated apps inherit the entire ecosystem

**The Result:**
A platform where you can **converse** your way through development, **manage** through visual interfaces, **govern** through approval workflows, and **understand** through complete transparency - all working together as one cohesive system.

---

## **Summary**

**Druppie is not "just a chat interface"** - it's a **complete development platform** where:
- **Chat** is where you *do* the work (primary interface)
- **Projects** is where you *manage* the work
- **Approvals** is where you *control* the work  
- **Debug** is where you *understand* the work
- **Settings** is where you *configure* the work

All interfaces share the same powerful backend: agent orchestration, MCP tools, state management, and governance - creating a seamless development experience from conversation to production.# **Druppie Technical Stack: Simple Yet Powerful Architecture**

## **Core Technical Philosophy**

We maintain extreme simplicity: **Agent-driven workflow with containerized MCPs, minimal dependencies, and straightforward setup**. The entire platform runs on a lightweight stack that's easy to understand, deploy, and maintain.

## **Technical Stack Components**

### **1. Infrastructure Layer**
- **Docker Compose**: Single `docker-compose.full.yml` that starts everything
- **PostgreSQL**: Main database for users, projects, approvals, audit trail
- **Redis**: State persistence, HITL pub/sub, real-time notifications
- **Keycloak**: Authentication and OBO token management
- **Gitea**: Git repositories for all projects

### **2. Core Platform (Python/FastAPI)**
- **FastAPI Backend**: Main application server
- **LangGraph/Agent Orchestration**: Simple router→planner→executor pattern
- **MCP Client**: HTTP client that communicates with MCP servers
- **State Management**: SQLAlchemy models with Redis for session state
- **WebSocket Server**: Real-time chat and notifications

### **3. MCP Layer (FastMCP Servers)**
Three specialized servers in separate containers:

1. **Coding MCP** (FastMCP on port 9001)
   - Workspace management with auto-initialization
   - File operations (read/write/list/delete)
   - Git integration with automatic commits
   - Shell command execution (with approval)
   - Branch and merge operations

2. **Docker MCP** (FastMCP on port 9002)
   - Container build operations
   - Container run/stop/management
   - Log retrieval
   - Docker Compose operations
   - Image management

3. **HITL MCP** (FastMCP on port 9003)
   - Human-in-the-loop questions via Redis pub/sub
   - State persistence for approval workflows
   - Progress reporting to frontend
   - Multi-day workflow resumption

### **4. Frontend Layer**
- **React/TypeScript**: Main web application
- **Chat Interface**: Primary conversation UI with agent attribution
- **Projects Dashboard**: Project management and overview
- **Approvals Interface**: Governance and compliance control
- **Debug Panel**: Full transparency and audit trail
- **WebSocket Client**: Real-time updates across all interfaces

### **5. Agent System**
- **YAML-based Definitions**: Simple agent configuration
- **Router Agent**: Intent recognition and conversation management
- **Planner Agent**: Work breakdown and specialist selection
- **Specialist Agents**: 7 core agents (Architect, Developer, Tester, etc.)
- **Skill Library**: Markdown files agents can reference
- **Workflow System**: YAML-defined multi-step processes

### **6. Druppie Core SDK**
- **JavaScript/TypeScript Package**: `@druppie/core`
- **Pre-configured Authentication**: Keycloak integration
- **MCP Client SDK**: Tool access from generated apps
- **Approval UI Components**: Consistent governance interface
- **Type-safe APIs**: Full TypeScript support

## **How Everything Fits Together**

### **Development Flow**
1. **User starts in Chat**: Natural conversation with router agent
2. **Router recognizes intent**: Determines new project, update, or question
3. **Planner creates plan**: Selects agents/workflows and custom instructions
4. **Agents execute via MCPs**: Only use registered tools (coding, docker, hitl)
5. **State persists throughout**: Redis + PostgreSQL for crash recovery
6. **Results appear in Chat**: Final deliverables presented conversationally

### **Technical Simplicity Wins**
- **No complex event systems**: Just HTTP calls between components
- **No message queues**: Redis pub/sub for real-time only
- **No service mesh**: Docker Compose networking is sufficient
- **No custom protocols**: Standard HTTP/WebSocket for everything
- **No complex deployments**: Single `docker-compose up` command

### **State Management Strategy**
- **Database**: PostgreSQL for structured data (users, projects, approvals)
- **Redis**: For session state, HITL messages, real-time notifications
- **Workspace Files**: Docker volumes for code repositories
- **Agent State**: LangGraph checkpoints persisted to database

### **Approval Workflow Technicals**
- **Tool-level configuration**: `mcp_config.yaml` defines approval requirements
- **State persistence**: Full agent state saved before pausing
- **Redis notifications**: Frontend notified of approval requests
- **Resume capability**: Exact continuation from saved state
- **Audit trail**: Every approval logged with full context

### **Generated App Integration**
- **Auto-included SDK**: `@druppie/core` in all generated apps
- **OBO token flow**: Apps act on behalf of logged-in user
- **Consistent MCP access**: Same tools as platform agents
- **Embeddable chat**: Apps can include Druppie chat interface
- **Unified permissions**: Same approval rules apply everywhere

## **Development and Testing Setup**

### **Local Development**
```bash
./setup.sh              # Starts everything
docker-compose logs -f  # Watch all services
# That's it - full platform running
```

### **Testing Strategy**
- **Unit tests**: Individual MCP server functionality
- **Integration tests**: Agent → MCP → Approval flows
- **E2E tests**: Full conversation flows with Playwright
- **Recovery tests**: Simulate crashes mid-approval
- **Performance tests**: Multiple concurrent conversations

### **Production Deployment**
- **Same docker-compose**: Just with production environment variables
- **Add Traefik/nginx**: For SSL termination and routing
- **Backup strategy**: Database and workspace volumes
- **Monitoring**: Basic health checks and logs
- **Scaling**: Add more backend instances if needed

## **Why This Stack Works**

### **Simplicity Advantages**
1. **Easy to understand**: Clear separation of concerns
2. **Easy to debug**: Logs show everything in one place
3. **Easy to deploy**: Single command setup
4. **Easy to extend**: Add new MCPs as needed
5. **Easy to maintain**: Minimal moving parts

### **Containerization Benefits**
- **Isolation**: Each MCP runs in its own container
- **Resource limits**: Control CPU/memory per component
- **Versioning**: Independent updates of components
- **Portability**: Works anywhere Docker runs
- **Networking**: Simple service discovery via Docker Compose

### **Agent-Centric Design**
- **Agents drive everything**: No complex backend logic
- **MCPs as capabilities**: Clear boundary for what's possible
- **State is king**: Everything persists, nothing is lost
- **Conversation is primary**: Natural language as the API
- **Governance is built-in**: Approval flows at tool level

## **The Complete Picture**

**Druppie is technically simple but functionally complete:**

- **Frontend**: React app with multiple interfaces
- **Backend**: FastAPI with agent orchestration  
- **MCPs**: 3 specialized servers in containers
- **Database**: PostgreSQL + Redis for state
- **Auth**: Keycloak with OBO token flow
- **Git**: Gitea for all repositories

**Everything connects via:**
- Standard HTTP calls (backend ↔ MCPs)
- WebSocket (frontend ↔ backend)
- Redis pub/sub (HITL ↔ frontend)
- Docker networking (containers ↔ each other)

**The result:** A platform that's **simple to run** but **powerful enough** to handle complex development workflows, with natural conversation as the primary interface and multiple supporting views for management, governance, and transparency.

One thing i might forgot to mention: the user should completely be able to see what happens, so router agent does x, planner makes plan ..., agent ,.. executes tool... and ttool2 and agent2 does..., etc..
