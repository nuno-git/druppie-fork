# Components

Component inventory in `frontend/src/components/`. Three tiers.

## Top-level (`src/components/*.jsx`)

| Component | Purpose |
|-----------|---------|
| `NavRail.jsx` | 48 px icon sidebar. Logo, main nav, Tools section, Admin section (if admin), user avatar + dropdown. Pending approval count badge on Tasks. |
| `ErrorBoundary.jsx` | React error boundary wrapping routed children. Shows a full-page error with stack trace in dev. |
| `Toast.jsx` | Toast notification system. `<ToastProvider>` + `useToast()` hook + `<ToastContainer>` rendered at the root. Variants: success, error, warning, info. Auto-dismiss after 5 s, manual dismiss via X. |
| `CodeBlock.jsx` | Syntax-highlighted code block using Prism. Detects language from className (e.g. ```python → language-python). Copy button, optional line numbers. |
| `MermaidBlock.jsx` | Mermaid diagram renderer. Pan/zoom via pointer events. Toggle between rendered SVG and raw markdown. Catches render errors and shows them with the raw input. |

## Chat components (`src/components/chat/`)

All components consumed by `<SessionDetail>` (the big one) or `<Chat>` shell.

| Component | Purpose |
|-----------|---------|
| `SessionDetail.jsx` | Main chat view. Renders timeline of messages + agent runs. Embeds approval cards and HITL question cards inline. Handles streaming-like polling (every ~2 s). Shows annotation bar at top with user, project, tokens, duration, status. |
| `SessionSidebar.jsx` | Session list grouped by date (Today/Yesterday/Last 7/Older). Search input, delete button, "new chat" button at top. |
| `NewSessionPanel.jsx` | Landing state for new sessions. Welcome message, chat input, optional agent selector. |
| `AnnotationBar.jsx` | Top-bar metadata strip: user avatar, project name link, token/cost, duration, status pill. |
| `WorkflowPipeline.jsx` | Visual horizontal pipeline of agents with per-agent status (pending/running/completed/failed). Built from the session's agent run sequence. |
| `ApprovalCard.jsx` | Inline approval card in timeline. Shows tool name, args, required role, status. Inline Approve/Reject buttons if the current user can act. |
| `ToolDecisionCard.jsx` | Card showing a tool the agent decided to call. Expandable to show arguments and result. Color-coded by `agent_id` via `getAgentColorClasses`. |
| `HITLQuestionMessage.jsx` | HITL question in timeline. Renders question text + either a text input or radio/checkbox choices. "Submit" button calls `answerQuestion`. |
| `SandboxEventCard.jsx` | Groups sandbox events (tool calls within the sandbox, screenshots, git ops). Streams from the sandbox events endpoint with cursor pagination. |
| `TestResultCard.jsx` | Inline test run result (from `test_report` tool). Shows PASS/FAIL counts, coverage, failed test names. |
| `FileReviewCard.jsx` | Card for design files (`.md` with Mermaid). Click to open a full-screen preview. |
| `DependencyInstallCard.jsx` | Card showing packages about to be / just-installed during build. |
| `DebugEventLog.jsx` | Right-side panel in `?mode=inspect`. Full chronological event log with expandable LLM prompts, tool schemas, and raw responses. |
| `ChatHelpers.jsx` | Shared utilities: markdown renderer with Mermaid detection, time formatters, JSON builders, approval extraction from timeline. |

## Shared components (`src/components/shared/`)

| Component | Purpose |
|-----------|---------|
| `PageHeader.jsx` | Title + optional subtitle + right-aligned slot for actions. Used on every non-Chat page. |
| `Skeleton.jsx` | Loading skeletons: `StatCard`, `ListItem`, `Card`, `ProjectCard`. Pulse animation. |
| `CopyButton.jsx` | Icon button that copies text to clipboard; shows "Copied" tooltip for 2 s. |
| `EmptyState.jsx` | Icon + title + description + optional CTA button. Used in lists with no items. |
| `ContainerLogsModal.jsx` | Fullscreen modal for container logs. Fetches `/api/deployments/{name}/logs?tail=N` with tail selector. |

## Rendering rules

- Markdown is always rendered via `react-markdown` with `remark-gfm`. `<CodeBlock>` and `<MermaidBlock>` are wired as custom renderers in `ChatHelpers.jsx`.
- Dates are rendered via `formatDuration` (in utils) or `Intl.DateTimeFormat` for absolute timestamps.
- Tokens/costs via `formatTokens`, `formatCost`, `formatTokensWithCost`.
- Tool names via `formatToolName` (e.g. `coding_write_file` → "Write File").
- Agent colors via `AGENT_CONFIG` (`src/utils/agentConfig.js`) — each agent has an icon, a color key, and a "thinking label".

## Component state strategy

- Local state (`useState`) for transient UI (modal open, hover, expanded rows).
- `useQuery` for server data.
- `useMutation` for actions (approve, reject, answer, delete).
- Zustand stores for cross-component state that isn't server data: toast stack, sidebar open/closed.
- React Router `useSearchParams` for URL-driven filters and pagination.

No Redux, no custom event bus, no hooks-over-context sprawl. The codebase stays readable by keeping state close to where it's used.
