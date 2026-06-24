"""Document Formatter Service.

Converts agent-produced markdown into professionally formatted PDFs using Typst.

Usage:
    service = DocumentFormatterService()
    pdf_bytes = service.generate_pdf(content=markdown_str, metadata={
        "document_type": "functional_design",
        "title": "FD: Hotel Booking",
        "status": "DRAFT",
        "project_name": "Hotel Booker",
        "include_toc": True,
        "include_watermark": True,
        "section_breaks": True,
    })
"""

import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any


class DocumentFormatterService:
    """Service that formats markdown content into styled PDF via Typst."""

    def __init__(self, template_dir: Path | str | None = None):
        """Initialize with path to Typst templates.

        Args:
            template_dir: Directory containing base.typ and assets/.
                Defaults to druppie/templates/documents/ relative to this file.
        """
        if template_dir is None:
            self.template_dir = Path(__file__).parent.parent / "templates" / "documents"
        else:
            self.template_dir = Path(template_dir)

        self.base_template = self.template_dir / "base.typ"
        if not self.base_template.exists():
            raise FileNotFoundError(
                f"Template not found: {self.base_template}. "
                "Run from project root or set template_dir explicitly."
            )

        # Verify typst binary is available
        self.typst_bin = shutil.which("typst")
        if self.typst_bin is None:
            raise RuntimeError(
                "Typst binary not found in PATH. "
                "Install it or set TYPST_FONT_PATHS if using a custom location."
            )

    def _render_mermaid_diagrams(
        self, content: str, tmpdir: Path
    ) -> list[tuple[str, str]]:
        """Split markdown into segments and render mermaid blocks to PNG.

        Returns a list of (segment_type, data) tuples where segment_type is
        'text' or 'mermaid'. For 'mermaid' segments, data is the PNG filename.
        For 'text' segments, data is the markdown text.
        """
        mmdc = shutil.which("mmdc")
        has_mermaid = "```mermaid" in content

        if mmdc is None or not has_mermaid:
            return [("text", content)]

        puppeteer_config = tmpdir / "puppeteer.json"
        puppeteer_config.write_text('{"args": ["--no-sandbox"]}', encoding="utf-8")

        svg_dir = tmpdir / "assets" / "diagrams"
        svg_dir.mkdir(parents=True, exist_ok=True)

        mermaid_pattern = re.compile(r"```mermaid\s*\n(.*?)\n```", re.DOTALL)
        segments: list[tuple[str, str]] = []
        last_end = 0
        diagram_counter = 0

        for match in mermaid_pattern.finditer(content):
            text_before = content[last_end : match.start()]
            if text_before.strip():
                segments.append(("text", text_before))

            mermaid_source = match.group(1).strip()
            mmd_path = svg_dir / f"diagram_{diagram_counter}.mmd"
            png_name = f"diagram_{diagram_counter}.png"
            png_path = svg_dir / png_name
            diagram_counter += 1

            mmd_path.write_text(mermaid_source, encoding="utf-8")

            cmd = [
                mmdc,
                "-i", str(mmd_path),
                "-o", str(png_path),
                "-p", str(puppeteer_config),
            ]
            try:
                subprocess.run(
                    cmd,
                    check=True,
                    capture_output=True,
                    text=True,
                    cwd=str(tmpdir),
                )
            except subprocess.CalledProcessError:
                # Fallback: render as raw code block
                segments.append(("text", f"```mermaid\n{mermaid_source}\n```"))
                last_end = match.end()
                continue

            if png_path.exists():
                segments.append(("mermaid", png_name))
            else:
                segments.append(("text", f"```mermaid\n{mermaid_source}\n```"))

            last_end = match.end()

        text_after = content[last_end:]
        if text_after.strip():
            segments.append(("text", text_after))

        return segments

    def _write_content_typ(
        self, segments: list[tuple[str, str]], tmpdir: Path
    ) -> None:
        """Generate a content.typ that interleaves text segments (via cmarker)
        and mermaid PNG images (via #image()).
        """
        lines: list[str] = ['#import "@preview/cmarker:0.1.8"']
        text_counter = 0

        for seg_type, data in segments:
            if seg_type == "text":
                seg_file = tmpdir / f"segment_{text_counter}.md"
                seg_file.write_text(data, encoding="utf-8")
                text_counter += 1
                lines.append(f'#cmarker.render(read("segment_{text_counter - 1}.md"))')
            elif seg_type == "mermaid":
                lines.append(f'#image("assets/diagrams/{data}")')

        (tmpdir / "content.typ").write_text(
            "\n\n".join(lines) + "\n",
            encoding="utf-8",
        )

    def _prepare_base_typ(self, tmpdir: Path) -> None:
        """Copy base.typ and replace the cmarker.render line with #include("content.typ")."""
        base_src = self.base_template.read_text(encoding="utf-8")
        # Replace the single cmarker.render(read("content.md")) line
        # with an include of the generated content.typ
        modified = base_src.replace(
            '#cmarker.render(read("content.md"))',
            '#include("content.typ")',
        )
        (tmpdir / "base.typ").write_text(modified, encoding="utf-8")

    def generate_pdf(self, content: str, metadata: dict[str, Any]) -> bytes:
        """Generate a PDF from markdown content and metadata.

        Args:
            content: Markdown string (body of document).
            metadata: Dict of document metadata controlling formatting.
                Expected keys: document_type, title, status, project_name,
                include_toc, include_watermark, section_breaks.

        Returns:
            PDF bytes.

        Raises:
            subprocess.CalledProcessError: If Typst compilation fails.
        """
        with tempfile.TemporaryDirectory(prefix="druppie-doc") as tmpdir:
            tmp = Path(tmpdir)

            # Split markdown and render mermaid diagrams
            segments = self._render_mermaid_diagrams(content, tmp)

            # Generate interleaved content.typ
            self._write_content_typ(segments, tmp)

            # Write metadata JSON for template consumption
            (tmp / "metadata.json").write_text(
                json.dumps(metadata, ensure_ascii=False),
                encoding="utf-8",
            )

            # Copy assets into temp workspace
            assets_src = self.template_dir / "assets"
            if assets_src.exists():
                shutil.copytree(assets_src, tmp / "assets", dirs_exist_ok=True)

            # Prepare modified base.typ that includes content.typ
            self._prepare_base_typ(tmp)

            # Compile with Typst
            pdf_path = tmp / "output.pdf"
            cmd = [
                self.typst_bin,
                "compile",
                "--font-path",
                str(tmp / "assets" / "fonts"),
                str(tmp / "base.typ"),
                str(pdf_path),
            ]

            env = dict(os.environ)

            try:
                subprocess.run(
                    cmd,
                    check=True,
                    capture_output=True,
                    text=True,
                    cwd=str(tmp),
                    env=env,
                )
            except subprocess.CalledProcessError as e:
                # Wrap compilation errors into readable messages
                raise DocumentFormatterError(
                    f"Typst compilation failed:\n{e.stderr}"
                ) from e

            if not pdf_path.exists():
                raise DocumentFormatterError("PDF output was not created")

            return pdf_path.read_bytes()


class DocumentFormatterError(Exception):
    """Raised when document formatting fails."""
