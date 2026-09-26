import type { Metadata } from "next";
import AskForm from "./AskForm";

export const metadata: Metadata = { title: "Ask" };

export default function AskPage() {
  return (
    <div>
      <h1 className="font-serif text-3xl font-semibold">Ask a research question</h1>
      <p className="mt-2 max-w-2xl text-muted">
        This is a research aid, not legal advice: it will not say whether someone has a case, predict outcomes, value a
        claim or calculate deadlines.
      </p>
      <AskForm />
    </div>
  );
}
