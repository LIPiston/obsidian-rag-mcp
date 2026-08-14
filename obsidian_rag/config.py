"""Configuration for obsidian-rag-mcp.

All settings are read from environment variables so they can be supplied via
the MCP extension's environment configuration (``envs``) when registering the
server with goose.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# Env var names (also used by the goose MCP extension config)
ENV_VAULT_PATH = "OBSIDIAN_VAULT_PATH"
ENV_PROVIDER = "EMBEDDING_PROVIDER"
ENV_BASE_URL = "EMBEDDING_BASE_URL"
ENV_MODEL = "EMBEDDING_MODEL"
ENV_API_KEY = "EMBEDDING_API_KEY"
ENV_INDEX_PATH = "OBSIDIAN_INDEX_PATH"
ENV_CHUNK_SIZE = "OBSIDIAN_CHUNK_SIZE"
ENV_MAX_NOTES = "OBSIDIAN_MAX_NOTES"


def _default_index_dir() -> Path:
    base = os.environ.get("OBSIDIAN_INDEX_HOME")
    if base:
        return Path(base).expanduser()
    return Path.home() / ".obsidian-rag"


@dataclass
class Settings:
    """Resolved settings for the server."""

    vault_path: Path
    provider: str = "openai"  # "openai" (compatible) or "ollama"
    base_url: str = "https://api.openai.com/v1"
    model: str = "text-embedding-3-small"
    api_key: str | None = None
    index_path: Path = field(default_factory=lambda: _default_index_dir() / "index.json")
    chunk_size: int = 1500
    max_notes: int = 1000

    @property
    def vault_name(self) -> str:
        return self.vault_path.name or "vault"

    @property
    def is_ollama(self) -> bool:
        return self.provider.lower() in ("ollama", "local")

    @property
    def is_fake(self) -> bool:
        return self.provider.lower() == "fake"

    def to_dict(self) -> dict:
        """Non-secret view of the settings (never include api_key)."""
        return {
            "vault_path": str(self.vault_path),
            "provider": self.provider,
            "base_url": self.base_url,
            "model": self.model,
            "api_key_set": bool(self.api_key),
            "index_path": str(self.index_path),
            "chunk_size": self.chunk_size,
            "max_notes": self.max_notes,
        }


def load_settings() -> Settings:
    """Load settings from the environment, validating the vault path."""
    vault_raw = os.environ.get(ENV_VAULT_PATH, "").strip()
    if not vault_raw:
        raise ValueError(
            f"Environment variable {ENV_VAULT_PATH} is not set. "
            "Provide the absolute path to your Obsidian vault when configuring the "
            "MCP extension (e.g. OBSIDIAN_VAULT_PATH=C:\\Users\\me\\MyVault)."
        )

    vault = Path(vault_raw).expanduser()
    if not vault.is_dir():
        raise ValueError(
            f"OBSIDIAN_VAULT_PATH does not exist or is not a directory: {vault}"
        )

    provider = os.environ.get(ENV_PROVIDER, "openai").strip().lower()
    base_url = os.environ.get(ENV_BASE_URL, "").strip()
    model = os.environ.get(ENV_MODEL, "").strip()
    api_key = os.environ.get(ENV_API_KEY, "").strip() or None

    if provider in ("ollama", "local"):
        if not base_url:
            base_url = "http://localhost:11434"
        if not model:
            model = "nomic-embed-text"
    elif provider == "fake":
        # Deterministic local embeddings for testing/demo. No network needed.
        if not model:
            model = "fake-hash-v1"
    else:
        provider = "openai"
        if not base_url:
            base_url = "https://api.openai.com/v1"
        if not model:
            model = "text-embedding-3-small"

    index_raw = os.environ.get(ENV_INDEX_PATH, "").strip()
    index_path = Path(index_raw).expanduser() if index_raw else _default_index_dir() / "index.json"

    try:
        chunk_size = int(os.environ.get(ENV_CHUNK_SIZE, "1500"))
    except ValueError:
        chunk_size = 1500
    try:
        max_notes = int(os.environ.get(ENV_MAX_NOTES, "1000"))
    except ValueError:
        max_notes = 1000

    return Settings(
        vault_path=vault,
        provider=provider,
        base_url=base_url.rstrip("/"),
        model=model,
        api_key=api_key,
        index_path=index_path,
        chunk_size=max(200, chunk_size),
        max_notes=max(1, max_notes),
    )
