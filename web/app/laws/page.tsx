import type { Metadata } from "next";
import Link from "next/link";
import { KIND_LABELS, formatDate, listLaws } from "@/lib/api";

export const metadata: Metadata = { title: "Law library" };

export default async function LawLibrary() {
  const groups = (await listLaws()) ?? [];
  return (
    <div>
      <h1 className="font-serif text-3xl font-semibold">Law library</h1>
      <p className="mt-2 text-muted">Every statute, regulation and by-law in the guide.</p>
      {groups.map((group) => (
        <section key={group.kind} className="mt-10" aria-labelledby={`kind-${group.kind}`}>
          <h2 id={`kind-${group.kind}`} className="font-serif text-2xl font-semibold">
            {KIND_LABELS[group.kind]}
          </h2>
          <ul className="mt-3 divide-y divide-rule border-y border-rule">
            {group.documents.map((doc) => (
              <li key={doc.slug} className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1 py-3">
                <div>
                  <Link href={`/laws/${doc.slug}`} className="font-serif text-lg">
                    {doc.title}
                  </Link>
                  {doc.citation && <span className="pinpoint ml-3 text-sm text-muted">{doc.citation}</span>}
                </div>
                <div className="text-sm text-muted">
                  {doc.section_count} sections · as of {formatDate(doc.in_force_from)}
                  {doc.reproduction === "excerpt" && " · excerpts only"}
                </div>
              </li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}
