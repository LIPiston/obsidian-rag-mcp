"""Embedding client supporting OpenAI-compatible APIs and Ollama."""

from __future__ import annotations

from typing import Any

import httpx

from .config import Settings


class EmbeddingError(RuntimeError):
    pass


class EmbeddingClient:
    """Fetches text embeddings from a configurable backend.

    - ``provider == "openai"`` → OpenAI-compatible ``POST {base}/embeddings``
    - ``provider == "ollama"``  → Ollama ``POST {base}/api/embed``
    """

    def __init__(self, settings: Settings, timeout: float = 60.0):
        self.settings = settings
        self.timeout = timeout

    @property
    def model_name(self) -> str:
        return self.settings.model

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        texts = [t[:8000] for t in texts]  # keep payloads sane
        if self.settings.is_fake:
            return self._embed_fake(texts)
        if self.settings.is_ollama:
            return self._embed_ollama(texts)
        return self._embed_openai(texts)
    def embed_one(self, text: str) -> list[float]:
        return self.embed([text])[0]

    # ------------------------------------------------------------------ #
    def _embed_openai(self, texts: list[str]) -> list[list[float]]:
        if not self.settings.api_key:
            raise EmbeddingError(
                "EMBEDDING_API_KEY is required when using an OpenAI-compatible "
                "embedding endpoint"
            )
        url = f"{self.settings.base_url}/embeddings"
        headers = {
            "Authorization": f"Bearer {self.settings.api_key}",
            "Content-Type": "application/json",
        }
        payload: dict[str, Any] = {"model": self.settings.model, "input": texts}
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.post(url, headers=headers, json=payload)
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as exc:
            raise EmbeddingError(f"Embedding request failed: {exc}") from exc

        items = data.get("data", [])
        # Some providers return items in arbitrary order; sort by index.
        items.sort(key=lambda it: it.get("index", 0))
        vectors = [it.get("embedding") for it in items]
        if not vectors or any(v is None for v in vectors):
            raise EmbeddingError(
                f"Unexpected embedding response from {url}: {str(data)[:300]}"
            )
        return vectors

    def _embed_ollama(self, texts: list[str]) -> list[list[float]]:
        url = f"{self.settings.base_url}/api/embed"
        payload = {"model": self.settings.model, "input": texts}
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.post(url, json=payload)
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as exc:
            raise EmbeddingError(f"Ollama embedding request failed: {exc}") from exc

        embeddings = data.get("embeddings")
        if not embeddings:
            raise EmbeddingError(
                f"Unexpected Ollama embedding response: {str(data)[:300]}"
            )
        return embeddings

    def _embed_fake(self, texts: list[str]) -> list[list[float]]:
        """Deterministic bag-of-words style vectors, no network needed.

        Useful for testing and for demoing the RAG pipeline before wiring up
        a real embedding API. Uses word counts over a fixed vocabulary of
        word hashes, so similar text yields similar vectors.
        """
        import hashlib

        vectors: list[list[float]] = []
        for text in texts:
            vec: dict[int, float] = {}
            for word in text.lower().split():
                h = int(hashlib.md5(word.encode("utf-8")).hexdigest()[:8], 16)
                idx = h % 256
                vec[idx] = vec.get(idx, 0.0) + 1.0
            # Normalize
            norm = sum(v * v for v in vec.values()) ** 0.5 or 1.0
            dense = [0.0] * 256
            for idx, count in vec.items():
                dense[idx] = count / norm
            vectors.append(dense)
        return vectors
