import { useEffect, useState } from "react";
import { Dialog, DialogPanel, DialogTitle } from "@headlessui/react";
import { Loader2 } from "lucide-react";
import { api, type Book, type Provider } from "../lib/api";
import { settingsFrom, toRunConfig, type RunSettings } from "../lib/runSettings";
import { Toggle } from "./controls";
import { RunSettingsFields } from "./RunSettingsFields";
import { Button } from "./ui";

/** One set of settings for several books, translated one after another. */
export function QueueDialog({
  books,
  onClose,
  onQueued,
}: {
  /** in queue order */
  books: Book[];
  onClose: () => void;
  onQueued: () => void;
}) {
  const [providers, setProviders] = useState<Provider[]>([]);
  const [settings, setSettings] = useState<RunSettings | null>(null);
  const [keepGlossary, setKeepGlossary] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.getProviders().then((p) => {
      setProviders(p);
      setSettings({ ...settingsFrom(null, p), sourceLang: "" }); // "": each book's own
    });
  }, []);

  const submit = async () => {
    if (!settings) return;
    setSaving(true);
    setError(null);
    try {
      await api.addToQueue(
        books.map((b) => b.id),
        toRunConfig(settings),
        keepGlossary,
      );
      onQueued();
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not queue the books");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open onClose={onClose} className="relative z-50">
      <div className="fixed inset-0 bg-ink/35" aria-hidden="true" />
      <div className="fixed inset-0 flex items-start justify-center overflow-auto p-4 pt-12">
        <DialogPanel className="w-full max-w-xl overflow-hidden rounded-lg bg-surface shadow-[0_24px_60px_rgba(27,36,51,0.18)]">
          <div className="border-b border-line px-6 py-5">
            <DialogTitle className="m-0 font-serif text-[26px] font-medium">
              Queue {books.length} {books.length === 1 ? "book" : "books"}
            </DialogTitle>
            <p className="m-0 mt-1 text-sm text-muted">
              Translated one after another on the server, in this order. You can close the page.
            </p>
          </div>

          <div className="flex flex-col gap-5 px-6 py-5">
            <ol className="m-0 flex list-decimal flex-col gap-1 rounded-md bg-tint px-4 py-3 pl-9 text-sm">
              {books.map((b) => (
                <li key={b.id} className="truncate">
                  {b.filename.replace(/\.(epub|pdf)$/i, "")}
                </li>
              ))}
            </ol>

            {settings ? (
              <RunSettingsFields
                providers={providers}
                value={settings}
                onChange={(patch) => setSettings((s) => s && { ...s, ...patch })}
                sourceAuto
              />
            ) : (
              <Loader2 className="mx-auto h-5 w-5 animate-spin text-faint" aria-label="Loading" />
            )}

            <div className="flex flex-col gap-1">
              <Toggle
                checked={keepGlossary}
                onChange={setKeepGlossary}
                label="Keep the glossary from one book to the next"
              />
              <p className="m-0 pl-12 text-xs text-faint">
                {keepGlossary
                  ? "Each book starts with the terms of the book before it (same series)."
                  : "Each book starts with its own glossary."}
              </p>
            </div>

            {error && <p className="m-0 text-sm text-danger">{error}</p>}
          </div>

          <div className="flex justify-end gap-2.5 border-t border-line px-6 py-4">
            <Button onClick={onClose}>Cancel</Button>
            <Button variant="primary" onClick={submit} disabled={saving || !settings?.providerId}>
              {saving && <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />}
              Start queue
            </Button>
          </div>
        </DialogPanel>
      </div>
    </Dialog>
  );
}
