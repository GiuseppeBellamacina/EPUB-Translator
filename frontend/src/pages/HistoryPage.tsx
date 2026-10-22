import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { BookOpen, Download, Eye, Loader2 } from "lucide-react";
import { api, type Book } from "../lib/api";
import { buttonClass } from "../lib/styles";
import { Card, Page, StatusPill } from "../components/ui";

export function HistoryPage() {
  const [books, setBooks] = useState<Book[] | null>(null);

  useEffect(() => {
    api.getBooks().then(setBooks);
  }, []);

  return (
    <Page title="Library" description="Every book you uploaded, with its translation status.">
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
            return (
              <li key={book.id}>
                <Card className="flex flex-wrap items-center gap-4 p-5">
                  <div className="min-w-0 flex-1">
                    <Link
                      to={`/translate/${book.id}`}
                      className="block truncate font-serif text-xl font-medium text-ink no-underline hover:underline"
                    >
                      {book.filename.replace(/\.(epub|pdf)$/i, "")}
                    </Link>
                    <div className="mt-1 text-[13px] text-muted">
                      {isPdf ? "PDF" : "EPUB"} · {book.total_chapters} {isPdf ? "pages" : "chapters"} ·{" "}
                      <span className="capitalize">{book.source_language}</span> →{" "}
                      <span className="capitalize">{book.target_language}</span> ·{" "}
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
                  <StatusPill status={book.status} />
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
                        {book.status === "uploaded" ? "Translate" : "Open"}
                      </Link>
                    )}
                  </div>
                </Card>
              </li>
            );
          })}
        </ul>
      )}
    </Page>
  );
}
