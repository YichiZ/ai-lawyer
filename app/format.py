"""Presentation helpers the web pages use: legislative indent levels and McGill-style citations."""
import re

LABEL = re.compile(r"^\(([0-9]+(?:\.[0-9]+)?|[a-z]{1,2}(?:\.[0-9]+)?|[ivxl]+(?:\.[0-9]+)?|[A-Z]{1,2}(?:\.[0-9]+)?)\)\s")
BYLAW_LABEL = re.compile(r"^[A-Z]{1,2}\.\s")
ROMAN = re.compile(r"^[ivxl]+$")
# A roman-looking label is a clause letter when it follows the letter before it: (h) -> (i), (u) -> (v), (w) -> (x).
LETTER_BEFORE = {"i": "h", "v": "u", "x": "w", "l": "k"}


def indent_lines(text: str) -> list[dict]:
    """Split section text into lines with an indent level: (1)=1, (a)=2, (i)=3, (A)=4; bylaw "A."=1; else 0."""
    out, last_clause = [], None
    for line in text.split("\n"):
        level = 0
        if m := LABEL.match(line):
            label = m.group(1).split(".")[0]
            if label.isdigit():
                level = 1
            elif label.isupper():
                level = 4
            elif ROMAN.match(label) and LETTER_BEFORE.get(label) != last_clause:
                level = 3
            else:
                level, last_clause = 2, label
        elif BYLAW_LABEL.match(line):
            level = 1
        out.append({"text": line, "level": level})
    return out


def _pinpoint_reference(pinpoint: str) -> str:
    if re.fullmatch(r"\d+-\d+(?:\.\d+)*", pinpoint):
        return f"§ {pinpoint}"
    head, _, rest = pinpoint.partition("-")
    if head in ("s", "r"):
        num, _, sub = rest.partition("-")
        return f"{head} {num}" + (f"({sub})" if sub else "")
    if head in ("ss", "rr"):
        return f"{head} {rest.replace('-', '–')}"
    if head == "part":
        return f"Part {rest.upper()}"
    if head == "rule":
        return f"Rule {rest}"
    words = pinpoint.split("-")
    return " ".join([words[0].capitalize()] + [w.upper() for w in words[1:]])


def mcgill_citation(doc: dict, pinpoint: str) -> dict:
    """{"title": italicized part, "reference": the rest, "text": plain copyable string}."""
    ref = _pinpoint_reference(pinpoint)
    if doc["kind"] == "bylaw":
        reference = f"City of {doc['citation']}, {ref}"
        return {"title": "", "reference": reference, "text": reference}
    reference = f"{doc['citation']}, {ref}"
    return {"title": doc["title"], "reference": reference, "text": f"{doc['title']}, {reference}"}
