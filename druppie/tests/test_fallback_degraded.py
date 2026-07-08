"""Tests for FallbackLLM ask-first fallback pattern.

Verifies that FallbackLLM raises FallbackAvailableError when the primary
fails, and uses the fallback directly once the session is approved.
"""

import asyncio

import pytest

from druppie.llm.base import BaseLLM, FallbackAvailableError, LLMError, LLMResponse, ServerError
from druppie.llm.fallback import FallbackLLM


class MockLLM(BaseLLM):
    """Mock LLM that can be configured to fail or succeed."""

    def __init__(self, name: str, should_fail: bool = False):
        self._name = name
        self.should_fail = should_fail
        self.call_count = 0

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


@pytest.fixture(autouse=True)
def _clean_approval_state():
    """Clear all approval state before and after each test."""
    FallbackLLM._approved_sessions.clear()
    FallbackLLM._approved_agents.clear()
    yield
    FallbackLLM._approved_sessions.clear()
    FallbackLLM._approved_agents.clear()


def test_normal_mode_uses_primary():
    """When primary works, fallback is never called."""
    primary = MockLLM("primary")
    fallback = MockLLM("fallback")
    llm = FallbackLLM(primary, fallback, session_id="sess-1")

    resp = llm.chat([{"role": "user", "content": "hi"}])

    assert resp.provider == "primary"
    assert primary.call_count == 1
    assert fallback.call_count == 0


def test_primary_failure_raises_fallback_available():
    """When primary fails, FallbackAvailableError is raised (not silent switch)."""
    primary = MockLLM("primary", should_fail=True)
    fallback = MockLLM("fallback")
    llm = FallbackLLM(primary, fallback, session_id="sess-2")

    with pytest.raises(FallbackAvailableError) as exc_info:
        llm.chat([{"role": "user", "content": "hi"}])

    assert exc_info.value.primary_provider == "primary"
    assert exc_info.value.fallback_provider == "fallback"
    assert primary.call_count == 1
    assert fallback.call_count == 0


def test_approved_session_uses_fallback_directly():
    """After session approval, calls go straight to fallback."""
    primary = MockLLM("primary", should_fail=True)
    fallback = MockLLM("fallback")
    llm = FallbackLLM(primary, fallback, session_id="sess-3")

    FallbackLLM.approve_fallback("sess-3")

    resp = llm.chat([{"role": "user", "content": "hi"}])
    assert resp.provider == "fallback"
    assert primary.call_count == 0
    assert fallback.call_count == 1


def test_approved_agent_uses_fallback():
    """Per-agent approval routes only that agent to fallback."""
    primary = MockLLM("primary", should_fail=True)
    fallback = MockLLM("fallback")
    llm = FallbackLLM(primary, fallback, session_id="sess-4", agent_id="agent-a")

    FallbackLLM.approve_fallback_for_agent("sess-4", "agent-a")

    resp = llm.chat([{"role": "user", "content": "hi"}])
    assert resp.provider == "fallback"
    assert primary.call_count == 0


def test_agent_approval_does_not_apply_to_other_agents():
    """Per-agent approval does not affect a different agent in the same session."""
    primary = MockLLM("primary", should_fail=True)
    fallback = MockLLM("fallback")
    llm = FallbackLLM(primary, fallback, session_id="sess-5", agent_id="agent-b")

    FallbackLLM.approve_fallback_for_agent("sess-5", "agent-a")

    with pytest.raises(FallbackAvailableError):
        llm.chat([{"role": "user", "content": "hi"}])


def test_clear_session_removes_approval():
    """clear_session removes all approval state for that session."""
    FallbackLLM.approve_fallback("sess-6")
    FallbackLLM.approve_fallback_for_agent("sess-6", "agent-x")

    FallbackLLM.clear_session("sess-6")

    assert "sess-6" not in FallbackLLM._approved_sessions
    assert ("sess-6", "agent-x") not in FallbackLLM._approved_agents


def test_different_session_not_approved():
    """Approval is per-session, doesn't leak to other sessions."""
    FallbackLLM.approve_fallback("sess-A")

    primary = MockLLM("primary", should_fail=True)
    fallback = MockLLM("fallback")
    llm = FallbackLLM(primary, fallback, session_id="sess-B")

    with pytest.raises(FallbackAvailableError):
        llm.chat([{"role": "user", "content": "hi"}])


def test_async_fallback_available():
    """Async achat raises FallbackAvailableError on primary failure."""
    session_id = "sess-7"

    async def run():
        primary = MockLLM("primary", should_fail=True)
        fallback = MockLLM("fallback")
        llm = FallbackLLM(primary, fallback, session_id=session_id)

        with pytest.raises(FallbackAvailableError):
            await llm.achat([{"role": "user", "content": "hi"}])

    asyncio.run(run())


def test_async_approved_uses_fallback():
    """Async achat uses fallback directly when session is approved."""
    session_id = "sess-8"

    async def run():
        primary = MockLLM("primary", should_fail=True)
        fallback = MockLLM("fallback")
        llm = FallbackLLM(primary, fallback, session_id=session_id)
        FallbackLLM.approve_fallback(session_id)

        resp = await llm.achat([{"role": "user", "content": "hi"}])
        assert resp.provider == "fallback"

    asyncio.run(run())


def test_fallback_properties():
    """FallbackLLM exposes fallback provider/model properties."""
    primary = MockLLM("primary")
    fallback = MockLLM("fallback")
    llm = FallbackLLM(primary, fallback, session_id="sess-9")

    assert llm.fallback_provider == "fallback"
    assert llm.fallback_model == "fallback"
    assert llm.provider_name == "primary"
    assert llm.model == "primary"
