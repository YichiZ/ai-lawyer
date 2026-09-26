import type { Metadata } from "next";
import Link from "next/link";
import { search } from "@/lib/api";

export const metadata: Metadata = { title: "Search" };

type Props = { searchParams: Promise<{ q?: string }> };

export default async function SearchPage({ searchParams }: Props) {
  const q = ((await searchParams).q ?? "").trim();
  if (q.length < 2) {
    return (
      <div>
        <h1 className="font-serif text-3xl font-semibold">Search</h1>
        <p className="mt-3 text-muted">Type at least two characters in the search box.</p>
      </div>
    );
  }
  const { groups, askThis } = await search(q);
  return (
    <div className="max-w-3xl">
      <h1 className="font-serif text-3xl font-semibold">Results for “{q}”</h1>
      {askThis && (
        <p className="mt-3 rounded-sm border border-rule bg-panel p-3">
          This looks like a research question.{" "}
          <Link href={`/ask?q=${encodeURIComponent(q)}`} className="font-semibold">Ask this</Link> to get an answer with
          verified quotes after review.
        </p>
      )}
      {groups.length === 0 && <p className="mt-6 text-muted">No matching sections in the laws we cover.</p>}
      {groups.map((g) => (
        <section key={g.slug} className="mt-8" aria-labelledby={`g-${g.slug}`}>
          <h2 id={`g-${g.slug}`} className="font-serif text-xl font-semibold">
            <Link href={`/laws/${g.slug}`} className="text-ink">{g.title}</Link>
          </h2>
          <ol className="mt-2 space-y-3">
            {g.hits.map((h) => (
              <li key={h.url} className="border-l-2 border-rule pl-3">
                <Link href={h.url} className="pinpoint">{h.display}</Link>
                <p className="mt-1 text-sm text-muted">{h.snippet}</p>
              </li>
            ))}
          </ol>
        </section>
      ))}
    </div>
  );
}
