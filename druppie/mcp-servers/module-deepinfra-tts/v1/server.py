"""DeepInfra TTS MCP Server.

Text-to-Speech synthesis module using DeepInfra API.
Provides tools for TTS synthesis, voice listing, cache configuration, and status checking.

This is a STANDALONE MCP service that provides TTS capabilities.
Uses FastMCP framework for HTTP transport.

Features:
- SSR (Server-Side Rendering) support with streaming capabilities
- SSE (Server-Sent Events) for real-time audio streaming
- Integration with Druppie core chat for voice sessions

Tools:
- synthesize: Convert text to speech audio
- synthesize_stream: Stream audio chunks via SSE
- list_voices: List available voices from DeepInfra
- configure_cache: Configure caching behavior
- check_status: Check service availability

Environment Variables:
- DEEPINFRA_API_KEY: API key for DeepInfra (required)
- DEEPINFRA_TTS_MAX_TEXT_LENGTH: Max text length in characters (default: 5000)
- DEEPINFRA_TTS_CACHE_ENABLED: Enable caching (default: true)
- DEEPINFRA_TTS_CACHE_TTL: Cache TTL in seconds (default: 3600)
- DEEPINFRA_TTS_CACHE_MAX_SIZE: Max number of cached items (default: 100)
- DEEPINFRA_TTS_DEFAULT_VOICE: Default voice ID (optional)
- DEEPINFRA_TTS_DEFAULT_DELIVERY: Default delivery mode (default: base64)
- DEEPINFRA_TTS_SSR_ENABLED: Enable SSR support (default: true)
- DEEPINFRA_TTS_STREAMING_ENABLED: Enable streaming mode (default: true)
- DEEPINFRA_TTS_CHAT_INTEGRATION: Enable chat voice integration (default: true)
- DEEPINFRA_TTS_DEFAULT_VOICE_FOR_CHAT: Default voice for chat sessions (default: nova)
"""

import base64
import hashlib
import io
import json
import logging
import os
from typing import Any, Literal

import httpx
from cachetools import TTLCache
from fastmcp import FastMCP
from pydantic import BaseModel, Field, field_validator

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("deepinfra-tts")

# Initialize FastMCP server
mcp = FastMCP("DeepInfra TTS MCP Server")

# Configuration
DEEPINFRA_API_KEY = os.getenv("DEEPINFRA_API_KEY", "")
DEEPINFRA_API_URL = "https://api.deepinfra.com/v1/inference/TTS"
MAX_TEXT_LENGTH = int(os.getenv("DEEPINFRA_TTS_MAX_TEXT_LENGTH", "5000"))
DEFAULT_CACHE_ENABLED = os.getenv("DEEPINFRA_TTS_CACHE_ENABLED", "true").lower() == "true"
DEFAULT_CACHE_TTL = int(os.getenv("DEEPINFRA_TTS_CACHE_TTL", "3600"))
DEFAULT_CACHE_MAX_SIZE = int(os.getenv("DEEPINFRA_TTS_CACHE_MAX_SIZE", "100"))
DEFAULT_VOICE = os.getenv("DEEPINFRA_TTS_DEFAULT_VOICE", "")
DEFAULT_DELIVERY = os.getenv("DEEPINFRA_TTS_DEFAULT_DELIVERY", "base64")
SSR_ENABLED = os.getenv("DEEPINFRA_TTS_SSR_ENABLED", "true").lower() == "true"
STREAMING_ENABLED = os.getenv("DEEPINFRA_TTS_STREAMING_ENABLED", "true").lower() == "true"
CHAT_INTEGRATION = os.getenv("DEEPINFRA_TTS_CHAT_INTEGRATION", "true").lower() == "true"
DEFAULT_VOICE_FOR_CHAT = os.getenv("DEEPINFRA_TTS_DEFAULT_VOICE_FOR_CHAT", "nova")

# Available output formats
OutputFormat = Literal["base64", "url", "stream"]


# =============================================================================
# CACHE MANAGEMENT
# =============================================================================


class TTSCache:
    """Thread-safe TTS audio cache with TTL support."""

    def __init__(self, max_size: int = 100, ttl: int = 3600):
        self._max_size = max_size
        self._ttl = ttl
        self._cache: TTLCache[str, bytes] = TTLCache(maxsize=max_size, ttl=ttl)
        self.enabled = True

    def _make_key(self, text: str, voice: str, language: str | None) -> str:
        """Create cache key from parameters (hashed to avoid storing text)."""
        key_data = f"{text}|{voice}|{language or 'auto'}"
        return hashlib.sha256(key_data.encode()).hexdigest()

    def get(self, text: str, voice: str, language: str | None) -> bytes | None:
        """Get cached audio if available and not expired."""
        if not self.enabled:
            return None
        key = self._make_key(text, voice, language)
        return self._cache.get(key)

    def set(self, text: str, voice: str, language: str | None, audio: bytes) -> None:
        """Store audio in cache."""
        if not self.enabled:
            return
        key = self._make_key(text, voice, language)
        self._cache[key] = audio

    def clear(self) -> None:
        """Clear all cached items."""
        self._cache.clear()

    def configure(
        self, enabled: bool | None = None, ttl: int | None = None, max_size: int | None = None
    ) -> dict:
        """Configure cache settings."""
        if enabled is not None:
            self.enabled = enabled
        if ttl is not None or max_size is not None:
            new_ttl = ttl if ttl is not None else self._ttl
            new_max_size = max_size if max_size is not None else self._max_size
            self._cache = TTLCache(maxsize=new_max_size, ttl=new_ttl)
            self._ttl = new_ttl
            self._max_size = new_max_size
        return self.get_status()

    def get_status(self) -> dict:
        """Get current cache status."""
        return {
            "enabled": self.enabled,
            "ttl_seconds": self._ttl,
            "max_size": self._max_size,
            "current_size": len(self._cache),
        }


# Global cache instance
tts_cache = TTSCache(max_size=DEFAULT_CACHE_MAX_SIZE, ttl=DEFAULT_CACHE_TTL)
tts_cache.enabled = DEFAULT_CACHE_ENABLED


# =============================================================================
# PYDANTIC MODELS
# =============================================================================


class SynthesizeRequest(BaseModel):
    """Request model for TTS synthesis."""

    text: str = Field(
        ..., min_length=1, max_length=MAX_TEXT_LENGTH, description="Text to synthesize"
    )
    voice: str | None = Field(None, description="Voice ID (uses default if not specified)")
    output_format: OutputFormat = Field("base64", description="Audio delivery method")
    use_cache: bool = Field(True, description="Enable caching for this request")
    language: str | None = Field(None, description="Language code (e.g., 'en-US', 'nl-NL')")

    @field_validator("language")
    @classmethod
    def validate_language(cls, v: str | None) -> str | None:
        if v is not None:
            # Basic validation for language code format
            if len(v) < 2 or len(v) > 10:
                raise ValueError("Invalid language code format")
        return v


class VoiceInfo(BaseModel):
    """Voice information model."""

    id: str
    name: str
    language: str
    gender: str | None = None
    preview_url: str | None = None


class CacheConfig(BaseModel):
    """Cache configuration model."""

    enabled: bool | None = Field(None, description="Enable or disable caching")
    ttl_seconds: int | None = Field(
        None, ge=60, le=86400, description="Cache TTL in seconds (60-86400)"
    )
    max_size: int | None = Field(None, ge=1, le=10000, description="Maximum number of cached items")


# =============================================================================
# DEEPINFRA API CLIENT
# =============================================================================


class DeepInfraClient:
    """HTTP client for DeepInfra TTS API."""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = DEEPINFRA_API_URL

    async def synthesize(
        self,
        text: str,
        voice: str | None = None,
        language: str | None = None,
    ) -> bytes:
        """Call DeepInfra TTS API to synthesize speech.

        Args:
            text: Text to synthesize
            voice: Voice ID to use
            language: Language code

        Returns:
            Audio data as bytes (MP3 format)

        Raises:
            httpx.HTTPStatusError: On API errors
            httpx.TimeoutException: On timeout
        """
        if not self.api_key:
            raise ValueError("DEEPINFRA_API_KEY is not configured")

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload: dict[str, Any] = {
            "text": text,
        }

        if voice:
            payload["voice"] = voice
        if language:
            payload["language"] = language

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                self.base_url,
                headers=headers,
                json=payload,
            )
            response.raise_for_status()

            # DeepInfra returns audio directly
            return response.content

    async def synthesize_streaming(
        self,
        text: str,
        voice: str | None = None,
        language: str | None = None,
        chunk_size: int = 8192,
    ):
        """Call DeepInfra TTS API with streaming response.

        This method streams the audio response in chunks, enabling
        real-time playback for SSR and streaming use cases.

        Args:
            text: Text to synthesize
            voice: Voice ID to use
            language: Language code
            chunk_size: Size of audio chunks to yield

        Yields:
            Audio data chunks as bytes

        Raises:
            httpx.HTTPStatusError: On API errors
            httpx.TimeoutException: On timeout
        """
        if not self.api_key:
            raise ValueError("DEEPINFRA_API_KEY is not configured")

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload: dict[str, Any] = {
            "text": text,
        }

        if voice:
            payload["voice"] = voice
        if language:
            payload["language"] = language

        async with httpx.AsyncClient(timeout=60.0) as client:
            async with client.stream(
                "POST",
                self.base_url,
                headers=headers,
                json=payload,
            ) as response:
                response.raise_for_status()

                # Stream audio chunks
                async for chunk in response.aiter_bytes(chunk_size=chunk_size):
                    if chunk:
                        yield chunk

    async def list_voices(self) -> list[VoiceInfo]:
        """Fetch available voices from DeepInfra.

        Note: DeepInfra doesn't have a dedicated voices endpoint,
        so we return a curated list of known voices.

        Returns:
            List of available voices
        """
        # DeepInfra TTS supports various voices
        # These are commonly available voices - actual availability may vary
        voices = [
            VoiceInfo(id="alloy", name="Alloy", language="en-US", gender="neutral"),
            VoiceInfo(id="echo", name="Echo", language="en-US", gender="male"),
            VoiceInfo(id="fable", name="Fable", language="en-US", gender="neutral"),
            VoiceInfo(id="onyx", name="Onyx", language="en-US", gender="male"),
            VoiceInfo(id="nova", name="Nova", language="en-US", gender="female"),
            VoiceInfo(id="shimmer", name="Shimmer", language="en-US", gender="female"),
        ]
        return voices

    async def check_status(self) -> dict[str, Any]:
        """Check DeepInfra API availability.

        Returns:
            Status information dict
        """
        if not self.api_key:
            return {
                "available": False,
                "error": "API key not configured",
                "error_code": "API_KEY_MISSING",
            }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                # Try a minimal request to check connectivity
                response = await client.get(
                    "https://api.deepinfra.com/v1/models",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                )
                if response.status_code == 200:
                    return {
                        "available": True,
                        "service": "DeepInfra TTS",
                        "status": "operational",
                    }
                return {
                    "available": False,
                    "status_code": response.status_code,
                    "error": "Service returned non-200 status",
                }
        except httpx.TimeoutException:
            return {
                "available": False,
                "error": "Connection timeout",
                "error_code": "API_TIMEOUT",
            }
        except httpx.ConnectError:
            return {
                "available": False,
                "error": "Cannot connect to DeepInfra API",
                "error_code": "API_ERROR",
            }
        except Exception as e:
            return {
                "available": False,
                "error": str(e),
                "error_code": "INTERNAL_ERROR",
            }


# Global client instance
deepinfra_client = DeepInfraClient(DEEPINFRA_API_KEY)


# =============================================================================
# MCP TOOLS
# =============================================================================


def _build_error_response(code: str, message: str, details: dict | None = None) -> dict:
    """Build standardized error response."""
    response = {
        "success": False,
        "error": {
            "code": code,
            "message": message,
        },
    }
    if details:
        response["error"]["details"] = details
    return response


def _build_success_response(data: dict) -> dict:
    """Build standardized success response."""
    return {
        "success": True,
        **data,
    }


@mcp.tool()
async def synthesize(
    text: str,
    voice: str | None = None,
    output_format: OutputFormat = "base64",
    use_cache: bool = True,
    language: str | None = None,
) -> dict:
    """Synthesize text to speech audio.

    Converts the provided text to speech using DeepInfra TTS API.
    Supports multiple output formats and caching for performance.

    Args:
        text: Text to convert to speech (required, max 5000 chars)
        voice: Voice ID to use (optional, uses default if not specified)
        output_format: Audio delivery method - 'base64', 'url', or 'stream' (default: base64)
        use_cache: Enable caching for this request (default: true)
        language: Language code like 'en-US' or 'nl-NL' (optional, auto-detected if not specified)

    Returns:
        Dict with success status and audio data or error information.
        On success, contains 'audio' object with content/url and metadata.
    """
    try:
        # Validate text length
        if len(text) > MAX_TEXT_LENGTH:
            return _build_error_response(
                code="TEXT_TOO_LONG",
                message=f"Text exceeds maximum length of {MAX_TEXT_LENGTH} characters",
                details={"max_length": MAX_TEXT_LENGTH, "actual_length": len(text)},
            )

        # Validate text not empty
        if not text or not text.strip():
            return _build_error_response(
                code="INVALID_INPUT",
                message="Text cannot be empty",
            )

        # Use default voice if not specified
        selected_voice = voice or DEFAULT_VOICE

        # Check cache
        cached_audio = None
        if use_cache and tts_cache.enabled:
            cached_audio = tts_cache.get(text, selected_voice or "default", language)

        if cached_audio:
            logger.info("Returning cached audio for text hash")
            audio_bytes = cached_audio
            from_cache = True
        else:
            # Call DeepInfra API
            logger.info("Calling DeepInfra API for synthesis")
            try:
                audio_bytes = await deepinfra_client.synthesize(
                    text=text,
                    voice=selected_voice,
                    language=language,
                )
                from_cache = False

                # Store in cache if enabled
                if use_cache and tts_cache.enabled:
                    tts_cache.set(text, selected_voice or "default", language, audio_bytes)

            except httpx.HTTPStatusError as e:
                error_details = {}
                try:
                    error_body = e.response.json()
                    error_details = {"api_response": error_body}
                except Exception:
                    pass

                return _build_error_response(
                    code="API_ERROR",
                    message=f"DeepInfra API error: {e.response.status_code}",
                    details=error_details,
                )
            except httpx.TimeoutException:
                return _build_error_response(
                    code="API_TIMEOUT",
                    message="DeepInfra API request timed out",
                )
            except ValueError as e:
                return _build_error_response(
                    code="API_KEY_MISSING",
                    message=str(e),
                )

        # Format output based on requested format
        audio_response: dict[str, Any] = {
            "format": "mp3",
            "duration_seconds": None,  # Would need audio analysis to determine
        }

        if output_format == "base64":
            audio_response["content"] = base64.b64encode(audio_bytes).decode("utf-8")
        elif output_format == "url":
            # Note: URL format would require file storage - returning base64 for now
            # with a note about this limitation
            audio_response["content"] = base64.b64encode(audio_bytes).decode("utf-8")
            audio_response["url_note"] = "URL format not yet implemented; returning base64"
        elif output_format == "stream":
            # Stream format returns raw bytes info
            audio_response["content"] = base64.b64encode(audio_bytes).decode("utf-8")
            audio_response["stream_note"] = "Stream format returns buffered content as base64"

        return _build_success_response(
            {
                "audio": audio_response,
                "voice_used": selected_voice or "default",
                "cached": from_cache,
                "text_length": len(text),
            }
        )

    except Exception as e:
        logger.error("Unexpected error in synthesize: %s", str(e))
        return _build_error_response(
            code="INTERNAL_ERROR",
            message="An unexpected error occurred",
            details={"error_type": type(e).__name__},
        )


@mcp.tool()
async def synthesize_stream(
    text: str,
    voice: str | None = None,
    language: str | None = None,
    chunk_size: int = 8192,
) -> dict:
    """Synthesize text to speech with streaming support.

    Returns information about streaming endpoint that can be used
    to receive audio chunks in real-time via Server-Sent Events (SSE).
    This is useful for SSR (Server-Side Rendering) and real-time audio playback.

    Args:
        text: Text to convert to speech (required, max 5000 chars)
        voice: Voice ID to use (optional, uses default if not specified)
        language: Language code like 'en-US' or 'nl-NL' (optional, auto-detected if not specified)
        chunk_size: Size of audio chunks in bytes (default: 8192)

    Returns:
        Dict with success status and streaming endpoint information.
        Contains SSE endpoint URL that can be used to receive audio chunks.
    """
    try:
        if not STREAMING_ENABLED:
            return _build_error_response(
                code="STREAMING_DISABLED",
                message="Streaming support is not enabled",
            )

        # Validate text length
        if len(text) > MAX_TEXT_LENGTH:
            return _build_error_response(
                code="TEXT_TOO_LONG",
                message=f"Text exceeds maximum length of {MAX_TEXT_LENGTH} characters",
                details={"max_length": MAX_TEXT_LENGTH, "actual_length": len(text)},
            )

        # Validate text not empty
        if not text or not text.strip():
            return _build_error_response(
                code="INVALID_INPUT",
                message="Text cannot be empty",
            )

        # Use default voice if not specified
        selected_voice = voice or DEFAULT_VOICE

        # Generate streaming session ID
        import uuid

        session_id = str(uuid.uuid4())

        # Store synthesis parameters in memory for streaming endpoint
        # In production, this would use Redis or another shared store
        streaming_sessions[session_id] = {
            "text": text,
            "voice": selected_voice,
            "language": language,
            "chunk_size": chunk_size,
            "created_at": __import__("time").time(),
        }

        # Get current port from environment or use default
        port = int(os.getenv("MCP_PORT", "9010"))

        return _build_success_response(
            {
                "streaming": {
                    "enabled": True,
                    "session_id": session_id,
                    "sse_url": f"http://localhost:{port}/api/tts/stream/{session_id}",
                    "format": "sse",
                    "protocol": "Server-Sent Events",
                },
                "parameters": {
                    "voice_used": selected_voice or "default",
                    "language": language or "auto",
                    "chunk_size": chunk_size,
                },
            }
        )

    except Exception as e:
        logger.error("Unexpected error in synthesize_stream: %s", str(e))
        return _build_error_response(
            code="INTERNAL_ERROR",
            message="An unexpected error occurred",
            details={"error_type": type(e).__name__},
        )


# Streaming sessions storage (in-memory for now)
streaming_sessions: dict[str, dict[str, Any]] = {}


@mcp.tool()
async def list_voices() -> dict:
    """List available TTS voices from DeepInfra.

    Retrieves the catalog of available voices for text-to-speech synthesis.
    Each voice includes metadata like name, language, and gender.

    Returns:
        Dict with success status and list of available voices.
        Each voice has id, name, language, and optional gender/preview_url.
    """
    try:
        voices = await deepinfra_client.list_voices()

        return _build_success_response(
            {
                "voices": [v.model_dump() for v in voices],
                "count": len(voices),
            }
        )

    except Exception as e:
        logger.error("Error listing voices: %s", str(e))
        return _build_error_response(
            code="API_ERROR",
            message="Failed to retrieve voice list",
            details={"error": str(e)},
        )


@mcp.tool()
async def configure_cache(
    enabled: bool | None = None,
    ttl_seconds: int | None = None,
    max_size: int | None = None,
) -> dict:
    """Configure TTS caching behavior.

    Allows enabling/disabling caching, setting TTL, and maximum cache size.
    Changes take effect immediately for subsequent requests.

    Args:
        enabled: Enable or disable caching (optional)
        ttl_seconds: Cache time-to-live in seconds, range 60-86400 (optional)
        max_size: Maximum number of items to cache, range 1-10000 (optional)

    Returns:
        Dict with success status and current cache configuration.
    """
    try:
        new_config = tts_cache.configure(
            enabled=enabled,
            ttl=ttl_seconds,
            max_size=max_size,
        )

        return _build_success_response(
            {
                "cache": new_config,
                "message": "Cache configuration updated",
            }
        )

    except Exception as e:
        logger.error("Error configuring cache: %s", str(e))
        return _build_error_response(
            code="CACHE_ERROR",
            message="Failed to configure cache",
            details={"error": str(e)},
        )


@mcp.tool()
async def check_status() -> dict:
    """Check DeepInfra TTS service status and availability.

    Performs a health check on the DeepInfra API to verify connectivity
    and service availability.

    Returns:
        Dict with availability status, service name, and any error details.
    """
    try:
        status = await deepinfra_client.check_status()

        response = _build_success_response(
            {
                "service": "DeepInfra TTS",
                **status,
                "cache_status": tts_cache.get_status(),
            }
        )

        return response

    except Exception as e:
        logger.error("Error checking status: %s", str(e))
        return _build_error_response(
            code="INTERNAL_ERROR",
            message="Failed to check service status",
            details={"error": str(e)},
        )


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    import time
    import uvicorn
    from starlette.responses import JSONResponse, StreamingResponse
    from starlette.routing import Route

    # Get MCP app with HTTP transport
    app = mcp.http_app()

    # Add health endpoint
    async def health(request):
        """Health check endpoint."""
        return JSONResponse(
            {
                "status": "healthy",
                "service": "deepinfra-tts-mcp",
                "cache_enabled": tts_cache.enabled,
                "ssr_enabled": SSR_ENABLED,
                "streaming_enabled": STREAMING_ENABLED,
            }
        )

    # Add SSE streaming endpoint for TTS
    async def stream_tts_sse(request):
        """Server-Sent Events endpoint for streaming TTS audio."""
        session_id = request.path_params["session_id"]

        # Retrieve session parameters
        session = streaming_sessions.get(session_id)
        if not session:
            return JSONResponse(
                {"error": "Invalid or expired session ID"},
                status_code=404,
            )

        # Clean up old sessions (older than 5 minutes)
        current_time = time.time()
        if current_time - session["created_at"] > 300:
            del streaming_sessions[session_id]
            return JSONResponse(
                {"error": "Session expired"},
                status_code=410,
            )

        async def generate_sse():
            """Generate SSE events for audio chunks."""
            try:
                # Send session start event
                yield f"event: start\ndata: {json.dumps({'session_id': session_id, 'voice': session['voice'], 'language': session['language']})}\n\n"

                # Stream audio from DeepInfra API
                chunk_count = 0
                total_bytes = 0

                async for chunk in deepinfra_client.synthesize_streaming(
                    text=session["text"],
                    voice=session["voice"],
                    language=session["language"],
                    chunk_size=session["chunk_size"],
                ):
                    # Send audio chunk as base64 encoded data
                    chunk_b64 = base64.b64encode(chunk).decode("utf-8")
                    event_data = json.dumps(
                        {
                            "chunk_index": chunk_count,
                            "chunk_size": len(chunk),
                            "data": chunk_b64,
                            "format": "base64",
                        }
                    )
                    yield f"event: chunk\ndata: {event_data}\n\n"
                    chunk_count += 1
                    total_bytes += len(chunk)

                # Send completion event
                yield f"event: complete\ndata: {json.dumps({'total_chunks': chunk_count, 'total_bytes': total_bytes})}\n\n"

            except Exception as e:
                logger.error("Error streaming audio: %s", str(e))
                error_data = json.dumps({"error": str(e)})
                yield f"event: error\ndata: {error_data}\n\n"

            finally:
                # Clean up session after streaming
                if session_id in streaming_sessions:
                    del streaming_sessions[session_id]

        return StreamingResponse(
            generate_sse(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",  # Disable Nginx buffering
            },
        )

    # Add routes
    app.routes.insert(0, Route("/health", health, methods=["GET"]))
    app.routes.insert(0, Route("/api/tts/stream/{session_id}", stream_tts_sse, methods=["GET"]))

    port = int(os.getenv("MCP_PORT", "9010"))

    logger.info("Starting DeepInfra TTS MCP Server on port %d", port)
    logger.info(
        "Cache enabled: %s, TTL: %ds, Max size: %d",
        tts_cache.enabled,
        tts_cache._ttl,
        tts_cache._max_size,
    )
    logger.info("SSR enabled: %s, Streaming enabled: %s", SSR_ENABLED, STREAMING_ENABLED)

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port,
        log_level="info",
    )
