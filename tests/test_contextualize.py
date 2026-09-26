from ingest.chunks import embed_input, embed_pending, plan_chunks, sync_chunks
from ingest.contextualize import MAX_OUTLINE_LINES, build_prompt, contextualize_pending, part_outline


SECTIONS = [
    {"id": 1, "pinpoint": "part-i", "kind": "part", "heading": "PART I LIMITATION PERIODS", "text": "", "parent": None},
    {"id": 2, "pinpoint": "s-4", "kind": "section", "heading": "Basic limitation period", "text": "Two years.", "parent": "part-i"},
    {"id": 3, "pinpoint": "s-5", "kind": "section", "heading": "Discovery", "text": "Discovered when...", "parent": "part-i"},
    {"id": 4, "pinpoint": "part-ii", "kind": "part", "heading": "PART II OTHER", "text": "", "parent": None},
    {"id": 5, "pinpoint": "s-9", "kind": "section", "heading": "Elsewhere", "text": "Other.", "parent": "part-ii"},
]


def test_part_outline_lists_sections_in_the_same_part_only():
    outline = part_outline(SECTIONS, "s-4")
    assert "PART I LIMITATION PERIODS" in outline and "s. 5 Discovery" in outline and "Elsewhere" not in outline


def test_part_outline_is_capped():
    many = [{"id": i, "pinpoint": f"s-{i}", "kind": "section", "heading": f"H{i}", "text": "x", "parent": None}
            for i in range(1, 200)]
    assert len(part_outline(many, "s-1").splitlines()) <= MAX_OUTLINE_LINES + 1


def test_prompt_contains_title_outline_and_chunk():
    p = build_prompt("Limitations Act, 2002", "s. 4", part_outline(SECTIONS, "s-4"), "Two years.")
    assert "Limitations Act, 2002" in p and "s. 5 Discovery" in p and "Two years." in p


def test_embed_input_includes_situating_text():
    assert embed_input("Act — s. 4", "Two years.", "It sets the basic period.") == "Act — s. 4\nIt sets the basic period.\n\nTwo years."
    assert embed_input("Act — s. 4", "Two years.") == "Act — s. 4\n\nTwo years."


def make_doc(conn):
    return conn.execute("INSERT INTO documents (sha256, kind, slug, title, source) VALUES ('s', 'statute', 'a', 'Act', 't') RETURNING id").fetchone()[0]


def test_contextualize_invalidates_embedding_and_is_idempotent(conn):
    doc = make_doc(conn)
    rows = [{"id": 10, "pinpoint": "s-4", "kind": "section", "heading": "Basic", "text": "Two years.", "parent": None}]
    sync_chunks(conn, doc, plan_chunks("Act", rows))
    embed_pending(conn, lambda t: [0.01] * 1536, model="m", workers=1)
    calls = []
    n = contextualize_pending(conn, lambda prompt: calls.append(prompt) or "It sets the basic two-year period.", workers=1)
    assert n == 1 and conn.execute("SELECT situating, embedding IS NULL FROM chunks").fetchone() == ("It sets the basic two-year period.", True)
    assert contextualize_pending(conn, lambda p: "x", workers=1) == 0  # already situated
    embedded = []
    embed_pending(conn, lambda t: embedded.append(t) or [0.02] * 1536, model="m", workers=1)
    assert "It sets the basic two-year period." in embedded[0]


def test_unchanged_chunk_keeps_situating_through_sync(conn):
    doc = make_doc(conn)
    rows = [{"id": 10, "pinpoint": "s-4", "kind": "section", "heading": "Basic", "text": "Two years.", "parent": None},
            {"id": 11, "pinpoint": "s-5", "kind": "section", "heading": "Other", "text": "Old.", "parent": None}]
    sync_chunks(conn, doc, plan_chunks("Act", rows))
    contextualize_pending(conn, lambda p: "Situated.", workers=1)
    rows[1]["text"] = "New."
    sync_chunks(conn, doc, plan_chunks("Act", rows))
    got = dict(conn.execute("SELECT pinpoint, situating FROM chunks").fetchall())
    assert got == {"s-4": "Situated.", "s-5": None}
