"""A2AJ case law (ONCA + SCC): the injury filter, paragraph parsing and loading (Phase 5)."""
import re

# Statutes specific enough that citing one makes a decision relevant (broad ones — Rules, CJA, HTA, Insurance Act,
# Family Law Act — only count together with injury terms).
INJURY_STATUTES = re.compile(
    r"Limitations Act, 2002|Negligence Act|Occupiers[’']? Liability Act|Dog Owners[’']? Liability Act|"
    r"Statutory Accident Benefits|Workplace Safety and Insurance Act|City of Toronto Act", re.IGNORECASE)
INJURY_TERMS = re.compile(
    r"personal injur|negligen|motor vehicle accident|slip and fall|occupier|duty of care|tort\b|"
    r"accident benefits|dog bite|bodily injur|non-pecuniary|general damages|contributory|wrongful death",
    re.IGNORECASE)
STRONG_TERMS = re.compile(
    r"personal injur|bodily injur|motor vehicle accident|slip and fall|occupier|dog bite|accident benefits|"
    r"wrongful death|non-pecuniary", re.IGNORECASE)
MIN_TERMS = 3
MIN_SCC_YEAR = 1970  # a guide to current law; older SCC tort cases are mostly superseded
SUBJECT = re.compile(r"^Subject\n([^\n]+)", re.MULTILINE)


def subject_of(text: str) -> str | None:
    m = SUBJECT.search(text[:3000])
    return m.group(1).strip() if m else None


def injury_score(text: str) -> dict:
    return {"statutes": len(INJURY_STATUTES.findall(text)), "terms": len(INJURY_TERMS.findall(text)),
            "strong": len(STRONG_TERMS.findall(text))}


def is_injury_case(court: str, text: str, year: int | None = None) -> bool:
    """ONCA: civil only; SCC: from MIN_SCC_YEAR. Keep if an injury statute is cited, or injury terms appear
    MIN_TERMS+ times including at least one injury-specific term (plain "negligence" is too broad)."""
    if court == "ONCA" and subject_of(text) not in ("Civil", None):
        return False
    if court == "SCC" and year is not None and year < MIN_SCC_YEAR:
        return False
    s = injury_score(text)
    return s["statutes"] > 0 or (s["terms"] >= MIN_TERMS and s["strong"] > 0)


# --- parsing ---

import hashlib  # noqa: E402
import json  # noqa: E402
from datetime import date  # noqa: E402

from ingest.statutes import ParsedLaw  # noqa: E402

PARSER_VERSION = 1
MARKER = re.compile(r"(?:^|(?<=\s))\[(\d{1,4})\]\s")


def split_paragraphs(text: str) -> tuple[str, list[tuple[int, str]]]:
    """(intro, [(n, paragraph text)]) from the text after "Decision Content". Only markers that continue the
    sequence 1, 2, 3 … start a paragraph, so citations like "[2004] 1 S.C.R." and back-references stay in the text.
    ponytail: if a later opinion restarts at [1], its text stays in the last paragraph of the first numbering."""
    body = text.split("Decision Content", 1)[-1].strip()
    starts, expected = [], 1
    for m in MARKER.finditer(body):
        if int(m.group(1)) == expected:
            starts.append((expected, m.start(), m.end()))
            expected += 1
    if not starts:
        return "", [(1, body)]
    intro = body[:starts[0][1]].strip()
    paras = []
    for i, (n, _, content_start) in enumerate(starts):
        end = starts[i + 1][1] if i + 1 < len(starts) else len(body)
        paras.append((n, body[content_start:end].strip()))
    return intro, paras


def decision_slug(citation: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", citation.lower()).strip("-")


def parse_decision(row: dict) -> ParsedLaw:
    intro, paras = split_paragraphs(row["unofficial_text_en"])
    sections = []
    if intro:
        sections.append({"pinpoint": "intro", "kind": "part", "heading": "Parties, judges and headnote", "text": intro,
                         "parent": None, "sort_order": 1})
    for n, text in paras:
        sections.append({"pinpoint": f"para-{n}", "kind": "section", "heading": None, "text": text or "(empty)",
                         "parent": None, "sort_order": len(sections) + 1})
    payload = json.dumps({k: str(row.get(k)) for k in ("citation_en", "name_en", "unofficial_text_en")}) + f":{PARSER_VERSION}"
    document = {
        "sha256": hashlib.sha256(payload.encode()).hexdigest(),
        "kind": "decision",
        "slug": decision_slug(row["citation_en"]),
        "title": row["name_en"],
        "short_name": row["name_en"],
        "citation": row["citation_en"],
        "neutral_citation": row["citation_en"],
        "court": row["dataset"],
        "jurisdiction": "CA" if row["dataset"] == "SCC" else "ON",
        "date": date.fromisoformat(str(row["document_date_en"])[:10]),
        "in_force_from": None,
        "url": row.get("url_en"),
        "source": "a2aj-caselaw",
        "upstream_license": row.get("upstream_license"),
        "reproduction": "full",
    }
    return ParsedLaw(document, sections)
