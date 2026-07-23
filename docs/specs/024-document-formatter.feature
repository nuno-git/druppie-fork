@prd docs/prds/023-document-formatter.md
@adr docs/adrs/026-documenter-typst-subsystem.md
Feature: Document Formatter (PDF Generation)
  # Acceptance criteria for the Typst-based PDF formatting subsystem.

  Scenario: Documenter agent formats functional design with Hoogheemraadschap title page
    Given the Documenter agent has access to the PDF formatting tool
    And a functional design document exists in Gitea with blob SHA "abc123"
    When the Documenter agent calls the format tool with the document path and format "hoogheemraadschap"
    Then the system fetches the source Markdown from Gitea
    And the system compiles the PDF using Typst with the Hoogheemraadschap template
    And the PDF contains a title page with the Hoogheemraadschap logo
    And the PDF contains a table of contents
    And the PDF contains page numbers in the footer
    And the PDF is returned to the agent

  Scenario: Documenter agent formats technical design with TOC and page numbers
    Given the Documenter agent has access to the PDF formatting tool
    And a technical design document exists in Gitea with blob SHA "def456"
    When the Documenter agent calls the format tool with the document path and format "hoogheemraadschap"
    Then the PDF contains a table of contents
    And every page has a page number in the footer
    And the header shows the document title and section name
    And code blocks in the document are syntax-highlighted

  Scenario: Source document unchanged returns cached PDF
    Given a document with blob SHA "abc123" was previously rendered and cached
    When the Documenter agent calls the format tool for the same document
    Then the system looks up blob SHA "abc123" in the render cache
    And the system returns the cached PDF without invoking the Typst CLI
    And the response time is under 500ms

  Scenario: Source document changed triggers new render
    Given a document with blob SHA "abc123" was previously rendered and cached
    And the source document has been updated to blob SHA "def456"
    When the Documenter agent calls the format tool for the document
    Then the system detects the blob SHA mismatch (cached "abc123" vs current "def456")
    And the system fetches the updated Markdown from Gitea
    And the system compiles a new PDF via Typst
    And the cache is updated with blob SHA "def456"
    And the new PDF is returned to the agent

  Scenario: PDF contains Mermaid diagrams rendered inline
    Given a document containing a Mermaid code block
    When the Documenter agent calls the format tool
    Then the PDF contains the Mermaid diagram rendered as an embedded image
    And the diagram is placed at the correct position in the document flow

  Scenario: PDF contains ArchiMate diagrams rendered inline
    Given a document containing an ArchiMate diagram reference
    When the Documenter agent calls the format tool
    Then the PDF contains the ArchiMate diagram rendered as an embedded image
    And the diagram resolution is at least 300 DPI

  Scenario: PDF has consistent fonts throughout
    Given a document with headings, body text, and code blocks
    When the Documenter agent calls the format tool
    Then the PDF uses the Hoogheemraadschap brand font for headings
    And the PDF uses a professional serif font for body text
    And the PDF uses a monospace font for code blocks
    And all fonts are embedded in the PDF file

  Scenario: Non-documenter agent cannot access formatting tool
    Given a Business Analyst agent session
    When the BA agent attempts to call the PDF formatting tool
    Then the tool is not available in the BA agent's MCP tool manifest
    And the BA agent receives a "tool not found" error

  Scenario: Formatting fails on corrupt source document
    Given a source document with malformed Markdown
    When the Documenter agent calls the format tool
    Then the Typst compilation fails with a parse error
    And the system returns a graceful error message to the agent
    And the error message includes the Typst compiler output for debugging
    And the cache is not updated

  Scenario: New project defaults to the Rijnland house style
    Given a newly created project with no house style explicitly set
    When the project's detail is retrieved
    Then the project's house style is "rijnland"
    And documents rendered for the project use the Rijnland template

  Scenario: Owner sets a project's house style to HHSK via the API
    Given a project owned by the current user
    When the owner sends PUT to "/api/projects/{id}/house-style" with house style "hhsk"
    Then the project's house style is updated to "hhsk"
    And the Documenter agent renders documents for the project with the HHSK template
    And the rendered PDF uses the HHSK palette, Ruda font, and HHSK logo

  Scenario: Non-owner cannot change a project's house style
    Given a project the current user does not own and is not an admin of
    When the user sends PUT to "/api/projects/{id}/house-style" with house style "hhsk"
    Then the request is rejected as unauthorized
    And the project's house style is unchanged

  Scenario: Explicit house style in the request overrides the project setting
    Given a project whose house style is set to "rijnland"
    When the Documenter agent receives a task explicitly requesting the HHSK house style
    Then the agent resolves the house style to "hhsk"
    And the document is rendered with the HHSK template instead of the project's Rijnland setting

  Scenario: Both house styles produce identically-structured documents
    Given the same source document rendered once with the Rijnland style and once with the HHSK style
    When both PDFs are compared
    Then both contain a title page, table of contents, page numbers, and watermark
    And both render tables, code blocks, blockquotes, and embedded diagrams the same way
    And only the visual identity — palette, fonts, logo, and layout — differs between them
