from evals.summaries import judge_summary, summarize_scores


def test_judge_summary_parses_verdict():
    seen = {}

    def fake(prompt, schema):
        seen["prompt"] = prompt
        return {"faithful": False, "unsupported": ["says 3 years"], "gives_advice": False, "reason": "wrong period"}

    v = judge_summary("Official: two years.", "You have three years.", fake)
    assert v == {"faithful": 0.0, "no_advice": 1.0, "unsupported": ["says 3 years"], "reason": "wrong period", "error": None}
    assert "Official: two years." in seen["prompt"] and "You have three years." in seen["prompt"]


def test_judge_summary_malformed():
    v = judge_summary("t", "s", lambda p, s: {"oops": 1})
    assert v["error"] == "judge_error" and v["faithful"] is None


def test_summarize_scores():
    rows = [{"faithful": 1.0, "no_advice": 1.0, "grade": 8.0}, {"faithful": 0.0, "no_advice": 1.0, "grade": 12.0},
            {"faithful": None, "no_advice": None, "grade": 9.0}]
    s = summarize_scores(rows)
    assert s == {"n": 3, "faithful": 0.5, "no_advice": 1.0, "mean_grade": 9.7, "grade_le_10": 0.667, "judge_errors": 1}
