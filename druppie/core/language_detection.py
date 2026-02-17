"""Language detection service for Druppie.

Detects user language to enable agents to respond in the same language.
Supports Dutch (nl) and English (en) with Dutch as the fallback default.

Uses a hybrid approach:
1. Word-based heuristics for reliable detection of common words
2. langdetect library with probability checking for longer texts
3. Conservative fallback to preserve session language when uncertain
"""

from typing import Optional
import re

import structlog

logger = structlog.get_logger()


class LanguageDetector:
    """Detects language from text input.

    Supports Dutch (nl) and English (en) with intelligent fallback:
    - Returns None for very short text (< 25 chars) to preserve existing session language
    - Uses word-based heuristics for reliability
    - Falls back to Dutch only when truly uncertain
    """

    # Minimum text length for reliable detection
    MIN_TEXT_LENGTH = 5

    # Supported languages (ISO 639-1 codes)
    SUPPORTED_LANGUAGES = ["nl", "en"]

    # Default fallback language
    DEFAULT_LANGUAGE = "nl"

    # Common Dutch words (high confidence indicators)
    DUCH_KEYWORDS = {
        # Articles
        "de", "het", "een", "der", "des", "den",
        # Pronouns
        "ik", "jij", "hij", "zij", "wij", "jullie", "ze", "mijn", "jou", "zijn", "haar",
        # Verbs (common)
        "is", "zijn", "was", "waren", "heb", "heeft", "had", "hadden", "wil", "wilt", "wil",
        "maak", "maakt", "maken", "kan", "kun", "kunnen", "moet", "moeten", "zal", "zullen",
        # Prepositions
        "van", "tot", "met", "voor", "naar", "uit", "over", "onder", "boven", "bij",
        # Common words
        "niet", "geen", "wel", "al", "alle", "alleen", "ook", "maar", "of", "en", "om",
        "app", "applicatie", "website", "game", "spel", "weer", "weerwebsite",
        # Questions
        "wat", "hoe", "waar", "wanneer", "waarom", "wie",
    }

    # Common English words (high confidence indicators)
    ENGLISH_KEYWORDS = {
        # Articles
        "the", "a", "an",
        # Pronouns
        "i", "you", "he", "she", "we", "they", "my", "your", "his", "her",
        # Verbs (common)
        "is", "are", "was", "were", "have", "has", "had", "will", "would", "can",
        "make", "makes", "making", "build", "creates", "create", "want", "wants",
        # Prepositions
        "of", "to", "for", "with", "from", "about", "over", "under", "above", "at",
        # Common words
        "not", "no", "yes", "all", "only", "also", "but", "or", "and", "app",
        "application", "website", "game", "weather", "dashboard",
        # Questions
        "what", "how", "where", "when", "why", "who",
    }

    def __init__(self, confidence_threshold: float = 0.6):
        """Initialize language detector.

        Args:
            confidence_threshold: Minimum confidence (0.0-1.0) for langdetect.
                Default 0.6 means we need 60% confidence to accept the result.
        """
        self.confidence_threshold = confidence_threshold

    def detect_language(self, text: str) -> Optional[str]:
        """Detect language from text.

        Args:
            text: Input text to analyze

        Returns:
            ISO 639-1 language code (e.g., "nl", "en"), or None if:
            - Text is too short (< MIN_TEXT_LENGTH chars) - preserves session language
            - Detection is uncertain - preserves session language

        Note:
            Returns None for short/uncertain text intentionally - this allows the caller
            to preserve existing session language instead of falling back to Dutch.
        """
        if not text or not text.strip():
            return None

        text_clean = text.strip().lower()

        # Check minimum length
        if len(text_clean) < self.MIN_TEXT_LENGTH:
            logger.debug(
                "text_too_short_for_detection",
                length=len(text_clean),
                min_length=self.MIN_TEXT_LENGTH,
            )
            return None

        # Step 1: Try word-based heuristics (most reliable for short texts)
        heuristic_result = self._detect_by_keywords(text_clean)
        if heuristic_result:
            logger.info(
                "language_detected_by_heuristics",
                language=heuristic_result,
                text_length=len(text),
            )
            return heuristic_result

        # Step 2: Try langdetect with probability checking
        langdetect_result = self._detect_by_langdetect(text)
        if langdetect_result:
            logger.info(
                "language_detected",
                language=langdetect_result,
                text_length=len(text),
            )
            return langdetect_result

        # Step 3: Uncertain - preserve session language by returning None
        logger.info(
            "language_detection_uncertain",
            text_length=len(text),
            result="preserve_session_language",
        )
        return None

    def _detect_by_keywords(self, text: str) -> Optional[str]:
        """Detect language using word-based heuristics.

        Counts unique Dutch and English keywords in the text.
        Requires a significant difference (2:1 ratio) to be confident.

        Returns None if heuristics are inconclusive.
        """
        # Extract words (alphanumeric only)
        words = set(re.findall(r"\b[a-z]+\b", text))

        # Count keyword matches
        dutch_matches = sum(1 for w in words if w in self.DUCH_KEYWORDS)
        english_matches = sum(1 for w in words if w in self.ENGLISH_KEYWORDS)

        # Require 2:1 ratio for confidence
        if dutch_matches >= 2 and dutch_matches > english_matches * 2:
            return "nl"

        if english_matches >= 2 and english_matches > dutch_matches * 2:
            return "en"

        # Inconclusive
        return None

    def _detect_by_langdetect(self, text: str) -> Optional[str]:
        """Detect language using langdetect with probability checking.

        Only returns a result if:
        1. Detected language is supported (nl/en)
        2. Confidence level meets threshold

        Returns None if uncertain.
        """
        try:
            from langdetect import detect_langs, LangDetectException

            # Get language with probabilities
            langs = detect_langs(text)

            if not langs:
                return None

            # Check top result
            top_lang = langs[0]
            detected = top_lang.lang
            probability = top_lang.prob

            logger.debug(
                "langdetect_result",
                detected=detected,
                probability=probability,
                threshold=self.confidence_threshold,
            )

            # Check if detected language is supported AND confidence is high enough
            if detected in self.SUPPORTED_LANGUAGES and probability >= self.confidence_threshold:
                return detected

            # Low confidence or unsupported language
            logger.debug(
                "langdetect_rejected",
                detected=detected,
                probability=probability,
                reason="low_confidence_or_unsupported",
            )
            return None

        except ImportError:
            logger.warning("langdetect_not_installed")
            return None
        except LangDetectException as e:
            logger.debug("langdetect_exception", error=str(e))
            return None
        except Exception as e:
            logger.warning("langdetect_error", error=str(e))
            return None
