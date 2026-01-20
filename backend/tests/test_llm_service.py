"""Tests for the LLM Service."""

import os
import pytest
from unittest.mock import patch, MagicMock
import json


class TestChatOllama:
    """Tests for the Ollama LLM client."""

    def test_ollama_init_default_values(self):
        """Test Ollama client initializes with default values."""
        from druppie.llm_service import ChatOllama

        client = ChatOllama()
        assert client.model == "qwen2.5:7b"
        assert client.base_url == "http://localhost:11434"
        assert client.temperature == 0.7
        assert client.timeout == 300.0

    def test_ollama_init_custom_values(self):
        """Test Ollama client initializes with custom values."""
        from druppie.llm_service import ChatOllama

        client = ChatOllama(
            model="llama2",
            base_url="http://custom:11434",
            temperature=0.5,
            timeout=60.0,
        )
        assert client.model == "llama2"
        assert client.base_url == "http://custom:11434"
        assert client.temperature == 0.5
        assert client.timeout == 60.0

    def test_ollama_init_from_env(self):
        """Test Ollama client reads from environment variables when params are None."""
        from druppie.llm_service import ChatOllama

        with patch.dict(os.environ, {
            "OLLAMA_MODEL": "codellama",
            "OLLAMA_HOST": "http://env-host:11434",
        }):
            # Pass None explicitly to use env vars
            client = ChatOllama(model=None, base_url=None)
            assert client.model == "codellama"
            assert client.base_url == "http://env-host:11434"

    def test_ollama_call_history_tracking(self):
        """Test that Ollama tracks call history."""
        from druppie.llm_service import ChatOllama

        client = ChatOllama()
        assert len(client.get_call_history()) == 0

        # Mock a successful call
        with patch("httpx.Client") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "choices": [{"message": {"content": "Hello!"}}],
                "usage": {"total_tokens": 10},
            }
            mock_client.return_value.__enter__.return_value.post.return_value = mock_response

            result = client.chat([{"role": "user", "content": "Hi"}], call_name="test_call")

            assert result == "Hello!"
            history = client.get_call_history()
            assert len(history) == 1
            assert history[0]["name"] == "test_call"
            assert history[0]["status"] == "success"
            assert history[0]["provider"] == "ollama"

    def test_ollama_clean_response(self):
        """Test that Ollama cleans response text properly."""
        from druppie.llm_service import ChatOllama

        client = ChatOllama()

        # Test removing <think> blocks
        text = "Before <think>some reasoning</think> After"
        assert client._clean_response(text) == "Before  After"

        # Test removing markdown code fences
        text = '```json\n{"key": "value"}\n```'
        assert client._clean_response(text) == '{"key": "value"}'

        # Test combined
        text = '<think>reasoning</think>\n```json\n{"result": "ok"}\n```'
        assert client._clean_response(text) == '{"result": "ok"}'


class TestChatZAI:
    """Tests for the Z.AI LLM client."""

    def test_zai_init_default_values(self):
        """Test Z.AI client initializes with default values."""
        from druppie.llm_service import ChatZAI

        client = ChatZAI()
        assert client.model == "GLM-4.7"
        assert "api.z.ai" in client.base_url
        assert client.temperature == 0.7

    def test_zai_init_with_api_key(self):
        """Test Z.AI client initializes with API key."""
        from druppie.llm_service import ChatZAI

        client = ChatZAI(api_key="test-key")
        assert client.api_key == "test-key"

    def test_zai_improved_error_message_on_401(self):
        """Test that Z.AI provides helpful error on 401."""
        from druppie.llm_service import ChatZAI

        client = ChatZAI()

        with patch("httpx.Client") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 401
            mock_response.text = '{"error": "unauthorized"}'
            mock_client.return_value.__enter__.return_value.post.return_value = mock_response

            with pytest.raises(ValueError) as exc_info:
                client.chat([{"role": "user", "content": "Hi"}])

            error_msg = str(exc_info.value)
            assert "API key is missing or invalid" in error_msg
            assert "ZAI_API_KEY" in error_msg
            assert "Ollama" in error_msg


class TestLLMService:
    """Tests for the LLM Service wrapper."""

    def test_service_auto_selects_ollama_without_key(self):
        """Test that service selects Ollama when no Z.AI key is set."""
        from druppie.llm_service import LLMService

        with patch.dict(os.environ, {"LLM_PROVIDER": "auto", "ZAI_API_KEY": ""}, clear=False):
            service = LLMService()
            provider = service.get_provider()
            assert provider == "ollama"

    def test_service_selects_zai_with_key(self):
        """Test that service selects Z.AI when key is set."""
        from druppie.llm_service import LLMService

        with patch.dict(os.environ, {"LLM_PROVIDER": "auto", "ZAI_API_KEY": "test-key"}, clear=False):
            service = LLMService()
            provider = service.get_provider()
            assert provider == "zai"

    def test_service_respects_explicit_provider_ollama(self):
        """Test that service respects explicit ollama provider setting."""
        from druppie.llm_service import LLMService

        with patch.dict(os.environ, {"LLM_PROVIDER": "ollama", "ZAI_API_KEY": "test-key"}, clear=False):
            service = LLMService()
            provider = service.get_provider()
            assert provider == "ollama"

    def test_service_parse_json_response(self):
        """Test JSON parsing from LLM responses."""
        from druppie.llm_service import LLMService

        service = LLMService()

        # Valid JSON
        result = service.parse_json_response('{"action": "create"}')
        assert result == {"action": "create"}

        # JSON with surrounding text
        result = service.parse_json_response('Here is the result: {"status": "ok"} done')
        assert result == {"status": "ok"}

        # Invalid JSON
        result = service.parse_json_response('not json at all')
        assert result == {}


class TestCleanResponse:
    """Tests for response cleaning functionality."""

    def test_removes_think_blocks(self):
        """Test removal of <think> blocks."""
        from druppie.llm_service import ChatOllama

        client = ChatOllama()
        text = "<think>Let me think about this...</think>The answer is 42."
        result = client._clean_response(text)
        assert "<think>" not in result
        assert "</think>" not in result
        assert "The answer is 42." in result

    def test_removes_multiple_think_blocks(self):
        """Test removal of multiple <think> blocks."""
        from druppie.llm_service import ChatOllama

        client = ChatOllama()
        text = "<think>First thought</think>Part 1<think>Second thought</think>Part 2"
        result = client._clean_response(text)
        assert "<think>" not in result
        assert "Part 1" in result
        assert "Part 2" in result

    def test_removes_json_code_fence(self):
        """Test removal of JSON code fences."""
        from druppie.llm_service import ChatOllama

        client = ChatOllama()
        text = '```json\n{"key": "value"}\n```'
        result = client._clean_response(text)
        assert "```" not in result
        assert '{"key": "value"}' in result

    def test_removes_generic_code_fence(self):
        """Test removal of generic code fences."""
        from druppie.llm_service import ChatOllama

        client = ChatOllama()
        text = "```\nsome code\n```"
        result = client._clean_response(text)
        assert "```" not in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
