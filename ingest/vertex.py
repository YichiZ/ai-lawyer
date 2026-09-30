"""One Vertex AI client for the app (ADC, global, 30 s timeout, retries on 429/5xx and dropped connections)."""
import logging
import os
import random
import time

import httpx
from google import genai
from google.genai import types

PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT")  # None: google-genai uses the ADC project
LOCATION = os.environ.get("GOOGLE_CLOUD_LOCATION", "global")
TIMEOUT_MS = 30_000
ANSWER_MODEL = "gemini-3.7-flash"
CHEAP_MODEL = "gemini-3.5-flash-lite"
EMBED_MODEL = "gemini-embedding-2"
EMBED_DIMS = 1536
DEFAULT_MAX_DELAY = 60.0  # google-genai's own default backoff cap
# google-genai retries these itself (HttpRetryOptions); retrying them here too would multiply the attempts
SDK_RETRIED = (httpx.TimeoutException, httpx.ConnectError)

log = logging.getLogger(__name__)


def make_client(attempts: int = 5, initial_delay: float = 1.0, max_delay: float | None = None,
                timeout_ms: int = TIMEOUT_MS) -> genai.Client:
    """The app's client: ADC, 30 s timeout, retries on 429/5xx. Bulk jobs use batch_client().

    HttpRetryOptions retries status codes (and connect/timeout errors) only; the same attempts and backoff are kept
    on the client as `transport_retry` so the calls below also retry dropped connections (#83)."""
    client = genai.Client(
        vertexai=True, project=PROJECT, location=LOCATION,
        http_options=types.HttpOptions(
            timeout=timeout_ms,
            retry_options=types.HttpRetryOptions(attempts=attempts, initial_delay=initial_delay, max_delay=max_delay,
                                                 http_status_codes=[429, 500, 503, 504]),
        ),
    )
    client.transport_retry = {"attempts": attempts, "initial_delay": initial_delay, "max_delay": max_delay}
    return client


def call(client, fn):
    """fn() with retries on transport errors the SDK doesn't retry (connection reset, server disconnected).

    Exponential backoff with jitter, using the client's attempts (a client without settings gets one attempt)."""
    opts = getattr(client, "transport_retry", None) or {"attempts": 1, "initial_delay": 1.0, "max_delay": None}
    for attempt in range(1, opts["attempts"] + 1):
        try:
            return fn()
        except httpx.TransportError as e:
            if isinstance(e, SDK_RETRIED) or attempt == opts["attempts"]:
                raise
            delay = min(opts["initial_delay"] * 2 ** (attempt - 1), opts["max_delay"] or DEFAULT_MAX_DELAY)
            delay += random.uniform(0, 1)
            log.warning("Vertex call failed (%r); retry %d/%d in %.1f s", e, attempt, opts["attempts"] - 1, delay)
            time.sleep(delay)


def batch_client() -> genai.Client:
    """Bulk jobs (ingest, evals, sweeps): more retries, longer backoff and timeout, so 429s and long answers recover."""
    return make_client(attempts=8, initial_delay=2.0, max_delay=60.0, timeout_ms=60_000)


def embedder(client: genai.Client, task_type: str = "RETRIEVAL_DOCUMENT"):
    """text -> 1536-dim vector. gemini-embedding-2 takes ONE content per request (a list is merged into one vector)."""
    config = types.EmbedContentConfig(output_dimensionality=EMBED_DIMS, task_type=task_type)

    def embed(text: str) -> list[float]:
        values = call(client, lambda: client.models.embed_content(
            model=EMBED_MODEL, contents=text, config=config)).embeddings[0].values
        if len(values) != EMBED_DIMS:
            raise ValueError(f"expected {EMBED_DIMS} dims, got {len(values)}")
        return values

    return embed


LOW_THINKING = types.ThinkingConfig(thinking_level="low")  # default thinking made grounding loop until timeout


def json_generator(client: genai.Client, model: str = ANSWER_MODEL):
    """(prompt, JSON schema) -> parsed JSON from the model, low thinking."""
    import json

    def generate(prompt: str, schema: dict) -> dict:
        config = types.GenerateContentConfig(
            thinking_config=LOW_THINKING, response_mime_type="application/json", response_schema=schema)
        r = call(client, lambda: client.models.generate_content(model=model, contents=prompt, config=config))
        u = r.usage_metadata
        if u is not None:
            from app import tracing

            tracing.update_current_generation(model=model, usage_details={
                "input": u.prompt_token_count or 0, "output": u.candidates_token_count or 0,
                "thinking": u.thoughts_token_count or 0})
        return json.loads(r.text)

    return generate


def text_generator(client: genai.Client, model: str = CHEAP_MODEL):
    """prompt -> plain text, low thinking."""

    def generate(prompt: str) -> str:
        config = types.GenerateContentConfig(thinking_config=LOW_THINKING)
        r = call(client, lambda: client.models.generate_content(model=model, contents=prompt, config=config))
        return r.text or ""

    return generate
