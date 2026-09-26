"use client";

import { useActionState } from "react";
import { askAction, type FormState } from "@/app/actions";

export default function AskForm({ defaultQuestion = "" }: { defaultQuestion?: string }) {
  const [state, action, pending] = useActionState<FormState, FormData>(askAction, {});
  return (
    <form action={action} className="mt-6 max-w-2xl">
      <label htmlFor="question" className="block font-semibold">
        Your research question
      </label>
      <textarea
        id="question"
        name="question"
        required
        minLength={5}
        maxLength={1000}
        rows={4}
        defaultValue={defaultQuestion}
        aria-describedby="question-help"
        className="mt-2 w-full rounded-sm border border-rule bg-panel p-3"
        placeholder="e.g. How soon must someone who slipped on an icy Toronto sidewalk notify the City?"
      />
      <p id="question-help" className="mt-1 text-sm text-muted">
        Answers come only from the laws in this guide, with verified quotes, and are released after a reviewer checks them.
      </p>
      {state.error && (
        <p role="alert" className="mt-3 text-accent">
          {state.error}
        </p>
      )}
      <button
        type="submit"
        disabled={pending}
        className="mt-4 rounded-sm bg-primary px-4 py-2 font-semibold text-paper disabled:opacity-60"
      >
        {pending ? "Finding sources…" : "Ask"}
      </button>
    </form>
  );
}
