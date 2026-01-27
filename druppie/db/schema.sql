-- =============================================================================
-- Druppie Governance Platform - PostgreSQL Schema
-- Single source of truth for all database tables
-- =============================================================================
-- Version: 1.1.0
--
-- RULES:
-- 1. NO JSON/JSONB columns - everything normalized into proper tables
-- 2. Config stays in files (agents/*.yaml, mcp_config.yaml), not database
-- 3. Keep it simple - only what's needed for goal2.md
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
-- SESSIONS
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

-- =============================================================================
-- WORKFLOWS (execution plans from planner)
-- =============================================================================

CREATE TABLE workflows (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID REFERENCES sessions(id) ON DELETE CASCADE,
    name VARCHAR(255),
    status VARCHAR(20) DEFAULT 'pending',   -- pending, running, paused, completed, failed
    current_step INTEGER DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_workflows_session ON workflows(session_id);

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
-- AGENT RUNS (each time an agent is invoked)
-- =============================================================================
-- This tracks every agent execution. Messages are linked here for isolation.
-- By default, an agent only sees messages from its own run.
-- Future: can expand to see parent's messages or full session history.

CREATE TABLE agent_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID REFERENCES sessions(id) ON DELETE CASCADE,
    workflow_step_id UUID REFERENCES workflow_steps(id),  -- NULL for router/planner
    agent_id VARCHAR(100) NOT NULL,         -- router, planner, architect, developer
    parent_run_id UUID REFERENCES agent_runs(id),  -- Who called this agent (for context chain)

    -- Execution state
    status VARCHAR(20) DEFAULT 'running',   -- running, paused_tool, paused_hitl, completed, failed
    iteration_count INTEGER DEFAULT 0,      -- How many LLM calls in this run

    -- Token usage for this run
    prompt_tokens INTEGER DEFAULT 0,
    completion_tokens INTEGER DEFAULT 0,
    total_tokens INTEGER DEFAULT 0,

    started_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    completed_at TIMESTAMP WITH TIME ZONE
);

CREATE INDEX idx_agent_runs_session ON agent_runs(session_id);
CREATE INDEX idx_agent_runs_parent ON agent_runs(parent_run_id);

-- =============================================================================
-- MESSAGES (all messages saved, linked to agent_run for isolation)
-- =============================================================================

CREATE TABLE messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID REFERENCES sessions(id) ON DELETE CASCADE,
    agent_run_id UUID REFERENCES agent_runs(id),  -- Which agent run this belongs to

    role VARCHAR(20) NOT NULL,              -- user, assistant, system, tool
    content TEXT NOT NULL,

    -- For assistant messages
    agent_id VARCHAR(100),                  -- Which agent sent this

    -- For tool messages
    tool_name VARCHAR(200),
    tool_call_id VARCHAR(100),

    sequence_number INTEGER NOT NULL,       -- Order within session (global)
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_messages_session ON messages(session_id);
CREATE INDEX idx_messages_agent_run ON messages(agent_run_id);
CREATE INDEX idx_messages_sequence ON messages(session_id, sequence_number);

-- =============================================================================
-- TOOL CALLS
-- =============================================================================

CREATE TABLE tool_calls (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID REFERENCES sessions(id) ON DELETE CASCADE,
    agent_run_id UUID REFERENCES agent_runs(id),

    -- Tool identification
    mcp_server VARCHAR(100) NOT NULL,
    tool_name VARCHAR(200) NOT NULL,

    -- Execution
    status VARCHAR(20) DEFAULT 'pending',   -- pending, executing, completed, failed
    result TEXT,
    error_message TEXT,

    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    executed_at TIMESTAMP WITH TIME ZONE
);

CREATE INDEX idx_tool_calls_session ON tool_calls(session_id);
CREATE INDEX idx_tool_calls_agent_run ON tool_calls(agent_run_id);

-- Tool call arguments (normalized, no JSON)
CREATE TABLE tool_call_arguments (
    tool_call_id UUID REFERENCES tool_calls(id) ON DELETE CASCADE,
    arg_name VARCHAR(100) NOT NULL,
    arg_value TEXT,                         -- Can be large (file content)
    PRIMARY KEY (tool_call_id, arg_name)
);

-- =============================================================================
-- APPROVALS
-- =============================================================================

CREATE TABLE approvals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID REFERENCES sessions(id) ON DELETE CASCADE,
    agent_run_id UUID REFERENCES agent_runs(id),
    tool_call_id UUID REFERENCES tool_calls(id),
    workflow_step_id UUID REFERENCES workflow_steps(id),

    approval_type VARCHAR(20) NOT NULL,     -- tool_call, workflow_step

    -- For tool approvals
    mcp_server VARCHAR(100),
    tool_name VARCHAR(200),

    -- Description for approvers
    title VARCHAR(500),
    description TEXT,

    -- Who can approve
    required_role VARCHAR(50),              -- architect, developer, infra_engineer, admin

    -- Danger level for MCP tools
    danger_level VARCHAR(20),               -- low, medium, high

    -- Status
    status VARCHAR(20) DEFAULT 'pending',   -- pending, approved, rejected

    -- Resolution
    resolved_by UUID REFERENCES users(id),
    resolved_at TIMESTAMP WITH TIME ZONE,
    rejection_reason TEXT,

    -- Tool arguments for execution after approval
    arguments JSONB,

    -- Agent state for resumption after approval
    agent_state JSONB,

    -- Agent ID that requested the approval
    agent_id VARCHAR(100),

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
    agent_run_id UUID REFERENCES agent_runs(id),

    question TEXT NOT NULL,
    question_type VARCHAR(20) DEFAULT 'text',  -- text, single_choice, multiple_choice

    -- Answer
    status VARCHAR(20) DEFAULT 'pending',   -- pending, answered
    answer TEXT,
    answered_at TIMESTAMP WITH TIME ZONE,

    -- Agent state for resumption (messages, iteration, context, workflow info)
    agent_state JSON,

    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_hitl_questions_session ON hitl_questions(session_id);
CREATE INDEX idx_hitl_questions_status ON hitl_questions(status);

-- HITL question choices (normalized, no JSON array)
CREATE TABLE hitl_question_choices (
    question_id UUID REFERENCES hitl_questions(id) ON DELETE CASCADE,
    choice_index INTEGER NOT NULL,          -- Order: 0, 1, 2...
    choice_text VARCHAR(500) NOT NULL,
    is_selected BOOLEAN DEFAULT FALSE,      -- For answered multiple_choice
    PRIMARY KEY (question_id, choice_index)
);

-- =============================================================================
-- WORKSPACES
-- =============================================================================

CREATE TABLE workspaces (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID REFERENCES sessions(id) ON DELETE CASCADE,
    project_id UUID REFERENCES projects(id),
    branch VARCHAR(255) DEFAULT 'main',
    local_path VARCHAR(512),
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
    container_name VARCHAR(255),
    container_id VARCHAR(100),
    host_port INTEGER,
    app_url VARCHAR(512),
    status VARCHAR(20) DEFAULT 'starting',  -- starting, running, stopped, failed
    is_preview BOOLEAN DEFAULT TRUE,
    started_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    stopped_at TIMESTAMP WITH TIME ZONE
);

CREATE INDEX idx_deployments_project ON deployments(project_id);
CREATE INDEX idx_deployments_status ON deployments(status);

-- =============================================================================
-- LLM USAGE TRACKING
-- =============================================================================

CREATE TABLE llm_calls (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID REFERENCES sessions(id) ON DELETE CASCADE,
    agent_run_id UUID REFERENCES agent_runs(id),
    provider VARCHAR(50) NOT NULL,          -- deepinfra, zai, openai
    model VARCHAR(100) NOT NULL,
    prompt_tokens INTEGER NOT NULL,
    completion_tokens INTEGER NOT NULL,
    total_tokens INTEGER NOT NULL,
    duration_ms INTEGER,
    -- Full request/response data for debugging (JSON allowed for debug data)
    request_messages JSON,                  -- Messages sent to LLM
    response_content TEXT,                  -- LLM response text
    response_tool_calls JSON,               -- Tool calls returned by LLM
    tools_provided JSON,                    -- Tools available to LLM
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_llm_calls_session ON llm_calls(session_id);
CREATE INDEX idx_llm_calls_agent_run ON llm_calls(agent_run_id);

-- =============================================================================
-- SESSION EVENTS (unified event log for timeline display)
-- =============================================================================
-- This table provides a single source of truth for session timeline/history.
-- Instead of reconstructing events from multiple tables, we log each event here.
-- Links to detailed records in other tables for full data.

CREATE TABLE session_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID REFERENCES sessions(id) ON DELETE CASCADE,

    -- Event classification
    event_type VARCHAR(50) NOT NULL,            -- agent_started, agent_completed, tool_call,
                                                -- tool_result, approval_pending, approval_granted,
                                                -- approval_rejected, hitl_question, hitl_answered,
                                                -- deployment_started, deployment_complete, error

    -- Actor identification
    agent_id VARCHAR(100),                      -- Which agent triggered this event

    -- Event details (denormalized for easy display)
    title VARCHAR(500),                         -- Human-readable event title
    tool_name VARCHAR(200),                     -- For tool events: coding:write_file

    -- References to detailed records (optional, for drill-down)
    agent_run_id UUID REFERENCES agent_runs(id),
    tool_call_id UUID REFERENCES tool_calls(id),
    approval_id UUID REFERENCES approvals(id),
    hitl_question_id UUID REFERENCES hitl_questions(id),

    -- Event-specific data (minimal, for display only)
    -- Using JSON only for truly variable event metadata
    event_data JSONB,

    timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_session_events_session ON session_events(session_id);
CREATE INDEX idx_session_events_timestamp ON session_events(session_id, timestamp);
CREATE INDEX idx_session_events_type ON session_events(event_type);

-- =============================================================================
-- NOTES
-- =============================================================================
-- Users and roles: Synced from Keycloak
-- Agents: Defined in druppie/agents/definitions/*.yaml
-- MCP servers: Defined in druppie/core/mcp_config.yaml
-- Workflows: Defined in druppie/workflows/definitions/*.yaml
--
-- MEMORY ISOLATION:
-- By default, agents only see messages from their own agent_run_id.
-- To expand context: query messages where agent_run_id IN (current_run, parent_run, ...)
-- Future: add visibility_mode to agent_runs for selective sharing.
