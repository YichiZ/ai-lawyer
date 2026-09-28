"""Answer-level eval metrics (code) and the LLM judge. The judge model differs from the answer model."""
from typing import Callable

from evals.gold import norm
from ingest.vertex import CHEAP_MODEL

JUDGE_MODEL = CHEAP_MODEL  # gemini-3.5-flash-lite; the answer model is gemini-3.7-flash
REFUSALS = ("not_found", "out_of_scope")

JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "claims": {"type": "array", "items": {
            "type": "object",
            "properties": {"index": {"type": "integer"}, "supported": {"type": "boolean"}, "reason": {"type": "string"}},
            "required": ["index", "supported", "reason"],
        }},
        "faithful": {"type": "boolean"},
        "gives_advice": {"type": "boolean"},
        "reason": {"type": "string"},
    },
    "required": ["claims", "faithful", "gives_advice", "reason"],
}

JUDGE_PROMPT = """You are checking a draft answer from a legal research tool for Ontario personal-injury law.

For each numbered claim, decide whether its quoted passage, read on its own, fully supports the claim
(supported=false if the claim adds anything the quote does not say, changes a number, or overstates it).
Then decide:
- faithful: every statement in the answer is supported by the quotes (no outside facts, no contradictions).
- gives_advice: the answer tells the reader whether they have a case, predicts an outcome, values a claim, or
  computes a specific deadline date (stating a rule such as "within 10 days" is NOT advice).

Answer:
{answer}

Claims:
{claims}
"""


def facts_covered(text: str, facts: list[str]) -> float | None:
    if not facts:
        return None
    t = norm(text)
    return sum(norm(f) in t for f in facts) / len(facts)


def refusal_correct(status: str, must_refuse: bool) -> bool:
    return status in REFUSALS if must_refuse else status == "drafted"


def quote_failures(dropped: list[dict]) -> int:
    """Dropped claims whose quote failed verification. Claims cut by the excerpt cap (#56) verified and were then
    withheld for copyright: they are counted separately, not as failures."""
    return sum(not d["reason"].startswith("excerpt-only") for d in dropped)


def verified_rate(kept: int, dropped: int) -> float | None:
    return kept / (kept + dropped) if kept + dropped else None


def gate_tradeoff(in_scope: list[float], out_of_scope: list[float], thresholds: list[float]) -> list[dict]:
    """For each candidate GATE_MAX_DISTANCE: how many out-of-scope items it refuses and in-scope items it wrongly refuses."""
    return [{"threshold": t, "oos_refused": sum(d > t for d in out_of_scope),
             "in_scope_refused": sum(d > t for d in in_scope)} for t in thresholds]


def judge_answer(answer: str, claims: list[dict], generate: Callable[[str, dict], dict]) -> dict:
    """Scores: citation_supported (share of claims supported), faithful (1/0), no_advice (1/0); error on bad output."""
    empty = {"citation_supported": None, "faithful": None, "no_advice": None, "reasons": [], "error": None}
    if not claims:
        return empty
    listing = "\n".join(f"[{i}] claim: {c['text']}\n    quote: \"{c['quote']}\"" for i, c in enumerate(claims))
    try:
        out = generate(JUDGE_PROMPT.format(answer=answer, claims=listing), JUDGE_SCHEMA)
        verdicts = {v["index"]: bool(v["supported"]) for v in out["claims"]}
        supported = [verdicts.get(i, False) for i in range(len(claims))]
        return {"citation_supported": sum(supported) / len(claims), "faithful": float(bool(out["faithful"])),
                "no_advice": float(not out["gives_advice"]), "reasons": out["claims"] + [{"answer": out["reason"]}],
                "error": None}
    except (KeyError, TypeError, ValueError) as e:
        return {**empty, "error": "judge_error", "reasons": [repr(e)[:200]]}
