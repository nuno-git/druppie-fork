ADR-007 as JSON data with an accompanying schema reference:

```json
{
  "$schema": "./adr.schema.json",
  "id": "007",
  "title": "Rolling deployment strategy for generated sandbox apps",
  "status": "accepted",
  "date": "2026-05-12",
  "deciders": ["nuno", "kilian"],
  "supersedes": "ADR-003",
  "linked_prd": "PRD-014",
  "context": "Sandbox apps were redeployed with a stop-then-start sequence, causing ~30s downtime and dropping active WebSocket sessions.",
  "decision": "Adopt a rolling deployment: start the new container, run a health check, switch traffic, then drain the old container. Rollout limits: maxSurge=1, maxUnavailable=0.",
  "consequences": [
    {"polarity": "positive", "text": "Zero-downtime deploys"},
    {"polarity": "positive", "text": "Safe automatic rollback when the health check fails"},
    {"polarity": "negative", "text": "Requires a /health endpoint on every generated app"},
    {"polarity": "negative", "text": "Transient ~2x memory usage during rollout"}
  ]
}
```
