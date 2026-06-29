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

    def _render_diagrams(
        self, content: str, tmpdir: Path,
        archimate_base_path: Path | None = None,
    ) -> list[tuple[str, str]]:
        """Split markdown into segments and render diagram blocks.

        Handles 'mermaid' (→ PNG via mmdc) and 'archimate' (→ SVG via Node.js SSR).
        Unrenderable blocks fall back to styled text references.

        Returns a list of (segment_type, data) tuples where segment_type
        is 'text', 'mermaid', or 'svg'.
        """
        diagrams_dir = tmpdir / "assets" / "diagrams"
        diagrams_dir.mkdir(parents=True, exist_ok=True)
        diagram_counter = 0

        # --- ArchiMate SSR setup ---
        archimate_ssr = Path("/app/scripts/archimate-ssr/render-archimate.mjs")
        has_archimate_ssr = archimate_ssr.exists()
        node_bin = shutil.which("node")

        DiagramBlock = tuple[int, int, str, str]
        blocks: list[DiagramBlock] = []

        for m in re.finditer(r"```mermaid\s*\n(.*?)\n```", content, re.DOTALL):
            blocks.append((m.start(), m.end(), "mermaid", m.group(1).strip()))

        for m in re.finditer(r"```archimate\s*\n(.*?)\n```", content, re.DOTALL):
            blocks.append((m.start(), m.end(), "archimate", m.group(1).strip()))

        blocks.sort(key=lambda b: b[0])

        if not blocks:
            return [("text", content)]

        segments: list[tuple[str, str]] = []
        last_end = 0

        for start, end, dtype, source in blocks:
            text_before = content[last_end:start]
            if text_before.strip():
                segments.append(("text", text_before))

            if dtype == "mermaid":
                self._render_mermaid(source, diagrams_dir, diagram_counter, segments)
            elif dtype == "archimate":
                self._render_archimate(
                    source, diagrams_dir, diagram_counter, segments,
                    has_archimate_ssr, node_bin, archimate_ssr,
                    archimate_base_path,
                )

            diagram_counter += 1
            last_end = end

        text_after = content[last_end:]
        if text_after.strip():
            segments.append(("text", text_after))

        return segments

    def _render_mermaid(
        self, source: str, out_dir: Path, counter: int,
        segments: list[tuple[str, str]]
    ) -> None:
        mmdc = shutil.which("mmdc")
        if mmdc is None:
            segments.append(("text", f"```mermaid\n{source}\n```"))
            return

        mmd_path = out_dir / f"diagram_{counter}.mmd"
        png_name = f"diagram_{counter}.png"
        png_path = out_dir / png_name
        mmd_path.write_text(source, encoding="utf-8")

        puppeteer_config = out_dir.parent.parent / "puppeteer.json"
        if not puppeteer_config.exists():
            puppeteer_config.write_text('{"args": ["--no-sandbox"]}', encoding="utf-8")

        cmd = [
            mmdc, "-i", str(mmd_path), "-o", str(png_path),
            "-p", str(puppeteer_config),
        ]
        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError:
            segments.append(("text", f"```mermaid\n{source}\n```"))
            return

        segments.append(("mermaid", png_name) if png_path.exists()
                        else ("text", f"```mermaid\n{source}\n```"))

    def _render_archimate(
        self, source: str, out_dir: Path, counter: int,
        segments: list[tuple[str, str]],
        has_ssr: bool, node_bin: str | None, ssr_script: Path,
        archimate_base_path: Path | None = None,
    ) -> None:
        # Parse spec (view-id + file)
        spec: dict[str, str] = {}
        for line in source.splitlines():
            m = re.match(r"^\s*([a-zA-Z_-]+)\s*[:=]\s*(.+?)\s*$", line)
            if m:
                spec[m[1].lower()] = m[2]

        view_id = spec.get("view-id", "")
        xml_file = spec.get("file", "docs/architecture.archimate")

        if not has_ssr or not node_bin or not view_id:
            # Fallback to text reference
            segments.append(("text",
                f"**Architecture Reference**\n\n- **View ID:** {view_id}\n"
                f"- **Source:** {xml_file}\n"))
            return

        xml_candidates: list[Path] = [
            self.template_dir / xml_file,
            self.template_dir / "test-inputs" / Path(xml_file).name,
        ]
        if archimate_base_path is not None:
            xml_candidates.insert(0, archimate_base_path / xml_file)
        xml_candidates.append(Path(xml_file))
        xml_path = next((p for p in xml_candidates if p.exists()), None)
        if xml_path is None:
            segments.append(("text",
                f"**Architecture Reference**\n\n- **View ID:** {view_id}\n"
                f"- **Source:** {xml_file} *(file not found)*\n"))
            return

        svg_name = f"diagram_{counter}.svg"
        svg_path = out_dir / svg_name
        cmd = [
            node_bin, str(ssr_script),
            "--xml", str(xml_path),
            "--view-id", view_id,
            "--output", str(svg_path),
        ]
        try:
            subprocess.run(
                cmd, check=True, capture_output=True, text=True,
                cwd=str(ssr_script.parent),
            )
        except subprocess.CalledProcessError:
            segments.append(("text",
                f"**Architecture Reference**\n\n- **View ID:** {view_id}\n"
                f"- **Source:** {xml_file} *(render failed)*\n"))
            return

        segments.append(("svg", svg_name) if svg_path.exists()
                        else ("text",
                            f"**Architecture Reference**\n\n- **View ID:** {view_id}\n"
                            f"- **Source:** {xml_file}\n"))

    def _write_content_typ(
        self, segments: list[tuple[str, str]], tmpdir: Path
    ) -> None:
        """Generate a content.typ that interleaves text segments (via cmarker)
        and diagram images (PNG for mermaid, SVG for archimate).
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
            elif seg_type == "svg":
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

    def generate_pdf(
        self,
        content: str,
        metadata: dict[str, Any],
        archimate_base_path: Path | None = None,
    ) -> bytes:
        """Generate a PDF from markdown content and metadata.

        Args:
            content: Markdown string (body of document).
            metadata: Dict of document metadata controlling formatting.
                Expected keys: document_type, title, status, project_name,
                include_toc, include_watermark, section_breaks.
            archimate_base_path: Optional base path for resolving ArchiMate
                XML files referenced in `` ```archimate `` blocks.

        Returns:
            PDF bytes.

        Raises:
            subprocess.CalledProcessError: If Typst compilation fails.
        """
        with tempfile.TemporaryDirectory(prefix="druppie-doc") as tmpdir:
            tmp = Path(tmpdir)

            # Split markdown and render mermaid diagrams
            segments = self._render_diagrams(
                content, tmp, archimate_base_path=archimate_base_path
            )

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
