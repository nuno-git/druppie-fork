"""LLM Integration Module v1.

Centralized LLM abstraction layer with multi-provider support.
"""

__version__ = "1.0.0"

from .module import LLMModule
from .tools import chat_completion, count_tokens, list_providers
from .providers import ProviderManager
from .config import Config
from .logging import get_logger

__all__ = [
    "LLMModule",
    "chat_completion",
    "count_tokens",
    "list_providers",
    "ProviderManager",
    "Config",
    "get_logger",
]
