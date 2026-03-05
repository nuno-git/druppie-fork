# Sandbox Resilience: Full-Stack Provider Failover & Smart Detection

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make sandbox coding tasks survive provider outages with three layers of defense: transparent proxy failover (A), smart failure detection (C1+C2+C3), and Druppie-level retry with next model (B).

**Architecture:** Three independent layers, implemented bottom-up. The proxy handles transient failures transparently. Detection signals propagate up through the control plane. Druppie orchestrates retries as last resort.

**Tech Stack:** TypeScript (control plane proxy + session-instance), Python (bridge, Druppie backend)

---

## Current State (Problem)

When a provider dies mid-sandbox:
1. Proxy returns 502/504 → OpenCode retries same provider → fails again
2. Sandbox sits idle — no webhook fires
3. **30-35 min** before watchdog marks session as FAILED
4. No retry with different model — session just fails

## Target State

```
Provider goes down
  ↓ (sub-second)
  Proxy tries next provider from model chain → transparent failover (A)
  ↓ (if ALL providers fail)
  Proxy error counter hits threshold → fires provider_unhealthy event (C1)
  ↓ (10-30 sec)
  Bridge detects session errors → emits provider_unhealthy event (C2)
  ↓ (parallel signal)
  Session instance tracks last_successful_llm_call → activity watchdog (C3)
  ↓ (1-5 min)
  Druppie receives failure webhook → retries with next model in chain (B)
  ↓ (30-60 sec sandbox spinup)
  New sandbox completes task with fallback model
```

---

## Implementation Order & Dependencies

```
Phase 1: Infrastructure (threading model chains)
  ├── Task 1: Thread modelChains to control plane
  └── Task 2: Store model chain in Druppie SandboxSession

Phase 2: Detection (C1 + C2 + C3)
  ├── Task 3: C1 — Proxy error counter + provider_unhealthy event
  ├── Task 4: C3 — Activity watchdog with LLM health tracking
  └── Task 5: C2 — Bridge-level LLM error detection

Phase 3: Proxy Failover (A)
  └── Task 6: Proxy-level transparent failover with model rewriting

Phase 4: Druppie Retry (B)
  ├── Task 7: Webhook handler retry logic
  └── Task 8: Watchdog retry logic

Phase 5: Commit & verify
  └── Task 9: End-to-end verification
```

---

## Phase 1: Infrastructure

### Task 1: Thread `modelChains` to control plane

The proxy needs the full model chain (not just the primary model) to know what to fail over to. Thread it from `builtin_tools.py` → `router.ts` → `session-instance.ts` → stored in-memory alongside credentials.

**Files:**
- Modify: `druppie/agents/builtin_tools.py`
- Modify: `vendor/open-inspect/packages/local-control-plane/src/router.ts`
- Modify: `vendor/open-inspect/packages/local-control-plane/src/session/session-instance.ts`
- Modify: `vendor/open-inspect/packages/local-control-plane/src/credentials/credential-store.ts`

**Step 1: Add `modelChains` to `create_body` in `builtin_tools.py`**

The model chain data already exists in `model_config` from the resolver. Add it to the session create request alongside `agentModels`:

```python
# In builtin_tools.py execute_sandbox_coding_task(), after model_config is resolved:
create_body: dict = {
    "repoOwner": sandbox_repo_owner,
    "repoName": sandbox_repo_name,
    "model": model,
    "agentModels": model_config.agents,
    "agentFiles": _load_agent_files(),
    "modelChains": _build_model_chains(model_config),   # NEW
    "title": f"Druppie sandbox: {task[:80]}",
    "credentials": { ... },
}
```

Add helper that builds a simple provider→model map for all chains. The proxy needs to know: "for proxy key X, if provider `zai` fails, try `anthropic` with model `anthropic/claude-sonnet-4-6`":

```python
def _build_model_chains() -> dict[str, list[dict[str, str]]]:
    """Build model chains for proxy failover.

    Returns dict mapping each model to its full chain of alternatives.
    E.g.: {"zai-coding-plan/glm-4.7": [
        {"provider": "zai", "model": "zai-coding-plan/glm-4.7"},
        {"provider": "anthropic", "model": "anthropic/claude-sonnet-4-6"},
    ]}
    """
    config = yaml.safe_load(_CONFIG_PATH.read_text())
    chains = {}
    for section in ("agents", "subagents"):
        for name, chain in config.get(section, {}).items():
            if chain:
                # Key by the first model in the chain (the one we resolve as primary)
                for entry in chain:
                    model = entry["model"]
                    if model not in chains:
                        chains[model] = chain
    return chains
```

Actually, simpler: just pass the raw YAML chains. The model_resolver already has the config. Import it:

```python
from druppie.sandbox.model_resolver import get_raw_model_chains

# add to create_body:
"modelChains": get_raw_model_chains(),
```

Add to `model_resolver.py`:

```python
def get_raw_model_chains() -> dict[str, list[dict[str, str]]]:
    """Return all model chains from sandbox_models.yaml, keyed by model string.

    Used by the proxy for failover — when a model's provider fails, the proxy
    tries the next model in the chain.
    """
    config = yaml.safe_load(_CONFIG_PATH.read_text())
    chains: dict[str, list[dict[str, str]]] = {}
    for section in ("agents", "subagents"):
        for _name, chain in config.get(section, {}).items():
            if chain:
                for entry in chain:
                    model_str = entry["model"]
                    if model_str not in chains:
                        chains[model_str] = [
                            {"provider": e["provider"], "model": e["model"]}
                            for e in chain
                        ]
    return chains
```

**Step 2: Pass `modelChains` through `router.ts` → `handleInit()`**

In `router.ts` POST /sessions handler, add to handleInit call:

```typescript
modelChains: body.modelChains ?? null,
```

**Step 3: Store in `session-instance.ts`**

Add private field and store in handleInit:

```typescript
private modelChains: Record<string, Array<{provider: string; model: string}>> | null = null;

// In handleInit():
this.modelChains = body.modelChains ?? null;
```

Inject as env var in `spawnSandbox()` and `restoreFromSnapshot()` (same pattern as agentModels):

```typescript
if (this.modelChains) {
    userEnvVars["SANDBOX_MODEL_CHAINS"] = JSON.stringify(this.modelChains);
}
```

**Step 4: Store model chains in credential store**

The proxy needs model chains for failover. Store them alongside LLM credentials.

In `credential-store.ts`, add to `StoredSession`:

```typescript
interface StoredSession {
    // ... existing fields ...
    /** Model chains for proxy failover — keyed by model string */
    modelChains: Record<string, Array<{provider: string; model: string}>> | null;
}
```

Add to `store()` method (accept via new parameter):

```typescript
store(sessionId: string, credentials: SessionCredentials, modelChains?: Record<string, Array<{provider: string; model: string}>>): ProxyKeys {
    // ... existing code ...
    const stored: StoredSession = {
        // ... existing fields ...
        modelChains: modelChains ?? null,
    };
}
```

Add accessor:

```typescript
getModelChains(proxyKey: string): Record<string, Array<{provider: string; model: string}>> | null {
    const sessionId = this.llmKeyIndex.get(proxyKey);
    if (!sessionId) return null;
    const stored = this.sessions.get(sessionId);
    return stored?.modelChains ?? null;
}

/** Get all available providers with credentials for a session (by proxy key). */
getAvailableProvidersByProxyKey(proxyKey: string): string[] {
    const sessionId = this.llmKeyIndex.get(proxyKey);
    if (!sessionId) return [];
    const stored = this.sessions.get(sessionId);
    if (!stored) return [];
    return Array.from(stored.llmCredentials.keys());
}
```

Update `router.ts` to pass modelChains to credential store:

```typescript
if (credentialStore && body.credentials) {
    proxyKeys = credentialStore.store(sessionId, body.credentials, body.modelChains);
    // ... rest unchanged ...
}
```

**Step 5: Commit**

```bash
git add -A && git commit -m "feat: thread model chains to control plane for proxy failover"
```

---

### Task 2: Store model chain in Druppie SandboxSession

For Approach B (retry), Druppie needs to know the full chain and which model was already tried.

**Files:**
- Modify: `druppie/db/models/sandbox_session.py`
- Modify: `druppie/repositories/sandbox_session_repository.py`
- Modify: `druppie/agents/builtin_tools.py`

**Step 1: Add columns to SandboxSession model**

```python
# In sandbox_session.py, add to SandboxSession class:
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text

# Model chain for retry (JSON array of {provider, model} dicts)
model_chain = Column(Text, nullable=True)       # JSON string
model_chain_index = Column(Integer, default=0)   # Which entry was used (0-based)
task_prompt = Column(Text, nullable=True)         # Original task for retry
agent_name = Column(String(100), nullable=True)   # Agent name for retry
```

**Step 2: Update repository create() to accept new fields**

```python
def create(
    self,
    sandbox_session_id: str,
    user_id: UUID,
    session_id: UUID | None = None,
    webhook_secret: str | None = None,
    model_chain: str | None = None,
    model_chain_index: int = 0,
    task_prompt: str | None = None,
    agent_name: str | None = None,
) -> SandboxSession:
    # ... existing code, add new fields to SandboxSession() constructor ...
    mapping = SandboxSession(
        sandbox_session_id=sandbox_session_id,
        user_id=user_id,
        session_id=session_id,
        webhook_secret=webhook_secret,
        model_chain=model_chain,
        model_chain_index=model_chain_index,
        task_prompt=task_prompt,
        agent_name=agent_name,
    )
```

**Step 3: Pass chain data in `builtin_tools.py`**

```python
# In execute_sandbox_coding_task(), when calling sandbox_repo.create():
import json

sandbox_repo.create(
    sandbox_session_id=sandbox_session_id,
    user_id=UUID(user_id),
    session_id=session_id,
    webhook_secret=webhook_secret,
    model_chain=json.dumps(model_config.get_chain_for_agent(agent)),
    model_chain_index=0,  # first model in chain
    task_prompt=task,
    agent_name=agent,
)
```

Add `get_chain_for_agent()` to `SandboxModelConfig`:

```python
# In model_resolver.py, add to resolve_sandbox_models():
# Store the raw chain for the primary agent for retry support
config = yaml.safe_load(_CONFIG_PATH.read_text())
agents_section = config.get("agents", {})
primary_chain = agents_section.get(requested_agent, [])
```

Actually, cleaner: add a method to model_resolver that returns the raw chain for an agent:

```python
def get_agent_chain(agent_name: str) -> list[dict[str, str]]:
    """Return the raw model chain for an agent from sandbox_models.yaml."""
    config = yaml.safe_load(_CONFIG_PATH.read_text())
    chain = config.get("agents", {}).get(agent_name)
    if not chain:
        chain = config.get("subagents", {}).get(agent_name, [])
    return chain or []
```

**Step 4: Reset DB**

```bash
docker compose --profile reset-db run --rm reset-db
```

**Step 5: Commit**

```bash
git add -A && git commit -m "feat: store model chain in SandboxSession for retry support"
```

---

## Phase 2: Detection

### Task 3: C1 — Proxy error counter with `provider_unhealthy` event

Track consecutive 5xx responses per proxyKey+provider. After N failures, notify the session instance.

**Files:**
- Modify: `vendor/open-inspect/packages/local-control-plane/src/proxy/llm-proxy.ts`
- Modify: `vendor/open-inspect/packages/local-control-plane/src/session/session-instance.ts`

**Step 1: Add error tracking to proxy**

Add to `llm-proxy.ts`, before `setupLlmProxy`:

```typescript
const CONSECUTIVE_ERROR_THRESHOLD = 3;

/**
 * Per-session error tracking for provider health detection.
 * Key: proxyKey, Value: Map<provider, consecutiveErrorCount>
 */
const sessionErrors = new Map<string, Map<string, number>>();

function trackLlmResult(
    proxyKey: string,
    provider: string,
    success: boolean,
    credentialStore: CredentialStore
): void {
    if (!sessionErrors.has(proxyKey)) {
        sessionErrors.set(proxyKey, new Map());
    }
    const counts = sessionErrors.get(proxyKey)!;

    if (success) {
        counts.set(provider, 0);
        return;
    }

    const errorCount = (counts.get(provider) || 0) + 1;
    counts.set(provider, errorCount);

    if (errorCount >= CONSECUTIVE_ERROR_THRESHOLD) {
        console.warn(
            `[llm-proxy] Provider ${provider} has ${errorCount} consecutive errors for proxy key ${proxyKey.slice(0, 8)}...`
        );
        // Notify session via internal event
        const sessionId = credentialStore.getSessionIdByLlmProxyKey(proxyKey);
        if (sessionId) {
            // Fire and forget — will be handled by session instance
            emitProviderUnhealthy(sessionId, provider, errorCount);
        }
        counts.set(provider, 0); // Reset to avoid repeated notifications
    }
}

/** Clean up error tracking when session is destroyed. */
export function clearSessionErrors(proxyKey: string): void {
    sessionErrors.delete(proxyKey);
}
```

The `emitProviderUnhealthy` function needs access to the session manager. Pass it via closure in `setupLlmProxy`:

```typescript
export function setupLlmProxy(
    app: Express,
    credentialStore: CredentialStore,
    onProviderUnhealthy?: (sessionId: string, provider: string, errorCount: number) => void
): void {
    // ... existing setup ...

    function emitProviderUnhealthy(sessionId: string, provider: string, errorCount: number) {
        if (onProviderUnhealthy) {
            onProviderUnhealthy(sessionId, provider, errorCount);
        }
    }
```

**Step 2: Call `trackLlmResult` on every upstream response**

In `handleStreamingRequest`, after receiving upstream status:

```typescript
// After: console.log(`[llm-proxy] ${provider} upstream responded status=...`)
const isError = upstreamRes.statusCode !== undefined && upstreamRes.statusCode >= 500;
trackLlmResult(proxyKey, provider, !isError, credentialStore);
```

In `handleBufferedRequest`, after receiving response:

```typescript
// After: console.log(`[llm-proxy] ${provider} buffered response status=...`)
trackLlmResult(proxyKey, provider, upstream.status < 500, credentialStore);
```

On timeout/error:

```typescript
// In upstream.on("timeout") and upstream.on("error"):
trackLlmResult(proxyKey, provider, false, credentialStore);
```

Pass `proxyKey` and `credentialStore` to both handler functions (add parameters).

**Step 3: Add `getSessionIdByLlmProxyKey` to credential store**

```typescript
// In credential-store.ts:
getSessionIdByLlmProxyKey(proxyKey: string): string | null {
    return this.llmKeyIndex.get(proxyKey) ?? null;
}
```

**Step 4: Wire up `onProviderUnhealthy` in `server.ts` (or wherever setupLlmProxy is called)**

Find where `setupLlmProxy` is called and pass the callback:

```typescript
setupLlmProxy(app, credentialStore, (sessionId, provider, errorCount) => {
    const instance = sessionManager.get(sessionId);
    // Use processSandboxEvent to fire through existing event pipeline
    instance.processSandboxEvent({
        type: "provider_unhealthy",
        provider,
        consecutiveErrors: errorCount,
        timestamp: Date.now(),
    }).catch(console.error);
});
```

**Step 5: Handle `provider_unhealthy` in session-instance.ts**

Add case in `processSandboxEvent`:

```typescript
case "provider_unhealthy":
    this.sql.exec(
        `INSERT INTO events (id, type, data, message_id, created_at) VALUES (?, ?, ?, ?, ?)`,
        generateId(),
        "provider_unhealthy",
        JSON.stringify(event),
        null,
        now
    );
    this.broadcast({ type: "sandbox_event", event });

    // Fire webhook to Druppie so it can retry with a different model
    // Find the processing message and send its callback
    const processingMsg = this.sql
        .exec("SELECT id FROM messages WHERE status = 'processing' LIMIT 1")
        .toArray()[0] as any;
    if (processingMsg) {
        this.sendWebhookCallback(processingMsg.id, false).catch((err) => {
            this.log.error("Provider unhealthy webhook failed", { error: String(err) });
        });
    }
    break;
```

**Step 6: Commit**

```bash
git add -A && git commit -m "feat: C1 — proxy error counter with provider_unhealthy detection"
```

---

### Task 4: C3 — Activity watchdog with LLM health tracking

Track `lastSuccessfulLlmCall` per session. Replace dumb inactivity timeout with smart one.

**Files:**
- Modify: `vendor/open-inspect/packages/local-control-plane/src/session/session-instance.ts`
- Modify: `vendor/open-inspect/packages/local-control-plane/src/proxy/llm-proxy.ts`

**Step 1: Add LLM health tracking fields to session-instance.ts**

```typescript
private lastSuccessfulLlmCall: number | null = null;
private lastLlmCallAttempt: number | null = null;

// New constant:
private static readonly LLM_FAILURE_TIMEOUT_MS = 300_000; // 5 minutes of LLM failures → kill
```

**Step 2: Add method to update LLM health from proxy**

```typescript
/** Called by proxy on each LLM call result. */
updateLlmHealth(success: boolean): void {
    const now = Date.now();
    this.lastLlmCallAttempt = now;
    if (success) {
        this.lastSuccessfulLlmCall = now;
    }
}
```

**Step 3: Wire from proxy via `onProviderUnhealthy` callback expansion**

Expand the proxy callback to also report successes. Change `setupLlmProxy` to accept a second callback:

```typescript
export function setupLlmProxy(
    app: Express,
    credentialStore: CredentialStore,
    callbacks?: {
        onProviderUnhealthy?: (sessionId: string, provider: string, errorCount: number) => void;
        onLlmResult?: (sessionId: string, success: boolean) => void;
    }
): void {
```

Call `callbacks.onLlmResult` on every response (success or failure):

```typescript
// After trackLlmResult():
if (callbacks?.onLlmResult) {
    const sessionId = credentialStore.getSessionIdByLlmProxyKey(proxyKey);
    if (sessionId) {
        callbacks.onLlmResult(sessionId, !isError);
    }
}
```

Wire in server setup:

```typescript
setupLlmProxy(app, credentialStore, {
    onProviderUnhealthy: (sessionId, provider, errorCount) => { ... },
    onLlmResult: (sessionId, success) => {
        const instance = sessionManager.get(sessionId);
        instance.updateLlmHealth(success);
    },
});
```

**Step 4: Enhance `handleAlarm` with smart LLM health check**

Replace the simple inactivity check with a smarter one:

```typescript
private async handleAlarm(): Promise<void> {
    const sandbox = this.getSandbox();
    if (!sandbox) return;
    if (sandbox.status === "stopped" || sandbox.status === "failed" || sandbox.status === "stale") return;

    const now = Date.now();
    const inactivityTimeoutMs = parseInt(this.config.SANDBOX_INACTIVITY_TIMEOUT_MS || "600000", 10);

    // Check 1: Total inactivity (no sandbox activity at all)
    if (sandbox.last_activity) {
        const inactiveTime = now - sandbox.last_activity;
        if (inactiveTime >= inactivityTimeoutMs) {
            this.log.info("Inactivity timeout", { last_activity: sandbox.last_activity });
            this.updateSandboxStatus("stopped");
            this.broadcast({ type: "sandbox_status", status: "stopped" });
            await this.destroySandboxContainer();
            const sandboxSocket = this.wsManager.getSandboxSocket();
            if (sandboxSocket) {
                this.wsManager.send(sandboxSocket, { type: "shutdown" });
            }
            return;
        }
    }

    // Check 2: LLM health — if LLM calls have been failing for LLM_FAILURE_TIMEOUT_MS
    if (this.lastLlmCallAttempt) {
        const lastSuccess = this.lastSuccessfulLlmCall || 0;
        const failingDuration = now - Math.max(lastSuccess, this.lastLlmCallAttempt - SessionInstance.LLM_FAILURE_TIMEOUT_MS);

        if (this.lastSuccessfulLlmCall === null || (now - this.lastSuccessfulLlmCall > SessionInstance.LLM_FAILURE_TIMEOUT_MS)) {
            // LLM has been failing for too long
            if (now - (this.lastSuccessfulLlmCall || this.lastLlmCallAttempt!) > SessionInstance.LLM_FAILURE_TIMEOUT_MS) {
                this.log.warn("LLM failure timeout", {
                    lastSuccessfulLlmCall: this.lastSuccessfulLlmCall,
                    lastLlmCallAttempt: this.lastLlmCallAttempt,
                    failingMs: now - (this.lastSuccessfulLlmCall || this.lastLlmCallAttempt!),
                });

                // Fire provider_unhealthy event + webhook
                const event = {
                    type: "provider_unhealthy",
                    reason: "llm_failure_timeout",
                    failingMs: now - (this.lastSuccessfulLlmCall || this.lastLlmCallAttempt!),
                    timestamp: now,
                };
                this.sql.exec(
                    `INSERT INTO events (id, type, data, message_id, created_at) VALUES (?, ?, ?, ?, ?)`,
                    generateId(), "provider_unhealthy", JSON.stringify(event), null, now
                );
                this.broadcast({ type: "sandbox_event", event });

                // Trigger webhook for processing message
                const processingMsg = this.sql
                    .exec("SELECT id FROM messages WHERE status = 'processing' LIMIT 1")
                    .toArray()[0] as any;
                if (processingMsg) {
                    this.sendWebhookCallback(processingMsg.id, false).catch(console.error);
                }

                // Kill the sandbox
                this.updateSandboxStatus("failed");
                this.broadcast({ type: "sandbox_error", error: "LLM provider unresponsive" });
                await this.destroySandboxContainer();
                return;
            }
        }
    }

    // Reschedule
    this.scheduleAlarm(now + Math.min(inactivityTimeoutMs, 60_000)); // Check every minute at most
}
```

**Step 5: Commit**

```bash
git add -A && git commit -m "feat: C3 — activity watchdog with LLM health tracking"
```

---

### Task 5: C2 — Bridge-level LLM error detection

The bridge sees `session.error` events from OpenCode. Detect LLM-specific errors and emit `provider_unhealthy`.

**Files:**
- Modify: `vendor/open-inspect/packages/modal-infra/src/sandbox/bridge.py`

**Step 1: Add LLM error tracking to bridge**

Add a counter in the bridge's `_stream_opencode_response_sse` method. When OpenCode reports errors that look like LLM provider failures (status 502, 504, rate limit, timeout), increment a counter. After 3 consecutive, emit event.

```python
# Add near top of AgentBridge class:
CONSECUTIVE_LLM_ERROR_THRESHOLD = 3

# Add instance variable in __init__:
self._consecutive_llm_errors = 0
```

**Step 2: Detect LLM errors in session.error events**

In `_stream_opencode_response_sse`, in the `session.error` handling:

```python
elif event_type == "session.error":
    error_session_id = props.get("sessionID")
    if error_session_id == self.opencode_session_id:
        error_msg = self._extract_error_message(props.get("error", {}))
        self.log.error("bridge.session_error", error_msg=error_msg)

        # Check if this is an LLM provider error
        if self._is_llm_provider_error(error_msg):
            self._consecutive_llm_errors += 1
            if self._consecutive_llm_errors >= self.CONSECUTIVE_LLM_ERROR_THRESHOLD:
                self.log.warn(
                    "bridge.provider_unhealthy",
                    consecutive_errors=self._consecutive_llm_errors,
                    error_msg=error_msg,
                )
                await self._send_event({
                    "type": "provider_unhealthy",
                    "reason": "bridge_detected_consecutive_llm_errors",
                    "consecutiveErrors": self._consecutive_llm_errors,
                    "lastError": error_msg or "Unknown",
                    "messageId": message_id,
                })
                self._consecutive_llm_errors = 0  # Reset after notification
        else:
            self._consecutive_llm_errors = 0  # Reset on non-LLM error

        yield {
            "type": "error",
            "error": error_msg or "Unknown error",
            "messageId": message_id,
        }
        return
```

**Step 3: Add `_is_llm_provider_error` method**

```python
@staticmethod
def _is_llm_provider_error(error_msg: str | None) -> bool:
    """Check if an error message indicates an LLM provider failure."""
    if not error_msg:
        return False
    error_lower = error_msg.lower()
    llm_patterns = [
        "502", "504", "503",
        "bad gateway", "gateway timeout", "service unavailable",
        "upstream", "proxy",
        "rate limit", "too many requests", "429",
        "connection refused", "connection reset",
        "timeout", "timed out",
        "api key", "authentication", "unauthorized",
        "internal server error", "500",
    ]
    return any(pattern in error_lower for pattern in llm_patterns)
```

**Step 4: Reset counter on successful LLM response**

In the token/step events (which indicate OpenCode is making progress with LLM), reset:

```python
# In the event streaming loop, when we see step_start or token events:
if event_type in ("session.updated", "message.updated"):
    # OpenCode is producing output — LLM is working
    self._consecutive_llm_errors = 0
```

**Step 5: Commit**

```bash
git add -A && git commit -m "feat: C2 — bridge-level LLM error detection"
```

---

## Phase 3: Proxy Failover

### Task 6: Proxy-level transparent failover with model rewriting

When the primary provider returns 5xx, try the next provider in the model chain.

**Files:**
- Modify: `vendor/open-inspect/packages/local-control-plane/src/proxy/llm-proxy.ts`

**Step 1: Add failover logic to the main proxy handler**

The key insight: we need to intercept the request BEFORE sending to upstream, check if we have alternative providers, and retry with model rewriting if the primary fails.

```typescript
// New function: attempt request with failover
async function attemptWithFailover(
    req: Request,
    res: Response,
    primaryProvider: string,
    primaryCreds: LlmCredentials & { sessionId: string },
    proxyKey: string,
    apiPath: string,
    body: Buffer,
    credentialStore: CredentialStore,
    callbacks?: { onLlmResult?: ... }
): Promise<void> {
    const modelChains = credentialStore.getModelChains(proxyKey);
    const streaming = req.method === "POST" && body.length > 0 && isStreamingRequest(body);

    // Build list of providers to try: primary first, then alternatives from chain
    const providersToTry: Array<{provider: string; creds: LlmCredentials; model: string | null}> = [
        { provider: primaryProvider, creds: primaryCreds, model: null }, // null = don't rewrite
    ];

    // Find alternative providers from model chains
    if (modelChains) {
        const requestModel = extractModelFromBody(body);
        if (requestModel) {
            const chain = modelChains[requestModel];
            if (chain) {
                for (const entry of chain) {
                    const altBaseProvider = entry.provider.split("-")[0];
                    if (altBaseProvider === primaryProvider.split("-")[0]) continue; // Skip same provider
                    const altCreds = credentialStore.getByLlmProxyKey(proxyKey, altBaseProvider);
                    if (altCreds) {
                        providersToTry.push({
                            provider: altBaseProvider,
                            creds: altCreds,
                            model: entry.model,  // rewrite model to this
                        });
                    }
                }
            }
        }
    }

    // Try each provider
    for (let i = 0; i < providersToTry.length; i++) {
        const attempt = providersToTry[i];
        const isLastAttempt = i === providersToTry.length - 1;

        // Rewrite model in body if needed
        let attemptBody = body;
        if (attempt.model) {
            attemptBody = rewriteModelInBody(body, attempt.model);
        }

        // Build upstream URL for this provider
        const baseUrl = attempt.creds.baseUrl || PROVIDER_BASE_URLS[attempt.provider] || "";
        if (!baseUrl) continue;

        let finalApiPath = apiPath;
        const versionRewrite = API_VERSION_REWRITE[attempt.provider];
        // ... same path rewriting logic as existing code ...

        const upstreamUrl = `${baseUrl.replace(/\/$/, "")}/${finalApiPath}`;
        const headers: Record<string, string> = { /* same header building */ };
        injectAuthHeaders(headers, attempt.provider, attempt.creds.apiKey);

        if (i > 0) {
            console.log(`[llm-proxy] FAILOVER: trying ${attempt.provider} (attempt ${i + 1}/${providersToTry.length}) model=${attempt.model}`);
        }

        if (streaming) {
            // For streaming, we can only failover if the upstream fails BEFORE sending headers
            const result = await attemptStreamingWithFailover(upstreamUrl, req.method, headers, attemptBody, res, attempt.provider);
            if (result === "success" || result === "headers_sent") {
                // Success or partially sent (can't retry)
                return;
            }
            // result === "failed_before_headers" → try next provider
            if (isLastAttempt) {
                // All providers failed
                if (!res.headersSent) {
                    res.status(502).json({ error: "All providers failed" });
                }
                return;
            }
            continue;
        } else {
            // Buffered: straightforward retry
            const result = await attemptBufferedRequest(upstreamUrl, req.method, headers, attemptBody, attempt.provider);
            if (result.status < 500 || isLastAttempt) {
                // Success or last attempt — send response
                res.status(result.status);
                if (result.contentType) res.setHeader("Content-Type", result.contentType);
                res.send(result.body);
                return;
            }
            // 5xx and not last attempt → try next provider
            console.log(`[llm-proxy] ${attempt.provider} returned ${result.status}, trying next provider`);
            continue;
        }
    }
}
```

**Step 2: Helper functions**

```typescript
function extractModelFromBody(body: Buffer): string | null {
    try {
        const parsed = JSON.parse(body.toString());
        return parsed.model || null;
    } catch {
        return null;
    }
}

function rewriteModelInBody(body: Buffer, newModel: string): Buffer {
    try {
        const parsed = JSON.parse(body.toString());
        parsed.model = newModel;
        return Buffer.from(JSON.stringify(parsed));
    } catch {
        return body;
    }
}
```

**Step 3: Split streaming handler to support failover**

The critical insight: for streaming, we can only retry if the upstream fails BEFORE we've sent response headers. Create `attemptStreamingWithFailover` that returns a status:

```typescript
type StreamResult = "success" | "headers_sent" | "failed_before_headers";

async function attemptStreamingWithFailover(
    url: string, method: string, headers: Record<string, string>,
    body: Buffer, res: Response, provider: string
): Promise<StreamResult> {
    return new Promise<StreamResult>((resolve) => {
        const parsed = new URL(url);
        const transport = parsed.protocol === "https:" ? https : http;
        const startTime = Date.now();

        const options: http.RequestOptions = {
            hostname: parsed.hostname,
            port: parsed.port || (parsed.protocol === "https:" ? 443 : 80),
            path: parsed.pathname + parsed.search,
            method,
            headers: { ...headers, "Content-Length": Buffer.byteLength(body).toString() },
            timeout: CONNECT_TIMEOUT_MS,
        };

        const upstream = transport.request(options, (upstreamRes) => {
            const ttfb = Date.now() - startTime;
            console.log(`[llm-proxy] ${provider} upstream responded status=${upstreamRes.statusCode} ttfb=${ttfb}ms`);

            if (upstreamRes.statusCode && upstreamRes.statusCode >= 500) {
                // 5xx BEFORE headers sent — can retry
                // Consume the error body to free the socket
                upstreamRes.resume();
                upstreamRes.on("end", () => resolve("failed_before_headers"));
                return;
            }

            // Success or 4xx — forward response (can't retry after this)
            // ... existing streaming forwarding code ...
            res.writeHead(upstreamRes.statusCode || 200, { /* headers */ });
            upstreamRes.on("data", (chunk) => res.write(chunk));
            upstreamRes.on("end", () => { res.end(); resolve("success"); });
            upstreamRes.on("error", () => { res.end(); resolve("headers_sent"); });
        });

        upstream.on("timeout", () => {
            upstream.destroy();
            resolve("failed_before_headers");
        });

        upstream.on("error", () => {
            resolve("failed_before_headers");
        });

        upstream.write(body);
        upstream.end();
    });
}
```

**Step 4: Apply version rewriting per-provider in failover loop**

Extract the existing path rewriting into a helper:

```typescript
function rewriteApiPath(apiPath: string, provider: string, baseUrl: string): string {
    let finalPath = apiPath;
    const versionRewrite = API_VERSION_REWRITE[provider];
    if (versionRewrite !== undefined && finalPath.startsWith("v1/")) {
        if (versionRewrite === null) {
            finalPath = finalPath.slice(3);
        } else {
            const baseEndsWithVersion = baseUrl.replace(/\/$/, "").endsWith(`/${versionRewrite}`);
            if (baseEndsWithVersion) {
                finalPath = finalPath.slice(3);
            } else {
                finalPath = `${versionRewrite}/${finalPath.slice(3)}`;
            }
        }
    }
    return finalPath;
}
```

**Step 5: Replace main handler with failover-aware version**

The main `app.all("/llm-proxy/:proxyKey/:provider/*", ...)` handler delegates to `attemptWithFailover` instead of directly calling `handleStreamingRequest`/`handleBufferedRequest`.

**Step 6: Commit**

```bash
git add -A && git commit -m "feat: A — proxy-level transparent failover with model rewriting"
```

---

## Phase 4: Druppie Retry

### Task 7: Webhook handler retry logic

When a sandbox fails, check if there are more models in the chain. If yes, create a new sandbox with the next model.

**Files:**
- Modify: `druppie/api/routes/sandbox.py`
- Modify: `druppie/agents/builtin_tools.py` (extract sandbox creation into reusable function)

**Step 1: Extract sandbox creation into a reusable function**

Move the sandbox creation logic from `execute_sandbox_coding_task` into a standalone function that can be called for retries:

```python
# New file: druppie/sandbox/create_sandbox.py

async def create_sandbox_session(
    task: str,
    agent: str,
    model: str,
    session_id: UUID,
    user_id: str,
    repo_owner: str,
    repo_name: str,
    model_chain: list[dict] | None = None,
    model_chain_index: int = 0,
    execution_repo: "ExecutionRepository" | None = None,
) -> dict:
    """Create a sandbox session with the given model.

    Returns dict with sandbox_session_id on success, or error on failure.
    Reusable by both execute_coding_task (first attempt) and retry logic.
    """
    # ... extracted from execute_sandbox_coding_task ...
```

This is a significant refactor. For simplicity, keep the existing function but add a retry helper that creates a NEW sandbox:

```python
# In sandbox.py routes, add:
async def _retry_sandbox_with_next_model(
    sandbox_mapping: SandboxSession,
    tool_call_id: UUID,
    db: Session,
) -> bool:
    """Attempt to retry the sandbox with the next model in the chain.

    Returns True if retry was initiated, False if no more models to try.
    """
    import json

    if not sandbox_mapping.model_chain or not sandbox_mapping.task_prompt:
        return False

    chain = json.loads(sandbox_mapping.model_chain)
    next_index = (sandbox_mapping.model_chain_index or 0) + 1

    if next_index >= len(chain):
        logger.info(
            "sandbox_retry_chain_exhausted",
            sandbox_session_id=sandbox_mapping.sandbox_session_id,
            tried_models=next_index,
            chain_length=len(chain),
        )
        return False

    next_entry = chain[next_index]
    next_model = next_entry["model"]
    next_provider = next_entry["provider"]

    # Check if the next provider's API key is available
    from druppie.sandbox.model_resolver import PROVIDER_API_KEYS
    env_var = PROVIDER_API_KEYS.get(next_provider)
    if not env_var or not os.getenv(env_var):
        logger.warning(
            "sandbox_retry_provider_unavailable",
            provider=next_provider,
            model=next_model,
        )
        # Skip this entry and try the next one
        # Recursive call with incremented index
        sandbox_mapping.model_chain_index = next_index
        db.flush()
        return await _retry_sandbox_with_next_model(sandbox_mapping, tool_call_id, db)

    logger.info(
        "sandbox_retry_with_next_model",
        sandbox_session_id=sandbox_mapping.sandbox_session_id,
        next_model=next_model,
        next_provider=next_provider,
        chain_index=next_index,
    )

    # Create a new sandbox session using the builtin tool's logic
    # We re-invoke execute_sandbox_coding_task with the new model
    from druppie.agents.builtin_tools import execute_sandbox_coding_task_with_model

    result = await execute_sandbox_coding_task_with_model(
        task=sandbox_mapping.task_prompt,
        agent=sandbox_mapping.agent_name or "druppie-builder",
        model=next_model,
        session_id=sandbox_mapping.session_id,
        user_id=sandbox_mapping.user_id,
        tool_call_id=tool_call_id,
        model_chain=sandbox_mapping.model_chain,
        model_chain_index=next_index,
        db=db,
    )

    return result.get("success", False)
```

**Step 2: Add `execute_sandbox_coding_task_with_model` to builtin_tools.py**

Extract the HTTP calls from `execute_sandbox_coding_task` into a function that accepts a model parameter:

```python
async def execute_sandbox_coding_task_with_model(
    task: str,
    agent: str,
    model: str,
    session_id: UUID,
    user_id: UUID,
    tool_call_id: UUID,
    model_chain: str | None = None,
    model_chain_index: int = 0,
    db: Session = None,
) -> dict:
    """Create a sandbox with a specific model. Used for retries."""
    # ... same HTTP logic as execute_sandbox_coding_task but with explicit model ...
    # ... register in sandbox_sessions with model_chain and model_chain_index ...
    # ... link to existing tool_call_id ...
```

**Step 3: Modify webhook handler to attempt retry on failure**

In `sandbox_complete_webhook`, after detecting `success=false`:

```python
# After building the result dict, BEFORE completing the tool call:
if not body.success:
    # Attempt retry with next model in chain
    retry_initiated = await _retry_sandbox_with_next_model(
        sandbox_mapping, tool_call.id, db
    )
    if retry_initiated:
        logger.info(
            "sandbox_webhook_retry_initiated",
            sandbox_session_id=sandbox_session_id,
            tool_call_id=str(tool_call.id),
        )
        # Don't complete the tool call — keep it in WAITING_SANDBOX state
        # The new sandbox will fire its own webhook when done
        sandbox_repo.mark_completed(sandbox_session_id)
        db.commit()
        return {"status": "retrying", "sandbox_session_id": sandbox_session_id}
    # else: no retry possible, fall through to normal failure handling
```

**Step 4: Commit**

```bash
git add -A && git commit -m "feat: B — Druppie-level sandbox retry with next model in chain"
```

---

### Task 8: Watchdog retry logic

The watchdog already detects stuck sandboxes. Enhance it to try the next model instead of just failing.

**Files:**
- Modify: `druppie/api/routes/sandbox.py`

**Step 1: Add retry logic to watchdog**

In `sandbox_watchdog_loop`, after detecting a stuck tool call:

```python
for tc in stuck_tool_calls:
    try:
        # Check if we can retry with next model
        sandbox_mapping = sandbox_repo.get_by_tool_call_id(tc.id)
        if sandbox_mapping:
            retry_initiated = await _retry_sandbox_with_next_model(
                sandbox_mapping, tc.id, db
            )
            if retry_initiated:
                # Cancel the old sandbox but don't fail the tool call
                sandbox_repo.mark_completed(sandbox_mapping.sandbox_session_id)
                # Reset sandbox_waiting_at for the new sandbox
                execution_repo.update_tool_call(
                    tc.id,
                    sandbox_waiting_at=datetime.now(timezone.utc),
                )
                db.commit()
                logger.info(
                    "sandbox_watchdog_retry_initiated",
                    tool_call_id=str(tc.id),
                    sandbox_session_id=sandbox_mapping.sandbox_session_id,
                )
                # Best-effort cancel old sandbox on control plane
                try:
                    # ... existing cancel logic ...
                except Exception:
                    pass
                continue  # Don't fail the tool call

        # No retry possible — fail as before
        execution_repo.update_tool_call(
            tc.id,
            status=ToolCallStatus.FAILED,
            error=f"Sandbox timed out after {SANDBOX_TIMEOUT_MINUTES} minutes",
        )
        # ... rest of existing failure handling ...
```

**Step 2: Commit**

```bash
git add -A && git commit -m "feat: B — watchdog retry with next model on timeout"
```

---

## Phase 5: Commit & Verify

### Task 9: End-to-end verification

**Step 1: Commit submodule changes**

```bash
cd vendor/open-inspect
git add -A
git commit -m "feat: sandbox resilience — proxy failover, error tracking, activity watchdog"
git push origin feat/per-agent-models
```

**Step 2: Update submodule ref and commit cleaner-druppie**

```bash
cd ../..
git add vendor/open-inspect druppie/
git commit -m "feat: full-stack sandbox resilience — proxy failover + smart detection + retry"
git push origin feature/execute-coding-task
```

**Step 3: Build and start**

```bash
docker compose build sandbox-image-builder sandbox-control-plane druppie-backend-dev
docker compose --profile reset-db run --rm reset-db
docker compose --profile dev --profile init up -d
```

**Step 4: Verify backend starts without errors**

```bash
docker compose logs druppie-backend-dev | grep -i "error\|traceback"
# Expected: no errors
```

**Step 5: Verify control plane starts**

```bash
docker compose logs sandbox-control-plane | tail -5
# Expected: "Local Control Plane running on http://localhost:8787"
```

**Step 6: Functional verification (manual)**

1. Trigger a builder agent task
2. Check control plane logs for `[llm-proxy]` lines showing normal flow
3. To test failover: temporarily set an invalid ZAI API key
4. Verify proxy logs show failover attempt
5. Verify webhook fires with success=false and retry is attempted

---

## Implementation Notes

**User directive:** Continue working autonomously. Use subagents for reviewing, testing e2e, debugging. Commit intermediate changes. Document everything. Do not stop until it works. Delegate via subagents to stay compact.

**Implementation status (2026-03-05):**
- Phase 1: DONE — model chains threaded, SandboxSession columns added
- Phase 2: DONE — C1 proxy error counter, C2 bridge detection, C3 LLM health watchdog
- Phase 3: DONE — proxy failover with model rewriting in llm-proxy.ts
- Phase 4: DONE — webhook retry + watchdog retry with _retry_sandbox_with_next_model
- Phase 5: DONE — built, E2E tested, two additional bugs found and fixed

**Code review fixes applied:**
1. Watchdog retry resets sandbox_waiting_at to prevent immediate re-retries
2. Duplicate webhook guard via completed_at check
3. Fixed broken repoOwner fallback in retry function
4. C3 requires minimum 3 failed attempts before killing sandbox
5. Bridge LLM error patterns made more specific to avoid false positives
6. Try-catch around session manager callbacks in index.ts

**E2E testing fixes (2026-03-05):**
7. OpenCode config key: `"agent"` (singular) not `"agents"` (plural) — OpenCode 1.2.16 rejects unrecognized keys
8. Proxy path rewrite: handle paths without `v1/` prefix — OpenCode SDK sends `chat/completions` not `v1/chat/completions` when using custom baseURL

**E2E test results:**
- OpenCode starts without config errors
- Proxy correctly rewrites ZAI paths to `/api/paas/v4/chat/completions`
- Bridge connects via WebSocket
- Model chains stored in credential store
- Failover infrastructure verified (only ZAI has credentials in test env, so failover destination unavailable)
- ZAI returns 429 (billing issue) — treated as 4xx (no failover), correct by design

---

## Files Summary

| File | Repo | Change | Phase |
|---|---|---|---|
| `druppie/sandbox/model_resolver.py` | cleaner-druppie | Add `get_raw_model_chains()`, `get_agent_chain()` | 1 |
| `druppie/agents/builtin_tools.py` | cleaner-druppie | Add modelChains to create_body, extract retry helper | 1, 4 |
| `druppie/db/models/sandbox_session.py` | cleaner-druppie | Add model_chain, model_chain_index, task_prompt, agent_name columns | 1 |
| `druppie/repositories/sandbox_session_repository.py` | cleaner-druppie | Accept new fields in create() | 1 |
| `druppie/api/routes/sandbox.py` | cleaner-druppie | Retry logic in webhook + watchdog | 4 |
| `vendor/.../router.ts` | background-agents | Pass modelChains to handleInit + credential store | 1 |
| `vendor/.../session-instance.ts` | background-agents | Store modelChains, LLM health tracking, smart alarm | 1, 2 |
| `vendor/.../credential-store.ts` | background-agents | Store modelChains, new accessors | 1 |
| `vendor/.../llm-proxy.ts` | background-agents | Error counter, LLM result callbacks, failover logic | 2, 3 |
| `vendor/.../bridge.py` | background-agents | LLM error detection, provider_unhealthy events | 2 |
