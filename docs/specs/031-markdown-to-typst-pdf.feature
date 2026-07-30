# @status draft
# @superseded_by
# @adr docs/adrs/039-markdown-to-typst-conversion.md
# @prd docs/prds/033-markdown-to-typst-pdf.md

@prd docs/prds/033-markdown-to-typst-pdf.md
@adr docs/adrs/039-markdown-to-typst-conversion.md
Feature: Markdown to Typst PDF pipeline
  As a user of the governance platform
  I want to download professionally branded PDF documents from markdown sources
  So that I can share design documents with stakeholders in a polished format

  Background:
    Given a project exists in Gitea
    And the user is authenticated

  # --- Happy path ---

  Scenario: PDF download of a functional design document
    Given the project has a "docs/functional-design.md" file in Gitea
    When the user requests the PDF via the API endpoint
    Then the response has content type "application/pdf"
    And the PDF is a valid PDF document
    And the PDF contains Rijnland branding

  # --- House style branding ---

  Scenario: PDF uses the configured house style branding
    Given the project is configured with HHSK house style
    And the project has a "docs/functional-design.md" file in Gitea
    When a PDF is generated for the document
    Then the PDF uses HHSK branding
    And the PDF does not use Rijnland branding

  # --- Special character escaping ---

  Scenario: Special characters are escaped correctly in Typst output
    Given a markdown document containing the characters "<", ">", "#", "@", "$"
    When the document is converted to Typst and compiled to PDF
    Then the PDF renders without compilation errors
    And the characters "<", ">", "#", "@", "$" appear correctly in the output

  # --- Mermaid diagram rendering ---

  Scenario: Mermaid diagrams are rendered via the mmdr package
    Given a markdown document with a mermaid code block
    When the document is converted to Typst
    Then the Typst source imports the "@preview/mmdr" package
    And the mermaid code block is wrapped in an mmdr render call
    And the compiled PDF contains the rendered diagram

  # --- Render caching ---

  Scenario: Cached PDF is returned for unchanged content
    Given a PDF was previously generated for "docs/functional-design.md"
    And the source document has not changed since the last generation
    When the user requests the PDF for the same Git SHA
    Then the cached PDF is returned
    And no Typst recompilation occurs

  Scenario: Cache is invalidated when the source document changes
    Given a PDF was previously cached for "docs/functional-design.md"
    When the source document is updated in Gitea
    And the user requests the PDF for the new Git SHA
    Then a new Typst compilation is triggered
    And the newly compiled PDF is returned
    And the cache is updated with the new PDF

  # --- Table rendering ---

  Scenario: Large tables break across pages
    Given a markdown document with a table exceeding one page in length
    When the document is converted to Typst and compiled to PDF
    Then the table breaks across pages correctly
    And table headers are repeated on continuation pages

  # --- Frontend integration ---

  Scenario: PDF download button in the frontend
    Given a user views a session with a design document
    And the session timeline shows a completed document
    When the user clicks the PDF download button
    Then the PDF file downloads to the user's device
    And the downloaded file has a filename matching the document title
