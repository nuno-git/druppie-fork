# summarizer

File: `druppie/agents/definitions/summarizer.yaml` (66 lines).

## Role

Final agent in every successful pipeline. Reads the summary relay and writes a user-friendly completion message via `create_message`.

## Config

| Field | Value |
|-------|-------|
| category | system |
| llm_profile | cheap |
| temperature | 0.3 |
| max_tokens | 2048 |
| max_iterations | 5 |
| builtin tools | `create_message`, `done` |
| MCPs | none |

## Output

A single `create_message(content="…")` call followed by `done()`.

The message:
- Written in the user's language (detected from `session.language`).
- Conversational tone — no internal jargon, no agent names, no technical abbreviations.
- Includes concrete outcomes: deployed URL, repo branch, PR number, what was built.
- Does NOT include prompt chain details, token counts, or internal decisions.

Example:
```
Ik heb een todo-app voor je gemaakt! Je kunt hem hier bekijken:
http://localhost:9105/ De code staat in https://gitea:3100/druppie/todo-app.
Laat me weten als je iets wilt aanpassen.
```

## Why a dedicated agent

Every other agent writes machine-friendly summaries for the relay. The summarizer translates that machine output into human output — a narrow, specific job that benefits from a tailored prompt and a cheap LLM.
