import { cn } from "./utils";

export type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";
export type ButtonSize = "md" | "sm";

const variants: Record<ButtonVariant, string> = {
  primary: "bg-ink text-on-ink border-ink font-semibold hover:opacity-90",
  secondary: "bg-surface text-ink border-line-strong hover:bg-tint",
  ghost: "bg-transparent text-ink border-transparent hover:bg-tint",
  danger: "bg-surface text-danger border-line-strong hover:bg-danger-soft",
};

const sizes: Record<ButtonSize, string> = {
  md: "h-11 px-[18px] text-sm",
  sm: "h-9 px-3.5 text-[13px]",
};

/** Pill button classes, for <button>, <a> and <Link> alike. */
export const buttonClass = (variant: ButtonVariant = "secondary", size: ButtonSize = "md") =>
  cn(
    "inline-flex items-center justify-center gap-2 rounded-full border font-medium transition",
    "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent",
    "disabled:opacity-50 disabled:cursor-not-allowed",
    variants[variant],
    sizes[size],
  );

export const inputClass =
  "w-full rounded-md border border-line-strong bg-surface px-3 text-sm text-ink placeholder:text-faint " +
  "focus:outline-none focus:ring-2 focus:ring-accent/40 focus:border-accent disabled:opacity-60";

export const labelClass = "flex flex-col gap-1.5 text-sm font-medium text-ink";
