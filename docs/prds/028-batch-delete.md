---
id: "028"
title: Batch delete sessions and projects
status: approved
author: nuno
date: 2026-07-17
supersedes: null
superseded_by: null
linked_adrs: []
linked_research: []
linked_specs:
  - docs/specs/026-batch-delete.feature
linked_workitem: null
---

# PRD 028: Batch delete sessions and projects

> **Where this fits:** The PRD is the START of the spec-driven pipeline. Everything flows
> from here: PRD -> Research (optional, only when unclear) -> ADR (decision) -> Spec (verification)
> -> Implementation. The PRD describes the PROBLEM and the GOAL from the user's perspective.
> It does NOT contain technical decisions (that's ADRs) or executable tests (that's Specs).

## Problem

Users accumulate many sessions and projects over time. The sidebar shows every session
a user has ever started. The projects page lists every project they have ever created.
There is no way to clean up old or unwanted items except by deleting them one at a time.

For power users who run dozens of agent sessions daily, this is a real friction point.
Clearing out a week's worth of test sessions means clicking the delete button on each
one individually. The same applies to projects: a user who creates throwaway projects
for experiments has no efficient way to remove them in bulk.

The lack of batch operations also means the UI never exposes a "select all" affordance,
which makes the overall experience feel less polished for users who manage many items.

## Goal

Users can enter a selection mode on both the session sidebar and the projects page,
select multiple items (or all items), and delete them in a single action. The backend
supports batch deletion via a single API call, with a fallback to delete-all when no
specific IDs are provided.

**Definition of done:**

- Session sidebar has a selection mode toggle.
- Projects page has a selection mode toggle.
- In selection mode, each item shows a checkbox.
- A "select all" toggle checks or unchecks all visible items.
- A delete button appears when at least one item is selected, showing the count.
- When all items are selected, the button reads "Delete all".
- Clicking delete shows a confirmation dialog.
- Confirming sends a single batch delete request to the backend.
- The backend accepts DELETE with an optional body containing IDs; empty body means delete all.
- After deletion, the sidebar or project list refreshes to reflect the new state.
- Cancelling the dialog exits selection mode without deleting anything.
- Selection mode can be toggled on and off cleanly at any time.
- The selection mode toggle is hidden when the list is empty.

## User Journey

1. User opens the session sidebar.
2. User clicks the selection mode toggle (e.g. an icon button or "Select" label).
3. System shows a checkbox next to each session.
4. User checks individual sessions one by one.
5. System shows a floating delete button with the count: "Delete (3)".
6. User clicks "Select all" to check every session.
7. System updates the button to read "Delete all".
8. User clicks the delete button.
9. System shows a confirmation dialog: "Delete 3 sessions? This cannot be undone."
10. User confirms.
11. System sends a single DELETE request with the selected session IDs.
12. Sidebar refreshes. Deleted sessions are gone. Selection mode exits.

Same flow applies to the projects page, with the same visual pattern.

## Constraints

- Selection mode is per-view: entering it on the sidebar does not affect the projects page.
- The confirmation dialog must be explicit about the count and the irreversible nature of the action.
- The backend endpoint must accept DELETE with an optional JSON body containing an `ids` array.
- When `ids` is absent or empty, the endpoint deletes all sessions (or projects) for the authenticated user.
- The frontend must handle the case where the backend returns a partial failure (some items deleted, some failed).
- Selection state must reset when exiting selection mode, navigating away, or refreshing the list.

## Out of Scope

- Undo delete (no soft delete or trash mechanism).
- Delete scheduling or deferred deletion.
- Bulk operations other than delete (e.g. no batch archive, batch export, batch share).
- Multi-page selection (selecting items across paginated results).
- Selection persistence across page reloads.

## Open Questions

None. The design is straightforward and the implementation path is clear.

## Linked Documents

- **ADRs:** none
- **Research:** none
- **Specs / Feature files:** docs/specs/026-batch-delete.feature
