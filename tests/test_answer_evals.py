import pytest

from evals.answers import JUDGE_MODEL, facts_covered, gate_tradeoff, judge_answer, refusal_correct, verified_rate
from ingest.vertex import ANSWER_MODEL


def test_judge_is_not_the_answer_model():
    assert JUDGE_MODEL != ANSWER_MODEL


def test_facts_covered_is_normalized():
    text = "Notice goes to the City  Clerk within 10\ndays."
    assert facts_covered(text, ["city clerk", "10 days"]) == 1.0
    assert facts_covered(text, ["city clerk", "60 days"]) == 0.5
    assert facts_covered(text, []) is None


@pytest.mark.parametrize(
    "status, must_refuse, ok",
    [("drafted", False, True), ("out_of_scope", False, False), ("not_found", True, True),
     ("out_of_scope", True, True), ("drafted", True, False), ("unverified", True, False), ("unverified", False, False)],
)
def test_refusal_correct(status, must_refuse, ok):
    assert refusal_correct(status, must_refuse) is ok


def test_verified_rate():
    assert verified_rate(3, 1) == 0.75
    assert verified_rate(0, 0) is None


def test_gate_tradeoff():
    rows = gate_tradeoff(in_scope=[0.1, 0.2, 0.3], out_of_scope=[0.25, 0.4], thresholds=[0.22, 0.35])
    assert rows == [{"threshold": 0.22, "oos_refused": 2, "in_scope_refused": 1},
                    {"threshold": 0.35, "oos_refused": 1, "in_scope_refused": 0}]


CLAIMS = [{"text": "Notice within 10 days.", "quote": "within 10 days after the occurrence of the injury"},
          {"text": "Notice within 30 days.", "quote": "within 10 days after the occurrence of the injury"}]


def test_judge_answer_scores():
    def fake(prompt, schema):
        assert "within 10 days" in prompt and "Notice within 30 days." in prompt
        return {"claims": [{"index": 0, "supported": True, "reason": "ok"}, {"index": 1, "supported": False, "reason": "30 vs 10"}],
                "faithful": False, "gives_advice": False, "reason": "claim 2 wrong"}
    verdict = judge_answer("Notice within 10 days.", CLAIMS, fake)
    assert verdict["citation_supported"] == 0.5 and verdict["faithful"] == 0.0 and verdict["no_advice"] == 1.0
    assert verdict["error"] is None


def test_judge_malformed_output_is_recorded_not_dropped():
    verdict = judge_answer("x", CLAIMS, lambda p, s: {"nonsense": True})
    assert verdict["error"] == "judge_error" and verdict["citation_supported"] is None


def test_judge_skips_answers_without_claims():
    verdict = judge_answer("Refused.", [], lambda p, s: pytest.fail("should not call the judge"))
    assert verdict["citation_supported"] is None and verdict["error"] is None
