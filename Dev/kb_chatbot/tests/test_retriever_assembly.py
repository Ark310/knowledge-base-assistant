import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from Dev.kb_chatbot.retriever import assemble_ticket
from Dev.kb_chatbot.chunker import Chunk


def _tc(idx, body, **md):
    text = "Ticket #75919 — GetWebDeal missing buy amount"
    if idx == 0:
        text += "\nClient: Acme · CSQA owner: p.shah"
    text += f"\n\n{body}"
    meta = {"kind": "ticket", "ticket_id": "75919", "title": "Ticket #75919",
            "url": "https://support.contoso.example/edit_bug.aspx?id=75919",
            "chunk_index": idx, "has_images": False}
    meta.update(md)
    return Chunk(id=f"ticket_h:{idx}", text=text, metadata=meta)


def test_assemble_orders_by_chunk_index_and_dedupes_title():
    # deliberately out of order
    chunks = [_tc(2, "step three end"), _tc(0, "Problem: buy amount null"),
              _tc(1, "Resolution: updated the value")]
    full = assemble_ticket(chunks)
    # header from chunk 0 present exactly once
    assert full.text.count("Client: Acme") == 1
    # title line appears once, not three times
    assert full.text.count("Ticket #75919 — GetWebDeal missing buy amount") == 1
    # all three bodies present in order
    i0 = full.text.index("buy amount null")
    i1 = full.text.index("updated the value")
    i2 = full.text.index("step three end")
    assert i0 < i1 < i2
    assert full.metadata["ticket_id"] == "75919"
    assert full.metadata["chunk_index"] == 0


def test_assemble_single_chunk_returns_equivalent():
    [only] = [_tc(0, "Problem: p\n\nResolution: r")]
    full = assemble_ticket([only])
    assert "Problem: p" in full.text and "Resolution: r" in full.text
    assert full.metadata["ticket_id"] == "75919"


def test_assemble_preserves_has_images_flag():
    chunks = [_tc(0, "Problem: p", has_images=True), _tc(1, "Resolution: r", has_images=True)]
    full = assemble_ticket(chunks)
    assert full.metadata["has_images"] is True
