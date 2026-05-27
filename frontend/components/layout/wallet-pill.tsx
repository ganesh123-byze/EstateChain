"use client";

import { useEffect, useState } from "react";
import { ChevronDown, LogOut } from "lucide-react";
import { MetaMaskIcon } from "@/components/icons/metamask";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { logout } from "@/lib/auth";
import { getSession, type SessionRecord } from "@/lib/api";
import { cn, shortAddress } from "@/lib/utils";

export function WalletPill({ className }: { className?: string }) {
  const [session, setSession] = useState<SessionRecord | null>(null);

  useEffect(() => {
    setSession(getSession());
    const handler = () => setSession(getSession());
    window.addEventListener("estatechain:session-changed", handler);
    window.addEventListener("storage", handler);
    return () => {
      window.removeEventListener("estatechain:session-changed", handler);
      window.removeEventListener("storage", handler);
    };
  }, []);

  if (!session) {
    return (
      <Button asChild size="sm" variant="outline" className="gap-2 px-3">
        <a href="/">
          <MetaMaskIcon size={16} />
          Connect Wallet
        </a>
      </Button>
    );
  }

  const wallet = session.user?.wallet_address ?? "";
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          className={cn(
            "inline-flex items-center gap-2 rounded-full border border-border bg-card px-3 text-xs font-medium text-foreground/90 transition-colors hover:bg-muted",
            className,
          )}
        >
          <MetaMaskIcon size={16} />
          <span className="font-mono tracking-tight">{shortAddress(wallet, 4, 4)}</span>
          <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-56">
        <DropdownMenuLabel>Connected wallet</DropdownMenuLabel>
        <div className="px-2 pb-2 font-mono text-[11px] text-muted-foreground break-all">{wallet}</div>
        <DropdownMenuSeparator />
        <DropdownMenuItem onClick={() => logout()} className="text-destructive focus:text-destructive">
          <LogOut className="h-4 w-4" />
          Disconnect
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
