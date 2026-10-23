import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { BookOpen, Download, Eye, ListOrdered, Loader2, Trash2 } from "lucide-react";
import { api, type Book, type QueueState } from "../lib/api";
import { languageName } from "../lib/runSettings";
import { buttonClass } from "../lib/styles";
import { Checkbox } from "../components/controls";
import { QueueDialog } from "../components/QueueDialog";
import { QueuePanel } from "../components/QueuePanel";
import { Button, Card, Page, StatusPill } from "../components/ui";

export function HistoryPage() {
  const [books, setBooks] = useState<Book[] | null>(null);
  const [queue, setQueue] = useState<QueueState | null>(null);
  const [selected, setSelected] = useState<number[]>([]); // in the order they were picked
  const [queueing, setQueueing] = useState(false);

  const load = useCallback(() => {
    api.getBooks().then(setBooks);
    api.getQueue().then(setQueue);
  }, []);

  useEffect(load, [load]);

  // Follow the queue while it runs
  useEffect(() => {
    if (!queue?.running) return;
    const timer = setInterval(load, 4000);
    return () => clearInterval(timer);
  }, [queue?.running, load]);

  const waiting = new Set(
    queue?.items.filter((i) => i.status !== "done" && i.status !== "failed").map((i) => i.book_id),
  );
  const pending = new Set(queue?.items.filter((i) => i.status === "pending").map((i) => i.book_id));
  const remove = async (book: Book) => {
    const name = book.filename.replace(/\.(epub|pdf)$/i, "");
    const note = book.status === "completed" ? " and its translation" : "";
    if (!window.confirm(`Delete "${name}"${note}? Progress and glossary are removed too.`)) return;
    try {
      await api.deleteBook(book.id);
    } catch (e) {
      window.alert(e instanceof Error ? e.message : "Could not delete the book");
    }
    setSelected((s) => s.filter((x) => x !== book.id));
    load();
  };
  const toggle = (id: number, on: boolean) =>
    setSelected((s) => (on ? [...s, id] : s.filter((x) => x !== id)));

  return (
    <Page title="Library" description="Every book you uploaded, with its translation status.">
      {queue && queue.items.length > 0 && <QueuePanel queue={queue} books={books ?? []} onChange={load} />}

      {selected.length > 0 && (
        <div className="sticky top-0 z-10 flex items-center justify-between gap-3 rounded-lg bg-ink px-5 py-3 text-on-ink">
          <span className="text-sm">
            {selected.length} selected · translated in the order you picked them
          </span>
          <div className="flex gap-2">
            <button type="button" onClick={() => setSelected([])} className="text-sm text-on-ink/70 hover:text-on-ink">
              Clear
            </button>
            <Button size="sm" variant="secondary" onClick={() => setQueueing(true)}>
              <ListOrdered className="h-4 w-4" aria-hidden="true" /> Queue {selected.length}
            </Button>
          </div>
        </div>
      )}

      {books === null ? (
        <Loader2 className="mx-auto h-6 w-6 animate-spin text-faint" aria-label="Loading" />
      ) : books.length === 0 ? (
        <Card className="flex flex-col items-center gap-4 py-16 text-center">
          <BookOpen className="h-8 w-8 text-faint" aria-hidden="true" />
          <p className="m-0 text-muted">No books yet.</p>
          <Link to="/" className={buttonClass("primary")}>
            Upload your first book
          </Link>
        </Card>
      ) : (
        <ul className="m-0 flex list-none flex-col gap-3 p-0">
          {books.map((book) => {
            const isPdf = book.filename.toLowerCase().endsWith(".pdf");
            const pct = book.total_chapters
              ? Math.round((book.translated_chapters / book.total_chapters) * 100)
              : 0;
            const queued = waiting.has(book.id);
            const pickable = book.status !== "completed" && book.status !== "translating" && !queued;
            const order = selected.indexOf(book.id);
            return (
              <li key={book.id}>
                <Card className="flex flex-wrap items-center gap-4 p-5">
                  <div className="flex w-6 justify-center">
                    {pickable ? (
                      <Checkbox
                        checked={order >= 0}
                        onChange={(on) => toggle(book.id, on)}
                        label={`Select ${book.filename} for the queue`}
                      />
                    ) : null}
                  </div>
                  <div className="min-w-0 flex-1">
                    <Link
                      to={`/translate/${book.id}`}
                      className="block truncate font-serif text-xl font-medium text-ink no-underline hover:underline"
                    >
                      {order >= 0 && <span className="mr-2 text-accent">{order + 1}.</span>}
                      {book.filename.replace(/\.(epub|pdf)$/i, "")}
                    </Link>
                    <div className="mt-1 text-[13px] text-muted">
                      {isPdf ? "PDF" : "EPUB"} · {book.total_chapters} {isPdf ? "pages" : "chapters"} ·{" "}
                      <span className="capitalize">{languageName(book.source_language, "unknown")}</span> →{" "}
                      <span className="capitalize">{languageName(book.target_language, "italian")}</span> ·{" "}
                      {new Date(book.created_at).toLocaleDateString()}
                    </div>
                    {book.translated_chapters > 0 && book.status !== "completed" && (
                      <div
                        role="progressbar"
                        aria-label="Translated"
                        aria-valuenow={pct}
                        aria-valuemin={0}
                        aria-valuemax={100}
                        className="mt-3 h-1 max-w-xs overflow-hidden rounded-full bg-tint"
                      >
                        <div className="h-full bg-accent" style={{ width: `${pct}%` }} />
                      </div>
                    )}
                  </div>
                  <StatusPill status={pending.has(book.id) && book.status !== "translating" ? "queued" : book.status} />
                  <div className="flex gap-2">
                    {book.status === "completed" ? (
                      <>
                        <Link to={`/preview/${book.id}`} className={buttonClass("secondary", "sm")}>
                          <Eye className="h-4 w-4" aria-hidden="true" /> Preview
                        </Link>
                        <a href={api.downloadBook(book.id)} className={buttonClass("primary", "sm")}>
                          <Download className="h-4 w-4" aria-hidden="true" /> Download
                        </a>
                      </>
                    ) : (
                      <Link to={`/translate/${book.id}`} className={buttonClass("primary", "sm")}>
                        {book.status === "uploaded" && !queued ? "Translate" : "Open"}
                      </Link>
                    )}
                    {book.status !== "translating" && (
                      <button
                        type="button"
                        onClick={() => remove(book)}
                        aria-label={`Delete ${book.filename}`}
                        title="Delete"
                        className="rounded-full p-2 text-faint hover:bg-danger-soft hover:text-danger"
                      >
                        <Trash2 className="h-4 w-4" aria-hidden="true" />
                      </button>
                    )}
                  </div>
                </Card>
              </li>
            );
          })}
        </ul>
      )}

      {queueing && books && (
        <QueueDialog
          books={selected.map((id) => books.find((b) => b.id === id)).filter((b): b is Book => !!b)}
          onClose={() => setQueueing(false)}
          onQueued={() => {
            setSelected([]);
            load();
          }}
        />
      )}
    </Page>
  );
}
