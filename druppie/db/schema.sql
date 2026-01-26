-- =============================================================================
-- Druppie Governance Platform - PostgreSQL Schema
-- Single source of truth for all database tables
-- =============================================================================
-- Version: 1.0.0
-- Keep it simple: No over-engineering, only what's needed for goal2.md
-- =============================================================================

-- =============================================================================
-- USERS & ROLES (synced from Keycloak)
-- =============================================================================

CREATE TABLE users (
    id UUID PRIMARY KEY,                    -- Keycloak user ID
    username VARCHAR(255) UNIQUE NOT NULL,
    email VARCHAR(255),
    display_name VARCHAR(255),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- User roles (simple: store as array or comma-separated in Keycloak, query from there)
-- We cache roles here for quick access
CREATE TABLE user_roles (
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    role VARCHAR(50) NOT NULL,              -- admin, architect, developer, infra_engineer, user
    PRIMARY KEY (user_id, role)
);

-- OBO tokens for external services (Gitea, SharePoint future)
CREATE TABLE user_tokens (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    service VARCHAR(100) NOT NULL,          -- gitea, sharepoint
    access_token TEXT NOT NULL,
    refresh_token TEXT,
    expires_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(user_id, service)
);

-- =============================================================================
-- PROJECTS (Gitea repositories)
-- =============================================================================

CREATE TABLE projects (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL,
    description TEXT,
    repo_name VARCHAR(255) NOT NULL,        -- Gitea repo name (org/repo)
    repo_url VARCHAR(512),                  -- Gitea web URL
    clone_url VARCHAR(512),                 -- Git clone URL
    owner_id UUID REFERENCES users(id),
    status VARCHAR(20) DEFAULT 'active',    -- active, archived
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_projects_owner ON projects(owner_id);

-- =============================================================================
-- SESSIONS & MESSAGES
-- =============================================================================

CREATE TABLE sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id),
    project_id UUID REFERENCES projects(id),
    title VARCHAR(500),                     -- Auto-generated from first message
    status VARCHAR(20) DEFAULT 'active',    -- active, paused_approval, paused_hitl, completed, failed

    -- Token usage (aggregated for transparency)
    prompt_tokens INTEGER DEFAULT 0,
    completion_tokens INTEGER DEFAULT 0,
    total_tokens INTEGER DEFAULT 0,

    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_sessions_user ON sessions(user_id);
CREATE INDEX idx_sessions_status ON sessions(status);

-- Chat messages (the conversation history)
CREATE TABLE messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID REFERENCES sessions(id) ON DELETE CASCADE,
    role VARCHAR(20) NOT NULL,              -- user, assistant, system, tool
    content TEXT NOT NULL,
    agent_id VARCHAR(100),                  -- Which agent sent this (for assistant messages)

    -- For tool result messages
    tool_name VARCHAR(200),
    tool_call_id VARCHAR(100),

    sequence_number INTEGER NOT NULL,       -- Order within session
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_messages_session ON messages(session_id);
CREATE INDEX idx_messages_sequence ON messages(session_id, sequence_number);

-- =============================================================================
-- WORKFLOWS (execution plans from planner)
-- =============================================================================

CREATE TABLE workflows (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID REFERENCES sessions(id) ON DELETE CASCADE,
    name VARCHAR(255),
    status VARCHAR(20) DEFAULT 'pending',   -- pending, running, paused, completed, failed
    current_step INTEGER DEFAULT 0,         -- Which step we're on
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_workflows_session ON workflows(session_id);

-- Workflow steps (the plan)
CREATE TABLE workflow_steps (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workflow_id UUID REFERENCES workflows(id) ON DELETE CASCADE,
    step_index INTEGER NOT NULL,            -- Order: 0, 1, 2...
    agent_id VARCHAR(100) NOT NULL,         -- router, planner, architect, developer, deployer
    description TEXT,
    status VARCHAR(20) DEFAULT 'pending',   -- pending, running, waiting_approval, completed, failed, skipped
    result_summary TEXT,
    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE
);

CREATE INDEX idx_workflow_steps_workflow ON workflow_steps(workflow_id);

-- =============================================================================
-- MCP SERVERS & TOOLS
-- =============================================================================

CREATE TABLE mcp_servers (
    id VARCHAR(100) PRIMARY KEY,            -- coding, docker, hitl, git, deploy
    name VARCHAR(255) NOT NULL,
    description TEXT,
    url VARCHAR(512) NOT NULL,
    health_status VARCHAR(20) DEFAULT 'unknown',  -- healthy, unhealthy, unknown
    last_health_check TIMESTAMP WITH TIME ZONE
);

-- Tool calls made by agents
CREATE TABLE tool_calls (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID REFERENCES sessions(id) ON DELETE CASCADE,
    agent_id VARCHAR(100) NOT NULL,         -- Which agent made this call

    -- Tool identification
    mcp_server VARCHAR(100) NOT NULL,
    tool_name VARCHAR(200) NOT NULL,
    arguments JSONB,                        -- Tool arguments (simple JSONB, read-only)

    -- Execution
    status VARCHAR(20) DEFAULT 'pending',   -- pending, executing, completed, failed
    result TEXT,
    error_message TEXT,

    -- Timing
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    executed_at TIMESTAMP WITH TIME ZONE
);

CREATE INDEX idx_tool_calls_session ON tool_calls(session_id);

-- =============================================================================
-- APPROVALS
-- =============================================================================

CREATE TABLE approvals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID REFERENCES sessions(id) ON DELETE CASCADE,
    tool_call_id UUID REFERENCES tool_calls(id),
    workflow_step_id UUID REFERENCES workflow_steps(id),

    -- What needs approval
    approval_type VARCHAR(20) NOT NULL,     -- tool_call, workflow_step
    agent_id VARCHAR(100) NOT NULL,         -- Which agent requested this (for resume)

    -- For tool approvals
    mcp_server VARCHAR(100),
    tool_name VARCHAR(200),

    -- Description for approvers
    title VARCHAR(500),
    description TEXT,

    -- Who can approve (simple: single role)
    required_role VARCHAR(50),              -- architect, developer, infra_engineer, admin

    -- Status
    status VARCHAR(20) DEFAULT 'pending',   -- pending, approved, rejected

    -- Resolution
    resolved_by UUID REFERENCES users(id),
    resolved_at TIMESTAMP WITH TIME ZONE,
    rejection_reason TEXT,

    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_approvals_session ON approvals(session_id);
CREATE INDEX idx_approvals_status ON approvals(status);

-- =============================================================================
-- HITL (Human-in-the-Loop) QUESTIONS
-- =============================================================================

CREATE TABLE hitl_questions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID REFERENCES sessions(id) ON DELETE CASCADE,
    agent_id VARCHAR(100) NOT NULL,         -- Which agent asked (for resume)

    -- Question
    question TEXT NOT NULL,
    question_type VARCHAR(20) DEFAULT 'text',  -- text, single_choice, multiple_choice
    choices JSONB,                          -- For choice questions: ["option1", "option2"]

    -- Answer
    status VARCHAR(20) DEFAULT 'pending',   -- pending, answered
    answer TEXT,
    answered_at TIMESTAMP WITH TIME ZONE,

    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_hitl_questions_session ON hitl_questions(session_id);
CREATE INDEX idx_hitl_questions_status ON hitl_questions(status);

-- =============================================================================
-- WORKSPACES
-- =============================================================================

CREATE TABLE workspaces (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID REFERENCES sessions(id) ON DELETE CASCADE,
    project_id UUID REFERENCES projects(id),
    branch VARCHAR(255) DEFAULT 'main',
    local_path VARCHAR(512),                -- /app/workspaces/{workspace_id}
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_workspaces_session ON workspaces(session_id);

-- =============================================================================
-- BUILDS & DEPLOYMENTS
-- =============================================================================

CREATE TABLE builds (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
    session_id UUID REFERENCES sessions(id),
    branch VARCHAR(255) DEFAULT 'main',
    status VARCHAR(20) DEFAULT 'pending',   -- pending, building, success, failed
    build_logs TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_builds_project ON builds(project_id);

CREATE TABLE deployments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    build_id UUID REFERENCES builds(id),
    project_id UUID REFERENCES projects(id) ON DELETE CASCADE,

    -- Container info
    container_name VARCHAR(255),
    container_id VARCHAR(100),

    -- Network
    host_port INTEGER,
    app_url VARCHAR(512),

    -- Status
    status VARCHAR(20) DEFAULT 'starting',  -- starting, running, stopped, failed
    is_preview BOOLEAN DEFAULT TRUE,

    started_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    stopped_at TIMESTAMP WITH TIME ZONE
);

CREATE INDEX idx_deployments_project ON deployments(project_id);
CREATE INDEX idx_deployments_status ON deployments(status);

-- =============================================================================
-- LLM USAGE TRACKING (for transparency/cost)
-- =============================================================================

CREATE TABLE llm_calls (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID REFERENCES sessions(id) ON DELETE CASCADE,
    agent_id VARCHAR(100) NOT NULL,

    -- Provider info
    provider VARCHAR(50) NOT NULL,          -- deepinfra, zai, openai
    model VARCHAR(100) NOT NULL,

    -- Token usage
    prompt_tokens INTEGER NOT NULL,
    completion_tokens INTEGER NOT NULL,
    total_tokens INTEGER NOT NULL,

    -- Timing
    duration_ms INTEGER,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_llm_calls_session ON llm_calls(session_id);

-- =============================================================================
-- INITIAL DATA
-- =============================================================================

-- Default MCP servers
INSERT INTO mcp_servers (id, name, description, url) VALUES
    ('coding', 'Coding MCP', 'File operations, git, and command execution', 'http://mcp-coding:9001'),
    ('docker', 'Docker MCP', 'Container build and deployment', 'http://mcp-docker:9002');

-- Note: Users and roles come from Keycloak, not seeded here
-- Note: Agents are defined in YAML files, not in database
