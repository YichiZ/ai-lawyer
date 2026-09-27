import pytest

from evals.metrics import matches, mrr, recall_at_k, summarize
from evals.langfuse_io import DATASET, upsert_dataset

E = [{"slug": "city-of-toronto-act-2006", "pinpoint": "s-42-6"}]


@pytest.mark.parametrize(
    "hit, expected, ok",
    [
        (("city-of-toronto-act-2006", "s-42-6"), E, True),   # exact
        (("city-of-toronto-act-2006", "s-42"), E, True),     # hit is the whole section containing the subsection
        (("city-of-toronto-act-2006", "s-42-6-a"), E, True), # hit is inside the expected subsection
        (("city-of-toronto-act-2006", "s-4"), E, False),     # s-4 is not a parent of s-42-6
        (("city-of-toronto-act-2006", "s-42-7"), E, False),  # sibling subsection
        (("occupiers-liability-act", "s-42-6"), E, False),   # other law
    ],
)
def test_matches(hit, expected, ok):
    assert matches(hit, expected) is ok


def test_recall_and_mrr():
    ranked = [("negligence-act", "s-1"), ("city-of-toronto-act-2006", "s-42"), ("x", "y")]
    assert recall_at_k(ranked, E, k=8) == 1.0
    assert recall_at_k(ranked, E, k=1) == 0.0
    assert mrr(ranked, E) == pytest.approx(0.5)
    assert mrr([("x", "y")], E) == 0.0


def test_summarize_by_topic():
    rows = [{"topic": "a", "recall@8": 1.0, "mrr": 0.5}, {"topic": "a", "recall@8": 0.0, "mrr": 0.0},
            {"topic": "b", "recall@8": 1.0, "mrr": 1.0}]
    s = summarize(rows, ["recall@8", "mrr"])
    assert s["all"] == {"n": 3, "recall@8": pytest.approx(2 / 3), "mrr": pytest.approx(0.5)}
    assert s["a"]["recall@8"] == 0.5 and s["b"]["n"] == 1


class FakeLF:
    def __init__(self):
        self.datasets, self.items = [], {}

    def create_dataset(self, name, **kw):
        self.datasets.append(name)

    def create_dataset_item(self, dataset_name, input, expected_output, metadata, id):
        self.items[id] = (dataset_name, input, expected_output, metadata)


def test_upsert_dataset_is_keyed_by_gold_id():
    lf = FakeLF()
    gold = [{"id": "lim-01", "question": "q?", "topic": "limitations", "expected": E, "facts": ["f"], "must_refuse": False}]
    upsert_dataset(lf, gold)
    upsert_dataset(lf, gold)
    assert list(lf.items) == ["lim-01"]
    name, inp, exp, meta = lf.items["lim-01"]
    assert name == DATASET and inp == {"question": "q?"}
    assert exp == {"expected": E, "facts": ["f"], "must_refuse": False} and meta == {"topic": "limitations"}


def test_hit_covering_several_subsections_matches_any_of_them():
    dog = [{"slug": "dog-owners-liability-act", "pinpoint": "s-4-3"}]
    packed = ("dog-owners-liability-act", "s-4-1", ["s-4-1", "s-4-2", "s-4-3", "s-4-4"])  # chunk labelled by its first
    other = ("dog-owners-liability-act", "s-4-5", ["s-4-5", "s-4-6"])
    assert matches(packed, dog) and not matches(other, dog)
    assert recall_at_k([other, packed], dog, k=2) == 1.0 and mrr([other, packed], dog) == 0.5


def test_unverified_alternative_counts_as_a_hit():
    expected = [{"slug": "insurance-act", "pinpoint": "s-267.5-7"},
                {"slug": "reg", "pinpoint": "s-5.1", "verified": False, "note": "not lawyer-checked"}]
    ranked = [("reg", "s-5.1"), ("insurance-act", "s-267.5-7")]
    assert recall_at_k(ranked, expected) == 1.0 and mrr(ranked, expected) == 1.0


def test_chunk_covers_uses_subsections_not_the_parent(conn):
    from evals.metrics import chunk_covers
    from ingest.chunks import CHUNK_CHAR_LIMIT, load_sections
    from ingest.statutes import load_document, parse_law
    from test_statutes import LAW, row
    import json as _json

    long_subs = {f"({i})": f"({i}) " + ("word " * 200).strip() + "." for i in range(1, 7)}
    sections = {"4": "\n".join(long_subs.values()), "5": "Short section."}
    load_document(conn, parse_law(row(unofficial_sections_en=_json.dumps(sections)), LAW))
    doc_id = conn.execute("SELECT id FROM documents WHERE slug = 'test-act'").fetchone()[0]
    from ingest.chunks import plan_chunks, sync_chunks
    sync_chunks(conn, doc_id, plan_chunks("Test Act", load_sections(conn, doc_id)))
    covers = chunk_covers(conn, [cid for (cid,) in conn.execute("SELECT id FROM chunks WHERE document_id = %s ORDER BY id", (doc_id,))])
    pieces = list(covers.values())
    assert len(sections["4"]) > CHUNK_CHAR_LIMIT and len(pieces) >= 3  # s. 4 split into several chunks
    assert pieces[0][0] == "s-4-1" and "s-4" not in pieces[0]            # subsections, not the whole section
    assert pieces[-1] == ["s-5"]                                          # unsplit section covers itself
