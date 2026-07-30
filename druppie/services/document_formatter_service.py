"""Document Formatter Service.

Compiles native Typst source files into professionally formatted PDFs.
The corporate identity is chosen by the .typ source itself, which imports
one of the house-style templates in druppie/templates/documents/.

Also provides markdown -> Typst conversion via markdown_to_typst() so that
agents can write standard markdown and the platform handles the branded
PDF pipeline through wrap_with_rijnland_template().
"""

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import structlog

from druppie.api.errors import ExternalServiceError

logger = structlog.get_logger()


# ---------------------------------------------------------------------------
# Markdown -> Typst conversion
# ---------------------------------------------------------------------------

_SENTINEL = "￾"


def _escape_typst(text: str) -> str:
    """Escape characters that have special meaning in Typst markup."""
    text = text.replace("\\", "\\\\")
    text = text.replace("#", "\\#")
    text = text.replace("@", "\\@")
    text = text.replace("$", "\\$")
    text = text.replace("<", "\\<")
    text = text.replace(">", "\\>")
    return text


def markdown_to_typst(content: str) -> str:
    """Convert markdown to native Typst syntax.

    Handles headings, bold, italic, tables, code blocks, mermaid diagrams
    (rendered via the mmdr Typst package), archimate SVG references,
    links, images, blockquotes, and horizontal rules.
    """
    has_mermaid = "```mermaid" in content
    lines = content.split("\n")
    result: list[str] = []
    in_code_block = False
    code_lang = ""
    code_lines: list[str] = []
    table_rows: list[list[str]] = []
    in_table = False

    if has_mermaid:
        result.append('#import "@preview/mmdr:0.2.2": mermaid')
        result.append("")

    def _flush_table() -> None:
        nonlocal table_rows, in_table
        if not table_rows:
            in_table = False
            return

        n_cols = len(table_rows[0])
        col_spec = ", ".join(["1fr"] * n_cols)

        result.append("#table(")
        result.append(f"  columns: ({col_spec}),")

        header_cells = ", ".join(f"[*{_convert_inline(c.strip())}*]" for c in table_rows[0])
        result.append(f"  table.header({header_cells}),")

        for row in table_rows[1:]:
            while len(row) < n_cols:
                row.append("")
            cells = ", ".join(f"[{_convert_inline(c.strip())}]" for c in row[:n_cols])
            result.append(f"  {cells},")

        result.append(")")
        result.append("")
        table_rows = []
        in_table = False

    def _convert_inline(text: str) -> str:
        # Escape Typst-special chars FIRST so they don't trigger scripting
        text = _escape_typst(text)

        # Stash bold(+italic) spans so the italic pass can't clobber them
        bolds: list[str] = []

        def _stash_bi(m: re.Match) -> str:
            bolds.append(f"*_{m.group(1)}_*")
            return f"{_SENTINEL}{len(bolds) - 1}{_SENTINEL}"

        def _stash_b(m: re.Match) -> str:
            bolds.append(f"*{m.group(1)}*")
            return f"{_SENTINEL}{len(bolds) - 1}{_SENTINEL}"

        text = re.sub(r"\*\*\*(.+?)\*\*\*", _stash_bi, text)
        text = re.sub(r"\*\*(.+?)\*\*", _stash_b, text)
        text = re.sub(r"(?<!\*)\*([^*\n]+?)\*(?!\*)", r"_\1_", text)

        for i, val in enumerate(bolds):
            text = text.replace(f"{_SENTINEL}{i}{_SENTINEL}", val)

        # Images/links: produce real Typst commands (unescaped #)
        text = re.sub(
            r"!\[([^\]]*)\]\(([^)]+)\)",
            lambda m: f'#image("{m.group(2)}")',
            text,
        )
        text = re.sub(
            r"\[([^\]]+)\]\(([^)]+)\)",
            lambda m: f'#link("{m.group(2)}")[{m.group(1)}]',
            text,
        )
        return text

    for line in lines:
        stripped = line.strip()

        # --- code fences ---
        if stripped.startswith("```"):
            if in_code_block:
                if code_lang == "mermaid":
                    mermaid_src = "\n".join(code_lines)
                    mermaid_src = mermaid_src.replace("\\", "\\\\")
                    mermaid_src = mermaid_src.replace('"', '\\"')
                    result.append(f'#align(center)[#mermaid("{mermaid_src}")]')
                    result.append("")
                elif code_lang == "archimate":
                    view_id = ""
                    for cl in code_lines:
                        m = re.search(r"view-id=(\S+)", cl)
                        if m:
                            view_id = m.group(1)
                            break
                    if view_id:
                        svg_name = re.sub(r"[^a-zA-Z0-9_-]", "-", view_id)
                        result.append(f'#image("docs/diagrams/{svg_name}.svg")')
                    else:
                        result.append(
                            "#block(fill: luma(245), inset: 10pt, " "radius: 4pt, width: 100%)["
                        )
                        result.append("  _ArchiMate diagram_")
                        result.append("]")
                else:
                    result.append(f"```{code_lang}")
                    result.extend(code_lines)
                    result.append("```")
                in_code_block = False
                code_lang = ""
                code_lines = []
                result.append("")
                continue
            else:
                if in_table:
                    _flush_table()
                code_lang = stripped[3:].strip()
                in_code_block = True
                continue

        if in_code_block:
            code_lines.append(line)
            continue

        # --- tables ---
        if stripped.startswith("|") and stripped.endswith("|"):
            cells = [c.strip() for c in stripped.split("|")[1:-1]]
            if all(set(c.replace(":", "")) <= {"-", " "} for c in cells):
                continue
            table_rows.append(cells)
            in_table = True
            continue
        elif in_table:
            _flush_table()

        # --- headings ---
        if stripped.startswith("#### "):
            result.append(f"==== {_convert_inline(stripped[5:])}")
        elif stripped.startswith("### "):
            result.append(f"=== {_convert_inline(stripped[4:])}")
        elif stripped.startswith("## "):
            result.append(f"== {_convert_inline(stripped[3:])}")
        elif stripped.startswith("# "):
            result.append(f"= {_convert_inline(stripped[2:])}")
        elif stripped in ("---", "***", "___"):
            result.append("#line(length: 100%)")
        elif stripped.startswith("> "):
            result.append(f"#quote[{_convert_inline(stripped[2:])}]")
        else:
            result.append(_convert_inline(line))

    if in_table:
        _flush_table()

    return "\n".join(result)


def wrap_with_rijnland_template(
    typst_body: str,
    *,
    title: str,
    document_type: str,
    project_name: str,
    status: str = "DRAFT",
) -> str:
    """Prepend the Rijnland corporate-identity template preamble."""
    watermark = "true" if status != "FINAL" else "false"
    header = (
        '#import "/druppie/templates/documents/rijnland.typ": rijnland_doc\n'
        "\n"
        "#show: rijnland_doc.with(\n"
        f'  title: "{title}",\n'
        f'  document_type: "{document_type}",\n'
        f'  status: "{status}",\n'
        f'  project_name: "{project_name}",\n'
        "  include_toc: true,\n"
        f"  include_watermark: {watermark},\n"
        "  section_breaks: true,\n"
        ")\n"
        "\n"
    )
    return header + typst_body


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
            template_dir: Directory containing the house-style templates and assets/.
                Defaults to druppie/templates/documents/.
        """
        if template_dir is None:
            self.template_dir = Path(__file__).parent.parent / "templates" / "documents"
        else:
            self.template_dir = Path(template_dir)

        if not self.template_dir.exists():
            raise DocumentFormatterError(f"Template directory not found: {self.template_dir}")

        # --root flag needs the project root (parent of druppie/); the double parent
        # traversal (templates/documents -> templates -> druppie -> project_root) is
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
            raise DocumentFormatterError(f"Typst compilation timed out after {self.TYPST_TIMEOUT}s")
        except subprocess.CalledProcessError as e:
            stderr = e.stderr[:2000] if e.stderr else ""
            logger.error(
                "typst_compile_failed",
                typ_path=str(typ_path),
                stderr=stderr,
                returncode=e.returncode,
            )
            raise DocumentFormatterError(f"Typst compilation failed:\n{stderr}") from e

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
