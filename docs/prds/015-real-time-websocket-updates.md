---
id: "015"
title: "Real-Time WebSocket Updates"
status: draft
author: nuno
date: 2026-07-16
supersedes: null
superseded_by: null
linked_adrs: []
linked_research: []
linked_specs: []
---

# PRD 015: Real-Time WebSocket Updates

## Problem

The frontend relies on HTTP polling for all real-time updates (agent progress, approval status, chat messages). This causes unnecessary load, latency (updates appear after poll interval), and a poor user experience for long-running agent sessions.

## Goal

Push-based real-time updates via WebSocket: agent progress events, approval state changes, tool call results, and chat messages pushed to the frontend the moment they happen. Eliminate polling for critical paths.

## User Journey

1. User opens a session — frontend establishes a WebSocket connection.
2. Agent starts running — progress events stream in real-time (tool calls, LLM thinking, completions).
3. Agent hits an approval gate — approval card appears instantly without polling.
4. User approves — agent resumes immediately (no refresh needed).
5. Session completes — final status pushed, connection closes cleanly.

## Constraints

- Must coexist with existing HTTP API (WebSocket is additive, not a replacement).
- Authentication via Keycloak JWT (same as HTTP endpoints).
- Connection lifecycle must handle page navigation, reconnects, and zombie cleanup.
- Must not break existing polling-based code (feature-flagged transition).

## Out of Scope

- WebSocket for generated applications (Druppie internal only).
- Mobile push notifications.

## Open Questions

- **Q1: Socket.io or raw WebSocket?**
  - Option A: Socket.io — reconnection, rooms, fallback to polling built-in.
  - Option B: Raw WebSocket — lighter, no extra dependency.
  - Owner: architect.

## Linked Documents

- Source: `docs/BACKLOG.md` — "No WebSocket Support"
