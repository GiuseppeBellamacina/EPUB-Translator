import { useState } from "react";
import { Plus, Trash2, Save, Check, Loader2, BookMarked } from "lucide-react";
import { api, type GlossaryEntry } from "../lib/api";
import { cn } from "../lib/utils";

interface EditableEntry {
  source_term: string;
  target_term: string;
  do_not_translate: boolean;
}

interface GlossaryEditorProps {
  bookId: number;
  initial: GlossaryEntry[];
  disabled?: boolean;
}

export function GlossaryEditor({
  bookId,
  initial,
  disabled,
}: GlossaryEditorProps) {
  const [entries, setEntries] = useState<EditableEntry[]>(() =>
    initial.map((g) => ({
      source_term: g.source_term,
      target_term: g.target_term,
      do_not_translate: g.do_not_translate,
    })),
  );
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  const markDirty = () => setSaved(false);

  const updateEntry = (index: number, patch: Partial<EditableEntry>) => {
    setEntries((prev) =>
      prev.map((e, i) => (i === index ? { ...e, ...patch } : e)),
    );
    markDirty();
  };

  const addEntry = () => {
    setEntries((prev) => [
      ...prev,
      { source_term: "", target_term: "", do_not_translate: false },
    ]);
    markDirty();
  };

  const removeEntry = (index: number) => {
    setEntries((prev) => prev.filter((_, i) => i !== index));
    markDirty();
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      const clean = entries
        .map((e) => ({
          source_term: e.source_term.trim(),
          target_term: e.target_term.trim(),
          do_not_translate: e.do_not_translate,
        }))
        .filter((e) => e.source_term.length > 0);
      await api.updateGlossary(bookId, clean);
      setEntries(clean);
      setSaved(true);
    } catch (err) {
      alert(err instanceof Error ? err.message : "Failed to save glossary");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-2">
        <label className="flex items-center gap-1.5 text-sm font-medium text-gray-700 dark:text-gray-300">
          <BookMarked className="w-4 h-4 text-gray-400" />
          Glossary
          <span className="text-xs text-gray-400 font-normal">
            ({entries.length})
          </span>
        </label>
        <button
          type="button"
          onClick={addEntry}
          disabled={disabled}
          className="flex items-center gap-1 text-xs font-medium text-gray-700 dark:text-gray-300 hover:text-gray-900 dark:hover:text-gray-100 disabled:opacity-40"
        >
          <Plus className="w-3.5 h-3.5" /> Add
        </button>
      </div>

      <div className="space-y-2 max-h-64 overflow-auto pr-1">
        {entries.length === 0 && (
          <p className="text-xs text-gray-400 italic py-2">
            No terms yet. Add key terms for a consistent translation.
          </p>
        )}
        {entries.map((entry, i) => (
          <div
            key={i}
            className="group rounded-md border border-gray-200 dark:border-gray-800 bg-gray-50 dark:bg-gray-900/40 p-2 space-y-1.5"
          >
            <div className="flex items-center gap-1.5">
              <input
                value={entry.source_term}
                onChange={(e) =>
                  updateEntry(i, { source_term: e.target.value })
                }
                placeholder="Source term"
                disabled={disabled}
                className="flex-1 min-w-0 rounded-md border border-gray-200 dark:border-gray-700 bg-white dark:bg-[#0a0a0a] px-2 py-1.5 text-xs text-gray-900 dark:text-gray-100 placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-gray-900 dark:focus:ring-gray-100"
              />
              <span className="text-gray-300 dark:text-gray-600 text-xs">
                →
              </span>
              <input
                value={entry.target_term}
                onChange={(e) =>
                  updateEntry(i, { target_term: e.target.value })
                }
                placeholder={
                  entry.do_not_translate ? "(unchanged)" : "Translation"
                }
                disabled={disabled || entry.do_not_translate}
                className="flex-1 min-w-0 rounded-md border border-gray-200 dark:border-gray-700 bg-white dark:bg-[#0a0a0a] px-2 py-1.5 text-xs text-gray-900 dark:text-gray-100 placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-gray-900 dark:focus:ring-gray-100 disabled:opacity-50"
              />
              <button
                type="button"
                onClick={() => removeEntry(i)}
                disabled={disabled}
                className="p-1.5 rounded-md text-gray-300 hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-950 transition-colors disabled:opacity-40"
                title="Remove"
              >
                <Trash2 className="w-3.5 h-3.5" />
              </button>
            </div>
            <label className="flex items-center gap-1.5 text-[11px] text-gray-500 dark:text-gray-400 cursor-pointer select-none">
              <input
                type="checkbox"
                checked={entry.do_not_translate}
                onChange={(e) =>
                  updateEntry(i, { do_not_translate: e.target.checked })
                }
                disabled={disabled}
                className="rounded border-gray-300 text-gray-900 focus:ring-gray-900/40"
              />
              Do not translate (keep unchanged)
            </label>
          </div>
        ))}
      </div>

      <button
        type="button"
        onClick={handleSave}
        disabled={disabled || saving}
        className={cn(
          "mt-2 w-full flex items-center justify-center gap-2 px-3 py-2 rounded-md text-xs font-medium transition-colors",
          saved
            ? "bg-gray-900 dark:bg-white text-white dark:text-gray-900"
            : "bg-gray-100 dark:bg-gray-900 text-gray-700 dark:text-gray-200 hover:bg-gray-200 dark:hover:bg-gray-800",
          "disabled:opacity-50",
        )}
      >
        {saving ? (
          <Loader2 className="w-3.5 h-3.5 animate-spin" />
        ) : saved ? (
          <Check className="w-3.5 h-3.5" />
        ) : (
          <Save className="w-3.5 h-3.5" />
        )}
        {saved ? "Glossary saved" : "Save glossary"}
      </button>
    </div>
  );
}
