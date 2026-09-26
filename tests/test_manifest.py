import hashlib
import json

import pytest

from ingest.manifest import REQUIRED, append_entry, needs_download, read_manifest, sha256_file


def entry(**overrides):
    base = {
        "url": "https://huggingface.co/datasets/a2aj/canadian-laws/resolve/main/LEGISLATION-ON/train.parquet",
        "source": "a2aj-laws",
        "title": "A2AJ Canadian Laws: LEGISLATION-ON",
        "jurisdiction": "ON",
        "doc_type": "legislation-dataset",
        "upstream_license": "MIT (dataset); per-row upstream_license",
        "sha256": "a" * 64,
        "fetched_at": "2026-09-25T22:00:00+00:00",
        "path": "input/a2aj/LEGISLATION-ON.parquet",
    }
    return {**base, **overrides}


def test_append_and_read(tmp_path):
    m = tmp_path / "manifest.jsonl"
    assert append_entry(m, entry()) is True
    assert read_manifest(m) == [entry()]


def test_duplicate_sha256_not_appended(tmp_path):
    m = tmp_path / "manifest.jsonl"
    append_entry(m, entry())
    assert append_entry(m, entry(title="other")) is False
    assert len(m.read_text().splitlines()) == 1


@pytest.mark.parametrize("field", sorted(REQUIRED))
def test_missing_required_field_rejected(tmp_path, field):
    bad = entry()
    del bad[field]
    with pytest.raises(ValueError, match=field):
        append_entry(tmp_path / "manifest.jsonl", bad)


def test_bad_sha256_rejected(tmp_path):
    with pytest.raises(ValueError, match="sha256"):
        append_entry(tmp_path / "manifest.jsonl", entry(sha256="xyz"))


def test_read_missing_manifest_is_empty(tmp_path):
    assert read_manifest(tmp_path / "nope.jsonl") == []


def test_lines_are_json(tmp_path):
    m = tmp_path / "manifest.jsonl"
    append_entry(m, entry())
    append_entry(m, entry(sha256="b" * 64))
    assert [json.loads(l)["sha256"] for l in m.read_text().splitlines()] == ["a" * 64, "b" * 64]


def test_sha256_file(tmp_path):
    f = tmp_path / "x.bin"
    f.write_bytes(b"hello")
    assert sha256_file(f) == hashlib.sha256(b"hello").hexdigest()


def test_needs_download(tmp_path):
    f = tmp_path / "x.bin"
    f.write_bytes(b"hello")
    sha = hashlib.sha256(b"hello").hexdigest()
    listed = [entry(sha256=sha)]
    assert needs_download(sha, listed, f) is False  # unchanged remote, file present
    assert needs_download("c" * 64, listed, f) is True  # remote changed
    assert needs_download(sha, [], f) is True  # not in manifest
    assert needs_download(sha, listed, tmp_path / "gone.bin") is True  # file deleted
    f.write_bytes(b"tampered")
    assert needs_download(sha, listed, f) is True  # local file corrupted
