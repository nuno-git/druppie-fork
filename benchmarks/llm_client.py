"""Lightweight OpenAI-compatible LLM client for benchmarking.

Uses httpx directly — no application dependencies needed.
Supports streaming for TTFT measurement.
"""

import json
import os
import ssl
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx


def _load_dotenv() -> None:
    """Load .env file from project root if it exists."""
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if not os.getenv(key):
            os.environ[key] = value


_load_dotenv()


@dataclass
class BenchmarkResult:
    """Raw result from a single LLM call."""

    total_latency_ms: float = 0.0
    time_to_first_token_ms: float | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    tokens_per_second: float = 0.0
    prompt_eval_rate: float = 0.0
    response_text: str = ""
    error: str | None = None


@dataclass
class EndpointConfig:
    """Configuration for an OpenAI-compatible endpoint."""

    base_url: str
    api_key: str = ""
    ssl_verify: bool = True
    auth_type: str = "bearer"


@dataclass
class ModelConfig:
    """Full model configuration including optimization details."""

    endpoint_name: str
    model: str
    display_name: str
    max_context: int = 32768
    parameters: str = ""
    quantization: str | None = None
    kv_cache_quant: str | None = None
    flash_attention: bool = False
    gpu_layers: int = -1
    notes: str = ""
    endpoint: EndpointConfig = field(default_factory=lambda: EndpointConfig(base_url=""))

    def config_summary(self) -> str:
        parts = []
        if self.parameters:
            parts.append(f"{self.parameters} params")
        if self.quantization:
            parts.append(self.quantization)
        if self.kv_cache_quant:
            parts.append(f"KV:{self.kv_cache_quant}")
        if self.flash_attention:
            parts.append("flash_attn")
        if self.gpu_layers != 0:
            parts.append(f"GPU={self.gpu_layers}")
        return ", ".join(parts) if parts else "default"


def fetch_models(endpoint: EndpointConfig, timeout: float = 30.0) -> list[dict]:
    """Fetch available models from an OpenAI-compatible endpoint.

    Tries /v1/models (OpenAI standard) first, falls back to /api/tags (Ollama).
    Returns a list of dicts with at least 'id' (model name).
    """
    base_url = endpoint.base_url.rstrip("/")
    headers = _auth_headers(endpoint)

    transport = None
    if not endpoint.ssl_verify:
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
        transport = httpx.HTTPTransport(verify=ssl_context)

    client_kwargs = {"timeout": httpx.Timeout(timeout)}
    if transport:
        client_kwargs["transport"] = transport

    with httpx.Client(**client_kwargs) as client:
        # Try OpenAI-compatible /models endpoint
        try:
            url = f"{base_url}/models"
            resp = client.get(url, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            if "data" in data:
                return data["data"]
        except Exception:
            pass

        # Fallback: Ollama /api/tags
        try:
            ollama_base = base_url.replace("/v1", "")
            url = f"{ollama_base}/api/tags"
            resp = client.get(url, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            models = []
            for m in data.get("models", []):
                models.append({
                    "id": m.get("model") or m.get("name", ""),
                    "name": m.get("name", ""),
                    "size": m.get("size"),
                    "parameter_size": m.get("details", {}).get("parameter_size", ""),
                    "quantization_level": m.get("details", {}).get("quantization_level", ""),
                    "family": m.get("details", {}).get("family", ""),
                })
            return models
        except Exception:
            pass

    return []


def _resolve_env_vars(value: str) -> str:
    if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
        env_var = value[2:-1]
        return os.getenv(env_var, "")
    return value


def _auth_headers(endpoint: EndpointConfig) -> dict:
    api_key = _resolve_env_vars(endpoint.api_key) or "no-key-required"
    if endpoint.auth_type == "api-key":
        return {"api-key": api_key}
    return {"Authorization": f"Bearer {api_key}"}


def _compute_rates(result: BenchmarkResult) -> None:
    latency_sec = result.total_latency_ms / 1000
    if latency_sec > 0 and result.completion_tokens > 0:
        result.tokens_per_second = result.completion_tokens / latency_sec
    if latency_sec > 0 and result.prompt_tokens > 0:
        result.prompt_eval_rate = result.prompt_tokens / latency_sec


def call_llm(
    model_config: ModelConfig,
    messages: list[dict],
    tools: list[dict] | None = None,
    max_tokens: int | None = None,
    timeout: float = 300.0,
    stream: bool = True,
) -> BenchmarkResult:
    """Call an LLM via OpenAI-compatible API and measure performance."""
    endpoint = model_config.endpoint

    base_url = endpoint.base_url.rstrip("/")
    url = f"{base_url}/chat/completions"

    headers = {"Content-Type": "application/json", **_auth_headers(endpoint)}

    use_stream = stream and tools is None
    body: dict = {
        "model": model_config.model,
        "messages": messages,
        "stream": use_stream,
    }
    if use_stream:
        body["stream_options"] = {"include_usage": True}
    if tools:
        body["tools"] = tools
        body["stream"] = False
    if max_tokens is not None:
        body["max_tokens"] = max_tokens

    verify = endpoint.ssl_verify
    transport = None
    if not verify:
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
        transport = httpx.HTTPTransport(verify=ssl_context)

    result = BenchmarkResult()
    start = time.perf_counter()

    try:
        result = _do_call(url, headers, body, timeout, transport, start)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 400 and max_tokens is not None:
            err_body = e.response.text
            if "max_tokens" in err_body and "max_completion_tokens" in err_body:
                body.pop("max_tokens", None)
                body["max_completion_tokens"] = max_tokens
                start = time.perf_counter()
                try:
                    result = _do_call(url, headers, body, timeout, transport, start)
                except Exception as retry_e:
                    result.total_latency_ms = (time.perf_counter() - start) * 1000
                    result.error = str(retry_e)
            else:
                result.total_latency_ms = (time.perf_counter() - start) * 1000
                result.error = str(e)
        else:
            result.total_latency_ms = (time.perf_counter() - start) * 1000
            result.error = str(e)
    except httpx.TimeoutException:
        result.total_latency_ms = (time.perf_counter() - start) * 1000
        result.error = f"Timeout after {timeout}s"
    except httpx.ConnectError as e:
        result.total_latency_ms = (time.perf_counter() - start) * 1000
        result.error = f"Connection error: {e}"
    except Exception as e:
        result.total_latency_ms = (time.perf_counter() - start) * 1000
        result.error = str(e)

    return result


def _do_call(
    url: str,
    headers: dict,
    body: dict,
    timeout: float,
    transport: httpx.HTTPTransport | None,
    start: float,
) -> BenchmarkResult:
    if body.get("stream"):
        return _call_streaming(url, headers, body, timeout, transport, start)
    return _call_non_streaming(url, headers, body, timeout, transport, start)


def _call_streaming(
    url: str,
    headers: dict,
    body: dict,
    timeout: float,
    transport: httpx.HTTPTransport | None,
    start: float,
) -> BenchmarkResult:
    result = BenchmarkResult()
    first_token_time = None
    text_parts = []
    usage_data = None

    client_kwargs = {"timeout": httpx.Timeout(timeout)}
    if transport:
        client_kwargs["transport"] = transport

    with httpx.Client(**client_kwargs) as client:
        with client.stream("POST", url, headers=headers, json=body) as response:
            if response.status_code >= 400:
                response.read()
                response.raise_for_status()
            for line in response.iter_lines():
                if not line.startswith("data: "):
                    continue
                data_str = line[6:]
                if data_str == "[DONE]":
                    break
                try:
                    chunk = json.loads(data_str)
                except json.JSONDecodeError:
                    continue

                if "choices" in chunk and chunk["choices"]:
                    delta = chunk["choices"][0].get("delta", {})
                    content = delta.get("content")
                    if content and first_token_time is None:
                        first_token_time = time.perf_counter()
                        result.time_to_first_token_ms = (first_token_time - start) * 1000
                    if content:
                        text_parts.append(content)

                if "usage" in chunk and chunk["usage"]:
                    usage_data = chunk["usage"]

    end = time.perf_counter()
    result.total_latency_ms = (end - start) * 1000
    result.response_text = "".join(text_parts)

    if usage_data:
        result.prompt_tokens = usage_data.get("prompt_tokens", 0) or 0
        result.completion_tokens = usage_data.get("completion_tokens", 0) or 0
        result.total_tokens = usage_data.get("total_tokens", 0) or 0

    if result.completion_tokens == 0 and result.response_text:
        result.completion_tokens = len(result.response_text.split()) * 4 // 3

    _compute_rates(result)
    return result


def _call_non_streaming(
    url: str,
    headers: dict,
    body: dict,
    timeout: float,
    transport: httpx.HTTPTransport | None,
    start: float,
) -> BenchmarkResult:
    result = BenchmarkResult()

    client_kwargs = {"timeout": httpx.Timeout(timeout)}
    if transport:
        client_kwargs["transport"] = transport

    with httpx.Client(**client_kwargs) as client:
        response = client.post(url, headers=headers, json=body)
        response.raise_for_status()

    end = time.perf_counter()
    result.total_latency_ms = (end - start) * 1000

    data = response.json()
    if "choices" in data and data["choices"]:
        message = data["choices"][0].get("message", {})
        result.response_text = message.get("content", "") or ""

    usage = data.get("usage", {})
    if usage:
        result.prompt_tokens = usage.get("prompt_tokens", 0) or 0
        result.completion_tokens = usage.get("completion_tokens", 0) or 0
        result.total_tokens = usage.get("total_tokens", 0) or 0

    _compute_rates(result)
    return result
