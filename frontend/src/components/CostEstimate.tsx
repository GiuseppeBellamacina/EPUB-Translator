import { useCallback, useEffect, useState } from "react";
import { Brain, Loader2, RefreshCw } from "lucide-react";
import { api, type CostEstimate as Estimate } from "../lib/api";
import { cn } from "../lib/utils";

const PROVIDER_LABEL = { openai: "OpenAI", anthropic: "Claude" } as const;

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
        .getEstimate(bookId, refresh)
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

  if (error) {
    return <p className="text-sm text-red-600 dark:text-red-400">{error}</p>;
  }
  if (!estimate) {
    return (
      <div className="flex items-center gap-2 text-sm text-gray-500 dark:text-gray-400">
        <Loader2 className="w-4 h-4 animate-spin" /> Estimating translation cost…
      </div>
    );
  }

  const { profile } = estimate;
  const updated = new Date(estimate.prices_fetched_at * 1000).toLocaleString();

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-3">
        <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100">
          Estimated cost
        </h3>
        <div
          role="radiogroup"
          aria-label="Review step"
          className="flex rounded-md border border-gray-300 dark:border-gray-700 text-xs overflow-hidden"
        >
          {[true, false].map((value) => (
            <button
              key={String(value)}
              role="radio"
              aria-checked={withReview === value}
              onClick={() => setWithReview(value)}
              className={cn(
                "px-2.5 py-1 transition-colors",
                withReview === value
                  ? "bg-gray-900 text-white dark:bg-white dark:text-gray-900"
                  : "text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-900",
              )}
            >
              {value ? "With review" : "No review"}
            </button>
          ))}
        </div>
      </div>

      <p className="text-xs text-gray-500 dark:text-gray-400">
        {profile.units} {profile.units === 1 ? "unit" : "units"} · {profile.chunks} chunks ·{" "}
        ~{formatTokens(profile.source_tokens)} source tokens · to{" "}
        <span className="capitalize">{estimate.target_language}</span>
      </p>

      <div className="surface rounded-lg overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-gray-500 dark:text-gray-400 border-b border-gray-200 dark:border-gray-800">
              <th className="px-3 py-2 font-medium">Model</th>
              <th className="px-3 py-2 font-medium text-right">$ / 1M in · out</th>
              <th className="px-3 py-2 font-medium text-right">Cost</th>
            </tr>
          </thead>
          <tbody>
            {estimate.models.map((m) => {
              const usage = withReview ? m.with_review : m.without_review;
              return (
                <tr
                  key={`${m.provider}/${m.model}`}
                  className="border-b last:border-0 border-gray-100 dark:border-gray-900"
                >
                  <td className="px-3 py-2">
                    <span className="text-xs text-gray-400 mr-1.5">
                      {PROVIDER_LABEL[m.provider]}
                    </span>
                    <span className="font-mono text-gray-900 dark:text-gray-100">{m.model}</span>
                    {m.reasoning && (
                      <span
                        title="Reasoning model: thinking tokens are billed as output (estimated)"
                        className="inline-flex items-center ml-1.5 align-middle text-gray-400"
                      >
                        <Brain className="w-3.5 h-3.5" aria-label="reasoning model" />
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums text-gray-500 dark:text-gray-400">
                    {m.input_per_million.toFixed(2)} · {m.output_per_million.toFixed(2)}
                  </td>
                  <td
                    className="px-3 py-2 text-right tabular-nums font-medium text-gray-900 dark:text-gray-100"
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

      <div className="flex items-start justify-between gap-3 text-[11px] text-gray-400">
        <p>
          Prices from LiteLLM&apos;s public list, {SOURCE_LABEL[estimate.prices_source]} (
          {updated}). Estimates include prompts, glossary, retries and, for reasoning models,
          thinking tokens; real costs may differ by ±30%.
        </p>
        <button
          onClick={refreshPrices}
          disabled={refreshing}
          className="shrink-0 inline-flex items-center gap-1 hover:text-gray-700 dark:hover:text-gray-200 disabled:opacity-50"
          title="Download the latest prices"
        >
          <RefreshCw className={cn("w-3 h-3", refreshing && "animate-spin")} /> Refresh
        </button>
      </div>
    </div>
  );
}
