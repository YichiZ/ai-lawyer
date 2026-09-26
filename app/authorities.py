"""Which statutes/regulations a draft names, and whether its cited sources hold them (#18).

Shared by the product (run_ask labels and flags the draft) and the abstention eval (evals/suite.py).
"""
import re

SECONDARY_LABEL = ("**Statute quoted in a court decision — not in our law library.** The wording below comes from the "
                   "decision; check the current version of the statute before relying on it.")

AUTHORITY_RE = re.compile(  # capitalised words, allowing lowercase connectors ("Trespass to Property Act")
    r"\b((?:[A-Z][A-Za-z'’.,]*\s+(?:(?:to|of|and|for|the|on)\s+)?){0,6}(?:Act|Code)(?:,\s*\d{4})?)\b"
    r"|\b(O\.?\s*Reg\.?\s*\d+/\d+)", re.UNICODE)
_LEADING = re.compile(r"^(?:the|under|in|per|see|section|sections|part|and|or|to|of|for|on)\s+", re.IGNORECASE)


def _norm(s: str) -> str:
    s = s.replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'")
    return " ".join(s.casefold().split())


def prose_of(draft: str) -> str:
    """The model's own words: everything before the quoted-law block."""
    return (draft or "").split("**What the law says**")[0]


def authorities_named(text: str) -> list[str]:
    out = []
    for m in AUTHORITY_RE.finditer(text or ""):
        name = (m.group(1) or m.group(2)).strip()
        while (stripped := _LEADING.sub("", name)) != name:
            name = stripped
        if len(name.split()) >= 2 or name.lower().startswith("o"):
            out.append(name)
    return list(dict.fromkeys(out))


def unsourced_authorities(draft: str, cited_titles: list[str]) -> list[str]:
    """Statutes/regulations the prose names that none of the cited sources is."""
    titles = [_norm(t) for t in cited_titles]
    names = authorities_named(prose_of(draft))
    return [n for n in names if not any(_norm(n).rstrip(",") in t or t in _norm(n) for t in titles)]


def secondary_statutes(prose: str, sources: list[dict]) -> list[str]:
    """Laws the prose names that are supported only by decisions quoting them (sources: {"title", "kind"})."""
    if not sources or any(s.get("kind") != "decision" for s in sources):
        return []
    return unsourced_authorities(prose, [s["title"] for s in sources])
