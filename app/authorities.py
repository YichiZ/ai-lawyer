"""Which statutes/regulations a draft names, and whether its cited sources hold them (#18).

Shared by the product (run_ask labels and flags the draft) and the abstention eval (evals/suite.py).
"""
import re

SECONDARY_LABEL = ("**Statute quoted in a court decision — not in our law library.** The wording below comes from the "
                   "decision; check the current version of the statute before relying on it.")

AUTHORITY_RE = re.compile(  # capitalised words, allowing lowercase connectors ("Trespass to Property Act")
    r"\b((?:[A-Z][A-Za-z'’.,]*\s+(?:(?:to|of|and|for|the|on)\s+)?){0,6}(?:Act|Code)(?:,\s*\d{4})?)\b"
    r"|\b(O\.?\s*Reg\.?\s*\d+/\d+)", re.UNICODE)
# Leading words that aren't part of a name; determiners too, so "This Act" / "Such Act" reduce to a bare "Act".
_LEADING = re.compile(r"^(?:the|under|in|per|see|section|sections|part|and|or|to|of|for|on"
                      r"|this|that|such|any|every|each|no)\s+", re.IGNORECASE)
_YEAR = re.compile(r",\s*\d{4}$")


def norm(s: str) -> str:
    """Casefolded, straight quotes, single spaces (also used by the evals)."""
    s = s.replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'")
    return " ".join(s.casefold().split())


def _key(name: str) -> str:
    """Library match key: no dots, no year ("O. Reg. 34/10" = "O Reg 34/10", "Limitations Act" = "…, 2002")."""
    return _YEAR.sub("", " ".join(norm(name).replace(".", " ").split()))


def in_library(name: str, library_titles: list[str]) -> bool:
    """Exact on the key, not containment ("Insurance Act" must not cover the Health Insurance Act); a title that
    continues after a comma also matches ("Toronto Municipal Code" = "Toronto Municipal Code, Chapter 719, …")."""
    k = _key(name)
    return any(t == k or t.startswith(k + ",") for t in map(_key, library_titles))


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
    def key(s):  # dots dropped so "O. Reg. 239/02" matches a cited "O Reg 239/02, s 2"
        return " ".join(norm(s).replace(".", " ").split())
    titles = [key(t) for t in cited_titles]
    names = authorities_named(prose_of(draft))
    return [n for n in names if not any(key(n).rstrip(",") in t or t in key(n) for t in titles)]


def secondary_statutes(prose: str, sources: list[dict], library_titles: list[str] = ()) -> list[str]:
    """Laws the prose names that we don't hold, supported only by decisions quoting them (sources: {"title", "kind"};
    library_titles: titles/short names/citations of the laws we hold, see app.ask.library_titles)."""
    if not sources or any(s.get("kind") != "decision" for s in sources):
        return []
    return [n for n in unsourced_authorities(prose, [s["title"] for s in sources]) if not in_library(n, library_titles)]
