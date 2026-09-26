"""evals/baseline.json and the regression gate used by `make eval`."""
import hashlib
from pathlib import Path

import psycopg

BASELINE_PATH = Path(__file__).resolve().parent / "baseline.json"
TOLERANCE = 0.02  # a quality metric may not drop more than 2 points (design doc)
# LLM-judge metrics swing between identical runs (faithful 0.852-0.930, citation_supported 0.938-0.966 across 3 runs,
# 2026-09-26), so a 2-point gate on them fails at random. ponytail: wider tolerance; average N runs if it bites.
JUDGE_TOLERANCE = 0.05
TOLERANCES = {"answers.in_scope.citation_supported": JUDGE_TOLERANCE, "answers.in_scope.faithful": JUDGE_TOLERANCE,
              "summaries.faithful": JUDGE_TOLERANCE}
QUALITY_METRICS = (
    "retrieval.recall@8", "retrieval.mrr",
    "answers.in_scope.has_verified_claim", "answers.in_scope.verified_claim_rate",
    "answers.in_scope.facts_covered", "answers.in_scope.citation_supported", "answers.in_scope.faithful",
    "answers.in_scope.no_advice", "answers.in_scope.refusal_correct", "answers.out_of_scope.refusal_correct",
)
SUMMARY_METRICS = ("summaries.faithful", "summaries.no_advice", "summaries.grade_le_10")


def corpus_hash(conn: psycopg.Connection) -> str:
    shas = [r[0] for r in conn.execute("SELECT sha256 FROM documents ORDER BY sha256")]
    return hashlib.sha256("\n".join(shas).encode()).hexdigest()


def gold_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def flatten(retrieval: dict, answers: dict, summaries: dict | None = None) -> dict[str, float]:
    r, a = retrieval["summary"]["all"], answers["summary"]
    flat = {"retrieval.recall@8": r["recall@8"], "retrieval.mrr": r["mrr"],
            "answers.out_of_scope.refusal_correct": a["out_of_scope"]["refusal_correct"]}
    for m in QUALITY_METRICS:
        if m.startswith("answers.in_scope."):
            flat[m] = a["in_scope"][m.split(".")[-1]]
    if summaries is not None:
        for m in SUMMARY_METRICS:
            flat[m] = summaries["summary"][m.split(".")[-1]]
    return flat


def compare(current: dict, baseline: dict) -> tuple[bool, list[str]]:
    """(ok, report lines). Fails on a drop > TOLERANCE, a missing metric, or a corpus/gold hash change."""
    lines, ok = [], True
    for key in ("corpus_hash", "gold_hash"):
        if current[key] != baseline[key]:
            ok = False
            lines.append(f"FAIL {key} changed ({baseline[key][:12]} -> {current[key][:12]}): re-record the baseline "
                         "deliberately with `make eval-baseline`")
    for metric, base in baseline["metrics"].items():
        now = current["metrics"].get(metric)
        if now is None:
            ok = False
            lines.append(f"FAIL {metric} missing from this run")
            continue
        delta, tol = now - base, TOLERANCES.get(metric, TOLERANCE)
        if delta < -tol:
            ok = False
            lines.append(f"FAIL {metric} {base:.3f} -> {now:.3f} ({delta * 100:+.1f} points)")
        elif delta > tol:
            lines.append(f"improved {metric} {base:.3f} -> {now:.3f} ({delta * 100:+.1f} points)")
    if ok:
        lines.append("no regression vs baseline")
    return ok, lines
