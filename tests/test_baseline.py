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
    ok, lines = compare(report(recall=0.90), report())
    assert ok and any("improved" in l and "recall@8" in l for l in lines)


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


def test_judge_tolerance_is_two_sd_of_the_difference_of_means():
    from evals.baseline import tolerance
    assert tolerance("answers.in_scope.faithful", 1, 3) == pytest.approx(0.067, abs=5e-4)  # gate 1 run vs record of 3
    assert tolerance("answers.in_scope.faithful", 3, 3) < tolerance("answers.in_scope.faithful", 1, 1)
    assert tolerance("retrieval.mrr", 1, 3) == 0.02  # code metrics keep 2 points
    assert tolerance("summaries.faithful", 50, 50) == 0.02  # never tighter than 2 points


def test_judge_metric_tolerance_depends_on_run_counts():
    base = {**report(citation=0.96), "n_runs": 3}
    assert compare(report(citation=0.925), base)[0]  # -3.5 points: inside 2 sd (3.7)
    ok, lines = compare(report(citation=0.92), base)  # -4 points: outside
    assert not ok and any("tolerance 3.7" in l for l in lines)


def test_average_is_per_metric_mean():
    from evals.baseline import average
    assert average([{"a": 0.9, "b": 1.0}, {"a": 0.8, "b": 1.0}, {"a": 1.0, "b": 0.7}]) == {"a": 0.9, "b": 0.9}


def rec(faithful, mrr=0.9, n=3):
    return {"n_runs": n, "corpus_hash": "c", "metrics": {"answers.in_scope.faithful": faithful, "retrieval.mrr": mrr}}


def test_record_keeps_old_judge_value_within_noise():
    from evals.baseline import merge_record
    ok, out, lines = merge_record(rec(0.90, mrr=0.95), rec(0.93))  # -3 points, noise is ±4.7 for 3 vs 3 runs
    assert ok and out["metrics"] == {"answers.in_scope.faithful": 0.93, "retrieval.mrr": 0.95}
    assert any(l.startswith("kept answers.in_scope.faithful") for l in lines)
    assert merge_record(rec(0.96), rec(0.93))[1]["metrics"]["answers.in_scope.faithful"] == 0.93  # no ratchet up either


def test_record_refuses_a_drop_beyond_noise_unless_accepted():
    from evals.baseline import merge_record
    ok, _, lines = merge_record(rec(0.85), rec(0.93))
    assert not ok and any("REFUSED" in l and "--accept-drop" in l for l in lines)
    ok, out, _ = merge_record(rec(0.85), rec(0.93), accept_drop=True)
    assert ok and out["metrics"]["answers.in_scope.faithful"] == 0.85


def test_record_raises_beyond_noise_and_records_first_baseline():
    from evals.baseline import merge_record
    assert merge_record(rec(0.99), rec(0.90))[1]["metrics"]["answers.in_scope.faithful"] == 0.99
    assert merge_record(rec(0.80), None)[1] == rec(0.80)


def test_single_run_old_baseline_counts_as_one_run():
    from evals.baseline import merge_record
    old = rec(0.944)
    del old["n_runs"]
    ok, out, _ = merge_record(rec(0.90), old)  # -4.4 points, noise 2*0.029*sqrt(1/3+1) = 6.7
    assert ok and out["metrics"]["answers.in_scope.faithful"] == 0.944


def test_flatten_adds_summary_metrics_when_given():
    from evals.baseline import SUMMARY_METRICS
    retrieval = {"summary": {"all": {"n": 62, "recall@8": 0.9, "mrr": 0.6}}}
    answers = {"summary": {"in_scope": {"n": 62, **{m.split(".")[-1]: 0.5 for m in QUALITY_METRICS if m.startswith("answers.in_scope")}},
                           "out_of_scope": {"n": 15, "refusal_correct": 1.0}}}
    summaries = {"summary": {"faithful": 0.96, "no_advice": 1.0, "grade_le_10": 0.8}}
    flat = flatten(retrieval, answers, summaries)
    assert set(SUMMARY_METRICS) <= set(flat) and flat["summaries.faithful"] == 0.96


def test_excerpt_report_is_per_run_and_tolerates_old_runs():
    from evals.baseline import excerpt_report

    run = lambda v: ({}, {"summary": {"in_scope": {} if v is None else {"excerpt_dropped": v}}}, None)
    assert excerpt_report([run(0.139), run(None)]) == "report excerpt_dropped per answer (not gated): 0.139 / n/a"
