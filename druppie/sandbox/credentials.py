"""Build sandbox credentials for the control plane.

Single source of truth for LLM and Git credential payloads sent to the
control plane when creating sandbox sessions. Both the initial creation
path (builtin_tools) and the retry path (sandbox routes) import from here.
"""

import os

from druppie.sandbox.model_resolver import PROVIDER_API_KEYS

# Provider name -> base URL. Must stay in sync with PROVIDER_API_KEYS.
PROVIDER_BASE_URLS: dict[str, str] = {
    "zai": "https://open.bigmodel.cn/api/paas",
    "deepseek": "https://api.deepseek.com",
    # NOTE: /v1 not /v1/openai — the sandbox LLM proxy appends its own path segments
    "deepinfra": "https://api.deepinfra.com/v1",
    "openai": "https://api.openai.com",
    "anthropic": "https://api.anthropic.com",
}

# Env-var overrides for base URLs (only providers that support custom endpoints).
_BASE_URL_ENV_VARS: dict[str, str] = {
    "zai": "ZAI_BASE_URL",
    "deepseek": "DEEPSEEK_BASE_URL",
    "deepinfra": "DEEPINFRA_BASE_URL",
}


def build_llm_credentials() -> list[dict[str, str]]:
    """Return LLM credential dicts for every configured provider."""
    credentials: list[dict[str, str]] = []
    for provider, api_key_env in PROVIDER_API_KEYS.items():
        api_key = os.getenv(api_key_env, "")
        if api_key:
            env_override = _BASE_URL_ENV_VARS.get(provider)
            base_url = (
                os.getenv(env_override, PROVIDER_BASE_URLS[provider])
                if env_override
                else PROVIDER_BASE_URLS.get(provider, "")
            )
            credentials.append({
                "provider": provider,
                "apiKey": api_key,
                "baseUrl": base_url,
            })
    return credentials


def build_git_credentials() -> dict[str, str]:
    """Return the Git credential dict for the control plane."""
    return {
        "provider": "gitea",
        "url": os.getenv("GITEA_INTERNAL_URL", "http://gitea:3000"),
        "username": os.getenv("GITEA_ADMIN_USER", "gitea_admin"),
        "password": os.getenv("GITEA_ADMIN_PASSWORD", ""),
    }
