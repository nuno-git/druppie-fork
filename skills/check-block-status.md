---
id: check-block-status
name: "Check Building Block Status"
description: "Verifies if a specific Building Block (service) is deployed and running in the cluster."
system_prompt: |
  To check if a building block is running:
  1. Identify the block ID (e.g., 'ai-video-comfyui').
  2. Query the runtime/cluster status (e.g., `kubectl get pods -l app=ai-video-comfyui`).
  3. Verify the status is 'Running' or 'Ready'.
  4. Return the service endpoint URL if valid.
allowed_tools: ["kubectl", "helm"]
---

This skill allows an agent to verify the operational state of a dependency before attempting to use it.
