from app.authorities import SECONDARY_LABEL, authorities_named, prose_of, secondary_statutes, unsourced_authorities

CASE = {"title": "Crinson v. Toronto (City)", "kind": "decision"}
STATUTE = {"title": "Limitations Act, 2002", "kind": "statute"}


def test_authorities_named_and_unsourced():
    prose = "Under the Municipal Act, 2001, notice is due in 10 days. The Limitations Act, 2002 also applies, see O. Reg. 461/96."
    assert authorities_named(prose) == ["Municipal Act, 2001", "Limitations Act, 2002", "O. Reg. 461/96"]
    draft = prose + "\n\n**What the law says**\n\n> quote — Limitations Act, 2002"
    assert prose_of(draft) == prose + "\n\n"
    assert unsourced_authorities(draft, ["Limitations Act, 2002"]) == ["Municipal Act, 2001", "O. Reg. 461/96"]
    assert authorities_named("Under the Trespass to Property Act, force is limited.") == ["Trespass to Property Act"]


def test_secondary_statutes_only_when_every_claim_is_a_decision():
    prose = "Under s. 44(10) of the Municipal Act, 2001, notice is due within 10 days."
    assert secondary_statutes(prose, [CASE]) == ["Municipal Act, 2001"]
    assert secondary_statutes(prose, [CASE, STATUTE]) == []  # a statute source: not secondary (the eval calls it invented)
    assert secondary_statutes("The Limitations Act, 2002 applies.", [STATUTE]) == []
    assert secondary_statutes("A court held the occupier liable.", [CASE]) == []
    assert secondary_statutes(prose, []) == []


def test_label_names_no_authority():
    assert authorities_named(SECONDARY_LABEL) == []
