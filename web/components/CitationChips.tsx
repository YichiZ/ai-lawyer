"use client";

import { useEffect, useRef, useState } from "react";
import { loadPassage, type Passage } from "@/app/actions";
import type { Claim } from "@/lib/api";

const norm = (s: string) => s.replace(/[“”]/g, '"').replace(/[‘’]/g, "'").replace(/\s+/g, " ").trim();

function Highlighted({ text, quote }: { text: string; quote: string }) {
  const t = norm(text);
  const q = norm(quote);
  const at = t.indexOf(q);
  if (at < 0) return <p>{t}</p>;
  return (
    <p>
      {t.slice(0, at)}
      <mark className="bg-accent/20 text-ink">{t.slice(at, at + q.length)}</mark>
      {t.slice(at + q.length)}
    </p>
  );
}

export default function CitationChips({ claims }: { claims: Claim[] }) {
  const [open, setOpen] = useState<{ claim: Claim; passage: Passage | null; error?: string } | null>(null);
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    closeRef.current?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(null);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  async function show(claim: Claim) {
    setOpen({ claim, passage: null });
    try {
      const passage = await loadPassage(claim.source.slug, claim.source.pinpoint);
      setOpen({ claim, passage, error: passage ? undefined : "That passage could not be found." });
    } catch {
      setOpen({ claim, passage: null, error: "The passage could not be loaded. Please try again." });
    }
  }

  return (
    <>
      <ul className="mt-4 flex flex-wrap gap-2" aria-label="Citations">
        {claims.map((c, i) => (
          <li key={i}>
            <button
              type="button"
              onClick={() => show(c)}
              className="pinpoint rounded-sm border border-rule bg-panel px-2 py-1 text-sm hover:border-primary"
            >
              {c.source.citation.title ? `${c.source.citation.title}, ` : ""}
              {c.source.display}
            </button>
          </li>
        ))}
      </ul>
      {open && (
        <aside
          role="dialog"
          aria-modal="false"
          aria-labelledby="passage-title"
          className="fixed inset-y-0 right-0 z-10 w-full max-w-md overflow-y-auto border-l border-rule bg-paper p-6 shadow-lg"
        >
          <div className="flex items-start justify-between gap-4">
            <h2 id="passage-title" className="font-serif text-xl font-semibold">
              {open.passage ? `${open.passage.title} ${open.passage.display}` : open.claim.source.display}
            </h2>
            <button ref={closeRef} type="button" onClick={() => setOpen(null)} className="text-sm">
              Close
            </button>
          </div>
          {open.error && <p role="alert" className="mt-4 text-accent">{open.error}</p>}
          {!open.passage && !open.error && <p className="mt-4 text-muted">Loading passage…</p>}
          {open.passage && (
            <div className="law-text mt-4 text-[17px]">
              <Highlighted text={open.passage.text} quote={open.claim.quote} />
              {!open.passage.fullText && (
                <p className="mt-3 text-sm text-muted">Excerpt only — City of Toronto copyright.</p>
              )}
              <p className="mt-4 font-sans text-sm">
                <a href={open.passage.href}>Open the full section page</a>
              </p>
            </div>
          )}
        </aside>
      )}
    </>
  );
}
