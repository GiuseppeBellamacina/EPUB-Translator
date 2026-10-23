import { useState } from "react";
import { Check, ChevronDown, Loader2, Plus, Save, Search, Trash2 } from "lucide-react";
import { api, COMPENDIUM_KINDS, GENDERS, type CompendiumItem } from "../lib/api";
import { followFixes } from "../lib/fixes";
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

const GENDER_PILL: Record<CompendiumItem["gender"], string> = {
  male: "bg-accent-soft text-accent",
  female: "bg-violet-soft text-violet",
  unknown: "bg-warn-soft text-warn",
  "n/a": "bg-tint text-muted",
};

const KIND_TAB: Record<CompendiumItem["kind"], string> = {
  character: "Characters",
  place: "Places",
  organization: "Organizations",
  item: "Items",
  other: "Other",
};

type Kind = CompendiumItem["kind"];
type Row = CompendiumItem & { dirty?: boolean };

// the server ignores `dirty`
const clean = (e: Row): Row => ({ ...e, name: e.name.trim(), notes: e.notes.trim() });

/** The book's compendium by kind, one compact row per entry that opens to edit it; an edited
 * entry is never changed by the translation. Single entries are saved on their own, also while
 * translating; the whole list only when idle. */
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
  const [tab, setTab] = useState<Kind>(() => (initial.some((e) => e.kind === "character") || !initial.length ? "character" : initial[0].kind));
  const [open, setOpen] = useState<Set<number>>(new Set());
  const [filter, setFilter] = useState("");
  const [saving, setSaving] = useState(false);
  const [busyRow, setBusyRow] = useState<number | null>(null);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const toggle = (index: number) =>
    setOpen((prev) => {
      const next = new Set(prev);
      if (!next.delete(index)) next.add(index);
      return next;
    });

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
      setOpen(new Set());
      setSaved(true);
    }, "Could not save the compendium");
    setSaving(false);
  };

  const saveRow = async (index: number) => {
    const entry = clean(entries[index]);
    if (!entry.name) return setError("An entry needs a name");
    setBusyRow(index);
    await attempt(async () => {
      const { bookmarked, fixing, confirm, books, ...stored } = await api.saveCompendiumEntry(bookId, entry);
      setEntries((prev) => prev.map((e, i) => (i === index ? stored : e)));
      toggle(index);
      setNotice(await followFixes({ bookmarked, fixing, confirm, books }, stored.name));
    }, `Could not save ${entry.name}`);
    setBusyRow(null);
  };

  const removeRow = async (index: number) => {
    const { id, name } = entries[index];
    setBusyRow(index);
    await attempt(async () => {
      if (id) await api.deleteCompendiumEntry(bookId, id);
      setEntries((prev) => prev.filter((_, j) => j !== index));
      setOpen(new Set()); // indexes shift
    }, `Could not remove ${name || "the entry"}`);
    setBusyRow(null);
  };

  const query = filter.trim().toLowerCase();
  const matches = (e: Row) => !query || [e.name, ...e.aliases].some((n) => n.toLowerCase().includes(query));
  const count = (kind: Kind) => entries.filter((e) => e.kind === kind && matches(e)).length;
  const shown = entries.map((entry, index) => ({ entry, index })).filter(({ entry }) => entry.kind === tab && matches(entry));

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <div role="tablist" aria-label="Kind" className="flex flex-wrap gap-1.5">
          {COMPENDIUM_KINDS.map((kind) => (
            <button
              key={kind}
              type="button"
              role="tab"
              aria-selected={tab === kind}
              onClick={() => setTab(kind)}
              className={cn(
                "rounded-full border px-3 py-1 text-sm",
                tab === kind ? "border-ink bg-ink text-paper" : "border-line text-muted hover:text-ink",
              )}
            >
              {KIND_TAB[kind]} <span className={tab === kind ? "opacity-70" : "text-faint"}>{count(kind)}</span>
            </button>
          ))}
        </div>
        {entries.length > 8 && (
          <label className="relative ml-auto min-w-48 flex-1 sm:max-w-64">
            <span className="sr-only">Filter by name</span>
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-faint" aria-hidden="true" />
            <input
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              placeholder="Filter by name or alias"
              className={cn(inputClass, "h-9 pl-9 font-normal")}
            />
          </label>
        )}
      </div>

      <ul className="m-0 flex max-h-[55vh] list-none flex-col overflow-auto rounded-md border border-line p-0">
        {shown.length === 0 && (
          <li className="p-4 text-sm text-faint">
            {entries.length === 0
              ? "No entries yet. Characters, places and other elements are added while translating; you can add them here too (for example a character's gender)."
              : `No ${KIND_TAB[tab].toLowerCase()}${query ? " match the filter" : " yet"}.`}
          </li>
        )}
        {shown.map(({ entry, index }) => {
          const isOpen = open.has(index) || !entry.name;
          return (
            <li key={entry.id ?? `new-${index}`} className="border-b border-line last:border-0">
              <div className="flex items-start gap-3 px-3 py-2.5">
                <button
                  type="button"
                  onClick={() => toggle(index)}
                  aria-expanded={isOpen}
                  className="flex min-w-0 flex-1 flex-col items-start gap-0.5 text-left"
                >
                  <span className="flex flex-wrap items-center gap-2">
                    <span className="font-medium text-ink">{entry.name || "New entry"}</span>
                    {entry.kind === "character" && (
                      <span className={cn("rounded-full px-2 py-0.5 text-[11px] font-semibold", GENDER_PILL[entry.gender])}>
                        {GENDER_LABEL[entry.gender]}
                      </span>
                    )}
                    {entry.evidence && (
                      <span
                        className="rounded-full bg-warn-soft px-2 py-0.5 text-[11px] font-medium text-warn"
                        title={`The text says: “${entry.evidence}”`}
                      >
                        Corrected
                      </span>
                    )}
                    {entry.dirty ? (
                      <span className="text-[11px] text-warn">Not saved</span>
                    ) : (
                      entry.user_edited && <span className="text-[11px] text-faint">Yours</span>
                    )}
                  </span>
                  {entry.aliases.length > 0 && (
                    <span className="text-xs text-muted">also {entry.aliases.join(", ")}</span>
                  )}
                  {entry.notes && !isOpen && <span className="line-clamp-1 text-xs text-faint">{entry.notes}</span>}
                </button>
                <div className="flex shrink-0 items-center">
                  {busyRow === index ? (
                    <Loader2 className="mx-2.5 h-4 w-4 animate-spin text-faint" aria-label="Saving" />
                  ) : (
                    entry.dirty && (
                      <button
                        type="button"
                        onClick={() => saveRow(index)}
                        aria-label={`Save ${entry.name || "entry"}`}
                        title="Save this entry"
                        className="rounded-full p-2.5 text-accent hover:bg-accent-soft"
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
                    className="rounded-full p-2.5 text-faint hover:bg-danger-soft hover:text-danger disabled:opacity-40"
                  >
                    <Trash2 className="h-4 w-4" aria-hidden="true" />
                  </button>
                  <button
                    type="button"
                    onClick={() => toggle(index)}
                    aria-label={`${isOpen ? "Close" : "Edit"} ${entry.name || "entry"}`}
                    className="rounded-full p-2.5 text-faint hover:bg-tint hover:text-ink"
                  >
                    <ChevronDown className={cn("h-4 w-4 transition-transform", isOpen && "rotate-180")} aria-hidden="true" />
                  </button>
                </div>
              </div>

              {isOpen && (
                <div className="flex flex-col gap-2 bg-tint/50 px-3 pb-3 pt-1">
                  <div className="grid grid-cols-1 gap-2 sm:grid-cols-[1fr_9rem_9rem] sm:items-end">
                    <label className="flex flex-col gap-1.5 text-sm font-medium text-ink">
                      Name
                      <input
                        value={entry.name}
                        onChange={(e) => update(index, { name: e.target.value })}
                        className={cn(inputClass, "h-10 font-normal text-ink")}
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
                  </div>
                  <label className="flex flex-col gap-1 text-xs text-muted">
                    Also called (comma separated)
                    <input
                      value={entry.aliases.join(", ")}
                      onChange={(e) => update(index, { aliases: e.target.value.split(",").map((a) => a.trimStart()) })}
                      onBlur={() => {
                        const aliases = entry.aliases.map((a) => a.trim()).filter(Boolean);
                        if (aliases.join() !== entry.aliases.join()) update(index, { aliases });
                      }}
                      className={cn(inputClass, "h-9 font-normal text-ink")}
                    />
                  </label>
                  <label className="flex flex-col gap-1 text-xs text-muted">
                    Notes for the translation
                    <textarea
                      rows={2}
                      value={entry.notes}
                      onChange={(e) => update(index, { notes: e.target.value })}
                      placeholder="Who they are, how they speak, a fixed translation…"
                      className={cn(inputClass, "resize-none py-2 font-normal text-ink")}
                    />
                  </label>
                  {entry.evidence && (
                    <p className="m-0 text-xs text-warn">Gender corrected by the text: “{entry.evidence}”</p>
                  )}
                </div>
              )}
            </li>
          );
        })}
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
              { name: "", kind: tab, gender: tab === "character" ? "unknown" : "n/a", aliases: [], notes: "", user_edited: true, dirty: true },
            ]);
            setSaved(false);
          }}
        >
          <Plus className="h-4 w-4" aria-hidden="true" /> Add {KIND_TAB[tab].toLowerCase().replace(/s$/, "")}
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
