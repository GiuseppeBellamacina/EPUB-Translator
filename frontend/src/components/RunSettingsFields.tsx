import { useCallback } from "react";
import { Link } from "react-router-dom";
import { api, FEATURES, type Provider } from "../lib/api";
import { LANGUAGES, type RunSettings } from "../lib/runSettings";
import { inputClass, labelClass } from "../lib/styles";
import { cn } from "../lib/utils";
import { Select, Toggle } from "./controls";
import { ModelCombobox } from "./ModelCombobox";
import { ProviderSelect } from "./ProviderSelect";

/** Provider, models, reviewer, languages and style of a translation run. */
export function RunSettingsFields({
  providers,
  value,
  onChange,
  disabled,
  sourceAuto,
}: {
  providers: Provider[];
  value: RunSettings;
  onChange: (patch: Partial<RunSettings>) => void;
  disabled?: boolean;
  /** offer "each book's own" as the source language (queue of several books) */
  sourceAuto?: boolean;
}) {
  const { providerId, model, enableReview, reviewModel, sourceLang, targetLang, style, features } = value;
  const off = FEATURES.filter(({ key }) => !features[key]).length;
  const provider = providers.find((p) => p.id === providerId) ?? null;
  const loadModels = useCallback(
    (refresh: boolean) =>
      providerId === null ? Promise.resolve([]) : api.getProviderModels(providerId, refresh),
    [providerId],
  );
  const languages = (current: string) => (LANGUAGES.includes(current) ? LANGUAGES : [current, ...LANGUAGES]);
  const sources = sourceAuto ? ["", ...LANGUAGES] : languages(sourceLang);

  return (
    <>
      {providers.length === 0 ? (
        <p className="m-0 text-sm text-muted">
          No providers yet. <Link to="/providers">Add one</Link> to start.
        </p>
      ) : (
        <>
          <div className="flex flex-col gap-1.5">
            <span className="text-sm font-medium">Provider</span>
            <ProviderSelect
              providers={providers}
              value={providerId}
              onChange={(pid) => onChange({ providerId: pid, model: "", reviewModel: "" })}
              disabled={disabled}
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <span className="text-sm font-medium">Translation model</span>
            <ModelCombobox
              key={`model-${providerId}`}
              label="Translation model"
              load={loadModels}
              loadKey={`model-${providerId}`}
              value={model}
              onChange={(m) => onChange({ model: m })}
              preferred={provider?.default_model}
              providerType={provider?.provider_type}
              baseUrl={provider?.base_url}
              disabled={disabled}
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium">Reviewer</span>
              <Toggle
                checked={enableReview}
                onChange={(v) => onChange({ enableReview: v })}
                label="Review each chunk"
                disabled={disabled}
              />
            </div>
            {enableReview ? (
              <ModelCombobox
                key={`review-${providerId}`}
                label="Reviewer model"
                load={loadModels}
                loadKey={`review-${providerId}`}
                value={reviewModel}
                onChange={(m) => onChange({ reviewModel: m })}
                autoSelect={false}
                emptyLabel={`Same as translation model${model ? ` (${model})` : ""}`}
                providerType={provider?.provider_type}
                baseUrl={provider?.base_url}
                hint="Flags major issues only; a stronger model than the translator works best"
                disabled={disabled}
              />
            ) : (
              <p className="m-0 text-xs text-faint">Faster and cheaper; no second opinion on each chunk.</p>
            )}
          </div>
        </>
      )}

      <div className="grid grid-cols-2 gap-3">
        <Select
          label="From"
          value={sourceLang}
          options={sources}
          onChange={(v) => onChange({ sourceLang: v })}
          render={(v) => (v ? <span className="capitalize">{v}</span> : "Each book's own")}
          disabled={disabled}
        />
        <Select
          label="To"
          value={targetLang}
          options={languages(targetLang)}
          onChange={(v) => onChange({ targetLang: v })}
          render={(v) => <span className="capitalize">{v}</span>}
          disabled={disabled}
        />
      </div>

      <label className={labelClass}>
        Style
        <textarea
          rows={3}
          value={style}
          onChange={(e) => onChange({ style: e.target.value })}
          placeholder="E.g. informal dialogue, keep honorifics"
          disabled={disabled}
          className={cn(inputClass, "resize-none py-2.5 font-normal")}
        />
      </label>

      <details className="group rounded-md border border-line px-3.5 py-2.5">
        <summary className="cursor-pointer text-sm font-medium marker:text-faint">
          Features <span className="font-normal text-muted">· {off ? `${off} off` : "all on"}</span>
        </summary>
        <div className="mt-3 flex flex-col gap-3">
          {FEATURES.map(({ key, label, hint }) => (
            <div key={key} className="flex flex-col gap-0.5">
              <Toggle
                checked={features[key]}
                onChange={(v) => onChange({ features: { ...features, [key]: v } })}
                label={label}
                disabled={disabled}
              />
              <span className="pl-12 text-xs text-faint">{hint}</span>
            </div>
          ))}
        </div>
      </details>
    </>
  );
}
