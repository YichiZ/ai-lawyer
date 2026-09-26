"""input/manifest.jsonl: one JSON line per stored file, keyed by sha256."""
import hashlib
import json
import re
from pathlib import Path

REQUIRED = frozenset(
    {"url", "source", "title", "jurisdiction", "doc_type", "upstream_license", "sha256", "fetched_at", "path"}
)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def read_manifest(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def validate(entry: dict) -> None:
    missing = sorted(f for f in REQUIRED if not entry.get(f))
    if missing:
        raise ValueError(f"manifest entry missing required fields: {', '.join(missing)}")
    if not SHA256_RE.match(entry["sha256"]):
        raise ValueError(f"manifest entry has invalid sha256: {entry['sha256']!r}")


def append_entry(path: Path, entry: dict) -> bool:
    """Append a validated entry. Returns False (and writes nothing) if its sha256 is already listed."""
    validate(entry)
    if any(e["sha256"] == entry["sha256"] for e in read_manifest(path)):
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return True


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def needs_download(remote_sha256: str, manifest: list[dict], local: Path) -> bool:
    """True unless the remote hash is already in the manifest and the local file still matches it."""
    listed = any(e["sha256"] == remote_sha256 for e in manifest)
    return not (listed and local.exists() and sha256_file(local) == remote_sha256)
