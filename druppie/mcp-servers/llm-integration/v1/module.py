"""Module initialization for LLM Integration Module.

Handles module lifecycle and initialization.
"""

from .config import get_config, reset_config
from .logging import configure_logging, get_logger
from .providers import ProviderManager

logger = get_logger()


class LLMModule:
    """LLM Integration Module lifecycle manager."""

    def __init__(self) -> None:
        """Initialize the module."""
        self.config = None
        self.provider_manager = None
        self._initialized = False

    def initialize(self) -> None:
        """Initialize the module.

        Loads configuration and sets up providers.
        """
        if self._initialized:
            return

        # Load configuration
        self.config = get_config()

        # Configure logging
        configure_logging(self.config.log_level)

        # Initialize provider manager
        self.provider_manager = ProviderManager(self.config)

        self._initialized = True

        logger.info(
            "LLM Integration Module initialized",
            version="1.0.0",
            provider_count=len(self.config.providers),
            log_level=self.config.log_level,
        )

    def shutdown(self) -> None:
        """Shutdown the module.

        Cleans up resources and resets state.
        """
        self._initialized = False
        self.config = None
        self.provider_manager = None

        # Reset global config for clean state
        reset_config()

        logger.info("LLM Integration Module shutdown")

    def is_initialized(self) -> bool:
        """Check if module is initialized.

        Returns:
            True if module is initialized.
        """
        return self._initialized

    def health_check(self) -> dict:
        """Perform health check.

        Returns:
            Health status dictionary.
        """
        if not self._initialized or self.provider_manager is None:
            return {
                "status": "unhealthy",
                "reason": "Module not initialized",
            }

        providers = self.provider_manager.list_providers()
        available_count = sum(1 for p in providers if p.get("available", False))

        return {
            "status": "healthy" if available_count > 0 else "degraded",
            "version": "1.0.0",
            "providers": {
                "total": len(providers),
                "available": available_count,
            },
        }


# Global module instance
_module: LLMModule | None = None


def get_module() -> LLMModule:
    """Get or create global module instance.

    Returns:
        LLMModule instance.
    """
    global _module
    if _module is None:
        _module = LLMModule()
    return _module


def initialize_module() -> LLMModule:
    """Initialize and return the module.

    Returns:
        Initialized LLMModule instance.
    """
    module = get_module()
    module.initialize()
    return module
