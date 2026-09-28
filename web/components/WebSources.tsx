import type { ReactNode } from "react";
import type { WebSource } from "@/lib/api";

/** Web-fallback sources as real links (#62). URLs are http(s)-only, checked by the API. */
export default function WebSources<T extends WebSource>({ sources, extra }: { sources: T[]; extra?: (w: T) => ReactNode }) {
  if (sources.length === 0) return null;
  return (
    <section className="mt-4 text-sm" aria-label="Web sources">
      <p className="font-semibold">Web sources</p>
      <ul className="mt-1 space-y-2">
        {sources.map((w) => (
          <li key={w.url}>
            <a href={w.url} target="_blank" rel="noopener noreferrer">
              {w.title || w.domain}
              <span className="sr-only"> (opens in a new tab)</span>
            </a>{" "}
            ({w.domain}){extra && <> {extra(w)}</>}
          </li>
        ))}
      </ul>
    </section>
  );
}
