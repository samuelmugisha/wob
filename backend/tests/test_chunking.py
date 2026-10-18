from app.services.chunking import chunk_blocks, count_tokens
from app.services.extraction.base import Block

PARAGRAPH = (
    "She chaired the audit and risk committee, led the board through a capital raise and "
    "introduced a skills matrix for director appointments. "
) * 8


def prose(pages: range) -> list[Block]:
    return [Block("paragraph", PARAGRAPH.strip(), page=p) for p in pages]


def test_chunks_respect_token_limits_and_overlap() -> None:
    chunks = chunk_blocks(prose(range(1, 30)), target_tokens=700, max_tokens=900)
    assert len(chunks) > 3
    assert all(c.token_count <= 900 for c in chunks)
    assert all(c.token_count >= 300 for c in chunks[:-1])
    # Size-driven splits of prose carry ~100 tokens of the previous chunk forward.
    assert all(80 <= c.overlap_tokens <= 110 for c in chunks[1:])
    assert [c.index for c in chunks] == list(range(len(chunks)))


def test_sections_follow_heading_hierarchy() -> None:
    blocks = [
        Block("heading", "Nomination", level=1),
        Block("heading", "Board roles", level=2),
        *prose(range(1, 6)),
        Block("heading", "Community impact", level=2),
        *prose(range(6, 11)),
    ]
    chunks = chunk_blocks(blocks)
    sections = [c.section for c in chunks]
    assert sections[0] == "Nomination › Board roles"
    assert sections[-1] == "Nomination › Community impact"
    first_impact = sections.index("Nomination › Community impact")
    assert chunks[first_impact].content.startswith("Section: Nomination › Community impact")
    assert "Community impact" in chunks[first_impact].content
    # A new section starts a fresh chunk, without overlap from the previous section.
    assert chunks[first_impact].overlap_tokens == 0


def test_small_tables_are_never_split() -> None:
    table = Block.table([["Year", "Board", "Role"]] + [["2021", "Acme", "Chair"]] * 20, page=3)
    chunks = chunk_blocks([*prose(range(1, 3)), table, *prose(range(4, 6))])
    containing = [c for c in chunks if "| Year | Board | Role |" in c.content]
    assert len(containing) == 1
    assert containing[0].content.count("| 2021 | Acme | Chair |") == 20
    assert containing[0].has_table


def test_large_tables_repeat_their_header() -> None:
    rows = [["Year", "Organisation", "Position"]] + [
        [str(1990 + i), f"Organisation number {i}", "Non-executive director"] for i in range(400)
    ]
    chunks = chunk_blocks([Block.table(rows, page=1)])
    assert len(chunks) > 1
    assert all(c.content.split("\n\n")[0].startswith("| Year |") for c in chunks)
    assert all(c.token_count <= 900 for c in chunks)
    body = "\n".join(c.content for c in chunks)
    assert all(f"| {1990 + i} |" in body for i in range(400))


def test_oversized_paragraph_is_split_by_sentence() -> None:
    giant = Block("paragraph", " ".join(f"Sentence number {i} is here." for i in range(800)))
    chunks = chunk_blocks([giant])
    assert all(c.token_count <= 900 for c in chunks)
    assert "Sentence number 0 is here." in chunks[0].content
    assert "Sentence number 799 is here." in chunks[-1].content


def test_page_range_is_recorded() -> None:
    chunks = chunk_blocks(prose(range(1, 30)))
    assert chunks[0].page_start == 1
    assert all(c.page_start <= c.page_end for c in chunks)
    assert chunks[-1].page_end == 29


def test_headings_alone_produce_no_chunk() -> None:
    assert chunk_blocks([Block("heading", "Empty section")]) == []
    assert count_tokens("hello world") == 2
