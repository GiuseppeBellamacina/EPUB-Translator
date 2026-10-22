import { Outlet, NavLink } from "react-router-dom";
import { BookOpen, Server, Upload } from "lucide-react";
import { cn } from "../lib/utils";
import { ThemeToggle } from "./ThemeToggle";

const navItems = [
  { to: "/", icon: Upload, label: "Upload" },
  { to: "/library", icon: BookOpen, label: "Library" },
  { to: "/providers", icon: Server, label: "Providers" },
];

export function Layout() {
  return (
    <div className="flex min-h-screen flex-col bg-paper md:h-screen md:flex-row md:overflow-hidden">
      <aside className="flex shrink-0 flex-col border-b border-line bg-surface md:w-58 md:border-b-0 md:border-r">
        <div className="flex items-center justify-between px-6 pb-3 pt-5 md:pb-6">
          <span className="font-serif text-[22px] font-semibold text-ink">Translator</span>
          <ThemeToggle className="md:hidden" />
        </div>

        <nav aria-label="Main" className="flex gap-1 overflow-x-auto px-3 pb-3 md:flex-1 md:flex-col md:pb-0">
          {navItems.map(({ to, icon: Icon, label }) => (
            <NavLink
              key={to}
              to={to}
              end={to === "/"}
              className={({ isActive }) =>
                cn(
                  "flex shrink-0 items-center gap-2.5 rounded-full px-3.5 py-2.5 text-sm transition-colors",
                  isActive ? "bg-ink font-semibold text-on-ink" : "text-muted hover:bg-tint hover:text-ink",
                )
              }
            >
              <Icon className="h-4.5 w-4.5" strokeWidth={1.8} aria-hidden="true" />
              {label}
            </NavLink>
          ))}
        </nav>

        <div className="hidden items-center justify-between border-t border-line px-6 py-4 md:flex">
          <span className="text-xs text-faint">Theme</span>
          <ThemeToggle />
        </div>
      </aside>

      <main className="min-w-0 flex-1 md:overflow-auto">
        <Outlet />
      </main>
    </div>
  );
}
