import { Moon, Sun } from "lucide-react";
import { useTheme } from "../hooks/useTheme";
import { cn } from "../lib/utils";

export function ThemeToggle({ className }: { className?: string }) {
  const { isDark, toggleTheme } = useTheme();

  return (
    <button
      onClick={toggleTheme}
      role="switch"
      aria-checked={isDark}
      aria-label={isDark ? "Switch to light theme" : "Switch to dark theme"}
      title={isDark ? "Light theme" : "Dark theme"}
      className={cn(
        "relative inline-flex h-8 w-14 shrink-0 items-center rounded-full p-1 transition-colors duration-300 ease-out ring-1",
        "focus:outline-none focus-visible:ring-2 focus-visible:ring-gray-900 dark:focus-visible:ring-white focus-visible:ring-offset-2",
        "focus-visible:ring-offset-white dark:focus-visible:ring-offset-black",
        isDark ? "bg-gray-800 ring-white/10" : "bg-gray-200 ring-black/5",
        className,
      )}
    >
      {/* Sliding knob */}
      <span
        className={cn(
          "flex h-6 w-6 items-center justify-center rounded-full shadow-sm",
          "transform transition-transform duration-300 ease-out",
          isDark ? "translate-x-6 bg-black" : "translate-x-0 bg-white",
        )}
      >
        <Sun
          className={cn(
            "absolute h-3.5 w-3.5 text-gray-700 transition-all duration-300",
            isDark
              ? "scale-0 -rotate-90 opacity-0"
              : "scale-100 rotate-0 opacity-100",
          )}
        />
        <Moon
          className={cn(
            "absolute h-3.5 w-3.5 text-gray-200 transition-all duration-300",
            isDark
              ? "scale-100 rotate-0 opacity-100"
              : "scale-0 rotate-90 opacity-0",
          )}
        />
      </span>
    </button>
  );
}
