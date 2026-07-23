---
id: "027"
title: "Deployments Dashboard"
status: approved
author: nuno
date: 2026-07-17
supersedes: null
superseded_by: null
linked_adrs: []
linked_research: []
linked_specs:
  - docs/specs/025-deployments-dashboard.feature
linked_workitem: null
---

# PRD 027: Deployments Dashboard

> **Where this fits:** The PRD is the START of the spec-driven pipeline. Everything flows
> from here: PRD -> Research (optional, only when unclear) -> ADR (decision) -> Spec (verification)
> -> Implementation. The PRD describes the PROBLEM and the GOAL from the user's perspective.
> It does NOT contain technical decisions (that's ADRs) or executable tests (that's Specs).

## Problem

Users cannot see their deployed applications without admin access to the Platform page. The Platform page is an admin-only view of all infrastructure, and regular users have no way to check whether their apps are running, stopped, or unhealthy. Every basic deployment visibility task requires an admin to check and report back.

This creates a bottleneck. A developer who deploys an app through Druppie has to ask an admin "Is it running?" or "Why did it stop?" instead of seeing the answer directly. The dependency on admins for read-only status checks slows down the feedback loop and wastes admin time on questions that a self-service dashboard would answer instantly.

## Goal

A user-facing Deployments dashboard at `/deployments` that shows all of the user's deployed applications with status, logs, and basic lifecycle actions. Users can see what is running, filter by app name, start or stop their own apps, and view logs without involving an admin.

**Definition of done:** A developer can open `/deployments`, see their apps with status chips, filter by name, start/stop/restart any of their own apps, and open a logs drawer showing the last 300 lines of output.

## User Journey

1. User navigates to `/deployments`.
2. System displays a stats row: Total / Running / Stopped / Unhealthy counts.
3. System displays a table of the user's deployed applications.
4. Each row shows app name, status chip (Running / Stopped / Unhealthy / Transitioning), health indicator, and action buttons.
5. User types in the search field to filter by app name.
6. Table filters to matching apps only.
7. User clicks the stop button on a running app.
8. System sends the stop request. Status transitions to Stopped.
9. User clicks the start button on a stopped app.
10. System sends the start request. Status transitions to Running.
11. User clicks the restart button on a running app.
12. System sends the restart request. Status shows Transitioning, then returns to Running.
13. User clicks the logs button on any app.
14. System opens a terminal-style drawer showing the last 300 lines of logs.
15. User clicks the refresh button in the logs drawer.
16. System fetches the latest logs and updates the drawer.
17. System polls every 5 seconds for status updates across all visible apps.

## Constraints

- User-scoped: each user sees only their own deployments. No cross-user visibility.
- Polling only: 5-second interval. No WebSocket or real-time push.
- Logs are snapshot-only: last 300 lines. No streaming or tailing.
- Action buttons (start / stop / restart) are scoped to the user's own apps. No admin-style cross-user actions.
- Status chips must handle four states: Running, Stopped, Unhealthy, Transitioning.
- Empty state must show a clear "No deployments found" message with no broken UI.
- Search filter is client-side by app name. No server-side search.

## Out of Scope

- Admin features: starting, stopping, or restarting other users' applications.
- Real-time WebSocket updates. Polling only.
- Deployment creation. Deployments are created by agents, not through this dashboard.
- Log streaming or tailing. Snapshot of last 300 lines only.
- Deployment history or rollback.
- Resource usage metrics (CPU, memory, disk).
- Notifications or alerts on deployment state changes.

## Open Questions

None. Scope is well-defined and the implementation path is straightforward.

## Linked Documents

- **ADRs:** none
- **Research:** none
- **Specs / Feature files:** docs/specs/025-deployments-dashboard.feature
