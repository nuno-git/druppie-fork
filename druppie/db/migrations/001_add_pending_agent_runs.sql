-- Migration: Add pending agent runs support for planner
-- This allows the planner to create agent runs with status='pending'
-- that will be executed in sequence order.

-- Add columns for pending runs
ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS planned_prompt TEXT;
ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS sequence_number INTEGER;

-- Add index for efficient pending run queries
CREATE INDEX IF NOT EXISTS idx_agent_runs_pending
    ON agent_runs(session_id, status, sequence_number)
    WHERE status = 'pending';

-- Update status comment (informational only)
COMMENT ON COLUMN agent_runs.status IS 'pending, running, paused_tool, paused_hitl, completed, failed';
COMMENT ON COLUMN agent_runs.planned_prompt IS 'Task description for pending runs created by planner';
COMMENT ON COLUMN agent_runs.sequence_number IS 'Execution order for pending runs (0, 1, 2...)';
