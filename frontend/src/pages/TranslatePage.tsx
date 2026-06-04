import { useEffect, useRef, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import {
  Play,
  Square,
  Eye,
  Download,
  BookOpen,
  Loader2,
  Wand2,
  Cpu,
  Languages,
  Activity,
} from "lucide-react";
import {
  api,
  type BookDetail,
  type Provider,
  type GlossaryEntry,
} from "../lib/api";
import { useTranslationWs } from "../hooks/useTranslationWs";
import { useStore } from "../stores/appStore";
import { cn } from "../lib/utils";
import { GlossaryEditor } from "../components/GlossaryEditor";

const inputClass =
  "w-full rounded-md border border-gray-300 dark:border-gray-700 bg-white dark:bg-[#0a0a0a] px-3 py-2 text-sm text-gray-900 dark:text-gray-100 placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-gray-900 dark:focus:ring-gray-100 focus:border-transparent transition";

export function TranslatePage() {
  const { bookId } = useParams<{ bookId: string }>();
  const navigate = useNavigate();
  const [book, setBook] = useState<BookDetail | null>(null);
  const [providers, setProviders] = useState<Provider[]>([]);
  const [glossary, setGlossary] = useState<GlossaryEntry[]>([]);
  const [selectedProvider, setSelectedProvider] = useState<number | null>(null);
  const [model, setModel] = useState("");
  const [sourceLang, setSourceLang] = useState("english");
  const [targetLang, setTargetLang] = useState("italian");
  const [styleInstructions, setStyleInstructions] = useState("");
  const [loading, setLoading] = useState(true);

  const { startTranslation, stopTranslation, isConnected, logs, liveText } =
    useTranslationWs();
  const progress = useStore((s) => s.translationProgress);
  const liveRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (liveRef.current) {
      liveRef.current.scrollTop = liveRef.current.scrollHeight;
    }
  }, [liveText]);

  useEffect(() => {
    if (!bookId) return;
    const id = parseInt(bookId);
    Promise.all([
      api.getBook(id),
      api.getProviders(),
      api.getGlossary(id),
    ]).then(([b, p, g]) => {
      setBook(b);
      setProviders(p);
      setGlossary(g);
      if (p.length > 0) {
        setSelectedProvider(p[0].id);
        setModel(p[0].default_model || "");
      }
      setSourceLang(b.source_language || "english");
      setTargetLang(b.target_language || "italian");
      setLoading(false);
    });
  }, [bookId]);

  const handleStart = () => {
    if (!bookId || !selectedProvider) return;
    startTranslation({
      bookId: parseInt(bookId),
      providerId: selectedProvider,
      sourceLanguage: sourceLang,
      targetLanguage: targetLang,
      model: model || undefined,
      styleInstructions: styleInstructions || undefined,
    });
  };

  if (loading) {
    return (
      <div className="h-full flex items-center justify-center">
        <Loader2 className="w-8 h-8 animate-spin text-slate-500 dark:text-slate-400" />
      </div>
    );
  }

  if (!book) return <div className="p-8">Book not found</div>;

  const isRunning = isConnected;
  const isCompleted =
    book.status === "completed" || logs.some((l) => l.event === "job_complete");
  const chapterPct = progress?.total_chapters
    ? ((progress.chapter_index || 0) / progress.total_chapters) * 100
    : 0;

  return (
    <div className="h-full flex flex-col">
      {/* Header */}
      <div className="border-b border-gray-200 dark:border-gray-800 bg-white dark:bg-[#0a0a0a] px-6 py-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-md bg-gray-100 dark:bg-gray-900 flex items-center justify-center">
              <BookOpen className="w-4 h-4 text-gray-600 dark:text-gray-300" />
            </div>
            <div>
              <h1 className="text-base font-semibold text-gray-900 dark:text-gray-100 truncate max-w-md">
                {book.filename}
              </h1>
              <p className="text-sm text-gray-500 dark:text-gray-400 flex items-center gap-1.5">
                {book.total_chapters} chapters
                <span className="text-gray-300 dark:text-gray-600">·</span>
                <span className="capitalize">{sourceLang}</span>
                <span className="text-gray-400">→</span>
                <span className="capitalize">{targetLang}</span>
              </p>
            </div>
          </div>
          <div className="flex gap-2">
            {isCompleted && (
              <>
                <button
                  onClick={() => navigate(`/preview/${book.id}`)}
                  className="flex items-center gap-2 px-4 py-2 rounded-md border border-gray-300 dark:border-gray-700 text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-900 text-sm font-medium transition-colors"
                >
                  <Eye className="w-4 h-4" /> Preview
                </button>
                <a
                  href={api.downloadBook(book.id)}
                  className="flex items-center gap-2 px-4 py-2 rounded-md bg-gray-900 dark:bg-white text-white dark:text-gray-900 hover:bg-gray-800 dark:hover:bg-gray-100 text-sm font-medium transition-colors"
                >
                  <Download className="w-4 h-4" /> Download
                </a>
              </>
            )}
          </div>
        </div>
      </div>

      <div className="flex-1 flex overflow-hidden">
        {/* Config panel */}
        <div className="w-80 border-r border-gray-200 dark:border-gray-800 bg-white dark:bg-[#0a0a0a] overflow-auto">
          <div className="p-6 space-y-5">
            <h2 className="flex items-center gap-2 text-sm font-semibold text-gray-900 dark:text-gray-100">
              <Cpu className="w-4 h-4 text-gray-400" /> Configuration
            </h2>

            {/* Provider selection */}
            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1.5">
                Provider
              </label>
              <select
                value={selectedProvider || ""}
                onChange={(e) => {
                  const id = parseInt(e.target.value);
                  setSelectedProvider(id);
                  const p = providers.find((p) => p.id === id);
                  if (p) setModel(p.default_model || "");
                }}
                className={inputClass}
                disabled={isRunning}
              >
                {providers.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name} ({p.provider_type})
                  </option>
                ))}
              </select>
              {providers.length === 0 && (
                <p className="text-xs text-red-500 mt-1">
                  No providers.{" "}
                  <button
                    onClick={() => navigate("/settings")}
                    className="underline"
                  >
                    Add one
                  </button>
                </p>
              )}
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1.5">
                Model
              </label>
              <input
                type="text"
                value={model}
                onChange={(e) => setModel(e.target.value)}
                placeholder="gpt-4o-mini"
                className={inputClass}
                disabled={isRunning}
              />
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1.5">
                  From
                </label>
                <input
                  type="text"
                  value={sourceLang}
                  onChange={(e) => setSourceLang(e.target.value)}
                  className={inputClass}
                  disabled={isRunning}
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1.5">
                  To
                </label>
                <input
                  type="text"
                  value={targetLang}
                  onChange={(e) => setTargetLang(e.target.value)}
                  className={inputClass}
                  disabled={isRunning}
                />
              </div>
            </div>

            {/* Style instructions */}
            <div>
              <label className="flex items-center gap-1.5 text-sm font-medium text-gray-700 dark:text-gray-300 mb-1.5">
                <Wand2 className="w-4 h-4 text-gray-400" /> Style instructions
              </label>
              <textarea
                value={styleInstructions}
                onChange={(e) => setStyleInstructions(e.target.value)}
                placeholder="E.g. informal tone, keep a poetic register…"
                rows={3}
                className={cn(inputClass, "resize-none leading-relaxed")}
                disabled={isRunning}
              />
              <p className="text-[11px] text-gray-400 mt-1">
                Free-form guidance on tone, register and style, applied to every
                chapter.
              </p>
            </div>

            {/* Glossary editor */}
            <div className="pt-1 border-t border-gray-200 dark:border-gray-800">
              <div className="pt-4">
                <GlossaryEditor
                  bookId={parseInt(bookId!)}
                  initial={glossary}
                  disabled={isRunning}
                />
              </div>
            </div>

            {/* Start/Stop button */}
            <div className="pt-2">
              {!isRunning ? (
                <button
                  onClick={handleStart}
                  disabled={!selectedProvider || isCompleted}
                  className="w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-md bg-gray-900 dark:bg-white text-white dark:text-gray-900 font-medium hover:bg-gray-800 dark:hover:bg-gray-100 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  <Play className="w-4 h-4" />
                  {isCompleted ? "Translation completed" : "Start translation"}
                </button>
              ) : (
                <button
                  onClick={stopTranslation}
                  className="w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-md bg-red-600 text-white font-medium hover:bg-red-700 transition-colors"
                >
                  <Square className="w-4 h-4" /> Stop
                </button>
              )}
            </div>
          </div>
        </div>

        {/* Progress / Live / Logs panel */}
        <div className="flex-1 p-6 overflow-auto">
          {/* Progress bar */}
          {progress && (
            <div className="mb-6 rounded-lg surface p-4 animate-fade-in-up">
              <div className="flex justify-between text-sm text-gray-600 dark:text-gray-300 mb-3">
                <span className="font-medium">
                  Chapter {(progress.chapter_index || 0) + 1} /{" "}
                  {progress.total_chapters || book.total_chapters}
                </span>
                {progress.total_chunks > 0 && (
                  <span className="text-gray-400">
                    Chunk {(progress.chunk_index || 0) + 1} /{" "}
                    {progress.total_chunks}
                  </span>
                )}
              </div>
              <div className="w-full bg-gray-100 dark:bg-gray-900 rounded-full h-1.5 overflow-hidden">
                <div
                  className="h-1.5 rounded-full bg-gray-900 dark:bg-white transition-all duration-500"
                  style={{ width: `${chapterPct}%` }}
                />
              </div>
            </div>
          )}

          {/* Live translation */}
          {(isRunning || liveText) && (
            <div className="mb-6">
              <h3 className="flex items-center gap-2 text-sm font-medium text-gray-700 dark:text-gray-300 mb-3">
                <Languages className="w-4 h-4 text-gray-400" /> Live translation
              </h3>
              <div
                ref={liveRef}
                className="surface rounded-lg p-5 max-h-[40vh] overflow-auto whitespace-pre-wrap text-sm leading-relaxed text-gray-800 dark:text-gray-200"
              >
                {liveText || (
                  <span className="text-gray-400 italic">
                    Translated text will stream here as each chunk completes…
                  </span>
                )}
              </div>
            </div>
          )}

          {/* Log messages */}
          <div>
            <h3 className="flex items-center gap-2 text-sm font-medium text-gray-700 dark:text-gray-300 mb-3">
              <Activity className="w-4 h-4 text-gray-400" /> Activity log
            </h3>
            {logs.length === 0 && (
              <div className="flex flex-col items-center justify-center text-center py-16 rounded-lg border border-dashed border-gray-300 dark:border-gray-700">
                <Languages className="w-9 h-9 text-gray-300 dark:text-gray-600 mb-3" />
                <p className="text-sm text-gray-500 dark:text-gray-400">
                  Configure the settings and start the translation
                </p>
                <p className="text-xs text-gray-400 mt-1">
                  Progress will appear here in real time.
                </p>
              </div>
            )}
            <div className="space-y-2">
              {logs.map((log, i) => (
                <div
                  key={i}
                  className={cn(
                    "px-4 py-2.5 rounded-md text-sm border",
                    log.event === "error"
                      ? "bg-red-50 dark:bg-red-950 border-red-200 dark:border-red-900 text-red-700 dark:text-red-300"
                      : log.event === "job_complete"
                        ? "bg-gray-900 dark:bg-white border-gray-900 dark:border-white text-white dark:text-gray-900"
                        : "bg-white dark:bg-[#0a0a0a] border-gray-200 dark:border-gray-800 text-gray-700 dark:text-gray-300",
                  )}
                >
                  {log.message}
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
