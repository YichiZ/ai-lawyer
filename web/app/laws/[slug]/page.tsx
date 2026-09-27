import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { TreeNode, asOf, getLaw, sourceLabel } from "@/lib/api";

type Props = { params: Promise<{ slug: string }> };

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const law = await getLaw((await params).slug);
  return { title: law?.document.title ?? "Not found" };
}

function SectionLink({ slug, node }: { slug: string; node: TreeNode }) {
  return (
    <li className="py-1">
      <Link href={`/laws/${slug}/${node.pinpoint}`} className="grid grid-cols-[7rem_1fr] gap-3">
        <span className="pinpoint text-sm">{node.display}</span>
        <span>{node.heading ?? <span className="text-muted">(no heading)</span>}</span>
      </Link>
    </li>
  );
}

export default async function LawPage({ params }: Props) {
  const { slug } = await params;
  const law = await getLaw(slug);
  if (!law) notFound();
  const { document: doc, tree } = law;

  // Group sections under their part, keeping reading order; sections outside any part stand alone.
  const blocks: { part: TreeNode | null; sections: TreeNode[] }[] = [];
  for (const node of tree) {
    if (node.kind === "part") blocks.push({ part: node, sections: [] });
    else {
      const last = blocks.at(-1);
      if (node.parent && last?.part?.pinpoint === node.parent) last.sections.push(node);
      else if (!node.parent && last && !last.part) last.sections.push(node);
      else blocks.push({ part: tree.find((n) => n.pinpoint === node.parent) ?? null, sections: [node] });
    }
  }

  return (
    <div>
      <nav aria-label="Breadcrumb" className="text-sm">
        <Link href="/laws">Law library</Link>
      </nav>
      <h1 className="mt-2 font-serif text-3xl font-semibold">{doc.title}</h1>
      <p className="mt-2 text-sm text-muted">
        {doc.subtitle && <span className="pinpoint">{doc.subtitle}</span>} · {asOf(doc)} ·
        Source: {sourceLabel(doc)}
        {doc.url && (
          <>
            {" · "}
            <a href={doc.url}>Official version</a>
          </>
        )}
      </p>
      {blocks.map((block, i) => (
        <section key={block.part?.pinpoint ?? `top-${i}`} className="mt-8">
          {block.part && (
            <h2 className="font-serif text-xl font-semibold">
              <Link href={`/laws/${slug}/${block.part.pinpoint}`} className="text-ink">
                {block.part.heading}
              </Link>
            </h2>
          )}
          <ul className="mt-2">
            {block.sections.map((node) => (
              <SectionLink key={node.pinpoint} slug={slug} node={node} />
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}
