"""Scan an Obsidian vault and split markdown notes into chunks."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Chunk:
    """A single retrievable text chunk."""

    path: str  # relative path inside the vault, posix style
    title: str  # note title (file stem)
    heading: str  # nearest markdown heading, or ""
    text: str

    def to_record(self, embedding: list[float]) -> dict:
        return {
            "path": self.path,
            "title": self.title,
            "heading": self.heading,
            "text": self.text,
            "embedding": embedding,
        }


HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")

# Front matter delimiters
FRONTMATTER_RE = re.compile(r"^---\s*\n.*?\n---\s*\n?", re.DOTALL)

# Markdown syntax to keep as plain text (code fences, tags, internal links, images)
CODE_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")
IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
TAG_RE = re.compile(r"#[\w/\-]+")


def _clean_text(text: str) -> str:
    text = FRONTMATTER_RE.sub("\n", text)
    text = CODE_FENCE_RE.sub("\n", text)
    text = IMAGE_RE.sub(r"\1", text)
    text = INLINE_CODE_RE.sub(r"\1", text)
    text = LINK_RE.sub(r"\1", text)
    text = TAG_RE.sub(" ", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _split_paragraphs(text: str, chunk_size: int) -> list[str]:
    """Split text into chunks of ~chunk_size characters at paragraph boundaries."""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    def flush() -> None:
        nonlocal current, current_len
        if current:
            chunks.append("\n\n".join(current))
            current = []
            current_len = 0

    for para in paragraphs:
        # Very long paragraph: hard-split it
        while len(para) > chunk_size:
            flush()
            chunks.append(para[:chunk_size])
            para = para[chunk_size:]
        if current_len + len(para) + 2 > chunk_size:
            flush()
        current.append(para)
        current_len += len(para) + 2
    flush()
    return chunks or ([""] if text else [])


def scan_vault(vault: Path, max_notes: int) -> list[Path]:
    """Return up to max_notes .md files inside the vault (stable order)."""
    if not vault.is_dir():
        raise FileNotFoundError(f"Vault directory not found: {vault}")
    files = sorted(vault.rglob("*.md"))
    # Skip hidden directories (e.g. .obsidian, .trash, .git)
    files = [f for f in files if not any(part.startswith(".") for part in f.relative_to(vault).parts)]
    return files[:max_notes]


def chunk_note(note_path: Path, vault: Path, chunk_size: int) -> list[Chunk]:
    """Parse a single markdown note into chunks."""
    try:
        raw = note_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        print(f"[obsidian-rag] skipped {note_path}: {exc}")
        return []

    rel = note_path.relative_to(vault).as_posix()
    title = note_path.stem

    chunks: list[Chunk] = []
    current_heading = ""
    current_section: list[str] = []

    def flush_section() -> None:
        nonlocal current_section
        if current_section:
            body = _clean_text("\n".join(current_section))
            for piece in _split_paragraphs(body, chunk_size):
                if piece.strip():
                    chunks.append(
                        Chunk(path=rel, title=title, heading=current_heading, text=piece)
                    )
            current_section = []

    for line in raw.splitlines():
        m = HEADING_RE.match(line.strip())
        if m:
            flush_section()
            current_heading = m.group(2).strip()
        else:
            current_section.append(line)
    flush_section()

    if not chunks:
        # No headings at all → whole note is one section
        body = _clean_text(raw)
        for piece in _split_paragraphs(body, chunk_size):
            if piece.strip():
                chunks.append(Chunk(path=rel, title=title, heading="", text=piece))

    return chunks
