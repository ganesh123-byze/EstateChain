"use client";

import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

export type InvestorKpiVariant = "violet" | "mint" | "sky" | "periwinkle";

const VARIANT_STYLES: Record<
  InvestorKpiVariant,
  {
    outer: string;
    topBar: string;
    body: string;
    title: string;
    iconWrap: string;
    icon: string;
  }
> = {
  violet: {
    outer: cn(
      "border border-[#ebe6f4]/90 shadow-[0_4px_16px_-10px_rgba(124,58,237,0.12)]",
      "dark:border-violet-400/10 dark:shadow-[0_6px_20px_-8px_rgba(124,58,237,0.28)]",
    ),
    topBar: cn(
      "bg-gradient-to-r from-[#7c3aed] via-[#a78bfa] to-[#ddd6fe]",
      "dark:from-[#9333ea] dark:via-[#c026d3] dark:to-[#ec4899]",
    ),
    body: cn(
      "bg-gradient-to-b from-[#fdfcff] via-[#faf7fe] to-[#f3ebfa]",
      "dark:bg-[#1e1b33] dark:bg-gradient-to-b dark:from-[#1e1b33] dark:via-[#1c192f] dark:to-[#181528]",
    ),
    title: "text-[#5b4d78] dark:text-violet-300/85",
    iconWrap: cn(
      "bg-[#f3edfc] ring-1 ring-[#e8dff5]/80",
      "dark:bg-violet-950/50 dark:ring-violet-400/15",
    ),
    icon: "text-[#7c3aed] dark:text-white",
  },
  mint: {
    outer: cn(
      "border border-[#dcefe6]/90 shadow-[0_4px_16px_-10px_rgba(16,185,129,0.1)]",
      "dark:border-emerald-400/10 dark:shadow-[0_6px_20px_-8px_rgba(16,185,129,0.22)]",
    ),
    topBar: cn(
      "bg-gradient-to-r from-[#0d9488] via-[#2dd4bf] to-[#a7f3d0]",
      "dark:from-[#0d9488] dark:via-[#2dd4bf] dark:to-[#4ade80]",
    ),
    body: cn(
      "bg-gradient-to-b from-[#f8fdfb] via-[#f4fbf8] to-[#eaf7f1]",
      "dark:bg-[#0d2b26] dark:bg-gradient-to-b dark:from-[#0d2b26] dark:via-[#0c2621] dark:to-[#0a211c]",
    ),
    title: "text-[#2a6b57] dark:text-emerald-300/85",
    iconWrap: cn(
      "bg-[#ecf9f4] ring-1 ring-[#d4ebe3]/80",
      "dark:bg-emerald-950/50 dark:ring-emerald-400/15",
    ),
    icon: "text-[#0d9488] dark:text-white",
  },
  sky: {
    outer: cn(
      "border border-[#dceaf5]/90 shadow-[0_4px_16px_-10px_rgba(59,130,246,0.1)]",
      "dark:border-sky-400/10 dark:shadow-[0_6px_20px_-8px_rgba(56,189,248,0.22)]",
    ),
    topBar: cn(
      "bg-gradient-to-r from-[#2563eb] via-[#38bdf8] to-[#bae6fd]",
      "dark:from-[#2563eb] dark:via-[#0ea5e9] dark:to-[#22d3ee]",
    ),
    body: cn(
      "bg-gradient-to-b from-[#f8fbff] via-[#f4f9fe] to-[#eaf4fc]",
      "dark:bg-[#0d2137] dark:bg-gradient-to-b dark:from-[#0d2137] dark:via-[#0c1e32] dark:to-[#0a1a2c]",
    ),
    title: "text-[#2a5f8a] dark:text-sky-300/85",
    iconWrap: cn(
      "bg-[#edf6fc] ring-1 ring-[#d4e8f5]/80",
      "dark:bg-sky-950/50 dark:ring-sky-400/15",
    ),
    icon: "text-[#2563eb] dark:text-white",
  },
  periwinkle: {
    outer: cn(
      "border border-[#ebe8f2]/90 shadow-[0_4px_16px_-10px_rgba(99,102,241,0.1)]",
      "dark:border-indigo-400/10 dark:shadow-[0_6px_20px_-8px_rgba(99,102,241,0.22)]",
    ),
    topBar: cn(
      "bg-gradient-to-r from-[#8b5cf6] via-[#c4b5fd] to-[#f5d0fe]",
      "dark:from-[#7c3aed] dark:via-[#a78bfa] dark:to-[#e9d5ff]",
    ),
    body: cn(
      "bg-gradient-to-b from-[#fdfcff] via-[#faf8fe] to-[#f2eef9]",
      "dark:bg-[#1c1b2e] dark:bg-gradient-to-b dark:from-[#1c1b2e] dark:via-[#1a1929] dark:to-[#171624]",
    ),
    title: "text-[#57547a] dark:text-indigo-300/85",
    iconWrap: cn(
      "bg-[#f2f0fa] ring-1 ring-[#e8e4f2]/80",
      "dark:bg-indigo-950/50 dark:ring-indigo-400/15",
    ),
    icon: "text-[#6366f1] dark:text-white",
  },
};

export function InvestorKpiCard({
  title,
  value,
  icon: Icon,
  variant,
  loading,
}: {
  title: string;
  value: string;
  icon: React.ComponentType<{ className?: string }>;
  variant: InvestorKpiVariant;
  loading?: boolean;
}) {
  const v = VARIANT_STYLES[variant];

  return (
    <div className={cn("flex flex-col overflow-hidden rounded-xl", v.outer)}>
      <div className={cn("h-[2px] w-full shrink-0 bg-gradient-to-r", v.topBar)} aria-hidden />
      <div className={cn("flex flex-col p-3", v.body)}>
        <div className="flex items-start justify-between gap-2">
          <span
            className={cn(
              "text-[10px] font-semibold uppercase tracking-[0.12em] leading-tight",
              v.title,
            )}
          >
            {title}
          </span>
          <div className={cn("grid h-8 w-8 shrink-0 place-items-center rounded-full", v.iconWrap)}>
            <Icon className={cn("h-[15px] w-[15px]", v.icon)} strokeWidth={2} />
          </div>
        </div>

        {loading ? (
          <Skeleton className="mt-2 h-7 w-24 rounded-md bg-black/5 dark:bg-white/10" />
        ) : (
          <p className="mt-1.5 text-xl font-bold leading-none tracking-tight text-[#010101] dark:text-white">
            {value}
          </p>
        )}
      </div>
    </div>
  );
}
