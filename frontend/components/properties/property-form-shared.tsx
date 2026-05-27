"use client";

import { Label } from "@/components/ui/label";
import { cn, formatEth } from "@/lib/utils";

/** Per-token sale price in ETH from total property value (ETH) ÷ token supply. */
export function calculateTokenPriceEth(totalValueEth: string, tokenSupply: string): number {
  const total = Number(totalValueEth);
  const supply = Number(tokenSupply);
  if (!Number.isFinite(total) || !Number.isFinite(supply) || total <= 0 || supply <= 0) return 0;
  return total / supply;
}

export function formatTokenPriceEth(priceEth: number, digits = 6): string {
  if (priceEth <= 0) return "";
  return formatEth(priceEth, { digits });
}

export const propertyDialogContentClass =
  "flex max-h-[calc(100vh-3rem)] w-[min(100vw-2rem,28rem)] max-w-[min(100vw-2rem,28rem)] flex-col gap-3 overflow-hidden p-0 sm:max-w-md";

/** Inner padded scroll container used inside each property dialog. */
export const propertyDialogBodyClass =
  "scrollbar-thin flex min-h-0 flex-col gap-4 overflow-y-auto px-6 pb-6 pt-5";

/** Scrollable main area for property detail overview modals (admin / tenant). */
export const propertyDetailScrollBodyClass =
  "scrollbar-thin min-h-0 flex-1 overflow-x-hidden overflow-y-auto overscroll-contain scroll-smooth";

/** Investor detail modal shell — 512px (max-w-lg), height follows content up to min(92vh, 920px). */
export const investorPropertyDetailDialogClass =
  "flex h-fit w-full max-w-lg flex-col gap-0 overflow-hidden p-0 max-h-[min(92vh,920px)] sm:rounded-2xl";

/** Investor detail scroll body (reserves ~48px for the pinned Invest footer). */
export const investorPropertyDetailScrollBodyClass =
  "scrollbar-thin overflow-x-hidden overflow-y-auto overscroll-contain scroll-smooth max-h-[calc(min(92vh,920px)-3rem)]";

/** Sticky footer styling used at the bottom of property dialogs. */
export const propertyDialogFooterClass =
  "sticky bottom-0 z-10 flex flex-col-reverse gap-2 border-t border-border/60 bg-card/95 px-6 py-3 backdrop-blur sm:flex-row sm:justify-end";

export const propertyFormClass = "grid min-w-0 gap-3";

export const propertyFormGridClass = "grid min-w-0 grid-cols-1 gap-3 sm:grid-cols-2";

export function PropertyFormField({
  label,
  children,
  className,
}: {
  label: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("grid min-w-0 gap-1.5", className)}>
      <Label className="text-xs">{label}</Label>
      <div className="min-w-0 [&_input]:min-w-0 [&_input]:w-full [&_input]:max-w-full">{children}</div>
    </div>
  );
}
