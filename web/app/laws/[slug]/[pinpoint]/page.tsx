import type { Metadata } from "next";
import Link from "next/link";
import { Fragment } from "react";
import { notFound } from "next/navigation";
import { asOf, getSection, sourceLabel } from "@/lib/api";
import CopyCitation from "./CopyCitation";

type Props = { params: Promise<{ slug: string; pinpoint: string }> };

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { slug, pinpoint } = await params;
  const s = await getSection(slug, pinpoint);
  return { title: s ? `${s.document.short_name ?? s.document.title} ${s.display}` : "Not found" };
}

export default async function SectionPage({ params }: Props) {
  const { slug, pinpoint } = await params;
  const s = await getSection(slug, pinpoint);
  if (!s) notFound();
  const doc = s.document;

  return (
    <article>
      <nav aria-label="Breadcrumb" className="text-sm">
        <ol className="flex flex-wrap gap-x-2">
          <li><Link href="/laws">Law library</Link> /</li>
          <li><Link href={`/laws/${slug}`}>{doc.short_name ?? doc.title}</Link>{s.breadcrumb.length > 0 && " /"}</li>
          {s.breadcrumb.map((b, i) => (
            <li key={b.pinpoint}>
              <Link href={`/laws/${slug}/${b.pinpoint}`}>{b.kind === "part" ? b.heading : b.display}</Link>
              {i < s.breadcrumb.length - 1 && " /"}
            </li>
          ))}
        </ol>
      </nav>

      <header className="mt-4">
        <p className="pinpoint text-lg text-primary">{s.display}</p>
        <h1 className="font-serif text-3xl font-semibold">{s.heading ?? doc.title}</h1>
      </header>

      <p className="mt-3 text-sm text-muted">
        {s.full_text ? "Unofficial copy of the official text" : "Excerpt only"} {asOf(doc)} ·
        Source: {sourceLabel(doc)}
        {doc.url && (
          <>
            {" · "}
            <a href={doc.url}>Official version</a>
          </>
        )}
      </p>

      {s.plain_summary && (
        <aside aria-labelledby="summary-heading" className="mt-6 max-w-[68ch] border-l-2 border-primary pl-4">
          <h2 id="summary-heading" className="text-sm font-semibold">In plain language</h2>
          <p className="mt-1">{s.plain_summary}</p>
          <p className="mt-1 text-xs text-muted">AI-written, checked against the official text. Not legal advice.</p>
        </aside>
      )}

      {s.kind === "part" ? (
        <ul className="mt-6">
          {s.children.map((c) => (
            <li key={c.pinpoint} className="py-1">
              <Link href={`/laws/${slug}/${c.pinpoint}`} className="grid grid-cols-[7rem_1fr] gap-3">
                <span className="pinpoint text-sm">{c.display}</span>
                <span>{c.heading}</span>
              </Link>
            </li>
          ))}
        </ul>
      ) : (
        <div className="mt-6 rounded-sm border border-rule bg-panel px-5 py-5">
          <div className="law-text">
            {s.lines.map((line, i) => (
              <Fragment key={i}>
                {line.note && <p className="marginal-note">{line.note}</p>}
                <p data-level={line.level}>{line.text}</p>
              </Fragment>
            ))}
          </div>
          {!s.full_text && (
            <p className="mt-4 border-t border-rule pt-3 text-sm">
              The City of Toronto does not permit reproducing the Municipal Code, so only an excerpt is shown.{" "}
              {doc.url && <a href={doc.url}>Read the full chapter on toronto.ca</a>}
            </p>
          )}
        </div>
      )}

      {s.glossary.length > 0 && (
        <section aria-labelledby="terms-heading" className="mt-6 max-w-[68ch]">
          <h2 id="terms-heading" className="text-sm font-semibold">Terms used here</h2>
          <dl className="mt-2 space-y-2 text-sm">
            {s.glossary.map((g) => (
              <div key={g.term}>
                <dt className="font-semibold">{g.term}</dt>
                <dd className="text-muted">{g.definition}</dd>
              </div>
            ))}
          </dl>
          <p className="mt-2 text-sm"><Link href="/glossary">All terms</Link></p>
        </section>
      )}

      {s.cited_by.total > 0 && (
        <section aria-labelledby="cited-heading" className="mt-6 max-w-[68ch]">
          <h2 id="cited-heading" className="text-sm font-semibold">
            Cited by {s.cited_by.total} decision{s.cited_by.total === 1 ? "" : "s"} (Court of Appeal and Supreme Court)
          </h2>
          <ul className="mt-2 space-y-1 text-sm">
            {s.cited_by.decisions.map((d) => (
              <li key={d.citation}>
                <Link href={d.url} className="underline"><cite className="italic">{d.title}</cite>, {d.citation}</Link>
                <span className="text-muted"> — {d.pinpoints.join(", ")}</span>
              </li>
            ))}
          </ul>
          {s.cited_by.total > s.cited_by.decisions.length && (
            <p className="mt-1 text-xs text-muted">Showing the {s.cited_by.decisions.length} most recent.</p>
          )}
        </section>
      )}

      <CopyCitation title={s.citation.title} reference={s.citation.reference} text={s.citation.text} />

      <nav aria-label="Previous and next" className="mt-10 flex justify-between border-t border-rule pt-4 text-sm">
        {s.prev ? <Link href={`/laws/${slug}/${s.prev}`} rel="prev">← Previous</Link> : <span />}
        {s.next ? <Link href={`/laws/${slug}/${s.next}`} rel="next">Next →</Link> : <span />}
      </nav>
    </article>
  );
}
