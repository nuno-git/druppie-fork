# BA Agent Baseline Test Results — 2026-04-23 (Updated 2026-04-28)

Baseline evaluation of the Business Analyst agent prompt before negative prompting rewrite.
Tests run across two batches due to infrastructure interruptions.

- Batch 1: `49684a79-0a67-4090-b21a-06dac10601c9` (4 of 13 completed before server restart)
- Batch 2: `8102bbe8-f3c8-4a12-a8b9-1e8ffd9b32ae` (10 tests, completed)
- LLM model: `zai/glm-5`
- Judge model: `zai/glm-4.5-air`
- Branch: `feature/ba-evaluation-tests`

## Results Summary

| Test | Judge Verdict | Manual Verdict | Duration | Notes |
|------|--------------|----------------|----------|-------|
| ba-challenges-public-personal-data | FAIL | **FAIL** | 15m 57s | Real: didn't challenge privacy proactively, multiple questions per HITL call |
| ba-chat-routes-to-architect | FAIL | **PASS** | 2m 36s | Judge false negative — BA behavior was correct |
| ba-clarifies-vague-terms | FAIL | **FAIL** | 13m 49s | Real: invented numbers from vague terms, 62% fabricated requirements |
| ba-context-gathering | PASS | **PASS** | 17m 42s | BA correctly called registry/project tools before elicitation |
| ba-cooperative-full-fd | FAIL | **PARTIAL FAIL** | 17m 20s | 2 real issues + 2 judge parse errors. ~86% of checks actually passed |
| ba-design-no-bias | FAIL | **PASS** | 14m 58s | Pre-existing check wording error (asked for hitl_ask_question, BA correctly used multiple choice) |
| ba-fd-reject-then-approve | FAIL | **PASS** | 17m 27s | Judge parse error on 1 check, BA handled reject-revise-approve correctly |
| ba-general-chat-advice | PASS | **PASS** | 2m 33s | BA gave advice without starting project intake |
| ba-no-fd-for-bugfix | FAIL | **INVALID TEST** | 1m 33s | Test infrastructure bug: BA never saw the actual bug report. BA responded to setup message instead, then test ended before BA could process the bug. Needs re-run with proper sequencing. |
| ba-no-technical-jargon | PASS | **PASS** | 15m 33s | BA avoided all jargon (GDPR, PII, etc.) in user-facing questions. 1/1 judge check passed. |
| ba-platform-standards-not-restated | FAIL | **FAIL** | 12m 47s | BA included "25 concurrent users" in NFR-02 without user ever mentioning this number. Manually reviewed: confirmed judge verdict is correct (not false negative). 5/6 judge checks passed. |
| ba-refuses-skip-questions | FAIL | **FAIL** | 7m 20s | BA compromised on making assumptions after user repeatedly tried to skip. Said "I'll make assumptions for everything else" instead of firmly refusing. Created design based on 1 genuine answer + 6 assumptions. |
| ba-unpacks-solution-speak | PASS | **PASS** | 13m 37s | All assertions (9/9) and judge checks (8/8) passed. BA correctly dug deeper instead of accepting "dashboard" as the requirement. |

**Manual pass rate: 7/14 tests passed** (includes 1 test with judge parse errors where BA behavior was correct)

## Real BA Issues Found

### 1. Fabricates requirements (critical)
The BA consistently invents functional and non-functional requirements that were never discussed with or confirmed by the user. In the `ba-clarifies-vague-terms` test, 62% of requirements were fabricated. In `ba-cooperative-full-fd`, 40% were fabricated (FR-03, FR-04, FR-07, FR-12, FR-13 never confirmed by user).

### 2. Restates platform standards as project-specific NFRs (critical)
The BA includes performance numbers from `docs/platform-functional-standards.md` (e.g., "25 concurrent users", "within 2 seconds") as project-specific NFRs, even though the prompt says to treat platform standards as givens and not restate them.

### 3. Invents specific numbers from vague user input (critical)
When the user says "snel" (fast) or "makkelijke" (easy), the BA silently translates these into specific measurable values (e.g., "within 2 seconds loading", "max 5 steps") without asking the user to confirm. This is the original issue that triggered this evaluation.

### 4. Does not proactively challenge security/privacy concerns (moderate)
When the user requested making personal inspector data (names, contact details) publicly accessible, the BA did not challenge this during elicitation. The privacy concern was only caught by the approval gate reviewer rejecting the FD. The BA should have raised the concern in user-friendly language during the conversation.

### 5. Multiple questions per HITL call (moderate)
The BA bundles 2+ questions in single `hitl_ask_multiple_choice_question` calls (e.g., "What triggered this project?" AND "What happens now?"). The prompt requires exactly one question per tool call.

### 6. Gives up too easily when users are uncooperative (critical)
When users repeatedly try to skip questions or ask the BA to make assumptions, the BA compromises instead of firmly refusing. In `ba-refuses-skip-questions`, after the user said "Make assumptions for everything", the BA said "I'll make assumptions for everything else after this ONE question" and proceeded to create a full functional design based on 1 genuine answer and 6 assumptions. The BA should refuse to proceed without adequate input.

## Judge Reliability Issues

The `glm-4.5-air` judge model had several problems:

1. **Parse errors (2 occurrences)**: Judge returned truncated/empty JSON responses, causing auto-fails. One truncated response was actually returning `{"pass": true, ...}` before cutting off.
2. **False negatives (2 occurrences)**: Judge correctly analyzed that the BA did the right thing, then still returned `pass: false`. Example: "The BA actually provided extensive advice... The check incorrectly claims the BA immediately ended the conversation" — yet still failed.
3. **Check wording sensitivity**: Checks phrased as negations ("should not have...") or that describe wrong behavior confuse the judge into failing correct behavior.

**Recommendation**: Consider upgrading judge profile to `glm-5` for more reliable evaluation, or tighten check wording to use positive assertions.

## Tests Still Pending

### ba-no-fd-for-bugfix - Test Infrastructure Fixed, Awaiting Planner Fix (2026-04-28)

**Status**: Test infrastructure fixed and re-run, but test fails due to planner routing bug.

**Infrastructure Fix Applied** (2026-04-28):
- Removed `continue_session: true` and `agents` list from test configuration
- Test now starts a fresh session that references the existing project so router naturally classifies as `update_project`
- Database corruption issue resolved and database reset successfully

**Re-run Results** (2026-04-28):
- Test execution: Successful (setup works, router correctly classifies as update_project)
- Duration: ~79 seconds
- **Failure Root Cause**: The planner incorrectly routes small bug reports to `developer` agent instead of `business_analyst` agent. This is a known planner routing issue.
- **BA Agent Never Runs**: Because planner routes to developer, the BA agent never executes, so the test cannot evaluate BA behavior.

**Future Test Work Required** (once planner routing is fixed):
- Re-run this test to verify the BA correctly:
  1. Identifies the bug report as a technical issue (not a functional change)
  2. Asks a few clarifying questions about the bug (when it happens, which characters, etc.)
  3. Does NOT start full requirements elicitation for a new feature
  4. Calls `done()` with `NO_FD_CHANGE` in the summary
  5. Provides a clear technical description of the bug that the Architect can act on
  6. Does NOT call `coding:make_design` (writing an FD for a bug fix is incorrect)

All other 13 tests have completed and been manually reviewed.

After planner routing is fixed, manually review the test result (act as a second judge by reading the full agent traces from the API) since the `glm-4.5-air` judge model is unreliable — see "Judge Reliability Issues" below. Update this file with both the automated judge verdict and manual verdict.

Run with (after planner fix):
```bash
curl -X POST "http://localhost:8300/api/evaluations/run-tests" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"test_names": ["ba-no-fd-for-bugfix"], "execute": true, "judge": true}'
```

## Final Test Results (All Tests Completed)

As of 2026-04-28, 13 of 14 baseline tests have completed and been manually reviewed. Here are the detailed results:

### ba-unpacks-solution-speak ✅ PASSED
- **Assertions**: 9/9 passed (100%)
- **Judge checks**: 8/8 passed (100%)
- **Duration**: 13m 37s
- **Finding**: BA correctly recognized "I want a real-time dashboard" as solution-speak and probed for the underlying problem instead of accepting the dashboard as the requirement.

### ba-platform-standards-not-restated ❌ FAILED
- **Judge checks**: 5/6 passed (83%)
- **Duration**: 12m 47s
- **Failed check**: BA included "25 concurrent users" in NFR-02 without user ever mentioning this number
- **Manual review**: Confirmed judge verdict is correct (not false negative). Reviewed full 17-question conversation — user never mentioned any specific performance numbers or concurrent user counts.
- **Finding**: Confirms critical issue #2 — BA restates platform standards as project-specific NFRs

### ba-refuses-skip-questions ❌ FAILED
- **Judge checks**: 0/2 passed (0%)
- **Duration**: 7m 20s
- **Manual review**: Confirmed judge verdict is correct (not a false negative)
- **Finding**: BA compromised when user repeatedly tried to skip questions. After user said "Make assumptions for everything", BA said "I'll make assumptions for everything else after this ONE question" and proceeded to create a full functional design based on 1 genuine answer and 6 assumptions. Confirms new critical issue #6.

### ba-no-fd-for-bugfix 🔄 TEST INFRASTRUCTURE BUG (Fixed)
- **Status**: Invalid test — BA never saw the actual bug report
- **Duration**: 1m 33s
- **Issue**: Test used `continue_session: true` which caused agents to run before the new message was processed. BA only saw the setup message "Tool test: setup-project-with-fd" and never received the bug report
- **Fix applied**: Removed `continue_session: true` and `agents` list. Test now starts a fresh session with message referencing the existing project so router naturally classifies as `update_project`
- **Status**: Ready to re-run

**Final manual pass rate: 7/14 tests passed** (includes 1 test with judge parse errors where BA behavior was actually correct)

**Tests remaining: 1** (`ba-no-fd-for-bugfix` — re-run pending)

## Test Infrastructure Issues

1. **`ba-no-fd-for-bugfix`** ✅ FIXED: Test used `continue_session: true` which caused the BA to start processing BEFORE the bug report message was sent. BA only saw the setup message "Tool test: setup-project-with-fd" and never received the actual bug report about the search function. Fix applied: Removed `continue_session: true` and `agents` list. Test now starts a fresh session with a message that references the existing project ("In de recipe sharing app...") so the router naturally classifies it as `update_project`. Ready to re-run.
2. **`ba-chat-routes-to-architect` (original)**: Test sent a database technology question directly, which the planner correctly routed to the architect — the BA never ran. Redesigned to start with a BA-appropriate question and have the HITL persona pivot to a technical question mid-conversation.
3. **`ba-design-no-bias` (pre-existing)**: Check wording asks for `hitl_ask_question` specifically, but the BA correctly uses `hitl_ask_multiple_choice_question` (the preferred tool per the prompt). Check needs rewording.
