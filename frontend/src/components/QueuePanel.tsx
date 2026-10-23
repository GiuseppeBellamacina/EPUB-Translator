import { Link } from "react-router-dom";
import { Pause, Play, X } from "lucide-react";
import { api, type QueueItem, type QueueState } from "../lib/api";
import { Button, Card, Heading, StatusPill } from "./ui";

const PILL: Record<QueueItem["status"], string> = {
  pending: "queued",
  running: "translating",
  paused: "paused",
  done: "completed",
  failed: "failed",
};

/** The book queue: order, per-book status, and start/pause/remove. */
export function QueuePanel({ queue, onChange }: { queue: QueueState; onChange: () => void }) {
  const waiting = queue.items.some((i) => i.status === "pending" || i.status === "paused");
  const finished = queue.items.some((i) => i.status === "done" || i.status === "failed");
  const act = (call: Promise<unknown>) => call.finally(onChange);

  return (
    <Card aria-labelledby="queue-title" className="flex flex-col gap-4 p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <Heading id="queue-title">Queue</Heading>
          <p className="m-0 mt-1 text-[13px] text-muted">
            {queue.running ? "Translating one book at a time." : waiting ? "Paused." : "Done."}
          </p>
        </div>
        <div className="flex gap-2">
          {finished && (
            <Button size="sm" variant="ghost" onClick={() => act(api.clearFinished())}>
              Clear finished
            </Button>
          )}
          {queue.running ? (
            <Button size="sm" onClick={() => act(api.stopQueue())}>
              <Pause className="h-4 w-4" aria-hidden="true" /> Pause queue
            </Button>
          ) : (
            waiting && (
              <Button size="sm" variant="primary" onClick={() => act(api.startQueue())}>
                <Play className="h-4 w-4" aria-hidden="true" /> Resume queue
              </Button>
            )
          )}
        </div>
      </div>

      <ol className="m-0 flex list-none flex-col divide-y divide-line p-0">
        {queue.items.map((item, n) => (
          <li key={item.id} className="flex items-center gap-3 py-2.5">
            <span className="w-5 shrink-0 text-right font-serif text-faint">{n + 1}</span>
            <div className="min-w-0 flex-1">
              <Link to={`/translate/${item.book_id}`} className="block truncate text-sm font-medium text-ink">
                {item.filename.replace(/\.(epub|pdf)$/i, "")}
              </Link>
              <div className="truncate text-xs text-muted" title={item.error ?? undefined}>
                {item.error ??
                  [
                    `${item.completed_units}/${item.total_units}`,
                    item.config.model ?? "default model",
                    item.keep_glossary && "keeps glossary",
                    item.keep_compendium && "keeps compendium",
                  ]
                    .filter(Boolean)
                    .join(" · ")}
              </div>
            </div>
            <StatusPill status={PILL[item.status]} />
            <button
              type="button"
              onClick={() => act(api.removeFromQueue(item.id))}
              disabled={item.status === "running"}
              aria-label={`Remove ${item.filename} from the queue`}
              className="rounded-md p-1.5 text-faint hover:bg-tint hover:text-ink disabled:invisible"
            >
              <X className="h-4 w-4" aria-hidden="true" />
            </button>
          </li>
        ))}
      </ol>
    </Card>
  );
}
