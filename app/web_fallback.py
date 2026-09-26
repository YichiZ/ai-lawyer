"""Web fallback (Phase 6.1): opt-in Google Search grounding when our law library has no answer.

The draft is labelled as coming from the web, lists its (resolved) sources, and — like every answer — is released
only after a reviewer approves it. Quote verification does not apply to web text; the reviewer sees the flag instead.
"""
import urllib.request
from typing import Callable
from urllib.parse import urlparse

WEB_LABEL = "**From the web, not our law library.** Check each source before relying on it."
PROMPT = """Answer this research question about Ontario personal-injury law using Google Search. Prefer official
sources (ontario.ca, canada.ca, ontariocourts.ca, scc-csc.ca, toronto.ca). 2-4 plain sentences. State rules, not
advice: never say whether someone has a case, predict outcomes, value a claim, or calculate a date. If the search finds
nothing reliable, say so.

Question: {question}"""


def domain_of(url: str) -> str:
    host = urlparse(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def _head(url: str) -> str:
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "ai-lawyer/0.1 (portfolio research demo)"})
    with urllib.request.urlopen(req, timeout=5) as r:
        return r.geturl()


def resolve_url(url: str, head: Callable[[str], str] = _head) -> str:
    """Grounding URIs are vertexaisearch redirects: follow them to the real page (keep the original on failure)."""
    if "vertexaisearch" not in url:
        return url
    try:
        return head(url)
    except Exception:  # a dead redirect must not lose the answer
        return url


def compose_web_draft(answer: str, sources: list[dict]) -> str:
    if not sources:
        return f"{WEB_LABEL}\n\nThe web search returned no web sources, so there is no answer to review."
    lines = [WEB_LABEL, "", answer.strip(), "", "**Web sources**", ""]
    lines += [f"- [{s['title'] or s['domain']}]({s['url']}) ({s['domain']})" for s in sources]
    return "\n".join(lines)


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
            url = resolve_url(ch.web.uri)
            if url not in seen:
                seen.add(url)
                sources.append({"url": url, "title": ch.web.title, "domain": domain_of(url)})
    return (r.text or "").strip(), sources
