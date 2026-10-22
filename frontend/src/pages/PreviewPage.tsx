import { useEffect, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { ArrowLeft, ChevronLeft, ChevronRight, Loader2 } from "lucide-react";
import { api, type Preview } from "../lib/api";
import { Button } from "../components/ui";

export function PreviewPage() {
  const { bookId } = useParams<{ bookId: string }>();
  const navigate = useNavigate();
  const [preview, setPreview] = useState<Preview | null>(null);
  const [searchParams] = useSearchParams();
  // ?page= is 1-based (the translate page links to the last translated one)
  const [chapterIndex, setChapterIndex] = useState(() => Math.max(0, Number(searchParams.get("page") || 1) - 1));
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!bookId) return;
    let cancelled = false;
    api
      .getPreview(parseInt(bookId), chapterIndex)
      .then((p) => !cancelled && setPreview(p))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [bookId, chapterIndex]);

  if (loading && !preview) {
    return (
      <div className="flex h-full items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-faint" aria-label="Loading" />
      </div>
    );
  }
  if (!preview) return <div className="p-8 text-muted">Preview not available.</div>;

  const step = (delta: number) => {
    setLoading(true);
    setChapterIndex((i) => Math.min(preview.total_chapters - 1, Math.max(0, i + delta)));
  };

  return (
    <div className="mx-auto flex h-full max-w-350 flex-col gap-4 px-4 py-6 sm:px-8">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Button size="sm" variant="ghost" onClick={() => navigate(-1)}>
          <ArrowLeft className="h-4 w-4" aria-hidden="true" /> Back
        </Button>
        <div className="flex items-center gap-2">
          <Button size="sm" onClick={() => step(-1)} disabled={chapterIndex === 0} aria-label="Previous">
            <ChevronLeft className="h-4 w-4" aria-hidden="true" />
          </Button>
          <label className="flex items-center gap-1.5 text-sm text-muted">
            <input
              key={chapterIndex}
              type="number"
              min={1}
              max={preview.total_chapters}
              defaultValue={chapterIndex + 1}
              aria-label="Go to"
              onKeyDown={(e) => e.key === "Enter" && e.currentTarget.blur()}
              onBlur={(e) => {
                const delta = Number(e.target.value) - 1 - chapterIndex;
                if (delta) step(delta);
              }}
              className="h-8 w-16 rounded-md border border-line bg-surface px-2 text-center text-ink"
            />
            of {preview.total_chapters}
          </label>
          <Button
            size="sm"
            onClick={() => step(1)}
            disabled={chapterIndex >= preview.total_chapters - 1}
            aria-label="Next"
          >
            <ChevronRight className="h-4 w-4" aria-hidden="true" />
          </Button>
        </div>
      </div>

      <div className="grid min-h-0 flex-1 grid-cols-1 overflow-hidden rounded-md border border-line bg-surface md:grid-cols-2">
        <section className="overflow-auto border-b border-line p-6 md:border-b-0 md:border-r">
          <div className="mb-3 text-[11px] uppercase tracking-[0.14em] text-faint">Original</div>
          <div className="whitespace-pre-wrap font-serif text-[17px] leading-relaxed text-muted">
            {preview.original_text || <span className="italic text-faint">No text on this page.</span>}
          </div>
        </section>
        <section className="overflow-auto p-6">
          <div className="mb-3 text-[11px] uppercase tracking-[0.14em] text-accent">Translation</div>
          <div className="whitespace-pre-wrap font-serif text-[17px] leading-relaxed text-ink">
            {preview.translated_text || <span className="italic text-faint">Not translated yet.</span>}
          </div>
        </section>
      </div>
    </div>
  );
}
