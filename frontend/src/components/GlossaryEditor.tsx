import { useState } from "react";
import { Check, Loader2, Plus, Trash2 } from "lucide-react";
import { api, type GlossaryEntry } from "../lib/api";
import { inputClass } from "../lib/styles";
import { cn } from "../lib/utils";
import { Checkbox } from "./controls";
import { Button } from "./ui";

interface EditableEntry {
  source_term: string;
  target_term: string;
  do_not_translate: boolean;
}

interface GlossaryEditorProps {
  bookId: number;
  initial: GlossaryEntry[];
  disabled?: boolean;
  onSaved?: (count: number) => void;
}

export function GlossaryEditor({ bookId, initial, disabled, onSaved }: GlossaryEditorProps) {
  const [entries, setEntries] = useState<EditableEntry[]>(() =>
    initial.map((g) => ({
      source_term: g.source_term,
      target_term: g.target_term,
      do_not_translate: g.do_not_translate,
    })),
  );
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const update = (index: number, patch: Partial<EditableEntry>) => {
    setEntries((prev) => prev.map((e, i) => (i === index ? { ...e, ...patch } : e)));
    setSaved(false);
  };

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    try {
      const clean = entries
        .map((e) => ({
          source_term: e.source_term.trim(),
          target_term: e.do_not_translate ? e.source_term.trim() : e.target_term.trim(),
          do_not_translate: e.do_not_translate,
        }))
        .filter((e) => e.source_term.length > 0);
      await api.updateGlossary(bookId, clean);
      setEntries(clean);
      setSaved(true);
      onSaved?.(clean.length);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save the glossary");
    } finally {
      setSaving(false);
    }
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
                  <span className="sr-only">Remove</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {entries.map((entry, i) => (
                <tr key={i} className="border-b border-line last:border-0">
                  <td className="px-3 py-1.5">
                    <input
                      value={entry.source_term}
                      onChange={(e) => update(i, { source_term: e.target.value })}
                      aria-label={`Term ${i + 1}`}
                      disabled={disabled}
                      className={cn(inputClass, "h-9")}
                    />
                  </td>
                  <td className="px-3 py-1.5">
                    <input
                      value={entry.do_not_translate ? entry.source_term : entry.target_term}
                      onChange={(e) => update(i, { target_term: e.target.value })}
                      aria-label={`Translation of term ${i + 1}`}
                      disabled={disabled || entry.do_not_translate}
                      className={cn(inputClass, "h-9")}
                    />
                  </td>
                  <td className="px-3 py-1.5">
                    <Checkbox
                      checked={entry.do_not_translate}
                      onChange={(v) => update(i, { do_not_translate: v })}
                      label={`Keep term ${i + 1} unchanged`}
                      disabled={disabled}
                    />
                  </td>
                  <td className="px-2 py-1.5 text-right">
                    <button
                      type="button"
                      onClick={() => {
                        setEntries((prev) => prev.filter((_, j) => j !== i));
                        setSaved(false);
                      }}
                      disabled={disabled}
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
          disabled={disabled}
          onClick={() => {
            setEntries((prev) => [...prev, { source_term: "", target_term: "", do_not_translate: false }]);
            setSaved(false);
          }}
        >
          <Plus className="h-4 w-4" aria-hidden="true" /> Add term
        </Button>
        <Button size="sm" variant="primary" onClick={handleSave} disabled={disabled || saving}>
          {saving ? (
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
          ) : saved ? (
            <Check className="h-4 w-4" aria-hidden="true" />
          ) : null}
          {saved ? "Saved" : `Save ${entries.length} terms`}
        </Button>
      </div>
    </div>
  );
}
