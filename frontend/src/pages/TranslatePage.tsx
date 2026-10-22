import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Dialog, DialogPanel, DialogTitle } from "@headlessui/react";
import { Download, Eye, Loader2, Pause, Play, RotateCcw } from "lucide-react";
import {
  api,
  type BookDetail,
  type BookProgress,
  type GlossaryEntry,
  type Provider,
} from "../lib/api";
import { liveChunks } from "../lib/jobEvents";
import { settingsFrom, type RunSettings } from "../lib/runSettings";
import { buttonClass } from "../lib/styles";
import { useTranslationWs } from "../hooks/useTranslationWs";
import { ActivityLog } from "../components/ActivityLog";
import { ModelCost } from "../components/CostEstimate";
import { GlossaryEditor } from "../components/GlossaryEditor";
import { LiveView } from "../components/LiveView";
import { ProgressPanel } from "../components/ProgressPanel";
import { RunSettingsFields } from "../components/RunSettingsFields";
import { Button, Card, Heading, Page, StatusPill } from "../components/ui";

export function TranslatePage() {
  const { bookId } = useParams<{ bookId: string }>();
  const id = Number(bookId);
  const [book, setBook] = useState<BookDetail | null>(null);
  const [providers, setProviders] = useState<Provider[]>([]);
  const [glossary, setGlossary] = useState<GlossaryEntry[]>([]);
  const [progress, setProgress] = useState<BookProgress | null>(null);
  const [settings, setSettings] = useState<RunSettings>(() => settingsFrom(null, []));
  const [glossaryOpen, setGlossaryOpen] = useState(false);
  const [totalCost, setTotalCost] = useState<{ with: number; without: number } | null>(null);
  const { providerId, model, enableReview, reviewModel, sourceLang, targetLang, style } = settings;

  const refresh = useCallback(() => {
    api.getBook(id).then(setBook);
    api.getProgress(id).then(setProgress);
    api.getGlossary(id).then(setGlossary);
  }, [id]);

  const { startTranslation, watchTranslation, stopTranslation, disconnect, isConnected, events, setEvents } =
    useTranslationWs(refresh);

  useEffect(() => {
    let active = true;
    Promise.all([api.getBook(id), api.getProviders(), api.getGlossary(id), api.getProgress(id)]).then(
      ([b, p, g, prog]) => {
        if (!active) return;
        setBook(b);
        setProviders(p);
        setGlossary(g);
        setProgress(prog);
        setEvents(prog.recent_events); // the recent log survives a page reload
        // The last run's settings, so a running or paused job shows (and resumes with) its own
        setSettings(settingsFrom(prog.config, p, { source: b.source_language, target: b.target_language }));
        if (prog.running || prog.queue_status === "pending") watchTranslation(id);
      },
    );
    return () => {
      active = false;
      disconnect(); // leaving the page stops following, the job goes on
    };
  }, [id, setEvents, watchTranslation, disconnect]);

  // Poll the run state while a job is running (counts, in flight, ETA)
  const running = isConnected || !!progress?.running;
  useEffect(() => {
    if (!running) return;
    const timer = setInterval(() => api.getProgress(id).then(setProgress), 4000);
    return () => clearInterval(timer);
  }, [running, id]);

  // New glossary terms appear in the side panel as they are found
  const latest = events[0];
  useEffect(() => {
    if (latest?.event === "glossary_update" || latest?.event === "analysis_complete") {
      api.getGlossary(id).then(setGlossary);
    }
  }, [latest, id]);

  useEffect(() => {
    if (providerId === null || !model) return;
    let current = true;
    api
      .getEstimate(id, { providerId, model })
      .then((e) => {
        const row = e.models[0];
        if (current) setTotalCost(row ? { with: row.with_review.cost, without: row.without_review.cost } : null);
      })
      .catch(() => current && setTotalCost(null));
    return () => {
      current = false;
    };
  }, [id, providerId, model]);

  const chunks = useMemo(() => liveChunks(events), [events]);

  if (!book) {
    return (
      <div className="flex h-full items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-faint" aria-label="Loading" />
      </div>
    );
  }

  const isPdf = book.filename.toLowerCase().endsWith(".pdf");
  const unitName = isPdf ? "pages" : "chapters";
  const unitAbbr = isPdf ? "p." : "ch.";
  const done = progress?.completed_units ?? book.translated_chapters;
  const isCompleted = book.status === "completed";
  const canResume = !isCompleted && done > 0;
  const total = totalCost && (enableReview ? totalCost.with : totalCost.without);
  const spent =
    total !== null && total !== undefined && book.total_chapters
      ? `$${((total * done) / book.total_chapters).toFixed(2)}`
      : null;

  const start = (restart = false) => {
    if (providerId === null) return;
    if (restart && !window.confirm("Discard all saved progress and translate the book from scratch?")) return;
    startTranslation({
      bookId: id,
      providerId,
      model: model || undefined,
      sourceLanguage: sourceLang,
      targetLanguage: targetLang,
      styleInstructions: style || undefined,
      enableReview,
      reviewModel: enableReview ? reviewModel : undefined,
      restart,
    });
  };

  return (
    <Page
      wide
      eyebrow={`${isPdf ? "PDF" : "EPUB"} · ${book.total_chapters} ${unitName} · ${sourceLang} to ${targetLang}`}
      title={book.filename.replace(/\.(epub|pdf)$/i, "")}
      actions={
        <>
          <StatusPill status={running ? "translating" : book.status} />
          {done > 0 && (
            <Link to={`/preview/${id}?page=${done}`} className={buttonClass()}>
              <Eye className="h-4 w-4" aria-hidden="true" /> Preview
            </Link>
          )}
          {isCompleted && !running && (
            <a href={api.downloadBook(id)} className={buttonClass()}>
              <Download className="h-4 w-4" aria-hidden="true" /> Download
            </a>
          )}
          {running ? (
            <Button
              variant="primary"
              onClick={() => (isConnected ? stopTranslation() : api.stopTranslation(id))}
            >
              <Pause className="h-4 w-4" aria-hidden="true" /> Pause
            </Button>
          ) : (
            <>
              {(canResume || isCompleted) && (
                <Button onClick={() => start(true)} disabled={providerId === null}>
                  <RotateCcw className="h-4 w-4" aria-hidden="true" /> Start over
                </Button>
              )}
              {!isCompleted && (
                <Button variant="primary" onClick={() => start(false)} disabled={providerId === null}>
                  <Play className="h-4 w-4" aria-hidden="true" />
                  {canResume ? `Resume (${done}/${book.total_chapters})` : "Start translation"}
                </Button>
              )}
            </>
          )}
        </>
      }
    >
      <div className="flex flex-wrap items-start gap-5">
        <Card aria-labelledby="config-title" className="flex w-full flex-col gap-5 p-5 lg:max-w-sm">
          <Heading id="config-title">Configuration</Heading>

          <RunSettingsFields
            providers={providers}
            value={settings}
            onChange={(patch) => setSettings((s) => ({ ...s, ...patch }))}
            disabled={running}
          />

          <div className="flex items-center justify-between rounded-md bg-tint p-3.5">
            <div>
              <div className="font-semibold">Glossary</div>
              <div className="text-[13px] text-muted">{glossary.length} terms</div>
            </div>
            <Button size="sm" onClick={() => setGlossaryOpen(true)}>
              {running ? "View" : "Edit"}
            </Button>
          </div>

          {providerId !== null && model && (
            <div className="flex items-center justify-between border-t border-line pt-3.5">
              <span className="text-muted">Estimated total</span>
              <span className="font-serif text-xl">
                <ModelCost bookId={id} providerId={providerId} model={model} withReview={enableReview} reviewModel={reviewModel} />
              </span>
            </div>
          )}
        </Card>

        <div className="flex min-w-0 flex-[999_1_560px] flex-col gap-5">
          <ProgressPanel progress={progress} unitName={unitName} unitAbbr={unitAbbr} spent={spent} />
          <LiveView chunks={chunks} unitName={isPdf ? "Page" : "Chapter"} targetLanguage={targetLang} />
          <ActivityLog events={events} unitAbbr={unitAbbr} />
        </div>
      </div>

      <Dialog open={glossaryOpen} onClose={() => setGlossaryOpen(false)} className="relative z-50">
        <div className="fixed inset-0 bg-ink/35" aria-hidden="true" />
        <div className="fixed inset-0 flex items-start justify-center overflow-auto p-4 pt-16">
          <DialogPanel className="w-full max-w-2xl rounded-lg bg-surface p-6 shadow-[0_24px_60px_rgba(27,36,51,0.18)]">
            <div className="mb-4 flex items-baseline justify-between gap-3">
              <DialogTitle className="m-0 font-serif text-[26px] font-medium">Glossary</DialogTitle>
              <Button size="sm" variant="ghost" onClick={() => setGlossaryOpen(false)}>
                Close
              </Button>
            </div>
            <p className="mb-4 mt-0 text-sm text-muted">
              Terms the translation must follow. New recurring names are added automatically while
              translating; your edits are never overwritten.
            </p>
            <GlossaryEditor
              bookId={id}
              initial={glossary}
              disabled={running}
              onSaved={() => api.getGlossary(id).then(setGlossary)}
            />
          </DialogPanel>
        </div>
      </Dialog>
    </Page>
  );
}
