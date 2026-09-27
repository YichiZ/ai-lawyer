"use client";

import Link from "next/link";
import { useActionState } from "react";
import { ingestAction, type IngestState } from "@/app/actions";

const STATUS: Record<string, string> = {
  queued: "Queued",
  running: "Adding",
  done: "Added to the library",
  dead: "Could not be added",
};

export default function AddToLibrary({ url }: { url: string }) {
  const [state, action, pending] = useActionState<IngestState, FormData>(ingestAction.bind(null, url), {});
  const job = state.job;
  const finished = job?.status === "done" || job?.status === "dead";
  return (
    <form action={action} className="inline">
      {!job && (
        <label className="mr-2 text-sm">
          <input type="checkbox" name="in_scope" required className="mr-1 align-middle" />
          This page is about Ontario personal-injury law
        </label>
      )}
      {!finished && (
        <button type="submit" disabled={pending} className="rounded-sm border border-primary px-2 py-0.5 text-sm font-semibold text-primary disabled:opacity-60">
          {pending ? "Working…" : job ? "Check status" : "Add to library"}
        </button>
      )}
      <span role="status" className="ml-2 text-sm">
        {job && `${STATUS[job.status]}${job.stage && !finished ? ` (${job.stage})` : ""}`}
        {job?.status === "done" && job.document_slug && (
          <>
            {" — "}
            <Link href={`/laws/${job.document_slug}`}>open</Link>
          </>
        )}
        {job?.status === "dead" && job.error && ` — ${job.error}`}
      </span>
      {state.error && <span role="alert" className="ml-2 text-sm text-accent">{state.error}</span>}
    </form>
  );
}
