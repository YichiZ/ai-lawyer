"""Load test (Phase 6.3): section pages, search, suggest and /ask against a running API.

Fake model (throughput):  AI_FAKE=1 uv run uvicorn app.main:app --port 8002 --workers 4
    uv run locust -f loadtest/locustfile.py Researcher --host http://localhost:8002 --headless -u 50 -r 5 -t 3m
Real model (draft latency, low rate, `make api`):
    uv run locust -f loadtest/locustfile.py Asker --host http://localhost:8000 --headless -u 3 -r 1 -t 4m
    then read draft timings from answers.flags->'timings_ms' (see docs/iterations.md 6.3) and delete the load answers:
    DELETE FROM answers WHERE question LIKE '[load]%' 
"""
import random

from locust import HttpUser, between, task

SLUGS = ["limitations-act-2002", "occupiers-liability-act", "highway-traffic-act", "insurance-act",
         "toronto-municipal-code-743", "rules-of-civil-procedure"]
QUERIES = ["limitation period", "slip and fall ice", "dog bite owner liable", "notice to municipality",
           "motor vehicle accident benefits", "discoverability", "occupier duty of care", "snow removal sidewalk"]
QUESTIONS = ["How long do I have to sue after a car accident?", "When must the city be notified of a sidewalk fall?",
             "Is a dog owner liable for a bite?", "What duty does an occupier owe visitors?",
             "What is the deadline for accident benefits applications?"]


class Researcher(HttpUser):
    wait_time = between(1, 3)

    def on_start(self):
        self.sections = []
        for slug in SLUGS:
            r = self.client.get(f"/laws/{slug}", name="/laws/[slug]")
            if r.ok and r.json()["data"]:
                self.sections += [(slug, n["pinpoint"]) for n in r.json()["data"]["tree"] if n["kind"] == "section"]

    @task(10)
    def section_page(self):
        if self.sections:
            slug, pin = random.choice(self.sections)
            self.client.get(f"/laws/{slug}/{pin}", name="/laws/[slug]/[pinpoint]")

    @task(4)
    def suggest(self):
        q = random.choice(QUERIES)
        self.client.get(f"/suggest?q={q[:random.randint(3, len(q))]}", name="/suggest")

    @task(3)
    def search(self):
        self.client.get(f"/search?q={random.choice(QUERIES)}", name="/search")

    @task(1)
    def ask(self):
        self.client.post("/ask", json={"question": f"[load] {random.choice(QUESTIONS)}"}, name="/ask (sources)")


class Asker(HttpUser):
    """Real-model run: a few researchers asking at a low rate, so drafts measure Vertex latency, not queueing."""
    wait_time = between(10, 20)

    @task
    def ask(self):
        self.client.post("/ask", json={"question": f"[load] {random.choice(QUESTIONS)}"}, name="/ask (sources)")
