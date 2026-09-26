"""Parse a Toronto Municipal Code chapter (pdftotext output) into the same document + sections shape as statutes.

Tree: Article (part) > § section. Text is kept line by line as extracted (lettered labels like "A." joined to their
paragraph); page headers, page numbers, dates and footnote markers are dropped.
City copyright: documents are stored with reproduction='excerpt' — the UI shows excerpts + a link, never full text.
"""
import hashlib
import re
import subprocess
from datetime import datetime
from pathlib import Path

from ingest.statutes import ParsedLaw

PARSER_VERSION = 1
MONTH_DATE = re.compile(
    r"^(January|February|March|April|May|June|July|August|September|October|November|December) \d{1,2}, \d{4}$")
ARTICLE = re.compile(r"^ARTICLE ([IVXLC]+)$")
LABEL = re.compile(r"^(?:[A-Z]{1,2}\.|\(\w{1,4}\))$")  # "A." or "(1)" alone on a line


def pdf_text(path: Path) -> str:
    """Extract text with poppler's pdftotext (system tool: brew install poppler)."""
    return subprocess.run(["pdftotext", str(path), "-"], capture_output=True, text=True, check=True).stdout


def clean_lines(raw: str, chapter: str) -> list[str]:
    page_number = re.compile(rf"^{re.escape(chapter)}-\d+(?:\.\d+)?$")
    out = []
    for line in raw.replace("\f", "\n").split("\n"):
        line = line.strip()
        if (not line or line == "TORONTO MUNICIPAL CODE" or line.startswith(f"CHAPTER {chapter},")
                or page_number.match(line) or MONTH_DATE.match(line) or re.fullmatch(r"\d{1,3}", line)):
            continue  # ponytail: footnote TEXT at page bottoms stays in; only bare footnote markers are dropped
        out.append(line)
    return out


def _body_start(lines: list[str], section_re: re.Pattern) -> int:
    """Index where the body begins: the second occurrence of the first section heading (the first is the TOC)."""
    first = next((i for i, l in enumerate(lines) if section_re.match(l)), None)
    if first is None:
        return 0
    again = next((i for i in range(first + 1, len(lines)) if lines[i] == lines[first]), None)
    if again is None:
        return first
    return again - 2 if again >= 2 and ARTICLE.match(lines[again - 2]) else again


def parse_chapter(raw: str, chapter: str, title: str, pdf_sha256: str, url: str, license: str) -> ParsedLaw:
    section_re = re.compile(rf"^§ {re.escape(chapter)}-(\d+(?:\.\d+)*)\.\s*(.*)$")
    lines = clean_lines(raw, chapter)
    i = _body_start(lines, section_re)

    sections: list[dict] = []
    seen: set[str] = set()
    article = None  # (pinpoint, heading)
    current = None

    def add(row):
        if row["pinpoint"] in seen:
            raise ValueError(f"chapter {chapter}: duplicate pinpoint {row['pinpoint']}")
        seen.add(row["pinpoint"])
        row["sort_order"] = len(sections) + 1
        sections.append(row)

    while i < len(lines):
        line = lines[i]
        if m := ARTICLE.match(line):
            name = lines[i + 1] if i + 1 < len(lines) else ""
            article = (f"article-{m.group(1).lower()}", f"Article {m.group(1)} — {name}")
            current, i = None, i + 2
            continue
        if m := section_re.match(line):
            heading = m.group(2)
            while heading and not heading.endswith(".") and i + 1 < len(lines) and not section_re.match(lines[i + 1]):
                i += 1
                heading = f"{heading} {lines[i]}"
            if article and article[0] not in seen:
                add({"pinpoint": article[0], "kind": "part", "heading": article[1], "text": "", "parent": None})
            current = {"pinpoint": f"{chapter}-{m.group(1)}", "kind": "section", "heading": heading.rstrip("."),
                       "text": [], "parent": article[0] if article else None}
            add(current)
            i += 1
            continue
        if current is not None:
            if LABEL.match(line) and i + 1 < len(lines):
                line, i = f"{line} {lines[i + 1]}", i + 1
            current["text"].append(line)
        i += 1

    for s in sections:
        if s["kind"] == "section":
            s["text"] = "\n".join(s["text"]) or s["heading"]
    if not any(s["kind"] == "section" for s in sections):
        raise ValueError(f"chapter {chapter}: no sections found")

    dates = [datetime.strptime(l.strip(), "%B %d, %Y").date() for l in raw.split("\n") if MONTH_DATE.match(l.strip())]
    document = {
        "sha256": hashlib.sha256(f"{pdf_sha256}:{PARSER_VERSION}".encode()).hexdigest(),
        "kind": "bylaw",
        "slug": f"toronto-municipal-code-{chapter}",
        "title": f"Toronto Municipal Code, Chapter {chapter}, {title}",
        "short_name": f"Toronto Municipal Code ch. {chapter}",
        "citation": f"Toronto Municipal Code, c {chapter}",
        "jurisdiction": "ON-Toronto",
        "in_force_from": max(dates) if dates else None,
        "url": url,
        "source": "toronto-municipal-code",
        "upstream_license": license,
        "reproduction": "excerpt",
    }
    return ParsedLaw(document, sections)
