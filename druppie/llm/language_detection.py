"""Language detection using LLM."""

import structlog
from druppie.core.config import get_fallback_language
from druppie.llm.service import get_llm_service

logger = structlog.get_logger()

# Language instruction templates for each supported language
LANGUAGE_INSTRUCTIONS = {
    "en": "LANGUAGE INSTRUCTION: The user is communicating in ENGLISH. You MUST respond in English.",
    "nl": "LANGUAGE INSTRUCTION: De gebruiker communiceert in NEDERLANDS. U MOET in het Nederlands antwoorden.",
    "es": "LANGUAGE INSTRUCTION: El usuario se comunica en ESPAÑOL. Debes responder en español.",
    "fr": "LANGUAGE INSTRUCTION: L'utilisateur communique en FRANÇAIS. Vous devez répondre en français.",
    "de": "LANGUAGE INSTRUCTION: Der Benutzer kommuniziert auf DEUTSCH. Sie müssen auf Deutsch antworten.",
    "pt": "LANGUAGE INSTRUCTION: O usuário se comunica em PORTUGUÊS. Você deve responder em português.",
    "it": "LANGUAGE INSTRUCTION: L'utente comunica in ITALIANO. Devi rispondere in italiano.",
    "ru": "LANGUAGE INSTRUCTION: Пользователь общается на РУССКОМ. Вы должны отвечать по-русски.",
    "ja": "LANGUAGE INSTRUCTION: ユーザーは日本語で通信しています。日本語で回答する必要があります。",
    "zh": "LANGUAGE INSTRUCTION: 用户使用中文交流。您必须用中文回答。",
    "ko": "LANGUAGE INSTRUCTION: 사용자는 한국어로 소통합니다. 한국어로 답변해야 합니다.",
}


async def detect_language(text: str, fallback_language: str | None = None) -> tuple[str, str, str]:
    """Detect the language of the given text using LLM.

    Args:
        text: Text to detect language from
        fallback_language: Fallback language code (defaults to configured fallback)

    Returns:
        Tuple of (language_code, language_name, instruction)
        Examples:
        - ("en", "English", "LANGUAGE INSTRUCTION: The user is communicating in ENGLISH...")
        - ("nl", "Dutch", "LANGUAGE INSTRUCTION: De gebruiker communiceert in NEDERLANDS...")
    """
    # Get fallback from config if not provided
    if fallback_language is None:
        fallback_language = get_fallback_language()

    if not text or len(text.strip()) < 2:
        lang_name = _get_language_name(fallback_language)
        instruction = LANGUAGE_INSTRUCTIONS.get(fallback_language, "")
        return (fallback_language, lang_name, instruction)

    # Simple prompt for language detection
    # Use straightforward examples to help the LLM distinguish similar languages
    prompt = f"""Detect the language of the following text. Respond ONLY with the two-letter ISO 639-1 language code.

Text: "{text[:400]}"

Common language markers:
- English: "make", "the", "for", "please", "yes", "no" -> en
- Dutch: "maak", "de", "voor", "alsjeblieft", "ja", "nee" -> nl
- Spanish: "hacer", "el", "por favor", "sí", "no" -> es
- French: "faire", "le", "s'il vous plaît", "oui", "non" -> fr

Respond with only the two-letter code (e.g., en, nl, es, fr, de, pt, it, ru, ja, zh, ko)."""

    try:
        llm_service = get_llm_service()
        llm = llm_service.get_llm()

        # Call LLM with higher token limit for reliable response
        # Even though we only need 2 chars, LLMs may need more tokens to process
        response = await llm.achat(
            messages=[{"role": "user", "content": prompt}],
            max_tokens=50,  # Increased from 10 for more reliable detection
        )

        # Extract language code from response
        # Handle empty or malformed responses
        logger.debug(
            "llm_response_received",
            content=response.content,
            raw_content=response.raw_content,
            content_length=len(response.content) if response.content else 0,
        )

        if not response.content:
            logger.warning("empty_llm_response", defaulting_to=fallback_language, raw=response.raw_content)
            lang_name = _get_language_name(fallback_language)
            instruction = LANGUAGE_INSTRUCTIONS.get(fallback_language, "")
            return (fallback_language, lang_name, instruction)

        content_parts = response.content.strip().lower().split()
        if not content_parts:
            logger.warning("empty_response_after_split", response_content=response.content, defaulting_to=fallback_language)
            lang_name = _get_language_name(fallback_language)
            instruction = LANGUAGE_INSTRUCTIONS.get(fallback_language, "")
            return (fallback_language, lang_name, instruction)

        lang_code = content_parts[0]

        # Validate it's a 2-letter code
        if len(lang_code) != 2 or not lang_code.isalpha():
            logger.warning("invalid_language_code_detected", detected=lang_code, defaulting_to=fallback_language)
            lang_code = fallback_language

        # Get language name and instruction
        lang_name = _get_language_name(lang_code)
        instruction = LANGUAGE_INSTRUCTIONS.get(lang_code, "")

        logger.info(
            "language_detected",
            language_code=lang_code,
            language_name=lang_name,
            has_instruction=bool(instruction),
        )

        return (lang_code, lang_name, instruction)

    except Exception as e:
        logger.error("language_detection_failed", error=str(e), defaulting_to=fallback_language)
        lang_name = _get_language_name(fallback_language)
        instruction = LANGUAGE_INSTRUCTIONS.get(fallback_language, "")
        return (fallback_language, lang_name, instruction)


def _get_language_name(lang_code: str) -> str:
    """Convert ISO language code to full name."""
    names = {
        "en": "English",
        "nl": "Dutch",
        "es": "Spanish",
        "fr": "French",
        "de": "German",
        "pt": "Portuguese",
        "it": "Italian",
        "ru": "Russian",
        "ja": "Japanese",
        "zh": "Chinese",
        "ko": "Korean",
    }
    return names.get(lang_code, "English")
