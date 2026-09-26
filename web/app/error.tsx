"use client";

export default function Error({ reset }: { error: Error; reset: () => void }) {
  return (
    <div role="alert">
      <h1 className="font-serif text-3xl font-semibold">Something went wrong</h1>
      <p className="mt-3 text-muted">The law library could not be loaded. Please try again in a moment.</p>
      <button type="button" onClick={reset} className="mt-6 rounded-sm border border-rule px-3 py-1">
        Try again
      </button>
    </div>
  );
}
