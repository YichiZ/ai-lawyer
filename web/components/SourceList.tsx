import Link from "next/link";
import type { Source } from "@/lib/api";

export default function SourceList({ sources }: { sources: Source[] }) {
  return (
    <ol className="mt-3 space-y-3">
      {sources.map((s) => (
        <li key={s.chunk_id} className="border-l-2 border-rule pl-3">
          <Link href={s.url} className="font-semibold">
            {s.citation.title && <cite className="italic">{s.citation.title}</cite>}
            {s.citation.title ? ", " : ""}
            {s.citation.title ? s.display : s.citation.reference}
          </Link>
          <p className="mt-1 text-sm text-muted">{s.snippet}</p>
        </li>
      ))}
    </ol>
  );
}
