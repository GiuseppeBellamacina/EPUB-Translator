import type { BookProgress } from "../lib/api";
import { Card } from "./ui";

function duration(seconds: number) {
  const m = Math.round(seconds / 60);
  if (m < 1) return "< 1 min";
  if (m < 60) return `~${m} min`;
  return `~${Math.floor(m / 60)} h ${m % 60} min`;
}

const list = (units: number[], abbr: string) =>
  units.length ? `${abbr} ${units.slice(0, 3).map((u) => u + 1).join(", ")}${units.length > 3 ? "…" : ""}` : "—";

export function ProgressPanel({
  progress,
  unitName,
  unitAbbr,
  spent,
}: {
  progress: BookProgress | null;
  unitName: string; // "pages" | "chapters"
  unitAbbr: string;
  spent: string | null;
}) {
  const total = progress?.total_units ?? 0;
  const done = progress?.completed_units ?? 0;
  const pct = total ? Math.round((done / total) * 100) : 0;

  return (
    <Card aria-label="Progress" className="flex flex-col gap-3.5 p-5">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <div className="flex items-baseline gap-2.5">
          <span className="font-serif text-[40px] font-medium leading-none">{done}</span>
          <span className="text-muted">
            of {total} {unitName}
          </span>
        </div>
        <span className="text-muted">{pct}%</span>
      </div>
      <div
        role="progressbar"
        aria-label={`${unitName} translated`}
        aria-valuenow={pct}
        aria-valuemin={0}
        aria-valuemax={100}
        className="h-1.5 overflow-hidden rounded-full bg-tint"
      >
        <div className="h-full rounded-full bg-accent transition-[width] duration-500" style={{ width: `${pct}%` }} />
      </div>
      <dl className="m-0 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <div>
          <dt className="text-xs text-faint">In progress</dt>
          <dd className="m-0 font-semibold">{list(progress?.in_flight ?? [], unitAbbr)}</dd>
        </div>
        <div>
          <dt className="text-xs text-faint">Failed</dt>
          <dd className={progress?.failed_units.length ? "m-0 font-semibold text-danger" : "m-0 font-semibold"}>
            {progress?.failed_units.length ?? 0}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-faint">Time left</dt>
          <dd className="m-0 font-semibold">
            {progress?.eta_seconds ? duration(progress.eta_seconds) : "—"}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-faint">Spent (est.)</dt>
          <dd className="m-0 font-semibold">{spent ?? "—"}</dd>
        </div>
      </dl>
    </Card>
  );
}
