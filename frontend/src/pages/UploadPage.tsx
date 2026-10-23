import { useState, useCallback } from "react";
import { Link, useNavigate } from "react-router-dom";
import { AlertCircle, ArrowRight, FileText, Languages, ListOrdered, ShieldCheck, Upload } from "lucide-react";
import { api, type Book } from "../lib/api";
import { buttonClass } from "../lib/styles";
import { cn } from "../lib/utils";
import { CostEstimate } from "../components/CostEstimate";
import { SortableItem, SortableList } from "../components/SortableList";
import { QueueDialog } from "../components/QueueDialog";
import { Button, Card, Page } from "../components/ui";

const STEPS = [
  { icon: FileText, label: "Analyze", desc: "Context and glossary" },
  { icon: Languages, label: "Translate", desc: "Consistent terminology" },
  { icon: ShieldCheck, label: "Review", desc: "Quality control" },
];

const bookName = (b: Book) => b.filename.replace(/\.(epub|pdf)$/i, "");

export function UploadPage() {
  const [isDragging, setIsDragging] = useState(false);
  const [uploading, setUploading] = useState<{ done: number; total: number } | null>(null);
  const [errors, setErrors] = useState<string[]>([]);
  const [uploaded, setUploaded] = useState<Book[]>([]);
  const [queueing, setQueueing] = useState(false);
  const navigate = useNavigate();

  const handleFiles = useCallback(async (files: File[]) => {
    const problems = files
      .filter((f) => !/\.(epub|pdf)$/i.test(f.name))
      .map((f) => `${f.name}: only .epub and .pdf files are supported`);
    const valid = files.filter((f) => /\.(epub|pdf)$/i.test(f.name));
    const books: Book[] = [];
    setUploading({ done: 0, total: valid.length });
    for (const file of valid) {
      // one at a time: each upload is parsed (and a PDF checked) on the server
      try {
        books.push(await api.uploadBook(file));
      } catch (e) {
        problems.push(`${file.name}: ${e instanceof Error ? e.message : "upload failed"}`);
      }
      setUploading({ done: books.length + problems.length, total: valid.length });
    }
    setUploading(null);
    setErrors(problems);
    setUploaded(books);
  }, []);

  const reorder = (ids: (string | number)[]) =>
    setUploaded((books) => ids.map((id) => books.find((b) => b.id === id)!));

  const reset = () => {
    setUploaded([]);
    setErrors([]);
  };

  const errorList = errors.length > 0 && (
    <div role="alert" className="flex flex-col gap-1 rounded-md bg-danger-soft p-3 text-sm text-danger">
      {errors.map((message) => (
        <div key={message} className="flex items-center gap-2">
          <AlertCircle className="h-4 w-4 shrink-0" aria-hidden="true" />
          {message}
        </div>
      ))}
    </div>
  );

  if (uploaded.length === 1) {
    const [book] = uploaded;
    const isPdf = book.filename.toLowerCase().endsWith(".pdf");
    return (
      <Page
        eyebrow={`${isPdf ? "PDF" : "EPUB"} · ${book.total_chapters} ${isPdf ? "pages" : "chapters"} uploaded`}
        title={bookName(book)}
        actions={
          <>
            <Button onClick={reset}>Upload another</Button>
            <Button variant="primary" onClick={() => navigate(`/translate/${book.id}`)}>
              Continue to translation <ArrowRight className="h-4 w-4" aria-hidden="true" />
            </Button>
          </>
        }
      >
        {errorList}
        <Card className="p-6">
          <CostEstimate bookId={book.id} />
        </Card>
      </Page>
    );
  }

  if (uploaded.length > 1) {
    return (
      <Page
        eyebrow={`${uploaded.length} books uploaded`}
        title="Ready to translate"
        description="Put them in the order you want, then queue them with the same settings, or open each one."
        actions={
          <>
            <Button onClick={reset}>Upload more</Button>
            <Button variant="primary" onClick={() => setQueueing(true)}>
              <ListOrdered className="h-4 w-4" aria-hidden="true" /> Queue {uploaded.length} books
            </Button>
          </>
        }
      >
        {errorList}
        <SortableList ids={uploaded.map((b) => b.id)} onReorder={reorder}>
        <ol className="m-0 flex list-none flex-col gap-3 p-0">
          {uploaded.map((book, n) => {
            const isPdf = book.filename.toLowerCase().endsWith(".pdf");
            return (
              <SortableItem key={book.id} id={book.id} label={bookName(book)} className="flex items-center gap-4 rounded-md border border-line bg-surface p-5">
                  <span className="w-5 text-right font-serif text-faint">{n + 1}</span>
                  <div className="min-w-0 flex-1">
                    <div className="truncate font-serif text-xl font-medium">{bookName(book)}</div>
                    <div className="mt-1 text-[13px] text-muted">
                      {isPdf ? "PDF" : "EPUB"} · {book.total_chapters} {isPdf ? "pages" : "chapters"}
                    </div>
                  </div>
                  <Link to={`/translate/${book.id}`} className={buttonClass("secondary", "sm")}>
                    Open
                  </Link>
              </SortableItem>
            );
          })}
        </ol>
        </SortableList>
        {queueing && (
          <QueueDialog books={uploaded} onClose={() => setQueueing(false)} onQueued={() => navigate("/library")} />
        )}
      </Page>
    );
  }

  return (
    <Page
      title="Translate a book"
      description="Upload one or more EPUB or PDF files. The translation keeps the same format and layout; only the language changes."
    >
      <label
        onDragOver={(e) => {
          e.preventDefault();
          setIsDragging(true);
        }}
        onDragLeave={() => setIsDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setIsDragging(false);
          if (e.dataTransfer.files.length) handleFiles([...e.dataTransfer.files]);
        }}
        className={cn(
          "flex h-64 w-full cursor-pointer flex-col items-center justify-center gap-3 rounded-md border border-dashed bg-surface transition-colors",
          isDragging ? "border-accent bg-accent-soft" : "border-line-strong hover:border-ink",
          uploading && "pointer-events-none opacity-60",
        )}
      >
        {uploading ? (
          <>
            <div className="h-10 w-10 animate-spin rounded-full border-2 border-line border-t-ink" aria-hidden="true" />
            <span className="text-sm text-muted" role="status">
              Uploading {Math.min(uploading.done + 1, uploading.total)} of {uploading.total}…
            </span>
          </>
        ) : (
          <>
            <span className="flex h-12 w-12 items-center justify-center rounded-full bg-ink text-on-ink">
              <Upload className="h-5 w-5" aria-hidden="true" />
            </span>
            <span className="text-sm text-muted">
              <span className="font-semibold text-ink">Click to upload</span> or drag and drop
            </span>
            <span className="text-xs text-faint">.epub or .pdf · several files at once</span>
          </>
        )}
        <input
          type="file"
          multiple
          className="sr-only"
          accept=".epub,.pdf"
          onChange={(e) => {
            if (e.target.files?.length) handleFiles([...e.target.files]);
            e.target.value = ""; // the same files can be picked again
          }}
          disabled={!!uploading}
        />
      </label>

      {errorList}

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        {STEPS.map(({ icon: Icon, label, desc }) => (
          <Card key={label} className="flex items-center gap-3 p-4">
            <Icon className="h-5 w-5 text-accent" aria-hidden="true" />
            <div>
              <div className="font-serif text-lg font-medium">{label}</div>
              <div className="text-xs text-muted">{desc}</div>
            </div>
          </Card>
        ))}
      </div>
    </Page>
  );
}
