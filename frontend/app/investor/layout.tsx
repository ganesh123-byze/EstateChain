"use client";

import { ReactNode, useEffect } from "react";
import { cn } from "@/lib/utils";
import { RoleGate } from "@/components/auth/role-gate";
import { InvestorSidebar } from "@/components/investor/investor-sidebar";
import { InvestorAiRuntime } from "@/components/investor/ai/investor-ai-runtime";

export default function InvestorLayout({ children }: { children: ReactNode }) {
  useEffect(() => {
    document.documentElement.classList.add("investor-route");
    return () => document.documentElement.classList.remove("investor-route");
  }, []);

  return (
    <RoleGate role="investor">
      <InvestorAiRuntime />
      <div
        className={cn(
          "investor-shell relative flex min-h-screen w-full",
          "bg-[#F4F5FB] dark:bg-background",
        )}
      >
        <div
          className="pointer-events-none absolute inset-0 bg-grid opacity-[0.08] dark:opacity-[0.12]"
          aria-hidden
        />
        <InvestorSidebar />
        <div className="relative flex min-w-0 flex-1 flex-col bg-[#F4F5FB] dark:bg-transparent">
          {children}
        </div>
      </div>
    </RoleGate>
  );
}
