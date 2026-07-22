"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import {
  FileText,
  FlaskConical,
  LayoutDashboard,
  ListChecks,
  ScanSearch,
  Terminal,
} from "lucide-react";

import { getHealth } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { HealthResponse } from "@/types";

const NAV_ITEMS = [
  { href: "/", label: "Dashboard", icon: LayoutDashboard },
  { href: "/analyse", label: "Analyse", icon: ScanSearch },
  { href: "/jobs", label: "Jobs", icon: ListChecks },
  { href: "/reports", label: "Reports", icon: FileText },
  { href: "/scenarios", label: "Scenarios", icon: FlaskConical },
] as const;

function isActive(pathname: string, href: string): boolean {
  return href === "/" ? pathname === "/" : pathname.startsWith(href);
}

function Brand() {
  return (
    <Link href="/" className="flex items-center gap-2.5 px-2">
      <span className="flex size-8 items-center justify-center rounded-lg bg-gradient-to-b from-accent-bright to-accent-indigo text-white shadow-glow">
        <Terminal className="size-4" />
      </span>
      <span className="flex flex-col">
        <span className="text-sm leading-tight font-semibold">
          K8s Incident Analyser
        </span>
        <span className="text-muted-foreground text-xs leading-tight">
          LLM ops console
        </span>
      </span>
    </Link>
  );
}

function HealthPill() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [down, setDown] = useState(false);

  useEffect(() => {
    let cancelled = false;

    async function check() {
      try {
        const h = await getHealth();
        if (!cancelled) {
          setHealth(h);
          setDown(false);
        }
      } catch (err) {
        console.error("[HealthPill] health_check_failed", err instanceof Error ? err.message : String(err));
        if (!cancelled) {
          setHealth(null);
          setDown(true);
        }
      }
    }

    check();
    const id = setInterval(check, 30_000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  return (
    <div className="flex items-center gap-2 rounded-lg border border-white/[0.06] bg-white/[0.03] px-2.5 py-1.5 text-xs">
      <span
        className={cn(
          "size-1.5 shrink-0 rounded-full",
          down
            ? "bg-red-400 shadow-[0_0_6px_rgba(248,113,113,0.7)]"
            : health?.cluster === "unreachable"
              ? "bg-amber-400 shadow-[0_0_6px_rgba(251,191,36,0.7)]"
              : health
                ? "bg-emerald-400 shadow-[0_0_6px_rgba(52,211,153,0.7)]"
                : "bg-zinc-500 animate-pulse",
        )}
      />
      <span className="text-muted-foreground truncate">
        {down
          ? "gateway unreachable"
          : health
            ? `${health.service} ${health.version}${health.provider ? ` · ${health.provider}` : ""}${health.cluster === "unreachable" ? " · cluster unreachable" : ""}`
            : "checking gateway…"}
      </span>
    </div>
  );
}

export function AppSidebar() {
  const pathname = usePathname();

  return (
    <aside className="fixed top-0 left-0 z-30 hidden h-screen w-64 flex-col overflow-hidden border-r border-white/[0.06] bg-background-deep/70 backdrop-blur-xl md:flex">
      <div className="flex h-16 shrink-0 items-center px-4">
        <Brand />
      </div>
      <nav className="flex-1 space-y-1 overflow-y-auto px-3 py-2">
        <p className="px-3 pt-1 pb-2 font-mono text-[10px] tracking-[0.2em] text-white/30 uppercase">
          Console
        </p>
        {NAV_ITEMS.map((item) => {
          const active = isActive(pathname, item.href);
          return (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                "relative flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium text-muted-foreground transition-all duration-200 ease-expo-out hover:bg-white/[0.05] hover:text-foreground",
                active &&
                  "bg-white/[0.07] text-foreground shadow-inset-highlight",
              )}
            >
              {active ? (
                <span
                  aria-hidden
                  className="absolute top-1/2 left-0 h-4 w-0.5 -translate-y-1/2 rounded-full bg-accent-indigo shadow-[0_0_8px_rgba(94,106,210,0.9)]"
                />
              ) : null}
              <item.icon className="size-4" />
              {item.label}
            </Link>
          );
        })}
      </nav>
      <div className="shrink-0 p-3">
        <HealthPill />
      </div>
    </aside>
  );
}

export function MobileNav() {
  const pathname = usePathname();

  return (
    <div className="sticky top-0 z-20 border-b border-white/[0.06] bg-background/90 backdrop-blur-xl md:hidden">
      <div className="flex h-14 items-center justify-between px-4">
        <Brand />
        <div className="w-40">
          <HealthPill />
        </div>
      </div>
      <nav className="flex gap-1 overflow-x-auto px-3 pb-2">
        {NAV_ITEMS.map((item) => (
          <Link
            key={item.href}
            href={item.href}
            className={cn(
              "flex shrink-0 items-center gap-2 rounded-lg px-3 py-1.5 text-sm font-medium text-muted-foreground transition-all duration-200 ease-expo-out hover:bg-white/[0.05] hover:text-foreground",
              isActive(pathname, item.href) &&
                "bg-white/[0.07] text-foreground",
            )}
          >
            <item.icon className="size-4" />
            {item.label}
          </Link>
        ))}
      </nav>
    </div>
  );
}
