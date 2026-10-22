import { useEffect, useMemo, useState } from "react";
import type { JobEvent } from "../lib/api";
import { logEntries, relativeTime, type LogKind } from "../lib/jobEvents";
import { cn } from "../lib/utils";
import { Card, Heading } from "./ui";

const DOT: Record<LogKind, string> = {
  done: "bg-accent",
  glossary: "bg-violet",
  review: "bg-warn",
  error: "bg-danger",
  info: "bg-faint",
};

const FILTERS: { id: "all" | LogKind; label: string }[] = [
  { id: "all", label: "All" },
  { id: "error", label: "Errors" },
  { id: "glossary", label: "Glossary" },
  { id: "review", label: "Review" },
];

/** Fixed-height activity log, newest first, with filters and collapsed repeats. */
export function ActivityLog({ events, unitAbbr }: { events: JobEvent[]; unitAbbr: string }) {
  const [filter, setFilter] = useState<"all" | LogKind>("all");
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 15000);
    return () => clearInterval(timer);
  }, []);

  const entries = useMemo(() => logEntries(events, unitAbbr), [events, unitAbbr]);
  const counts = useMemo(() => {
    const c: Record<string, number> = { all: entries.length };
    for (const e of entries) c[e.kind] = (c[e.kind] ?? 0) + 1;
    return c;
  }, [entries]);
  const shown = filter === "all" ? entries : entries.filter((e) => e.kind === filter);

  return (
    <Card aria-labelledby="activity-title" className="overflow-hidden">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-5 py-3.5">
        <Heading id="activity-title" className="text-xl">
          Activity
        </Heading>
        <div role="group" aria-label="Filter activity" className="flex flex-wrap gap-1.5">
          {FILTERS.map(({ id, label }) => (
            <button
              key={id}
              type="button"
              aria-pressed={filter === id}
              onClick={() => setFilter(id)}
              className={cn(
                "h-8 rounded-full border px-3.5 text-[13px] transition-colors",
                filter === id
                  ? "border-ink bg-ink text-on-ink"
                  : "border-line-strong bg-surface text-ink hover:bg-tint",
              )}
            >
              {label} {counts[id] ?? 0}
            </button>
          ))}
        </div>
      </div>
      <ol className="m-0 h-60 list-none overflow-auto p-0 py-1.5" aria-live="polite" aria-relevant="additions">
        {shown.length === 0 && (
          <li className="px-5 py-3 text-sm text-faint">
            {entries.length ? "Nothing here with this filter." : "Events appear here while translating."}
          </li>
        )}
        {shown.map((e) => (
          <li
            key={e.key}
            className="grid grid-cols-[10px_76px_minmax(0,1fr)_52px] items-center gap-3 px-5 py-2 text-sm"
          >
            <span className={cn("h-2 w-2 rounded-full", DOT[e.kind])} aria-hidden="true" />
            <span className="truncate text-xs text-faint">{e.unit ?? "—"}</span>
            <span className={cn("truncate", e.kind === "info" ? "text-muted" : "text-ink")} title={e.text}>
              {e.text}
            </span>
            <span className="text-right text-xs text-faint">{relativeTime(e.ts, now)}</span>
          </li>
        ))}
      </ol>
    </Card>
  );
}
