=============================================================================
SUMMARY RELAY (CRITICAL — READ AND FOLLOW!)
=============================================================================

When your prompt contains "PREVIOUS AGENT SUMMARY:", read it carefully.
It contains an accumulating log of what every previous agent accomplished,
plus key context you need (branch names, URLs, container names, PR numbers).

When you call done, the system AUTOMATICALLY includes all previous agent
summaries. You only need to describe what YOU did.

Your summary MUST follow this format:
  Agent <your_role>: <one sentence describing what you did and key outputs>.

Example of what the system accumulates after 3 agents:

  Agent architect: Designed counter app architecture, wrote architecture.md.
  Agent developer: Implemented app on branch feature/add-counter, pushed 3 files (index.html, styles.css, Dockerfile).
  Agent deployer: Built and deployed preview from feature/add-counter at http://localhost:9101 (container: counter-preview, port 9101:80).

RULES:
- One sentence per agent, max ~30 words.
- Always include actionable details the next agent needs: branch names, file
  paths, container names, URLs, port mappings, PR numbers, merge status.
- NEVER call done with a vague summary like "Task completed" or "Done".
  This breaks the entire pipeline. Be specific about what you did.
- Start your summary with "Agent <your_role>:" so the system can track it.

=============================================================================
done TOOL — MANDATORY FORMAT
=============================================================================

The done tool is how you signal completion AND pass information to the next
agent. The summary argument is the ONLY way agents communicate.

Previous agent summaries are auto-prepended by the system. You only provide
YOUR OWN summary line.

CORRECT:
  Call done with summary: "Agent developer: Created branch feature/add-login, pushed 4 files."

WRONG — these break the pipeline:
  Calling done with summary "Task completed"
  Calling done with summary "Done"
  Calling done with summary "Finished the task"

=============================================================================
WORKSPACE STATE
=============================================================================

Your workspace is shared across all agents in this session. If a previous
agent created a feature branch, you are already on that branch.
Read the PREVIOUS AGENT SUMMARY to know the current branch name.
Do NOT create a branch unless your task explicitly says "create a branch".
