"use client";

import { useActionState } from "react";
import { askWebAction, type FormState } from "@/app/actions";

export default function WebFallback({ question }: { question: string }) {
  const [state, action, pending] = useActionState<FormState, FormData>(askWebAction.bind(null, question), {});
  return (
    <form action={action} className="mt-4 rounded-sm border border-rule p-3 text-sm">
      <p>Our law library has no close match for this question.</p>
      <button type="submit" disabled={pending} className="mt-2 rounded-sm border border-primary px-3 py-1 font-semibold text-primary disabled:opacity-60">
        {pending ? "Searching…" : "Search the web instead"}
      </button>
      <p className="mt-2 text-xs text-muted">Web answers are labelled, list their sources, and are reviewed before release.</p>
      {state.error && <p role="alert" className="mt-2 text-accent">{state.error}</p>}
    </form>
  );
}
