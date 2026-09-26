"""Citation extraction (Phase 5.4): decision → decision (A2AJ lists) and decision → statute section (regex)."""
import re

STATUTES = {  # name pattern → slug (the 12 v0 laws that decisions cite by name)
    r"Limitations Act,? 2002": "limitations-act-2002",
    r"Negligence Act": "negligence-act",
    r"Occupiers[’']? Liability Act": "occupiers-liability-act",
    r"Dog Owners[’']? Liability Act": "dog-owners-liability-act",
    r"Insurance Act": "insurance-act",
    r"Highway Traffic Act": "highway-traffic-act",
    r"Courts of Justice Act": "courts-of-justice-act",
    r"Family Law Act": "family-law-act",
    r"City of Toronto Act,? 2006": "city-of-toronto-act-2006",
    r"Workplace Safety and Insurance Act,? 1997": "workplace-safety-and-insurance-act-1997",
    r"Statutory Accident Benefits Schedule": "statutory-accident-benefits-schedule",
}
_NAME = "(?P<name>" + "|".join(f"(?:{p})" for p in STATUTES) + ")"
_SEC = r"(?:s\.|ss\.|sections?)\s*(?P<num>\d+(?:\.\d+)?)(?P<subs>(?:\s?\(\w{1,4}\))*)"
BEFORE = re.compile(_SEC + r"\s+of\s+the\s+" + _NAME, re.IGNORECASE)                 # s. 4 of the Limitations Act
AFTER = re.compile(_NAME + r"(?P<cite>,[^;\n]{0,70}?)?,\s*" + _SEC, re.IGNORECASE)   # Limitations Act, S.O. …, s. 4 (comma-led citation)
NAME_ONLY = re.compile(_NAME, re.IGNORECASE)


def _slug(name: str) -> str:
    return next(slug for pattern, slug in STATUTES.items() if re.fullmatch(pattern, name, re.IGNORECASE))


def _pinpoint(num: str, subs: str) -> str:
    first_sub = re.search(r"\((\d+(?:\.\d+)?)\)", subs or "")
    return f"s-{num}" + (f"-{first_sub.group(1)}" if first_sub else "")


def statute_refs(text: str) -> list[tuple[str, str | None]]:
    """[(slug, pinpoint or None)] in order of first mention, deduplicated. A statute named without a section gives
    (slug, None). Pinpoints go down to the subsection; clauses are dropped."""
    found: list[tuple[int, str, str | None]] = []
    spans: list[tuple[int, int]] = []
    for pattern in (BEFORE, AFTER):
        for m in pattern.finditer(text):
            found.append((m.start(), _slug(m.group("name")), _pinpoint(m.group("num"), m.group("subs"))))
            spans.append((m.start(), m.end()))
    for m in NAME_ONLY.finditer(text):
        if not any(s <= m.start() < e for s, e in spans):
            found.append((m.start(), _slug(m.group("name")), None))
    seen, out = set(), []
    for _, slug, pin in sorted(found):
        if (slug, pin) not in seen:
            seen.add((slug, pin))
            out.append((slug, pin))
    return out


def build_citations(conn, citing_document_id: int, refs: list[tuple[str, str | None]], cases: list[str]) -> int:
    """Replace a decision's citations: statute refs resolved to sections (unknown subsection → its section) and
    cited cases resolved to corpus decisions by neutral citation (others kept as text). Returns rows written."""
    with conn.transaction():
        conn.execute("DELETE FROM citations WHERE citing_document_id = %s", (citing_document_id,))
        own = conn.execute("SELECT neutral_citation FROM documents WHERE id = %s", (citing_document_id,)).fetchone()[0]
        n = 0
        for slug, pin in refs:
            doc = conn.execute("SELECT id FROM documents WHERE slug = %s", (slug,)).fetchone()
            section = None
            for candidate in ([pin, pin.rsplit("-", 1)[0]] if pin and pin.count("-") >= 2 else [pin] if pin else []):
                row = conn.execute("SELECT s.id FROM sections s JOIN documents d ON d.id = s.document_id"
                                   " WHERE d.slug = %s AND s.pinpoint = %s", (slug, candidate)).fetchone()
                if row:
                    section = row[0]
                    break
            conn.execute("INSERT INTO citations (citing_document_id, kind, cited_document_id, cited_slug, cited_pinpoint,"
                         " cited_section_id) VALUES (%s, 'statute', %s, %s, %s, %s)",
                         (citing_document_id, doc[0] if doc else None, slug, pin, section))
            n += 1
        for citation in dict.fromkeys(cases):
            if citation == own:
                continue
            doc = conn.execute("SELECT id FROM documents WHERE neutral_citation = %s", (citation,)).fetchone()
            conn.execute("INSERT INTO citations (citing_document_id, kind, cited_citation, cited_document_id)"
                         " VALUES (%s, 'case', %s, %s)", (citing_document_id, citation, doc[0] if doc else None))
            n += 1
    return n
