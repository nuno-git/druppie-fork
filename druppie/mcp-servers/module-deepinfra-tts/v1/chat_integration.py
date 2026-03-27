"""Chat Integration Module for DeepInfra TTS.

Provides integration between Druppie's core chat system and TTS capabilities.
Enables voice sessions for chat conversations with real-time audio synthesis.

This module provides:
- Chat message to speech conversion
- Voice session management
- Per-session voice configuration
- Integration hooks for the chat system
"""

import base64
import json
import logging
import os
from typing import Any, AsyncGenerator, Literal

import httpx

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("deepinfra-tts-chat-integration")

# Configuration from environment
TTS_SERVICE_URL = os.getenv("DEEPINFRA_TTS_SERVICE_URL", "http://localhost:9010")
DEFAULT_VOICE_FOR_CHAT = os.getenv("DEEPINFRA_TTS_DEFAULT_VOICE_FOR_CHAT", "nova")
CHAT_INTEGRATION = os.getenv("DEEPINFRA_TTS_CHAT_INTEGRATION", "true").lower() == "true"


# Voice session state
class VoiceSession:
    """Represents a voice session for a chat conversation."""

    def __init__(
        self,
        session_id: str,
        voice: str | None = None,
        language: str | None = None,
        enabled: bool = True,
    ):
        self.session_id = session_id
        self.voice = voice or DEFAULT_VOICE_FOR_CHAT
        self.language = language  # Auto-detected if None
        self.enabled = enabled
        self.message_count = 0
        self.total_audio_bytes = 0

    def to_dict(self) -> dict[str, Any]:
        """Convert session to dictionary representation."""
        return {
            "session_id": self.session_id,
            "voice": self.voice,
            "language": self.language,
            "enabled": self.enabled,
            "message_count": self.message_count,
            "total_audio_bytes": self.total_audio_bytes,
        }


# Active voice sessions storage (in-memory - use Redis in production)
active_sessions: dict[str, VoiceSession] = {}


class ChatIntegration:
    """Integration handler for chat and TTS services."""

    def __init__(self, tts_service_url: str = TTS_SERVICE_URL):
        self.tts_service_url = tts_service_url
        self.http_client = httpx.AsyncClient(timeout=60.0)

    async def convert_message_to_speech(
        self,
        session_id: str,
        text: str,
        voice: str | None = None,
        language: str | None = None,
        output_format: Literal["base64", "url", "stream"] = "base64",
    ) -> dict[str, Any]:
        """Convert a chat message to speech audio.

        Args:
            session_id: Chat session identifier
            text: Text to synthesize
            voice: Voice ID (uses session default if not specified)
            language: Language code (uses session default if not specified)
            output_format: Audio delivery method

        Returns:
            Dict with audio data and metadata
        """
        if not CHAT_INTEGRATION:
            return {
                "success": False,
                "error": {
                    "code": "CHAT_INTEGRATION_DISABLED",
                    "message": "Chat integration is not enabled",
                },
            }

        # Get or create voice session
        session = active_sessions.get(session_id)
        if not session:
            session = VoiceSession(
                session_id=session_id,
                voice=voice or DEFAULT_VOICE_FOR_CHAT,
                language=language,
            )
            active_sessions[session_id] = session
            logger.info("Created new voice session: %s", session_id)

        # Use session defaults if not specified
        selected_voice = voice or session.voice
        selected_language = language or session.language

        try:
            # Call TTS service synthesize endpoint
            response = await self.http_client.post(
                f"{self.tts_service_url}/tools/synthesize",
                json={
                    "text": text,
                    "voice": selected_voice,
                    "output_format": output_format,
                    "use_cache": True,  # Enable caching for chat
                    "language": selected_language,
                },
            )
            response.raise_for_status()
            result = response.json()

            if result.get("success"):
                # Update session stats
                session.message_count += 1
                audio_data = result.get("audio", {})
                if "content" in audio_data:
                    # Estimate bytes from base64
                    try:
                        session.total_audio_bytes += len(base64.b64decode(audio_data["content"]))
                    except Exception:
                        pass

                # Add session context to response
                result["session"] = {
                    "id": session_id,
                    "message_index": session.message_count,
                    "voice_used": selected_voice,
                }

                logger.info("Converted message to speech for session %s", session_id)
                return result
            else:
                logger.error("TTS synthesis failed: %s", result.get("error"))
                return result

        except httpx.HTTPStatusError as e:
            logger.error("HTTP error calling TTS service: %s", e)
            return {
                "success": False,
                "error": {
                    "code": "TTS_SERVICE_ERROR",
                    "message": f"TTS service returned error: {e.response.status_code}",
                },
            }
        except Exception as e:
            logger.error("Unexpected error converting message to speech: %s", e)
            return {
                "success": False,
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": f"Unexpected error: {str(e)}",
                },
            }

    async def stream_message_speech(
        self,
        session_id: str,
        text: str,
        voice: str | None = None,
        language: str | None = None,
        chunk_size: int = 8192,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Stream audio chunks for a chat message.

        This generator yields audio chunks as they're received from the TTS service,
        enabling real-time playback during chat conversations.

        Args:
            session_id: Chat session identifier
            text: Text to synthesize
            voice: Voice ID (uses session default if not specified)
            language: Language code (uses session default if not specified)
            chunk_size: Size of audio chunks in bytes

        Yields:
            Dicts containing event type and audio data chunks
        """
        if not CHAT_INTEGRATION:
            yield {
                "event": "error",
                "data": {"message": "Chat integration is not enabled"},
            }
            return

        # Get or create voice session
        session = active_sessions.get(session_id)
        if not session:
            session = VoiceSession(
                session_id=session_id,
                voice=voice or DEFAULT_VOICE_FOR_CHAT,
                language=language,
            )
            active_sessions[session_id] = session

        # Use session defaults if not specified
        selected_voice = voice or session.voice
        selected_language = language or session.language

        try:
            # First request streaming session
            response = await self.http_client.post(
                f"{self.tts_service_url}/tools/synthesize_stream",
                json={
                    "text": text,
                    "voice": selected_voice,
                    "language": selected_language,
                    "chunk_size": chunk_size,
                },
            )
            response.raise_for_status()
            result = response.json()

            if not result.get("success"):
                yield {
                    "event": "error",
                    "data": result.get("error"),
                }
                return

            streaming_info = result.get("streaming", {})
            sse_url = streaming_info.get("sse_url")

            if not sse_url:
                yield {
                    "event": "error",
                    "data": {"message": "No SSE URL returned"},
                }
                return

            # Connect to SSE endpoint and stream events
            async with self.http_client.stream("GET", sse_url) as sse_response:
                sse_response.raise_for_status()

                event_type = "message"  # Default event type
                async for line in sse_response.aiter_lines():
                    if line.startswith("event: "):
                        event_type = line[7:]
                    elif line.startswith("data: "):
                        data = line[6:]
                        if data:
                            try:
                                parsed_data = json.loads(data)
                                yield {
                                    "event": event_type,
                                    "data": parsed_data,
                                }
                            except json.JSONDecodeError:
                                # Send raw data if JSON parsing fails
                                yield {
                                    "event": event_type,
                                    "raw_data": data,
                                }

            # Update session stats
            session.message_count += 1
            logger.info("Streamed message speech for session %s", session_id)

        except Exception as e:
            logger.error("Error streaming message speech: %s", e)
            yield {
                "event": "error",
                "data": {"message": str(e)},
            }

    async def get_session(self, session_id: str) -> VoiceSession | None:
        """Get an existing voice session.

        Args:
            session_id: Session identifier

        Returns:
            VoiceSession if found, None otherwise
        """
        return active_sessions.get(session_id)

    async def create_session(
        self,
        session_id: str,
        voice: str | None = None,
        language: str | None = None,
    ) -> VoiceSession:
        """Create a new voice session.

        Args:
            session_id: Session identifier
            voice: Default voice for this session
            language: Default language for this session

        Returns:
            Created VoiceSession
        """
        session = VoiceSession(
            session_id=session_id,
            voice=voice or DEFAULT_VOICE_FOR_CHAT,
            language=language,
        )
        active_sessions[session_id] = session
        logger.info("Created voice session %s with voice %s", session_id, session.voice)
        return session

    async def update_session(
        self,
        session_id: str,
        voice: str | None = None,
        language: str | None = None,
        enabled: bool | None = None,
    ) -> VoiceSession | None:
        """Update an existing voice session.

        Args:
            session_id: Session identifier
            voice: New voice to use
            language: New language to use
            enabled: Enable/disable voice for this session

        Returns:
            Updated VoiceSession if found, None otherwise
        """
        session = active_sessions.get(session_id)
        if not session:
            return None

        if voice is not None:
            session.voice = voice
        if language is not None:
            session.language = language
        if enabled is not None:
            session.enabled = enabled

        logger.info("Updated voice session %s", session_id)
        return session

    async def delete_session(self, session_id: str) -> bool:
        """Delete a voice session.

        Args:
            session_id: Session identifier

        Returns:
            True if session was deleted, False if not found
        """
        if session_id in active_sessions:
            del active_sessions[session_id]
            logger.info("Deleted voice session %s", session_id)
            return True
        return False

    async def list_sessions(self) -> list[dict[str, Any]]:
        """List all active voice sessions.

        Returns:
            List of session dictionaries
        """
        return [session.to_dict() for session in active_sessions.values()]

    async def cleanup_old_sessions(self, max_age_seconds: int = 3600) -> int:
        """Remove old sessions to prevent memory leaks.

        Args:
            max_age_seconds: Maximum age of sessions in seconds

        Returns:
            Number of sessions removed
        """
        import time

        current_time = time.time()
        to_remove = [
            sid
            for sid, sess in active_sessions.items()
            if current_time - sess.message_count * 10 > max_age_seconds
        ]  # Approximate age based on message count

        for sid in to_remove:
            del active_sessions[sid]

        if to_remove:
            logger.info("Cleaned up %d old sessions", len(to_remove))

        return len(to_remove)


# Global chat integration instance
chat_integration = ChatIntegration()


# =============================================================================
# INTEGRATION HOOKS
# =============================================================================


async def on_chat_message(session_id: str, text: str, **kwargs) -> dict[str, Any]:
    """Hook called when a chat message is generated.

    This can be integrated into the chat system to automatically
    generate speech for messages.

    Args:
        session_id: Chat session ID
        text: Message text
        **kwargs: Additional parameters (voice, language, etc.)

    Returns:
        Audio generation result
    """
    result = await chat_integration.convert_message_to_speech(
        session_id=session_id,
        text=text,
        voice=kwargs.get("voice"),
        language=kwargs.get("language"),
        output_format=kwargs.get("output_format", "base64"),
    )
    return result


async def setup_voice_session(
    session_id: str, user_preferences: dict[str, Any] | None = None
) -> VoiceSession:
    """Setup a voice session with user preferences.

    Args:
        session_id: Chat session ID
        user_preferences: User voice preferences

    Returns:
        Created voice session
    """
    if user_preferences:
        return await chat_integration.create_session(
            session_id=session_id,
            voice=user_preferences.get("preferred_voice"),
            language=user_preferences.get("preferred_language"),
        )
    else:
        return await chat_integration.create_session(session_id=session_id)


# =============================================================================
# MAIN FOR TESTING
# =============================================================================

if __name__ == "__main__":
    import asyncio

    async def test_integration():
        """Test the chat integration."""
        print("Testing Chat Integration...")

        # Create a test session
        session = await chat_integration.create_session(
            session_id="test-session-1",
            voice="nova",
            language="en-US",
        )
        print(f"Created session: {session.to_dict()}")

        # Convert a message
        result = await chat_integration.convert_message_to_speech(
            session_id="test-session-1",
            text="Hello! This is a test message for TTS integration.",
        )
        print(f"Synthesis result: {result}")

        # List all sessions
        sessions = await chat_integration.list_sessions()
        print(f"Active sessions: {len(sessions)}")

        # Cleanup
        await chat_integration.delete_session("test-session-1")
        print("Test completed!")

    asyncio.run(test_integration())
