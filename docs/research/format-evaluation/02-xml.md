ADR-007 rendered with XML-style semantic tags:

```xml
<adr>
  <id>007</id>
  <title>Rolling deployment strategy for generated sandbox apps</title>
  <status>accepted</status>
  <date>2026-05-12</date>
  <deciders>nuno, kilian</deciders>
  <supersedes>ADR-003</supersedes>
  <linked_prd>PRD-014</linked_prd>
  <context>Sandbox apps were redeployed with a stop-then-start sequence, causing ~30s downtime and dropping active WebSocket sessions.</context>
  <decision>Adopt a rolling deployment: start the new container, run a health check, switch traffic, then drain the old container. Rollout limits: maxSurge=1, maxUnavailable=0.</decision>
  <consequences>
    <positive>Zero-downtime deploys</positive>
    <positive>Safe automatic rollback when the health check fails</positive>
    <negative>Requires a /health endpoint on every generated app</negative>
    <negative>Transient ~2x memory usage during rollout</negative>
  </consequences>
</adr>
```
