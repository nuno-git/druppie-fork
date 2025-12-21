# Druppie UI Specification

## 1. System Overview
**Druppie UI** is the visual control plane for the Druppie Platform. It allows users to interact with the AI Core, visualize generated code, manage projects via a Kanban board, and approve sensitive actions. It connects to the `Druppie Core` via REST, Server-Sent Events (SSE), and WebSockets.

**Key Principles:**
*   **Human-in-the-Control-Loop**: The UI is designed to give users insight and control over the AI's autonomous actions.
*   **Real-Time**: State changes in the Core (e.g., Build finished, Plan updated) are reflected instantly.
*   **Transparency**: No "hidden" AI magic; always show the Plan, the Code, and the Logs.

## 2. Technical Stack
*   **Framework**: Next.js 14+ (App Router).
*   **Styling**: Tailwind CSS (adhering to Company Style Guide).
*   **State Management**: React Query (Server State) + Zustang (Client State).
*   **Visualization**:
    *   Code: `monaco-editor` or `prismjs`.
    *   Diagrams: `mermaid.js`.
    *   Markdown: `react-markdown`.
*   **Protocol**:
    *   Chat: SSE (Server-Sent Events) for streaming tokens.
    *   Events: WebSockets for Kanban/Status updates.

---

## 3. Epics & User Stories

### Epic 1: Conversational Interface (Chat)
**Goal**: Provide a rich, IDE-like chat experience for instructing the AI.

*   **Story 1.1: Streaming Response**
    *   **User**: "Build me a new drone service."
    *   **UI**: Renders text token-by-token. Supports Markdown rendering (tables, headers, bold).
*   **Story 1.2: Interactive Artifacts**
    *   **Function**: If the AI mentions a file (e.g., "I updated `deployment.yaml`"), the filename is a clickable link that opens the Code Viewer side-panel.
*   **Story 1.3: Thread Management**
    *   **Function**: Users can create new threads, rename them, and view history. History is fetched from Core.

### Epic 2: Visual Code Explorer (The "Lens")
**Goal**: Allow users to verify the AI's work without leaving the browser.

*   **Story 2.1: File Tree Navigator**
    *   **View**: A VSCode-like file tree representing the target Git repository's structure.
    *   **Source**: Fetched live from Gitea or the Core's "Temporary Workspace".
*   **Story 2.2: Code Editor/Viewer**
    *   **Function**: Read-only view of files with Syntax Highlighting (support for Go, Python, YAML, Markdown).
*   **Story 2.3: Diff Viewer**
    *   **Use Case**: When the AI proposes changes (HITL), show a side-by-side Diff (Red/Green) of Before vs After.
    *   **Action**: "Approve" button executes the change; "Reject" allows commenting feedback.

### Epic 3: Project Management (Kanban)
**Goal**: Visualize the Execution Plan as manageable tasks.

*   **Story 3.1: Live Board**
    *   **Columns**: `Planning`, `In Progress`, `Review`, `Done`.
    *   **Sync**: When the Core moves a step to "Completed", the card moves to "Done" automatically via WebSocket.
*   **Story 3.2: Drag-and-Drop Control**
    *   **Action**: User drags a card from "In Progress" back to "Planning".
    *   **Effect**: Sends a signal to Core to STOP execution and replan that step.
*   **Story 3.3: Project Context Selector**
    *   **View**: Dropdown menu in the Sidebar/Header to switch the active Project.
    *   **Action**: "Create New Project" button opens a modal to define Project Name and Key (e.g., `drone-service`).
    *   **Effect**: Filters the Chat History, Kanban Board, and File Browser to the selected Project scope.

### Epic 4: Registry Explorer
**Goal**: Browse the available capabilities of the platform.

*   **Story 4.1: Building Block Catalog**
    *   **View**: Grid view of cards for each Building Block (e.g., "Postgres", "Redis").
    *   **Detail**: Clicking a card shows its inputs, outputs, and dependencies (rendered from the Markdown definition).
*   **Story 4.2: Skill & Persona Viewer**
    *   **View**: List active Agents and their Skills.
    *   **Admin**: (If Admin) specific buttons to enable/disable specific skills.

### Epic 5: Governance Dashboard
**Goal**: Visibility into compliance and security.

*   **Story 5.1: Approval Queue**
    *   **View**: A dedicated "Inbox" for pending requests (Deployment to Prod, Public S3 bucket creation).
    *   **Action**: Approve/Deny with reason.
*   **Story 5.2: Compliance Reports**
    *   **View**: Tabular list of projects and their latest Compliance Scan status (Pass/Fail).

### Epic 6: Admin Control Plane
**Goal**: Manage the platform's configuration, users, and health.

*   **Story 6.1: IAM & RBAC Management**
    *   **View**: Manage Users, Groups, and Role Mappings (UI for Keycloak).
    *   **Action**: Assign "Platform Admin" or "Developer" roles to users.
*   **Story 6.2: System Health Monitor**
    *   **View**: Real-time dashboard of Core Services (Router, Planner, Registry).
    *   **Metric**: CPU/Memory usage of Agent pods.
*   **Story 6.3: Audit Log Viewer**
    *   **View**: Searchable table of all actions taken by Agents and Users.
    *   **Filter**: Filter by UserID, ProjectID, or Timestamp.
    *   **Detail**: View the exact differences (diffs) applied during an action.
*   **Story 6.4: Configuration Manager**
*   **View**: Edit Global Settings (e.g., "Default LLM Model", "Max Token Limit").
    *   **Action**: Upload new Corporate Guidelines (PDF) to the Compliance Engine.
*   **Story 6.5: Building Block Manager**
    *   **View**: Master list of all registered Building Blocks (e.g., "Postgres", "Redis").
    *   **Action**: Toggle `Enable/Disable`. Disabled blocks cannot be selected by the Planner.
    *   **Detail**: View metadata, version history, and dependency graph.
*   **Story 6.6: MCP Server Manager**
    *   **View**: List of connected Model Context Protocol (MCP) servers.
    *   **Action**: Register new MCP endpoint (URL + API Key).
    *   **Status**: Check health (`Ping`) of external tool providers.
*   **Story 6.7: Skill & Persona Manager**
    *   **View**: Catalog of Agent Skills (System Prompts + Tool Sets).
    *   **Action**: Upload new Skill definitions (Markdown/YAML).
    *   **Modification**: Hot-patch system prompts for specific Agents (e.g., tweaking the "Reviewer" personality).

---

## 4. Design Guidelines (UX)
*   **Theme**: Dark mode by default (Engineer focused).
*   **Layout**:
    *   **Left Sidebar**: Navigation (Chat, Projects, Catalog, Settings).
    *   **Center**: Main Content (Chat Stream or Kanban Board).
    *   **Right Panel (Collapsible)**: Context (Code Viewer, Documentation, Logs).
*   **Feedback**: Use "Toasts" for async events ("Build Started", "Agent Connected").

## 5. Security
*   **Auth**: Integrate with OIDC Client (Keycloak).
*   **Token**: Pass Bearer Token in all API calls to Core.
*   **Role Hiding**: Hide Admin settings if the user lacks the `platform-admin` role.
