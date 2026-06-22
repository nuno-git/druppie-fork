"""Tests for FallbackLLM sticky degraded mode.

Simulates the scenario from issue #76: primary model is unavailable,
verify that after the first fallback, subsequent calls avoid slow retries.
"""

import asyncio

from druppie.llm.base import BaseLLM, LLMError, LLMResponse, ServerError
from druppie.llm.fallback import FallbackLLM


class MockLLM(BaseLLM):
    """Mock LLM that can be configured to fail or succeed."""

    def __init__(self, name: str, should_fail: bool = False):
        self._name = name
        self.should_fail = should_fail
        self.call_count = 0
        self.max_retries = 3

    @property
    def model(self) -> str:
        return self._name

    @property
    def model_name(self) -> str:
        return self._name

    @property
    def provider_name(self) -> str:
        return self._name

    def chat(self, messages, tools=None):
        self.call_count += 1
        if self.should_fail:
            raise ServerError(f"{self._name} is down", provider=self._name)
        return LLMResponse(content=f"response from {self._name}", provider=self._name, model=self._name)

    async def achat(self, messages, tools=None, max_tokens=None):
        self.call_count += 1
        if self.should_fail:
            raise ServerError(f"{self._name} is down", provider=self._name)
        return LLMResponse(content=f"response from {self._name}", provider=self._name, model=self._name)

    def get_call_history(self):
        return []

    def clear_call_history(self):
        pass


def test_normal_mode_uses_primary():
    """When primary works, fallback is never called."""
    primary = MockLLM("primary")
    fallback = MockLLM("fallback")
    llm = FallbackLLM(primary, fallback, session_id="sess-1")

    resp = llm.chat([{"role": "user", "content": "hi"}])

    assert resp.provider == "primary"
    assert primary.call_count == 1
    assert fallback.call_count == 0
    assert not llm.degraded

    FallbackLLM.clear_session("sess-1")


def test_first_failure_activates_fallback_and_degrades():
    """First primary failure falls back and enters degraded mode."""
    primary = MockLLM("primary", should_fail=True)
    fallback = MockLLM("fallback")
    llm = FallbackLLM(primary, fallback, session_id="sess-2")

    resp = llm.chat([{"role": "user", "content": "hi"}])

    assert resp.provider == "fallback"
    assert primary.call_count == 1
    assert fallback.call_count == 1
    assert llm.degraded
    assert "sess-2" in FallbackLLM._degraded_sessions

    FallbackLLM.clear_session("sess-2")


def test_same_run_skips_primary_after_failure():
    """Within the same agent run, primary is skipped entirely after failure."""
    primary = MockLLM("primary", should_fail=True)
    fallback = MockLLM("fallback")
    llm = FallbackLLM(primary, fallback, session_id="sess-3")

    # Call 1: primary fails, falls back
    llm.chat([{"role": "user", "content": "msg1"}])
    assert primary.call_count == 1
    assert fallback.call_count == 1

    # Calls 2-5: primary should be skipped entirely
    for i in range(4):
        resp = llm.chat([{"role": "user", "content": f"msg{i+2}"}])
        assert resp.provider == "fallback"

    assert primary.call_count == 1  # never called again
    assert fallback.call_count == 5

    FallbackLLM.clear_session("sess-3")


def test_new_run_probes_primary_once_in_degraded_mode():
    """New agent run in same session: probes primary once (no retries), then falls back."""
    session_id = "sess-4"
    primary1 = MockLLM("primary", should_fail=True)
    fallback1 = MockLLM("fallback")

    # Agent run 1: triggers degraded mode
    llm1 = FallbackLLM(primary1, fallback1, session_id=session_id)
    llm1.chat([{"role": "user", "content": "hi"}])
    assert llm1.degraded

    # Agent run 2: new FallbackLLM, same session — should start degraded
    primary2 = MockLLM("primary", should_fail=True)
    fallback2 = MockLLM("fallback")
    llm2 = FallbackLLM(primary2, fallback2, session_id=session_id)

    assert llm2.degraded  # starts degraded from session state

    # Call 1: probes primary once, fails, instant fallback
    resp = llm2.chat([{"role": "user", "content": "msg1"}])
    assert resp.provider == "fallback"
    assert primary2.call_count == 1
    assert primary2.max_retries == 3  # restored after probe

    # Call 2: skips primary entirely (failed this run)
    resp = llm2.chat([{"role": "user", "content": "msg2"}])
    assert resp.provider == "fallback"
    assert primary2.call_count == 1  # not called again

    FallbackLLM.clear_session(session_id)


def test_degraded_probe_disables_retries():
    """In degraded mode, the primary probe has max_retries=0."""
    session_id = "sess-5"

    # First run: enter degraded
    p1 = MockLLM("primary", should_fail=True)
    f1 = MockLLM("fallback")
    llm1 = FallbackLLM(p1, f1, session_id=session_id)
    llm1.chat([{"role": "user", "content": "hi"}])

    # Second run: check retries are disabled during probe
    p2 = MockLLM("primary", should_fail=True)
    p2.max_retries = 3
    f2 = MockLLM("fallback")
    llm2 = FallbackLLM(p2, f2, session_id=session_id)

    retries_during_call = []
    original_chat = p2.chat

    def spy_chat(messages, tools=None):
        retries_during_call.append(p2.max_retries)
        return original_chat(messages, tools)

    p2.chat = spy_chat
    llm2.chat([{"role": "user", "content": "probe"}])

    assert retries_during_call == [0]  # retries were disabled
    assert p2.max_retries == 3  # restored after

    FallbackLLM.clear_session(session_id)


def test_primary_recovers_in_degraded_mode():
    """If primary recovers during a degraded probe, use it."""
    session_id = "sess-6"

    # First run: enter degraded
    p1 = MockLLM("primary", should_fail=True)
    f1 = MockLLM("fallback")
    llm1 = FallbackLLM(p1, f1, session_id=session_id)
    llm1.chat([{"role": "user", "content": "hi"}])

    # Second run: primary is back
    p2 = MockLLM("primary", should_fail=False)
    f2 = MockLLM("fallback")
    llm2 = FallbackLLM(p2, f2, session_id=session_id)

    resp = llm2.chat([{"role": "user", "content": "hello"}])
    assert resp.provider == "primary"
    assert p2.call_count == 1
    assert f2.call_count == 0

    FallbackLLM.clear_session(session_id)


def test_different_session_not_degraded():
    """Degraded state is per-session, doesn't leak to other sessions."""
    # Session A: enter degraded
    pa = MockLLM("primary", should_fail=True)
    fa = MockLLM("fallback")
    llm_a = FallbackLLM(pa, fa, session_id="sess-A")
    llm_a.chat([{"role": "user", "content": "hi"}])
    assert llm_a.degraded

    # Session B: should NOT be degraded
    pb = MockLLM("primary", should_fail=False)
    fb = MockLLM("fallback")
    llm_b = FallbackLLM(pb, fb, session_id="sess-B")
    assert not llm_b.degraded

    resp = llm_b.chat([{"role": "user", "content": "hi"}])
    assert resp.provider == "primary"

    FallbackLLM.clear_session("sess-A")
    FallbackLLM.clear_session("sess-B")


def test_clear_session_removes_degraded():
    """clear_session removes the degraded state."""
    session_id = "sess-7"
    p = MockLLM("primary", should_fail=True)
    f = MockLLM("fallback")
    llm = FallbackLLM(p, f, session_id=session_id)
    llm.chat([{"role": "user", "content": "hi"}])
    assert session_id in FallbackLLM._degraded_sessions

    FallbackLLM.clear_session(session_id)
    assert session_id not in FallbackLLM._degraded_sessions

    # New instance should not be degraded
    p2 = MockLLM("primary", should_fail=False)
    f2 = MockLLM("fallback")
    llm2 = FallbackLLM(p2, f2, session_id=session_id)
    assert not llm2.degraded


def test_async_degraded_flow():
    """Same degraded behavior works for async achat()."""
    session_id = "sess-8"

    async def run():
        # Run 1: enter degraded
        p1 = MockLLM("primary", should_fail=True)
        f1 = MockLLM("fallback")
        llm1 = FallbackLLM(p1, f1, session_id=session_id)
        resp = await llm1.achat([{"role": "user", "content": "hi"}])
        assert resp.provider == "fallback"
        assert llm1.degraded

        # Run 1, call 2: skip primary
        resp = await llm1.achat([{"role": "user", "content": "hi2"}])
        assert resp.provider == "fallback"
        assert p1.call_count == 1  # only called once

        # Run 2: probe primary once, fail, instant fallback
        p2 = MockLLM("primary", should_fail=True)
        f2 = MockLLM("fallback")
        llm2 = FallbackLLM(p2, f2, session_id=session_id)
        assert llm2.degraded

        resp = await llm2.achat([{"role": "user", "content": "msg1"}])
        assert resp.provider == "fallback"
        assert p2.call_count == 1

        # Run 2, call 2: skip primary
        resp = await llm2.achat([{"role": "user", "content": "msg2"}])
        assert p2.call_count == 1

        FallbackLLM.clear_session(session_id)

    asyncio.run(run())


def test_no_session_id_works_without_persistence():
    """Without session_id, degraded mode still works within the run but doesn't persist."""
    primary = MockLLM("primary", should_fail=True)
    fallback = MockLLM("fallback")
    llm = FallbackLLM(primary, fallback)  # no session_id

    llm.chat([{"role": "user", "content": "hi"}])
    assert llm.degraded

    # Second call: skips primary (same run)
    llm.chat([{"role": "user", "content": "hi2"}])
    assert primary.call_count == 1

    # New instance without session_id: NOT degraded (no persistence)
    p2 = MockLLM("primary", should_fail=False)
    f2 = MockLLM("fallback")
    llm2 = FallbackLLM(p2, f2)
    assert not llm2.degraded


if __name__ == "__main__":
    test_normal_mode_uses_primary()
    test_first_failure_activates_fallback_and_degrades()
    test_same_run_skips_primary_after_failure()
    test_new_run_probes_primary_once_in_degraded_mode()
    test_degraded_probe_disables_retries()
    test_primary_recovers_in_degraded_mode()
    test_different_session_not_degraded()
    test_clear_session_removes_degraded()
    test_async_degraded_flow()
    test_no_session_id_works_without_persistence()
    print("\nAll 10 tests passed!")
