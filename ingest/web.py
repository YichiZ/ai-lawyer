"""Add-to-corpus (Phase 6.2): fetch one page from an allowed official domain, store it, parse it, load it as 'web'.

Rules: https on the allowed domains only (never CanLII), robots.txt obeyed, ≤ 1 request/s per domain, file kept in
input/web/ with a manifest line, toronto.ca stays excerpt-only (City copyright).
"""
import hashlib
import re
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
import urllib.robotparser
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from ingest.manifest import append_entry
from ingest.statutes import ParsedLaw, slugify

USER_AGENT = "ai-lawyer/0.1 (portfolio research demo)"
MAX_BYTES = 10 * 1024 * 1024
LICENCES = {  # licence note stored with each page; see each site's terms
    "ontario.ca": "© King's Printer for Ontario (ontario.ca/page/copyright-information)",
    "canada.ca": "© His Majesty the King in Right of Canada (canada.ca/en/transparency/terms)",
    "ontariocourts.ca": "© Court of Appeal / Superior Court of Justice for Ontario (site terms)",
    "scc-csc.ca": "© Supreme Court of Canada (scc-csc.ca terms and conditions)",
    "toronto.ca": "© City of Toronto, all rights reserved (toronto.ca/home/copyright-information). "
                  "Local search index only: show short excerpts with a link to the official page.",
}
ALLOWED_DOMAINS = tuple(LICENCES)
EXCERPT_DOMAINS = ("toronto.ca",)
PARSER_VERSION = 1  # in the document hash: a parser change reloads pages already in the library


class NotAllowed(ValueError):
    """The URL may not be fetched (domain, scheme, robots.txt or type); never retried."""
    permanent = True


def site_of(url: str) -> str | None:
    """The allowed domain this https URL belongs to (subdomains included), else None."""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https":
        return None
    return next((d for d in ALLOWED_DOMAINS if host == d or host.endswith("." + d)), None)


class _AllowedRedirects(urllib.request.HTTPRedirectHandler):
    """Refuse a redirect off the allowed domains before it is requested."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if site_of(newurl) is None:
            raise NotAllowed(f"{req.full_url} redirects off the allowed domains to {newurl}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_opener = urllib.request.build_opener(_AllowedRedirects)


def _get(url: str, timeout: float = 20) -> tuple[bytes, str]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with _opener.open(req, timeout=timeout) as r:
        body = r.read(MAX_BYTES + 1)
        if len(body) > MAX_BYTES:
            raise ValueError(f"page larger than {MAX_BYTES} bytes")
        return body, r.headers.get_content_type()


class Throttle:
    """≤ 1 request per second per host, across the worker's threads."""
    # ponytail: per-process only; one worker process is the design. Move to Redis (SET NX PX) if workers scale out.

    def __init__(self, interval: float = 1.0, clock=time.monotonic, sleep=time.sleep):
        self.interval, self.clock, self.sleep = interval, clock, sleep
        self.last: dict[str, float] = {}
        self.lock = threading.Lock()

    def wait(self, host: str) -> None:
        with self.lock:
            now = self.clock()
            delay = self.last.get(host, -self.interval) + self.interval - now
            if delay > 0:
                self.sleep(delay)
            self.last[host] = max(now, now + delay)


def robots_allows(url: str, get: Callable[[str], tuple[bytes, str]]) -> bool:
    parsed = urlparse(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    rp = urllib.robotparser.RobotFileParser(robots_url)
    try:
        body, _ = get(robots_url)
    except urllib.error.HTTPError as e:
        return e.code in (404, 410)  # no robots.txt: allowed; 401/403/5xx: treat as disallowed
    rp.parse(body.decode("utf-8", "replace").splitlines())
    return rp.can_fetch(USER_AGENT, url)


class _Text(HTMLParser):
    """Headings + block text from <main> (or <body>), skipping nav/header/footer/script/style and link-only blocks
    (menus, tables of contents: a block whose text is all link text)."""
    SKIP = {"script", "style", "nav", "header", "footer", "noscript", "svg", "form", "aside"}
    BLOCK = {"p", "li", "td", "th", "dd", "dt", "div", "section", "article", "br", "tr", "blockquote"}
    HEADING = {"h1", "h2", "h3"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title, self.items, self.buf = "", [], []  # items: ("h1"|"h2"|"h3"|"p", text)
        self.skip = self.in_link = 0
        self.link_text: list[str] = []
        self.in_title = False
        self.tag = "p"

    def _flush(self):
        text = " ".join("".join(self.buf).split())
        link_only = text == " ".join("".join(self.link_text).split())
        if text and (self.tag != "p" or not link_only):
            self.items.append((self.tag, text))
        self.buf, self.link_text, self.tag = [], [], "p"

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
        elif tag == "title":
            self.in_title = True
        elif tag == "a":
            self.in_link += 1
        elif tag in self.HEADING or tag in self.BLOCK:
            self._flush()
            if tag in self.HEADING:
                self.tag = tag

    def handle_endtag(self, tag):
        if tag in self.SKIP:
            self.skip = max(0, self.skip - 1)
        elif tag == "title":
            self.in_title = False
        elif tag == "a":
            self.in_link = max(0, self.in_link - 1)
        elif tag in self.HEADING or tag in self.BLOCK:
            self._flush()

    def handle_data(self, data):
        if self.in_title:
            self.title += data
        elif not self.skip:
            self.buf.append(data)
            if self.in_link:
                self.link_text.append(data)


def html_sections(html: str) -> tuple[str, list[dict]]:
    """(title, sections): one section per h2/h3 heading (text before the first heading is the introduction)."""
    main = re.search(r"<main\b.*?</main>", html, re.S | re.I)
    page = _Text()
    page.feed(html if not main else html[: html.lower().find("<body")] + main.group(0))
    page._flush()
    h1 = next((t for tag, t in page.items if tag == "h1"), "")
    title = h1 or " ".join(page.title.split()).split(" - ")[0].split(" | ")[0]
    groups: list[tuple[str, list[str]]] = [("Introduction", [])]
    for tag, text in page.items:
        if tag in ("h2", "h3"):
            groups.append((text, []))
        elif tag == "p":
            groups[-1][1].append(text)
    return title, _sections(groups)


def pdf_sections(pdf: bytes) -> tuple[str, list[dict]]:
    """(title, sections): one section per PDF page; the title is the first non-empty line."""
    with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
        f.write(pdf)
        f.flush()
        text = subprocess.run(["pdftotext", "-layout", f.name, "-"], capture_output=True, text=True, check=True).stdout
    pages = [[" ".join(line.split()) for line in page.split("\n") if line.strip()] for page in text.split("\f")]
    title = next((line for page in pages for line in page), "")
    return title, _sections([(f"Page {i}", lines) for i, lines in enumerate(pages, 1)], prefix="page")


def _sections(groups: list[tuple[str, list[str]]], prefix: str = "sec") -> list[dict]:
    out = []
    for heading, lines in groups:
        if lines:
            n = len(out) + 1 if prefix == "sec" else int(heading.split()[-1])
            out.append({"pinpoint": f"{prefix}-{n}", "kind": "section", "heading": heading, "text": "\n".join(lines),
                        "parent": None, "sort_order": len(out) + 1})
    return out


def parse_page(url: str, body: bytes, content_type: str) -> ParsedLaw:
    site = site_of(url)
    if content_type == "application/pdf" or body[:5] == b"%PDF-":
        title, sections = pdf_sections(body)
    elif content_type in ("text/html", "application/xhtml+xml"):
        title, sections = html_sections(body.decode("utf-8", "replace"))
    else:
        raise NotAllowed(f"unsupported content type {content_type!r} (HTML or PDF only)")
    if not sections:
        raise ValueError("no text found on the page")
    parsed = urlparse(url)
    title = title or parsed.path.rsplit("/", 1)[-1] or site
    document = {
        "sha256": hashlib.sha256(body + f"\nparser {PARSER_VERSION}".encode()).hexdigest(), "kind": "web",
        "slug": ("web-" + slugify(f"{parsed.hostname.removeprefix('www.')} {parsed.path}"))[:120].rstrip("-"),
        "title": title, "short_name": title[:80], "citation": f"online: {site} <{url}>",
        "jurisdiction": "CA" if site in ("canada.ca", "scc-csc.ca") else "ON", "url": url, "source": f"web:{site}",
        "date": datetime.now(ZoneInfo("America/Toronto")).date(),  # fetched on; shown where laws show "as of"
        "upstream_license": LICENCES[site], "reproduction": "excerpt" if site in EXCERPT_DOMAINS else "full",
    }
    return ParsedLaw(document, sections)


def store(root: Path, url: str, body: bytes, content_type: str, title: str) -> Path:
    """Keep the fetched file in input/web/ and list it in the manifest (skipped if its sha256 is already there)."""
    sha = hashlib.sha256(body).hexdigest()
    ext = "pdf" if content_type == "application/pdf" or body[:5] == b"%PDF-" else "html"
    path = root / "input" / "web" / f"{sha}.{ext}"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_bytes(body)
    append_entry(root / "input" / "manifest.jsonl", {
        "url": url, "source": f"web:{site_of(url)}", "title": title, "jurisdiction": "ON", "doc_type": "web-page",
        "upstream_license": LICENCES[site_of(url)], "sha256": sha,
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "path": str(path.relative_to(root)),
    })
    return path


def fetch_page(url: str, throttle: Throttle, get: Callable[[str], tuple[bytes, str]] = _get) -> tuple[bytes, str]:
    """Check the domain and robots.txt, then fetch — each request throttled per host."""
    if site_of(url) is None:
        raise NotAllowed(f"only https pages on {', '.join(ALLOWED_DOMAINS)} can be added")
    host = urlparse(url).hostname

    def throttled(u: str) -> tuple[bytes, str]:
        throttle.wait(host)
        return get(u)

    if not robots_allows(url, throttled):
        raise NotAllowed(f"robots.txt on {host} disallows {url}")
    try:
        return throttled(url)
    except urllib.error.HTTPError as e:
        if 400 <= e.code < 500 and e.code != 429:  # missing or forbidden page: retrying cannot help
            raise NotAllowed(f"{url} returned HTTP {e.code}") from e
        raise


def ingest_web(conn, job: dict, set_stage: Callable[[str], None], root: Path, throttle: Throttle,
               embed: Callable[[str], list[float]], model: str, get=_get) -> str:
    """The worker's job body: fetch → store → parse → load → chunk → embed. Returns the document slug."""
    from ingest.chunks import embed_pending, plan_chunks, sync_chunks
    from ingest.statutes import load_document

    set_stage("fetch")
    body, content_type = fetch_page(job["url"], throttle, get)
    set_stage("parse")
    parsed = parse_page(job["url"], body, content_type)
    store(root, job["url"], body, content_type, parsed.document["title"])
    set_stage("load")
    load_document(conn, parsed)  # unchanged when this sha256 is already loaded
    doc_id, title = conn.execute("SELECT id, title FROM documents WHERE slug = %s", (parsed.document["slug"],)).fetchone()
    rows = conn.execute("SELECT id, pinpoint, kind, heading, text FROM sections WHERE document_id = %s ORDER BY sort_order",
                        (doc_id,)).fetchall()
    sections = [dict(zip(("id", "pinpoint", "kind", "heading", "text"), r), parent=None) for r in rows]
    set_stage("chunk")
    sync_chunks(conn, doc_id, plan_chunks(title, sections))
    set_stage("embed")
    embed_pending(conn, embed, model, workers=4)
    return parsed.document["slug"]
