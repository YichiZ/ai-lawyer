from app.web_fallback import WEB_LABEL, compose_web_draft, domain_of, resolve_url


def test_resolve_url_follows_redirects_and_keeps_title():
    calls = []

    def head(url):
        calls.append(url)
        return "https://www.ontario.ca/page/slip-and-fall" if "vertexaisearch" in url else url

    assert resolve_url("https://vertexaisearch.cloud.google.com/grounding-api-redirect/abc", head) == "https://www.ontario.ca/page/slip-and-fall"
    assert resolve_url("https://www.canada.ca/x", head) == "https://www.canada.ca/x"


def test_resolve_url_failure_keeps_original():
    def boom(url):
        raise TimeoutError("slow")

    assert resolve_url("https://vertexaisearch.cloud.google.com/r/1", boom) == "https://vertexaisearch.cloud.google.com/r/1"


def test_domain_of():
    assert domain_of("https://www.ontario.ca/page/x?y=1") == "ontario.ca"
    assert domain_of("https://news.example.co.uk/a") == "news.example.co.uk"


def test_compose_web_draft_is_labelled_and_lists_sources():
    md = compose_web_draft("Ontario has a two-year limit.", [{"url": "https://www.ontario.ca/a", "title": "Limits", "domain": "ontario.ca"}])
    assert md.startswith(WEB_LABEL) and "Ontario has a two-year limit." in md
    assert "[Limits](https://www.ontario.ca/a) (ontario.ca)" in md


def test_no_sources_means_refusal():
    md = compose_web_draft("Some text.", [])
    assert "no web sources" in md.lower()
