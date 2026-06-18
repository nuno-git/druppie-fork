"""Translation service — translates text between languages via DeepInfra.

Uses Gemma 3 27B on DeepInfra for translations. Raises
TranslationNotAvailableError when DEEPINFRA_API_KEY is not configured,
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


class TranslationService:
    """Translates text between languages using Gemma 3 27B on DeepInfra."""

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
                model="google/gemma-3-27b-it",
                temperature=0.1,
                max_tokens=16384,
                timeout=120.0,
                max_retries=2,
            )
        return self._llm

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
