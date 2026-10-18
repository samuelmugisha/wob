"""Split extracted blocks into retrieval chunks (spec §5.2).

Chunks aim for `target_tokens` and never exceed `max_tokens`. They:
- carry their heading path ("Section: Board roles › Current") so a passage keeps its context,
- start afresh at each heading (very short sections are merged forward),
- never split a table unless it alone is too large, in which case every piece repeats the
  header row,
- overlap by about `overlap_tokens` when a run of prose is split purely for size.
"""

import re
from dataclasses import dataclass, field
from functools import lru_cache

from app.services.extraction.base import Block, render_row

CHUNKER_VERSION = "chunk-v1"
TOKENIZER = "cl100k_base"
# A heading starts a new chunk unless less than this much content is pending, so each chunk's
# section label matches its text; tinier sections are merged into the next chunk.
MIN_SECTION_TOKENS = 150
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


@lru_cache
def _encoding():
    import tiktoken

    return tiktoken.get_encoding(TOKENIZER)


def count_tokens(text: str) -> int:
    return len(_encoding().encode(text, disallowed_special=()))


def _token_slices(text: str, size: int) -> list[str]:
    tokens = _encoding().encode(text, disallowed_special=())
    return [_encoding().decode(tokens[i : i + size]) for i in range(0, len(tokens), size)]


def _tail(text: str, tokens: int) -> str:
    """Roughly the last `tokens` tokens of text, starting at a word boundary."""
    encoded = _encoding().encode(text, disallowed_special=())
    if len(encoded) <= tokens:
        return text
    tail = _encoding().decode(encoded[-tokens:])
    space = tail.find(" ")
    return tail[space + 1 :] if 0 <= space < len(tail) - 1 else tail


@dataclass
class Chunk:
    index: int
    content: str
    section: str | None
    page_start: int | None
    page_end: int | None
    token_count: int
    overlap_tokens: int
    has_table: bool

    @property
    def metadata(self) -> dict:
        return {
            "page_end": self.page_end,
            "overlap_tokens": self.overlap_tokens,
            "has_table": self.has_table,
            "tokenizer": TOKENIZER,
            "chunker_version": CHUNKER_VERSION,
        }


@dataclass
class _Unit:
    text: str
    tokens: int
    page: int | None
    kind: str  # heading | paragraph | table


@dataclass
class _Builder:
    target_tokens: int
    max_tokens: int
    overlap_tokens: int
    chunks: list[Chunk] = field(default_factory=list)
    path: list[tuple[int, str]] = field(default_factory=list)
    units: list[_Unit] = field(default_factory=list)
    section: str | None = None
    overlap: str = ""

    @property
    def label(self) -> str | None:
        return " › ".join(text for _, text in self.path) or None

    @property
    def has_content(self) -> bool:
        return any(u.kind != "heading" for u in self.units)

    @property
    def tokens(self) -> int:
        """Tokens the chunk would have if flushed now, including section line and overlap."""
        total = sum(u.tokens for u in self.units)
        if self.overlap:
            total += count_tokens(self.overlap)
        if self.section:
            total += count_tokens(f"Section: {self.section}")
        return total

    def heading(self, block: Block) -> None:
        if self.has_content and self.tokens >= MIN_SECTION_TOKENS:
            self.flush(carry_overlap=False)
        while self.path and self.path[-1][0] >= block.level:
            self.path.pop()
        self.path.append((block.level, block.text))
        if not self.has_content:
            self.section = self.label
        self.units.append(_Unit(block.text, count_tokens(block.text), block.page, "heading"))

    def add(self, text: str, page: int | None, kind: str) -> None:
        tokens = count_tokens(text)
        if self.has_content and (
            self.tokens + tokens > self.max_tokens or self.tokens >= self.target_tokens
        ):
            last = next((u for u in reversed(self.units) if u.kind != "heading"), None)
            follows_prose = last is not None and last.kind == "paragraph"
            self.flush(carry_overlap=kind == "paragraph" and follows_prose)
        self.units.append(_Unit(text, tokens, page, kind))

    def flush(self, carry_overlap: bool) -> None:
        if not self.has_content:
            return
        # Headings at the end belong to the next chunk's content.
        trailing: list[_Unit] = []
        while self.units[-1].kind == "heading":
            trailing.insert(0, self.units.pop())
        if trailing:
            carry_overlap = False  # never carry prose from one section into the next
        parts = [f"Section: {self.section}"] if self.section else []
        if self.overlap:
            parts.append(self.overlap)
        parts.extend(u.text for u in self.units)
        content = "\n\n".join(parts)
        pages = [u.page for u in self.units if u.page is not None]
        self.chunks.append(
            Chunk(
                index=len(self.chunks),
                content=content,
                section=self.section,
                page_start=min(pages) if pages else None,
                page_end=max(pages) if pages else None,
                token_count=count_tokens(content),
                overlap_tokens=count_tokens(self.overlap) if self.overlap else 0,
                has_table=any(u.kind == "table" for u in self.units),
            )
        )
        prose = [u.text for u in self.units if u.kind == "paragraph"]
        self.overlap = _tail(prose[-1], self.overlap_tokens) if carry_overlap and prose else ""
        self.units = trailing
        self.section = self.label


def _split_text(text: str, max_tokens: int) -> list[str]:
    if count_tokens(text) <= max_tokens:
        return [text]
    pieces: list[str] = []
    current: list[str] = []
    current_tokens = 0
    for sentence in _SENTENCE_END.split(text):
        tokens = count_tokens(sentence)
        if tokens > max_tokens:
            if current:
                pieces.append(" ".join(current))
                current, current_tokens = [], 0
            pieces.extend(_token_slices(sentence, max_tokens))
            continue
        if current and current_tokens + tokens + 1 > max_tokens:
            pieces.append(" ".join(current))
            current, current_tokens = [], 0
        current.append(sentence)
        current_tokens += tokens + 1
    if current:
        pieces.append(" ".join(current))
    return pieces


def _split_table(block: Block, max_tokens: int) -> list[str]:
    rendered = block.render()
    if count_tokens(rendered) <= max_tokens:
        return [rendered]
    if len(block.rows) < 2:
        return _split_text(rendered, max_tokens)
    header = render_row(block.rows[0])
    budget = max_tokens - count_tokens(header) - 1
    pieces: list[str] = []
    current: list[str] = []
    current_tokens = 0
    for row in block.rows[1:]:
        line = render_row(row)
        tokens = count_tokens(line) + 1
        if tokens > budget:
            if current:
                pieces.append("\n".join([header, *current]))
                current, current_tokens = [], 0
            pieces.extend(f"{header}\n{part}" for part in _split_text(line, budget))
            continue
        if current and current_tokens + tokens > budget:
            pieces.append("\n".join([header, *current]))
            current, current_tokens = [], 0
        current.append(line)
        current_tokens += tokens
    if current:
        pieces.append("\n".join([header, *current]))
    return pieces


def chunk_blocks(
    blocks: list[Block],
    *,
    target_tokens: int = 700,
    max_tokens: int = 900,
    overlap_tokens: int = 100,
) -> list[Chunk]:
    builder = _Builder(target_tokens, max_tokens, overlap_tokens)
    # Leave room for the section line and overlap that may precede a unit in its chunk.
    unit_budget = max_tokens - overlap_tokens - 40
    for block in blocks:
        if block.kind == "heading":
            builder.heading(block)
        elif block.kind == "table":
            for piece in _split_table(block, unit_budget):
                builder.add(piece, block.page, "table")
        else:
            for piece in _split_text(block.text, unit_budget):
                builder.add(piece, block.page, "paragraph")
    builder.flush(carry_overlap=False)
    return builder.chunks
