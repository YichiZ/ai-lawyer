"""Glossary definitions (Phase 4.3): one or two plain sentences per curated term, written by gemini-3.7-flash
from the term's source section (its statutory definition when a law defines it).

Every definition is checked before it is stored: a non-answer ("the provided text does not define…") or one that
talks about its source ("based on this text", "under this section") is retried once with a stricter prompt and
dropped if it still fails (#4)."""
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable

import psycopg

from ingest.statutes import display_pinpoint
from ingest.v0 import V0

TERMS_PATH = Path(__file__).resolve().parent.parent / "app" / "glossary_terms.tsv"
LAW_KINDS = ("statute", "regulation", "bylaw")
LIBRARY_ORDER = [law.slug for law in V0]  # injury-core laws first
PROMPT = """Write a glossary entry for the legal term "{term}" for paralegals and law students working in Ontario \
personal-injury law: 1-2 short sentences, grade 8 reading level.

Say what the term means in plain language, so the entry makes sense on its own. Your source is the provision below \
from {where}:
- If the provision defines the term, reword that definition only and add nothing to it.
- Otherwise, give the term's core legal meaning in one short sentence, then one sentence on what the law says about \
it, naming the law (who it applies to, what it allows or bars). Do not narrow the core meaning to one situation (e.g. only dog \
owners) unless the term only exists there.
Everything else must be supported by the provision: do not add numbers, deadlines, conditions, examples or exceptions \
it does not state, and never contradict it.
Never mention the source itself: no "the provided text", "based on this text", "under this section", "this Act", \
"the text does not define". If a law must be named, name it (e.g. "Ontario's Negligence Act").
Not legal advice. Reply with the definition only, as plain text (no Markdown).

<provision>
{text}
</provision>"""
RETRY = """

Your previous answer was rejected because it {reason}: "{previous}".
Write the definition itself this time. Start with the term, e.g. "{term_cap} is …" or "{term_cap} means …"."""

NON_ANSWER_RE = re.compile(
    r"based on the (?:provided|given) text|the (?:provided|given) text (?:does not|doesn't)|not (?:explicitly )?defined"
    r"|does not (?:provide|contain|include) a definition|no definition|cannot (?:be )?determine|i (?:can't|cannot)"
    r"|is not (?:explicitly )?(?:mentioned|stated)", re.IGNORECASE)
SOURCE_REF_RE = re.compile(
    r"\b(?:the|this) (?:provided|given|above|source) (?:text|passage|excerpt|provision)\b|\bthe text\b"
    r"|\bthis (?:text|passage|excerpt|provision|act|regulation|section|subsection|rule|part|schedule)\b"
    r"|\bbased (?:only |strictly |solely )?on (?:the|this) (?:text|provision|section|passage|act)\b", re.IGNORECASE)


def is_non_answer(definition: str) -> bool:
    """The model said it can't define the term. Shared with the glossary eval (evals/suite.py)."""
    return bool(NON_ANSWER_RE.search(definition or ""))


def rejection(definition: str) -> str | None:
    """Why a definition must not be stored, or None if it may."""
    if not (definition or "").strip():
        return "was empty"
    if is_non_answer(definition):
        return "said the term could not be defined"
    if SOURCE_REF_RE.search(definition):
        return "referred to the source text instead of defining the term"
    if "*" in definition:
        return "used Markdown formatting"
    return None


def _clean(text: str) -> str:
    return " ".join(text.replace("*", "").split())


def load_terms(path: Path = TERMS_PATH) -> list[tuple[str, str | None, str | None]]:
    out = []
    for line in path.read_text().splitlines():
        if line.strip() and not line.startswith("#"):
            parts = line.split("\t")
            out.append((parts[0].strip(), parts[1].strip(), parts[2].strip()) if len(parts) == 3 else (parts[0].strip(), None, None))
    return out


def _defining_section(conn: psycopg.Connection, term: str, slug: str | None = None):
    """(slug, pinpoint, text) of the law section that says “term” means/includes …: only in `slug` when given,
    otherwise library laws in `V0` order (injury-core first), then others; within a law the first defining section
    (its matching subsection before it, as the shorter text)."""
    row = conn.execute(
        "SELECT d.slug, s.pinpoint, s.text FROM sections s JOIN documents d ON d.id = s.document_id"
        " LEFT JOIN sections p ON p.id = s.parent_id AND s.kind = 'subsection'"
        " WHERE d.kind = ANY(%s) AND s.text ILIKE ANY(%s) AND (%s::text IS NULL OR d.slug = %s)"
        " ORDER BY array_position(%s::text[], d.slug) NULLS LAST, d.slug, COALESCE(p.sort_order, s.sort_order),"
        " (s.kind = 'subsection') DESC, s.sort_order LIMIT 1",
        (list(LAW_KINDS), [f"%“{term}” means%", f"%“{term}” includes%"], slug, slug, LIBRARY_ORDER)).fetchone()
    return tuple(row) if row else None


def _defines(text: str, term: str) -> bool:
    return any(f"“{term}” {verb}".lower() in text.lower() for verb in ("means", "includes"))


NAME_ONLY_WORDS = 15  # a definition this short that points elsewhere only names the term (#36)
POINTER_RE = re.compile(r"\b(?:established|continued|created|constituted|as defined|within the meaning)\b", re.IGNORECASE)


def _names_only(text: str, term: str) -> bool:
    """The law's “term” means … clause is short, restates the term and points elsewhere, e.g. “Licence Appeal
    Tribunal” means the Licence Appeal Tribunal established under … — a curated section that says what the thing does
    is richer. (“claim” means a claim to remedy an injury is a real definition.)"""
    m = re.search(rf"“{re.escape(term)}” (?:means|includes)\s+(.*?)(?:\(“|;|$)", text, re.IGNORECASE | re.DOTALL)
    clause = m.group(1) if m else ""
    return term.lower() in clause.lower() and len(clause.split()) <= NAME_ONLY_WORDS and bool(POINTER_RE.search(clause))


def _curated(conn: psycopg.Connection, slug: str, spec: str):
    """(slug, spec, text) of the curated section(s): `spec` is one pinpoint or several joined by "+" (e.g.
    "s-29+s-1-1": a definition plus the one it refers to), texts in that order; None if the first is missing."""
    pins = spec.split("+")
    texts = dict(conn.execute("SELECT s.pinpoint, s.text FROM sections s JOIN documents d ON d.id = s.document_id"
                              " WHERE d.slug = %s AND s.pinpoint = ANY(%s)", (slug, pins)).fetchall())
    if pins[0] not in texts:
        return None
    if len(pins) == 1:
        return slug, spec, texts[spec]
    return slug, spec, "\n\n".join(f"{display_pinpoint(p)}:\n{texts[p]}" for p in pins if p in texts)


def resolve_source(conn: psycopg.Connection, term: str, slug: str | None, pinpoint: str | None):
    """(slug, pinpoint spec, text), first match of: the curated section if it defines “term”; another section of the
    curated law that defines it; any law's definition (library order); the curated section; None. A definition that
    only names the term (`_names_only`) never beats a curated section."""
    pinned = _curated(conn, slug, pinpoint) if slug and pinpoint else None
    if pinned and _defines(pinned[2], term):
        return pinned
    found = (_defining_section(conn, term, slug) if slug else None) or _defining_section(conn, term)
    if found and pinned and _names_only(found[2], term):
        return pinned
    return found or pinned


def where(title: str, spec: str) -> str:
    return f"{title}, {' and '.join(display_pinpoint(p) for p in spec.split('+'))}"


def judged_sources(conn: psycopg.Connection, terms=None) -> list[tuple]:
    """(term, definition, where, source text or None) for every stored definition, with the text of the curated
    extra sections ("s-29+s-1-1") the definition was written from, for the judges."""
    curated = {t.lower(): (s, p) for t, s, p in (terms if terms is not None else load_terms()) if p}
    out = []
    for term, definition, slug, pin, title in conn.execute(
            "SELECT g.term, g.plain_definition, g.source_slug, g.source_pinpoint, d.title FROM glossary_terms g"
            " LEFT JOIN documents d ON d.slug = g.source_slug ORDER BY g.term").fetchall():
        c_slug, c_spec = curated.get(term.lower(), (None, None))
        spec = c_spec if c_slug == slug and c_spec and c_spec.split("+")[0] == pin else pin
        src = _curated(conn, slug, spec) if slug and spec else None
        out.append((term, definition, where(title or "", spec or ""), src[2] if src else None))
    return out


def prune(conn: psycopg.Connection, terms) -> list[str]:
    """Delete stored definitions whose term is no longer curated (their glossary links go with them)."""
    keep = [t.lower() for t, _, _ in terms]
    return [r[0] for r in conn.execute("DELETE FROM glossary_terms WHERE NOT lower(term) = ANY(%s) RETURNING term",
                                       (keep,)).fetchall()]


def build_prompt(term: str, where: str, text: str) -> str:
    return PROMPT.format(term=term, where=where, text=text)


def define(term: str, prompt: str, generate: Callable[[str], str]) -> str | None:
    """A checked definition, retried once with a stricter prompt; None (logged) if both attempts fail."""
    first = _clean(generate(prompt))
    reason = rejection(first)
    if reason is None:
        return first
    retry = prompt + RETRY.format(reason=reason, previous=first[:300], term_cap=term[:1].upper() + term[1:])
    second = _clean(generate(retry))
    if rejection(second) is None:
        return second
    print(f"glossary: dropped {term!r}: {rejection(second)}: {second[:160]!r}", flush=True)
    return None


def upsert_definitions(conn: psycopg.Connection, terms, generate: Callable[[str], str], workers: int = 4,
                       redo: frozenset[str] = frozenset()) -> int:
    """Write definitions for curated terms that have none, whose stored definition fails the check, or that are in
    `redo` (lower case). A failed rewrite deletes a stored definition that fails the check and keeps one that passes.
    Returns model jobs."""
    stored = {t.lower(): d for t, d in conn.execute("SELECT term, plain_definition FROM glossary_terms")}
    jobs = []
    for term, slug, pin in terms:
        key = term.lower()
        if key in stored and key not in redo and rejection(stored[key]) is None:
            continue
        src = resolve_source(conn, term, slug, pin)
        if src is None:
            print(f"glossary: no source section for {term!r}", flush=True)
            continue
        title = conn.execute("SELECT title FROM documents WHERE slug = %s", (src[0],)).fetchone()[0]
        jobs.append((term, src[0], src[1].split("+")[0], build_prompt(term, where(title, src[1]), src[2])))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(lambda j: define(j[0], j[3], generate), jobs))
    with conn.transaction():
        for (term, slug, pin, _), definition in zip(jobs, results):
            if definition is not None:
                conn.execute("INSERT INTO glossary_terms (term, plain_definition, source_slug, source_pinpoint)"
                             " VALUES (%s, %s, %s, %s) ON CONFLICT (term) DO UPDATE SET plain_definition ="
                             " EXCLUDED.plain_definition, source_slug = EXCLUDED.source_slug,"
                             " source_pinpoint = EXCLUDED.source_pinpoint", (term, definition, slug, pin))
            elif term.lower() in stored and rejection(stored[term.lower()]) is not None:
                conn.execute("DELETE FROM glossary_terms WHERE lower(term) = lower(%s)", (term,))
    return len(jobs)
