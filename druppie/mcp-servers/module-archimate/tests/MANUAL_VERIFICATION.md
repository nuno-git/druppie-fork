# ArchiMate End-to-End — Manual Verification Checklist

Some acceptance criteria of the Archimate-end-to-end story can only be
validated against the full Druppie stack with a real user session. The
automated tests in this folder cover everything else:

| AC | Automated test | Manual step |
|----|----------------|-------------|
| AC1: Write-MCP round-trip + Archi opens file | `test_writer_roundtrip.py` (byte-diff, no-drift) | "Archi opens without errors" — see below |
| AC2: Architect produces ArchiMate TD | — | Full agent run, see below |
| AC3: Browser-rendering (existing + auto-layout) | `frontend/.../archimateParser.test.js` | Visual check in TD viewer, see below |
| AC4: Incremental update preserves positions | `test_writer_roundtrip.py` (step [4/4]) | Optional visual check |
| AC5: Approval-gates enforced | `test_approval_gates.py` (config parse) | Optional in-product test, see below |

## AC1 — Archi opens the saved file

After running the automated round-trip test, take the produced
`architecture.archimate` (or any file the agent has saved in a session
workspace at `docs/architecture.archimate`) and:

1. Install Archi from <https://www.archimatetool.com> if not already.
2. `File → Import → Open Exchange XML…` and select the file.
3. Expect: import succeeds without warnings, every view opens, every
   element keeps its name, type, and position.

Failure modes to watch for: schema-validation errors, missing
namespaces, mis-typed `xsi:type` values, dangling relationship
endpoints.

## AC2 — Architect produces ArchiMate TD (full agent run)

Pre-requisites: stack up via `docker compose --profile dev --profile init up -d`, Gitea reachable on `http://localhost:3000`, Keycloak with the `architect` test user (password `Architect123!`).

1. Log in as `architect`.
2. Create a new project (`create_project` flow), provide a brief that
   touches structural architecture (e.g. "Customer portal that calls
   an auth service and a notifications service, using PostgreSQL").
3. Submit the FD via the BA path (or write `docs/functional-design.md`
   directly to test the architect path in isolation).
4. Trigger the architect agent. Expected behaviour:
   - The agent invokes `making-archimate-diagrams` and
     `making-mermaid-diagrams` skills.
   - The agent searches WILMA via `search_model` even if not
     applicable, and either imports relevant elements via
     `get_or_create_wilma_reference` or notes in the TD why
     project-specific modeling was chosen.
   - The plate is built with `add_layered_view` / `add_cooperation_view`
     (or the primitive `create_element`, `create_relationship`,
     `add_to_view`, `add_connection_to_view`, `save_model` for
     incremental edits). These write tools are ungated — the single
     approval gate is the `coding:make_design` call on the technical
     design; approve that one as the architect user.
   - The agent writes `docs/technical-design.md` with at least one
     `` ```archimate view-id=… file=docs/architecture.archimate ``` ``
     block; behavioural diagrams (if any) use Mermaid.
   - `coding.run_git` commits and pushes both
     `docs/architecture.archimate` and `docs/technical-design.md`.
5. In Gitea: confirm both files are present, plus an
   `docs/diagrams/<view-name>.svg` per view.

## AC3 — Browser rendering

After AC2 produces a TD:

1. Open the session detail in Druppie.
2. The TD viewer renders the ` ```archimate ` block as an interactive
   SVG. Confirm:
   - Pan works by click-drag, zoom works by mouse-wheel and the
     +/-/reset buttons.
   - Element rectangles are filled with the ArchiMate layer color
     (yellow for Business, cyan for Application, green for Technology,
     purple for Motivation).
   - Relationship lines have the correct marker per type (filled
     triangle for Triggering / Flow, open triangle for Realization /
     Specialization, diamond for Composition / Aggregation, …).
   - The block header shows the view name.
3. If a view was created without explicit positions (rare — only when
   `add_to_view` was called with `x=-1`), the elkjs auto-layout runs
   and the view still looks reasonable (no lines through elements
   given default spacing).

## AC4 — Incremental update visual check (optional)

1. After AC2 + AC3, give chat-message feedback like "add a Billing
   service called from the Portal" and let the architect agent revise.
2. Approve the resulting write-tool calls.
3. Reopen the TD viewer for the same session.
4. Confirm:
   - The original elements have not moved (compare visually).
   - The new "Billing" element appears in blue, and the block header
     shows `1 new` badge keyed to the latest commit message.
   - Existing connections remain straight / orthogonal; only the new
     connection routes through the freshly added position.

## AC5 — Approval enforcement (optional in-product test)

1. Log in as a non-architect role (e.g. `developer`).
2. Manually call any ArchiMate write tool through the MCP bridge UI
   (or via the chat). Expect: a HITL approval is requested; the
   developer cannot self-approve since the gate requires `architect`.
3. Switch to the architect role and approve. The tool then executes.

The static config check `test_approval_gates.py` already asserts that
every write tool has `requires_approval: true` and
`required_role: architect`, so step 1's behaviour is guaranteed by
the config. The manual step verifies the runtime path end-to-end.
