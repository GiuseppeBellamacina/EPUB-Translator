import { useCallback, useEffect, useState } from "react";
import { Loader2, RefreshCw } from "lucide-react";
import { api, type CostEstimate as Estimate } from "../lib/api";
import { cn } from "../lib/utils";
import { ProviderLogo } from "./ProviderLogo";

const SOURCE_LABEL: Record<Estimate["prices_source"], string> = {
  live: "just updated",
  cache: "cached",
  "stale-cache": "offline, last known prices",
  bundled: "offline, bundled snapshot",
};

function formatCost(cost: number) {
  if (cost < 0.01) return "< $0.01";
  return `$${cost < 10 ? cost.toFixed(2) : cost.toFixed(0)}`;
}

function formatTokens(n: number) {
  return n >= 1_000_000 ? `${(n / 1_000_000).toFixed(1)}M` : `${Math.round(n / 1000)}k`;
}

/** Estimated translation cost of a book per OpenAI / Claude model, with live prices. */
export function CostEstimate({ bookId }: { bookId: number }) {
  const [estimate, setEstimate] = useState<Estimate | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [withReview, setWithReview] = useState(true);

  const fetchEstimate = useCallback(
    (refresh: boolean) =>
      api
        .getEstimate(bookId, { refreshPrices: refresh })
        .then((e) => {
          setEstimate(e);
          setError(null);
        })
        .catch((e) => setError(e instanceof Error ? e.message : "Estimate failed")),
    [bookId],
  );

  useEffect(() => {
    fetchEstimate(false);
  }, [fetchEstimate]);

  const refreshPrices = () => {
    setRefreshing(true);
    fetchEstimate(true).finally(() => setRefreshing(false));
  };

  if (error) return <p className="m-0 text-sm text-danger">{error}</p>;
  if (!estimate) {
    return (
      <div className="flex items-center gap-2 text-sm text-muted">
        <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> Estimating translation cost…
      </div>
    );
  }

  const { profile } = estimate;
  const updated = new Date(estimate.prices_fetched_at * 1000).toLocaleString();

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="m-0 font-serif text-[22px] font-medium">Estimated cost</h2>
        <div role="radiogroup" aria-label="Review step" className="flex gap-1.5">
          {[true, false].map((value) => (
            <button
              key={String(value)}
              type="button"
              role="radio"
              aria-checked={withReview === value}
              onClick={() => setWithReview(value)}
              className={cn(
                "h-8 rounded-full border px-3.5 text-[13px] transition-colors",
                withReview === value
                  ? "border-ink bg-ink text-on-ink"
                  : "border-line-strong bg-surface text-ink hover:bg-tint",
              )}
            >
              {value ? "With review" : "No review"}
            </button>
          ))}
        </div>
      </div>

      <p className="m-0 text-[13px] text-muted">
        {profile.units} {profile.units === 1 ? "unit" : "units"} · {profile.chunks} chunks · ~
        {formatTokens(profile.source_tokens)} source tokens · to{" "}
        <span className="capitalize">{estimate.target_language}</span>
      </p>

      <div className="overflow-x-auto rounded-md border border-line bg-surface">
        <table className="w-full min-w-120 text-sm">
          <thead>
            <tr className="border-b border-line text-left text-xs text-faint">
              <th className="px-4 py-2.5 font-medium">Model</th>
              <th className="px-4 py-2.5 text-right font-medium">$ / 1M in · out</th>
              <th className="px-4 py-2.5 text-right font-medium">Cost</th>
            </tr>
          </thead>
          <tbody>
            {estimate.models.map((m) => {
              const usage = withReview ? m.with_review : m.without_review;
              return (
                <tr key={`${m.provider}/${m.model}`} className="border-b border-line last:border-0">
                  <td className="px-4 py-2.5">
                    <span className="flex items-center gap-2.5">
                      <ProviderLogo providerType={m.provider} modelId={m.model} className="h-4 w-4" />
                      <span className="font-mono text-[13px] text-ink">{m.model}</span>
                      {m.reasoning && (
                        <span
                          title="Reasoning model: thinking tokens are billed as output (estimated)"
                          className="rounded-full bg-violet-soft px-2 py-0.5 text-[11px] text-violet"
                        >
                          reasoning
                        </span>
                      )}
                    </span>
                  </td>
                  <td className="px-4 py-2.5 text-right tabular-nums text-muted">
                    {m.input_per_million.toFixed(2)} · {m.output_per_million.toFixed(2)}
                  </td>
                  <td
                    className="px-4 py-2.5 text-right font-serif text-base tabular-nums text-ink"
                    title={`~${formatTokens(usage.input_tokens)} input · ~${formatTokens(usage.output_tokens)} output tokens`}
                  >
                    {formatCost(usage.cost)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="flex items-start justify-between gap-3 text-xs text-faint">
        <p className="m-0">
          Prices from LiteLLM&apos;s public list, {SOURCE_LABEL[estimate.prices_source]} ({updated}).
          Estimates include prompts, glossary, retries and, for reasoning models, thinking tokens;
          real costs may differ by ±30%.
        </p>
        <button
          type="button"
          onClick={refreshPrices}
          disabled={refreshing}
          className="inline-flex shrink-0 items-center gap-1 rounded-full px-2 py-1 hover:bg-tint hover:text-ink disabled:opacity-50"
          title="Download the latest prices"
        >
          <RefreshCw className={cn("h-3 w-3", refreshing && "animate-spin")} aria-hidden="true" /> Refresh
        </button>
      </div>
    </div>
  );
}

/** A cost from useRunCost: "…" while loading, "n/a" when a price is unknown. */
export function CostValue({ cost }: { cost: number | null | undefined }) {
  if (cost === undefined) return <span className="text-faint">…</span>;
  if (cost === null) return <span className="text-faint">n/a</span>;
  return <span>{formatCost(cost)}</span>;
}
