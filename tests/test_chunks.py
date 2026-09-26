import threading

import pytest

from ingest.chunks import CHUNK_CHAR_LIMIT, embed_pending, plan_chunks, sync_chunks


def sec(id, pinpoint, text, kind="section", parent=None, heading=None):
    return {"id": id, "pinpoint": pinpoint, "kind": kind, "heading": heading, "text": text, "parent": parent}


def long_section():
    subs = [f"({i}) " + ("word " * 180).strip() + "." for i in range(1, 9)]  # ~900 chars each
    text = "\n".join(subs)
    rows = [sec(10, "s-15", text, heading="Ultimate limitation periods")]
    rows += [sec(11 + i, f"s-15-{i + 1}", t, kind="subsection", parent="s-15") for i, t in enumerate(subs)]
    return rows, text


def test_short_section_is_one_chunk():
    [c] = plan_chunks("Limitations Act, 2002", [sec(1, "s-4", "Unless this Act provides otherwise...", heading="Basic limitation period")])
    assert c["text"] == "Unless this Act provides otherwise..."
    assert c["section_ids"] == [1] and c["pinpoint"] == "s-4"
    assert c["context"] == "Limitations Act, 2002 — s. 4 — Basic limitation period"
    assert len(c["text_sha256"]) == 64


def test_long_section_splits_on_subsections():
    rows, text = long_section()
    chunks = plan_chunks("Limitations Act, 2002", rows)
    assert len(chunks) > 1
    assert all(len(c["text"]) <= CHUNK_CHAR_LIMIT for c in chunks)
    assert "\n".join(c["text"] for c in chunks) == text  # nothing lost, nothing added
    assert all(c["text"] in text for c in chunks)  # quotes verify against section text
    assert chunks[0]["pinpoint"] == "s-15-1" and chunks[0]["section_ids"][0] == 10
    assert all(c["text"].startswith("(") for c in chunks)  # every split starts at a subsection


def test_parts_and_blank_sections_get_no_chunk():
    rows = [sec(1, "part-i", "", kind="part", heading="PART I"), sec(2, "s-26", "[blank]"), sec(3, "s-4", "Real text.")]
    assert [c["pinpoint"] for c in plan_chunks("Act", rows)] == ["s-4"]


def test_oversized_section_without_subsections_splits_on_lines():
    lines = [("clause text " * 60).strip() for _ in range(8)]  # ~720 chars per line
    text = "\n".join(lines)
    chunks = plan_chunks("Act", [sec(1, "s-9", text)])
    assert len(chunks) > 1 and "\n".join(c["text"] for c in chunks) == text


def test_hash_depends_on_context_and_text():
    a = plan_chunks("Act", [sec(1, "s-4", "Text.", heading="H")])[0]["text_sha256"]
    b = plan_chunks("Act", [sec(1, "s-4", "Text.", heading="Other")])[0]["text_sha256"]
    c = plan_chunks("Act", [sec(1, "s-4", "Text!", heading="H")])[0]["text_sha256"]
    assert len({a, b, c}) == 3


# --- database: sync + embed ---

def make_document(conn):
    doc = conn.execute(
        "INSERT INTO documents (sha256, kind, slug, title, source) VALUES (%s, 'statute', 'act', 'Act', 'test') RETURNING id",
        ("f" * 64,),
    ).fetchone()[0]
    return doc


def fake_embed(calls):
    lock = threading.Lock()

    def embed(text):
        with lock:
            calls.append(text)
        return [0.01] * 1536

    return embed


def test_sync_then_embed_then_rerun_is_free(conn):
    doc = make_document(conn)
    planned = plan_chunks("Act", [sec(1, "s-1", "One."), sec(2, "s-2", "Two.")])
    assert sync_chunks(conn, doc, planned) == ("replaced", 0)
    calls = []
    assert embed_pending(conn, fake_embed(calls), model="m", workers=2) == 2
    assert sync_chunks(conn, doc, planned) == ("unchanged", 0)
    assert embed_pending(conn, fake_embed(calls), model="m", workers=2) == 0
    assert len(calls) == 2
    assert conn.execute("SELECT count(*) FROM chunks WHERE embedding IS NULL").fetchone()[0] == 0


def test_changed_section_reuses_other_embeddings(conn):
    doc = make_document(conn)
    sync_chunks(conn, doc, plan_chunks("Act", [sec(1, "s-1", "One."), sec(2, "s-2", "Two.")]))
    embed_pending(conn, fake_embed([]), model="m", workers=1)
    assert sync_chunks(conn, doc, plan_chunks("Act", [sec(1, "s-1", "One."), sec(2, "s-2", "Two changed.")])) == ("replaced", 1)
    calls = []
    assert embed_pending(conn, fake_embed(calls), model="m", workers=1) == 1
    assert "Two changed." in calls[0]


def test_failed_embedding_run_resumes(conn):
    doc = make_document(conn)
    sync_chunks(conn, doc, plan_chunks("Act", [sec(i, f"s-{i}", f"Text {i}.") for i in range(1, 6)]))
    seen = []

    def flaky(text):
        seen.append(text)
        if len(seen) == 3:
            raise RuntimeError("Vertex 503")
        return [0.02] * 1536

    with pytest.raises(RuntimeError):
        embed_pending(conn, flaky, model="m", workers=1)
    done = conn.execute("SELECT count(*) FROM chunks WHERE embedding IS NOT NULL").fetchone()[0]
    assert done == 2
    calls = []
    assert embed_pending(conn, fake_embed(calls), model="m", workers=1) == 3
    assert len(calls) == 3


def test_model_change_forces_reembed(conn):
    doc = make_document(conn)
    sync_chunks(conn, doc, plan_chunks("Act", [sec(1, "s-1", "One.")]))
    embed_pending(conn, fake_embed([]), model="old-model", workers=1)
    calls = []
    assert embed_pending(conn, fake_embed(calls), model="new-model", workers=1) == 1
