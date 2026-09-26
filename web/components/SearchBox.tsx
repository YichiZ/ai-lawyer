"use client";

import { useRouter } from "next/navigation";
import { useEffect, useId, useRef, useState } from "react";
import { suggestAction } from "@/app/actions";
import type { Suggestion } from "@/lib/api";

const DEBOUNCE_MS = 150;

export default function SearchBox() {
  const router = useRouter();
  const inputRef = useRef<HTMLInputElement>(null);
  const listId = useId();
  const [q, setQ] = useState("");
  const [items, setItems] = useState<Suggestion[]>([]);
  const [active, setActive] = useState(-1);
  const [open, setOpen] = useState(false);

  // "/" focuses the box unless the user is already typing somewhere.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (e.key === "/" && !["INPUT", "TEXTAREA", "SELECT"].includes(t.tagName) && !t.isContentEditable) {
        e.preventDefault();
        inputRef.current?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  useEffect(() => {
    if (q.trim().length < 2) {
      setItems([]);
      return;
    }
    let cancelled = false;
    const timer = setTimeout(async () => {
      const found = await suggestAction(q);
      if (!cancelled) {
        setItems(found);
        setActive(found.length ? 0 : -1);
        setOpen(true);
      }
    }, DEBOUNCE_MS);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [q]);

  function go(url: string) {
    setOpen(false);
    router.push(url);
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "ArrowDown" && items.length) {
      e.preventDefault();
      setOpen(true);
      setActive((i) => (i + 1) % items.length);
    } else if (e.key === "ArrowUp" && items.length) {
      e.preventDefault();
      setActive((i) => (i - 1 + items.length) % items.length);
    } else if (e.key === "Escape" && open) {
      e.preventDefault(); // close the list only; a second Escape clears the box natively
      setOpen(false);
    } else if (e.key === "Enter" && q.trim().length >= 2) {
      e.preventDefault();
      go(open && active >= 0 && items[active] ? items[active].url : `/search?q=${encodeURIComponent(q.trim())}`);
    }
  }

  const expanded = open && items.length > 0;
  return (
    <div className="relative w-full max-w-xs">
      <label htmlFor="site-search" className="sr-only">
        Search laws (press / to focus)
      </label>
      <input
        ref={inputRef}
        id="site-search"
        type="search"
        role="combobox"
        aria-expanded={expanded}
        aria-controls={listId}
        aria-autocomplete="list"
        aria-activedescendant={expanded && active >= 0 ? `${listId}-${active}` : undefined}
        autoComplete="off"
        placeholder="Search laws or type s. 4  ( / )"
        value={q}
        onChange={(e) => setQ(e.target.value)}
        onKeyDown={onKeyDown}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
        onFocus={() => items.length && setOpen(true)}
        className="w-full rounded-sm border border-rule bg-panel px-2 py-1 text-sm"
      />
      {expanded && (
        <ul id={listId} role="listbox" className="absolute z-20 mt-1 w-[28rem] max-w-[90vw] rounded-sm border border-rule bg-paper shadow-lg">
          {items.map((s, i) => (
            <li
              key={s.url}
              id={`${listId}-${i}`}
              role="option"
              aria-selected={i === active}
              onMouseDown={(e) => {
                e.preventDefault();
                go(s.url);
              }}
              className={`cursor-pointer px-3 py-2 text-sm ${i === active ? "bg-panel" : ""}`}
            >
              {s.type === "law" ? (
                <span className="font-semibold">{s.title}</span>
              ) : (
                <>
                  <span className="pinpoint mr-2 text-primary">{s.display}</span>
                  <span>{s.heading ?? ""}</span>
                  <span className="block text-xs text-muted">{s.title}</span>
                </>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
