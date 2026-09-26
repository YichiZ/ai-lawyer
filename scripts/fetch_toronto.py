"""Download the approved Toronto Municipal Code chapters into input/toronto/ with manifest lines.

Run: uv run scripts/fetch_toronto.py
Approved 2026-09-25 for LOCAL INDEXING ONLY (City copyright): the UI shows excerpts + a link, never full text.
Idempotent: a HEAD request's Last-Modified is compared with the manifest; unchanged files are skipped.
"""
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ingest.manifest import append_entry, read_manifest, sha256_file  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "input" / "manifest.jsonl"
OUT_DIR = ROOT / "input" / "toronto"
CHAPTERS = {  # chapter -> title, exactly as on https://www.toronto.ca/legdocs/bylaws/lawmcode.htm
    "719": "Snow and Ice Removal",
    "743": "Streets and Sidewalks, Use of",
    "629": "Property Standards",
}
URL = "https://www.toronto.ca/legdocs/municode/1184_{}.pdf"
LICENSE = ("© City of Toronto, all rights reserved (toronto.ca/home/copyright-information). "
           "Local search index only: show short excerpts with a link to the official PDF, never the full text.")
HEADERS = {"User-Agent": "ai-lawyer/0.1 (portfolio research demo)"}
TIMEOUT_S = 60
MIN_INTERVAL_S = 1.0  # ≤ 1 request per second per domain


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    total, added, last = 0, 0, 0.0

    def polite():
        nonlocal last
        time.sleep(max(0.0, MIN_INTERVAL_S - (time.monotonic() - last)))
        last = time.monotonic()

    for chapter, title in CHAPTERS.items():
        url, dest = URL.format(chapter), OUT_DIR / f"chapter-{chapter}.pdf"
        polite()
        with urllib.request.urlopen(urllib.request.Request(url, method="HEAD", headers=HEADERS), timeout=TIMEOUT_S) as r:
            last_modified = r.headers["Last-Modified"]
        known = [e for e in read_manifest(MANIFEST) if e["url"] == url and e.get("last_modified") == last_modified]
        if known and dest.exists() and sha256_file(dest) == known[-1]["sha256"]:
            print(f"[skip] ch. {chapter}: unchanged ({last_modified})", flush=True)
            continue
        polite()
        with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=TIMEOUT_S) as r:
            data = r.read()
        if not data.startswith(b"%PDF"):
            raise RuntimeError(f"ch. {chapter}: response is not a PDF")
        dest.write_bytes(data)
        total += len(data)
        added += append_entry(MANIFEST, {
            "url": url,
            "source": "toronto-municipal-code",
            "title": f"Toronto Municipal Code, Chapter {chapter}, {title}",
            "jurisdiction": "ON-Toronto",
            "doc_type": "bylaw",
            "upstream_license": LICENSE,
            "sha256": sha256_file(dest),
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "path": str(dest.relative_to(ROOT)),
            "last_modified": last_modified,
        })
        print(f"[ok  ] ch. {chapter}: {len(data) / 1e6:.2f} MB ({last_modified})", flush=True)
    print(f"{total / 1e6:.2f} MB downloaded, {added} new manifest lines", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
