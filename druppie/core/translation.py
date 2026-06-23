"""Translation service — translates text between languages.

Uses a configurable LLM provider for translations. The provider/model
is resolved in this order:
1. Runtime override (set by admin via the Model Management UI)
2. TRANSLATION_PROVIDER / TRANSLATION_MODEL env vars
3. Legacy: DEEPINFRA_API_KEY with Gemma 3 27B
4. Any available provider from PROVIDER_CONFIGS

Raises TranslationNotAvailableError when no provider is available,
and TranslationError on translation failures, so callers can surface
clear errors instead of silently serving untranslated text.
"""

import os

import structlog

logger = structlog.get_logger()


class TranslationNotAvailableError(RuntimeError):
    """Raised when translation is requested but cannot work (e.g. missing API key)."""


class TranslationError(RuntimeError):
    """Raised when a translation call fails (timeout, API error, empty result)."""


def _language_name(code: str) -> str:
    """Resolve ISO 639-1 code to English language name via pycountry."""
    try:
        import pycountry
        lang = pycountry.languages.get(alpha_2=code)
        if lang:
            return lang.name
    except Exception:
        pass
    return code


def _has_api_key_for_provider(provider: str) -> bool:
    """Check whether the API key for a provider is configured."""
    from druppie.llm.litellm_provider import PROVIDER_CONFIGS
    config = PROVIDER_CONFIGS.get(provider)
    if not config:
        return False
    if config.get("api_key_optional"):
        return True
    return bool(os.getenv(config["api_key_env"]))


class TranslationService:
    """Translates text between languages using a configurable LLM provider."""

    def __init__(self):
        self._llm = None
        self._configured_provider: str | None = None
        self._configured_model: str | None = None

    def configure(self, provider: str | None, model: str | None):
        """Set the translation provider/model at runtime.

        Called by ModelManagementService when an admin sets or removes
        a translation override. Pass None/None to clear the override.
        """
        self._configured_provider = provider
        self._configured_model = model
        self._llm = None

    def get_current_config(self) -> tuple[str, str, str]:
        """Return (provider, model, source) for the current translation config."""
        return self._resolve_translation_config()

    @property
    def llm(self):
        if self._llm is None:
            provider, model, source = self._resolve_translation_config()
            logger.info(
                "translation_llm_initialized",
                provider=provider,
                model=model,
                source=source,
            )
            from druppie.llm.litellm_provider import ChatLiteLLM
            self._llm = ChatLiteLLM(
                provider=provider,
                model=model,
                temperature=0.1,
                max_tokens=16384,
                timeout=120.0,
                max_retries=2,
            )
        return self._llm

    def _resolve_translation_config(self) -> tuple[str, str, str]:
        """Resolve which provider+model to use for translation.

        Returns (provider, model, source) where source describes how it was resolved.
        """
        from druppie.llm.litellm_provider import PROVIDER_CONFIGS

        # 1. Runtime override (set via admin UI)
        if self._configured_provider and self._configured_model:
            if _has_api_key_for_provider(self._configured_provider):
                return (self._configured_provider, self._configured_model, "db_override")
            logger.warning(
                "translation_override_api_key_missing",
                provider=self._configured_provider,
            )
            raise TranslationNotAvailableError(
                f"Translation override uses provider '{self._configured_provider}' "
                f"but its API key is not configured. "
                f"Update the override in Model Management or configure the API key."
            )

        # 2. Environment variables
        env_provider = os.getenv("TRANSLATION_PROVIDER")
        env_model = os.getenv("TRANSLATION_MODEL")
        if env_provider and env_model:
            if _has_api_key_for_provider(env_provider):
                return (env_provider, env_model, "env")
            logger.warning(
                "translation_env_api_key_missing",
                provider=env_provider,
            )

        # 3. Legacy: DeepInfra with Gemma (backward compat)
        if os.getenv("DEEPINFRA_API_KEY"):
            return ("deepinfra", "google/gemma-3-27b-it", "legacy")

        # 4. Any available provider
        for name, config in PROVIDER_CONFIGS.items():
            if _has_api_key_for_provider(name):
                return (name, config["default_model"], "fallback")

        raise TranslationNotAvailableError(
            "No LLM provider with a valid API key is available for translation. "
            "Configure at least one provider API key in your .env file, "
            "or set TRANSLATION_PROVIDER and TRANSLATION_MODEL."
        )

    async def translate_to_english(self, text: str, source_language: str) -> str:
        if not source_language or source_language == "en":
            return text
        if len(text.strip()) < 5:
            return text

        lang_name = _language_name(source_language)
        try:
            result = await self._translate(text, lang_name, "English")
            if len(result) > len(text) * 3 + 50:
                logger.warning(
                    "translation_hallucination_detected",
                    input_len=len(text),
                    output_len=len(result),
                    input_preview=text[:60],
                )
                return text
            return result
        except TranslationError:
            logger.warning("translate_to_english_fallback", source_language=source_language)
            return text

    async def translate_from_english(self, text: str, target_language: str) -> str:
        if not target_language or target_language == "en":
            return text
        if len(text.strip()) < 5:
            return text

        lang_name = _language_name(target_language)
        return await self._translate(text, "English", lang_name)

    async def translate_label(self, text: str, target_language: str) -> str:
        """Translate a short label (e.g. a multiple-choice option).

        Uses a tighter prompt than translate_from_english to prevent
        the model from expanding a short phrase into an explanation.
        Falls back to the full translate method if the result looks untranslated.
        """
        if not target_language or target_language == "en":
            return text
        if len(text.strip()) < 3:
            return text

        lang_name = _language_name(target_language)
        try:
            response = await self.llm.achat(
                messages=[
                    {
                        "role": "system",
                        "content": (
                            f"Translate this short label from English to {lang_name}. "
                            "Output ONLY the translated label, nothing else."
                        ),
                    },
                    {"role": "user", "content": text},
                ],
            )
            translated = self._strip_thinking(response.content)
            if not translated:
                return text
            if self._looks_untranslated(text, translated):
                logger.warning(
                    "label_translation_looks_english_retrying",
                    original=text[:60],
                    result=translated[:60],
                )
                return await self._translate(text, "English", lang_name)
            return translated
        except (TranslationNotAvailableError, TranslationError):
            raise
        except Exception as e:
            raise TranslationError(
                f"Label translation English → {lang_name} failed: {e}"
            ) from e

    @staticmethod
    def _looks_untranslated(original: str, translated: str) -> bool:
        """Heuristic: detect if translated text is still English / unchanged."""
        if translated.strip().lower() == original.strip().lower():
            return True
        orig_words = set(original.lower().split())
        trans_words = set(translated.lower().split())
        if not orig_words:
            return False
        overlap = len(orig_words & trans_words) / len(orig_words)
        return overlap > 0.6

    @staticmethod
    def _strip_thinking(text: str) -> str:
        """Remove <think>...</think> blocks from model output, including unclosed tags."""
        import re
        text = re.sub(r"<think>.*?</think>\s*", "", text, flags=re.DOTALL)
        text = re.sub(r"<think>.*", "", text, flags=re.DOTALL)
        return text.strip()

    async def _translate(self, text: str, from_lang: str, to_lang: str) -> str:
        try:
            response = await self.llm.achat(
                messages=[
                    {
                        "role": "system",
                        "content": (
                            f"Translate the following {from_lang} text to {to_lang}. "
                            "Output ONLY the translation. No explanations, no extra text. "
                            "Preserve all markdown formatting exactly — including heading "
                            "prefixes (##, ###), bullet points, code blocks, and special characters."
                        ),
                    },
                    {"role": "user", "content": text},
                ],
            )
            translated = self._strip_thinking(response.content)
            if not translated:
                raise TranslationError(f"Empty response translating {from_lang} → {to_lang}")
            return translated
        except (TranslationNotAvailableError, TranslationError):
            raise
        except Exception as e:
            raise TranslationError(f"Translation {from_lang} → {to_lang} failed: {e}") from e


_translation_service: TranslationService | None = None


def get_translation_service() -> TranslationService:
    global _translation_service
    if _translation_service is None:
        _translation_service = TranslationService()
    return _translation_service
