"""Tests for MCP tools."""

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from v1.tools import chat_completion, count_tokens, list_providers


class TestChatCompletion(unittest.IsolatedAsyncioTestCase):
    """Test chat completion tool."""

    async def test_chat_completion_validation_error(self):
        """Test chat completion with invalid input."""
        # Missing required 'role' field
        result = await chat_completion(
            messages=[{"content": "Hello"}],  # Missing 'role'
        )
        self.assertFalse(result["success"])
        self.assertIn("error", result)

    async def test_chat_completion_empty_messages(self):
        """Test chat completion with empty messages."""
        result = await chat_completion(messages=[])
        self.assertFalse(result["success"])


class TestCountTokens(unittest.IsolatedAsyncioTestCase):
    """Test count tokens tool."""

    async def test_count_tokens_success(self):
        """Test successful token counting."""
        result = await count_tokens(
            text="Hello, world!",
            model="gpt-3.5-turbo",
        )
        self.assertTrue(result["success"])
        self.assertIn("token_count", result)
        self.assertIn("model", result)
        self.assertGreater(result["token_count"], 0)

    async def test_count_tokens_default_model(self):
        """Test token counting with default model."""
        result = await count_tokens(text="Hello, world!")
        self.assertTrue(result["success"])
        self.assertEqual(result["model"], "gpt-3.5-turbo")


class TestListProviders(unittest.IsolatedAsyncioTestCase):
    """Test list providers tool."""

    async def test_list_providers_success(self):
        """Test successful provider listing."""
        result = await list_providers()
        self.assertTrue(result["success"])
        self.assertIn("providers", result)
        self.assertIsInstance(result["providers"], list)


if __name__ == "__main__":
    unittest.main()
