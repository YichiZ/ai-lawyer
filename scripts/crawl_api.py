"""Request every law and every section; report status codes and latency.

Run: make api, then  uv run -m scripts.crawl_api                      (API JSON)
     with the web app: uv run -m scripts.crawl_api --web http://localhost:3000   (rendered pages)
"""
import statistics
import sys
import time

import httpx

API = "http://localhost:8000"
WEB = sys.argv[2] if len(sys.argv) > 2 and sys.argv[1] == "--web" else None


def main() -> int:
    with httpx.Client(base_url=API, timeout=10) as api, httpx.Client(base_url=WEB or API, timeout=30) as http:
        docs = [d for g in api.get("/laws").json()["data"] for d in g["documents"]]
        ok, bad, times = 0, [], []
        for d in docs:
            tree = api.get(f"/laws/{d['slug']}").json()["data"]["tree"]
            for node in tree:
                path = f"/laws/{d['slug']}/{node['pinpoint']}"
                t = time.perf_counter()
                r = http.get(path)
                times.append((time.perf_counter() - t) * 1000)
                if r.status_code == 200 and (WEB or r.json()["error"] is None):
                    ok += 1
                else:
                    bad.append(f"{r.status_code} {path}")
    total = ok + len(bad)
    q = statistics.quantiles(times, n=100)
    print(f"{'web' if WEB else 'api'}: {len(docs)} laws; {ok}/{total} section pages 200; p50 {q[49]:.1f} ms, p95 {q[94]:.1f} ms, max {max(times):.1f} ms")
    for b in bad[:20]:
        print("  FAIL", b)
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
