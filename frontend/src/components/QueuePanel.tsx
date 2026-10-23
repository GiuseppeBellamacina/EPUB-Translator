import { useState } from "react";
import { Link } from "react-router-dom";
import { Dialog, DialogPanel, DialogTitle } from "@headlessui/react";
import { Loader2, Pause, Play, Plus, X } from "lucide-react";
import { api, type Book, type QueueItem, type QueueState } from "../lib/api";
import { Checkbox } from "./controls";
import { Button, Card, Heading, StatusPill } from "./ui";

const PILL: Record<QueueItem["status"], string> = {
  pending: "queued",
  running: "translating",
  paused: "paused",
  done: "completed",
  failed: "failed",
};

const bookName = (filename: string) => filename.replace(/\.(epub|pdf)$/i, "");

/** Items by queue (batch), in order; batches are contiguous in the global order. */
function batches(items: QueueItem[]): QueueItem[][] {
  const groups: QueueItem[][] = [];
  for (const item of items) {
    const last = groups[groups.length - 1];
    if (last && item.batch_id !== null && last[0].batch_id === item.batch_id) last.push(item);
    else groups.push([item]);
  }
  return groups;
}

/** Pick books to append to a queue, in the order they are picked. */
function AddBooksDialog({
  batchId,
  candidates,
  onClose,
  onAdded,
}: {
  batchId: number;
  candidates: Book[];
  onClose: () => void;
  onAdded: () => void;
}) {
  const [picked, setPicked] = useState<number[]>([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const add = async () => {
    setSaving(true);
    setError(null);
    try {
      await api.addToBatch(batchId, picked);
      onAdded();
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not add the books");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open onClose={onClose} className="relative z-50">
      <div className="fixed inset-0 bg-ink/35" aria-hidden="true" />
      <div className="fixed inset-0 flex items-start justify-center overflow-auto p-4 pt-16">
        <DialogPanel className="w-full max-w-lg rounded-lg bg-surface p-6 shadow-[0_24px_60px_rgba(27,36,51,0.18)]">
          <DialogTitle className="m-0 font-serif text-[26px] font-medium">Add books to this queue</DialogTitle>
          <p className="mb-4 mt-1 text-sm text-muted">
            They run after its last book, with the same settings, and keep its glossary and
            compendium when the queue does.
          </p>
          {candidates.length === 0 ? (
            <p className="m-0 rounded-md bg-tint p-4 text-sm text-muted">
              No other books to add: upload more, or they are already queued or translated.
            </p>
          ) : (
            <ul className="m-0 flex max-h-[50vh] list-none flex-col gap-1 overflow-auto p-0">
              {candidates.map((book) => {
                const order = picked.indexOf(book.id);
                return (
                  <li key={book.id} className="flex items-center gap-3 rounded-md px-2 py-2 hover:bg-tint">
                    <Checkbox
                      checked={order >= 0}
                      onChange={(on) =>
                        setPicked((p) => (on ? [...p, book.id] : p.filter((id) => id !== book.id)))
                      }
                      label={`Add ${book.filename}`}
                    />
                    <span className="w-5 text-right font-serif text-accent">{order >= 0 ? order + 1 : ""}</span>
                    <span className="min-w-0 flex-1 truncate text-sm">{bookName(book.filename)}</span>
                  </li>
                );
              })}
            </ul>
          )}
          {error && <p className="mb-0 mt-3 text-sm text-danger">{error}</p>}
          <div className="mt-5 flex justify-end gap-2.5">
            <Button onClick={onClose}>Cancel</Button>
            <Button variant="primary" onClick={add} disabled={saving || picked.length === 0}>
              {saving && <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />}
              Add {picked.length || ""}
            </Button>
          </div>
        </DialogPanel>
      </div>
    </Dialog>
  );
}

/** The queues: order, per-book status, start/pause, add and remove books. */
export function QueuePanel({
  queue,
  books,
  onChange,
}: {
  queue: QueueState;
  /** all books, to pick the ones to add */
  books: Book[];
  onChange: () => void;
}) {
  const [addingTo, setAddingTo] = useState<number | null>(null);
  const waiting = queue.items.some((i) => i.status === "pending" || i.status === "paused");
  const finished = queue.items.some((i) => i.status === "done" || i.status === "failed");
  const act = (call: Promise<unknown>) => call.finally(onChange);
  const busy = new Set(queue.items.filter((i) => i.status !== "done" && i.status !== "failed").map((i) => i.book_id));
  const candidates = books.filter((b) => b.status !== "completed" && !busy.has(b.id));
  const groups = batches(queue.items);

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

      {groups.map((group) => {
        const [first] = group;
        const open = group.some((i) => i.status !== "done" && i.status !== "failed");
        const carries = [first.keep_glossary && "keeps glossary", first.keep_compendium && "keeps compendium"]
          .filter(Boolean)
          .join(" · ");
        return (
          <section key={first.id} className="rounded-md border border-line">
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line bg-tint px-3 py-2">
              <span className="min-w-0 truncate text-xs text-muted">
                <span className="font-mono">{first.config.model ?? "default model"}</span>
                {carries && ` · ${carries}`}
              </span>
              {first.batch_id !== null && open && (
                <Button size="sm" variant="ghost" onClick={() => setAddingTo(first.batch_id)}>
                  <Plus className="h-4 w-4" aria-hidden="true" /> Add books
                </Button>
              )}
            </div>
            <ol className="m-0 flex list-none flex-col divide-y divide-line p-0 px-3">
              {group.map((item, n) => (
                <li key={item.id} className="flex items-center gap-3 py-2.5">
                  <span className="w-5 shrink-0 text-right font-serif text-faint">{n + 1}</span>
                  <div className="min-w-0 flex-1">
                    <Link to={`/translate/${item.book_id}`} className="block truncate text-sm font-medium text-ink">
                      {bookName(item.filename)}
                    </Link>
                    <div className="truncate text-xs text-muted" title={item.error ?? undefined}>
                      {item.error ?? `${item.completed_units}/${item.total_units}`}
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
          </section>
        );
      })}

      {addingTo !== null && (
        <AddBooksDialog
          batchId={addingTo}
          candidates={candidates}
          onClose={() => setAddingTo(null)}
          onAdded={onChange}
        />
      )}
    </Card>
  );
}
