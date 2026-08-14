"""Tests for the obsidian-rag RAG pipeline (uses the fake embedding provider)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from obsidian_rag.config import Settings
from obsidian_rag.embeddings import EmbeddingClient
from obsidian_rag.store import VectorStore, build_index
from obsidian_rag.vault import chunk_note, scan_vault

PYPROJECT = Path(__file__).resolve().parent.parent


def make_vault(tmp_path: Path) -> Path:
    """Create a small Obsidian-style vault."""
    vault = tmp_path / "TestVault"
    (vault / "Projects").mkdir(parents=True)
    (vault / "Notes").mkdir(parents=True)
    (vault / "Projects" / "Website.md").write_text(
        """---
tags: [project]
---
# Website Redesign

## Goals
The website redesign aims to improve conversion rates and mobile experience.

## Stack
We use Next.js with TypeScript and Tailwind CSS.

## Deadline
Launch is scheduled for the end of Q3.
""",
        encoding="utf-8",
    )
    (vault / "Projects" / "MobileApp.md").write_text(
        """# Mobile App

## Stack
React Native with a Python FastAPI backend.

## Notes
Push notifications are a priority for the next release.
""",
        encoding="utf-8",
    )
    (vault / "Notes" / "Meeting 2026-08-01.md").write_text(
        """# Team Meeting

Discussion about the website redesign budget and timeline.

## Action items
- [ ] Send updated budget to finance
- [ ] Book design review with marketing
""",
        encoding="utf-8",
    )
    (vault / ".obsidian").mkdir()
    (vault / ".obsidian" / "app.json").write_text("{}", encoding="utf-8")
    (vault / ".trash").mkdir()
    (vault / ".trash" / "old.md").write_text("# Old stuff", encoding="utf-8")
    return vault


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    return make_vault(tmp_path)


def make_settings(vault: Path, tmp_path: Path) -> Settings:
    return Settings(
        vault_path=vault,
        provider="fake",
        base_url="http://localhost:1",
        model="fake-hash-v1",
        api_key=None,
        index_path=tmp_path / "index.json",
    )


# --------------------------------------------------------------------------- #
# Provider auto-detection
# --------------------------------------------------------------------------- #
def test_detect_provider():
    from obsidian_rag.config import detect_provider

    # Ollama: default port or /api path
    assert detect_provider("http://localhost:11434", None, None) == "ollama"
    assert detect_provider("http://192.168.1.5:11434/api", "x", None) == "ollama"
    # OpenAI-compatible endpoint
    assert detect_provider("https://ai.example.org/v1", "sk-1", None) == "openai"
    # No URL + no key -> offline fake
    assert detect_provider("", None, None) == "fake"
    # No URL + key -> OpenAI official
    assert detect_provider("", "sk-1", None) == "openai"
    # Explicit override wins
    assert detect_provider("http://localhost:11434", None, "openai") == "openai"
    assert detect_provider("https://ai.example.org/v1", "sk-1", "ollama") == "ollama"
# Vault scanning
# --------------------------------------------------------------------------- #
def test_scan_vault_skips_hidden_dirs(vault: Path):
    files = scan_vault(vault, max_notes=1000)
    rels = {f.relative_to(vault).as_posix() for f in files}
    assert "Projects/Website.md" in rels
    assert ".trash/old.md" not in rels
    assert len(files) == 3


def test_chunk_note_headings(vault: Path):
    note = vault / "Projects" / "Website.md"
    chunks = chunk_note(note, vault, chunk_size=1500)
    assert len(chunks) >= 3
    headings = {c.heading for c in chunks}
    assert {"Goals", "Stack", "Deadline"} <= headings
    assert all(c.path == "Projects/Website.md" for c in chunks)
    # front matter should not appear in chunk text
    assert not any("---" in c.text for c in chunks)


def test_chunk_note_without_headings(vault: Path):
    (vault / "NoHeadings.md").write_text("Just a plain note with some content.", encoding="utf-8")
    chunks = chunk_note(vault / "NoHeadings.md", vault, chunk_size=1500)
    assert chunks
    assert "plain note" in chunks[0].text


# --------------------------------------------------------------------------- #
# Store / retrieval
# --------------------------------------------------------------------------- #
def test_build_index_and_search(vault: Path, tmp_path: Path):
    settings = make_settings(vault, tmp_path)
    client = EmbeddingClient(settings)
    store = VectorStore(settings.index_path, settings.model)

    stats = build_index(settings, client, store, force=True)
    assert stats["indexed"] is True
    assert stats["notes"] == 3
    assert stats["chunks"] > 3
    assert store.index_path.is_file()

    # Reload from disk in a fresh store
    store2 = VectorStore(settings.index_path, settings.model)
    assert store2.load() is True

    qv = client.embed_one("website redesign conversion rate")
    results = store2.search(qv, top_k=3)
    assert results, "expected some results"
    assert results[0]["score"] > 0.0
    # Website redesign content should rank near the top
    top_paths = [r["path"] for r in results]
    assert "Projects/Website.md" in top_paths[:2]


def test_index_force_rebuild(vault: Path, tmp_path: Path):
    settings = make_settings(vault, tmp_path)
    client = EmbeddingClient(settings)
    store = VectorStore(settings.index_path, settings.model)
    build_index(settings, client, store, force=True)
    before = len(store)
    stats = build_index(settings, client, store, force=False)
    assert stats["indexed"] is True and "already exists" in stats["note"]
    assert len(store) == before


# --------------------------------------------------------------------------- #
# MCP server (end-to-end over stdio)
# --------------------------------------------------------------------------- #
def _env(vault: Path, tmp_path: Path) -> dict:
    env = os.environ.copy()
    env.update(
        {
            "OBSIDIAN_VAULT_PATH": str(vault),
            "EMBEDDING_PROVIDER": "fake",
            "EMBEDDING_MODEL": "fake-hash-v1",
            "OBSIDIAN_INDEX_PATH": str(tmp_path / "index.json"),
        }
    )
    return env


@pytest.mark.asyncio
async def test_mcp_server_tools(vault: Path, tmp_path: Path):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    cmd = [sys.executable, "-m", "obsidian_rag.server"]
    params = StdioServerParameters(command=cmd[0], args=cmd[1:], env=_env(vault, tmp_path))

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            names = {t.name for t in tools.tools}
            assert {
                "obsidian_index",
                "obsidian_search",
                "obsidian_rag",
                "obsidian_list_notes",
                "obsidian_read_note",
                "obsidian_index_status",
                "obsidian_get_config",
            } <= names


@pytest.mark.asyncio
async def test_mcp_rag_flow(vault: Path, tmp_path: Path):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    cmd = [sys.executable, "-m", "obsidian_rag.server"]
    params = StdioServerParameters(command=cmd[0], args=cmd[1:], env=_env(vault, tmp_path))

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            idx = await session.call_tool("obsidian_index", {"force": True})
            assert idx.isError is not True
            payload = json.loads(idx.content[0].text)
            assert payload["indexed"] is True

            res = await session.call_tool(
                "obsidian_rag", {"question": "website redesign", "top_k": 2}
            )
            assert res.isError is not True
            data = json.loads(res.content[0].text)
            assert data["count"] >= 1
            assert data["context"][0]["path"].endswith("Website.md")

            listed = await session.call_tool(
                "obsidian_list_notes", {"keyword": "Meeting"}
            )
            listed_data = json.loads(listed.content[0].text)
            assert listed_data["count"] == 1
            assert "Meeting 2026-08-01.md" in listed_data["notes"][0]
