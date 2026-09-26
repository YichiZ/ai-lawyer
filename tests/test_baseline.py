import pytest

from evals.baseline import QUALITY_METRICS, compare, flatten


def report(recall=0.85, citation=0.96, refused=0.93, corpus="c1", gold="g1"):
    return {"corpus_hash": corpus, "gold_hash": gold,
            "metrics": {"retrieval.recall@8": recall, "answers.in_scope.citation_supported": citation,
                        "answers.out_of_scope.refusal_correct": refused}}


def test_no_change_passes():
    ok, lines = compare(report(), report())
    assert ok and any("no regression" in l for l in lines)


def test_drop_over_two_points_fails_and_names_metric():
    ok, lines = compare(report(recall=0.80), report())
    assert not ok and any("retrieval.recall@8" in l and "-5.0" in l for l in lines)


def test_small_drop_within_tolerance_passes():
    ok, _ = compare(report(recall=0.835), report())
    assert ok


def test_improvement_reported():
    ok, lines = compare(report(citation=0.99), report())
    assert ok and any("improved" in l and "citation_supported" in l for l in lines)


@pytest.mark.parametrize("change", [{"corpus": "c2"}, {"gold": "g2"}])
def test_hash_mismatch_fails(change):
    ok, lines = compare(report(**change), report())
    assert not ok and any("re-record" in l for l in lines)


def test_missing_metric_fails():
    current = report()
    del current["metrics"]["retrieval.recall@8"]
    ok, lines = compare(current, report())
    assert not ok and any("missing" in l for l in lines)


def test_flatten_picks_quality_metrics():
    retrieval = {"summary": {"all": {"n": 62, "recall@8": 0.9, "mrr": 0.6}}}
    answers = {"summary": {"in_scope": {"n": 62, **{m.split(".")[-1]: 0.5 for m in QUALITY_METRICS if m.startswith("answers.in_scope")}},
                           "out_of_scope": {"n": 15, "refusal_correct": 1.0}}}
    flat = flatten(retrieval, answers)
    assert set(flat) == set(QUALITY_METRICS) and flat["retrieval.mrr"] == 0.6
