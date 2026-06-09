import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from Dev.kb_chatbot.chunker import _split_body_md

# Create text with paragraph breaks so it splits into multiple chunks
paragraphs = []
for p in range(10):
    paragraphs.append(" ".join(f"p{p}w{i}" for i in range(60)))

LONG = "# Title\n\n" + "\n\n".join(paragraphs)


def test_zero_overlap_is_default_and_unchanged():
    assert _split_body_md(LONG) == _split_body_md(LONG, overlap_words=0)


def test_overlap_prepends_tail_of_previous_chunk():
    chunks = _split_body_md(LONG, target_words=100, overlap_words=30)
    assert len(chunks) >= 2
    prev_tail = " ".join(chunks[0].split()[-30:])
    assert chunks[1].startswith("[…] ")
    # After "[…] ", the next 30 words should be the tail from chunk 0
    overlap_section = " ".join(chunks[1].split()[1:31])
    assert overlap_section == prev_tail


def test_single_chunk_documents_get_no_overlap_marker():
    chunks = _split_body_md("# T\n\nshort body.", overlap_words=50)
    assert len(chunks) == 1 and "[…]" not in chunks[0]
