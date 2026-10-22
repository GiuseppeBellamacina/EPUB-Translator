import { useCallback, useEffect, useState } from "react";
import { Loader2, Plus } from "lucide-react";
import { api, type Provider } from "../lib/api";
import { cn } from "../lib/utils";
import { ProviderLogo } from "../components/ProviderLogo";
import { ProviderWizard } from "../components/ProviderWizard";
import { Button, Card, Page } from "../components/ui";

type Status = { state: "checking" } | { state: "ok"; models: number; free: number } | { state: "error"; message: string };

function kindLabel(p: Provider) {
  return (
    { openai: "OpenAI", anthropic: "Anthropic", openrouter: "OpenRouter", ollama: "Ollama", custom: "Custom endpoint", fake: "Offline test" }[
      p.provider_type
    ] ?? p.provider_type
  );
}

function StatusBadge({ status }: { status: Status | undefined }) {
  if (!status || status.state === "checking") {
    return (
      <span className="inline-flex items-center gap-1.5 text-xs text-faint">
        <Loader2 className="h-3 w-3 animate-spin" aria-hidden="true" /> Checking
      </span>
    );
  }
  const ok = status.state === "ok";
  return (
    <span className={cn("inline-flex items-center gap-1.5 text-xs font-medium", ok ? "text-accent" : "text-warn")}>
      <span className="h-1.5 w-1.5 rounded-full bg-current" aria-hidden="true" />
      {ok ? "Connected" : "Not reachable"}
    </span>
  );
}

export function ProvidersPage() {
  const [providers, setProviders] = useState<Provider[] | null>(null);
  const [status, setStatus] = useState<Record<number, Status>>({});
  const [editing, setEditing] = useState<Provider | null>(null);
  const [adding, setAdding] = useState(false);

  const load = useCallback(() => {
    api.getProviders().then((list) => {
      setProviders(list);
      setStatus({});
      for (const p of list) {
        api
          .getProviderModels(p.id)
          .then((models) =>
            setStatus((s) => ({
              ...s,
              [p.id]: {
                state: "ok",
                models: models.length,
                free: models.filter((m) => m.input_per_million === 0 && m.output_per_million === 0).length,
              },
            })),
          )
          .catch((e) =>
            setStatus((s) => ({
              ...s,
              [p.id]: { state: "error", message: e instanceof Error ? e.message : "Unreachable" },
            })),
          );
      }
    });
  }, []);

  useEffect(load, [load]);

  const remove = async (p: Provider) => {
    const note =
      p.source === "config" ? "\n\nIt comes from config.yaml and will be re-created at the next start unless you remove it there." : "";
    if (!window.confirm(`Delete the provider "${p.name}"?${note}`)) return;
    await api.deleteProvider(p.id);
    load();
  };

  return (
    <Page
      title="Providers"
      description="Models are listed live from each provider. Keys in .env are added automatically."
      actions={
        <Button variant="primary" onClick={() => setAdding(true)}>
          <Plus className="h-4 w-4" aria-hidden="true" /> Add provider
        </Button>
      }
    >
      {providers === null ? (
        <Loader2 className="mx-auto h-6 w-6 animate-spin text-faint" aria-label="Loading" />
      ) : providers.length === 0 ? (
        <Card className="flex flex-col items-center gap-4 py-16 text-center">
          <p className="m-0 text-muted">No providers yet. Add one, or put API keys in .env and restart.</p>
          <Button variant="primary" onClick={() => setAdding(true)}>
            Add provider
          </Button>
        </Card>
      ) : (
        <ul className="m-0 grid list-none grid-cols-[repeat(auto-fill,minmax(280px,1fr))] gap-4 p-0">
          {providers.map((p) => {
            const s = status[p.id];
            return (
              <li key={p.id}>
                <Card className="flex h-full flex-col gap-3 p-5">
                  <div className="flex items-center gap-3">
                    <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-tint">
                      <ProviderLogo providerType={p.provider_type} baseUrl={p.base_url} className="h-5.5 w-5.5" />
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-[15px] font-semibold">{p.name}</div>
                      <div className="truncate text-[13px] text-muted">
                        {kindLabel(p)}
                        {s?.state === "ok" && ` · ${s.models} models${s.free ? `, ${s.free} free` : ""}`}
                      </div>
                    </div>
                    <StatusBadge status={s} />
                  </div>

                  {s?.state === "error" ? (
                    <p className="m-0 line-clamp-2 text-[13px] text-muted" title={s.message}>
                      {s.message}
                    </p>
                  ) : (
                    <div className="flex justify-between gap-3 text-[13px]">
                      <span className="text-faint">Default</span>
                      <span className="truncate font-mono">{p.default_model ?? "—"}</span>
                    </div>
                  )}

                  <div className="mt-auto flex items-center justify-between gap-2 border-t border-line pt-3">
                    <span className="text-xs text-faint">{p.source === "config" ? "From config.yaml" : "Added here"}</span>
                    <div className="flex gap-1.5">
                      <Button size="sm" variant="ghost" onClick={() => remove(p)} aria-label={`Delete ${p.name}`}>
                        Delete
                      </Button>
                      <Button size="sm" onClick={() => setEditing(p)}>
                        Edit
                      </Button>
                    </div>
                  </div>
                </Card>
              </li>
            );
          })}
        </ul>
      )}

      {(adding || editing) && (
        <ProviderWizard
          open
          provider={editing}
          onClose={() => {
            setAdding(false);
            setEditing(null);
          }}
          onSaved={load}
        />
      )}
    </Page>
  );
}
