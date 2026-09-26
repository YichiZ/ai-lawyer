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
