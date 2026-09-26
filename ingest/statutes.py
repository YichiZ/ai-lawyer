"""Parse an A2AJ statute/regulation row into a document + section tree, and load it into Postgres.

Tree: Part (from `##` Markdown headings) > section (A2AJ section map, text kept exactly) > subsection ((1), (1.1) lines).
Clauses (a) and subclauses (i) stay inside their subsection's text.
"""
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date

import psycopg

from ingest.v0 import V0Law

NUMERIC_KEY = re.compile(r"^\d+(?:\.\d+)*$")
RANGE_KEY = re.compile(r"^\d+(?:\.\d+)*-\d+(?:\.\d+)*$")
SUBSECTION_LINE = re.compile(r"^\((\d+(?:\.\d+)?)\)\s")
PART_HEADING = re.compile(r"^part\s+([ivxlc]+(?:\.\d+)?)\b", re.IGNORECASE)
RULE_HEADING = re.compile(r"^rule\s+(\d+(?:\.\d+)?)\b", re.IGNORECASE)  # Rules of Civil Procedure group by Rule
PARSER_VERSION = 2  # bump when parsing changes so the loader replaces already-loaded documents
RULE_SLUGS = {"rules-of-civil-procedure"}


@dataclass
class ParsedLaw:
    document: dict
    sections: list[dict]  # reading order; "parent" is a pinpoint or None


def slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9.]+", "-", s.lower()).strip("-")


def section_pinpoint(key: str, prefix: str) -> str:
    if NUMERIC_KEY.match(key):
        return f"{prefix}-{key}"
    if RANGE_KEY.match(key):
        return f"{prefix}{prefix}-{key}"
    return slugify(key)


def display_pinpoint(pinpoint: str) -> str:
    """s-4-1 -> s. 4(1); r-1.06-2 -> r. 1.06(2); ss-25-49 -> ss. 25-49; part-iii.1 -> Part III.1."""
    if re.fullmatch(r"\d+-\d+(?:\.\d+)*", pinpoint):  # Toronto Municipal Code: 743-9 -> § 743-9
        return f"§ {pinpoint}"
    if pinpoint.startswith("para-"):  # decisions: para-45 -> para 45
        return f"para {pinpoint[5:]}"
    head, _, rest = pinpoint.partition("-")
    if head in ("s", "r"):
        num, _, sub = rest.partition("-")
        return f"{head}. {num}" + (f"({sub})" if sub else "")
    if head in ("ss", "rr"):
        return f"{head}. {rest}"
    if head == "part":
        return f"Part {rest.upper()}"
    words = pinpoint.split("-")
    return " ".join([words[0].capitalize()] + [w.upper() for w in words[1:]])


def human_url(api_url: str) -> str:
    return api_url.replace("/laws/api/v2/legislation/en/doc-search/", "/laws/")


def split_subsections(text: str) -> list[tuple[str, str]]:
    """[(label, text)] when the section is fully made of (n) subsections with unique labels, else []."""
    lines = text.split("\n")
    if not SUBSECTION_LINE.match(lines[0]):
        return []
    parts: list[tuple[str, list[str]]] = []
    for line in lines:
        m = SUBSECTION_LINE.match(line)
        if m:
            parts.append((m.group(1), [line]))
        else:
            parts[-1][1].append(line)
    labels = [label for label, _ in parts]
    if len(labels) < 2 or len(labels) != len(set(labels)):
        return []
    return [(label, "\n".join(body)) for label, body in parts]


SECTION_START = re.compile(r"^(\d+(?:\.\d+)*(?:-\d+(?:\.\d+)*)?)(?:\s|$)")


def locate_sections(markdown: str, keys: list[str]) -> dict[str, tuple[str | None, str | None]]:
    """key -> (part heading, section heading) from the Markdown.

    One pass records the part and heading in effect at each line (a heading applies only up to the next section
    start). Keys are looked up forward from the previous hit first, then anywhere, because the section map order
    can differ from the Markdown order (e.g. Rule 2.1.01 vs 2.02).
    """
    part_at, heading_at, starts = [], [], {}
    part = heading = None
    for i, line in enumerate(markdown.split("\n")):
        part_at.append(part)
        heading_at.append(heading)
        if line.startswith("## ") or (line.startswith("### ") and RULE_HEADING.match(line[4:])):
            part, heading = line.split(" ", 1)[1].strip(), None
        elif line.startswith("### "):
            heading = line[4:].strip()
        elif m := SECTION_START.match(line):
            starts.setdefault(m.group(1), []).append(i)
            heading = None

    pos, last_part, found = 0, None, {}
    for key in keys:
        hits = starts.get(key, [])
        forward = [i for i in hits if i >= pos]
        if forward or hits:
            i = forward[0] if forward else hits[0]
            if forward:
                pos = i + 1
            last_part = part_at[i]
            found[key] = (part_at[i], heading_at[i])
        else:
            found[key] = (last_part, None)  # not in the Markdown: stays under the previous part
    return found


def part_pinpoint(heading: str) -> str:
    if m := PART_HEADING.match(heading):
        return f"part-{m.group(1).lower()}"
    if m := RULE_HEADING.match(heading):
        return f"rule-{m.group(1)}"
    return f"heading-{slugify(heading)[:60]}"


def source_hash(row: dict) -> str:
    payload = {k: row.get(k) for k in ("name_en", "citation_en", "unofficial_sections_en", "unofficial_text_en")}
    payload["parser_version"] = PARSER_VERSION
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def parse_law(row: dict, law: V0Law) -> ParsedLaw:
    section_map: dict[str, str] = json.loads(row["unofficial_sections_en"])
    prefix = "r" if law.slug in RULE_SLUGS else "s"
    located = locate_sections(row["unofficial_text_en"] or "", list(section_map))

    sections: list[dict] = []
    seen: set[str] = set()

    def add(pinpoint, kind, heading, text, parent):
        if pinpoint in seen:
            raise ValueError(f"{law.slug}: duplicate pinpoint {pinpoint}")
        seen.add(pinpoint)
        sections.append({"pinpoint": pinpoint, "kind": kind, "heading": heading, "text": text, "parent": parent,
                         "sort_order": len(sections) + 1})

    for key, text in section_map.items():
        if not text or not text.strip():
            raise ValueError(f"{law.slug}: section {key} has empty text")
        part_heading, heading = located[key]
        parent = part_pinpoint(part_heading) if part_heading else None
        if parent and parent not in seen:
            add(parent, "part", part_heading, "", None)
        pin = section_pinpoint(key, prefix)
        add(pin, "section", heading, text, parent)
        for label, sub_text in split_subsections(text):
            add(f"{pin}-{label}", "subsection", None, sub_text, pin)

    document = {
        "sha256": source_hash(row),
        "kind": "statute" if law.dataset.startswith("LEGISLATION") else "regulation",
        "slug": law.slug,
        "title": law.title,
        "short_name": law.title,
        "citation": row["citation_en"],
        "jurisdiction": "ON",
        "in_force_from": date.fromisoformat(str(row["document_date_en"])[:10]),
        "url": human_url(row["source_url_en"]),
        "source": "a2aj-laws",
        "upstream_license": row["upstream_license"],
        "reproduction": "full",
    }
    return ParsedLaw(document, sections)


DOC_COLUMNS = ("sha256", "kind", "slug", "title", "short_name", "citation", "jurisdiction", "in_force_from", "url",
               "source", "upstream_license", "reproduction", "neutral_citation", "court", "date")


def load_document(conn: psycopg.Connection, parsed: ParsedLaw) -> str:
    """Insert or replace one document and its sections in a single transaction. Returns inserted|updated|unchanged."""
    doc = parsed.document
    with conn.transaction():
        existing = conn.execute("SELECT id, sha256 FROM documents WHERE slug = %s", (doc["slug"],)).fetchone()
        if existing and existing[1] == doc["sha256"]:
            return "unchanged"
        values = [doc.get(c) for c in DOC_COLUMNS]
        if existing:
            doc_id = existing[0]
            sets = ", ".join(f"{c} = %s" for c in DOC_COLUMNS)
            conn.execute(f"UPDATE documents SET {sets} WHERE id = %s", (*values, doc_id))
            conn.execute("DELETE FROM sections WHERE document_id = %s", (doc_id,))
        else:
            cols, marks = ", ".join(DOC_COLUMNS), ", ".join(["%s"] * len(DOC_COLUMNS))
            doc_id = conn.execute(f"INSERT INTO documents ({cols}) VALUES ({marks}) RETURNING id", values).fetchone()[0]
        ids: dict[str, int] = {}
        for s in parsed.sections:
            parent_id = ids[s["parent"]] if s["parent"] else None
            ids[s["pinpoint"]] = conn.execute(
                "INSERT INTO sections (document_id, parent_id, pinpoint, kind, heading, text, sort_order)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
                (doc_id, parent_id, s["pinpoint"], s["kind"], s["heading"], s["text"], s["sort_order"]),
            ).fetchone()[0]
    return "updated" if existing else "inserted"
