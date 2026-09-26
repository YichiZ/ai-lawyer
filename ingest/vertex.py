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


def make_client() -> genai.Client:
    return genai.Client(
        vertexai=True, project=PROJECT, location=LOCATION,
        http_options=types.HttpOptions(
            timeout=TIMEOUT_MS,
            retry_options=types.HttpRetryOptions(attempts=5, initial_delay=1.0, http_status_codes=[429, 500, 503, 504]),
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
