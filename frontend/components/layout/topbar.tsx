"use client";

import type { ReactNode } from "react";
import { Menu } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ThemeToggle } from "./theme-toggle";
import { WalletPill } from "./wallet-pill";
import { StatusDot } from "./status-dot";
import { cn } from "@/lib/utils";
import { AmbientSystemPulse } from "@/components/ai/ambient-system-pulse";

export function AdminTopbar({
  title,
  subtitle,
  onMenuClick,
  actions,
  className,
}: {
  title: string;
  subtitle?: string;
  onMenuClick?: () => void;
  /** Override default header actions (investor topbar uses uniform control sizes). */
  actions?: ReactNode;
  className?: string;
}) {
  return (
    <header
      className={cn(
        "sticky top-0 z-30 flex h-16 items-center justify-between gap-4 border-b border-border/60 bg-background/75 px-4 shadow-elevate backdrop-blur-xl lg:px-6",
        className,
      )}
    >
      <div className="flex items-center gap-3">
        <Button
          variant="ghost"
          size="icon"
          className="lg:hidden"
          onClick={onMenuClick}
          aria-label="Open navigation"
        >
          <Menu className="h-5 w-5" />
        </Button>
        <div className="flex flex-col leading-tight">
          <h1 className="text-base font-semibold tracking-tight md:text-lg">{title}</h1>
          {subtitle ? <span className="text-xs text-muted-foreground">{subtitle}</span> : null}
        </div>
      </div>
      <div className="flex items-center gap-2">
        {actions ?? (
          <>
            <AmbientSystemPulse />
            <WalletPill />
            <ThemeToggle />
            <StatusDot />
          </>
        )}
      </div>
    </header>
  );
}
