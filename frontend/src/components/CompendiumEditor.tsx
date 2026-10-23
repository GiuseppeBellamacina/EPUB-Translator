import { useState } from "react";
import { Check, Loader2, Plus, Search, Trash2 } from "lucide-react";
import { api, COMPENDIUM_KINDS, GENDERS, type CompendiumItem } from "../lib/api";
import { inputClass } from "../lib/styles";
import { cn } from "../lib/utils";
import { Select } from "./controls";
import { Button } from "./ui";

const GENDER_LABEL: Record<CompendiumItem["gender"], string> = {
  male: "Male",
  female: "Female",
  unknown: "Unknown",
  "n/a": "Not a person",
};

/** View and edit the book's compendium; an edited entry is never changed by the translation. */
export function CompendiumEditor({
  bookId,
  initial,
  disabled,
  onSaved,
}: {
  bookId: number;
  initial: CompendiumItem[];
  disabled?: boolean;
  onSaved?: () => void;
}) {
  const [entries, setEntries] = useState<CompendiumItem[]>(initial);
  const [filter, setFilter] = useState("");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const update = (index: number, patch: Partial<CompendiumItem>) => {
    setEntries((prev) => prev.map((e, i) => (i === index ? { ...e, ...patch, user_edited: true } : e)));
    setSaved(false);
  };

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      const clean = entries
        .map((e) => ({ ...e, name: e.name.trim(), notes: e.notes.trim() }))
        .filter((e) => e.name);
      await api.updateCompendium(bookId, clean);
      setEntries(clean);
      setSaved(true);
      onSaved?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save the compendium");
    } finally {
      setSaving(false);
    }
  };

  const query = filter.trim().toLowerCase();
  const shown = entries
    .map((entry, index) => ({ entry, index }))
    .filter(({ entry }) => !query || [entry.name, ...entry.aliases].some((n) => n.toLowerCase().includes(query)));

  return (
    <div className="flex flex-col gap-3">
      {entries.length > 8 && (
        <label className="relative">
          <span className="sr-only">Filter by name</span>
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-faint" aria-hidden="true" />
          <input
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder="Filter by name or alias"
            className={cn(inputClass, "h-10 pl-9 font-normal")}
          />
        </label>
      )}

      <ul className="m-0 flex max-h-[55vh] list-none flex-col gap-2 overflow-auto p-0">
        {entries.length === 0 && (
          <li className="rounded-md border border-line p-4 text-sm text-faint">
            No entries yet. Characters, places and other elements are added while translating; you
            can add them here too (for example a character's gender).
          </li>
        )}
        {shown.map(({ entry, index }) => (
          <li key={index} className="flex flex-col gap-2 rounded-md border border-line p-3">
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-[1fr_9rem_9rem_auto] sm:items-end">
              <label className="flex flex-col gap-1.5 text-sm font-medium">
                Name
                <input
                  value={entry.name}
                  onChange={(e) => update(index, { name: e.target.value })}
                  disabled={disabled}
                  className={cn(inputClass, "h-11 font-normal")}
                />
              </label>
              <Select
                label="Kind"
                value={entry.kind}
                options={COMPENDIUM_KINDS}
                onChange={(kind) => update(index, { kind })}
                render={(k) => <span className="capitalize">{k}</span>}
                disabled={disabled}
              />
              <Select
                label="Gender"
                value={entry.gender}
                options={GENDERS}
                onChange={(gender) => update(index, { gender })}
                render={(g) => GENDER_LABEL[g]}
                disabled={disabled}
              />
              <button
                type="button"
                onClick={() => {
                  setEntries((prev) => prev.filter((_, j) => j !== index));
                  setSaved(false);
                }}
                disabled={disabled}
                aria-label={`Remove ${entry.name || "entry"}`}
                className="h-11 rounded-full px-3 text-faint hover:bg-danger-soft hover:text-danger disabled:opacity-40"
              >
                <Trash2 className="h-4 w-4" aria-hidden="true" />
              </button>
            </div>
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-[1fr_2fr]">
              <label className="flex flex-col gap-1 text-xs text-muted">
                Also called (comma separated)
                <input
                  value={entry.aliases.join(", ")}
                  onChange={(e) =>
                    update(index, { aliases: e.target.value.split(",").map((a) => a.trimStart()) })
                  }
                  onBlur={() => {
                    const aliases = entry.aliases.map((a) => a.trim()).filter(Boolean);
                    if (aliases.join() !== entry.aliases.join()) update(index, { aliases });
                  }}
                  disabled={disabled}
                  className={cn(inputClass, "h-9 font-normal text-ink")}
                />
              </label>
              <label className="flex flex-col gap-1 text-xs text-muted">
                Notes for the translation
                <input
                  value={entry.notes}
                  onChange={(e) => update(index, { notes: e.target.value })}
                  placeholder="Who they are, how they speak, a fixed translation…"
                  disabled={disabled}
                  className={cn(inputClass, "h-9 font-normal text-ink")}
                />
              </label>
            </div>
            {entry.user_edited && <span className="text-[11px] text-faint">Edited by you: kept as is</span>}
          </li>
        ))}
      </ul>

      {error && <p className="m-0 text-sm text-danger">{error}</p>}

      <div className="flex flex-wrap items-center justify-between gap-2">
        <Button
          size="sm"
          disabled={disabled}
          onClick={() => {
            setFilter("");
            setEntries((prev) => [
              ...prev,
              { name: "", kind: "character", gender: "unknown", aliases: [], notes: "", user_edited: true },
            ]);
            setSaved(false);
          }}
        >
          <Plus className="h-4 w-4" aria-hidden="true" /> Add entry
        </Button>
        <Button size="sm" variant="primary" onClick={save} disabled={disabled || saving}>
          {saving ? (
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
          ) : saved ? (
            <Check className="h-4 w-4" aria-hidden="true" />
          ) : null}
          {saved ? "Saved" : `Save ${entries.length} ${entries.length === 1 ? "entry" : "entries"}`}
        </Button>
      </div>
    </div>
  );
}
