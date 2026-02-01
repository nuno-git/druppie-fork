=============================================================================
SUMMARY RELAY (CRITICAL — READ AND FOLLOW!)
=============================================================================

When your prompt contains "PREVIOUS AGENT SUMMARY:", read it carefully.
It contains an accumulating log of what every previous agent accomplished,
plus key context you need (branch names, URLs, container names, PR numbers).

When you call done(), your summary MUST follow this format:

1. COPY the entire previous summary as-is (preserve all earlier entries).
2. APPEND one new line for yourself:
   Agent <your_role>: <one sentence describing what you did and key outputs>.

Example of an accumulating summary after 3 agents:

  Agent architect: Designed counter app architecture, wrote architecture.md.
  Agent developer: Implemented app on branch feature/add-counter, pushed 3 files (index.html, styles.css, Dockerfile).
  Agent deployer: Built and deployed preview from feature/add-counter at http://localhost:9101 (container: counter-preview, port 9101:80).

RULES:
- One sentence per agent, max ~30 words.
- Always include actionable details the next agent needs: branch names, file
  paths, container names, URLs, port mappings, PR numbers, merge status.
- Never summarise with just "Task completed" — be specific.
- If you are the first agent (no previous summary), start a fresh log.
