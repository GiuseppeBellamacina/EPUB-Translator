import type { JobEvent } from "./api";

const PLACEHOLDER = /<\/?\d+\/?>/g;

/** Inline-markup placeholders (<1>…</1>, <2/>) are pipeline internals: hide them. */
export const clean = (text: string) => text.replace(PLACEHOLDER, "");

export type ChunkStatus = "translated" | "approved" | "retranslating" | "accepted";

export interface LiveChunk {
  key: string;
  unit: number; // 0-based chapter/page index
  chunk: number;
  totalChunks: number;
  source: string;
  translation: string;
  status: ChunkStatus;
}

/** Last translated chunks, oldest first, from events given newest first. */
export function liveChunks(eventsNewestFirst: JobEvent[], max = 30): LiveChunk[] {
  const byKey = new Map<string, LiveChunk>();
  for (let i = eventsNewestFirst.length - 1; i >= 0; i--) {
    const e = eventsNewestFirst[i];
    if (e.chapter_index === undefined || e.chunk_index === undefined) continue;
    const key = `${e.chapter_index}:${e.chunk_index}`;
    const translated = typeof e.data?.translated_text === "string" ? e.data.translated_text : null;
    const existing = byKey.get(key);
    if (e.event === "chunk_translated" && translated !== null) {
      byKey.delete(key); // re-insert: a retranslation moves the chunk to the end
      byKey.set(key, {
        key,
        unit: e.chapter_index,
        chunk: e.chunk_index,
        totalChunks: e.total_chunks ?? 1,
        source: typeof e.data?.source_text === "string" ? e.data.source_text : existing?.source ?? "",
        translation: translated,
        status: "translated",
      });
    } else if (existing) {
      if (e.event === "chunk_reviewed") existing.status = "approved";
      if (e.event === "chunk_rejected") existing.status = "retranslating";
      if (e.event === "chunk_accepted") {
        existing.status = "accepted";
        if (translated !== null) existing.translation = translated;
      }
    }
  }
  return [...byKey.values()].slice(-max);
}

export type LogKind = "done" | "glossary" | "review" | "error" | "info";

export interface LogEntry {
  key: string;
  kind: LogKind;
  unit: string | null; // "p. 12", "ch. 3–5"
  text: string;
  ts?: number;
}

const unitText = (abbr: string, from: number, to = from) =>
  from === to ? `${abbr} ${from + 1}` : `${abbr} ${Math.min(from, to) + 1}–${Math.max(from, to) + 1}`;

/**
 * Readable activity entries, newest first. Low-level events (chunk translated,
 * checkpoints) are hidden; consecutive saved/skipped units collapse into one row.
 */
export function logEntries(eventsNewestFirst: JobEvent[], unitAbbr: string): LogEntry[] {
  const out: LogEntry[] = [];
  let run: { kind: "saved" | "skipped"; first: number; last: number; entry: LogEntry } | null = null;

  eventsNewestFirst.forEach((e, i) => {
    const unit = e.chapter_index ?? 0;
    const at = unitText(unitAbbr, unit);
    const base = { key: `${i}-${e.event}-${e.ts ?? ""}`, ts: e.ts };

    if (e.event === "chapter_saved" || e.event === "chapter_skipped") {
      const kind = e.event === "chapter_saved" ? "saved" : "skipped";
      const failed = ((e.data?.failed_chunks as unknown[]) ?? []).length;
      if (kind === "saved" && failed) {
        run = null;
        out.push({ ...base, kind: "error", unit: at, text: `Saved with ${failed} untranslated part(s); resume to retry` });
        return;
      }
      if (run && run.kind === kind && Math.abs(unit - run.last) === 1) {
        run.last = unit;
        run.entry.unit = unitText(unitAbbr, run.last, run.first);
        const n = Math.abs(run.first - run.last) + 1;
        run.entry.text = kind === "saved" ? `${n} saved` : `${n} already translated`;
        return;
      }
      const entry: LogEntry = {
        ...base,
        kind: kind === "saved" ? "done" : "info",
        unit: at,
        text: kind === "saved" ? "Saved" : "Already translated",
      };
      run = { kind, first: unit, last: unit, entry };
      out.push(entry);
      return;
    }
    run = null;

    switch (e.event) {
      case "chunk_reviewed":
        out.push({ ...base, kind: "done", unit: at, text: "Approved by reviewer" });
        break;
      case "chunk_rejected": {
        const issues = (e.data?.issues as string[] | undefined) ?? [];
        out.push({
          ...base,
          kind: "review",
          unit: at,
          text: `Review: ${issues.length || "some"} major issue${issues.length === 1 ? "" : "s"}, retranslating${issues[0] ? ` — ${issues[0]}` : ""}`,
        });
        break;
      }
      case "chunk_accepted":
        out.push({ ...base, kind: "review", unit: at, text: "Accepted after the retry" });
        break;
      case "glossary_update": {
        const terms = ((e.data?.new_terms as { source_term: string }[]) ?? []).map((t) => t.source_term);
        out.push({ ...base, kind: "glossary", unit: at, text: `New terms: ${terms.join(", ")}` });
        break;
      }
      case "compendium_update": {
        const entries = (e.data?.entries as { name: string; gender: string; evidence?: string }[]) ?? [];
        const described = entries.map((c) =>
          c.gender === "male" || c.gender === "female"
            ? `${c.name} (${c.gender}${c.evidence ? ", corrected" : ""})`
            : c.name,
        );
        out.push({ ...base, kind: "glossary", unit: at, text: `Compendium: ${described.join(", ")}` });
        break;
      }
      case "analysis_complete":
        out.push({ ...base, kind: "glossary", unit: null, text: e.message ?? "Analysis complete" });
        break;
      case "error":
        out.push({ ...base, kind: "error", unit: e.chapter_index !== undefined ? at : null, text: e.message ?? "Error" });
        break;
      case "started":
      case "queued":
      case "cancelled":
      case "job_complete":
      case "building_epub":
        out.push({ ...base, kind: "info", unit: null, text: e.message ?? e.event });
        break;
    }
  });
  return out;
}

export function relativeTime(ts: number | undefined, now: number): string {
  if (!ts) return "";
  const s = Math.max(0, Math.round(now / 1000 - ts));
  if (s < 5) return "now";
  if (s < 60) return `${s} s`;
  if (s < 3600) return `${Math.round(s / 60)} min`;
  return `${Math.round(s / 3600)} h`;
}
