---
id: "019"
title: "Visualization Enhancements"
status: draft
author: nuno
date: 2026-07-16
supersedes: null
superseded_by: null
linked_adrs: []
linked_research: []
linked_specs: []
---

# PRD 019: Visualization Enhancements

## Problem

Current visualization (via data_analyst agent + create_chart tools) is limited to single-source reads with basic chart types. Multiple-source joins, large-dataset performance, smarter chart selection, and frontend artifact rendering all need improvement. The data_analyst prompt also grows too large when context includes schema for many tables.

## Goal

Comprehensive visualization upgrades: multi-source joins, performance at scale (server-side aggregation pushed to DB), smarter automatic chart-type selection, frontend rendering of chart artifacts alongside documents, and prompt-size optimization for the data_analyst agent.

## User Journey

1. Data Analyst agent receives a request: "Compare sales across two databases."
2. Agent joins data from two Azure SQL sources via a unified query path.
3. Agent selects chart type automatically based on data shape (time series → line, comparison → bar).
4. Chart is rendered in the frontend alongside the functional design document.
5. For large datasets, aggregation is pushed to the database — only the chart spec returns.

## Constraints

- Multi-source joins must respect each source's security boundaries.
- Chart rendering must work in the existing frontend (React/Vite).
- Server-side aggregation must stay within existing row caps and injection guards.
- Prompt size for data_analyst must be bounded (schema pagination or lazy loading).

## Out of Scope

- Real-time streaming visualizations.
- Custom chart editor in the frontend.
- Non-tabular data sources (graph, document stores).

## Open Questions

- **Q1: How to handle multi-source joins across different database engines?**
  - Option A: Federated query via Azure SQL OPENROWSET.
  - Option B: Materialize both sources server-side and join in Python.
  - Owner: architect.

## Linked Documents

- Source: `docs/BACKLOG.md` — "Visualization" section (5 items: Multiple Sources, Performance, Smarter Graphing, Frontend, Prompt Size)
