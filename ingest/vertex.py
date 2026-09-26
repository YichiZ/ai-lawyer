"""One Vertex AI client for the app (ADC, global, 30 s timeout, retries on 429/5xx) and the model names."""
import os

from google import genai
from google.genai import types

PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT", "long-indexer-507414-n0")
LOCATION = os.environ.get("GOOGLE_CLOUD_LOCATION", "global")
TIMEOUT_MS = 30_000
ANSWER_MODEL = "gemini-3.7-flash"
CHEAP_MODEL = "gemini-3.5-flash-lite"
EMBED_MODEL = "gemini-embedding-2"
EMBED_DIMS = 1536


def make_client(attempts: int = 5, initial_delay: float = 1.0, max_delay: float | None = None,
                timeout_ms: int = TIMEOUT_MS) -> genai.Client:
    """Bulk jobs (evals) pass more attempts, a longer max_delay and timeout so quota 429s and slow calls recover."""
    return genai.Client(
        vertexai=True, project=PROJECT, location=LOCATION,
        http_options=types.HttpOptions(
            timeout=timeout_ms,
            retry_options=types.HttpRetryOptions(attempts=attempts, initial_delay=initial_delay, max_delay=max_delay,
                                                 http_status_codes=[429, 500, 503, 504]),
        ),
    )


def embedder(client: genai.Client, task_type: str = "RETRIEVAL_DOCUMENT"):
    """text -> 1536-dim vector. gemini-embedding-2 takes ONE content per request (a list is merged into one vector)."""
    config = types.EmbedContentConfig(output_dimensionality=EMBED_DIMS, task_type=task_type)

    def embed(text: str) -> list[float]:
        values = client.models.embed_content(model=EMBED_MODEL, contents=text, config=config).embeddings[0].values
        if len(values) != EMBED_DIMS:
            raise ValueError(f"expected {EMBED_DIMS} dims, got {len(values)}")
        return values

    return embed


LOW_THINKING = types.ThinkingConfig(thinking_level="low")  # default thinking made grounding loop until timeout


def json_generator(client: genai.Client, model: str = ANSWER_MODEL):
    """(prompt, JSON schema) -> parsed JSON from the model, low thinking."""
    import json

    def generate(prompt: str, schema: dict) -> dict:
        r = client.models.generate_content(
            model=model, contents=prompt,
            config=types.GenerateContentConfig(
                thinking_config=LOW_THINKING, response_mime_type="application/json", response_schema=schema),
        )
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
        r = client.models.generate_content(
            model=model, contents=prompt, config=types.GenerateContentConfig(thinking_config=LOW_THINKING))
        return r.text or ""

    return generate
