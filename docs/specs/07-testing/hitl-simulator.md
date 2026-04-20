# HITL Simulator

`druppie/testing/hitl_simulator.py`. Lets agent tests run end-to-end without a human answering HITL questions or approvals.

## Concept

Each HITL profile encodes a persona: a demographic + knowledge model + behavioural rules. When an agent asks a question or a tool hits an approval gate, the simulator:
1. Builds a transcript of the session so far (excluding the pending question/approval).
2. Calls an LLM with the persona prompt + transcript + question.
3. Parses the LLM's response into the expected shape (text, choice index, approve/reject).
4. Submits the answer via the normal Druppie API path (ensuring the agent run resumes the same way it would for a real user).

## `HITLProfile`

From `druppie/testing/schema.py`:

```python
class HITLProfile(BaseModel):
    model: str
    provider: str
    temperature: float = 0.2
    prompt: str            # the persona's system prompt
```

## Profiles shipped (`testing/profiles/hitl.yaml`)

### `non-technical-pm`
Short answers. Ignores technical details. Prefers examples over specs.

### `dutch-water-authority`
Dutch speaker. Domain expertise in water management, permits, environmental compliance. Uses Dutch jargon.

### `developer`
Technical. Precise. Cares about testing, architecture, error handling. Asks follow-up questions where agents are vague.

### `picky-session-owner`
Used by `ba-fd-reject-then-approve.yaml`. Programmed behaviour:
- First `coding:make_design` approval gate → reject with a concrete concern (e.g. "You haven't addressed NFR3 about concurrent users").
- Second approval gate (after BA revises) → approve, noting the revision fixed the concern.
- Never reject twice.

## Session transcript

`druppie/testing/session_transcript.py:build_transcript(session_id, exclude_current_pending=True)`:
- Queries AgentRun, ToolCall, Question, Approval in creation order.
- Formats each:
  - Tool call: `{agent} called {tool}({args_excerpt}) → {result_excerpt}`
  - Question: `{agent} asked: {question} → {answer}` (or `pending` if unanswered)
  - Approval: `approval requested for {tool} by {role} → {approved|rejected|pending}`
- Truncates fields to `MAX_FIELD_CHARS = 4000` to keep the prompt bounded.

The `exclude_current_pending=True` flag omits the question/approval the simulator is about to answer — otherwise the prompt would contain the question twice, confusing the LLM.

## Simulator flow

```python
class HITLSimulator:
    def __init__(self, profile: HITLProfile, context: dict):
        self.profile = profile
        self.context = context
        self.interactions = 0

    def answer(self, question_or_approval) -> answer_payload:
        self.interactions += 1
        if self.interactions > MAX_HITL_INTERACTIONS:
            raise RuntimeError("Too many HITL interactions")
        transcript = build_transcript(session_id, exclude_current_pending=True)
        prompt = build_prompt(self.profile, transcript, question_or_approval)
        response = self._call_llm_with_retry(prompt)
        return parse_response(response, question_or_approval.type)
```

## Integration with `BoundedOrchestrator`

The agent test registers a hook: when the orchestrator would pause on HITL or approval, call `HITLSimulator.answer()` inline, then let the orchestrator continue. The result: the agent test runs end-to-end without spinning up a separate thread / manual polling.

## Retries

`_call_llm_with_retry`:
- 3 attempts with 1s/2s/4s backoff.
- Logs parse failures.
- On final failure: the simulator returns a defaulted response (approve for approval gates, empty-string answer for text) and the test assertion likely fails — that's visible in the result.

## Limitations

- Personas are prompt-only — no memory across questions beyond the transcript.
- Persona drift if the LLM is inconsistent. Using a stable model (glm-4.7 or similar) for the simulator helps.
- Can't simulate long-form domain expertise reliably — personas work best for "style" decisions, not deep-knowledge questions.
