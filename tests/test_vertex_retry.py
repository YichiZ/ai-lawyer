"""Transport errors (dropped connections) are retried with the client's attempts; nothing else is (#83)."""
from types import SimpleNamespace

import httpx
import pytest

from app import web_fallback
from ingest import vertex


class FlakyModels:
    """Raises the given errors in order, then succeeds."""

    def __init__(self, errors):
        self.errors, self.calls = list(errors), 0

    def _next(self, result):
        self.calls += 1
        if self.errors:
            raise self.errors.pop(0)
        return result

    def embed_content(self, **kw):
        return self._next(SimpleNamespace(embeddings=[SimpleNamespace(values=[0.0] * vertex.EMBED_DIMS)]))

    def generate_content(self, **kw):
        return self._next(SimpleNamespace(text='{"ok": 1}', usage_metadata=None, candidates=[]))


def client(errors, attempts=3):
    return SimpleNamespace(models=FlakyModels(errors),
                           transport_retry={"attempts": attempts, "initial_delay": 1.0, "max_delay": None})


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    slept = []
    monkeypatch.setattr(vertex.time, "sleep", slept.append)
    return slept


def read_error():
    return httpx.ReadError("[Errno 54] Connection reset by peer")


def test_transport_error_is_retried_then_succeeds(no_sleep):
    c = client([read_error(), httpx.RemoteProtocolError("server disconnected")])
    assert vertex.json_generator(c)("p", {}) == {"ok": 1}
    assert c.models.calls == 3 and len(no_sleep) == 2 and no_sleep[1] > no_sleep[0] - 1  # backoff grows (with jitter)
    c = client([read_error()])
    assert len(vertex.embedder(c)("t")) == vertex.EMBED_DIMS and c.models.calls == 2
    c = client([read_error()])
    assert vertex.text_generator(c)("p") == '{"ok": 1}' and c.models.calls == 2


def test_gives_up_after_attempts_with_the_original_error():
    err = read_error()
    c = client([err, read_error(), read_error(), read_error()])
    with pytest.raises(httpx.ReadError) as info:
        vertex.text_generator(c)("p")
    assert c.models.calls == 3 and info.value is not err  # the last attempt's error propagates


def test_non_transport_and_sdk_retried_errors_are_not_retried():
    for err in (ValueError("bad json"), httpx.ConnectError("refused"), httpx.ReadTimeout("slow")):
        c = client([err])  # ConnectError / timeouts: google-genai already retries them; don't multiply attempts
        with pytest.raises(type(err)):
            vertex.text_generator(c)("p")
        assert c.models.calls == 1


def test_single_attempt_client_is_not_retried(no_sleep):
    c = client([read_error()], attempts=1)  # the interactive rerank client: one fast attempt, then fused order
    with pytest.raises(httpx.ReadError):
        vertex.json_generator(c)("p", {})
    assert c.models.calls == 1 and no_sleep == []


def test_client_without_settings_gets_one_attempt():
    c = SimpleNamespace(models=FlakyModels([read_error()]))
    with pytest.raises(httpx.ReadError):
        vertex.text_generator(c)("p")


def test_make_client_carries_its_attempts(monkeypatch):
    monkeypatch.setattr(vertex.genai, "Client", lambda **kw: SimpleNamespace(**kw))
    assert vertex.make_client(attempts=1).transport_retry["attempts"] == 1
    assert vertex.batch_client().transport_retry == {"attempts": 8, "initial_delay": 2.0, "max_delay": 60.0}


def test_web_search_retries(monkeypatch):
    c = client([read_error()])
    assert web_fallback.search_web("q", c, "m") == ('{"ok": 1}', []) and c.models.calls == 2
