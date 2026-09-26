"""Retrieval metrics against gold pinpoints. A hit matches an expected pinpoint in the same law when either one
contains the other (a whole-section chunk contains its subsections; a subsection chunk sits inside its section)."""
from statistics import mean

Hit = tuple[str, str]  # (slug, pinpoint)


def _contains(outer: str, inner: str) -> bool:
    return inner == outer or inner.startswith(outer + "-")


def matches(hit: Hit, expected: list[dict]) -> bool:
    slug, pin = hit
    return any(e["slug"] == slug and (_contains(pin, e["pinpoint"]) or _contains(e["pinpoint"], pin)) for e in expected)


def recall_at_k(ranked: list[Hit], expected: list[dict], k: int = 8) -> float:
    """1.0 if any of the top k hits matches an expected pinpoint (gold items list alternatives, so any one counts)."""
    return 1.0 if any(matches(h, expected) for h in ranked[:k]) else 0.0


def mrr(ranked: list[Hit], expected: list[dict]) -> float:
    return next((1 / rank for rank, h in enumerate(ranked, start=1) if matches(h, expected)), 0.0)


def summarize(rows: list[dict], metrics: list[str]) -> dict[str, dict]:
    """Mean of each metric overall ("all") and per topic, with counts."""
    groups: dict[str, list[dict]] = {"all": rows}
    for r in rows:
        groups.setdefault(r["topic"], []).append(r)
    return {g: {"n": len(rs), **{m: mean(r[m] for r in rs) for m in metrics}} for g, rs in groups.items()}
