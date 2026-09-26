from contextlib import contextmanager

import pytest

from app import tracing


class FakeObservation:
    def __init__(self, log, name):
        self.log, self.name = log, name

    def update(self, **kw):
        self.log.append(("update", self.name, sorted(kw)))


class FakeLangfuse:
    def __init__(self):
        self.log, self.stack = [], []

    @contextmanager
    def start_as_current_observation(self, name, as_type="span", **kw):
        self.log.append(("start", name, as_type))
        self.stack.append(name)
        try:
            yield FakeObservation(self.log, name)
        finally:
            self.stack.pop()

    def get_current_trace_id(self):
        return "trace-123" if self.stack else None

    def get_current_observation_id(self):
        return f"obs-{len(self.stack)}" if self.stack else None

    def update_current_generation(self, **kw):
        self.log.append(("update_current_generation", self.stack[-1], sorted(kw)))

    def get_trace_url(self, trace_id):
        return f"https://lf.example/trace/{trace_id}"

    def create_score(self, **kw):
        self.log.append(("score", kw["name"], kw["value"]))


@pytest.fixture
def fake_langfuse(monkeypatch):
    fake = FakeLangfuse()
    monkeypatch.setattr(tracing, "_client", fake)
    monkeypatch.setattr(tracing, "_checked", True)
    return fake


def test_disabled_without_keys_is_a_noop(monkeypatch):
    monkeypatch.setattr(tracing, "_client", None)
    monkeypatch.setattr(tracing, "_checked", False)
    assert tracing.client() is None
    with tracing.observe("x", input={"a": 1}) as obs:
        obs.update(output={"b": 2})
    assert tracing.current_trace_id() is None and tracing.trace_url("t") is None
    tracing.update_current_generation(model="m")  # no error


def test_observe_nests_and_reports_trace_id(fake_langfuse):
    with tracing.observe("ask"):
        with tracing.observe("generate", as_type="generation") as g:
            tracing.update_current_generation(model="m", usage_details={"input": 1})
            g.update(output={"ok": True})
        assert tracing.current_trace_id() == "trace-123"
    names = [e[1] for e in fake_langfuse.log if e[0] == "start"]
    assert names == ["ask", "generate"]


def test_update_current_generation_outside_a_span_is_skipped(fake_langfuse):
    tracing.update_current_generation(model="m")
    assert not any(e[0] == "update_current_generation" for e in fake_langfuse.log)
