import { useState } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { clean, type ChunkStatus, type LiveChunk } from "../lib/jobEvents";
import { Card, Heading } from "./ui";

const STATUS: Record<ChunkStatus, string> = {
  translated: "translated",
  approved: "approved by reviewer",
  retranslating: "review found issues, retranslating",
  accepted: "accepted after the retry",
};

/** One chunk at a time (original | translation), stepping back through recent ones. */
export function LiveView({
  chunks,
  unitName,
  targetLanguage,
}: {
  chunks: LiveChunk[];
  unitName: string;
  targetLanguage: string;
}) {
  // null = follow the newest chunk
  const [pinned, setPinned] = useState<string | null>(null);
  const pinnedIndex = pinned ? chunks.findIndex((c) => c.key === pinned) : -1;
  const index = pinnedIndex >= 0 ? pinnedIndex : chunks.length - 1;
  const chunk = chunks[index];

  const go = (to: number) => {
    const target = chunks[to];
    setPinned(to >= chunks.length - 1 ? null : (target?.key ?? null));
  };

  return (
    <Card aria-labelledby="live-title" className="overflow-hidden">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-5 py-3.5">
        <div className="flex min-w-0 items-baseline gap-2.5">
          <Heading id="live-title" className="text-xl">
            Live
          </Heading>
          {chunk && (
            <span className="truncate text-[13px] text-faint">
              {unitName} {chunk.unit + 1}
              {chunk.totalChunks > 1 && ` · part ${chunk.chunk + 1} of ${chunk.totalChunks}`} ·{" "}
              {STATUS[chunk.status]}
            </span>
          )}
        </div>
        <div className="flex items-center gap-1.5">
          <button
            type="button"
            aria-label="Previous chunk"
            disabled={index <= 0}
            onClick={() => go(index - 1)}
            className="flex h-9 w-9 items-center justify-center rounded-full border border-line bg-surface text-ink hover:bg-tint disabled:opacity-40"
          >
            <ChevronLeft className="h-4 w-4" />
          </button>
          <span className="min-w-16 text-center text-[13px] text-muted" aria-live="off">
            {chunks.length ? `${index + 1} of ${chunks.length}` : "—"}
          </span>
          <button
            type="button"
            aria-label="Next chunk"
            disabled={index >= chunks.length - 1}
            onClick={() => go(index + 1)}
            className="flex h-9 w-9 items-center justify-center rounded-full border border-line bg-surface text-ink hover:bg-tint disabled:opacity-40"
          >
            <ChevronRight className="h-4 w-4" />
          </button>
          {pinned && (
            <button
              type="button"
              onClick={() => setPinned(null)}
              className="ml-1 rounded-full px-2.5 py-1 text-[13px] text-accent hover:bg-accent-soft"
            >
              Latest
            </button>
          )}
        </div>
      </div>
      <div className="grid h-56 grid-cols-1 md:grid-cols-2">
        {chunk ? (
          <>
            <div className="overflow-auto border-b border-line px-5 py-4 md:border-b-0 md:border-r">
              <div className="mb-2 text-[11px] uppercase tracking-[0.14em] text-faint">Original</div>
              <p className="m-0 whitespace-pre-line font-serif text-[17px] leading-relaxed text-muted">
                {clean(chunk.source) || "—"}
              </p>
            </div>
            <div className="overflow-auto px-5 py-4">
              <div className="mb-2 text-[11px] uppercase tracking-[0.14em] text-accent capitalize">
                {targetLanguage}
              </div>
              <p className="m-0 whitespace-pre-line font-serif text-[17px] leading-relaxed text-ink">
                {clean(chunk.translation)}
              </p>
            </div>
          </>
        ) : (
          <p className="col-span-full m-0 self-center px-5 text-center text-sm text-faint">
            Each translated passage appears here, original and translation side by side.
          </p>
        )}
      </div>
    </Card>
  );
}
