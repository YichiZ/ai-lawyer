import type { Metadata } from "next";
import { getQueue } from "@/lib/api";
import { currentRole } from "@/lib/role";
import ReviewItem from "./ReviewItem";

export const metadata: Metadata = { title: "Review queue" };

export default async function ReviewPage() {
  const role = await currentRole();
  if (role !== "reviewer") {
    return (
      <div>
        <h1 className="font-serif text-3xl font-semibold">Review queue</h1>
        <p className="mt-3 text-muted">Only reviewers can see the queue. Switch the demo role to Reviewer in the header.</p>
      </div>
    );
  }
  const items = (await getQueue(role)) ?? [];
  return (
    <div>
      <h1 className="font-serif text-3xl font-semibold">Review queue</h1>
      <p className="mt-2 text-muted">{items.length} answer(s) awaiting review. Flagged drafts come first, then topic-guide sections.</p>
      <div className="mt-6 space-y-6">
        {items.map((item) => <ReviewItem key={item.id} item={item} />)}
        {items.length === 0 && <p>Nothing to review.</p>}
      </div>
    </div>
  );
}
