import { useState } from "react";
import { Check, Loader2, Plus, Save, Search, Trash2 } from "lucide-react";
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

type Row = CompendiumItem & { dirty?: boolean };

// the server ignores `dirty`
const clean = (e: Row): Row => ({ ...e, name: e.name.trim(), notes: e.notes.trim() });

/** View and edit the book's compendium; an edited entry is never changed by the translation.
 * Single entries are saved on their own, also while translating; the whole list only when idle. */
export function CompendiumEditor({
  bookId,
  initial,
  running,
  onSaved,
}: {
  bookId: number;
  initial: CompendiumItem[];
  running?: boolean;
  onSaved?: () => void;
}) {
  const [entries, setEntries] = useState<Row[]>(initial);
  const [filter, setFilter] = useState("");
  const [saving, setSaving] = useState(false);
  const [busyRow, setBusyRow] = useState<number | null>(null);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const update = (index: number, patch: Partial<CompendiumItem>) => {
    setEntries((prev) => prev.map((e, i) => (i === index ? { ...e, ...patch, user_edited: true, dirty: true } : e)));
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

  const save = async () => {
    setSaving(true);
    await attempt(async () => {
      await api.updateCompendium(bookId, entries.map(clean).filter((e) => e.name));
      setEntries(await api.getCompendium(bookId)); // fresh ids for single-entry edits
      setSaved(true);
    }, "Could not save the compendium");
    setSaving(false);
  };

  const saveRow = async (index: number) => {
    const entry = clean(entries[index]);
    if (!entry.name) return setError("An entry needs a name");
    setBusyRow(index);
    await attempt(async () => {
      const { bookmarked, ...stored } = await api.saveCompendiumEntry(bookId, entry);
      setEntries((prev) => prev.map((e, i) => (i === index ? stored : e)));
      setNotice(
        bookmarked
          ? `${bookmarked} translated ${bookmarked === 1 ? "passage names" : "passages name"} ${stored.name}: the doubt review will recheck them.`
          : null,
      );
    }, `Could not save ${entry.name}`);
    setBusyRow(null);
  };

  const removeRow = async (index: number) => {
    const { id, name } = entries[index];
    setBusyRow(index);
    await attempt(async () => {
      if (id) await api.deleteCompendiumEntry(bookId, id);
      setEntries((prev) => prev.filter((_, j) => j !== index));
    }, `Could not remove ${name || "the entry"}`);
    setBusyRow(null);
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
          <li key={entry.id ?? `new-${index}`} className="flex flex-col gap-2 rounded-md border border-line p-3">
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-[1fr_9rem_9rem_auto] sm:items-end">
              <label className="flex flex-col gap-1.5 text-sm font-medium">
                Name
                <input
                  value={entry.name}
                  onChange={(e) => update(index, { name: e.target.value })}
                  className={cn(inputClass, "h-11 font-normal")}
                />
              </label>
              <Select
                label="Kind"
                value={entry.kind}
                options={COMPENDIUM_KINDS}
                onChange={(kind) => update(index, { kind })}
                render={(k) => <span className="capitalize">{k}</span>}
              />
              <Select
                label="Gender"
                value={entry.gender}
                options={GENDERS}
                onChange={(gender) => update(index, { gender })}
                render={(g) => GENDER_LABEL[g]}
              />
              <div className="flex h-11 items-center justify-end sm:w-24">
                {busyRow === index ? (
                  <Loader2 className="mx-3 h-4 w-4 animate-spin text-faint" aria-label="Saving" />
                ) : (
                  entry.dirty && (
                    <button
                      type="button"
                      onClick={() => saveRow(index)}
                      aria-label={`Save ${entry.name || "entry"}`}
                      title="Save this entry"
                      className="rounded-full p-3 text-accent hover:bg-accent-soft"
                    >
                      <Save className="h-4 w-4" aria-hidden="true" />
                    </button>
                  )
                )}
                <button
                  type="button"
                  onClick={() => removeRow(index)}
                  disabled={busyRow === index}
                  aria-label={`Remove ${entry.name || "entry"}`}
                  className="rounded-full p-3 text-faint hover:bg-danger-soft hover:text-danger disabled:opacity-40"
                >
                  <Trash2 className="h-4 w-4" aria-hidden="true" />
                </button>
              </div>
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
                  className={cn(inputClass, "h-9 font-normal text-ink")}
                />
              </label>
              <label className="flex flex-col gap-1 text-xs text-muted">
                Notes for the translation
                <input
                  value={entry.notes}
                  onChange={(e) => update(index, { notes: e.target.value })}
                  placeholder="Who they are, how they speak, a fixed translation…"
                  className={cn(inputClass, "h-9 font-normal text-ink")}
                />
              </label>
            </div>
            <div className="flex flex-wrap items-center gap-2 text-[11px] text-faint">
              {entry.evidence && (
                <span
                  className="rounded-full bg-warn-soft px-2 py-0.5 font-medium text-warn"
                  title={`The text says: “${entry.evidence}”`}
                >
                  Corrected: “{entry.evidence}”
                </span>
              )}
              {entry.dirty ? (
                <span>Not saved yet</span>
              ) : (
                entry.user_edited && <span>Edited by you: kept as is</span>
              )}
            </div>
          </li>
        ))}
      </ul>

      {error && <p className="m-0 text-sm text-danger">{error}</p>}
      {notice && <p className="m-0 text-sm text-muted">{notice}</p>}

      <div className="flex flex-wrap items-center justify-between gap-2">
        <Button
          size="sm"
          onClick={() => {
            setFilter("");
            setEntries((prev) => [
              ...prev,
              { name: "", kind: "character", gender: "unknown", aliases: [], notes: "", user_edited: true, dirty: true },
            ]);
            setSaved(false);
          }}
        >
          <Plus className="h-4 w-4" aria-hidden="true" /> Add entry
        </Button>
        {running ? (
          <span className="text-xs text-muted">Translating: save each entry on its own</span>
        ) : (
          <Button size="sm" variant="primary" onClick={save} disabled={saving}>
            {saving ? (
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
            ) : saved ? (
              <Check className="h-4 w-4" aria-hidden="true" />
            ) : null}
            {saved ? "Saved" : `Save ${entries.length} ${entries.length === 1 ? "entry" : "entries"}`}
          </Button>
        )}
      </div>
    </div>
  );
}
