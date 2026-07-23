---
id: "021"
title: "ArchiMate v2+ Roadmap"
status: draft
author: nuno
date: 2026-07-16
supersedes: null
superseded_by: null
linked_adrs: []
linked_research: []
linked_specs: []
---

# PRD 021: ArchiMate v2+ Roadmap

## Problem

The ArchiMate module (v1) supports basic generation and rendering but defers several capabilities: edge-routing upgrades (server-side libavoid), full 7-layer ArchiMate support, Bizzdesign integration, interactive editing in the TD viewer, webhook-based SVG regeneration, custom specializations, custom viewpoints, cross-project view references, concurrent-edit conflict resolution, WILMA version pinning, and property definitions in the write MCP.

## Goal

Incremental ArchiMate improvements delivered as versioned upgrades, each independently shippable. Priority order determined by user demand and implementation effort.

## User Journey

1. Architect creates a TD with ArchiMate diagrams.
2. Edge routing produces clean, non-overlapping lines (server-side libavoid).
3. All 7 ArchiMate layers are supported (strategy, business, application, data, technology, physical, implementation).
4. User edits a diagram interactively in the TD viewer.
5. Diagram SVG auto-regenerates via webhook when the model changes.
6. Custom element types and viewpoints are supported.

## Constraints

- Each feature is a major version bump (v2, v3, ...) following the module version system.
- Must not break existing v1 diagrams (backward compatibility).
- Server-side libavoid requires a native dependency in the container.
- Bizzdesign integration requires API access and authentication.

## Out of Scope

- Replacing the ArchiMate modeling engine.
- 3D visualization.

## Open Questions

- **Q1: Which deferred items are highest priority for v2?**
  - Option A: Edge routing + full 7-layer support (visual quality).
  - Option B: Interactive editing + webhook regeneration (user workflow).
  - Owner: architect, deadline: next sprint planning.

## Linked Documents

- Guide: `docs/guides/archimate-drawing-conventions.md` — current drawing conventions
- Source: `docs/BACKLOG.md` — "ArchiMate End-to-End — Deferred Items (v2+)" section
