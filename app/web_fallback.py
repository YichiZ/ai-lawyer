"""Web fallback (Phase 6.1): opt-in Google Search grounding when our law library has no answer.

The draft is labelled as coming from the web; its (resolved) sources are stored in `flags.web_sources` and shown as
links beside the text, never inside it (#62). Like every answer, it is released only after a reviewer approves it.
Quote verification does not apply to web text; the reviewer sees the flag instead.
"""
import re
import urllib.error
import urllib.request
from typing import Callable
from urllib.parse import urljoin, urlparse

WEB_LABEL = "**From the web, not our law library.** Check each source before relying on it."
PROMPT = """Answer this research question about Ontario personal-injury law using Google Search. Prefer official
sources (ontario.ca, canada.ca, ontariocourts.ca, scc-csc.ca, toronto.ca). 2-4 plain sentences. State rules, not
advice: never say whether someone has a case, predict outcomes, value a claim, or calculate a date. If the search finds
nothing reliable, say so.

Question: {question}"""


def domain_of(url: str) -> str:
    host = urlparse(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None  # urllib then raises the 3xx as an HTTPError, headers included


def _head(url: str) -> str:
    """The redirector's Location header. The target site is never contacted (many answer HEAD with 405)."""
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "ai-lawyer/0.1 (portfolio research demo)"})
    try:
        urllib.request.build_opener(_NoRedirect).open(req, timeout=5).close()
    except urllib.error.HTTPError as e:
        e.close()  # the error wraps the open response
        if 300 <= e.code < 400 and e.headers.get("Location"):
            return urljoin(url, e.headers["Location"])
        raise
    raise ValueError(f"no redirect from {url}")


def resolve_url(url: str, head: Callable[[str], str] = _head) -> str | None:
    """Grounding URIs are vertexaisearch redirects: resolve them to the real page, or None to drop the source."""
    if "vertexaisearch" not in url:
        return url
    try:
        resolved = head(url)
    except Exception:  # a dead redirect drops one source, not the answer
        return None
    return None if "vertexaisearch" in resolved else resolved


def is_web_url(url: str) -> bool:
    """Only http(s) pages with a host are ever rendered as links (never javascript:, data: …)."""
    try:
        u = urlparse(url)
    except ValueError:
        return False
    return u.scheme in ("http", "https") and bool(u.netloc)


def web_links(sources: list[dict]) -> list[dict]:
    return [{"url": s["url"], "title": s.get("title") or "", "domain": s.get("domain") or domain_of(s["url"])}
            for s in sources if isinstance(s.get("url"), str) and is_web_url(s["url"])]


# Drafts written before #62 ended with the source list as markdown links, which the site renders as raw text.
_SOURCE_BLOCK = re.compile(r"\n*\*\*Web sources\*\*\n(?:[ \t]*\n|- .*(?:\n|$))*\Z")


def strip_source_list(markdown: str | None) -> str | None:
    """Drop a stored draft's trailing "**Web sources**" link list (read time; idempotent)."""
    return _SOURCE_BLOCK.sub("", markdown) if markdown else markdown


def compose_web_draft(answer: str, sources: list[dict]) -> str:
    if not sources:
        return f"{WEB_LABEL}\n\nThe web search returned no web sources, so there is no answer to review."
    return f"{WEB_LABEL}\n\n{answer.strip()}"


def search_web(question: str, client, model: str) -> tuple[str, list[dict]]:
    """(answer text, [{url, title, domain}]) from gemini + Google Search grounding (low thinking)."""
    from google.genai import types

    r = client.models.generate_content(
        model=model, contents=PROMPT.format(question=question),
        config=types.GenerateContentConfig(tools=[types.Tool(google_search=types.GoogleSearch())],
                                           thinking_config=types.ThinkingConfig(thinking_level="low")),
    )
    gm = r.candidates[0].grounding_metadata if r.candidates else None
    sources, seen = [], set()
    for ch in (gm.grounding_chunks or []) if gm else []:
        if ch.web and ch.web.uri:
            url = resolve_url(ch.web.uri, _head)
            if url and is_web_url(url) and url not in seen:
                seen.add(url)
                sources.append({"url": url, "title": ch.web.title, "domain": domain_of(url)})
    return (r.text or "").strip(), sources
