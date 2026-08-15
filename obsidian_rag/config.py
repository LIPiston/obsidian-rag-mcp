"""Configuration for obsidian-rag-mcp.

All settings are read from environment variables so they can be supplied via
the MCP client's environment configuration (``env`` in JSON configs, ``envs``
in goose's YAML) when registering the server (Claude Desktop, Cursor, ZCode,
goose, ...).

You only need three embedding settings:
  EMBEDDING_BASE_URL   URL of the embedding API
  EMBEDDING_MODEL      model name
  EMBEDDING_API_KEY    API key (only for OpenAI-compatible endpoints)
  EMBEDDING_PROVIDER   optional override: openai | ollama | fake

The backend is detected automatically from EMBEDDING_BASE_URL:
  - port 11434 or a path ending in /api  -> Ollama
  - otherwise                            -> OpenAI-compatible (POST {base}/embeddings)

If EMBEDDING_BASE_URL is empty and EMBEDDING_API_KEY is set, the OpenAI
official endpoint is used. If both are empty, the offline "fake" provider
(deterministic local embeddings, no network) is used for testing/demos.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# Env var names (also used by the MCP client's server config)
ENV_VAULT_PATH = "OBSIDIAN_VAULT_PATH"
ENV_BASE_URL = "EMBEDDING_BASE_URL"
ENV_MODEL = "EMBEDDING_MODEL"
ENV_API_KEY = "EMBEDDING_API_KEY"
ENV_PROVIDER = "EMBEDDING_PROVIDER"  # optional manual override: openai|ollama|fake
ENV_INDEX_PATH = "OBSIDIAN_INDEX_PATH"
ENV_CHUNK_SIZE = "OBSIDIAN_CHUNK_SIZE"
ENV_MAX_NOTES = "OBSIDIAN_MAX_NOTES"

DEFAULT_OPENAI_URL = "https://api.openai.com/v1"
DEFAULT_OPENAI_MODEL = "text-embedding-3-small"
DEFAULT_OLLAMA_URL = "http://localhost:11434"
DEFAULT_OLLAMA_MODEL = "nomic-embed-text"
FAKE_MODEL = "fake-hash-v1"

_PROVIDER_OPENAI = "openai"
_PROVIDER_OLLAMA = "ollama"
_PROVIDER_FAKE = "fake"


def _default_index_dir() -> Path:
    base = os.environ.get("OBSIDIAN_INDEX_HOME")
    if base:
        return Path(base).expanduser()
    return Path.home() / ".obsidian-rag"


def detect_provider(base_url: str, api_key: str | None, override: str | None) -> str:
    """Decide which backend to use.

    Priority:
      1. explicit EMBEDDING_PROVIDER override (openai|ollama|fake)
      2. URL-based detection (Ollama port/path -> ollama)
      3. no URL + no key -> fake (offline testing)
      4. otherwise -> openai
    """
    if override:
        ov = override.strip().lower()
        if ov in (_PROVIDER_OPENAI, _PROVIDER_OLLAMA, _PROVIDER_FAKE):
            return ov

    if base_url:
        lower = base_url.lower()
        if ":11434" in lower or lower.rstrip("/").endswith("/api"):
            return _PROVIDER_OLLAMA
        return _PROVIDER_OPENAI

    if not api_key:
        return _PROVIDER_FAKE
    return _PROVIDER_OPENAI


@dataclass
class Settings:
    """Resolved settings for the server."""

    vault_path: Path
    base_url: str
    model: str
    api_key: str | None = None
    provider: str = _PROVIDER_OPENAI
    index_path: Path = field(default_factory=lambda: _default_index_dir() / "index.json")
    chunk_size: int = 1500
    max_notes: int = 1000

    @property
    def vault_name(self) -> str:
        return self.vault_path.name or "vault"

    @property
    def is_ollama(self) -> bool:
        return self.provider == _PROVIDER_OLLAMA

    @property
    def is_fake(self) -> bool:
        return self.provider == _PROVIDER_FAKE

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

    base_url = os.environ.get(ENV_BASE_URL, "").strip()
    model = os.environ.get(ENV_MODEL, "").strip()
    api_key = os.environ.get(ENV_API_KEY, "").strip() or None
    override = os.environ.get(ENV_PROVIDER, "").strip() or None

    provider = detect_provider(base_url, api_key, override)

    if not base_url:
        if provider == _PROVIDER_OLLAMA:
            base_url = DEFAULT_OLLAMA_URL
        elif provider == _PROVIDER_FAKE:
            base_url = ""
        else:
            base_url = DEFAULT_OPENAI_URL

    if not model:
        if provider == _PROVIDER_OLLAMA:
            model = DEFAULT_OLLAMA_MODEL
        elif provider == _PROVIDER_FAKE:
            model = FAKE_MODEL
        else:
            model = DEFAULT_OPENAI_MODEL

    index_raw = os.environ.get(ENV_INDEX_PATH, "").strip()
    index_path = (
        Path(index_raw).expanduser() if index_raw else _default_index_dir() / "index.json"
    )

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
