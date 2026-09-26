"""Smoke-test every Vertex AI call the app depends on, using ADC.

Run: uv run -m scripts.check_vertex
"""
import json
import sys

from google.genai import types

from ingest.vertex import (
    ANSWER_MODEL,
    CHEAP_MODEL,
    EMBED_DIMS,
    EMBED_MODEL,
    LOCATION,
    LOW_THINKING,
    PROJECT,
    TIMEOUT_MS,
    make_client,
)

CHUNK = (
    "4 Unless this Act provides otherwise, a proceeding shall not be commenced in respect "
    "of a claim after the second anniversary of the day on which the claim was discovered."
)
CLAIMS_SCHEMA = {
    "type": "object",
    "properties": {"claims": {"type": "array", "items": {
        "type": "object",
        "properties": {"text": {"type": "string"}, "chunk_id": {"type": "string"}, "quote": {"type": "string"}},
        "required": ["text", "chunk_id", "quote"],
    }}},
    "required": ["claims"],
}
FIXES = {
    "RefreshError": "run: gcloud auth application-default login",
    "PERMISSION_DENIED": f"enable aiplatform.googleapis.com on {PROJECT} and grant roles/aiplatform.user",
    "NOT_FOUND": f"model not available in location '{LOCATION}'; try GOOGLE_CLOUD_LOCATION=global",
    "RESOURCE_EXHAUSTED": "quota hit; wait or request a quota increase",
}


def norm(s: str) -> str:
    return " ".join(s.split())


def generate(client, model, contents, **config):
    """Call `model` with low thinking unless overridden; the SDK retries 429/5xx."""
    config.setdefault("thinking_config", LOW_THINKING)
    cfg = types.GenerateContentConfig(**config)
    return client.models.generate_content(model=model, contents=contents, config=cfg), model


def check_generate(client, model):
    r, used = generate(client, model, "Reply with exactly: OK")
    assert r.text and "OK" in r.text, f"unexpected reply {r.text!r}"
    return f"replied OK via {used}"


def check_embedding(client, _):
    r = client.models.embed_content(
        model=EMBED_MODEL, contents=[CHUNK],
        config=types.EmbedContentConfig(output_dimensionality=EMBED_DIMS),
    )
    dims = len(r.embeddings[0].values)
    assert dims == EMBED_DIMS, f"got {dims} dims"
    return f"{dims} dims"


def check_verified_claims(client, _):
    r, used = generate(
        client, ANSWER_MODEL,
        f"[chunk c1] {CHUNK}\n\nQuestion: How long is the basic limitation period in Ontario? "
                 "Answer only from the chunk and quote it exactly.",
        response_mime_type="application/json", response_schema=CLAIMS_SCHEMA,
    )
    claims = json.loads(r.text)["claims"]
    verified = [c for c in claims if norm(c["quote"]) in norm(CHUNK)]
    assert verified, f"no quote verified in {claims}"
    return f"{len(verified)}/{len(claims)} quotes verified via {used}"


def check_search_grounding(client, _):
    r, used = generate(
        client, ANSWER_MODEL,
        "Use Google Search once: what is the official website of the Ontario Court of Appeal? One line.",
        # Default thinking over-searches until a 504; low thinking answers in ~3s.
        tools=[types.Tool(google_search=types.GoogleSearch())],
    )
    gm = r.candidates[0].grounding_metadata
    n = len(gm.grounding_chunks or []) if gm else 0
    assert n, "model did not search"
    return f"{n} web sources via {used}"


RERANK_QUERY = "I slipped on an icy sidewalk in Toronto. How soon must I tell the City?"
RERANK_PASSAGES = {
    "p1": "Dog Owners' Liability Act s. 2: the owner of a dog is liable for damages resulting from a bite or attack.",
    "p2": "Limitations Act, 2002 s. 4: no proceeding after the second anniversary of the day the claim was discovered.",
    "p3": "City of Toronto Act, 2006 s. 42(6): no action for injury from snow or ice on a sidewalk unless written notice "
          "is given to the City within 10 days after the injury.",
    "p4": "Highway Traffic Act s. 128: rate of speed limits on highways.",
}
RERANK_SCHEMA = {
    "type": "object",
    "properties": {"ranking": {"type": "array", "items": {"type": "string"}}},
    "required": ["ranking"],
}


def check_rerank(client, _):
    listing = "\n".join(f"[{pid}] {text}" for pid, text in RERANK_PASSAGES.items())
    r, _ = generate(
        client, CHEAP_MODEL,
        f"Query: {RERANK_QUERY}\n\nPassages:\n{listing}\n\n"
                 "Return every passage id ordered from most to least relevant to the query.",
        response_mime_type="application/json", response_schema=RERANK_SCHEMA,
    )
    ranking = json.loads(r.text)["ranking"]
    assert ranking and ranking[0] == "p3", f"expected p3 first, got {ranking}"
    return f"ranked {ranking}"


CHECKS = [
    (f"generate {ANSWER_MODEL}", check_generate, ANSWER_MODEL),
    (f"generate {CHEAP_MODEL}", check_generate, CHEAP_MODEL),
    (f"embed {EMBED_MODEL}", check_embedding, None),
    ("structured claims + quote verification", check_verified_claims, None),
    ("google search grounding", check_search_grounding, None),
    (f"listwise rerank {CHEAP_MODEL}", check_rerank, None),
]


def main() -> int:
    client = make_client(attempts=3)  # the app's settings: fails fast on a broken setup
    print(f"project={PROJECT or '(ADC default)'} location={LOCATION}")
    failed = 0
    for name, fn, arg in CHECKS:
        print(f"[....] {name}", flush=True)
        try:
            print(f"[pass] {name}: {fn(client, arg)}", flush=True)
        except Exception as e:  # report every failure with its fix, keep going
            failed += 1
            msg = f"{type(e).__name__}: {e}"
            fix = next((f for k, f in FIXES.items() if k in msg), "see error above")
            if "timed out" in msg.lower() or "Timeout" in msg:
                fix = f"call exceeded {TIMEOUT_MS // 1000}s; retry, or simplify the prompt"
            print(f"[fail] {name}: {msg[:300]}\n       fix: {fix}")
    print(f"{len(CHECKS) - failed}/{len(CHECKS)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
