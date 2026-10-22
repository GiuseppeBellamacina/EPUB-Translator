import { Listbox, ListboxButton, ListboxOption, ListboxOptions } from "@headlessui/react";
import { Check, ChevronDown } from "lucide-react";
import type { Provider } from "../lib/api";
import { cn } from "../lib/utils";
import { ProviderLogo } from "./ProviderLogo";

export function ProviderSelect({
  providers,
  value,
  onChange,
  disabled,
}: {
  providers: Provider[];
  value: number | null;
  onChange: (id: number) => void;
  disabled?: boolean;
}) {
  const selected = providers.find((p) => p.id === value);
  return (
    <Listbox value={value} onChange={(id: number | null) => id !== null && onChange(id)} disabled={disabled}>
      <ListboxButton
        aria-label="Provider"
        className={cn(
          "flex h-11 w-full items-center gap-2.5 rounded-md border border-line-strong bg-surface px-3 text-left text-sm text-ink",
          "focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/40 disabled:opacity-60",
        )}
      >
        {selected ? (
          <>
            <ProviderLogo providerType={selected.provider_type} baseUrl={selected.base_url} label={false} className="h-4 w-4" />
            <span className="flex-1 truncate font-medium">{selected.name}</span>
          </>
        ) : (
          <span className="flex-1 text-faint">No providers</span>
        )}
        <ChevronDown className="h-4 w-4 text-faint" aria-hidden="true" />
      </ListboxButton>
      <ListboxOptions
        anchor="bottom start"
        className="z-50 mt-1 w-(--button-width) rounded-md border border-line bg-surface p-1.5 shadow-[0_16px_40px_rgba(27,36,51,0.14)] focus:outline-none"
      >
        {providers.map((p) => (
          <ListboxOption
            key={p.id}
            value={p.id}
            className="group flex cursor-pointer items-center gap-2.5 rounded-md px-2.5 py-2 text-sm data-focus:bg-tint"
          >
            <ProviderLogo providerType={p.provider_type} baseUrl={p.base_url} label={false} className="h-4 w-4" />
            <span className="flex-1 truncate">{p.name}</span>
            <Check className="invisible h-4 w-4 text-accent group-data-selected:visible" aria-hidden="true" />
          </ListboxOption>
        ))}
      </ListboxOptions>
    </Listbox>
  );
}
