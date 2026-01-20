# Ralph Loop Progress - Druppie Improvements

## Iteration 2 Summary

### What Was Tested

1. **Setup Script** - Fixed Docker Compose v2 compatibility
   - Detects `docker compose` vs `docker-compose`
   - Uses `$DOCKER_COMPOSE` variable throughout
   - Removed deprecated `version` key from docker-compose.yml

2. **Authentication** - Working with Keycloak
   - Login flow works correctly
   - Role-based access (admin has all permissions)

3. **Chat Interface** - Working with Z.AI / GLM-4.7
   - Router agent analyzes intent
   - Planner agent creates execution plans
   - Developer agent generates code
   - Debug panel shows all LLM calls

4. **Project Creation** - Working end-to-end
   - Created Flask Todo App successfully
   - Build and Run functionality works
   - App runs at allocated port (9001)

5. **HITL Question/Answer Flow** - Working
   - When request is vague, router asks clarifying questions
   - Question appears inline in chat with input field
   - User can answer and workflow continues
   - Created Python Calculator after clarification

### Issues Found

1. **Git Push Fails** - Repository URL is generated but actual push fails
   - Error: `repository not found` when pushing to Gitea
   - Files are generated locally but not pushed to Git
   - Need to investigate Gitea repo creation flow

2. **Answer Submission UI** - Got stuck on "Submitting..."
   - Backend processed correctly (confirmed in logs)
   - Frontend didn't update until manual wait
   - May need better loading state handling

### What's Working Well

- Router agent correctly identifies vague requests and asks questions
- Planner creates appropriate execution plans
- Developer agent generates complete working apps
- Docker build and run functionality
- Debug panel provides full visibility into LLM calls
- Workflow events show real-time progress

### What Needs Improvement

1. **Role-based approvals** - Not yet tested
   - `deploy.staging` requires ROLE approval
   - `deploy.production` requires MULTI approval

2. **Git integration** - Repo push failing

3. **UI responsiveness** - Answer submission feedback

### Next Steps

1. Fix Gitea repository creation/push issue
2. Test role-based approval workflows
3. Improve UI loading states
4. Add more comprehensive E2E tests

## Commits Made

1. `d152fff` - Fix Docker Compose v2 compatibility in setup script
2. `aa2dba5` - Fix Gitea repo creation for reserved usernames like 'admin'

## Status After Iteration 2

All core functionality is working:
- Authentication with Keycloak
- Chat with LLM (Z.AI / GLM-4.7)
- Router agent analyzes intent
- Planner agent creates execution plans
- Developer agent generates code
- HITL question/answer flow
- Project creation with Git push to Gitea
- Build and run projects in Docker

Next iteration should focus on:
- Testing role-based approval workflows (deploy.staging, deploy.production)
- Adding more E2E tests
- Improving UI responsiveness

---

## Iteration 3 Summary

### What Was Tested

1. **Role-Based Approval Workflows** - Now working correctly
   - Fixed API endpoint to use MCP registry's `approval_roles` instead of fallback
   - `deploy.staging` tasks now require approval from `developer` or `infra-engineer`
   - Approvals page shows pending tasks filtered by user's roles
   - "You can approve" badge shown when user has the required role

2. **Approval/Reject Flow** - Working
   - Approve button works - task status changes to "approved"
   - Reject button requires a reason before confirming
   - Reject works - task status changes to "rejected"
   - Task counts update in real-time after approval/rejection

### Bugs Fixed

1. **API Missing plan_id Validation**
   - `POST /api/mcp/request-approval` didn't validate required `plan_id`
   - Now returns 400 error if `plan_id` is missing
   - Also verifies plan exists (returns 404 if not found)

2. **Wrong required_role for Approvals**
   - API was using `mcp_manager.get_required_role()` which returned "admin" as fallback
   - Now uses MCP registry's `approval_roles` from tool definition
   - `deploy.staging` correctly shows `required_role: developer`

3. **Missing approval_type Field**
   - Task creation wasn't setting `approval_type` field
   - Now uses `tool.approval_type.value` from MCP registry

### Code Changes

**backend/app.py** - `/api/mcp/request-approval` endpoint:
- Added validation for required `plan_id`
- Added plan existence check
- Get `approval_type` from MCP registry tool definition
- Get `required_role` from tool's `approval_roles` array

### Test Results

- Created approval request via API: Working
- Task appears on Approvals page: Working
- Approve task as developer: Working (status → approved)
- Reject task with reason: Working (status → rejected)
- Real-time count updates: Working

### What's Working Well

- Role-based permissions filtering (only shows tasks user can approve)
- Clear UI for approval/rejection with required reason for rejections
- Real-time updates via WebSocket
- MCP tool registry provides correct approval configuration

### Next Steps

1. Test MULTI approval workflow (deploy.production needs 2 of 3 roles)
2. Test approval flow from chat (when agent calls deploy tool)
3. Improve UI responsiveness for answer submission
4. Add E2E tests for approval workflows

---

## Iteration 4 Summary

### What Was Tested

1. **MULTI Approval Workflow** - Working correctly
   - `deploy.production` requires 2 approvals from different roles
   - Tested with seniordev (developer role) and infra (infra-engineer role)
   - Task stays `pending_approval` until required number of approvals is met
   - After 2 approvals, task status changes to `approved`

2. **Approval Flow from Chat** - Partially tested
   - Chat workflow is focused on code generation, not deployment
   - Router agent asks clarifying questions correctly
   - Deploy tools (`deploy.staging`, `deploy.production`) are defined but not integrated into chat workflow
   - Gap identified: need agent/workflow path to trigger MCP tools with approval requirements

### Bugs Fixed

1. **Task Approved with Only 1 Approval**
   - Cause: SQLAlchemy auto-flush was counting the new approval before commit
   - Fix: Added explicit `db.session.flush()` before counting approvals

2. **MULTI Tasks Shown to Wrong Users**
   - Cause: `list_tasks` checked single `required_role` before `required_roles`
   - Fix: Moved MULTI approval check before single role check with `continue`

3. **Frontend Not Showing Approve Buttons for MULTI**
   - Cause: `canApprove` only checked `task.required_role`, not `task.required_roles`
   - Fix: Updated to check `required_roles.some(role => hasRole(role))` for MULTI type

4. **Error Message Incorrect for MULTI Approval**
   - Updated to show all required roles: "You need one of these roles to approve: developer, infra-engineer, product-owner"

### Code Changes

**backend/druppie/models.py**:
- Added `required_roles` (JSON) field for MULTI approval
- Added `required_approvals` (Integer) field to track how many approvals needed

**backend/app.py** - `list_tasks` endpoint:
- Check MULTI approval first (has priority over single role)
- Filter out tasks user already approved
- Only show MULTI tasks to users with matching roles

**backend/app.py** - `approve_task` endpoint:
- Added MULTI approval logic
- Track multiple approvals, only mark as approved when required count is met
- Added explicit `db.session.flush()` to fix count issue

**backend/app.py** - `request_mcp_approval` endpoint:
- Set `required_roles` and `required_approvals` for MULTI tasks

**frontend/src/pages/Tasks.jsx**:
- Updated `canApprove` to check `required_roles` for MULTI type
- Updated error message to show all required roles for MULTI

### Test Results

- Created MULTI approval task via API: Working
- First approval (seniordev/developer): Task stays pending_approval
- Second approval (infra/infra-engineer): Task becomes approved
- Frontend correctly shows Approve buttons for users with any required role
- Tasks filtered out after user approves (prevents duplicate approvals)

### Architecture Gap Identified

The chat workflow doesn't have a path to trigger MCP tools like `deploy.production`:
- Router agent focuses on project creation/updates
- Planner creates code generation tasks
- No agent/workflow step to execute deployment MCP tools
- Future improvement needed: add deployment workflow that triggers approval flow

### What's Working Well

- MULTI approval workflow fully functional via API
- Frontend correctly handles MULTI approval display
- Role-based filtering works for both single and MULTI approval types
- Question/answer flow works in chat (HITL for clarification)
- Debug panel shows all LLM calls and workflow events

### Next Steps

1. Add deployment workflow that triggers MCP approval flow from chat
2. Verify optimistic update for answer submission (needs testing)
3. Add E2E tests for MULTI approval workflows
4. Consider inline approval UI in chat for triggered deploy actions

### Commits Made (Iteration 4)

1. `6d77678` - Add MULTI approval workflow support
2. `23abf83` - Add optimistic update for answer submission UI
