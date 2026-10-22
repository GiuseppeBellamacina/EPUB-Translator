import { useCallback, useEffect, useState } from "react";
import { Dialog, DialogPanel, DialogTitle } from "@headlessui/react";
import { AlertCircle, Check, Code2, Loader2 } from "lucide-react";
import { api, type ModelOption, type Provider } from "../lib/api";
import { inputClass, labelClass } from "../lib/styles";
import { cn } from "../lib/utils";
import { ModelCombobox } from "./ModelCombobox";
import { ProviderLogo } from "./ProviderLogo";
import { Button } from "./ui";

type KeyMode = "required" | "optional" | "none";

interface Kind {
  id: string;
  label: string;
  type: string;
  key: KeyMode;
  /** whether the user gives an endpoint */
  url?: "optional" | "required";
  urlPlaceholder?: string;
  keyUrl?: string;
}

const KINDS: Kind[] = [
  { id: "openai", label: "OpenAI", type: "openai", key: "required", keyUrl: "https://platform.openai.com/api-keys" },
  { id: "anthropic", label: "Anthropic", type: "anthropic", key: "required", keyUrl: "https://console.anthropic.com/settings/keys" },
  { id: "openrouter", label: "OpenRouter", type: "openrouter", key: "required", keyUrl: "https://openrouter.ai/keys" },
  { id: "ollama", label: "Ollama", type: "ollama", key: "none", url: "optional", urlPlaceholder: "http://host.docker.internal:11434" },
  { id: "custom", label: "Custom", type: "custom", key: "optional", url: "required", urlPlaceholder: "http://my-server:8000/v1" },
]; // fmt: off

function kindOf(p: Provider): Kind {
  return KINDS.find((k) => k.type === p.provider_type) ?? KINDS[4];
}

type Check = { state: "idle" | "checking" | "ok" | "error"; message?: string };

/** Add a provider, or edit one (`provider` set): type → key/URL (checked live) → default model. */
export function ProviderWizard({
  open,
  provider,
  onClose,
  onSaved,
}: {
  open: boolean;
  provider?: Provider | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const editing = !!provider;
  const [kind, setKind] = useState<Kind>(provider ? kindOf(provider) : KINDS[0]);
  const [apiKey, setApiKey] = useState("");
  const [url, setUrl] = useState(provider?.base_url ?? "");
  const [name, setName] = useState(provider?.name ?? "");
  const [model, setModel] = useState(provider?.default_model ?? "");
  const [typedCreds, setCreds] = useState<{ key: string; url: string } | null>(null);
  const [check, setCheck] = useState<Check>({ state: "idle" });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const baseUrl = url.trim() || undefined;
  const keyMissing = kind.key === "required" && !apiKey.trim() && !editing;
  const urlMissing = kind.url === "required" && !url.trim();

  // Check the credentials once typing pauses; editing with an empty key keeps the stored one
  useEffect(() => {
    if (keyMissing || urlMissing) return;
    const timer = setTimeout(() => setCreds({ key: apiKey.trim(), url: baseUrl ?? "" }), 600);
    return () => clearTimeout(timer);
  }, [apiKey, baseUrl, keyMissing, urlMissing]);
  const creds = keyMissing || urlMissing ? null : typedCreds;

  const load = useCallback(
    (refresh: boolean): Promise<ModelOption[]> => {
      if (!creds) return Promise.resolve([]);
      setCheck({ state: "checking" });
      const unchanged = editing && !creds.key && creds.url === (provider?.base_url ?? "");
      return unchanged
        ? api.getProviderModels(provider!.id, refresh)
        : api.listModelsFor({
            provider_type: kind.type,
            api_key: creds.key || undefined,
            base_url: creds.url || undefined,
          });
    },
    [creds, editing, kind.type, provider],
  );

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      const data = {
        name: name.trim() || kind.id,
        provider_type: kind.type,
        base_url: baseUrl,
        default_model: model || undefined,
        api_key: apiKey.trim() || undefined,
      };
      if (provider) await api.updateProvider(provider.id, data);
      else await api.createProvider(data);
      onSaved();
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save the provider");
    } finally {
      setSaving(false);
    }
  };

  const pickKind = (k: Kind) => {
    setKind(k);
    setModel("");
    setCheck({ state: "idle" });
    if (!name || KINDS.some((x) => x.id === name)) setName(k.id);
  };

  return (
    <Dialog open={open} onClose={onClose} className="relative z-50">
      <div className="fixed inset-0 bg-ink/35" aria-hidden="true" />
      <div className="fixed inset-0 flex items-start justify-center overflow-auto p-4 pt-12">
        <DialogPanel className="w-full max-w-xl overflow-hidden rounded-lg bg-surface shadow-[0_24px_60px_rgba(27,36,51,0.18)]">
          <div className="flex items-baseline justify-between border-b border-line px-6 py-5">
            <DialogTitle className="m-0 font-serif text-[26px] font-medium">
              {editing ? `Edit ${provider?.name}` : "Add provider"}
            </DialogTitle>
            {provider?.source === "config" && (
              <span className="text-xs text-faint">Saving makes it independent of config.yaml</span>
            )}
          </div>

          <div className="flex flex-col gap-5 px-6 py-5">
            <div role="radiogroup" aria-label="Provider type" className="grid grid-cols-3 gap-2 sm:grid-cols-5">
              {KINDS.map((k) => (
                <button
                  key={k.id}
                  type="button"
                  role="radio"
                  aria-checked={kind.id === k.id}
                  disabled={editing}
                  onClick={() => pickKind(k)}
                  className={cn(
                    "flex h-18 flex-col items-center justify-center gap-1.5 rounded-lg border text-xs transition-colors",
                    kind.id === k.id
                      ? "border-2 border-ink bg-tint font-semibold"
                      : "border-line bg-surface hover:bg-tint",
                    editing && kind.id !== k.id && "opacity-40",
                  )}
                >
                  {k.id === "custom" ? (
                    <Code2 className="h-5.5 w-5.5" aria-hidden="true" />
                  ) : (
                    <ProviderLogo
                      providerType={k.type}
                      label={false}
                      className="h-5.5 w-5.5"
                    />
                  )}
                  {k.label}
                </button>
              ))}
            </div>

            {(kind.url || kind.key !== "none") && (
              <div className={cn("grid gap-3", kind.url && kind.key !== "none" && "sm:grid-cols-2")}>
                {kind.url && (
                  <label className={labelClass}>
                    Base URL {kind.url === "optional" && <span className="text-xs font-normal text-faint">optional</span>}
                    <input
                      value={url}
                      onChange={(e) => setUrl(e.target.value)}
                      placeholder={kind.urlPlaceholder}
                      className={cn(inputClass, "h-11 font-mono text-[13px] font-normal")}
                    />
                  </label>
                )}
                {kind.key !== "none" && (
                  <label className={labelClass}>
                    <span className="flex items-center justify-between">
                      <span>
                        API key{" "}
                        {kind.key === "optional" && <span className="text-xs font-normal text-faint">optional</span>}
                      </span>
                      {kind.keyUrl && (
                        <a href={kind.keyUrl} target="_blank" rel="noreferrer" className="text-xs font-normal">
                          Get a key
                        </a>
                      )}
                    </span>
                    <input
                      type="password"
                      autoComplete="off"
                      value={apiKey}
                      onChange={(e) => setApiKey(e.target.value)}
                      placeholder={editing ? "Unchanged" : "Paste your key"}
                      className={cn(inputClass, "h-11 font-mono text-[13px] font-normal")}
                    />
                  </label>
                )}
              </div>
            )}

            <div role="status" className="min-h-5 text-[13px]">
              {check.state === "checking" && (
                <span className="inline-flex items-center gap-1.5 text-muted">
                  <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" /> Checking the connection…
                </span>
              )}
              {check.state === "ok" && (
                <span className="inline-flex items-center gap-1.5 font-medium text-accent">
                  <Check className="h-4 w-4" aria-hidden="true" /> {check.message}
                </span>
              )}
              {check.state === "error" && (
                <span className="inline-flex items-start gap-1.5 text-danger">
                  <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" /> {check.message}
                </span>
              )}
              {check.state === "idle" && (keyMissing || urlMissing) && (
                <span className="text-faint">
                  {keyMissing ? "Enter the API key" : "Enter the endpoint URL"} to list the models.
                </span>
              )}
            </div>

            <div className="flex flex-col gap-1.5">
              <span className="text-sm font-medium">Default model</span>
              {creds ? (
                <ModelCombobox
                  key={`${kind.id}|${creds.key}|${creds.url}`}
                  label="Default model"
                  load={load}
                  loadKey={`${kind.id}|${creds.key}|${creds.url}`}
                  value={model}
                  onChange={setModel}
                  preferred={provider?.default_model}
                  providerType={kind.type}
                  baseUrl={baseUrl}
                  onLoaded={(list) =>
                    setCheck({
                      state: "ok",
                      message: `${kind.key === "none" ? "Connected" : "Key works"} · ${list.length} models`,
                    })
                  }
                  onError={(message) =>
                    setCheck({ state: "error", message: `${message}. You can still type a model id below.` })
                  }
                  showError={false}
                />
              ) : (
                <input disabled placeholder="Waiting for the connection details" className={cn(inputClass, "h-13")} />
              )}
            </div>

            {error && <p className="m-0 text-sm text-danger">{error}</p>}
          </div>

          <div className="flex flex-wrap items-end justify-between gap-3 border-t border-line px-6 py-4">
            <label className="flex flex-col gap-1 text-[13px] text-muted">
              Name
              <input value={name} onChange={(e) => setName(e.target.value)} className={cn(inputClass, "h-10")} />
            </label>
            <div className="flex gap-2.5">
              <Button onClick={onClose}>Cancel</Button>
              <Button variant="primary" onClick={save} disabled={saving || keyMissing || urlMissing || (!model && !editing)}>
                {saving && <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />}
                {editing ? "Save changes" : "Save provider"}
              </Button>
            </div>
          </div>
        </DialogPanel>
      </div>
    </Dialog>
  );
}
