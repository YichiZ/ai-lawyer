import Link from "next/link";

export default function Home() {
  return (
    <div className="max-w-2xl">
      <h1 className="font-serif text-4xl font-semibold leading-tight">Ontario personal-injury law, in one place</h1>
      <p className="mt-4 text-lg text-muted">
        Browse the statutes, regulations and Toronto by-laws that govern injury claims in Ontario — official text,
        pinpoint citations and the source for every provision.
      </p>
      <p className="mt-8">
        <Link href="/laws" className="text-lg font-semibold">
          Open the law library →
        </Link>
      </p>
    </div>
  );
}
