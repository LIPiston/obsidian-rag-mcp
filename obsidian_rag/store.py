"""Persistent vector store + cosine similarity retrieval (pure Python)."""

from __future__ import annotations

import json
import math
import os
import tempfile
from pathlib import Path
from typing import Iterable

from .config import Settings
from .embeddings import EmbeddingClient


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    if len(a) != len(b) or not a:
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (math.sqrt(na) * math.sqrt(nb))


class VectorStore:
    """JSON-backed store of embedded chunks."""

    def __init__(self, index_path: Path, model: str):
        self.index_path = index_path
        self.model = model
        self.records: list[dict] = []

    # ------------------------------------------------------------------ #
    def load(self) -> bool:
        """Load an existing index if it matches the current embedding model."""
        if not self.index_path.is_file():
            return False
        try:
            data = json.loads(self.index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        if data.get("model") != self.model or not isinstance(data.get("chunks"), list):
            return False
        self.records = data["chunks"]
        return True

    def save(self) -> None:
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"model": self.model, "chunks": self.records}
        # Atomic-ish write
        fd, tmp = tempfile.mkstemp(
            dir=str(self.index_path.parent), suffix=".tmp", text=True
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False)
            os.replace(tmp, self.index_path)
        finally:
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass

    def reset(self) -> None:
        self.records = []

    def add(self, records: Iterable[dict]) -> None:
        self.records.extend(records)

    def __len__(self) -> int:
        return len(self.records)

    # ------------------------------------------------------------------ #
    def search(self, query_vector: list[float], top_k: int = 5) -> list[dict]:
        """Return top-k chunks ranked by cosine similarity."""
        if not self.records:
            return []
        scored = []
        for rec in self.records:
            emb = rec.get("embedding")
            if not emb:
                continue
            score = _cosine_similarity(query_vector, emb)
            scored.append((score, rec))
        scored.sort(key=lambda item: item[0], reverse=True)
        results = []
        for score, rec in scored[:top_k]:
            result = {
                "path": rec.get("path", ""),
                "title": rec.get("title", ""),
                "heading": rec.get("heading", ""),
                "text": rec.get("text", ""),
                "score": round(score, 4),
            }
            results.append(result)
        return results


def build_index(
    settings: Settings, client: EmbeddingClient, store: VectorStore, force: bool = False
) -> dict:
    """Scan the vault and (re)build the embedding index. Returns stats."""
    if store.records and not force:
        return {
            "indexed": True,
            "notes": len({r["path"] for r in store.records}),
            "chunks": len(store.records),
            "model": store.model,
            "note": "Index already exists. Pass force=True to rebuild.",
        }

    from .vault import chunk_note, scan_vault

    note_files = scan_vault(settings.vault_path, settings.max_notes)
    if not note_files:
        return {
            "indexed": False,
            "notes": 0,
            "chunks": 0,
            "model": settings.model,
            "note": "No .md files found in the vault.",
        }

    store.reset()
    total_chunks = 0
    for nf in note_files:
        chunks = chunk_note(nf, settings.vault_path, settings.chunk_size)
        if not chunks:
            continue
        texts = [c.text for c in chunks]
        try:
            embeddings = client.embed(texts)
        except Exception as exc:  # noqa: BLE001 - surface to caller
            raise RuntimeError(
                f"Embedding failed while indexing {nf.name}: {exc}"
            ) from exc
        for chunk, emb in zip(chunks, embeddings):
            store.add([chunk.to_record(emb)])
        total_chunks += len(chunks)

    store.save()
    return {
        "indexed": True,
        "notes": len({r["path"] for r in store.records}),
        "chunks": len(store.records),
        "model": store.model,
        "note": f"Indexed {len(note_files)} notes → {total_chunks} chunks.",
    }
