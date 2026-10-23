import type { Bookmark } from "../lib/api";
import { cn } from "../lib/utils";
import { Card, Heading } from "./ui";

const STATUS: Record<Bookmark["status"], { label: string; className: string }> = {
  open: { label: "Open", className: "bg-warn-soft text-warn" },
  fixed: { label: "Fixed", className: "bg-accent-soft text-accent" },
  kept: { label: "Kept", className: "bg-tint text-muted" },
};

/** Passages the translator was unsure about, and what the final doubt review decided. */
export function DoubtsPanel({ bookmarks, unitName }: { bookmarks: Bookmark[]; unitName: string }) {
  const count = (status: Bookmark["status"]) => bookmarks.filter((b) => b.status === status).length;
  return (
    <Card aria-labelledby="doubts-title" className="flex flex-col gap-3 p-5">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <Heading id="doubts-title">Doubts</Heading>
        <span className="text-[13px] text-muted">
          {count("open")} open · {count("fixed")} fixed · {count("kept")} kept
        </span>
      </div>
      <p className="m-0 text-sm text-muted">
        Places where the translator had to guess. They are reviewed at the end of the book, when
        the glossary and the compendium are complete.
      </p>
      <ul className="m-0 flex max-h-96 list-none flex-col gap-2 overflow-auto p-0">
        {bookmarks.map((b) => (
          <li key={b.id} className="flex flex-col gap-1.5 rounded-md border border-line p-3 text-sm">
            <div className="flex flex-wrap items-center gap-2">
              <span className={cn("rounded-full px-2 py-0.5 text-[11px] font-semibold", STATUS[b.status].className)}>
                {STATUS[b.status].label}
              </span>
              <span className="text-xs text-faint">
                {unitName} {b.unit + 1}
              </span>
              <span className="font-medium">“{b.quote}”</span>
              <span className="text-muted">{b.reason}</span>
            </div>
            {b.status === "fixed" && b.resolution ? (
              <div className="grid gap-1 text-[13px] sm:grid-cols-2 sm:gap-3">
                <p className="m-0 text-faint line-through decoration-faint/60">{b.translation}</p>
                <p className="m-0 text-ink">{b.resolution}</p>
              </div>
            ) : (
              b.translation && <p className="m-0 text-[13px] text-muted">{b.translation}</p>
            )}
            {b.note && <p className="m-0 text-xs text-faint">{b.note}</p>}
          </li>
        ))}
      </ul>
    </Card>
  );
}
