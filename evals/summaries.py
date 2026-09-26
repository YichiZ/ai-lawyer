"""Summary evals (Phase 4.2): LLM-judge faithfulness vs the official text + code-scored reading grade."""
from statistics import mean
from typing import Callable

from evals.metrics import mean_of

SCHEMA = {
    "type": "object",
    "properties": {"faithful": {"type": "boolean"}, "unsupported": {"type": "array", "items": {"type": "string"}},
                   "gives_advice": {"type": "boolean"}, "reason": {"type": "string"}},
    "required": ["faithful", "unsupported", "gives_advice", "reason"],
}
PROMPT = """You are checking a plain-language summary of a provision of Ontario law.

faithful = true only if every statement in the summary is supported by the official text (plain rewording is fine;
adding facts, conditions, numbers or consequences that the text does not state is not). List any unsupported
statements. gives_advice = true if the summary tells the reader whether they have a case, predicts an outcome,
values a claim or computes a specific date.

The summary was written knowing the law and provision below, so naming them is supported.
Law and provision: {where}
<official_text>
{text}
</official_text>

<summary>
{summary}
</summary>"""


def judge_summary(text: str, summary: str, generate: Callable[[str, dict], dict], where: str = "") -> dict:
    try:
        out = generate(PROMPT.format(text=text, summary=summary, where=where or "(not given)"), SCHEMA)
        return {"faithful": float(bool(out["faithful"])), "no_advice": float(not out["gives_advice"]),
                "unsupported": list(out["unsupported"]), "reason": out["reason"], "error": None}
    except (KeyError, TypeError, ValueError) as e:
        return {"faithful": None, "no_advice": None, "unsupported": [], "reason": repr(e)[:200], "error": "judge_error"}


def summarize_scores(rows: list[dict]) -> dict:
    grades = [r["grade"] for r in rows]
    return {"n": len(rows), "faithful": mean_of(rows, "faithful"), "no_advice": mean_of(rows, "no_advice"),
            "mean_grade": round(mean(grades), 1), "grade_le_10": round(sum(g <= 10 for g in grades) / len(grades), 3),
            "judge_errors": sum(r.get("faithful") is None for r in rows)}
