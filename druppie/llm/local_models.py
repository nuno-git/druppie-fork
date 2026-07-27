"""Dynamic model discovery for the in-cluster LLMKube/vLLM endpoint.

The `llmkube` profile lists local models in preference order (best first).
Which models are actually served changes as they are rolled in and out of the
cluster, so profile entries are filtered against the endpoint's
OpenAI-compatible model list (GET {base_url}/models) at resolution time.

The special model name 'auto' is a catch-all: it resolves to the first served
model not already claimed by an earlier entry, so a newly deployed local model
is usable before it has been ranked in the profile.

Discovery is cached for a short TTL (results AND failures). resolve_model()
is synchronous and — via lazy agent-LLM creation — runs on the backend's
event-loop thread, so the discovery GET blocks the loop for up to its timeout
when the endpoint is slow or down. The cache bounds that to at most one stall
per TTL window instead of one per resolution (e.g. model-management listing
resolves every agent in a loop). Same precedent as resolver._profiles_cache.

Failure semantics are deliberate: llmkube entries are never ALL dropped. If
discovery fails or nothing listed is served, one llmkube entry survives (model
falls back to LLMKUBE_MODEL env / provider default), so an external provider
is never silently promoted to primary — a broken local endpoint surfaces as a
failed call plus fallback-approval request, not as silent external spend.
"""

import os
import threading
import time

import httpx
import structlog

from .litellm_provider import PROVIDER_CONFIGS

logger = structlog.get_logger()

LOCAL_PROVIDER = "llmkube"
AUTO_MODEL = "auto"

_DISCOVERY_TIMEOUT = 3.0
_DISCOVERY_CACHE_TTL = 60.0

_cache_lock = threading.Lock()
_cached_served: list[str] | None = None
_cached_at: float | None = None


def reset_discovery_cache() -> None:
    """Forget the cached served-model list (tests / forced re-discovery)."""
    global _cached_served, _cached_at
    with _cache_lock:
        _cached_served = None
        _cached_at = None


def _endpoint_base_url() -> str:
    config = PROVIDER_CONFIGS[LOCAL_PROVIDER]
    url = os.getenv(config["base_url_env"], "") or config["default_base_url"]
    return url.rstrip("/")


def list_served_models() -> list[str] | None:
    """Return model ids served by the LLMKube endpoint, or None when unknown.

    Cached for _DISCOVERY_CACHE_TTL seconds, failures included — a down
    endpoint costs one blocking GET per TTL window, not one per resolution
    (see module docstring).
    """
    global _cached_served, _cached_at
    with _cache_lock:
        if _cached_at is not None and time.monotonic() - _cached_at < _DISCOVERY_CACHE_TTL:
            return _cached_served
    served = _fetch_served_models()
    with _cache_lock:
        _cached_served = served
        _cached_at = time.monotonic()
    return served


def _fetch_served_models() -> list[str] | None:
    headers = {}
    api_key = os.getenv(PROVIDER_CONFIGS[LOCAL_PROVIDER]["api_key_env"], "")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        resp = httpx.get(
            f"{_endpoint_base_url()}/models",
            headers=headers,
            timeout=_DISCOVERY_TIMEOUT,
        )
        resp.raise_for_status()
        served = [m["id"] for m in resp.json().get("data", []) if m.get("id")]
    except Exception as exc:
        logger.warning("llmkube_model_discovery_failed", error=str(exc))
        return None

    logger.info("llmkube_models_discovered", models=served)
    return served


def apply_local_availability(entries: list[dict]) -> list[dict]:
    """Filter/resolve llmkube profile entries against the served-model list.

    Non-llmkube entries pass through untouched and keep their position.
    llmkube entries: an explicit model is kept only when the endpoint serves
    it; 'auto' resolves to the first served model not claimed by an earlier
    entry. At least one llmkube entry always survives (see module docstring).
    """
    local_entries = [e for e in entries if e.get("provider") == LOCAL_PROVIDER]
    if not local_entries:
        return entries

    served = list_served_models()
    if served is None:
        # Endpoint unknown — keep static config; 'auto' falls back to the
        # LLMKUBE_MODEL env / provider default at client construction.
        return [
            {**e, "model": None}
            if e.get("provider") == LOCAL_PROVIDER and e.get("model") == AUTO_MODEL
            else e
            for e in entries
        ]

    result: list[dict] = []
    claimed: set[str] = set()
    for entry in entries:
        if entry.get("provider") != LOCAL_PROVIDER:
            result.append(entry)
            continue
        model = entry.get("model")
        if not model or model == AUTO_MODEL:
            remaining = [m for m in served if m not in claimed]
            if remaining:
                claimed.add(remaining[0])
                result.append({**entry, "model": remaining[0]})
            continue
        if model in served:
            claimed.add(model)
            result.append(entry)
        else:
            logger.info("llmkube_model_not_served", model=model, served=served)

    if not any(e.get("provider") == LOCAL_PROVIDER for e in result):
        # Nothing local matched — keep one llmkube entry as primary anyway so
        # an external fallback is never silently promoted; the call will fail
        # loudly instead.
        result.insert(0, {**local_entries[0], "model": None})
        logger.warning("llmkube_no_listed_model_served", served=served)

    return result
