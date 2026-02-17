"""Processed human input with metadata.

Entry point for processing user text. Currently handles language detection;
extensible for future input parsing (e.g., intent hints, attachments).
"""


class HumanInput:
    """Processed human input with metadata."""

    def __init__(self, text: str, language_detector):
        self.text = text
        self.detected_language = language_detector.detect_language(text)
        # First 3 words + "..." for debug display
        words = text.split()[:3]
        self.preview = " ".join(words) + ("..." if len(text.split()) > 3 else "")

    def language_info(self) -> dict:
        """Return language detection info for the prompt builder.

        Always returns a dict (never None) so the prompt block can show status.
        """
        if self.detected_language:
            return {
                "detected_from": self.preview,
                "detected_language": self.detected_language,
                "detection_status": "detected",
            }
        else:
            return {
                "detected_from": self.preview,
                "detected_language": None,
                "detection_status": "failed",
            }
