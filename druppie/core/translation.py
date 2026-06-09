"""Translation service — translates text between languages via DeepInfra.

Uses a dedicated lightweight LLM instance (Qwen/Qwen3-32B on DeepInfra) for
translations. Raises TranslationNotAvailableError on first use when
DEEPINFRA_API_KEY is not configured, so callers surface a clear error instead
of silently serving untranslated text.
"""

import os

import structlog

logger = structlog.get_logger()


class TranslationNotAvailableError(RuntimeError):
    """Raised when translation is requested but cannot work (e.g. missing API key)."""


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


class TranslationService:
    """Translates text between languages using Qwen/Qwen3-32B on DeepInfra."""

    def __init__(self):
        self._llm = None

    @property
    def llm(self):
        if self._llm is None:
            if not os.getenv("DEEPINFRA_API_KEY"):
                raise TranslationNotAvailableError(
                    "DEEPINFRA_API_KEY is not set. Translation requires a valid "
                    "DeepInfra API key. Set DEEPINFRA_API_KEY in your .env file "
                    "to enable translation for non-English sessions."
                )
            from druppie.llm.litellm_provider import ChatLiteLLM
            self._llm = ChatLiteLLM(
                provider="deepinfra",
                model="Qwen/Qwen3-32B",
                temperature=0.1,
                max_tokens=4096,
                timeout=15.0,
                max_retries=1,
            )
        return self._llm

    async def translate_to_english(self, text: str, source_language: str) -> str:
        if not source_language or source_language == "en":
            return text
        if len(text.strip()) < 5:
            return text

        lang_name = _language_name(source_language)
        return await self._translate(text, lang_name, "English")

    async def translate_from_english(self, text: str, target_language: str) -> str:
        if not target_language or target_language == "en":
            return text
        if len(text.strip()) < 5:
            return text

        lang_name = _language_name(target_language)
        return await self._translate(text, "English", lang_name)

    @staticmethod
    def _strip_thinking(text: str) -> str:
        """Remove <think>...</think> blocks from model output."""
        import re
        return re.sub(r"<think>.*?</think>\s*", "", text, flags=re.DOTALL).strip()

    async def _translate(self, text: str, from_lang: str, to_lang: str) -> str:
        try:
            response = await self.llm.achat(
                messages=[
                    {
                        "role": "system",
                        "content": (
                            f"/no_think\n"
                            f"Translate the following {from_lang} text to {to_lang}. "
                            "Output ONLY the translation. No explanations, no extra text. "
                            "Preserve all markdown formatting, code blocks, and special characters."
                        ),
                    },
                    {"role": "user", "content": text},
                ],
            )
            translated = self._strip_thinking(response.content)
            if not translated:
                logger.warning("translation_empty_response", from_lang=from_lang, to_lang=to_lang)
                return text
            return translated
        except TranslationNotAvailableError:
            raise
        except Exception as e:
            logger.warning("translation_failed", error=str(e), from_lang=from_lang, to_lang=to_lang)
            return text


_translation_service: TranslationService | None = None


def get_translation_service() -> TranslationService:
    global _translation_service
    if _translation_service is None:
        _translation_service = TranslationService()
    return _translation_service
