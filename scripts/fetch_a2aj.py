"""Download the Ontario A2AJ law files into input/a2aj/ and record them in input/manifest.jsonl.

Run: uv run scripts/fetch_a2aj.py
Idempotent: a HEAD request reads the file's sha256 (Hugging Face x-linked-etag); unchanged files are skipped.
"""
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ingest.manifest import append_entry, needs_download, read_manifest, sha256_file  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "input" / "manifest.jsonl"
OUT_DIR = ROOT / "input" / "a2aj"
BASE = "https://huggingface.co/datasets/a2aj/canadian-laws/resolve/main"
FILES = {  # approved 2026-09-25: 64.1 MB + 63.6 MB
    "LEGISLATION-ON": "legislation-dataset",
    "REGULATIONS-ON": "regulations-dataset",
}
TIMEOUT_S = 60
HEADERS = {"User-Agent": "ai-lawyer/0.1 (portfolio research demo)"}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None  # keep the Hugging Face response, which carries x-linked-etag


def remote_sha256(url: str) -> str:
    opener = urllib.request.build_opener(NoRedirect)
    req = urllib.request.Request(url, method="HEAD", headers=HEADERS)
    try:
        resp = opener.open(req, timeout=TIMEOUT_S)
    except urllib.error.HTTPError as e:  # 302 surfaces as HTTPError when redirects are off
        resp = e
    etag = resp.headers.get("x-linked-etag", "").strip('"')
    if len(etag) != 64:
        raise RuntimeError(f"no sha256 etag for {url} (status {resp.status})")
    return etag


def download(url: str, dest: Path) -> int:
    part = dest.with_suffix(dest.suffix + ".part")
    written = 0
    with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=TIMEOUT_S) as resp, part.open("wb") as f:
        for block in iter(lambda: resp.read(1 << 20), b""):
            f.write(block)
            written += len(block)
    part.replace(dest)
    return written


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    total_bytes, added = 0, 0
    for name, doc_type in FILES.items():
        url = f"{BASE}/{name}/train.parquet"
        dest = OUT_DIR / f"{name}.parquet"
        sha = remote_sha256(url)
        if not needs_download(sha, read_manifest(MANIFEST), dest):
            print(f"[skip] {name}: unchanged ({sha[:12]})", flush=True)
            continue
        print(f"[get ] {name} -> {dest.relative_to(ROOT)}", flush=True)
        n = download(url, dest)
        got = sha256_file(dest)
        if got != sha:
            dest.unlink()
            raise RuntimeError(f"{name}: sha256 mismatch (expected {sha}, got {got}); file removed")
        total_bytes += n
        added += append_entry(MANIFEST, {
            "url": url,
            "source": "a2aj-laws",
            "title": f"A2AJ Canadian Laws: {name}",
            "jurisdiction": "ON",
            "doc_type": doc_type,
            "upstream_license": "MIT (A2AJ dataset); each row carries its own upstream_license",
            "sha256": sha,
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "path": str(dest.relative_to(ROOT)),
        })
        print(f"[ok  ] {name}: {n / 1e6:.1f} MB, sha256 {sha[:12]} verified", flush=True)
    print(f"{total_bytes / 1e6:.1f} MB downloaded, {added} new manifest lines", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
