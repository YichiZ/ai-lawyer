"use client";

import { startTransition, useActionState, useState, type FormEvent } from "react";
import { reviewAction, type FormState } from "@/app/actions";
import Markdown from "@/components/Markdown";
import WebSources from "@/components/WebSources";
import AddToLibrary from "./AddToLibrary";
import { REJECT_REASONS, type QueueItem } from "@/lib/api";

const RISK_LABELS: Record<string, string> = {
  excerpt_overflow: "Copies too much by-law text: edit before approving",
  secondary_statute: "Statute only quoted in a decision",
  advice_seeking: "Asks for advice on their own facts",
  dropped_claims: "Claims dropped by quote check",
  retried: "Needed a retry",
  not_found: "Not found in our laws",
  out_of_scope: "Out of scope",
  unverified: "No verified claims",
};

export default function ReviewItem({ item }: { item: QueueItem }) {
  const [state, action, pending] = useActionState<FormState, FormData>(reviewAction.bind(null, item.id), {});
  const [decision, setDecision] = useState<"approve" | "edit" | "reject">("approve");

  // #70: dispatch by hand, not via <form action>. React 19 resets a form after its action runs, which unchecks the
  // controlled radios and restores the textarea/note, so a resubmit after an error sent `approve` with the draft.
  // Without the reset the entered text survives, and the decision sent is always the one shown.
  function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    form.set("decision", decision);
    startTransition(() => action(form));
  }

  return (
    <article className="rounded-sm border border-rule p-5" aria-labelledby={`q-${item.id}`}>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id={`q-${item.id}`} className="font-serif text-xl font-semibold">{item.question}</h2>
        <span className="text-sm text-muted">
          #{item.id} · {item.asked_by ?? "unknown"}
          {item.trace_url && (
            <>
              {" · "}
              <a href={item.trace_url} target="_blank" rel="noreferrer">View trace</a>
            </>
          )}
        </span>
      </div>
      {item.guide && (
        <p className="mt-1 text-sm">
          Guide: <a href={`/guides/${item.guide.slug}`}>{item.guide.title}</a> → {item.guide.heading}
        </p>
      )}
      {item.risk.length > 0 && (
        <ul className="mt-2 flex flex-wrap gap-2" aria-label="Risk flags">
          {item.risk.map((r) => (
            <li key={r} className="rounded-sm border border-accent px-2 py-0.5 text-sm text-accent">{RISK_LABELS[r] ?? r}</li>
          ))}
        </ul>
      )}

      <div className="mt-4 rounded-sm bg-panel p-4">
        <p className="text-sm text-muted">Draft</p>
        <Markdown text={item.draft_markdown} />
      </div>

      <WebSources sources={item.web_sources} extra={(w) =>
        w.addable ? <AddToLibrary url={w.url} /> : <span className="text-muted">— not an official source; cannot be added</span>} />

      {item.claims.length > 0 && (
        <table className="mt-4 w-full text-left text-sm">
          <caption className="text-left font-semibold">Claims and their verified quotes</caption>
          <thead><tr><th className="py-1 pr-3">Claim</th><th className="py-1 pr-3">Quote</th><th className="py-1">Source</th></tr></thead>
          <tbody>
            {item.claims.map((c, i) => (
              <tr key={i} className="border-t border-rule align-top">
                <td className="py-2 pr-3">{c.text}</td>
                <td className="py-2 pr-3 font-serif">“{c.quote}”</td>
                <td className="py-2"><a href={c.source.url}>{c.source.citation.text}</a></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {item.dropped_claims.length > 0 && (
        <details className="mt-3 text-sm">
          <summary>{item.dropped_claims.length} dropped claim(s)</summary>
          <ul className="mt-2 list-disc pl-6">
            {item.dropped_claims.map((c, i) => <li key={i}>{c.text} — “{c.quote}” ({c.reason})</li>)}
          </ul>
        </details>
      )}

      <form onSubmit={submit} className="mt-5 space-y-3">
        <fieldset className="flex flex-wrap gap-4">
          <legend className="sr-only">Decision</legend>
          {(["approve", "edit", "reject"] as const).map((d) => (
            <label key={d} className="flex items-center gap-1 capitalize">
              <input type="radio" name="decision" value={d} checked={decision === d} onChange={() => setDecision(d)} />
              {d}
            </label>
          ))}
        </fieldset>
        {decision === "edit" && (
          <>
            <label className="block text-sm font-semibold" htmlFor={`final-${item.id}`}>Revised answer</label>
            <textarea id={`final-${item.id}`} name="final_markdown" rows={8} defaultValue={item.draft_markdown}
                      className="w-full rounded-sm border border-rule bg-panel p-2 font-mono text-sm" required />
            <label className="block text-sm font-semibold" htmlFor={`note-${item.id}`}>Note (required)</label>
            <input id={`note-${item.id}`} name="note" required className="w-full rounded-sm border border-rule bg-panel p-2" />
          </>
        )}
        {decision === "reject" && (
          <>
            <label className="block text-sm font-semibold" htmlFor={`reason-${item.id}`}>Reason</label>
            <select id={`reason-${item.id}`} name="reason" required defaultValue="" className="rounded-sm border border-rule bg-panel p-2">
              <option value="" disabled>Choose a reason</option>
              {Object.entries(REJECT_REASONS).map(([v, label]) => <option key={v} value={v}>{label}</option>)}
            </select>
          </>
        )}
        {state.error && <p role="alert" className="text-accent">{state.error}</p>}
        <button type="submit" disabled={pending} className="rounded-sm bg-primary px-4 py-2 font-semibold capitalize text-paper disabled:opacity-60">
          {pending ? "Saving…" : `${decision} answer`}
        </button>
      </form>
    </article>
  );
}
