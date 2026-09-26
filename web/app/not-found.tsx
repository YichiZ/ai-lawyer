import Link from "next/link";

export default function NotFound() {
  return (
    <div>
      <h1 className="font-serif text-3xl font-semibold">Not found</h1>
      <p className="mt-3 text-muted">That law or section is not in the guide.</p>
      <p className="mt-6"><Link href="/laws">Back to the law library</Link></p>
    </div>
  );
}
