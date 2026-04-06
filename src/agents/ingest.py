"""Document Ingestion Agent: parses PRDs and specs into normalized markdown sections."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from src.agents.base import BaseAgent
from src.artifacts.models import DocumentSection, IngestedDocument


class IngestAgent(BaseAgent):
    agent_name = "ingest"
    default_task_type = "document_parsing"

    async def run(self, inputs: Any) -> dict:
        state = inputs["state"]
        store = inputs["store"]
        config = inputs["config"]

        # Get input file paths
        docs_dir = Path(config.get("inputs", {}).get("docs_dir", "docs/input"))
        accepted = config.get("inputs", {}).get("accepted_formats", ["pdf", "md", "html"])
        input_files = []
        for fmt in accepted:
            input_files.extend(docs_dir.glob(f"*.{fmt}"))

        if not input_files:
            raise FileNotFoundError(f"No documents found in {docs_dir}")

        documents: list[IngestedDocument] = []
        for file_path in input_files:
            doc = await self._ingest_file(file_path)
            documents.append(doc)
            self.logger.info("Ingested: %s (%d sections)", file_path.name, len(doc.sections))

        # Save all documents
        artifact_paths = []
        for doc in documents:
            path = store.save("requirements", f"ingested_{doc.doc_id[:8]}.json", doc)
            artifact_paths.append(str(path))

        # Save the list of doc IDs for the next stage
        from src.artifacts.models import RequirementSet
        import json
        doc_ids = [d.doc_id for d in documents]
        store.save_text("requirements", "doc_ids.json", json.dumps(doc_ids))

        return {"artifact_paths": artifact_paths, "documents": documents}

    async def _ingest_file(self, file_path: Path) -> IngestedDocument:
        """Parse a single file into an IngestedDocument."""
        content = file_path.read_text(errors="replace")
        doc_id = hashlib.sha256(content.encode()).hexdigest()[:16]

        suffix = file_path.suffix.lower()
        if suffix == ".pdf":
            return await self._ingest_pdf(file_path, doc_id)
        elif suffix in (".md", ".markdown"):
            return self._ingest_markdown(file_path, content, doc_id)
        elif suffix in (".html", ".htm"):
            return self._ingest_html(file_path, content, doc_id)
        else:
            # Treat as plain text
            return self._ingest_markdown(file_path, content, doc_id)

    async def _ingest_pdf(self, file_path: Path, doc_id: str) -> IngestedDocument:
        """Extract text from PDF using pymupdf."""
        try:
            import fitz  # pymupdf
            pdf = fitz.open(str(file_path))
            sections = []
            for i, page in enumerate(pdf):
                text = page.get_text()
                if text.strip():
                    sections.append(DocumentSection(
                        section_id=f"{doc_id}-page-{i+1}",
                        heading=f"Page {i+1}",
                        content=text.strip(),
                        level=1,
                    ))
            pdf.close()
        except ImportError:
            self.logger.warning("pymupdf not installed, reading PDF as text")
            content = file_path.read_text(errors="replace")
            sections = [DocumentSection(
                section_id=f"{doc_id}-raw",
                heading="Full Document",
                content=content,
                level=1,
            )]

        return IngestedDocument(
            doc_id=doc_id,
            source_path=str(file_path),
            source_format="pdf",
            title=file_path.stem,
            sections=sections,
        )

    def _ingest_markdown(self, file_path: Path, content: str, doc_id: str) -> IngestedDocument:
        """Parse markdown into sections based on headings."""
        sections = []
        current_heading = "Introduction"
        current_level = 1
        current_lines: list[str] = []
        section_idx = 0

        for line in content.split("\n"):
            if line.startswith("#"):
                # Save previous section
                if current_lines:
                    sections.append(DocumentSection(
                        section_id=f"{doc_id}-s{section_idx}",
                        heading=current_heading,
                        content="\n".join(current_lines).strip(),
                        level=current_level,
                    ))
                    section_idx += 1
                    current_lines = []

                # Parse new heading
                level = len(line) - len(line.lstrip("#"))
                current_heading = line.lstrip("#").strip()
                current_level = min(level, 6)
            else:
                current_lines.append(line)

        # Don't forget the last section
        if current_lines:
            sections.append(DocumentSection(
                section_id=f"{doc_id}-s{section_idx}",
                heading=current_heading,
                content="\n".join(current_lines).strip(),
                level=current_level,
            ))

        if not sections:
            sections = [DocumentSection(
                section_id=f"{doc_id}-s0",
                heading="Full Document",
                content=content,
                level=1,
            )]

        return IngestedDocument(
            doc_id=doc_id,
            source_path=str(file_path),
            source_format="markdown",
            title=file_path.stem,
            sections=sections,
        )

    def _ingest_html(self, file_path: Path, content: str, doc_id: str) -> IngestedDocument:
        """Convert HTML to markdown then parse."""
        try:
            from markdownify import markdownify
            md_content = markdownify(content)
        except ImportError:
            self.logger.warning("markdownify not installed, stripping HTML tags")
            import re
            md_content = re.sub(r"<[^>]+>", "", content)

        return self._ingest_markdown(file_path, md_content, doc_id)
