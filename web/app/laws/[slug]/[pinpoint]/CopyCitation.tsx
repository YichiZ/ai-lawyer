"use client";

import { useState } from "react";

export default function CopyCitation({ title, reference, text }: { title: string; reference: string; text: string }) {
  const [status, setStatus] = useState("");

  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setStatus("Citation copied");
    } catch {
      setStatus("Copy failed — select the citation and copy it manually");
    }
  }

  return (
    <div className="no-print mt-6 flex flex-wrap items-center gap-3 text-sm">
      <span className="text-muted">Cite:</span>
      <span>
        {title && <cite className="italic">{title}</cite>}
        {title && ", "}
        {reference}
      </span>
      <button
        type="button"
        onClick={copy}
        className="rounded-sm border border-rule px-2 py-1 hover:bg-panel"
      >
        Copy citation
      </button>
      <span role="status" aria-live="polite" className="text-muted">
        {status}
      </span>
    </div>
  );
}
