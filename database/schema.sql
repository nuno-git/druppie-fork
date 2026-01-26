-- AI Governance Platform - PostgreSQL Schema
-- Single source of truth for all database tables
-- No nested JSON - fully normalized relational design
--
-- Version: 1.0.0
-- Created: 2026-01-26

-- =============================================================================
-- USERS & AUTHENTICATION
-- =============================================================================

-- User roles (lookup table)
CREATE TABLE roles (
    id SERIAL PRIMARY KEY,
    name VARCHAR(50) UNIQUE NOT NULL,  -- admin, architect, senior_developer, developer, infra_engineer
    description TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Users (synced from Keycloak, cached locally)
CREATE TABLE users (
    id UUID PRIMARY KEY,  -- Keycloak user ID
    username VARCHAR(255) UNIQUE NOT NULL,
    email VARCHAR(255),
    display_name VARCHAR(255),
    is_active BOOLEAN DEFAULT TRUE,
    last_login_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- User role assignments (many-to-many)
CREATE TABLE user_roles (
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    role_id INTEGER REFERENCES roles(id) ON DELETE CASCADE,
    granted_by UUID REFERENCES users(id),
    granted_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    PRIMARY KEY (user_id, role_id)
);

-- OBO tokens for external services (per user)
CREATE TABLE user_tokens (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    service VARCHAR(100) NOT NULL,  -- gitea, sharepoint, etc.
    access_token TEXT NOT NULL,
    refresh_token TEXT,
    expires_at TIMESTAMP WITH TIME ZONE,
    scopes TEXT,  -- comma-separated scopes
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(user_id, service)
);

-- =============================================================================
-- PROJECTS & REPOSITORIES
-- =============================================================================

-- Projects (Gitea repositories)
CREATE TABLE projects (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL,
    description TEXT,
    repo_name VARCHAR(255) NOT NULL,  -- Gitea repo name (user/repo)
    repo_url VARCHAR(512),            -- Gitea web URL
    clone_url VARCHAR(512),           -- Git clone URL
    owner_id UUID REFERENCES users(id),
    status VARCHAR(20) DEFAULT 'active',  -- active, archived, deleted
    default_branch VARCHAR(100) DEFAULT 'main',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_projects_owner ON projects(owner_id);
CREATE INDEX idx_projects_status ON projects(status);

-- Project collaborators (shared access)
CREATE TABLE project_collaborators (
    project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    permission VARCHAR(20) DEFAULT 'read',  -- read, write, admin
    added_by UUID REFERENCES users(id),
    added_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    PRIMARY KEY (project_id, user_id)
);

-- =============================================================================
-- SESSIONS & CONVERSATIONS
-- =============================================================================

-- Conversation sessions
CREATE TABLE sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id),
    project_id UUID REFERENCES projects(id),
    title VARCHAR(500),  -- Auto-generated from first message
    status VARCHAR(20) DEFAULT 'active',  -- active, paused_approval, paused_hitl, completed, failed

    -- Current execution position
    current_workflow_id UUID,  -- FK added after workflows table
    current_step_index INTEGER DEFAULT 0,

    -- Token usage (aggregated)
    prompt_tokens INTEGER DEFAULT 0,
    completion_tokens INTEGER DEFAULT 0,
    total_tokens INTEGER DEFAULT 0,
    estimated_cost_usd DECIMAL(10,6) DEFAULT 0,

    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_sessions_user ON sessions(user_id);
CREATE INDEX idx_sessions_project ON sessions(project_id);
CREATE INDEX idx_sessions_status ON sessions(status);

-- Chat messages in a session
CREATE TABLE messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID REFERENCES sessions(id) ON DELETE CASCADE,
    role VARCHAR(20) NOT NULL,  -- user, assistant, system, tool
    content TEXT NOT NULL,
    agent_id VARCHAR(100),  -- Which agent sent this (for assistant messages)

    -- For tool messages
    tool_name VARCHAR(200),
    tool_call_id VARCHAR(100),

    -- Metadata
    sequence_number INTEGER NOT NULL,  -- Order within session
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_messages_session ON messages(session_id);
CREATE INDEX idx_messages_sequence ON messages(session_id, sequence_number);

-- =============================================================================
-- WORKFLOWS & EXECUTION PLANS
-- =============================================================================

-- Workflow templates (created by planner agent)
CREATE TABLE workflows (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID REFERENCES sessions(id) ON DELETE CASCADE,
    name VARCHAR(255),
    description TEXT,
    status VARCHAR(20) DEFAULT 'pending',  -- pending, running, paused, completed, failed
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    completed_at TIMESTAMP WITH TIME ZONE
);

CREATE INDEX idx_workflows_session ON workflows(session_id);

-- Add FK from sessions to workflows (after workflows table exists)
ALTER TABLE sessions ADD CONSTRAINT fk_sessions_workflow
    FOREIGN KEY (current_workflow_id) REFERENCES workflows(id);

-- Workflow steps (execution plan)
CREATE TABLE workflow_steps (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workflow_id UUID REFERENCES workflows(id) ON DELETE CASCADE,
    step_index INTEGER NOT NULL,  -- Order of execution
    agent_id VARCHAR(100) NOT NULL,  -- router, planner, architect, developer, etc.
    description TEXT,

    -- Step status
    status VARCHAR(20) DEFAULT 'pending',  -- pending, running, waiting_approval, waiting_hitl, completed, failed, skipped

    -- Results
    result_summary TEXT,
    error_message TEXT,

    -- Timing
    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,

    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_workflow_steps_workflow ON workflow_steps(workflow_id);
CREATE INDEX idx_workflow_steps_order ON workflow_steps(workflow_id, step_index);

-- =============================================================================
-- AGENT EXECUTION
-- =============================================================================

-- Agent definitions (cached from YAML)
CREATE TABLE agents (
    id VARCHAR(100) PRIMARY KEY,  -- router, planner, architect, developer, etc.
    name VARCHAR(255) NOT NULL,
    description TEXT,

    -- LLM settings
    llm_provider VARCHAR(50),  -- zai, openai, anthropic, deepinfra
    llm_model VARCHAR(100),
    temperature DECIMAL(3,2) DEFAULT 0.1,
    max_tokens INTEGER DEFAULT 4000,
    max_iterations INTEGER DEFAULT 10,

    -- System prompt stored separately for easy editing
    system_prompt TEXT,

    is_active BOOLEAN DEFAULT TRUE,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Agent execution runs (each time an agent is invoked)
CREATE TABLE agent_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID REFERENCES sessions(id) ON DELETE CASCADE,
    workflow_step_id UUID REFERENCES workflow_steps(id),
    agent_id VARCHAR(100) REFERENCES agents(id),

    -- Execution state
    status VARCHAR(20) DEFAULT 'running',  -- running, paused_tool, paused_hitl, completed, failed
    iteration_count INTEGER DEFAULT 0,

    -- Token usage for this run
    prompt_tokens INTEGER DEFAULT 0,
    completion_tokens INTEGER DEFAULT 0,
    total_tokens INTEGER DEFAULT 0,

    -- For resumption after pause
    last_message_index INTEGER,  -- Position in messages array

    started_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    completed_at TIMESTAMP WITH TIME ZONE
);

CREATE INDEX idx_agent_runs_session ON agent_runs(session_id);
CREATE INDEX idx_agent_runs_step ON agent_runs(workflow_step_id);

-- =============================================================================
-- MCP TOOLS & APPROVALS
-- =============================================================================

-- MCP servers registry
CREATE TABLE mcp_servers (
    id VARCHAR(100) PRIMARY KEY,  -- coding, docker, hitl, git, deploy
    name VARCHAR(255) NOT NULL,
    description TEXT,
    url VARCHAR(512) NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    health_status VARCHAR(20) DEFAULT 'unknown',  -- healthy, unhealthy, unknown
    last_health_check TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- MCP tools registry
CREATE TABLE mcp_tools (
    id SERIAL PRIMARY KEY,
    server_id VARCHAR(100) REFERENCES mcp_servers(id) ON DELETE CASCADE,
    name VARCHAR(200) NOT NULL,
    description TEXT,

    -- Default approval settings
    requires_approval BOOLEAN DEFAULT FALSE,
    danger_level VARCHAR(20) DEFAULT 'low',  -- low, medium, high, critical

    UNIQUE(server_id, name)
);

-- Tool approval role requirements (default)
CREATE TABLE mcp_tool_required_roles (
    tool_id INTEGER REFERENCES mcp_tools(id) ON DELETE CASCADE,
    role_id INTEGER REFERENCES roles(id) ON DELETE CASCADE,
    approval_count INTEGER DEFAULT 1,  -- How many of this role needed
    PRIMARY KEY (tool_id, role_id)
);

-- Tool calls made by agents
CREATE TABLE tool_calls (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_run_id UUID REFERENCES agent_runs(id) ON DELETE CASCADE,
    session_id UUID REFERENCES sessions(id) ON DELETE CASCADE,

    -- Tool identification
    mcp_server VARCHAR(100) NOT NULL,
    tool_name VARCHAR(200) NOT NULL,

    -- Arguments (normalized for common fields)
    workspace_id UUID,
    file_path VARCHAR(1000),
    file_content TEXT,
    command TEXT,
    commit_message TEXT,
    -- Other args stored as key-value pairs in tool_call_arguments

    -- Execution
    status VARCHAR(20) DEFAULT 'pending',  -- pending, approved, rejected, executing, completed, failed
    result TEXT,
    error_message TEXT,
    duration_ms INTEGER,

    -- Approval tracking
    requires_approval BOOLEAN DEFAULT FALSE,
    approval_id UUID,  -- FK added after approvals table

    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    executed_at TIMESTAMP WITH TIME ZONE
);

CREATE INDEX idx_tool_calls_agent_run ON tool_calls(agent_run_id);
CREATE INDEX idx_tool_calls_session ON tool_calls(session_id);
CREATE INDEX idx_tool_calls_status ON tool_calls(status);

-- Additional tool call arguments (key-value for flexibility)
CREATE TABLE tool_call_arguments (
    tool_call_id UUID REFERENCES tool_calls(id) ON DELETE CASCADE,
    arg_name VARCHAR(100) NOT NULL,
    arg_value TEXT,
    PRIMARY KEY (tool_call_id, arg_name)
);

-- Approval requests
CREATE TABLE approvals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID REFERENCES sessions(id) ON DELETE CASCADE,
    tool_call_id UUID REFERENCES tool_calls(id),
    workflow_step_id UUID REFERENCES workflow_steps(id),  -- For step approvals
    agent_run_id UUID REFERENCES agent_runs(id),

    -- What needs approval
    approval_type VARCHAR(20) NOT NULL,  -- tool_call, workflow_step

    -- For tool approvals
    mcp_server VARCHAR(100),
    tool_name VARCHAR(200),

    -- Description for approvers
    title VARCHAR(500),
    description TEXT,
    danger_level VARCHAR(20) DEFAULT 'low',

    -- Status
    status VARCHAR(20) DEFAULT 'pending',  -- pending, approved, rejected, expired

    -- Timing
    expires_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    resolved_at TIMESTAMP WITH TIME ZONE
);

CREATE INDEX idx_approvals_session ON approvals(session_id);
CREATE INDEX idx_approvals_status ON approvals(status);

-- Add FK from tool_calls to approvals
ALTER TABLE tool_calls ADD CONSTRAINT fk_tool_calls_approval
    FOREIGN KEY (approval_id) REFERENCES approvals(id);

-- Required roles for an approval (copied from tool defaults, can be overridden)
CREATE TABLE approval_required_roles (
    approval_id UUID REFERENCES approvals(id) ON DELETE CASCADE,
    role_id INTEGER REFERENCES roles(id) ON DELETE CASCADE,
    required_count INTEGER DEFAULT 1,
    received_count INTEGER DEFAULT 0,
    PRIMARY KEY (approval_id, role_id)
);

-- Individual approval decisions
CREATE TABLE approval_decisions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    approval_id UUID REFERENCES approvals(id) ON DELETE CASCADE,
    user_id UUID REFERENCES users(id),
    role_id INTEGER REFERENCES roles(id),

    decision VARCHAR(20) NOT NULL,  -- approved, rejected, request_changes
    comment TEXT,

    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_approval_decisions_approval ON approval_decisions(approval_id);

-- =============================================================================
-- HUMAN-IN-THE-LOOP (HITL)
-- =============================================================================

-- HITL questions from agents to users
CREATE TABLE hitl_questions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID REFERENCES sessions(id) ON DELETE CASCADE,
    agent_run_id UUID REFERENCES agent_runs(id),
    agent_id VARCHAR(100) REFERENCES agents(id),

    -- Question
    question TEXT NOT NULL,
    question_type VARCHAR(20) DEFAULT 'text',  -- text, single_choice, multiple_choice

    -- Status
    status VARCHAR(20) DEFAULT 'pending',  -- pending, answered, expired, cancelled

    -- Answer
    answer TEXT,
    answered_by UUID REFERENCES users(id),
    answered_at TIMESTAMP WITH TIME ZONE,

    -- Timing
    timeout_seconds INTEGER DEFAULT 86400,  -- 24 hours default
    expires_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_hitl_questions_session ON hitl_questions(session_id);
CREATE INDEX idx_hitl_questions_status ON hitl_questions(status);

-- HITL question choices (for choice questions)
CREATE TABLE hitl_question_choices (
    id SERIAL PRIMARY KEY,
    question_id UUID REFERENCES hitl_questions(id) ON DELETE CASCADE,
    choice_index INTEGER NOT NULL,
    choice_text VARCHAR(500) NOT NULL,
    is_selected BOOLEAN DEFAULT FALSE,  -- For answered questions
    UNIQUE(question_id, choice_index)
);

-- =============================================================================
-- WORKSPACES & FILE SYSTEM
-- =============================================================================

-- Workspaces (sandboxed environments for sessions)
CREATE TABLE workspaces (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID REFERENCES sessions(id) ON DELETE CASCADE,
    project_id UUID REFERENCES projects(id),

    -- Git state
    branch VARCHAR(255) DEFAULT 'main',
    base_commit VARCHAR(40),  -- Git commit SHA

    -- Local paths
    local_path VARCHAR(512),  -- /app/workspaces/{workspace_id}

    -- Metadata
    is_new_project BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_workspaces_session ON workspaces(session_id);
CREATE INDEX idx_workspaces_project ON workspaces(project_id);

-- =============================================================================
-- DEPLOYMENTS & BUILDS
-- =============================================================================

-- Container builds
CREATE TABLE builds (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
    session_id UUID REFERENCES sessions(id),  -- Which session triggered this

    -- Git source
    branch VARCHAR(255) DEFAULT 'main',
    commit_sha VARCHAR(40),

    -- Build status
    status VARCHAR(20) DEFAULT 'pending',  -- pending, building, success, failed
    build_logs TEXT,

    -- Timing
    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_builds_project ON builds(project_id);
CREATE INDEX idx_builds_status ON builds(status);

-- Running deployments
CREATE TABLE deployments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    build_id UUID REFERENCES builds(id),
    project_id UUID REFERENCES projects(id) ON DELETE CASCADE,

    -- Container info
    container_name VARCHAR(255),
    container_id VARCHAR(100),

    -- Network
    host_port INTEGER,
    container_port INTEGER DEFAULT 80,
    app_url VARCHAR(512),

    -- Environment
    environment VARCHAR(50) DEFAULT 'preview',  -- preview, staging, production
    is_preview BOOLEAN DEFAULT TRUE,

    -- Status
    status VARCHAR(20) DEFAULT 'starting',  -- starting, running, stopped, failed

    -- Timing
    started_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    stopped_at TIMESTAMP WITH TIME ZONE
);

CREATE INDEX idx_deployments_project ON deployments(project_id);
CREATE INDEX idx_deployments_status ON deployments(status);

-- =============================================================================
-- LLM USAGE & COST TRACKING
-- =============================================================================

-- Individual LLM API calls
CREATE TABLE llm_calls (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_run_id UUID REFERENCES agent_runs(id) ON DELETE CASCADE,
    session_id UUID REFERENCES sessions(id) ON DELETE CASCADE,

    -- Provider info
    provider VARCHAR(50) NOT NULL,  -- zai, openai, anthropic
    model VARCHAR(100) NOT NULL,

    -- Token usage
    prompt_tokens INTEGER NOT NULL,
    completion_tokens INTEGER NOT NULL,
    total_tokens INTEGER NOT NULL,

    -- Cost (calculated based on provider pricing)
    cost_usd DECIMAL(10,6),

    -- Timing
    duration_ms INTEGER,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_llm_calls_agent_run ON llm_calls(agent_run_id);
CREATE INDEX idx_llm_calls_session ON llm_calls(session_id);
CREATE INDEX idx_llm_calls_created ON llm_calls(created_at);

-- =============================================================================
-- AUDIT LOG
-- =============================================================================

-- Comprehensive audit trail
CREATE TABLE audit_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Who
    user_id UUID REFERENCES users(id),
    agent_id VARCHAR(100),

    -- What
    action VARCHAR(100) NOT NULL,  -- session.created, tool.executed, approval.granted, etc.
    resource_type VARCHAR(50),  -- session, project, approval, deployment
    resource_id UUID,

    -- Details
    details TEXT,  -- Human-readable description

    -- Context
    session_id UUID REFERENCES sessions(id),
    ip_address INET,

    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_audit_log_user ON audit_log(user_id);
CREATE INDEX idx_audit_log_action ON audit_log(action);
CREATE INDEX idx_audit_log_resource ON audit_log(resource_type, resource_id);
CREATE INDEX idx_audit_log_created ON audit_log(created_at);

-- =============================================================================
-- EXECUTION CHECKPOINTS (for pause/resume)
-- =============================================================================

-- Checkpoints for resuming paused executions
CREATE TABLE execution_checkpoints (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID REFERENCES sessions(id) ON DELETE CASCADE,
    agent_run_id UUID REFERENCES agent_runs(id),

    -- What caused the pause
    pause_type VARCHAR(20) NOT NULL,  -- tool_approval, hitl_question, step_approval
    pause_reference_id UUID,  -- ID of approval or hitl_question

    -- Resumption data
    agent_id VARCHAR(100) NOT NULL,
    iteration_count INTEGER DEFAULT 0,
    pending_tool_call TEXT,  -- Tool call that needs approval

    -- Conversation state at pause point
    messages_snapshot_count INTEGER,  -- How many messages existed

    -- Status
    status VARCHAR(20) DEFAULT 'active',  -- active, resumed, expired

    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    resumed_at TIMESTAMP WITH TIME ZONE
);

CREATE INDEX idx_checkpoints_session ON execution_checkpoints(session_id);
CREATE INDEX idx_checkpoints_status ON execution_checkpoints(status);

-- =============================================================================
-- INITIAL DATA
-- =============================================================================

-- Default roles
INSERT INTO roles (name, description) VALUES
    ('admin', 'Full system access, can approve anything'),
    ('architect', 'Can approve technical designs and architecture'),
    ('senior_developer', 'Can approve code changes and implementations'),
    ('developer', 'Can write code, limited approval rights'),
    ('infra_engineer', 'Can approve deployments and infrastructure changes'),
    ('user', 'Regular user, can create projects and chat');

-- Default MCP servers
INSERT INTO mcp_servers (id, name, description, url) VALUES
    ('coding', 'Coding MCP', 'File operations, git, and test execution', 'http://mcp-coding:9001'),
    ('docker', 'Docker MCP', 'Container build and deployment', 'http://mcp-docker:9002'),
    ('hitl', 'HITL MCP', 'Human-in-the-loop questions', 'http://mcp-hitl:9003');

-- Default agents
INSERT INTO agents (id, name, description, llm_provider, llm_model, temperature, max_tokens) VALUES
    ('router', 'Router Agent', 'Classifies user intent and routes to appropriate workflow', 'zai', 'glm-4', 0.1, 2000),
    ('planner', 'Planner Agent', 'Creates execution plans for complex tasks', 'zai', 'glm-4', 0.1, 4000),
    ('architect', 'Architect Agent', 'Designs system architecture and technical specifications', 'zai', 'glm-4', 0.2, 8000),
    ('developer', 'Developer Agent', 'Writes and modifies code', 'zai', 'glm-4', 0.1, 16000),
    ('reviewer', 'Reviewer Agent', 'Reviews code quality and suggests improvements', 'zai', 'glm-4', 0.1, 8000),
    ('deployer', 'Deployer Agent', 'Manages deployments and infrastructure', 'zai', 'glm-4', 0.1, 4000),
    ('tester', 'Tester Agent', 'Runs tests and validates implementations', 'zai', 'glm-4', 0.1, 4000);

-- =============================================================================
-- HELPER VIEWS
-- =============================================================================

-- Session overview with token usage
CREATE VIEW session_overview AS
SELECT
    s.id,
    s.user_id,
    u.username,
    s.project_id,
    p.name as project_name,
    s.title,
    s.status,
    s.prompt_tokens,
    s.completion_tokens,
    s.total_tokens,
    s.estimated_cost_usd,
    s.created_at,
    s.updated_at,
    (SELECT COUNT(*) FROM messages m WHERE m.session_id = s.id) as message_count,
    (SELECT COUNT(*) FROM approvals a WHERE a.session_id = s.id AND a.status = 'pending') as pending_approvals,
    (SELECT COUNT(*) FROM hitl_questions h WHERE h.session_id = s.id AND h.status = 'pending') as pending_questions
FROM sessions s
LEFT JOIN users u ON s.user_id = u.id
LEFT JOIN projects p ON s.project_id = p.id;

-- Pending approvals view
CREATE VIEW pending_approvals_view AS
SELECT
    a.id,
    a.session_id,
    s.title as session_title,
    a.approval_type,
    a.mcp_server,
    a.tool_name,
    a.title,
    a.description,
    a.danger_level,
    a.created_at,
    a.expires_at,
    u.username as requester,
    array_agg(DISTINCT r.name) as required_roles
FROM approvals a
JOIN sessions s ON a.session_id = s.id
LEFT JOIN users u ON s.user_id = u.id
LEFT JOIN approval_required_roles arr ON a.id = arr.approval_id
LEFT JOIN roles r ON arr.role_id = r.id
WHERE a.status = 'pending'
GROUP BY a.id, s.title, u.username;

-- Running deployments view
CREATE VIEW running_deployments_view AS
SELECT
    d.id,
    d.project_id,
    p.name as project_name,
    p.owner_id,
    d.container_name,
    d.host_port,
    d.app_url,
    d.environment,
    d.status,
    d.started_at,
    b.branch,
    b.commit_sha
FROM deployments d
JOIN projects p ON d.project_id = p.id
LEFT JOIN builds b ON d.build_id = b.id
WHERE d.status = 'running';

-- Cost summary by project
CREATE VIEW project_cost_summary AS
SELECT
    p.id as project_id,
    p.name as project_name,
    p.owner_id,
    COUNT(DISTINCT s.id) as session_count,
    SUM(s.prompt_tokens) as total_prompt_tokens,
    SUM(s.completion_tokens) as total_completion_tokens,
    SUM(s.total_tokens) as total_tokens,
    SUM(s.estimated_cost_usd) as total_cost_usd
FROM projects p
LEFT JOIN sessions s ON s.project_id = p.id
GROUP BY p.id, p.name, p.owner_id;
