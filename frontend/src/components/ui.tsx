import type { ButtonHTMLAttributes, HTMLAttributes, ReactNode } from "react";
import { cn } from "../lib/utils";
import { buttonClass, type ButtonSize, type ButtonVariant } from "../lib/styles";

/** Pill button of the design system. */
export function Button({
  variant = "secondary",
  size = "md",
  className,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: ButtonVariant; size?: ButtonSize }) {
  return <button type="button" {...props} className={cn(buttonClass(variant, size), className)} />;
}

export function Card({ className, children, ...props }: HTMLAttributes<HTMLElement>) {
  return (
    <section {...props} className={cn("rounded-md border border-line bg-surface", className)}>
      {children}
    </section>
  );
}

/** Serif section heading. */
export function Heading({
  id,
  children,
  className,
}: {
  id?: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <h2 id={id} className={cn("m-0 font-serif text-[22px] font-medium text-ink", className)}>
      {children}
    </h2>
  );
}

/** Small uppercase label above a title. */
export function Eyebrow({ children }: { children: ReactNode }) {
  return <div className="text-xs uppercase tracking-[0.12em] text-faint">{children}</div>;
}

const statusStyles: Record<string, string> = {
  uploaded: "bg-tint text-muted",
  queued: "bg-tint text-ink",
  translating: "bg-accent-soft text-accent",
  paused: "bg-warn-soft text-warn",
  completed: "bg-accent-soft text-accent",
  failed: "bg-danger-soft text-danger",
};

export function StatusPill({ status }: { status: string }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-semibold capitalize",
        statusStyles[status] ?? statusStyles.uploaded,
      )}
    >
      <span className="h-1.5 w-1.5 rounded-full bg-current" aria-hidden="true" />
      {status}
    </span>
  );
}

/** Page wrapper: title block plus content. */
export function Page({
  eyebrow,
  title,
  description,
  actions,
  children,
  wide = false,
}: {
  eyebrow?: ReactNode;
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  wide?: boolean;
}) {
  return (
    <div
      className={cn(
        "mx-auto flex w-full flex-col gap-6 px-4 py-7 sm:px-8 animate-fade-in-up",
        wide ? "max-w-350" : "max-w-5xl",
      )}
    >
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div className="flex min-w-0 flex-col gap-1.5">
          {eyebrow && <Eyebrow>{eyebrow}</Eyebrow>}
          <h1 className="m-0 font-serif text-[40px] font-medium leading-[1.05] text-ink break-words">
            {title}
          </h1>
          {description && <p className="m-0 text-muted">{description}</p>}
        </div>
        {actions && <div className="flex flex-wrap items-center gap-2.5">{actions}</div>}
      </header>
      {children}
    </div>
  );
}
