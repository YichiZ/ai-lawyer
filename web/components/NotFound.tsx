import Link from "next/link";

// Shared body of the per-route not-found pages (#15): say what is missing and link back to where to find it.
export default function NotFound({ message, href, label }: { message: string; href: string; label: string }) {
  return (
    <div>
      <h1 className="font-serif text-3xl font-semibold">Not found</h1>
      <p className="mt-3 text-muted">{message}</p>
      <p className="mt-6"><Link href={href}>{label}</Link></p>
    </div>
  );
}
