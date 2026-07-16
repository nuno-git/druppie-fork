# @status draft
# @superseded_by
# @adr
# @prd docs/prds/007-platform-standards-files.md

@prd docs/prds/007-platform-standards-files.md
Feature: Platform Standards Files
  # The "why" (problem, goal, user journey) lives in the linked PRD (@prd).
  # This spec holds only the acceptance Scenarios below.

  Scenario: New project repo is seeded with both standards files
    Given a new project is created via create_project
    When the template-push writes the project repo into Gitea
    Then the file docs/platform-functional-standards.md exists in the project repo
    And the file docs/platform-technical-standards.md exists in the project repo
    And each file carries a manual "Revision:" date header at the top

  Scenario: Business Analyst reads and applies the functional standards
    Given the business_analyst agent is running in update_project mode
    And the file docs/platform-functional-standards.md exists in the project repo
    When the business_analyst reads the functional standards file
    Then the business_analyst treats covered topics as a do-not-elicit list
    And gives a one-sentence heads-up to the user about platform defaults
    And does not write FR/NFR entries for topics the standards file covers

  Scenario: Architect reads and applies the technical standards
    Given the architect agent is running
    And the file docs/platform-technical-standards.md exists in the project repo
    When the architect reads the technical standards file before writing the TD
    Then the architect does not restate covered defaults in the TD
    And the TD Security section only covers project-specific measures

  Scenario: Functional Design links to the functional standards file
    Given the business_analyst has read docs/platform-functional-standards.md
    When the business_analyst produces docs/functional-design.md
    Then the first line of the FD is a visible markdown link to the standards file
    And the link includes the revision of the standards file applied
    And the link text states only deviations are listed below

  Scenario: Technical Design links to the technical standards file
    Given the architect has read docs/platform-technical-standards.md
    When the architect produces docs/technical-design.md
    Then the first line of the TD is a visible markdown link to the standards file
    And the link includes the revision of the standards file applied
    And the link text states only deviations are documented below

  Scenario: Deviations table tracks intentional exceptions
    Given an FD or TD is being produced against the platform standards
    When the agent intentionally deviates from a covered standard
    Then the deviation is recorded in a "Platform standard deviations" table
    And the table is present even when there are no deviations (empty row)
    And covered topics with no deviation produce no FR/NFR entry

  Scenario: Frontend renders standards links correctly in chat preview
    Given an FD or TD containing a relative markdown link to a standards file
    And the session has a project with repo_url and default_branch
    When the file preview is rendered in the chat via ReactMarkdown
    Then the MarkdownLink component resolves the relative path against the source file directory
    And rewrites the link to the Gitea source URL for the target file
    And the link opens in a new tab

  Scenario: External links in chat preview are left untouched
    Given a design document containing an external https link
    When the file preview is rendered in the chat via ReactMarkdown
    Then the MarkdownLink component leaves the external href unchanged
    And opens the link in a new tab

  Scenario: Standards update propagates only to new projects
    Given the platform team edits the standards files in druppie/templates/project/docs/
    When a new project is created after the edit is merged
    Then the new project repo contains the updated standards content
    But existing project repos keep their original snapshot of the standards
