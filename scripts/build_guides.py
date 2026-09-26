"""Phase 4.4: create the 5 topic guides. Each section question is drafted by the /ask pipeline (retrieve, rerank,
generate, verify) and lands in the review queue; the guide shows a section only after a reviewer approves it.
Idempotent: existing sections are skipped. --retry-failed re-drafts sections whose draft failed (Vertex 504/429)
and removes the failed placeholder answer (never reviewed; the builder created it).

Run: uv run --env-file .env scripts/build_guides.py [--retry-failed]
"""
import os
import sys
from pathlib import Path

import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import ask  # noqa: E402
from app.main import VertexAI, draft_answer  # noqa: E402
from app.rerank import RERANK_CANDIDATES  # noqa: E402
from ingest.vertex import json_generator, make_client  # noqa: E402

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://postgres:dev@localhost:5432/ai_lawyer")
GUIDES = [  # slug, title, intro, [(heading, question)] — deadlines first, stated as rules
    ("motor-vehicle-accidents", "Motor vehicle accidents", "Accident benefits from your own insurer, and suing the at-fault driver.", [
        ("Deadlines", "What are the time limits after a car accident in Ontario to dispute accident benefits and to sue?"),
        ("Suing for pain and suffering", "What injury threshold must be met to sue for pain and suffering after a car accident?"),
        ("Owner liability", "When is a vehicle owner liable for a crash caused by someone else driving their car?"),
    ]),
    ("slip-and-fall", "Slip and fall on private property", "Injuries on someone else's premises under the Occupiers' Liability Act.", [
        ("Deadlines", "What written notice must be given after slipping on snow or ice on private property, and how soon?"),
        ("The occupier's duty", "What duty of care does an occupier owe to people on their premises?"),
        ("Lower duties", "When does an occupier owe a lower duty, such as to trespassers or on recreational trails?"),
    ]),
    ("claims-against-the-city", "Claims against the City of Toronto", "Injuries from roads, sidewalks and bridges the City maintains.", [
        ("Deadlines", "How soon must written notice be given to the City of Toronto after an injury on a road or sidewalk?"),
        ("Snow and ice", "When is the City of Toronto liable for injuries from snow or ice on a sidewalk?"),
        ("Property owners' duties", "What must Toronto property owners do about snow and ice on the sidewalk?"),
    ]),
    ("dog-bites", "Dog bites", "Owner liability under the Dog Owners' Liability Act.", [
        ("Deadlines", "What is the basic limitation period for suing after a dog bite in Ontario?"),
        ("When the owner is liable", "When is a dog owner liable for a bite or attack?"),
        ("The victim's own conduct", "How can the victim's own fault or negligence affect damages for a dog bite?"),
    ]),
    ("limitation-periods", "Limitation periods", "How long you have to start a claim in Ontario.", [
        ("The basic period", "What is the basic limitation period for a claim in Ontario?"),
        ("Discovery", "When is a claim considered discovered under the Limitations Act, 2002?"),
        ("Minors and incapable persons", "When does the limitation period not run for minors or incapable persons?"),
        ("The ultimate period", "What is the ultimate limitation period in Ontario?"),
    ]),
]


def draft(conn, connect, ai, generate, question: str) -> int:
    candidates = ask.retrieve(conn, question, ai.embed_query(question), top_k=RERANK_CANDIDATES)
    answer_id = ask.create_pending(conn, question, None, candidates[:ask.TOP_K], {"sources": 0}, None)
    draft_answer(connect, answer_id, question, candidates, generate, None, ai.rerank)
    return answer_id


def status_of(conn, answer_id: int) -> str:
    return conn.execute("SELECT flags->>'status' FROM answers WHERE id = %s", (answer_id,)).fetchone()[0]


def main() -> int:
    ai = VertexAI()
    # batch job: patient generation client (the app's interactive one gives up after 30 s)
    generate = json_generator(make_client(attempts=8, initial_delay=2.0, max_delay=60.0, timeout_ms=60_000))
    connect = lambda: psycopg.connect(DATABASE_URL, autocommit=True)
    created = 0
    with connect() as conn:
        if "--retry-failed" in sys.argv:
            failed = conn.execute(
                "SELECT gs.id, gs.guide_slug, gs.heading, gs.question, gs.answer_id FROM guide_sections gs"
                " JOIN answers a ON a.id = gs.answer_id WHERE a.flags->>'status' = 'failed' AND a.status = 'pending_review'"
            ).fetchall()
            for sid, slug, heading, question, old in failed:
                new = draft(conn, connect, ai, generate, question)
                conn.execute("UPDATE guide_sections SET answer_id = %s WHERE id = %s", (new, sid))
                conn.execute("DELETE FROM answers WHERE id = %s", (old,))
                print(f"[{status_of(conn, new):<9}] retried {slug} / {heading} -> answer {new} (removed failed {old})", flush=True)
            return 0
        for order, (slug, title, intro, sections) in enumerate(GUIDES, 1):
            conn.execute("INSERT INTO guides (slug, title, intro, sort_order) VALUES (%s, %s, %s, %s)"
                         " ON CONFLICT (slug) DO UPDATE SET title = EXCLUDED.title, intro = EXCLUDED.intro,"
                         " sort_order = EXCLUDED.sort_order", (slug, title, intro, order))
            for s_order, (heading, question) in enumerate(sections, 1):
                if conn.execute("SELECT 1 FROM guide_sections WHERE guide_slug = %s AND heading = %s", (slug, heading)).fetchone():
                    continue
                answer_id = draft(conn, connect, ai, generate, question)
                conn.execute("INSERT INTO guide_sections (guide_slug, heading, question, answer_id, sort_order)"
                             " VALUES (%s, %s, %s, %s, %s)", (slug, heading, question, answer_id, s_order))
                print(f"[{status_of(conn, answer_id):<9}] {slug} / {heading} -> answer {answer_id}", flush=True)
                created += 1
    print(f"{created} guide sections drafted; approve them in /review to publish", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
