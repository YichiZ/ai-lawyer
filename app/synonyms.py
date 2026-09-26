"""Everyday → legal term expansion for the keyword retriever only (the vector query is left as typed)."""
import re
from pathlib import Path

PATH = Path(__file__).with_name("synonyms.tsv")


def _load(path: Path) -> dict[str, list[str]]:
    out = {}
    for line in path.read_text().splitlines():
        if line.strip() and not line.startswith("#"):
            phrase, terms = line.split("\t", 1)
            out[phrase.strip().lower()] = [t.strip() for t in terms.split(";") if t.strip()]
    return out


SYNONYMS = _load(PATH)
_PATTERNS = [(re.compile(rf"\b{re.escape(p)}\b", re.IGNORECASE), terms) for p, terms in SYNONYMS.items()]


def expand(question: str) -> str:
    """The question plus the legal terms of every phrase it contains (each phrase once, no chaining)."""
    extra: list[str] = []
    for pattern, terms in _PATTERNS:
        if pattern.search(question):
            extra += [t for t in terms if t not in extra]
    return question if not extra else f"{question} {' '.join(extra)}"
