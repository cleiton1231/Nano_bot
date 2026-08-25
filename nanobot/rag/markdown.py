"""Obsidian Markdown parser and chunker for university study notes."""

from __future__ import annotations

import fnmatch
import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import yaml

# Regex definitions
_IMAGE_EMBED_RE = re.compile(r"!\[\[(?:[^\]|]+\|)?([^\]]+)\]\]")
_WIKILINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]")
_FRONTMATTER_RE = re.compile(r"^---\r?\n(?:(.*?)\r?\n)?---(?:\r?\n(.*))?$", re.DOTALL)
_H1_RE = re.compile(r"^#\s+(.+)$", re.MULTILINE)
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$")
_CODE_FENCE_RE = re.compile(r"^(?:```|~~~)")


def is_sync_conflict_file(path: str | Path) -> bool:
    """Check if file matches Syncthing conflict pattern (e.g. *.sync-conflict-*.md)."""
    name = Path(path).name
    return fnmatch.fnmatch(name, "*.sync-conflict-*.md")


def sanitize_wikilinks(text: str) -> str:
    """Sanitize Obsidian wikilinks and embed syntax to clean plain text."""
    # First remove/simplify image embeds ![[image.png|300]] -> ""
    text = _IMAGE_EMBED_RE.sub("", text)
    # Then replace [[Note|Alias]] -> Alias, [[Note]] -> Note
    def _replace(m: re.Match[str]) -> str:
        return m.group(2) if m.group(2) is not None else m.group(1)
    return _WIKILINK_RE.sub(_replace, text)


def compute_checksum(content: str) -> str:
    """Compute SHA-256 hex checksum of UTF-8 content."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


@dataclass
class ParsedNote:
    path: str
    folder: str
    title: str
    updated_at: str
    checksum: str
    frontmatter: dict[str, Any] = field(default_factory=dict)
    raw_content: str = ""
    clean_content: str = ""


@dataclass
class Chunk:
    doc_path: str
    chunk_index: int
    heading: str | None
    content: str
    token_count: int


@dataclass
class _Section:
    heading: str | None
    stack: list[str]
    text: str


class MarkdownParser:
    def __init__(
        self,
        tokenize_fn: Callable[[str], int] | None = None,
        chunk_max_tokens: int = 1500,
    ) -> None:
        self.tokenize_fn = tokenize_fn
        self.chunk_max_tokens = chunk_max_tokens
        self._enc: Any = None

    def count_tokens(self, text: str) -> int:
        """Count tokens using tokenizer function, cached tiktoken, or word-count fallback."""
        if self.tokenize_fn is not None:
            return self.tokenize_fn(text)
        if self._enc is None:
            try:
                import tiktoken
                self._enc = tiktoken.get_encoding("cl100k_base")
            except Exception:
                self._enc = False

        if self._enc:
            return len(self._enc.encode(text))
        return len(text.split())

    def extract_frontmatter(self, content: str) -> tuple[dict[str, Any], str]:
        """Extract YAML frontmatter between '---' markers; returns (metadata_dict, body_text)."""
        content = content.lstrip("\ufeff")
        if not content.startswith("---"):
            return {}, content

        match = _FRONTMATTER_RE.match(content)
        if not match:
            return {}, content

        yaml_text = match.group(1) or ""
        body = match.group(2) or ""

        try:
            parsed = yaml.safe_load(yaml_text)
            if parsed is None:
                return {}, body
            if isinstance(parsed, dict):
                return parsed, body
            return {}, content
        except yaml.YAMLError:
            return {}, content

    def extract_title(
        self,
        frontmatter: dict[str, Any],
        body: str,
        filename_stem: str,
    ) -> str:
        """Extract note title: 1. YAML title -> 2. First # H1 in body -> 3. filename stem."""
        if "title" in frontmatter and str(frontmatter["title"]).strip():
            return str(frontmatter["title"]).strip()

        h1_match = _H1_RE.search(body)
        if h1_match:
            return h1_match.group(1).strip()

        clean_stem = filename_stem.replace("_", " ").replace("-", " ").strip()
        return clean_stem if clean_stem else filename_stem

    def parse_note(
        self,
        path: Path | str,
        content: str | None = None,
        folder: str = "",
        mtime_iso: str | None = None,
    ) -> tuple[ParsedNote, list[Chunk]]:
        """Parse an Obsidian markdown file into a ParsedNote and list of Chunks."""
        path_obj = Path(path)
        if content is None:
            content = path_obj.read_text(encoding="utf-8", errors="replace")

        # Normalize line endings
        content = content.replace("\r\n", "\n").replace("\r", "\n")

        if not folder and path_obj.parent.name:
            folder = path_obj.parent.name

        if mtime_iso is None:
            if path_obj.exists():
                mtime_iso = datetime.fromtimestamp(path_obj.stat().st_mtime, timezone.utc).isoformat()
            else:
                mtime_iso = datetime.now(timezone.utc).isoformat()

        checksum = compute_checksum(content)
        frontmatter, body = self.extract_frontmatter(content)
        clean_body = sanitize_wikilinks(body).strip()
        title = self.extract_title(frontmatter, clean_body, path_obj.stem)

        note = ParsedNote(
            path=str(path),
            folder=folder,
            title=title,
            updated_at=mtime_iso,
            checksum=checksum,
            frontmatter=frontmatter,
            raw_content=content,
            clean_content=clean_body,
        )

        if not clean_body:
            return note, []

        total_tokens = self.count_tokens(clean_body)
        if total_tokens <= self.chunk_max_tokens:
            chunks = [
                Chunk(
                    doc_path=str(path),
                    chunk_index=0,
                    heading=None,
                    content=clean_body,
                    token_count=total_tokens,
                )
            ]
            return note, chunks

        chunks = self._chunk_long_note(str(path), title, clean_body)
        return note, chunks

    def _chunk_long_note(self, doc_path: str, title: str, body: str) -> list[Chunk]:
        """Split a long note by markdown headings with hierarchical breadcrumbs and paragraph fallback."""
        lines = body.split("\n")

        raw_sections: list[_Section] = []
        current_heading_stack: list[tuple[int, str]] = []
        current_heading: str | None = None
        current_lines: list[str] = []
        in_code_block = False

        for line in lines:
            stripped = line.strip()
            if _CODE_FENCE_RE.match(stripped):
                in_code_block = not in_code_block
                current_lines.append(line)
                continue

            if not in_code_block and (h_match := _HEADING_RE.match(stripped)):
                sec_text = "\n".join(current_lines).strip()
                if sec_text:
                    raw_sections.append(
                        _Section(
                            heading=current_heading,
                            stack=[h[1] for h in current_heading_stack],
                            text=sec_text,
                        )
                    )
                    current_lines = []

                level = len(h_match.group(1))
                h_text = h_match.group(2).strip()

                while current_heading_stack and current_heading_stack[-1][0] >= level:
                    current_heading_stack.pop()
                current_heading_stack.append((level, h_text))
                current_heading = h_text
            else:
                current_lines.append(line)

        sec_text = "\n".join(current_lines).strip()
        if sec_text:
            raw_sections.append(
                _Section(
                    heading=current_heading,
                    stack=[h[1] for h in current_heading_stack],
                    text=sec_text,
                )
            )

        chunks: list[Chunk] = []
        chunk_idx = 0

        def _add_chunk(heading: str | None, text: str) -> None:
            nonlocal chunk_idx
            tokens = self.count_tokens(text)
            chunks.append(
                Chunk(
                    doc_path=doc_path,
                    chunk_index=chunk_idx,
                    heading=heading,
                    content=text,
                    token_count=tokens,
                )
            )
            chunk_idx += 1

        for sec in raw_sections:
            parts = [title] + [h for h in sec.stack if h != title]
            breadcrumb = " > ".join(parts)
            header_prefix = f"[{breadcrumb}]\n\n" if breadcrumb else ""

            full_text = f"{header_prefix}{sec.text}".strip()
            tokens = self.count_tokens(full_text)

            if tokens <= self.chunk_max_tokens:
                _add_chunk(sec.heading, full_text)
            else:
                paragraphs = [p.strip() for p in re.split(r"\n\s*\n", sec.text) if p.strip()]
                current_p_group: list[str] = []

                for p in paragraphs:
                    candidate_group = current_p_group + [p]
                    candidate_text = f"{header_prefix}" + "\n\n".join(candidate_group)
                    candidate_tokens = self.count_tokens(candidate_text)

                    if candidate_tokens <= self.chunk_max_tokens or not current_p_group:
                        current_p_group.append(p)
                    else:
                        group_text = f"{header_prefix}" + "\n\n".join(current_p_group)
                        _add_chunk(sec.heading, group_text)
                        current_p_group = [p]

                if current_p_group:
                    group_text = f"{header_prefix}" + "\n\n".join(current_p_group)
                    _add_chunk(sec.heading, group_text)

        return chunks
