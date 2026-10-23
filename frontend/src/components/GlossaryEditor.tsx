import { useState } from "react";
import { Check, Loader2, Plus, Save, Trash2 } from "lucide-react";
import { api, type GlossaryEntry, type GlossaryEntryCreate } from "../lib/api";
import { inputClass } from "../lib/styles";
import { cn } from "../lib/utils";
import { Checkbox } from "./controls";
import { Button } from "./ui";

interface EditableEntry {
  id?: number;
  source_term: string;
  target_term: string;
  do_not_translate: boolean;
  dirty?: boolean;
}

interface GlossaryEditorProps {
  bookId: number;
  initial: GlossaryEntry[];
  running?: boolean;
  onSaved?: () => void;
}

const editable = (g: GlossaryEntry): EditableEntry => ({
  id: g.id,
  source_term: g.source_term,
  target_term: g.target_term,
  do_not_translate: g.do_not_translate,
});

const clean = (e: EditableEntry): GlossaryEntryCreate => ({
  source_term: e.source_term.trim(),
  target_term: e.do_not_translate ? e.source_term.trim() : e.target_term.trim(),
  do_not_translate: e.do_not_translate,
});

/** Single terms are saved on their own, also while translating; the whole list only when idle. */
export function GlossaryEditor({ bookId, initial, running, onSaved }: GlossaryEditorProps) {
  const [entries, setEntries] = useState<EditableEntry[]>(() => initial.map(editable));
  const [saving, setSaving] = useState(false);
  const [busyRow, setBusyRow] = useState<number | null>(null);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const update = (index: number, patch: Partial<EditableEntry>) => {
    setEntries((prev) => prev.map((e, i) => (i === index ? { ...e, ...patch, dirty: true } : e)));
    setSaved(false);
  };

  const attempt = async (action: () => Promise<void>, failure: string) => {
    setError(null);
    try {
      await action();
      onSaved?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : failure);
    }
  };

  const handleSave = async () => {
    setSaving(true);
    await attempt(async () => {
      await api.updateGlossary(bookId, entries.map(clean).filter((e) => e.source_term));
      setEntries((await api.getGlossary(bookId)).map(editable)); // fresh ids for single edits
      setSaved(true);
    }, "Failed to save the glossary");
    setSaving(false);
  };

  const saveRow = async (index: number) => {
    const { id } = entries[index];
    const entry = clean(entries[index]);
    if (!entry.source_term) return setError("A term cannot be empty");
    setBusyRow(index);
    await attempt(async () => {
      const stored = id ? await api.editGlossaryEntry(bookId, id, entry) : await api.addGlossaryEntry(bookId, entry);
      setEntries((prev) => prev.map((e, i) => (i === index ? editable(stored) : e)));
    }, `Could not save ${entry.source_term}`);
    setBusyRow(null);
  };

  const removeRow = async (index: number) => {
    const { id, source_term } = entries[index];
    setBusyRow(index);
    await attempt(async () => {
      if (id) await api.deleteGlossaryEntry(bookId, id);
      setEntries((prev) => prev.filter((_, j) => j !== index));
    }, `Could not remove ${source_term || "the term"}`);
    setBusyRow(null);
  };

  return (
    <div className="flex flex-col gap-3">
      <div className="max-h-[50vh] overflow-auto rounded-md border border-line">
        {entries.length === 0 ? (
          <p className="m-0 p-4 text-sm text-faint">
            No terms yet. Add names and recurring terms for a consistent translation.
          </p>
        ) : (
          <table className="w-full text-sm">
            <thead className="sticky top-0 bg-surface">
              <tr className="border-b border-line text-left text-xs text-faint">
                <th className="px-3 py-2 font-medium">Term</th>
                <th className="px-3 py-2 font-medium">Translation</th>
                <th className="px-3 py-2 font-medium">Keep as is</th>
                <th className="px-3 py-2">
                  <span className="sr-only">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {entries.map((entry, i) => (
                <tr key={entry.id ?? `new-${i}`} className="border-b border-line last:border-0">
                  <td className="px-3 py-1.5">
                    <input
                      value={entry.source_term}
                      onChange={(e) => update(i, { source_term: e.target.value })}
                      aria-label={`Term ${i + 1}`}
                      className={cn(inputClass, "h-9")}
                    />
                  </td>
                  <td className="px-3 py-1.5">
                    <input
                      value={entry.do_not_translate ? entry.source_term : entry.target_term}
                      onChange={(e) => update(i, { target_term: e.target.value })}
                      aria-label={`Translation of term ${i + 1}`}
                      disabled={entry.do_not_translate}
                      className={cn(inputClass, "h-9")}
                    />
                  </td>
                  <td className="px-3 py-1.5">
                    <Checkbox
                      checked={entry.do_not_translate}
                      onChange={(v) => update(i, { do_not_translate: v })}
                      label={`Keep term ${i + 1} unchanged`}
                    />
                  </td>
                  <td className="whitespace-nowrap px-2 py-1.5 text-right">
                    {busyRow === i ? (
                      <Loader2 className="mx-2 inline h-4 w-4 animate-spin text-faint" aria-label="Saving" />
                    ) : (
                      entry.dirty && (
                        <button
                          type="button"
                          onClick={() => saveRow(i)}
                          aria-label={`Save term ${i + 1}`}
                          title="Save this term"
                          className="rounded-full p-2 text-accent hover:bg-accent-soft"
                        >
                          <Save className="h-4 w-4" />
                        </button>
                      )
                    )}
                    <button
                      type="button"
                      onClick={() => removeRow(i)}
                      disabled={busyRow === i}
                      aria-label={`Remove term ${i + 1}`}
                      className="rounded-full p-2 text-faint hover:bg-danger-soft hover:text-danger disabled:opacity-40"
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {error && <p className="m-0 text-sm text-danger">{error}</p>}

      <div className="flex flex-wrap items-center justify-between gap-2">
        <Button
          size="sm"
          onClick={() => {
            setEntries((prev) => [...prev, { source_term: "", target_term: "", do_not_translate: false, dirty: true }]);
            setSaved(false);
          }}
        >
          <Plus className="h-4 w-4" aria-hidden="true" /> Add term
        </Button>
        {running ? (
          <span className="text-xs text-muted">Translating: save each term on its own</span>
        ) : (
          <Button size="sm" variant="primary" onClick={handleSave} disabled={saving}>
            {saving ? (
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
            ) : saved ? (
              <Check className="h-4 w-4" aria-hidden="true" />
            ) : null}
            {saved ? "Saved" : `Save ${entries.length} terms`}
          </Button>
        )}
      </div>
    </div>
  );
}
