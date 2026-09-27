"""evals/baseline.json and the regression gate used by `make eval`."""
import hashlib
from math import sqrt
from pathlib import Path
from statistics import mean

import psycopg

BASELINE_PATH = Path(__file__).resolve().parent / "baseline.json"
TOLERANCE = 0.02  # a quality metric may not drop more than 2 points (design doc)
# Std of one full run (drafting + judging) for the LLM-judge metrics, measured 2026-09-27 (#31) over the 10 saved runs
# of 70-71 in-scope items and 10 summaries runs. Re-judging the same drafts moves faithful only ~1 point (sd 0.007-0.012),
# so the spread comes from the drafts, and averaging judge passes would not fix it; averaging full runs does.
RUN_SD = {"answers.in_scope.faithful": 0.029, "answers.in_scope.citation_supported": 0.016, "summaries.faithful": 0.015}
RECORD_RUNS = 3  # `record` averages this many full runs


def tolerance(metric: str, n_now: int = 1, n_base: int = 1) -> float:
    """Allowed drop: 2 sd of (mean of n_now runs − mean of n_base runs) for judge metrics, at least TOLERANCE."""
    sd = RUN_SD.get(metric)
    return TOLERANCE if sd is None else max(TOLERANCE, round(2 * sd * sqrt(1 / n_now + 1 / n_base), 4))


def average(flats: list[dict[str, float]]) -> dict[str, float]:
    """Per-metric mean over several runs' flattened metrics."""
    return {k: round(mean(f[k] for f in flats), 4) for k in flats[0]}


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
    n_now, n_base = current.get("n_runs", 1), baseline.get("n_runs", 1)
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
        delta, tol = now - base, tolerance(metric, n_now, n_base)
        if delta < -tol:
            ok = False
            lines.append(f"FAIL {metric} {base:.3f} -> {now:.3f} ({delta * 100:+.1f} points, tolerance {tol * 100:.1f})")
        elif delta > tol:
            lines.append(f"improved {metric} {base:.3f} -> {now:.3f} ({delta * 100:+.1f} points)")
    if ok:
        lines.append("no regression vs baseline")
    return ok, lines


def merge_record(new: dict, old: dict | None, accept_drop: bool = False) -> tuple[bool, dict, list[str]]:
    """(ok, record to write, report lines). A judge metric within noise of the old baseline keeps the old value, so a
    low (or high) draw can't move the bar; a drop beyond noise is refused unless accept_drop. Code metrics take new."""
    if old is None or accept_drop:
        return True, new, ["recorded new values" + (" (--accept-drop)" if old is not None else "")]
    ok, lines, metrics = True, [], dict(new["metrics"])
    n_new, n_old = new.get("n_runs", 1), old.get("n_runs", 1)
    for m in RUN_SD:
        if m not in metrics or m not in old["metrics"]:
            continue
        now, base = metrics[m], old["metrics"][m]
        tol = tolerance(m, n_new, n_old)
        if abs(now - base) <= tol:
            metrics[m] = base
            lines.append(f"kept {m} {base:.3f} (new {now:.3f} is within noise, ±{tol * 100:.1f} points)")
        elif now < base:
            ok = False
            lines.append(f"REFUSED {m} {base:.3f} -> {now:.3f} ({(now - base) * 100:+.1f} points, beyond noise "
                         f"{tol * 100:.1f}): a real drop; rerun with --accept-drop to record it deliberately")
        else:
            lines.append(f"raised {m} {base:.3f} -> {now:.3f} (beyond noise {tol * 100:.1f})")
    return ok, {**new, "metrics": metrics}, lines
