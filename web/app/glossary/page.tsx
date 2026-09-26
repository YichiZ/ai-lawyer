import type { Metadata } from "next";
import Link from "next/link";
import { getGlossary } from "@/lib/api";

export const metadata: Metadata = { title: "Glossary" };

export default async function GlossaryPage() {
  const terms = (await getGlossary()) ?? [];
  return (
    <div className="max-w-3xl">
      <h1 className="font-serif text-3xl font-semibold">Glossary</h1>
      <p className="mt-2 text-muted">Legal words used in the guide, in plain language. Definitions are AI-written from the law; the linked section is the authority.</p>
      {terms.length === 0 && <p className="mt-6">No terms yet.</p>}
      <dl className="mt-6 divide-y divide-rule border-y border-rule">
        {terms.map((t) => (
          <div key={t.term} id={t.term.replace(/\s+/g, "-")} className="py-3">
            <dt className="font-serif text-lg font-semibold">{t.term}</dt>
            <dd className="mt-1">{t.definition}</dd>
            {t.source && (
              <dd className="mt-1 text-sm"><Link href={t.source.url}>Defined in {t.source.display}</Link></dd>
            )}
          </div>
        ))}
      </dl>
    </div>
  );
}
