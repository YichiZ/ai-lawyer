from app.synonyms import SYNONYMS, expand


def test_expands_phrases_on_word_boundaries():
    assert "limitation period" in expand("How long do I have to sue?")
    assert "proceeding" in expand("How long do I have to sue?")
    assert "occupier" in expand("I slipped at a store")


def test_no_partial_word_matches():
    assert "proceeding" not in expand("the issue was pursued")  # "sue" inside "issue"/"pursued"
    assert expand("citywide policy") == "citywide policy"      # "city" inside "citywide"


def test_multiword_and_case_insensitive():
    out = expand("Was I Partly To Blame?")
    assert "contributory negligence" in out and out.startswith("Was I Partly To Blame?")


def test_each_phrase_expanded_once_and_legal_terms_not_reexpanded():
    out = expand("sue sue sue")
    assert out.count("proceeding") == 1
    assert "municipality" not in expand("the occupier")  # expansions never trigger further expansions


def test_file_loaded():
    assert len(SYNONYMS) >= 50 and SYNONYMS["time limit"] == ["limitation period"]
