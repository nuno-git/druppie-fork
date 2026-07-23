---
id: "025"
title: File upload for messages, HITL answers, and approval rejections
status: approved
author: nuno
date: 2026-07-17
supersedes: null
superseded_by: null
linked_adrs:
  - docs/adrs/025-file-upload-architecture.md
linked_research: []
linked_specs:
  - docs/specs/023-file-upload.feature
linked_workitem: null
---

# PRD 025: File upload for messages, HITL answers, and approval rejections

> **Where this fits:** The PRD is the START of the spec-driven pipeline. Everything flows
> from here: PRD → Research (optional, only when unclear) → ADR (decision) → Spec (verification)
> → Implementation. The PRD describes the PROBLEM and the GOAL from the user's perspective.
> It does NOT contain technical decisions (that's ADRs) or executable tests (that's Specs).

## Problem

Users need to share files with agents during conversations. A user might upload a text
document with requirements, a PDF specification, or a scanned form that the agent should
read and act on. Currently there is no way to provide file-based context in any
user-facing input surface.

This gap affects three specific surfaces:

- **Chat messages.** A user cannot attach a requirements document to a chat message and
  have the agent read it. Every piece of context must be typed or pasted as text.
- **HITL question answers.** When an agent asks a human-in-the-loop question (free-text
  or multiple choice), the answer cannot include a supporting file. The agent resumes
  without the document context it needs.
- **Approval rejection feedback.** When a user rejects an approval with feedback, they
  cannot attach a file explaining why. The rejection reason is limited to plain text.

Without file upload, users resort to pasting file contents into text fields, which is
cumbersome for large documents and impossible for scanned PDFs or formatted documents
where structure matters.

## Goal

Users can upload text files and PDFs across all three input surfaces. Uploaded file
content is extracted synchronously and injected into the agent's prompt context so the
agent can read and act on it immediately. File content persists for the duration of the
session.

Success criteria:

- Users can upload `.txt`, `.md`, `.csv`, `.json`, `.yaml`, `.xml`, `.log`, `.py`,
  `.js`, `.ts`, `.html`, `.css`, and `.pdf` files.
- Text-based PDFs have their content extracted via pypdf.
- Scanned PDFs fall back to OCR via pytesseract.
- Uploaded file content appears in every agent's prompt context within the session.
- File content persists across agent runs within the same session.
- Size limit of 10 MB per file is enforced server-side.
- Unsupported file types are rejected with a clear error message.

## User Journey

1. User opens a chat session with an agent.
2. User clicks the upload button next to the message input.
3. System opens a file picker filtered to supported types.
4. User selects a text file or PDF.
5. System uploads the file, extracts content synchronously, and returns a file_id.
6. User types a message and sends it with the file attached.
7. Agent receives the message with file content injected into its prompt context.
8. Agent reads the file content and responds accordingly.

Same flow applies to HITL question answers and approval rejection feedback, where the
upload button appears alongside the answer input or rejection text field.

## Constraints

- File type validation must happen on both frontend and backend.
- Size limit of 10 MB enforced server-side. Frontend should also warn before upload.
- Content extraction must be synchronous at upload time. Agents need immediate access.
- No cloud storage dependency. Files stored on disk with DB metadata.
- Session-level persistence: uploaded files are available to all agents in the session.
- Must support mobile browsers (explicit button, no drag-and-drop dependency).

## Out of Scope

- Drag-and-drop upload (button-based only for now).
- Image files (JPEG, PNG, GIF) and video files.
- File download from agents to users (surfaced file writes are a separate feature).
- Upload to running sandbox agents (files are for agent context, not sandbox execution).
- Cloud storage (S3, GCS, Azure Blob). Disk storage only.
- File preview in the frontend (thumbnail, inline viewer).

## Open Questions

None. Architecture is decided in ADR 025.

## Linked Documents

- **ADRs:** docs/adrs/025-file-upload-architecture.md
- **Research:** none
- **Specs / Feature files:** docs/specs/023-file-upload.feature
