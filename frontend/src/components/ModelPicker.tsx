import { useEffect, useMemo, useState } from "react";
import { Brain, Loader2, RefreshCw } from "lucide-react";
import { api, type ModelOption } from "../lib/api";
import { cn } from "../lib/utils";

interface Props {
  providerId: number;
  /** Model to preselect when the current value is not offered (provider's default). */
  preferred?: string | null;
  value: string;
  onChange: (model: string) => void;
  disabled?: boolean;
  className: string;
}

const FILTER_THRESHOLD = 20;

function priceLabel(m: ModelOption) {
  if (m.input_per_million === null || m.output_per_million === null) return "";
  if (m.input_per_million === 0 && m.output_per_million === 0) return " — free";
  return ` — $${m.input_per_million.toFixed(2)} / $${m.output_per_million.toFixed(2)}`;
}

/** Model selector listing what the provider actually serves (live from its API). */
export function ModelPicker({
  providerId,
  preferred,
  value,
  onChange,
  disabled,
  className,
}: Props) {
  const [models, setModels] = useState<ModelOption[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState("");
  const [reload, setReload] = useState(0);

  useEffect(() => {
    let current = true;
    api
      .getProviderModels(providerId, reload > 0)
      .then((list) => {
        if (!current) return;
        setModels(list);
        setError(null);
        if (!list.some((m) => m.id === value)) {
          const fallback = list.find((m) => m.id === preferred) ?? list[0];
          if (fallback) onChange(fallback.id);
        }
      })
      .catch((e) => {
        if (!current) return;
        setModels([]);
        setError(e instanceof Error ? e.message : "Could not list models");
      });
    return () => {
      current = false;
    };
    // value/preferred/onChange only matter when a new list arrives
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [providerId, reload]);

  const visible = useMemo(() => {
    const needle = filter.trim().toLowerCase();
    const list = models ?? [];
    const matches = needle
      ? list.filter((m) => `${m.id} ${m.label}`.toLowerCase().includes(needle))
      : list;
    // keep the selected model visible even when filtered out
    const selected = list.find((m) => m.id === value);
    return selected && !matches.includes(selected) ? [selected, ...matches] : matches;
  }, [models, filter, value]);

  if (models === null) {
    return (
      <div className="flex items-center gap-2 text-sm text-gray-500 dark:text-gray-400 py-2">
        <Loader2 className="w-4 h-4 animate-spin" /> Loading models…
      </div>
    );
  }

  // Listing failed or the provider exposes no list: let the user type the model id
  if (error || models.length === 0) {
    return (
      <div className="space-y-1">
        <input
          type="text"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder="model id"
          className={className}
          disabled={disabled}
        />
        <p className="text-[11px] text-amber-600 dark:text-amber-400">
          {error ?? "This provider did not list any model."} Type the model id.
        </p>
      </div>
    );
  }

  const selected = models.find((m) => m.id === value);

  return (
    <div className="space-y-1.5">
      {models.length > FILTER_THRESHOLD && (
        <input
          type="search"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          placeholder={`Filter ${models.length} models…`}
          aria-label="Filter models"
          className={className}
          disabled={disabled}
        />
      )}
      <div className="flex gap-1.5">
        <select
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className={cn(className, "min-w-0")}
          disabled={disabled}
          aria-label="Model"
        >
          {visible.map((m) => (
            <option key={m.id} value={m.id}>
              {m.label}
              {priceLabel(m)}
            </option>
          ))}
        </select>
        <button
          type="button"
          onClick={() => setReload((n) => n + 1)}
          disabled={disabled}
          title="Reload the model list from the provider"
          aria-label="Reload models"
          className="shrink-0 px-2 rounded-md border border-gray-300 dark:border-gray-700 text-gray-500 hover:text-gray-900 dark:hover:text-gray-100 disabled:opacity-50"
        >
          <RefreshCw className="w-4 h-4" />
        </button>
      </div>
      {selected && (
        <p className="text-[11px] text-gray-400 flex items-center gap-1">
          <span className="font-mono truncate">{selected.id}</span>
          {selected.input_per_million !== null && <span>· $ per 1M tokens in / out</span>}
          {selected.reasoning && (
            <span className="inline-flex items-center gap-0.5" title="Thinking tokens are billed as output">
              · <Brain className="w-3 h-3" /> reasoning
            </span>
          )}
        </p>
      )}
    </div>
  );
}
