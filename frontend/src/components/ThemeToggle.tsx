import { Moon, Sun } from "lucide-react";
import { useTheme } from "../hooks/useTheme";
import { cn } from "../lib/utils";

export function ThemeToggle({ className }: { className?: string }) {
  const { isDark, toggleTheme } = useTheme();

  return (
    <button
      type="button"
      onClick={toggleTheme}
      role="switch"
      aria-checked={isDark}
      aria-label="Dark theme"
      title={isDark ? "Light theme" : "Dark theme"}
      className={cn(
        "relative inline-flex h-8 w-14 shrink-0 items-center rounded-full border border-line-strong bg-tint p-1 transition-colors",
        "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent",
        className,
      )}
    >
      <span
        className={cn(
          "flex h-6 w-6 items-center justify-center rounded-full bg-surface shadow-sm transition-transform duration-300 motion-reduce:transition-none",
          isDark ? "translate-x-6" : "translate-x-0",
        )}
      >
        {isDark ? (
          <Moon className="h-3.5 w-3.5 text-ink" aria-hidden="true" />
        ) : (
          <Sun className="h-3.5 w-3.5 text-ink" aria-hidden="true" />
        )}
      </span>
    </button>
  );
}
