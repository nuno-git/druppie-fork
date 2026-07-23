# @status active
# @superseded_by
# @adr docs/adrs/025-file-upload-architecture.md
# @prd docs/prds/025-file-upload.md

@adr docs/adrs/025-file-upload-architecture.md
@prd docs/prds/025-file-upload.md
Feature: File upload for messages, HITL answers, and approval rejections
  # Users can upload text files and PDFs across chat messages, HITL question
  # answers, and approval rejection feedback. Uploaded file content is extracted
  # synchronously and injected into every agent's prompt context within the session.
  # Full technical detail lives in docs/adrs/025-file-upload-architecture.md.

  # ─────────────────────────────────────────────────────────────────────────
  # Upload validation
  # ─────────────────────────────────────────────────────────────────────────

  Scenario: Upload valid text file returns file_id with extracted content
    Given a user session with session_id "ses_abc"
    When the user uploads a file "requirements.txt" with content "Build a login page" via POST /api/files/upload
    Then the response status is 200
    And the response body contains a file_id matching the UUID pattern
    And the response body contains extracted_content equal to "Build a login page"
    And the response body contains mime_type "text/plain"
    And the file is stored on disk under /data/uploads/ses_abc/<file_id>/

  Scenario: Upload valid text-based PDF extracts content via pypdf
    Given a user session with session_id "ses_abc"
    When the user uploads a text-based PDF "spec.pdf" containing "System shall support SSO"
    Then the response status is 200
    And the response body contains extracted_content including "System shall support SSO"
    And the response body contains extraction_method "pypdf"

  Scenario: Upload scanned PDF falls back to OCR via pytesseract
    Given a user session with session_id "ses_abc"
    When the user uploads a scanned PDF "scan.pdf" with embedded image containing text "Approved by board"
    Then the response status is 200
    And the response body contains extracted_content including "Approved by board"
    And the response body contains extraction_method "tesseract_ocr"

  Scenario: Upload file exceeding size limit returns error
    Given a user session with session_id "ses_abc"
    When the user uploads a file of size 11 MB
    Then the response status is 413
    And the response body contains error "File exceeds maximum size of 10 MB"
    And no file is stored on disk

  Scenario: Upload unsupported file type returns error
    Given a user session with session_id "ses_abc"
    When the user uploads a file "image.png" with MIME type "image/png"
    Then the response status is 400
    And the response body contains error "Unsupported file type"
    And no file is stored on disk

  # ─────────────────────────────────────────────────────────────────────────
  # Attachment to input surfaces
  # ─────────────────────────────────────────────────────────────────────────

  Scenario: Attach file to chat message injects content into agent prompt context
    Given a user session with session_id "ses_abc"
    And the user has uploaded a file with file_id "f_001" containing "Database schema v2"
    When the user sends a chat message "Review this schema" with attached file_id "f_001"
    Then the agent's system prompt contains a "Uploaded Files" section
    And the "Uploaded Files" section lists file "f_001" with content "Database schema v2"
    And the agent can reference the file content in its response

  Scenario: Attach file to HITL question answer makes content visible to agent on resume
    Given a user session with session_id "ses_abc"
    And a HITL question is pending with question_id "q_001"
    When the user answers the HITL question with text "See attached" and attached file_id "f_001"
    Then the agent resumes with the answer text "See attached"
    And the agent's prompt context includes the file content from "f_001"

  Scenario: Attach file to approval rejection feedback makes content visible to agent
    Given a user session with session_id "ses_abc"
    And an approval request is pending with approval_id "a_001"
    When the user rejects the approval with reason "Needs revision" and attached file_id "f_001"
    Then the approval status is "rejected"
    And the rejection reason is "Needs revision"
    And the agent's prompt context on next run includes the file content from "f_001"

  # ─────────────────────────────────────────────────────────────────────────
  # Session-level persistence
  # ─────────────────────────────────────────────────────────────────────────

  Scenario: Multiple uploads in same session accumulate in context
    Given a user session with session_id "ses_abc"
    When the user uploads file "doc1.txt" with content "Part one"
    And the user uploads file "doc2.txt" with content "Part two"
    And the user sends a chat message with both file_ids attached
    Then the agent's prompt context contains both "Part one" and "Part two"
    And the "Uploaded Files" section lists both files

  Scenario: File content persists across agent runs within same session
    Given a user session with session_id "ses_abc"
    And the user uploaded file "requirements.txt" with content "Dark mode support" in a previous message
    When a new agent run starts within the same session
    Then the new agent's prompt context includes the file content "Dark mode support"
    And the "Uploaded Files" section lists "requirements.txt"

  # ─────────────────────────────────────────────────────────────────────────
  # Channel isolation
  # ─────────────────────────────────────────────────────────────────────────

  Scenario: Uploads to different channels do not cross-contaminate
    Given a user session with session_id "ses_abc"
    When the user uploads file "chat_doc.txt" via the chat channel
    And the user uploads file "hitl_doc.txt" via the HITL answer channel
    And the user submits a HITL answer
    Then the HITL answer context includes "hitl_doc.txt" content
    But the HITL answer context does NOT include "chat_doc.txt" content
