# BA Agent Evaluation Process

How to evaluate the Business Analyst agent using the standardized test suite.

## Overview

Run the full BA test suite (13 tests) to measure how well the BA agent performs
across a range of expected behaviors. Each evaluation run consists of 5 iterations
to account for LLM non-determinism. Results reveal which behaviors are reliable,
which are flaky, and which consistently fail.

Use this process to evaluate:

- **BA prompt or workflow changes** — does a new version of the agent definition
  improve or regress behavior?
- **LLM swaps** — does a different model produce better BA behavior with the same
  agent definition?
- **Infrastructure changes** — do changes to tool implementations, MCP servers,
  or the execution loop affect BA outcomes?

## Prerequisites

- Druppie dev environment running (`docker compose --profile dev --profile init up -d`)
- Admin credentials (`admin` / `Admin123!`)
- API keys configured for the relevant LLM provider (see `.env`)

## Fixed test infrastructure

The judge and HITL simulator stay the same across all evaluation runs to ensure
consistent scoring:

| Component | Model | Provider | Config file |
|-----------|-------|----------|-------------|
| Judge | `glm-5` | `zai` | `testing/profiles/judges.yaml` |
| HITL simulator | `glm-5` | `zai` | `testing/profiles/hitl.yaml` |

## Test suite

All 13 tests are tagged `business_analyst` and can be run as a batch:

| Test | What it checks |
|------|---------------|
| ba-challenges-public-personal-data | Proactively challenges privacy concerns |
| ba-chat-routes-to-architect | Hands off to architect when user pivots to technical question |
| ba-clarifies-vague-terms | Asks user to clarify vague terms instead of inventing numbers |
| ba-context-gathering | Calls registry/project tools before starting elicitation |
| ba-cooperative-full-fd | Happy path: produces complete FD with cooperative user |
| ba-design-no-bias | Writes WHAT not HOW — no solution/technology bias |
| ba-fd-reject-then-approve | Handles FD rejection, revises, gets approval |
| ba-general-chat-advice | Gives advice in general_chat without starting project intake |
| ba-no-fd-for-bugfix | Identifies bug report as NO_FD_CHANGE |
| ba-no-technical-jargon | Avoids technical jargon in user-facing questions |
| ba-platform-standards-not-restated | Does not restate platform defaults as project-specific NFRs |
| ba-refuses-skip-questions | Refuses when user tries to skip all questions |
| ba-unpacks-solution-speak | Digs into underlying problem behind solution-speak |

### Known BA weaknesses

These 6 issues were identified during baseline evaluation. Tests that target them
deserve extra attention when reviewing results:

1. **Requirement fabrication** — BA invents requirements not stated by the user
2. **Restating platform standards** — BA lists platform defaults as project-specific NFRs
3. **Inventing numbers from vague input** — BA assigns concrete values to vague terms
4. **Not challenging privacy concerns** — BA doesn't push back on risky data decisions
5. **Multiple questions per HITL call** — BA asks several questions at once instead of one at a time
6. **Giving up too easily** — BA stops elicitation when the user is uncooperative

## Running an evaluation

### 1. Configure the agent under test

If you are evaluating a change to the BA agent definition, make sure the updated
`agents/definitions/business_analyst.yaml` is in place and the backend has been
restarted.

If you are testing a different LLM, set the force overrides in `.env`:

```bash
LLM_FORCE_PROVIDER=zai        # or: deepinfra, deepseek, azure_foundry, ollama
LLM_FORCE_MODEL=glm-5         # the specific model to test
```

Then restart the backend:

```bash
docker compose --profile dev restart druppie-backend-dev
```

### 2. Run a test batch

Authenticate and start the batch:

```bash
# Get token
TOKEN=$(curl -s -X POST "http://localhost:8380/realms/druppie/protocol/openid-connect/token" \
  -d "client_id=druppie-backend" \
  -d "grant_type=password" \
  -d "username=admin" \
  -d "password=Admin123!" | jq -r '.access_token')

# Start all BA tests
curl -s -X POST "http://localhost:8000/api/evaluations/run-tests" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"tag": "business_analyst", "execute": true, "judge": true}' | jq .
```

Save the returned `run_id`.

### 3. Monitor progress

```bash
curl -s "http://localhost:8000/api/evaluations/run-status/$RUN_ID" \
  -H "Authorization: Bearer $TOKEN" | jq .
```

A full batch takes approximately 2-3 hours (13 tests, ~10-15 min average each).

### 4. Repeat 5 times

Run steps 2-3 five times. Wait for each batch to complete before starting the
next (only one batch can run at a time).

Record the batch IDs:

| What changed | Iteration | Batch ID | Date |
|--------------|-----------|----------|------|
| _(describe the change)_ | 1 | | |
| | 2 | | |
| | 3 | | |
| | 4 | | |
| | 5 | | |

## Collecting results

### Per-batch summary

```bash
curl -s "http://localhost:8000/api/evaluations/analytics/batch/$BATCH_ID" \
  -H "Authorization: Bearer $TOKEN" | jq .
```

### All batches with tag filter

```bash
curl -s "http://localhost:8000/api/evaluations/test-batches?tag=business_analyst&limit=50" \
  -H "Authorization: Bearer $TOKEN" | jq .
```

### Detailed assertion results for a batch

```bash
curl -s "http://localhost:8000/api/evaluations/batch/$BATCH_ID/assertions" \
  -H "Authorization: Bearer $TOKEN" | jq .
```

## Analysis

### What to compute

For each evaluation (5 iterations), compute:

1. **Aggregate pass rate**: total tests passed / total tests run (out of 65)
2. **Per-test pass rate**: how often each test passes across 5 runs (out of 5)
3. **Consistency**: standard deviation of pass rate across iterations
4. **Duration**: average time per test and per batch

### What to look for

- **Stable passes** (5/5): the BA reliably handles this behavior
- **Stable fails** (0/5): the BA consistently gets this wrong — high-priority fix target
- **Flaky tests** (1-4 out of 5): partially learned behavior — prompt tuning may help
- **Known weakness performance**: check the 6 known BA issues listed above. Improvement
  on these is the clearest signal that a change is working.

### Comparing evaluations

When comparing two evaluations (e.g., before/after a prompt change, or two different
LLMs), use this template:

| Test | Baseline (pass rate) | Changed (pass rate) | Delta |
|------|---------------------|---------------------|-------|
| ba-challenges-public-personal-data | /5 | /5 | |
| ba-chat-routes-to-architect | /5 | /5 | |
| ba-clarifies-vague-terms | /5 | /5 | |
| ba-context-gathering | /5 | /5 | |
| ba-cooperative-full-fd | /5 | /5 | |
| ba-design-no-bias | /5 | /5 | |
| ba-fd-reject-then-approve | /5 | /5 | |
| ba-general-chat-advice | /5 | /5 | |
| ba-no-fd-for-bugfix | /5 | /5 | |
| ba-no-technical-jargon | /5 | /5 | |
| ba-platform-standards-not-restated | /5 | /5 | |
| ba-refuses-skip-questions | /5 | /5 | |
| ba-unpacks-solution-speak | /5 | /5 | |
| **Total** | **/65** | **/65** | |

## Notes

- If a batch fails mid-run (server restart, timeout), mark it as cancelled in the DB
  and start a fresh iteration. Do not count partial runs.
- The `TEST_TIMEOUT_SECONDS` env var (default 600s) controls per-test timeout.
  Some tests (e.g., `ba-cooperative-full-fd`) run close to this limit. Consider
  increasing to 900s if you see timeouts.
- To remove the force override and return to normal profile-based resolution,
  unset both `LLM_FORCE_PROVIDER` and `LLM_FORCE_MODEL` and restart the backend.
