Build this project in iterations. Read CLAUDE.md and docs/design.md first; they are the spec and the rules.

Start with Phase 1 from the milestones table in docs/design.md, broken into iterations of at most ~1 hour each. Propose the iteration list for Phase 1 first (each with its exit criterion) and wait for my OK.

For every iteration, follow the loop in CLAUDE.md exactly:
1. Plan — name the iteration and its exit criterion.
2. Implement — smallest change that meets it.
3. Test — write tests first where there is logic; run them and show the output.
4. Validate — run the real thing end to end (app, script, or `make eval`) and show the result against the exit criterion. Don't claim done without output.
5. Record — append to docs/iterations.md and add any lesson to CLAUDE.md "Lessons learned".

Then stop, summarize in 3 lines (done / numbers / next), and wait for "next" before starting the following iteration.

Session start, every time: run `uv run scripts/check_vertex.py`. If a check fails, fix that first (if it's auth, ask me to run `gcloud auth application-default login`).

Constraints: ask before adding a dependency, changing the stack, or downloading anything from the web (show file, URL, size). Never bulk-download from CanLII. No API keys — Vertex AI via ADC only.
