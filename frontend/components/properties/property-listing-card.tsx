"use client";

import type { ReactNode } from "react";
import { MapPin } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { PropertyListingCover } from "@/components/properties/property-listing-cover";
import type { Property } from "@/lib/types";
import { cn, formatCurrency, formatNumber, percent, shortAddress } from "@/lib/utils";

export type PropertyListingCardProps = {
  property: Property;
  onClick: () => void;
  statusLabel: string;
  statusVariant?: "success" | "warning" | "muted" | "default";
  actionLabel: string;
  actionIcon?: ReactNode;
  onActionClick?: (e: React.MouseEvent) => void;
  actionDisabled?: boolean;
  actionVariant?: "default" | "secondary";
  footerExtra?: ReactNode;
  toolbar?: ReactNode;
  className?: string;
};

export function PropertyListingCard({
  property,
  onClick,
  statusLabel,
  statusVariant = "success",
  actionLabel,
  actionIcon,
  onActionClick,
  actionDisabled,
  actionVariant = "default",
  footerExtra,
  toolbar,
  className,
}: PropertyListingCardProps) {
  const sold = Number(property.tokens_sold ?? 0);
  const supply = Number(property.token_supply ?? 0);
  const soldPct = Number(property.sold_percentage ?? percent(sold, supply));
  const monthlyRent = Number(property.monthly_rent_eth ?? 0);
  const contractAddr = property.token_address;

  return (
    <article
      role="button"
      tabIndex={0}
      onClick={onClick}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onClick();
        }
      }}
      className={cn(
        "group flex cursor-pointer flex-col overflow-hidden rounded-xl border border-border/80 bg-card text-left shadow-sm",
        "transition-shadow duration-200 hover:shadow-md",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40",
        className,
      )}
    >
      <PropertyListingCover
        images={property.images}
        propertyId={property.id}
        title={property.name}
        className="h-[11.5rem] w-full shrink-0"
      />

      <div className="flex flex-1 flex-col p-4">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0 flex flex-wrap items-center gap-2">
            <h3 className="truncate text-base font-semibold tracking-tight text-foreground">
              #{property.id} {property.name}
            </h3>
            <Badge variant="outline" className="h-5 shrink-0 px-2 text-[10px] font-semibold uppercase tracking-wide">
              {property.token_symbol}
            </Badge>
          </div>
          <Badge variant={statusVariant} className="shrink-0 text-[10px] font-medium">
            {statusLabel}
          </Badge>
        </div>

        <p className="mt-1 flex items-center gap-1 text-xs text-muted-foreground">
          <MapPin className="h-3 w-3 shrink-0" />
          <span className="truncate">{property.location || "—"}</span>
        </p>

        <div className="mt-4 grid grid-cols-2 gap-x-4 gap-y-3">
          <Metric label="Monthly rent" value={monthlyRent > 0 ? `${monthlyRent.toFixed(4)} ETH` : "—"} />
          <Metric label="Property value" value={formatCurrency(property.total_value)} />
          <Metric label="Supply" value={formatNumber(supply)} />
          <Metric label="Ownership sold" value={`${soldPct.toFixed(1)}%`} />
        </div>

        <div className="mt-4">
          <div className="mb-1.5 flex items-center justify-between gap-2 text-xs">
            <span className="text-muted-foreground">Token sale progress</span>
            <span className="font-semibold tabular-nums text-foreground">
              {formatNumber(sold)} / {formatNumber(supply)}
            </span>
          </div>
          <Progress value={soldPct} className="h-1.5 bg-muted" indicatorClassName="bg-primary" />
        </div>

        {toolbar ? (
          <div
            className="mt-3 flex items-center gap-1 border-t border-border/60 pt-3"
            onClick={(e) => e.stopPropagation()}
            onKeyDown={(e) => e.stopPropagation()}
          >
            {toolbar}
          </div>
        ) : null}

        {footerExtra}

        <div className="mt-auto flex items-center justify-between gap-3 border-t border-border/80 pt-3">
          <span className="min-w-0 truncate font-mono text-[11px] text-muted-foreground">
            {contractAddr ? shortAddress(contractAddr, 6, 4) : "Contract pending"}
          </span>
          <Button
            type="button"
            size="sm"
            variant={actionVariant}
            className="h-8 shrink-0 gap-1.5 rounded-lg px-3 text-xs font-semibold shadow-sm"
            disabled={actionDisabled}
            onClick={(e) => {
              e.stopPropagation();
              onActionClick?.(e);
            }}
          >
            {actionIcon}
            {actionLabel}
          </Button>
        </div>
      </div>
    </article>
  );
}

function Metric({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="min-w-0">
      <div className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">{label}</div>
      <div className="mt-0.5 truncate text-sm font-semibold tabular-nums text-foreground">{value}</div>
    </div>
  );
}
