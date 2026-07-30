"""PDF render service — on-demand compilation with render cache.

The cache is keyed by (project_id, typ_path, file_sha) where file_sha is the
Git blob SHA from Gitea. This means identical source at identical revision
always produces the same PDF without recompiling.

Source of truth for documents is Gitea (not a local file). The PDF is a
reproducible build artifact: re-creatable any time from the cached metadata.
"""

import base64
import os
import re
from pathlib import Path

import structlog

from druppie.core.gitea import get_gitea_client
from druppie.repositories.pdf_render_repository import PdfRenderRepository
from druppie.services.document_formatter_service import (
    DocumentFormatterError,
    DocumentFormatterService,
)

logger = structlog.get_logger()

CACHE_ROOT = Path(os.getenv("WORKSPACE_ROOT", "/app/workspace")) / "uploads" / "pdf-cache"


class PdfRenderService:
    """Resolve Typst source from Gitea, compile, and cache the result."""

    def __init__(self, db=None):
        self.db = db
        self.typst = DocumentFormatterService()

    async def get_or_create_pdf(
        self,
        project_id,
        repo_name: str,
        repo_owner: str,
        typ_path: str,
        branches: list[str] | None = None,
        output_pdf_name: str | None = None,
    ) -> tuple[bytes, str, str] | tuple[None, None, str]:
        """Return (pdf_bytes, pdf_storage_path, error_message).

        Tries branches in order. Cache hit → returns cached bytes instantly.
        Cache miss → resolves from Gitea, compiles, stores in cache.
        """
        gitea = get_gitea_client()
        branches = branches or ["main"]

        file_result = None
        content = None
        file_sha = ""
        for branch in branches:
            file_result = await gitea.get_file(
                repo=repo_name,
                path=typ_path,
                branch=branch,
                owner=repo_owner,
            )
            if file_result.get("success"):
                content = file_result.get("content")
                file_sha = file_result.get("data", {}).get("sha", "")
                if content and file_sha:
                    break

        if not content or not file_sha:
            return None, None, f"Typst source not found in Gitea: {typ_path}"

        repo = PdfRenderRepository(self.db)
        cached = repo.get_by_cache_key(project_id, typ_path, file_sha)
        if cached:
            cache_file = (
                Path(os.getenv("WORKSPACE_ROOT", "/app/workspace")) / cached.pdf_storage_path
            )
            if cache_file.exists():
                pdf_bytes = cache_file.read_bytes()
                logger.info(
                    "pdf_cache_hit",
                    project_id=str(project_id),
                    typ_path=typ_path,
                    file_sha=file_sha[:8],
                    size=len(pdf_bytes),
                )
                return pdf_bytes, cached.pdf_storage_path, ""

        pdf_name = output_pdf_name or f"{Path(typ_path).stem}.pdf"
        pdf_name = pdf_name.replace(" ", "_").replace("/", "_")

        cache_dir = CACHE_ROOT / str(project_id) / file_sha[:8]
        cache_dir.mkdir(parents=True, exist_ok=True)
        temp_dir = cache_dir / "_build"
        temp_dir.mkdir(parents=True, exist_ok=True)

        try:
            typ_file = temp_dir / Path(typ_path).name
            typ_file.parent.mkdir(parents=True, exist_ok=True)
            typ_file.write_text(content, encoding="utf-8")

            image_refs = self._extract_image_refs(content)

            listed = await gitea.list_files(
                repo=repo_name,
                path="docs/diagrams",
                branch=branch,
                owner=repo_owner,
            )
            if listed.get("success") and listed.get("files"):
                for f in listed["files"]:
                    if f.get("path", "").endswith(".svg"):
                        image_refs.add(f["path"])

            typ_parent = Path(typ_path).parent
            for img_ref in image_refs:
                if img_ref.startswith("docs/"):
                    gitea_img_path = img_ref
                else:
                    gitea_img_path = (
                        str(typ_parent / img_ref) if typ_parent != Path(".") else img_ref
                    )

                try:
                    img_res = await gitea.get_file(
                        repo=repo_name,
                        path=gitea_img_path,
                        branch=branch,
                        owner=repo_owner,
                    )
                    if img_res.get("success") and img_res.get("data", {}).get("content"):
                        raw_b64 = img_res["data"]["content"]
                        try:
                            img_bytes = base64.b64decode(raw_b64)
                            local_img = temp_dir / img_ref
                            local_img.parent.mkdir(parents=True, exist_ok=True)
                            local_img.write_bytes(img_bytes)
                        except (ValueError, OSError) as exc:
                            logger.warning(
                                "pdf_render_image_decode_failed",
                                img_ref=img_ref,
                                error=str(exc),
                            )
                            continue
                except Exception as exc:
                    logger.warning(
                        "pdf_render_image_download_failed",
                        img_ref=img_ref,
                        error=str(exc),
                    )
                    continue

            pdf_file = temp_dir / pdf_name
            pdf_bytes = self.typst.compile_typ(typ_file, output_pdf_path=pdf_file)

            cache_pdf = cache_dir / pdf_name
            cache_pdf.write_bytes(pdf_bytes)

            storage_path = f"uploads/pdf-cache/{project_id}/{file_sha[:8]}/{pdf_name}"
            repo.create(
                project_id=project_id,
                typ_path=typ_path,
                file_sha=file_sha,
                pdf_storage_path=storage_path,
                file_size=len(pdf_bytes),
            )
            self.db.commit()

            logger.info(
                "pdf_cache_miss_compiled",
                project_id=str(project_id),
                typ_path=typ_path,
                file_sha=file_sha[:8],
                size=len(pdf_bytes),
            )
            return pdf_bytes, storage_path, ""

        except DocumentFormatterError as e:
            return None, None, f"PDF compilation failed: {e}"

        finally:
            if temp_dir.exists():
                import shutil

                shutil.rmtree(temp_dir)

    async def render_markdown_pdf(
        self,
        project_id,
        repo_name: str,
        repo_owner: str,
        markdown_path: str,
        document_type: str,
        title: str,
        project_name: str,
        branches: list[str] | None = None,
        output_pdf_name: str | None = None,
    ) -> tuple[bytes, str, str] | tuple[None, None, str]:
        """Convert a markdown file to a Rijnland-branded PDF.

        Fetches markdown from Gitea, converts to Typst with the
        corporate identity template, compiles, and caches the result.
        """
        from druppie.services.document_formatter_service import (
            markdown_to_typst,
            wrap_with_rijnland_template,
        )

        gitea = get_gitea_client()
        branches = branches or ["main"]

        content = None
        file_sha = ""
        successful_branch = None
        for branch in branches:
            file_result = await gitea.get_file(
                repo=repo_name,
                path=markdown_path,
                branch=branch,
                owner=repo_owner,
            )
            if file_result.get("success"):
                content = file_result.get("content")
                file_sha = file_result.get("data", {}).get("sha", "")
                if content and file_sha:
                    successful_branch = branch
                    break

        if not content or not file_sha:
            return None, None, f"Markdown file not found in Gitea: {markdown_path}"

        cache_key = f"{markdown_path}:design_pdf"
        repo = PdfRenderRepository(self.db)
        cached = repo.get_by_cache_key(project_id, cache_key, file_sha)
        if cached:
            cache_file = (
                Path(os.getenv("WORKSPACE_ROOT", "/app/workspace")) / cached.pdf_storage_path
            )
            if cache_file.exists():
                pdf_bytes = cache_file.read_bytes()
                logger.info(
                    "design_pdf_cache_hit",
                    markdown_path=markdown_path,
                    file_sha=file_sha[:8],
                )
                return pdf_bytes, cached.pdf_storage_path, ""

        typst_body = markdown_to_typst(content)
        typst_content = wrap_with_rijnland_template(
            typst_body,
            title=title,
            document_type=document_type,
            project_name=project_name,
        )

        pdf_name = output_pdf_name or f"{Path(markdown_path).stem}.pdf"
        pdf_name = pdf_name.replace(" ", "_").replace("/", "_")

        cache_dir = CACHE_ROOT / str(project_id) / file_sha[:8]
        cache_dir.mkdir(parents=True, exist_ok=True)
        temp_dir = cache_dir / "_build"
        temp_dir.mkdir(parents=True, exist_ok=True)

        try:
            typ_file = temp_dir / f"{Path(markdown_path).stem}.typ"
            typ_file.write_text(typst_content, encoding="utf-8")

            image_refs = self._extract_image_refs(typst_content)

            if successful_branch:
                try:
                    listed = await gitea.list_files(
                        repo=repo_name,
                        path="docs/diagrams",
                        branch=successful_branch,
                        owner=repo_owner,
                    )
                    if listed.get("success") and listed.get("files"):
                        for f in listed["files"]:
                            if f.get("path", "").endswith(".svg"):
                                image_refs.add(f["path"])
                except Exception:
                    pass

            md_parent = Path(markdown_path).parent
            for img_ref in image_refs:
                if img_ref.startswith("docs/"):
                    gitea_img_path = img_ref
                else:
                    gitea_img_path = str(md_parent / img_ref) if md_parent != Path(".") else img_ref
                try:
                    img_res = await gitea.get_file(
                        repo=repo_name,
                        path=gitea_img_path,
                        branch=successful_branch or branches[0],
                        owner=repo_owner,
                    )
                    if img_res.get("success") and img_res.get("data", {}).get("content"):
                        raw_b64 = img_res["data"]["content"]
                        try:
                            img_bytes = base64.b64decode(raw_b64)
                            local_img = temp_dir / img_ref
                            local_img.parent.mkdir(parents=True, exist_ok=True)
                            local_img.write_bytes(img_bytes)
                        except (ValueError, OSError):
                            continue
                except Exception:
                    continue

            pdf_file = temp_dir / pdf_name
            pdf_bytes = self.typst.compile_typ(typ_file, output_pdf_path=pdf_file)

            cache_pdf = cache_dir / pdf_name
            cache_pdf.write_bytes(pdf_bytes)

            storage_path = f"uploads/pdf-cache/{project_id}/{file_sha[:8]}/{pdf_name}"
            repo.create(
                project_id=project_id,
                typ_path=cache_key,
                file_sha=file_sha,
                pdf_storage_path=storage_path,
                file_size=len(pdf_bytes),
            )
            self.db.commit()

            logger.info(
                "design_pdf_rendered",
                markdown_path=markdown_path,
                file_sha=file_sha[:8],
                size=len(pdf_bytes),
            )
            return pdf_bytes, storage_path, ""

        except DocumentFormatterError as e:
            return None, None, f"PDF compilation failed: {e}"

        except Exception as exc:
            logger.error(
                "render_markdown_pdf_failed",
                markdown_path=markdown_path,
                project_id=str(project_id),
                error=str(exc),
                exc_info=True,
            )
            raise

        finally:
            if temp_dir.exists():
                import shutil

                shutil.rmtree(temp_dir)

    @staticmethod
    def _extract_image_refs(content: str) -> set[str]:
        refs = set()
        for match in re.finditer(r"[#\s]*image\s*\(", content):
            start = match.end()
            rest = content[start : start + 500]
            quoted = re.search(r"""["']([^"']+)["']""", rest)
            if quoted:
                img_path = quoted.group(1).strip()
                if img_path.startswith(("http://", "https://", "/")):
                    continue
                refs.add(img_path)
        return refs
