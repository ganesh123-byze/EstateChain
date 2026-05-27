"use client";

import { cn } from "@/lib/utils";
import { AmbientSystemPulse } from "@/components/ai/ambient-system-pulse";
import { AdminTopbar } from "@/components/layout/topbar";
import { StatusDot } from "@/components/layout/status-dot";
import { ThemeToggle } from "@/components/layout/theme-toggle";
import { WalletPill } from "@/components/layout/wallet-pill";

/** Shared height for all header controls on investor routes. */
export const INVESTOR_TOPBAR_CONTROL_CLASS = "h-9 shrink-0";

export function InvestorTopbar({
  title,
  subtitle,
}: {
  title: string;
  subtitle?: string;
}) {
  return (
    <AdminTopbar
      title={title}
      subtitle={subtitle}
      className={cn(
        "border-[#e8ecf4]/90 bg-[#F4F5FB]/95 backdrop-blur-md",
        "dark:border-border/60 dark:bg-background/75",
      )}
      actions={
        <>
          <AmbientSystemPulse
            className={`${INVESTOR_TOPBAR_CONTROL_CLASS} flex px-3 text-xs`}
          />
          <WalletPill className={INVESTOR_TOPBAR_CONTROL_CLASS} />
          <ThemeToggle className={`${INVESTOR_TOPBAR_CONTROL_CLASS} w-[3.25rem]`} />
          <StatusDot className={`${INVESTOR_TOPBAR_CONTROL_CLASS} w-9`} />
        </>
      }
    />
  );
}
