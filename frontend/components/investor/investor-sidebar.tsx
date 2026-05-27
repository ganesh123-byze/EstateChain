"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Building2, LayoutDashboard, Receipt, Wallet } from "lucide-react";
import { cn } from "@/lib/utils";

const NAV = [
  { href: "/investor", label: "Dashboard", icon: LayoutDashboard },
  { href: "/investor/marketplace", label: "Marketplace", icon: Building2 },
  { href: "/investor/portfolio", label: "Portfolio", icon: Wallet },
  { href: "/investor/transactions", label: "Transactions", icon: Receipt },
] as const;

export function InvestorSidebar() {
  const pathname = usePathname();

  return (
    <aside
      className={cn(
        "sticky top-0 hidden h-screen w-[260px] shrink-0 flex-col border-r lg:flex",
        "border-[#e8ecf4] bg-[#F9FAFF]",
        "dark:border-white/[0.06] dark:bg-[#0b1120]",
      )}
    >
      <div className="px-4 pb-4 pt-5">
        <Link href="/investor" className="flex items-center gap-3">
          <div className="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-[#1e3a8a] text-sm font-bold text-white shadow-sm dark:bg-[#2563eb]">
            E
          </div>
          <div className="min-w-0 flex flex-col leading-tight">
            <span className="truncate text-[15px] font-semibold text-[#010101] dark:text-white">
              EstateChain
            </span>
            <span className="text-[12px] text-[#6c7381] dark:text-[#9ca3af]">Investor Suite</span>
          </div>
        </Link>
      </div>

      <div className="mx-4 border-b border-[#e8ecf4] dark:border-white/[0.08]" aria-hidden />

      <div className="flex flex-1 flex-col py-4">
        <p className="mb-3 px-5 text-[10px] font-semibold uppercase tracking-[0.16em] text-[#9ca3af] dark:text-[#6b7280]">
          Menu
        </p>

        <nav className="flex flex-col gap-0.5">
          {NAV.map((item) => {
            const active =
              item.href === "/investor"
                ? pathname === "/investor"
                : pathname?.startsWith(item.href);
            const Icon = item.icon;

            return (
              <Link
                key={item.href}
                href={item.href}
                className={cn(
                  "group relative flex min-h-[42px] w-full items-center gap-3 py-2.5 pl-5 pr-4 text-[13px] font-medium",
                  "transition-[color] duration-150",
                  "outline-none focus-visible:ring-2 focus-visible:ring-[#2563eb]/30 focus-visible:ring-offset-2 focus-visible:ring-offset-[#F9FAFF] dark:focus-visible:ring-offset-[#0b1120]",
                  active
                    ? "text-[#2563eb] dark:text-[#60a5fa]"
                    : "text-[#6c7381] hover:text-[#374151] dark:text-[#9ca3af] dark:hover:text-[#e5e7eb]",
                )}
              >
                {active ? (
                  <>
                    <span
                      aria-hidden
                      className={cn(
                        "pointer-events-none absolute inset-y-0 left-0 right-1 z-0 rounded-l-[10px]",
                        "bg-gradient-to-r from-[#dbeafe] via-[#e8f2ff]/75 to-transparent",
                        "dark:from-[#1e3a8a]/70 dark:via-[#172554]/45 dark:to-transparent",
                      )}
                    />
                    <span
                      aria-hidden
                      className="pointer-events-none absolute inset-y-0 left-0 z-[1] w-[3px] bg-[#2563eb] dark:bg-[#3b82f6]"
                    />
                  </>
                ) : (
                  <span
                    aria-hidden
                    className={cn(
                      "pointer-events-none absolute inset-y-0 left-2 right-2 z-0 rounded-lg opacity-0 transition-opacity duration-150",
                      "group-hover:opacity-100 group-focus-visible:opacity-100",
                      "bg-[#eef1f8] dark:bg-white/[0.04]",
                    )}
                  />
                )}
                <Icon className="relative z-10 h-[18px] w-[18px] shrink-0" strokeWidth={1.75} />
                <span className="relative z-10">{item.label}</span>
              </Link>
            );
          })}
        </nav>
      </div>
    </aside>
  );
}
