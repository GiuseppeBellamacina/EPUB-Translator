import { api } from "./api";

/** What an edit of a glossary term or compendium entry set in motion (services/fixes.py). */
export interface FixResult {
  /** translated passages naming it, bookmarked for a targeted fix */
  bookmarked?: number;
  /** their fix runs now (or at the end of the running translation) */
  fixing?: boolean;
  /** many passages, or a notes change: the user decides */
  confirm?: boolean;
  books?: number[];
}

/** Ask when needed, start the fixes, and say what happens. `saved` is the response of a save:
 * only the edit of an entry already used in translated passages carries a FixResult. */
export async function followFixes(saved: object, name: string): Promise<string | null> {
  const result = saved as FixResult;
  const n = result.bookmarked ?? 0;
  if (!n) return null;
  const passages = `${n} translated ${n === 1 ? "passage names" : "passages name"} ${name}`;
  if (result.fixing) return `${passages}: fixing them now, only them.`;
  if (
    result.confirm &&
    window.confirm(`${passages}. Fix them now? Exact replacements need no model; the others take one call each.`)
  ) {
    const started = await Promise.all((result.books ?? []).map((id) => api.startFixes(id)));
    if (started.some((s) => s.started)) return `${passages}: fixing them now, only them.`;
  }
  return `${passages}: bookmarked. They are fixed by the next run (or "Review doubts" on a finished book).`;
}
