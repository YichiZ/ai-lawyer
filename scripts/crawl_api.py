"""Request every law and every section from a running API; report status codes and latency.

Run: make api (in another terminal), then uv run scripts/crawl_api.py [base_url]
"""
import statistics
import sys
import time

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"


def main() -> int:
    with httpx.Client(base_url=BASE, timeout=10) as http:
        docs = [d for g in http.get("/laws").json()["data"] for d in g["documents"]]
        ok, bad, times = 0, [], []
        for d in docs:
            tree = http.get(f"/laws/{d['slug']}").json()["data"]["tree"]
            for node in tree:
                path = f"/laws/{d['slug']}/{node['pinpoint']}"
                t = time.perf_counter()
                r = http.get(path)
                times.append((time.perf_counter() - t) * 1000)
                if r.status_code == 200 and r.json()["error"] is None:
                    ok += 1
                else:
                    bad.append(f"{r.status_code} {path}")
    total = ok + len(bad)
    q = statistics.quantiles(times, n=100)
    print(f"{len(docs)} laws; {ok}/{total} section pages 200; p50 {q[49]:.1f} ms, p95 {q[94]:.1f} ms, max {max(times):.1f} ms")
    for b in bad[:20]:
        print("  FAIL", b)
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
