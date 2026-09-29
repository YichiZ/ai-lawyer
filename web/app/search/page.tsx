import type { Metadata } from "next";
import Link from "next/link";
import SearchResults from "@/components/SearchResults";
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
  const { groups, askThis, error } = await search(q);
  if (error) {
    return (
      <div>
        <h1 className="font-serif text-3xl font-semibold">Search</h1>
        <p role="alert" className="mt-3 text-accent">{error}</p>
      </div>
    );
  }
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
      <SearchResults key={q} q={q} initial={groups} />
    </div>
  );
}
