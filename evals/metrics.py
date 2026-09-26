"""Retrieval metrics against gold pinpoints. A hit matches an expected pinpoint in the same law when either one
contains the other (a whole-section chunk contains its subsections; a subsection chunk sits inside its section).
A split chunk is labelled by its first subsection but covers several; pass them as the hit's third element."""
from statistics import mean

import psycopg

Hit = tuple  # (slug, pinpoint) or (slug, pinpoint, [covered pinpoints])


def _contains(outer: str, inner: str) -> bool:
    return inner == outer or inner.startswith(outer + "-")


def matches(hit: Hit, expected: list[dict]) -> bool:
    slug, pins = hit[0], (hit[2] if len(hit) > 2 and hit[2] else [hit[1]])
    return any(e["slug"] == slug and (_contains(p, e["pinpoint"]) or _contains(e["pinpoint"], p))
               for e in expected for p in pins)


def chunk_covers(conn: psycopg.Connection, chunk_ids: list[int]) -> dict[int, list[str]]:
    """Pinpoints each chunk covers: its subsections when it holds some (the parent id rides along in every piece of a
    split section, so it is left out), else its section."""
    rows = conn.execute(
        "SELECT c.id, s.pinpoint, s.kind FROM chunks c JOIN sections s ON s.id = ANY(c.section_ids)"
        " WHERE c.id = ANY(%s) ORDER BY c.id, s.sort_order", (chunk_ids,),
    ).fetchall()
    by_chunk: dict[int, list[tuple[str, str]]] = {cid: [] for cid in chunk_ids}
    for cid, pin, kind in rows:
        by_chunk[cid].append((pin, kind))
    return {cid: ([p for p, k in ps if k == "subsection"] or [p for p, _ in ps]) for cid, ps in by_chunk.items()}


def recall_at_k(ranked: list[Hit], expected: list[dict], k: int = 8) -> float:
    """1.0 if any of the top k hits matches an expected pinpoint (gold items list alternatives, so any one counts)."""
    return 1.0 if any(matches(h, expected) for h in ranked[:k]) else 0.0


def mrr(ranked: list[Hit], expected: list[dict]) -> float:
    return next((1 / rank for rank, h in enumerate(ranked, start=1) if matches(h, expected)), 0.0)


def mean_of(rows: list[dict], key: str) -> float | None:
    """Mean of key over the rows that have it (judge errors leave it unset), to 3 places; None when none do."""
    vals = [r[key] for r in rows if r.get(key) is not None]
    return round(mean(vals), 3) if vals else None


def summarize(rows: list[dict], metrics: list[str]) -> dict[str, dict]:
    """Mean of each metric overall ("all") and per topic, with counts."""
    groups: dict[str, list[dict]] = {"all": rows}
    for r in rows:
        groups.setdefault(r["topic"], []).append(r)
    return {g: {"n": len(rs), **{m: mean(r[m] for r in rs) for m in metrics}} for g, rs in groups.items()}
