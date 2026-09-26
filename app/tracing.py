"""Langfuse Cloud tracing. Off (every call a no-op) unless LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY are set.

Sent: questions, public law text, model prompts/outputs, timings, token usage. Not sent: user identifiers beyond the
demo role name.
"""
import logging
import os
from contextlib import contextmanager
from typing import Any, Iterator

log = logging.getLogger("app.tracing")
_client: Any = None
_checked = False


class _NoopObservation:
    def update(self, **_: Any) -> None:
        pass


def client() -> Any:
    """The Langfuse client, or None when tracing is off. Checked once per process."""
    global _client, _checked
    if not _checked:
        _checked = True
        if os.environ.get("LANGFUSE_PUBLIC_KEY") and os.environ.get("LANGFUSE_SECRET_KEY"):
            from langfuse import Langfuse

            _client = Langfuse()
            log.info("Langfuse tracing on (%s)", os.environ.get("LANGFUSE_BASE_URL", "default host"))
        else:
            log.info("Langfuse tracing off: LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY not set")
    return _client


@contextmanager
def observe(name: str, as_type: str = "span", **kwargs: Any) -> Iterator[Any]:
    """Nested span/generation under the current trace (a new trace at the top level)."""
    c = client()
    if c is None:
        yield _NoopObservation()
        return
    with c.start_as_current_observation(name=name, as_type=as_type, **kwargs) as obs:
        yield obs


def update_current_generation(**kwargs: Any) -> None:
    """No-op outside an observation (e.g. offline scripts), instead of Langfuse's 'No active span' error."""
    c = client()
    if c is not None and _in_span():
        c.update_current_generation(**kwargs)


def _in_span() -> bool:
    """Is an OpenTelemetry span active? (Langfuse's own getters log an error when none is.)"""
    from opentelemetry import trace

    return trace.get_current_span().get_span_context().is_valid


def current_trace_id() -> str | None:
    c = client()
    return c.get_current_trace_id() if c is not None else None


def trace_url(trace_id: str | None) -> str | None:
    c = client()
    return c.get_trace_url(trace_id=trace_id) if c is not None and trace_id else None


def score(trace_id: str | None, name: str, value: Any, **kwargs: Any) -> None:
    c = client()
    if c is not None and trace_id:
        c.create_score(trace_id=trace_id, name=name, value=value, **kwargs)


def flush() -> None:
    c = client()
    if c is not None:
        c.flush()
