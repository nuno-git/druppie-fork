"""Document Formatter Service.

Compiles native Typst source files into professionally formatted PDFs
using the Rijnland corporate identity template.
"""

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import structlog

from druppie.api.errors import ExternalServiceError

logger = structlog.get_logger()


class DocumentFormatterError(ExternalServiceError):
    """Raised when document formatting fails."""

    def __init__(self, message: str, original_error: str | None = None):
        super().__init__(service="typst", message=message, original_error=original_error)


class DocumentFormatterService:
    """Service that compiles .typ source files into styled PDFs via Typst."""

    TYPST_TIMEOUT = 60  # seconds

    def __init__(self, template_dir: Path | str | None = None):
        """Initialize with path to Typst templates.

        Args:
            template_dir: Directory containing rijnland.typ and assets/.
                Defaults to druppie/templates/documents/.
        """
        if template_dir is None:
            self.template_dir = Path(__file__).parent.parent / "templates" / "documents"
        else:
            self.template_dir = Path(template_dir)

        if not self.template_dir.exists():
            raise DocumentFormatterError(
                f"Template directory not found: {self.template_dir}"
            )

        # --root flag needs the project root (parent of druppie/); the double parent
        # traversal (templates/documents → templates → druppie → project_root) is
        # required because template_dir points to druppie/templates/documents.
        self.project_root = str(self.template_dir.parent.parent.parent)

        # Verify typst binary is available
        self.typst_bin = shutil.which("typst")
        if self.typst_bin is None:
            raise DocumentFormatterError(
                "Typst binary not found in PATH. "
                "Install it or set TYPST_FONT_PATHS if using a custom location."
            )

    def compile_typ(
        self,
        typ_path: Path,
        output_pdf_path: Path | None = None,
        extra_font_paths: list[Path] | None = None,
    ) -> bytes:
        """Compile a native .typ source file into a PDF.

        Args:
            typ_path: Path to the .typ file to compile.
            output_pdf_path: Optional path for the output PDF.
                If omitted, a temporary path is used.
            extra_font_paths: Optional additional directories to search for fonts.

        Returns:
            PDF bytes.

        Raises:
            DocumentFormatterError: If Typst compilation fails or PDF is missing.
        """
        typ_path = Path(typ_path)
        if not typ_path.exists():
            raise DocumentFormatterError(f"Typst source file not found: {typ_path}")

        if output_pdf_path is None:
            output_pdf_path = Path(tempfile.gettempdir()) / f"druppie-{typ_path.stem}.pdf"
        else:
            output_pdf_path = Path(output_pdf_path)

        font_paths: list[str] = [str(self.template_dir / "assets" / "fonts")]
        if extra_font_paths:
            font_paths.extend(str(p) for p in extra_font_paths)

        cmd = [
            self.typst_bin,
            "compile",
            "--root",
            self.project_root,
            "--font-path",
            ":".join(font_paths),
            str(typ_path),
            str(output_pdf_path),
        ]

        env = dict(os.environ)
        env["TYPST_FONT_PATHS"] = ":".join(font_paths)

        logger.info(
            "typst_compile_start",
            typ_path=str(typ_path),
            output=str(output_pdf_path),
        )

        try:
            result = subprocess.run(
                cmd,
                check=True,
                capture_output=True,
                text=True,
                cwd=str(typ_path.parent),
                env=env,
                timeout=self.TYPST_TIMEOUT,
            )
            logger.info(
                "typst_compile_success",
                typ_path=str(typ_path),
                stdout=result.stdout[:500] if result.stdout else None,
            )
        except subprocess.TimeoutExpired:
            logger.error("typst_compile_timed_out", timeout=self.TYPST_TIMEOUT)
            raise DocumentFormatterError(
                f"Typst compilation timed out after {self.TYPST_TIMEOUT}s"
            )
        except subprocess.CalledProcessError as e:
            stderr = e.stderr[:2000] if e.stderr else ""
            logger.error(
                "typst_compile_failed",
                typ_path=str(typ_path),
                stderr=stderr,
                returncode=e.returncode,
            )
            raise DocumentFormatterError(
                f"Typst compilation failed:\n{stderr}"
            ) from e

        if not output_pdf_path.exists():
            raise DocumentFormatterError("PDF output was not created")

        pdf_bytes = output_pdf_path.read_bytes()
        logger.info(
            "pdf_generated",
            typ_path=str(typ_path),
            pdf_size=len(pdf_bytes),
        )
        return pdf_bytes

    def verify_typ(self, typ_path: Path) -> tuple[bool, str | None]:
        """Run a syntax check on a .typ file without producing PDF output.

        Args:
            typ_path: Path to the .typ file to validate.

        Returns:
            (is_valid, error_message) tuple. is_valid is True if syntax is clean.
        """
        typ_path = Path(typ_path)
        if not typ_path.exists():
            return False, f"Typst source file not found: {typ_path}"

        font_paths = [str(self.template_dir / "assets" / "fonts")]
        cmd = [
            self.typst_bin,
            "compile",
            "--root",
            self.project_root,
            "--font-path",
            ":".join(font_paths),
            "--format",
            "pdf",
            "--diagnostic-format",
            "short",
            str(typ_path),
            "/dev/null" if os.name != "nt" else "nul",
        ]

        env = dict(os.environ)
        env["TYPST_FONT_PATHS"] = ":".join(font_paths)

        logger.info("typst_verify_start", typ_path=str(typ_path))

        try:
            result = subprocess.run(
                cmd,
                check=False,
                capture_output=True,
                text=True,
                cwd=str(typ_path.parent),
                env=env,
                timeout=self.TYPST_TIMEOUT,
            )
        except subprocess.TimeoutExpired:
            logger.error("typst_verify_timed_out", timeout=self.TYPST_TIMEOUT)
            return False, f"Typst syntax check timed out after {self.TYPST_TIMEOUT}s"

        if result.returncode == 0:
            logger.info("typst_verify_success", typ_path=str(typ_path))
            return True, None
        else:
            stderr = result.stderr[:2000] if result.stderr else ""
            logger.warning(
                "typst_verify_failed",
                typ_path=str(typ_path),
                stderr=stderr,
                returncode=result.returncode,
            )
            return False, stderr
