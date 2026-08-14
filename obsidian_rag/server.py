"""obsidian-rag MCP server.

Run with:
    uv run obsidian-rag-mcp            # stdio transport (for goose)
    uv run obsidian-rag-mcp --transport sse   # SSE (for testing in browsers)

Required environment variables (set when registering the extension in goose):
    OBSIDIAN_VAULT_PATH   absolute path to the Obsidian vault

Embedding configuration:
    EMBEDDING_PROVIDER    "openai" (default, OpenAI-compatible) | "ollama"
    EMBEDDING_BASE_URL    OpenAI-compatible base URL or Ollama host
    EMBEDDING_MODEL       model name
    EMBEDDING_API_KEY     API key (required for "openai")
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from .config import Settings, load_settings
from .embeddings import EmbeddingClient, EmbeddingError
from .store import VectorStore, build_index
from .vault import scan_vault

# --------------------------------------------------------------------------- #
# State (loaded lazily so `--help`/validation can run without a vault)
# --------------------------------------------------------------------------- #
_settings: Settings | None = None
_client: EmbeddingClient | None = None
_store: VectorStore | None = None


def _ensure() -> tuple[Settings, EmbeddingClient, VectorStore]:
    global _settings, _client, _store
    if _settings is None:
        _settings = load_settings()
    if _client is None:
        _client = EmbeddingClient(_settings)
    if _store is None:
        _store = VectorStore(_settings.index_path, _settings.model)
    return _settings, _client, _store


def _err(msg: str) -> str:
    return json.dumps({"error": msg}, ensure_ascii=False)


def _ok(**kwargs: Any) -> str:
    return json.dumps(kwargs, ensure_ascii=False)


# --------------------------------------------------------------------------- #
# MCP server
# --------------------------------------------------------------------------- #
mcp = FastMCP(
    "obsidian-rag",
    instructions=(
        "RAG tools for an Obsidian vault. Use obsidian_index to build the "
        "embeddings index, then obsidian_search / obsidian_rag to retrieve "
        "relevant notes and analyze the user's input against them."
    ),
)


@mcp.tool()
def obsidian_get_config() -> str:
    """Show the current configuration (vault path, embedding provider/model).

    The API key is never returned.
    """
    try:
        settings, _, _ = _ensure()
    except ValueError as exc:
        return _err(str(exc))
    return _ok(config=settings.to_dict())


@mcp.tool()
def obsidian_index(force: bool = False) -> str:
    """Scan the vault and build/refresh the embedding index.

    Args:
        force: rebuild the index even if one already exists.
    """
    try:
        settings, client, store = _ensure()
        _ = _store  # already assigned
    except ValueError as exc:
        return _err(str(exc))
    try:
        stats = build_index(settings, client, store, force=force)
    except (RuntimeError, EmbeddingError) as exc:
        return _err(str(exc))
    return _ok(**stats)


@mcp.tool()
def obsidian_search(query: str, top_k: int = 5) -> str:
    """Semantically search the vault for chunks related to `query`.

    Args:
        query: what to look for (natural language).
        top_k: number of results to return (1-20).
    """
    try:
        settings, client, store = _ensure()
    except ValueError as exc:
        return _err(str(exc))

    if not store.load():
        return _err(
            "No index found. Call obsidian_index first to build the index."
        )
    try:
        qv = client.embed_one(query)
    except (EmbeddingError, RuntimeError) as exc:
        return _err(str(exc))
    results = store.search(qv, top_k=max(1, min(20, top_k)))
    return _ok(results=results, count=len(results))


@mcp.tool()
def obsidian_rag(question: str, top_k: int = 5) -> str:
    """Retrieve the most relevant Obsidian notes for `question` and return them
    as context.

    Use this to analyze a user's message against what is stored in the vault:
    search first, then reason over the returned context.

    Args:
        question: the user's question / content to analyze.
        top_k: number of context chunks to retrieve (1-20).
    """
    try:
        settings, client, store = _ensure()
    except ValueError as exc:
        return _err(str(exc))

    if not store.load():
        return _err(
            "No index found. Call obsidian_index first to build the index."
        )
    try:
        qv = client.embed_one(question)
    except (EmbeddingError, RuntimeError) as exc:
        return _err(str(exc))
    results = store.search(qv, top_k=max(1, min(20, top_k)))
    return _ok(
        question=question,
        model=store.model,
        context=results,
        count=len(results),
    )


@mcp.tool()
def obsidian_list_notes(keyword: str | None = None) -> str:
    """List the markdown notes in the vault.

    Args:
        keyword: optional filter; only notes whose path contains this string
                 are returned.
    """
    try:
        settings, _, _ = _ensure()
    except ValueError as exc:
        return _err(str(exc))
    files = scan_vault(settings.vault_path, settings.max_notes)
    notes = [f.relative_to(settings.vault_path).as_posix() for f in files]
    if keyword:
        notes = [n for n in notes if keyword.lower() in n.lower()]
    return _ok(count=len(notes), notes=notes)


@mcp.tool()
def obsidian_read_note(path: str) -> str:
    """Read the full text of a note from the vault.

    Args:
        path: vault-relative markdown path, e.g. "Projects/MyProject.md".
    """
    try:
        settings, _, _ = _ensure()
    except ValueError as exc:
        return _err(str(exc))

    target = (settings.vault_path / path).resolve()
    vault_root = settings.vault_path.resolve()
    # Guard against path traversal
    if not target.is_relative_to(vault_root):
        return _err("Path escapes the vault directory.")
    if not target.is_file() or target.suffix.lower() != ".md":
        return _err(f"Not a markdown file inside the vault: {path}")
    try:
        content = target.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return _err(f"Failed to read {path}: {exc}")
    return _ok(path=path, content=content)


@mcp.tool()
def obsidian_index_status() -> str:
    """Report whether an index exists and matches the configured embedding model."""
    try:
        settings, _, store = _ensure()
    except ValueError as exc:
        return _err(str(exc))
    if store.load():
        notes = len({r["path"] for r in store.records})
        return _ok(
            indexed=True,
            model=store.model,
            notes=notes,
            chunks=len(store.records),
            index_path=str(store.index_path),
        )
    return _ok(
        indexed=False,
        model=settings.model,
        index_path=str(settings.index_path),
        note="Run obsidian_index to build it.",
    )


# --------------------------------------------------------------------------- #
# Entry points
# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> None:
    """CLI entry point (used by `uv run obsidian-rag-mcp`)."""
    argv = sys.argv[1:] if argv is None else argv

    if argv and argv[0] in ("-h", "--help"):
        print(
            "obsidian-rag MCP server\n"
            "Usage:\n"
            "  obsidian-rag-mcp                 run over stdio (default)\n"
            "  obsidian-rag-mcp --transport sse run over SSE\n"
            "  obsidian-rag-mcp --check         validate configuration\n"
            "Environment:\n"
            "  OBSIDIAN_VAULT_PATH (required), EMBEDDING_PROVIDER,\n"
            "  EMBEDDING_BASE_URL, EMBEDDING_MODEL, EMBEDDING_API_KEY,\n"
            "  OBSIDIAN_INDEX_PATH, OBSIDIAN_CHUNK_SIZE, OBSIDIAN_MAX_NOTES"
        )
        return

    if argv and argv[0] == "--check":
        try:
            settings = load_settings()
        except ValueError as exc:
            print(f"[check] FAIL: {exc}")
            sys.exit(1)
        print(
            "[check] OK\n"
            f"  vault  : {settings.vault_path}\n"
            f"  provider: {settings.provider}\n"
            f"  base_url: {settings.base_url}\n"
            f"  model  : {settings.model}\n"
            f"  api_key: {'set' if settings.api_key else 'NOT SET'}"
        )
        return

    if argv and argv[0] == "--transport":
        transport = argv[1] if len(argv) > 1 else "stdio"
        mcp.run(transport=transport)
        return

    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
