"""Glossary term matching for tooltips: whole words, case-insensitive, longest term first, no overlaps,
each term linked once per text (the first occurrence)."""
import re


def find_terms(text: str, terms: list[str]) -> list[tuple[int, int, str]]:
    """[(start, end, term)] sorted by start."""
    if not text or not terms:
        return []
    taken: list[tuple[int, int]] = []
    found: list[tuple[int, int, str]] = []
    for term in sorted(terms, key=len, reverse=True):
        for m in re.finditer(rf"(?<![\w-]){re.escape(term)}(?![\w-])", text, re.IGNORECASE):
            if not any(m.start() < e and s < m.end() for s, e in taken):
                taken.append((m.start(), m.end()))
                found.append((m.start(), m.end(), term))
                break  # once per term
    return sorted(found)
