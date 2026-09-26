import Link from "next/link";
import { listGuides } from "@/lib/api";

export default async function Home() {
  const guides = (await listGuides()) ?? [];
  return (
    <div>
      <div className="max-w-2xl">
        <h1 className="font-serif text-4xl font-semibold leading-tight">Ontario personal-injury law, in one place</h1>
        <p className="mt-4 text-lg text-muted">
          Topic guides, the official text of every law that applies, and research answers checked by a reviewer — each
          statement traceable to its source.
        </p>
      </div>
      <h2 className="mt-10 font-serif text-2xl font-semibold">Topic guides</h2>
      <ul className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {guides.map((g) => (
          <li key={g.slug}>
            <Link href={`/guides/${g.slug}`} className="block h-full rounded-sm border border-rule p-4 no-underline hover:bg-panel">
              <span className="font-serif text-lg font-semibold text-ink">{g.title}</span>
              <span className="mt-1 block text-sm text-muted">{g.intro}</span>
              <span className="mt-2 block text-xs text-muted">{g.reviewed} of {g.sections} sections reviewed</span>
            </Link>
          </li>
        ))}
      </ul>
      <p className="mt-10"><Link href="/laws" className="font-semibold">Browse the law library →</Link></p>
    </div>
  );
}
