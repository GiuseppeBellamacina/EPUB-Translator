import { Link } from "react-router-dom";
import { QUEUE_PILL, type QueueItem } from "../lib/api";
import { cn } from "../lib/utils";
import { Card, Heading, StatusPill } from "./ui";

/** The queue this book belongs to: every book's status and progress, this one highlighted. */
export function QueueProgress({ items, bookId }: { items: QueueItem[]; bookId: number }) {
  const done = items.filter((i) => i.status === "done").length;
  const units = items.reduce((n, i) => n + i.total_units, 0);
  const translated = items.reduce((n, i) => n + Math.min(i.completed_units, i.total_units), 0);
  const pct = units ? Math.round((translated / units) * 100) : 0;
  return (
    <Card aria-labelledby="queue-progress-title" className="flex flex-col gap-3 p-5">
      <div className="flex items-baseline justify-between gap-3">
        <Heading id="queue-progress-title">Queue</Heading>
        <span className="text-[13px] text-muted">
          {done} of {items.length} books · {pct}%
        </span>
      </div>
      <div
        role="progressbar"
        aria-label="Queue progress"
        aria-valuenow={pct}
        aria-valuemin={0}
        aria-valuemax={100}
        className="h-1 overflow-hidden rounded-full bg-tint"
      >
        <div className="h-full bg-accent transition-[width]" style={{ width: `${pct}%` }} />
      </div>
      <ol className="m-0 flex max-h-56 list-none flex-col overflow-auto p-0">
        {items.map((item, n) => (
          <li
            key={item.id}
            aria-current={item.book_id === bookId ? "page" : undefined}
            className={cn(
              "flex items-center gap-3 rounded-md px-2 py-1.5",
              item.book_id === bookId && "bg-tint",
            )}
          >
            <span className="w-5 shrink-0 text-right font-serif text-faint">{n + 1}</span>
            <Link
              to={`/translate/${item.book_id}`}
              className="min-w-0 flex-1 truncate text-sm text-ink no-underline hover:underline"
            >
              {item.filename.replace(/\.(epub|pdf)$/i, "")}
            </Link>
            <span className="shrink-0 text-xs text-muted">
              {item.completed_units}/{item.total_units}
            </span>
            <StatusPill status={QUEUE_PILL[item.status]} />
          </li>
        ))}
      </ol>
    </Card>
  );
}
