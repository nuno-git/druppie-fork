"""Pytest configuration for Druppie backend tests."""

import os
import sys

# Add backend to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest


@pytest.fixture(autouse=True)
def reset_env():
    """Reset environment variables after each test."""
    original_env = os.environ.copy()
    yield
    os.environ.clear()
    os.environ.update(original_env)


@pytest.fixture
def mock_ollama_response():
    """Create a mock Ollama response."""
    return {
        "choices": [
            {
                "message": {
                    "content": "Hello! I'm an AI assistant.",
                    "role": "assistant",
                }
            }
        ],
        "model": "qwen2.5:7b",
        "usage": {
            "prompt_tokens": 10,
            "completion_tokens": 8,
            "total_tokens": 18,
        },
    }


@pytest.fixture
def mock_zai_response():
    """Create a mock Z.AI response."""
    return {
        "choices": [
            {
                "message": {
                    "content": "Hello from Z.AI!",
                    "role": "assistant",
                }
            }
        ],
        "model": "GLM-4.7",
        "usage": {
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15,
        },
    }
