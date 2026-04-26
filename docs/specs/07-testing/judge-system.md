# Judge System

LLM-as-a-judge: an LLM reads an agent's execution trace and verdicts whether it meets a natural-language criterion.

## Two modes

### LLM Judge
The judge's verdict IS the result. Used to evaluate quality in a subjective domain:
- "Does the FD cover all 13 required sections?"
- "Does the architect cite NORA principles by number?"
- "Is the response in Dutch?"

Each check has a `PASS` or `FAIL` verdict + reasoning. The TestAssertionResult stores both.

### Judge Eval
Tests the judge itself. Each check has an `expected: bool`. If the judge's verdict matches expected, the check passes; if not, the judge is flagged as unreliable.

```yaml
judge:
  checks:
    - name: Judge correctly identifies Dutch
      check: "Is this text in Dutch?"
      expected: true
      context_override:
        inline: "Dit is een voorbeeldzin in het Nederlands."
```

Used to calibrate prompts before trusting them in production evaluations.

## JudgeRunner

`druppie/testing/judge_runner.py`:

```python
class JudgeRunner:
    def __init__(self, judge_profile: JudgeProfile):
        self.profile = judge_profile

    def run_checks(
        self,
        db: DbSession,
        session_id: UUID,
        judge_checks: list,                  # list of JudgeCheck (or dicts convertible via JudgeCheck.from_value)
        context: str | list[str] = "all",    # "all" | agent_id | list of agent_ids
        source: str = "check",               # usually "check" (from a CheckDefinition) or "inline" (per-test)
    ) -> list[JudgeCheckResult]:
        ...
```

`source` is passed through into each `JudgeCheckResult` so the UI can show whether a check came from a reusable `CheckDefinition` or from an inline `judge:` block on the test itself. In Judge-Eval mode the check has an `expected` flag, and the runner compares the LLM verdict against that expected value to decide `passed`.

## Context filter

Judge checks can narrow what the LLM sees:

```yaml
context:
  - agent: business_analyst                # include only this agent's runs
  - agents: [business_analyst, architect]  # multiple agents
  - all                                    # everything (default)
```

The extractor applies the filter when querying the DB.

## Context sources

Declared per check:

```yaml
checks:
  - name: Uses make_design tool
    context:
      - all_tool_calls: {agent: business_analyst}
    check: "Did the BA call coding:make_design?"
```

Extractors (from `eval_context.py`):
- `all_tool_calls(agent?)` — tool calls for specified agent or all.
- `session_messages` — user/assistant messages.
- `agent_definition(agent, fields?)` — static data from agent YAML.
- `tool_call_result(tool, args_match?)` — specific tool call's result.
- `tool_call_arguments(tool, args_match?)` — specific tool call's args.

Each extractor returns a formatted string the prompt template interpolates.

## Judge profiles

`testing/profiles/judges.yaml`:

```yaml
default:
  model: glm-4.5-air
  provider: zai

strict:
  model: glm-4.5-air
  provider: zai

fast:
  model: glm-4.5-air
  provider: zai
```

A judge is just an LLM; the profile picks the model. Different judges for different check types are allowed — e.g. use a cheap model for basic formatting checks and a strong model for design quality.

## Prompt template

Simplified:

```
System: You are a strict evaluator. Given a trace of agent execution, determine if the criterion is met. Return JSON with "verdict" (true|false) and "reasoning" (one sentence).

User:
CRITERION: {{check.text}}

TRACE:
{{extracted_context}}

Respond with JSON only.
```

The agent doesn't see the trace. The judge doesn't see the real user's message outside the trace.

## Reusable check bundles

`testing/checks/*.yaml` — named checks agent tests can reference by `ref`:

```yaml
# testing/checks/architect-produces-td.yaml
check:
  name: architect-produces-td
  description: Architect reads FD, produces TD that is not a copy
  assert:
    - agent: architect
      tool: coding:make_design
  judge:
    context:
      - all_tool_calls: {agent: architect}
    checks:
      - name: Read FD before writing TD
        check: "Did the architect call read_file on functional_design.md before make_design?"
      - name: TD in Dutch
        check: "Is technical_design.md written in Dutch?"
      - name: Architecture decisions present
        check: "Does the TD include concrete architectural decisions (components, data model, infrastructure)?"
      - name: Not a copy-paste
        check: "Does the TD translate WHAT (from FD) to HOW (design-level), rather than rewording the FD?"
```

Referenced as `ref: architect-produces-td` in tests.

## Why NOT just regex

Regex checks the surface (presence of "NORA"). Judge checks the substance ("NORA principles cited with justification"). Some checks can't be regex'd reasonably:
- "Did the agent avoid solution bias?"
- "Is the design coherent with the TD?"
- "Does the test_report accurately describe the failure?"

The judge pays a non-trivial token cost per check, so heavy check suites are expensive. Judge Eval mode lets you calibrate which checks produce consistent verdicts and skip unreliable ones.

## Storage

Each judge check writes one `test_assertion_result` row with:
- `assertion_type = "judge_check"` (or `"judge_eval"` for eval mode).
- `passed` bool.
- `judge_reasoning` text.
- `judge_raw_input` — full prompt sent to judge.
- `judge_raw_output` — full response (JSON before parsing).

The Analytics page lets you drill into these to see exactly what the judge saw and said.
