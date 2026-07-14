"""Tests for dynamic local-model selection (llm/local_models.py).

The llmkube profile is an ordered preference list; entries are filtered
against the models the endpoint actually serves. Pinned guarantees:

1. Preference order wins: the first listed model that is served becomes
   primary; listed-but-not-served models are dropped.
2. 'auto' picks up newly deployed models that are not ranked yet, without
   duplicating a model already claimed by an earlier entry.
3. An external provider is NEVER silently promoted to primary: when discovery
   fails or nothing local is served, one llmkube entry always survives at the
   front of the chain.
"""

from unittest.mock import patch

import pytest

from druppie.llm import local_models
from druppie.llm.local_models import apply_local_availability


@pytest.fixture(autouse=True)
def _fresh_discovery_cache():
    local_models.reset_discovery_cache()

QWEN = "Qwen/Qwen3.6-27B"
NEW_MODEL = "some-org/Brand-New-70B"
ZAI = {"provider": "zai", "model": "glm-5"}


def _llmkube(model):
    return {"provider": "llmkube", "model": model}


def _with_served(served):
    return patch.object(local_models, "list_served_models", return_value=served)


# --- preference order --------------------------------------------------------

def test_preferred_model_kept_when_served():
    with _with_served([QWEN]):
        result = apply_local_availability([_llmkube(QWEN), _llmkube("auto")])
    assert result[0] == _llmkube(QWEN)


def test_unserved_listed_model_is_dropped():
    with _with_served([NEW_MODEL]):
        result = apply_local_availability(
            [_llmkube(QWEN), _llmkube(NEW_MODEL), _llmkube("auto")]
        )
    models = [e["model"] for e in result]
    assert QWEN not in models
    assert models[0] == NEW_MODEL


def test_preference_order_decides_primary_when_multiple_served():
    with _with_served([NEW_MODEL, QWEN]):
        result = apply_local_availability([_llmkube(QWEN), _llmkube(NEW_MODEL)])
    assert [e["model"] for e in result] == [QWEN, NEW_MODEL]


# --- 'auto' catch-all --------------------------------------------------------

def test_auto_resolves_to_unranked_new_model():
    with _with_served([QWEN, NEW_MODEL]):
        result = apply_local_availability([_llmkube(QWEN), _llmkube("auto")])
    assert [e["model"] for e in result] == [QWEN, NEW_MODEL]


def test_auto_does_not_duplicate_a_claimed_model():
    with _with_served([QWEN]):
        result = apply_local_availability([_llmkube(QWEN), _llmkube("auto")])
    assert [e["model"] for e in result] == [QWEN]


def test_auto_alone_picks_first_served_model():
    with _with_served([NEW_MODEL, QWEN]):
        result = apply_local_availability([_llmkube("auto")])
    assert [e["model"] for e in result] == [NEW_MODEL]


# --- never silently external -------------------------------------------------

def test_nothing_served_keeps_a_local_primary():
    with _with_served([]):
        result = apply_local_availability([_llmkube(QWEN), ZAI])
    assert result[0]["provider"] == "llmkube"
    assert result[0]["model"] is None  # env/default fallback at call time
    assert ZAI in result


def test_discovery_failure_keeps_static_config():
    with _with_served(None):
        result = apply_local_availability([_llmkube(QWEN), _llmkube("auto"), ZAI])
    assert result[0] == _llmkube(QWEN)
    assert result[1]["model"] is None  # 'auto' degrades to env/default
    assert result[2] == ZAI


def test_non_local_entries_pass_through_untouched():
    with _with_served([QWEN]):
        result = apply_local_availability([ZAI, _llmkube(QWEN)])
    assert result == [ZAI, _llmkube(QWEN)]


def test_chain_without_local_entries_skips_discovery():
    with patch.object(local_models, "list_served_models") as discovery:
        result = apply_local_availability([ZAI])
    discovery.assert_not_called()
    assert result == [ZAI]


# --- discovery client --------------------------------------------------------

def test_list_served_models_parses_openai_model_list():
    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"data": [{"id": QWEN}, {"id": NEW_MODEL}, {"object": "model"}]}

    with patch.object(local_models.httpx, "get", return_value=_Resp()) as get:
        assert local_models.list_served_models() == [QWEN, NEW_MODEL]
    url = get.call_args.args[0]
    assert url.endswith("/models")


def test_list_served_models_returns_none_on_error():
    with patch.object(local_models.httpx, "get", side_effect=OSError("down")):
        assert local_models.list_served_models() is None


def test_discovery_result_is_cached_within_ttl():
    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"data": [{"id": QWEN}]}

    with patch.object(local_models.httpx, "get", return_value=_Resp()) as get:
        assert local_models.list_served_models() == [QWEN]
        assert local_models.list_served_models() == [QWEN]
    assert get.call_count == 1


def test_discovery_failure_is_cached_too():
    with patch.object(local_models.httpx, "get", side_effect=OSError("down")) as get:
        assert local_models.list_served_models() is None
        assert local_models.list_served_models() is None
    assert get.call_count == 1
