---
id: "025"
title: File upload architecture — two-step flow, synchronous extraction, session-level injection
status: accepted
date: 2026-07-17
deciders:
  - nuno
supersedes: null
superseded_by: null
linked_prd: docs/prds/025-file-upload.md
linked_research: null
---

# ADR 025: File upload architecture — two-step flow, synchronous extraction, session-level injection

## Context

PRD 025 defines file upload support across three user-facing input surfaces: chat
messages, HITL question answers, and approval rejection feedback. Users need to upload
text files and PDFs that agents can read and act on immediately.

Several architectural questions need resolution:

- **Upload timing.** Should the file be uploaded as part of the message submission, or
  as a separate step beforehand? Separate upload decouples validation from persistence
  but adds an extra API call. Combined upload is simpler but ties file validation to
  message creation, making retries and re-attachment harder.
- **Content extraction timing.** Should extraction happen at upload time (synchronous)
  or at message processing time (lazy)? Synchronous extraction blocks the upload
  response but guarantees content is ready when the agent runs. Lazy extraction avoids
  blocking upload but adds latency to agent execution.
- **Content injection scope.** Should uploaded file content be injected into every agent
  in the session, or only the agent that receives the message? Session-level injection
  gives all agents the same context (router, planner, BA, architect, developer) but
  increases prompt size. Per-agent injection is more targeted but requires tracking
  which files each agent should see.
- **Upload channel isolation.** When a user uploads a file for a chat message while a
  HITL question is pending, can the uploads collide? Separate channels prevent
  cross-contamination but add complexity. A single shared channel is simpler but risks
  attaching a chat file to a HITL answer.
- **Storage backend.** Disk storage is simple and has no external dependency. Cloud
  storage (S3, GCS) scales better and survives container restarts but adds setup cost
  and a dependency on external infrastructure.

## Decision

### 1. Two-step upload flow

Upload is a separate step from message/question/approval submission. The client first
uploads the file via `POST /api/files/upload`, which returns a `file_id`. The client
then includes that `file_id` when sending the message, answering the HITL question, or
submitting the approval rejection.

Why: decouples upload validation from message persistence. If the file is invalid, the
user gets an error before typing their message. The same file can be re-attached to
multiple messages without re-uploading. The upload endpoint is simple and focused:
validate, extract, store, return ID.

### 2. Synchronous content extraction at upload time

Content extraction runs synchronously during the upload call:

- Text files (`.txt`, `.md`, `.csv`, `.json`, `.yaml`, `.xml`, `.log`, `.py`, `.js`,
  `.ts`, `.html`, `.css`): read as UTF-8 text.
- Text-based PDFs: extract via pypdf.
- Scanned PDFs: OCR fallback via pytesseract (Tesseract OCR).

Extracted content is stored alongside the file metadata in the database. When an agent
runs, the content is already available — no on-demand extraction, no async job, no
lazy loading.

Why: agents need immediate text access to file content. A URL or blob reference would
require the agent to fetch and parse the file itself, which adds complexity and
duplicates extraction logic. Synchronous extraction keeps the upload endpoint as the
single place where content is parsed.

### 3. Session-level context injection

Uploaded file content is injected into every agent's prompt via
`build_project_context()`. The function appends a "Uploaded Files" section to the
system prompt that lists each file's name, type, and extracted content.

Why: the router, planner, BA, architect, and developer agents all need the same file
context. A user uploading a requirements document expects every agent in the pipeline
to see it. Per-agent tracking would require a file-to-agent mapping that adds
complexity with no clear benefit for the current use cases.

### 4. Scoped upload channels via shared uploadManager module

A single `uploadManager` module manages upload state per session, with separate
channels for:

- `chat` — files attached to chat messages
- `hitl_answer` — files attached to HITL question answers
- `approval_rejection` — files attached to approval rejection feedback

Each channel tracks its own list of uploaded file IDs. When a message is sent, the
backend reads from the `chat` channel. When a HITL answer is submitted, it reads from
`hitl_answer`. This prevents cross-contamination: a file uploaded for a chat message
is not accidentally attached to a HITL answer.

Why: concurrent uploads to different surfaces must not collide. Scoped channels are
simpler than a global file list with surface tags, and they make the intent explicit
at the API level.

### 5. File type validation at both frontend and backend

The frontend filters the file picker to supported MIME types and shows an error for
unsupported files before upload. The backend re-validates the MIME type and file
extension on every upload request. Size limits are enforced server-side only (the
frontend may warn, but the backend is the authority).

Why: frontend validation gives instant feedback. Backend validation is the security
boundary. Both are needed.

### 6. No drag-and-drop — explicit button-based upload only

Upload is triggered by clicking an upload button that opens a native file picker.
Drag-and-drop is not supported.

Why: button-based upload works on all devices including mobile. Drag-and-drop adds
implementation complexity (drop zone rendering, drag event handling, mobile
incompatibility) with no clear benefit for the initial release.

### 7. Disk storage + DB metadata

Files are stored on disk under a configurable upload directory (default:
`/data/uploads/{session_id}/{file_id}/`). Metadata (file_id, original name, MIME type,
size, extracted content, session_id, channel, created_at) is stored in a
`message_attachments` database table. No cloud storage.

Why: disk storage has zero external dependencies, works offline, and is simple to
implement. Cloud storage can be added later when scaling requirements demand it.

## Consequences

### Positive

- **Shared context across all agents in a session.** A single upload feeds the router,
  planner, BA, architect, and developer agents without per-agent wiring.
- **Synchronous extraction avoids async complexity.** No background jobs, no polling,
  no eventual-consistency delays. Content is ready when the upload response returns.
- **Scoped channels prevent race conditions.** Concurrent uploads to different surfaces
  (chat + HITL answer) do not interfere with each other.
- **Two-step flow enables re-attachment.** The same file can be attached to multiple
  messages without re-uploading.
- **Button-based upload works on mobile.** No drag-and-drop dependency means the
  feature works on touch devices from day one.

### Negative

- **Disk storage needs monitoring.** Uploads consume disk space. A cleanup policy for
  orphaned files (uploads never attached to a message) and session-scoped cleanup on
  session expiry are needed.
- **Synchronous extraction blocks the upload response.** Large PDFs with OCR may take
  several seconds. The upload endpoint should have a generous timeout, and the
  frontend should show a progress indicator.
- **Content injection increases prompt size.** Large files (especially OCR output)
  add tokens to every agent's prompt. Context compaction (ADR 016) may need tuning
  for file-heavy sessions.
- **No cloud storage yet.** Container restarts lose disk storage unless a volume is
  mounted. Stateless deployments (Kubernetes) need a persistent volume or a cloud
  storage migration.
- **No drag-and-drop.** Users accustomed to drag-and-drop in other applications may
  find the button-only approach less convenient.

## Linked Documents

- **PRD:** docs/prds/025-file-upload.md
- **Spec:** docs/specs/023-file-upload.feature
