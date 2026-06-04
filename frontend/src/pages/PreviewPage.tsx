import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { ArrowLeft, ChevronLeft, ChevronRight, Loader2 } from "lucide-react";
import { api, type Preview } from "../lib/api";

export function PreviewPage() {
  const { bookId } = useParams<{ bookId: string }>();
  const navigate = useNavigate();
  const [preview, setPreview] = useState<Preview | null>(null);
  const [chapterIndex, setChapterIndex] = useState(0);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!bookId) return;
    let cancelled = false;
    const load = async () => {
      setLoading(true);
      try {
        const p = await api.getPreview(parseInt(bookId), chapterIndex);
        if (!cancelled) setPreview(p);
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    load();
    return () => {
      cancelled = true;
    };
  }, [bookId, chapterIndex]);

  if (loading) {
    return (
      <div className="h-full flex items-center justify-center">
        <Loader2 className="w-8 h-8 animate-spin text-gray-400" />
      </div>
    );
  }

  if (!preview) return <div className="p-8">Preview not available</div>;

  return (
    <div className="h-full flex flex-col">
      {/* Navigation */}
      <div className="border-b border-gray-200 dark:border-gray-800 px-6 py-3 flex items-center justify-between">
        <button
          onClick={() => navigate(-1)}
          className="flex items-center gap-2 text-sm text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-gray-100 transition-colors"
        >
          <ArrowLeft className="w-4 h-4" />
          Back
        </button>
        <div className="flex items-center gap-1">
          <button
            onClick={() => setChapterIndex(Math.max(0, chapterIndex - 1))}
            disabled={chapterIndex === 0}
            className="p-2 rounded-md hover:bg-gray-100 dark:hover:bg-gray-900 disabled:opacity-30 transition-colors"
          >
            <ChevronLeft className="w-5 h-5" />
          </button>
          <span className="text-sm font-medium text-gray-700 dark:text-gray-300 min-w-28 text-center">
            Chapter {chapterIndex + 1} / {preview.total_chapters}
          </span>
          <button
            onClick={() =>
              setChapterIndex(
                Math.min(preview.total_chapters - 1, chapterIndex + 1),
              )
            }
            disabled={chapterIndex >= preview.total_chapters - 1}
            className="p-2 rounded-md hover:bg-gray-100 dark:hover:bg-gray-900 disabled:opacity-30 transition-colors"
          >
            <ChevronRight className="w-5 h-5" />
          </button>
        </div>
      </div>

      {/* Side by side */}
      <div className="flex-1 flex overflow-hidden">
        {/* Original */}
        <div className="flex-1 border-r border-gray-200 dark:border-gray-800 overflow-auto">
          <div className="p-6">
            <h3 className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-3">
              Original
            </h3>
            <div className="prose prose-sm dark:prose-invert max-w-none whitespace-pre-wrap text-gray-800 dark:text-gray-200 leading-relaxed">
              {preview.original_text}
            </div>
          </div>
        </div>

        {/* Translated */}
        <div className="flex-1 overflow-auto">
          <div className="p-6">
            <h3 className="text-xs font-semibold text-gray-900 dark:text-gray-100 uppercase tracking-wider mb-3">
              Translated
            </h3>
            <div className="prose prose-sm dark:prose-invert max-w-none whitespace-pre-wrap text-gray-800 dark:text-gray-200 leading-relaxed">
              {preview.translated_text || (
                <p className="italic text-gray-400">
                  Translation not available yet
                </p>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
