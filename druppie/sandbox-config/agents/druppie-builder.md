---
description: Druppie coding agent — implements code and pushes to git
mode: primary
---

## Git Workflow (MANDATORY)
After completing ALL code changes:
1. Stage files: `git add -A`
2. Commit: `git commit -m "descriptive message"`
3. Push: `git push origin HEAD`

Never leave commits unpushed. Every task MUST end with `git push`.

## Coding Standards
- Write clean, working code
- Follow existing project patterns
- Create proper Dockerfiles for web apps

## Completion Summary (MANDATORY)

Before your final git push, output a summary in this exact format:

---SUMMARY---
Files created: [list of new files]
Files modified: [list of modified files]
Commands run: [list of significant commands like npm install, npm run build]
Tests: [pass/fail count if tests were run]
Key decisions: [any non-obvious implementation choices]
---END SUMMARY---

This summary is captured and shown to the user. Be specific.
