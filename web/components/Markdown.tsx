// ponytail: renders only the markdown our drafts use (paragraphs, "> " quotes, **bold**, *italic*, "- " lists).
// Swap for a real renderer if reviewers start writing richer markdown.
import { Fragment, type ReactNode } from "react";

function inline(text: string): ReactNode[] {
  return text.split(/(\*\*[^*]+\*\*|\*[^*]+\*)/g).map((part, i) => {
    if (part.startsWith("**") && part.endsWith("**")) return <strong key={i}>{part.slice(2, -2)}</strong>;
    if (part.startsWith("*") && part.endsWith("*") && part.length > 2) return <em key={i}>{part.slice(1, -1)}</em>;
    return <Fragment key={i}>{part}</Fragment>;
  });
}

export default function Markdown({ text }: { text: string }) {
  const blocks = text.trim().split(/\n\s*\n/);
  return (
    <div className="space-y-3">
      {blocks.map((block, i) => {
        const lines = block.split("\n");
        if (lines.every((l) => l.startsWith(">"))) {
          const body = lines.map((l) => l.replace(/^>\s?/, ""));
          const cite = body.at(-1)?.startsWith("— ") ? body.pop() : undefined;
          return (
            <blockquote key={i} className="border-l-2 border-primary pl-4">
              <p className="font-serif">{inline(body.join(" "))}</p>
              {cite && <footer className="mt-1 text-sm text-muted">{inline(cite)}</footer>}
            </blockquote>
          );
        }
        if (lines.every((l) => l.startsWith("- "))) {
          return (
            <ul key={i} className="list-disc pl-6">
              {lines.map((l, j) => <li key={j}>{inline(l.slice(2))}</li>)}
            </ul>
          );
        }
        return <p key={i}>{inline(lines.join(" "))}</p>;
      })}
    </div>
  );
}
