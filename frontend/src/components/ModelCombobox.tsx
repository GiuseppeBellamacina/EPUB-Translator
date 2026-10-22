import { useEffect, useMemo, useState } from "react";
import {
  Combobox,
  ComboboxButton,
  ComboboxInput,
  ComboboxOption,
  ComboboxOptions,
} from "@headlessui/react";
import { Check, ChevronDown, Loader2, RefreshCw } from "lucide-react";
import type { ModelOption } from "../lib/api";
import { cn } from "../lib/utils";
import { ProviderLogo } from "./ProviderLogo";

interface Props {
  /** Loads the models; called again when `loadKey` changes or on reload. */
  load: (refresh: boolean) => Promise<ModelOption[]>;
  loadKey: string;
  value: string;
  onChange: (modelId: string) => void;
  /** Picked when the current value is not offered (e.g. the provider's default). */
  preferred?: string | null;
  providerType?: string | null;
  baseUrl?: string | null;
  label: string;
  /** Short context under the selected model (e.g. provider name). */
  hint?: string;
  disabled?: boolean;
  /** Pick a model when the value is empty or not offered (default true). */
  autoSelect?: boolean;
  /** Shown when the value is empty and autoSelect is off (e.g. "Same as translation model"). */
  emptyLabel?: string;
  onLoaded?: (models: ModelOption[]) => void;
  onError?: (message: string) => void;
  /** Show the listing error under the field (off when the parent shows it). */
  showError?: boolean;
}

const FREE_FILTER_MIN = 30;

function price(m: ModelOption) {
  if (m.input_per_million === null || m.output_per_million === null) return null;
  if (m.input_per_million === 0 && m.output_per_million === 0) return "free";
  return `$${m.input_per_million.toFixed(2)} / $${m.output_per_million.toFixed(2)}`;
}

/** Searchable model picker fed by a provider's live model list; any typed id is allowed. */
export function ModelCombobox({
  load,
  loadKey,
  value,
  onChange,
  preferred,
  providerType,
  baseUrl,
  label,
  hint,
  disabled,
  autoSelect = true,
  emptyLabel,
  onLoaded,
  onError,
  showError = true,
}: Props) {
  const [models, setModels] = useState<ModelOption[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [freeOnly, setFreeOnly] = useState(false);
  const [reload, setReload] = useState(0);

  useEffect(() => {
    let current = true;
    load(reload > 0)
      .then((list) => {
        if (!current) return;
        setModels(list);
        setError(null);
        onLoaded?.(list);
        if (autoSelect && list.length && !list.some((m) => m.id === value)) {
          onChange((list.find((m) => m.id === preferred) ?? list[0]).id);
        }
      })
      .catch((e) => {
        if (!current) return;
        const message = e instanceof Error ? e.message : "Could not list models";
        setModels([]);
        setError(message);
        onError?.(message);
      });
    return () => {
      current = false;
    };
    // the list only depends on what is loaded; value/preferred matter when it arrives
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loadKey, reload]);

  const hasFree = (models ?? []).some((m) => price(m) === "free");
  const showFreeFilter = hasFree && (models?.length ?? 0) >= FREE_FILTER_MIN;

  const options = useMemo(() => {
    const needle = query.trim().toLowerCase();
    let list = models ?? [];
    if (freeOnly) list = list.filter((m) => price(m) === "free");
    if (needle) list = list.filter((m) => `${m.id} ${m.label}`.toLowerCase().includes(needle));
    return list.slice(0, 200);
  }, [models, query, freeOnly]);

  const typed = query.trim();
  const offerTyped = typed && !(models ?? []).some((m) => m.id === typed);
  const selected = (models ?? []).find((m) => m.id === value);

  return (
    <div className="flex flex-col gap-1">
      <Combobox
        value={value}
        onChange={(id: string | null) => id && onChange(id)}
        onClose={() => setQuery("")}
        disabled={disabled}
        immediate
      >
        <div className="relative">
          <span className="pointer-events-none absolute inset-y-0 left-3 flex items-center">
            <ProviderLogo providerType={providerType} baseUrl={baseUrl} modelId={value} />
          </span>
          <ComboboxInput
            aria-label={label}
            className={cn(
              "h-13 w-full rounded-md border border-line-strong bg-surface pl-10 pr-20 text-sm text-ink",
              "placeholder:text-faint focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/40",
              "disabled:opacity-60",
            )}
            displayValue={(id: string) => (models === null ? "" : (selected?.label ?? id))}
            placeholder={
              models === null ? "Loading models…" : (emptyLabel ?? "Search or type a model id")
            }
            onChange={(e) => setQuery(e.target.value)}
            onFocus={(e) => e.target.select()}
          />
          <span className="absolute inset-y-0 right-2 flex items-center gap-1">
            {models === null ? (
              <Loader2 className="h-4 w-4 animate-spin text-faint" aria-label="Loading" />
            ) : (
              <button
                type="button"
                onClick={() => setReload((n) => n + 1)}
                disabled={disabled}
                aria-label="Reload models from the provider"
                title="Reload models"
                className="rounded-full p-1.5 text-faint hover:bg-tint hover:text-ink"
              >
                <RefreshCw className="h-3.5 w-3.5" />
              </button>
            )}
            <ComboboxButton aria-label="Show models" className="rounded-full p-1.5 text-faint hover:bg-tint">
              <ChevronDown className="h-4 w-4" />
            </ComboboxButton>
          </span>
        </div>

        <ComboboxOptions
          anchor="bottom start"
          className={cn(
            "z-50 mt-1 max-h-80 w-(--input-width) overflow-auto rounded-md border border-line bg-surface p-1.5",
            "shadow-[0_16px_40px_rgba(27,36,51,0.14)] empty:invisible",
          )}
        >
          {showFreeFilter && (
            <div className="flex items-center justify-between px-2 pb-1.5 pt-0.5 text-xs text-faint">
              <span>{models?.length} models</span>
              <button
                type="button"
                aria-pressed={freeOnly}
                onClick={() => setFreeOnly((v) => !v)}
                className={cn(
                  "rounded-full border px-2.5 py-1",
                  freeOnly ? "border-accent bg-accent-soft text-accent" : "border-line-strong text-muted",
                )}
              >
                Free only
              </button>
            </div>
          )}
          {options.map((m) => {
            const p = price(m);
            return (
              <ComboboxOption
                key={m.id}
                value={m.id}
                className="group flex cursor-pointer items-center gap-2.5 rounded-md px-2.5 py-2 data-focus:bg-tint"
              >
                <ProviderLogo providerType={providerType} baseUrl={baseUrl} modelId={m.id} label={false} className="h-4 w-4" />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-medium text-ink">{m.label}</span>
                  {m.label !== m.id && (
                    <span className="block truncate font-mono text-xs text-faint">{m.id}</span>
                  )}
                </span>
                {m.reasoning && (
                  <span className="rounded-full bg-violet-soft px-2 py-0.5 text-[11px] text-violet">
                    reasoning
                  </span>
                )}
                {p && (
                  <span className={cn("shrink-0 text-xs", p === "free" ? "font-semibold text-accent" : "text-muted")}>
                    {p}
                  </span>
                )}
                <Check className="invisible h-4 w-4 text-accent group-data-selected:visible" aria-hidden="true" />
              </ComboboxOption>
            );
          })}
          {offerTyped && (
            <ComboboxOption
              value={typed}
              className="flex cursor-pointer items-center gap-2 rounded-md px-2.5 py-2 text-sm data-focus:bg-tint"
            >
              Use <span className="font-mono text-[13px]">{typed}</span>
            </ComboboxOption>
          )}
          {models !== null && !options.length && !offerTyped && (
            <div className="px-2.5 py-2 text-sm text-faint">No model matches.</div>
          )}
        </ComboboxOptions>
      </Combobox>

      {error && showError ? (
        <p className="m-0 text-xs text-warn">{error} — you can still type a model id.</p>
      ) : (
        (hint || selected) && (
          <p className="m-0 truncate text-xs text-faint">
            {[hint, selected && price(selected) && `${price(selected)} per 1M tokens`]
              .filter(Boolean)
              .join(" · ")}
          </p>
        )
      )}
    </div>
  );
}
