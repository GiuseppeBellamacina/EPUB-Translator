import type { ReactNode } from "react";
import {
  Checkbox as HCheckbox,
  Field,
  Label,
  Listbox,
  ListboxButton,
  ListboxOption,
  ListboxOptions,
  Switch,
} from "@headlessui/react";
import { Check, ChevronDown } from "lucide-react";
import { cn } from "../lib/utils";

/** On/off switch with its label (settings such as "Review each chunk"). */
export function Toggle({
  checked,
  onChange,
  label,
  disabled,
  className,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label: ReactNode;
  disabled?: boolean;
  className?: string;
}) {
  return (
    <Field disabled={disabled} className={cn("inline-flex items-center gap-2.5 data-disabled:opacity-60", className)}>
      <Switch
        checked={checked}
        onChange={onChange}
        className={cn(
          "group relative inline-flex h-5.5 w-9.5 shrink-0 cursor-pointer items-center rounded-full bg-line-strong transition-colors",
          "data-checked:bg-accent focus:outline-none data-focus:ring-2 data-focus:ring-accent/40 data-disabled:cursor-not-allowed",
        )}
      >
        <span
          aria-hidden="true"
          className="h-4.5 w-4.5 translate-x-0.5 rounded-full bg-surface shadow-sm transition-transform group-data-checked:translate-x-4.5"
        />
      </Switch>
      <Label className="cursor-pointer text-sm text-muted">{label}</Label>
    </Field>
  );
}

/** Square checkbox (selection in lists and tables). */
export function Checkbox({
  checked,
  onChange,
  label,
  disabled,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  /** accessible name */
  label: string;
  disabled?: boolean;
}) {
  return (
    <HCheckbox
      checked={checked}
      onChange={onChange}
      disabled={disabled}
      aria-label={label}
      className={cn(
        "group flex h-4.5 w-4.5 shrink-0 cursor-pointer items-center justify-center rounded border border-line-strong bg-surface transition-colors",
        "data-checked:border-accent data-checked:bg-accent focus:outline-none data-focus:ring-2 data-focus:ring-accent/40",
        "data-disabled:cursor-not-allowed data-disabled:opacity-50",
      )}
    >
      <Check className="invisible h-3.5 w-3.5 text-on-ink group-data-checked:visible" strokeWidth={3} aria-hidden="true" />
    </HCheckbox>
  );
}

/** Dropdown for a short list of plain values. */
export function Select<T extends string>({
  label,
  value,
  options,
  onChange,
  disabled,
  render = (v) => v,
  className,
}: {
  label: string;
  value: T;
  options: readonly T[];
  onChange: (v: T) => void;
  disabled?: boolean;
  render?: (v: T) => ReactNode;
  className?: string;
}) {
  return (
    <Field disabled={disabled} className={cn("flex flex-col gap-1.5", className)}>
      <Label className="text-sm font-medium">{label}</Label>
      <Listbox value={value} onChange={onChange}>
        <ListboxButton
          className={cn(
            "flex h-11 w-full items-center gap-2 rounded-md border border-line-strong bg-surface px-3 text-left text-sm text-ink",
            "focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/40 data-disabled:opacity-60",
          )}
        >
          <span className="flex-1 truncate">{render(value)}</span>
          <ChevronDown className="h-4 w-4 text-faint" aria-hidden="true" />
        </ListboxButton>
        <ListboxOptions
          anchor="bottom start"
          className="z-50 mt-1 max-h-72 w-(--button-width) overflow-auto rounded-md border border-line bg-surface p-1.5 shadow-[0_16px_40px_rgba(27,36,51,0.14)] focus:outline-none"
        >
          {options.map((option) => (
            <ListboxOption
              key={option}
              value={option}
              className="group flex cursor-pointer items-center gap-2 rounded-md px-2.5 py-2 text-sm data-focus:bg-tint"
            >
              <span className="flex-1 truncate">{render(option)}</span>
              <Check className="invisible h-4 w-4 text-accent group-data-selected:visible" aria-hidden="true" />
            </ListboxOption>
          ))}
        </ListboxOptions>
      </Listbox>
    </Field>
  );
}
