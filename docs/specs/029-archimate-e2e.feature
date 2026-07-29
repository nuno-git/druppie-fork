# @status active
# @superseded_by
# @adr docs/adrs/031-hybrid-diagramming-strategy.md
# @prd docs/prds/021-archimate-v2-roadmap.md

# Spec (executable Gherkin) for the ArchiMate E2E (PR #215).
#
# Traceability: the @prd tag links this behaviour back to PRD 021.
# The @adr tag links to ADR 031 (hybrid diagramming strategy).

@prd docs/prds/021-archimate-v2-roadmap.md
@adr docs/adrs/031-hybrid-diagramming-strategy.md
Feature: ArchiMate E2E
  # The "why" (problem, goal, user journey) lives in the linked PRD (@prd).
  # This spec holds only the acceptance Scenarios below.

  Scenario: Architect creates layered view and model is written to project
    Given the architect agent has access to the ArchiMate write-MCP tools
    When the architect calls add_layered_view with layers "Business", "Application", and "Technology"
    And elements "CRM System" (Application), "Customer Database" (Data), and "Web Server" (Technology)
    Then the ArchiMate model is written to docs/architecture.archimate in the project repository
    And the file contains a layered view with the specified elements
    And the file is valid ArchiMate XML

  Scenario: Architect creates cooperation view with elements and relationships
    Given the architect agent has access to the ArchiMate write-MCP tools
    When the architect calls add_cooperation_view with actors "Customer" and "Sales Agent"
    And business processes "Place Order" and "Process Payment"
    And a triggering relationship from "Customer" to "Place Order"
    Then the ArchiMate model contains a cooperation view
    And the view includes all specified elements
    And the view includes the triggering relationship
    And the relationship direction is from "Customer" to "Place Order"

  Scenario: SVG export produces proper ArchiMate shapes per element type
    Given an ArchiMate model with elements of types "ApplicationComponent", "BusinessProcess", and "DataObject"
    When the SVG export tool renders the model
    Then the SVG contains an ApplicationComponent shape with the standard corner notation
    And the SVG contains a BusinessProcess shape with the rounded rectangle notation
    And the SVG contains a DataObject shape with the cylinder notation
    And each shape has a label matching the element name

  Scenario: TD viewer renders ArchiMate inline below Mermaid diagrams
    Given a technical design document containing both a Mermaid sequence diagram and an ArchiMate view reference
    When the user opens the TD in the frontend viewer
    Then the Mermaid diagram is rendered first
    And the ArchiMate diagram is rendered below the Mermaid diagram
    And both diagrams are interactive (pan/zoom)

  Scenario: Architect modifies existing view incrementally
    Given an existing ArchiMate model in docs/architecture.archimate with a layered view
    When the architect calls add_element to add a new "API Gateway" element to the existing view
    Then the model file is updated with the new element
    And the existing elements and relationships are preserved
    And the view now contains "API Gateway" in addition to the original elements

  Scenario: Element with wilma_id references pre-defined WILMA model element
    Given a WILMA reference model with a defined element "DataLake" having wilma_id "wilma://data/datalake"
    When the architect creates an element with wilma_id "wilma://data/datalake"
    Then the ArchiMate model stores the wilma_id reference
    And the element inherits properties from the WILMA reference model
    And the element is rendered with a WILMA reference indicator

  Scenario: ArchiMate view is validated before done() completes
    Given the architect agent has created an ArchiMate view
    When the architect calls done() to finalize the technical design
    Then the system validates the ArchiMate model for structural correctness
    And the validation checks that all relationships reference existing elements
    And the validation checks that every element has a name and type
    And if validation fails, done() returns an error listing the issues
    And if validation passes, done() completes successfully

  Scenario: Non-architect agent cannot access ArchiMate tools
    Given a developer agent session
    When the developer agent attempts to call add_layered_view
    Then the tool is not available in the developer agent's MCP tool manifest
    And the developer agent receives a "tool not found" error

  Scenario: ArchiMate model renders correctly in PDF export
    Given a technical design document containing an ArchiMate view reference
    When the Documenter agent calls the format tool to produce a PDF
    Then the PDF contains the ArchiMate diagram rendered as an embedded image
    And the diagram resolution is at least 300 DPI
    And the ArchiMate shapes are legible at the printed page size
