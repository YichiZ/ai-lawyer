"""The v0 corpus: Ontario statutes and regulations for injury law, matched to A2AJ rows by citation."""
import difflib
import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class V0Law:
    slug: str
    title: str
    citation: str
    dataset: str  # A2AJ subset: LEGISLATION-ON or REGULATIONS-ON


V0 = (
    V0Law("limitations-act-2002", "Limitations Act, 2002", "SO 2002, c 24, Sched B", "LEGISLATION-ON"),
    V0Law("negligence-act", "Negligence Act", "RSO 1990, c N1", "LEGISLATION-ON"),
    V0Law("occupiers-liability-act", "Occupiers' Liability Act", "RSO 1990, c O2", "LEGISLATION-ON"),
    V0Law("dog-owners-liability-act", "Dog Owners' Liability Act", "RSO 1990, c D16", "LEGISLATION-ON"),
    V0Law("insurance-act", "Insurance Act", "RSO 1990, c I8", "LEGISLATION-ON"),
    V0Law("statutory-accident-benefits-schedule", "Statutory Accident Benefits Schedule", "O Reg 34/10", "REGULATIONS-ON"),
    V0Law("highway-traffic-act", "Highway Traffic Act", "RSO 1990, c H8", "LEGISLATION-ON"),
    V0Law("courts-of-justice-act", "Courts of Justice Act", "RSO 1990, c C43", "LEGISLATION-ON"),
    V0Law("rules-of-civil-procedure", "Rules of Civil Procedure", "RRO 1990, Reg 194", "REGULATIONS-ON"),
    V0Law("family-law-act", "Family Law Act", "RSO 1990, c F3", "LEGISLATION-ON"),
    V0Law("city-of-toronto-act-2006", "City of Toronto Act, 2006", "SO 2006, c 11, Sched A", "LEGISLATION-ON"),
    V0Law("workplace-safety-and-insurance-act-1997", "Workplace Safety and Insurance Act, 1997", "SO 1997, c 16, Sched A", "LEGISLATION-ON"),
)


def norm_citation(s: str) -> str:
    return " ".join(s.casefold().replace(".", "").replace(",", " ").split())


def norm_title(s: str) -> str:
    s = s.casefold().replace("'", "").replace("’", "")
    return " ".join(re.sub(r"[^\w/]+", " ", s).split())


@dataclass
class Match:
    law: V0Law
    status: str  # matched | missing | title_mismatch | ambiguous
    row: dict | None = None
    candidates: list[str] = field(default_factory=list)


def match_v0(rows: list[dict], laws=V0) -> list[Match]:
    """Match each law to exactly one row by (dataset, citation); the title must agree. Never drops a law silently."""
    by_citation: dict[tuple[str, str], list[dict]] = {}
    for r in rows:
        if r.get("citation_en"):
            by_citation.setdefault((r["dataset"], norm_citation(r["citation_en"])), []).append(r)
    titles = [r["name_en"] for r in rows if r.get("name_en")]

    results = []
    for law in laws:
        hits = by_citation.get((law.dataset, norm_citation(law.citation)), [])
        if not hits:
            close = difflib.get_close_matches(law.title, titles, n=3, cutoff=0.5)
            results.append(Match(law, "missing", candidates=close))
        elif len(hits) > 1:
            results.append(Match(law, "ambiguous", candidates=[h["name_en"] for h in hits]))
        elif not norm_title(hits[0]["name_en"] or "").startswith(norm_title(law.title)):
            results.append(Match(law, "title_mismatch", row=hits[0]))
        else:
            results.append(Match(law, "matched", row=hits[0]))
    return results
