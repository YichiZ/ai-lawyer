"use client";

import { useTransition } from "react";
import { setRole } from "@/app/actions";

export default function RoleSwitch({ role }: { role: "researcher" | "reviewer" }) {
  const [pending, start] = useTransition();
  return (
    <div className="flex items-center gap-2 text-sm" role="group" aria-label="Demo role (no login)">
      <span className="text-muted">Demo role:</span>
      {(["researcher", "reviewer"] as const).map((r) => (
        <button
          key={r}
          type="button"
          aria-pressed={role === r}
          disabled={pending}
          onClick={() => start(() => setRole(r))}
          className={`rounded-sm border px-2 py-0.5 capitalize ${
            role === r ? "border-primary bg-primary text-paper" : "border-rule hover:bg-panel"
          }`}
        >
          {r}
        </button>
      ))}
    </div>
  );
}
