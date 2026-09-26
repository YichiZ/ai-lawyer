import json
import urllib.error

import pytest

from app.jobs import Queue
from ingest import web

PAGE = b"""<html><head><title>Slip and fall claims | ontario.ca</title></head><body>
<header><nav>Menu Home Services</nav></header>
<main><div><a href="/civil">Civil</a></div><ul><li><a href="/a">Filing</a></li></ul><h1>Slips and falls on city property</h1>
<p>You must give the municipality <a href="/n">written notice</a> within 60 days.</p>
<h2>Who to notify</h2><p>Send notice to the clerk of the municipality.</p><ul><li>By registered mail</li></ul>
<script>track()</script></main><footer>Copyright</footer></body></html>"""
ROBOTS_OK = b"User-agent: *\nDisallow: /private/\n"


def fake_get(pages):
    calls = []

    def get(url):
        calls.append(url)
        if url not in pages:
            raise urllib.error.HTTPError(url, 404, "not found", {}, None)
        return pages[url]
    get.calls = calls
    return get


@pytest.mark.parametrize("url, site", [
    ("https://www.ontario.ca/page/x", "ontario.ca"),
    ("https://laws-lois.justice.gc.ca.canada.ca/x", "canada.ca"),
    ("https://www.toronto.ca/services/x", "toronto.ca"),
    ("https://scc-csc.ca/x", "scc-csc.ca"),
    ("http://www.ontario.ca/page/x", None),  # https only
    ("https://www.canlii.org/en/on/", None),  # never CanLII
    ("https://ontario.ca.evil.com/x", None),
    ("https://notontario.ca/x", None),
])
def test_allowed_domains(url, site):
    assert web.site_of(url) == site


def test_refuses_other_domains_without_any_request():
    get = fake_get({})
    with pytest.raises(web.NotAllowed, match="only https pages"):
        web.fetch_page("https://www.canlii.org/x", web.Throttle(sleep=lambda s: None), get)
    assert get.calls == []


def test_robots_txt_disallow_is_obeyed():
    get = fake_get({"https://www.ontario.ca/robots.txt": (ROBOTS_OK, "text/plain")})
    with pytest.raises(web.NotAllowed, match="robots.txt"):
        web.fetch_page("https://www.ontario.ca/private/a", web.Throttle(sleep=lambda s: None), get)
    assert get.calls == ["https://www.ontario.ca/robots.txt"]


def test_missing_robots_allows_and_forbidden_robots_refuses():
    assert web.robots_allows("https://www.ontario.ca/page/x", fake_get({})) is True

    def forbidden(url):
        raise urllib.error.HTTPError(url, 403, "forbidden", {}, None)
    assert web.robots_allows("https://www.ontario.ca/page/x", forbidden) is False


def test_throttle_spaces_requests_per_host():
    t, slept = [0.0], []
    th = web.Throttle(clock=lambda: t[0], sleep=lambda s: slept.append(round(s, 2)))
    th.wait("a")
    th.wait("b")  # other host: no wait
    t[0] = 0.3
    th.wait("a")
    assert slept == [0.7]


def test_html_sections_skip_chrome_and_split_on_headings():
    title, sections = web.html_sections(PAGE.decode())
    assert title == "Slips and falls on city property"
    assert [(s["pinpoint"], s["heading"]) for s in sections] == [("sec-1", "Introduction"), ("sec-2", "Who to notify")]
    assert sections[1]["text"] == "Send notice to the clerk of the municipality.\nBy registered mail"
    assert sections[0]["text"] == "You must give the municipality written notice within 60 days."  # menus dropped
    assert "track" not in sections[1]["text"]


def test_toronto_pages_are_excerpt_only():
    doc = web.parse_page("https://www.toronto.ca/a/b", PAGE, "text/html").document
    assert (doc["kind"], doc["reproduction"], doc["slug"]) == ("web", "excerpt", "web-toronto.ca-a-b")
    assert web.parse_page("https://www.ontario.ca/a", PAGE, "text/html").document["reproduction"] == "full"


def test_unsupported_type_is_permanent():
    with pytest.raises(web.NotAllowed) as e:
        web.parse_page("https://www.ontario.ca/a.zip", b"PK..", "application/zip")
    assert e.value.permanent


def test_end_to_end_ingest_through_the_queue(conn, tmp_path, monkeypatch):
    import redis
    client = redis.Redis(decode_responses=True)
    q = Queue(client, stream="test-ingest-e2e", group="workers")
    client.delete(q.stream, f"{q.stream}:dead")
    q.ensure_group()
    url = "https://www.ontario.ca/page/slip-and-fall-fixture"
    get = fake_get({"https://www.ontario.ca/robots.txt": (ROBOTS_OK, "text/plain"), url: (PAGE, "text/html")})
    stages = []
    jid = q.enqueue(conn, "web_page", url)
    [(entry, job_id)] = q.claim("w1", block_ms=100)

    def run(job, set_stage):
        stages_set = lambda s: (stages.append(s), set_stage(s))  # noqa: E731
        return web.ingest_web(conn, job, stages_set, tmp_path, web.Throttle(sleep=lambda s: None),
                              embed=lambda text: [0.01] * 1536, model="fake-embed", get=get)
    q.process(conn, entry, job_id, run)
    status, slug, error = conn.execute("SELECT status, document_slug, error FROM ingest_jobs WHERE id = %s",
                                       (jid,)).fetchone()
    assert (status, error) == ("done", None), error
    assert stages == ["fetch", "parse", "load", "chunk", "embed"]
    kind, n_chunks, n_embedded = conn.execute(
        "SELECT d.kind, count(c.id), count(c.embedding) FROM documents d JOIN chunks c ON c.document_id = d.id"
        " WHERE d.slug = %s GROUP BY d.kind", (slug,)).fetchone()
    assert (kind, n_chunks, n_embedded) == ("web", 2, 2)
    [line] = [json.loads(l) for l in (tmp_path / "input" / "manifest.jsonl").read_text().splitlines()]
    assert line["url"] == url and (tmp_path / line["path"]).read_bytes() == PAGE

    # idempotent by sha256: same page again leaves one manifest line and the same document
    again = web.ingest_web(conn, {"url": url}, lambda s: None, tmp_path, web.Throttle(sleep=lambda s: None),
                           embed=lambda text: [0.01] * 1536, model="fake-embed", get=get)
    assert again == slug and len((tmp_path / "input" / "manifest.jsonl").read_text().splitlines()) == 1
    client.delete(q.stream)


def test_missing_page_fails_permanently():
    get = fake_get({"https://www.ontario.ca/robots.txt": (ROBOTS_OK, "text/plain")})
    with pytest.raises(web.NotAllowed, match="HTTP 404"):
        web.fetch_page("https://www.ontario.ca/page/gone", web.Throttle(sleep=lambda s: None), get)


def test_redirect_off_allowed_domains_is_refused_before_following():
    import urllib.request
    handler = web._AllowedRedirects()
    req = urllib.request.Request("https://www.ontario.ca/page/x")
    with pytest.raises(web.NotAllowed, match="redirects off"):
        handler.redirect_request(req, None, 302, "Found", {}, "http://169.254.169.254/latest/meta-data")
    assert handler.redirect_request(req, None, 301, "Moved", {}, "https://www.ontario.ca/page/y").full_url.endswith("/y")
