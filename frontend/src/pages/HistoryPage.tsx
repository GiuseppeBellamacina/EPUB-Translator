import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { BookOpen, Eye, Download, Loader2 } from "lucide-react";
import { api, type Book } from "../lib/api";
import { cn } from "../lib/utils";

const statusColors: Record<string, string> = {
  uploaded: "bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-300",
  analyzing: "bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-300",
  translating: "bg-gray-900 text-white dark:bg-white dark:text-gray-900",
  completed:
    "bg-gray-100 text-gray-900 dark:bg-gray-800 dark:text-gray-100 border border-gray-300 dark:border-gray-600",
  failed: "bg-red-50 text-red-600 dark:bg-red-950 dark:text-red-400",
};

const statusLabels: Record<string, string> = {
  uploaded: "uploaded",
  analyzing: "analyzing",
  translating: "translating",
  completed: "completed",
  failed: "failed",
};

export function HistoryPage() {
  const [books, setBooks] = useState<Book[]>([]);
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();

  useEffect(() => {
    api
      .getBooks()
      .then(setBooks)
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="h-full flex items-center justify-center">
        <Loader2 className="w-8 h-8 animate-spin text-slate-500 dark:text-slate-400" />
      </div>
    );
  }

  return (
    <div className="p-8 max-w-4xl mx-auto animate-fade-in-up">
      <h1 className="text-xl font-semibold mb-6 tracking-tight text-gray-900 dark:text-gray-100">
        Translation history
      </h1>

      {books.length === 0 ? (
        <div className="text-center py-16 surface rounded-lg">
          <BookOpen className="w-10 h-10 text-gray-300 dark:text-gray-600 mx-auto mb-4" />
          <p className="text-gray-500 dark:text-gray-400">
            No translated books yet
          </p>
          <button
            onClick={() => navigate("/")}
            className="mt-4 px-5 py-2.5 bg-gray-900 dark:bg-white text-white dark:text-gray-900 rounded-md hover:bg-gray-800 dark:hover:bg-gray-100 text-sm font-medium transition-colors"
          >
            Upload your first EPUB
          </button>
        </div>
      ) : (
        <div className="space-y-3">
          {books.map((book) => (
            <div
              key={book.id}
              className="surface rounded-lg p-4 flex items-center justify-between hover:border-gray-300 dark:hover:border-gray-700 transition-colors"
            >
              <div className="flex items-center gap-4">
                <div className="w-9 h-9 bg-gray-100 dark:bg-gray-900 rounded-md flex items-center justify-center">
                  <BookOpen className="w-4 h-4 text-gray-600 dark:text-gray-300" />
                </div>
                <div>
                  <h3 className="font-medium text-gray-900 dark:text-white text-sm">
                    {book.filename}
                  </h3>
                  <p className="text-xs text-gray-500 dark:text-gray-400">
                    {book.total_chapters} chapters · {book.source_language} →{" "}
                    {book.target_language}
                    {" · "}
                    {new Date(book.created_at).toLocaleDateString()}
                  </p>
                </div>
              </div>

              <div className="flex items-center gap-3">
                <span
                  className={cn(
                    "px-2.5 py-1 rounded-md text-xs font-medium",
                    statusColors[book.status] || statusColors.uploaded,
                  )}
                >
                  {statusLabels[book.status] || book.status}
                </span>

                <div className="flex gap-1">
                  {book.status === "completed" && (
                    <>
                      <button
                        onClick={() => navigate(`/preview/${book.id}`)}
                        className="p-2 text-gray-400 hover:text-gray-900 dark:hover:text-gray-100 rounded-md hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
                        title="Preview"
                      >
                        <Eye className="w-4 h-4" />
                      </button>
                      <a
                        href={api.downloadBook(book.id)}
                        className="p-2 text-gray-400 hover:text-gray-900 dark:hover:text-gray-100 rounded-md hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
                        title="Download"
                      >
                        <Download className="w-4 h-4" />
                      </a>
                    </>
                  )}
                  {(book.status === "uploaded" || book.status === "failed") && (
                    <button
                      onClick={() => navigate(`/translate/${book.id}`)}
                      className="p-2 text-gray-400 hover:text-gray-900 dark:hover:text-gray-100 rounded-md hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
                      title="Translate"
                    >
                      <BookOpen className="w-4 h-4" />
                    </button>
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
