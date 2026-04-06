"""Tests for the Ingest Agent."""

import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from src.agents.ingest import IngestAgent
from src.artifacts.models import IngestedDocument
from src.artifacts.store import ArtifactStore


@pytest.fixture
def ingest_agent(tmp_path):
    router = MagicMock()
    store = ArtifactStore(tmp_path / "generated")
    config = {
        "harness": {"output_dir": str(tmp_path / "generated")},
        "inputs": {"docs_dir": str(tmp_path / "docs"), "accepted_formats": ["md"]},
    }
    return IngestAgent(router, store, config)


def test_ingest_markdown(ingest_agent, tmp_path):
    """Test markdown parsing into sections."""
    doc = ingest_agent._ingest_markdown(
        Path("test.md"),
        "# Section 1\nContent 1\n## Section 2\nContent 2\n",
        "abc123",
    )
    assert isinstance(doc, IngestedDocument)
    assert doc.source_format == "markdown"
    assert len(doc.sections) == 2
    assert doc.sections[0].heading == "Section 1"
    assert doc.sections[1].heading == "Section 2"
    assert doc.sections[1].level == 2


def test_ingest_markdown_no_headings(ingest_agent):
    """Test markdown with no headings creates a single section."""
    doc = ingest_agent._ingest_markdown(
        Path("plain.md"),
        "Just some text\nwith no headings\n",
        "def456",
    )
    assert len(doc.sections) == 1
    assert doc.sections[0].heading == "Introduction"


@pytest.mark.asyncio
async def test_ingest_run(ingest_agent, tmp_path):
    """Test the full ingest agent run with markdown files."""
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    (docs_dir / "test_prd.md").write_text(
        "# VPN Requirements\n\nMust support WireGuard.\n\n"
        "## Encryption\n\nAES-256-GCM required.\n"
    )

    store = ArtifactStore(tmp_path / "generated")
    inputs = {
        "state": MagicMock(),
        "store": store,
        "config": {
            "inputs": {"docs_dir": str(docs_dir), "accepted_formats": ["md"]},
        },
    }

    result = await ingest_agent.run(inputs)
    assert "documents" in result
    assert len(result["documents"]) == 1
    assert result["documents"][0].sections[0].heading == "VPN Requirements"
