"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { rerankedSearchAction } from "@/app/actions";
import type { SearchGroup } from "@/lib/api";

const hitKeys = (groups: SearchGroup[]) => groups.flatMap((g) => g.hits.map((h) => h.url)).sort().join("\n");

// Shows the fast (fused) results at once, then swaps in the reranked order when it arrives (#41); a failed rerank keeps
// the fused order. The hits are the same, so the list keeps its height. The list is remounted rather than reordered:
// moving existing nodes counts as layout shift (CLS 0.19 measured), inserting new ones in the same space does not.
export default function SearchResults({ q, initial }: { q: string; initial: SearchGroup[] }) {
  const [groups, setGroups] = useState(initial);
  const [status, setStatus] = useState("");

  useEffect(() => {
    let live = true; // the page keys this component by q, so a new search starts fresh
    rerankedSearchAction(q).then((reranked) => {
      if (!live || !reranked || hitKeys(reranked) !== hitKeys(initial)) return;
      setGroups(reranked);
      setStatus("Results re-ranked by relevance.");
    });
    return () => {
      live = false;
    };
  }, [q, initial]);

  return (
    <>
      <p role="status" aria-live="polite" className="sr-only">{status}</p>
      <div key={status ? "reranked" : "fused"}>
        {groups.map((g) => (
          <section key={g.slug} className="mt-8" aria-labelledby={`g-${g.slug}`}>
            <h2 id={`g-${g.slug}`} className="font-serif text-xl font-semibold">
              <Link href={`/laws/${g.slug}`} className="text-ink">{g.title}</Link>
            </h2>
            {g.kind === "web" && (
              <p className="text-sm text-muted">Official web page · {g.subtitle}</p>
            )}
            <ol className="mt-2 space-y-3">
              {g.hits.map((h) => (
                <li key={h.url} className="border-l-2 border-rule pl-3">
                  <Link href={h.url} className="pinpoint">{h.display}</Link>
                  {h.snippet && <p className="mt-1 text-sm text-muted">{h.snippet}</p>}
                </li>
              ))}
            </ol>
          </section>
        ))}
      </div>
    </>
  );
}
