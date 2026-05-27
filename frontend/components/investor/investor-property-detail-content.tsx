"use client";

import { useState } from "react";
import { BadgeCheck, Banknote, Check, Copy, MapPin } from "lucide-react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { Button } from "@/components/ui/button";
import { PropertyImageGallery } from "@/components/properties/property-image-gallery";
import { availablePropertyTokens, propertyUnitValue } from "@/components/investor/investor-utils";
import { addressExplorerUrl, RUNTIME_CONFIG } from "@/lib/runtime-config";
import type { Property } from "@/lib/types";
import { cn, formatCurrency, formatNumber, percent, shortAddress } from "@/lib/utils";

const CHAIN_LABELS: Record<number, string> = {
  1: "Ethereum Mainnet",
  11155111: "Sepolia",
};

function chainLabel(): string {
  return CHAIN_LABELS[RUNTIME_CONFIG.chainId] ?? `Chain ${RUNTIME_CONFIG.chainId}`;
}

function propertyDescription(property: Property): string {
  const location = property.location || "its listed region";
  const rentNote = property.rent_enabled
    ? " It offers rental yield to token holders when rent is collected on-chain."
    : " Rental yield activates once the owner configures monthly rent.";
  return `${property.name} is a modern and stylish rental property located in ${location}.${rentNote} Invest via fractional ${property.token_symbol} security tokens on ${chainLabel()}.`;
}

function deriveFinancialOverview(property: Property) {
  const monthlyRent = Number(property.monthly_rent_eth ?? 0);
  const tokenPrice = Number(property.token_sale_price_eth ?? 0);
  const supply = Number(property.token_supply ?? 0);
  const navEth = tokenPrice > 0 && supply > 0 ? tokenPrice * supply : 0;
  const annualRentEth = monthlyRent > 0 ? monthlyRent * 12 : 0;

  if (!navEth || !annualRentEth) return null;

  const expectedRoi = (annualRentEth / navEth) * 100;
  const netYield = expectedRoi * 0.66;
  const paybackYears = navEth / annualRentEth;

  return {
    expectedRoi: `${expectedRoi.toFixed(1)}%`,
    netYield: `${netYield.toFixed(1)}%`,
    payback: `${paybackYears.toFixed(1)} Years`,
    occupancy: property.rent_enabled ? "90%+" : "—",
  };
}

export function InvestorPropertyDetailContent({ property }: { property: Property }) {
  const sold = Number(property.tokens_sold ?? 0);
  const supply = Number(property.token_supply ?? 0);
  const soldPct = Number(property.sold_percentage ?? percent(sold, supply));
  const tokenPrice = Number(property.token_sale_price_eth ?? 0);
  const monthlyRent = Number(property.monthly_rent_eth ?? 0);
  const available = availablePropertyTokens(property);
  const unitValue = propertyUnitValue(property);
  const rentReady = Boolean(property.rent_enabled && monthlyRent > 0);
  const financials = deriveFinancialOverview(property);

  return (
    <div className="space-y-2.5">
      <div className="flex items-start justify-between gap-2 pr-7">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-1.5">
            <h2 className="text-base font-semibold leading-tight tracking-tight text-foreground">
              #{property.id} {property.name}
            </h2>
            <Badge variant="outline" className="h-4 px-1.5 text-[9px] font-semibold uppercase tracking-wide">
              {property.token_symbol}
            </Badge>
          </div>
          <p className="mt-0.5 flex items-center gap-1 text-xs text-muted-foreground">
            <MapPin className="h-3 w-3 shrink-0" />
            {property.location || "—"}
          </p>
        </div>
        <Badge variant={rentReady ? "success" : "muted"} className="h-5 shrink-0 px-1.5 text-[10px]">
          {rentReady ? "Rent ready" : "Rent not set"}
        </Badge>
      </div>

      <PropertyImageGallery
        variant="compact"
        autoPlay
        images={property.images}
        propertyId={property.id}
        title={property.name}
      />

      <div className="rounded-lg border border-border bg-card p-3 shadow-sm">
        <div className="grid grid-cols-2 gap-x-4 gap-y-3 sm:grid-cols-3 lg:grid-cols-5">
          <DetailMetric
            label="Monthly rent"
            value={monthlyRent > 0 ? `${monthlyRent.toFixed(4)} ETH` : "—"}
          />
          <DetailMetric label="Property value" value={formatCurrency(property.total_value)} />
          <DetailMetric label="Supply" value={formatNumber(supply)} />
          <DetailMetric label="Ownership sold" value={`${soldPct.toFixed(1)}%`} />
          <DetailMetric
            label="Token price"
            value={tokenPrice > 0 ? `${tokenPrice.toFixed(4)} ETH` : "—"}
            subValue={unitValue > 0 ? `~${formatCurrency(unitValue)}` : undefined}
          />
        </div>
        <div className="mt-2.5 border-t border-border pt-2.5">
          <div className="mb-1 flex items-center justify-between text-[11px]">
            <span className="text-muted-foreground">Token sale progress</span>
            <span className="font-semibold tabular-nums text-foreground">
              {formatNumber(sold)} / {formatNumber(supply)}
            </span>
          </div>
          <Progress value={soldPct} className="h-1 bg-muted" indicatorClassName="bg-primary" />
        </div>
      </div>

      <PropertyInfoGrid property={property} financials={financials} available={available} />
    </div>
  );
}

function PropertyInfoGrid({
  property,
  financials,
  available,
}: {
  property: Property;
  financials: ReturnType<typeof deriveFinancialOverview>;
  available: number;
}) {
  const tokenStandard =
    property.nft_token_id != null ? "ERC-721" : property.token_address ? "ERC-20" : "—";
  const monthlyRent = Number(property.monthly_rent_eth ?? 0);

  return (
    <div className="grid gap-2 sm:grid-cols-2">
      <Panel title="Property description">
        <p className="text-xs leading-snug text-muted-foreground">
          {propertyDescription(property)}
        </p>
      </Panel>

      <Panel title="Property details">
        <Row label="Property type" value="Residential" />
        <Row label="Location" value={property.location || "—"} />
        <Row label="Token symbol" value={property.token_symbol} emphasize />
        <Row label="Total supply" value={formatNumber(property.token_supply)} />
        <Row label="Available tokens" value={formatNumber(available)} emphasize />
        <Row
          label="Monthly rent"
          value={monthlyRent > 0 ? `${monthlyRent.toFixed(4)} ETH` : "Not set"}
        />
      </Panel>

      <Panel title="Financial overview">
        {financials ? (
          <>
            <Row label="Expected ROI (annual)" value={financials.expectedRoi} emphasize />
            <Row label="Net yield (annual)" value={financials.netYield} emphasize />
            <Row label="Payback period" value={financials.payback} emphasize />
            <Row label="Target occupancy" value={financials.occupancy} emphasize />
          </>
        ) : (
          <p className="text-xs leading-snug text-muted-foreground">
            Configure monthly rent on this listing to display yield estimates.
          </p>
        )}
      </Panel>

      <Panel title="Smart contract">
        <CopyField
          label="Contract address"
          value={property.token_address}
          fallback="Pending deployment"
          explorer={property.token_address ? addressExplorerUrl(property.token_address) : undefined}
          linkStyle
        />
        <CopyField label="Token standard" value={tokenStandard} fullText copyValue={tokenStandard} />
        <CopyField
          label="Created by"
          value={property.owner_wallet}
          fallback="—"
          mono
          explorer={property.owner_wallet ? addressExplorerUrl(property.owner_wallet) : undefined}
          linkStyle
        />
        <Row
          label="Verified"
          value={
            property.token_address ? (
              <span className="inline-flex items-center gap-0.5 text-xs font-semibold text-success">
                <BadgeCheck className="h-3.5 w-3.5" /> Yes
              </span>
            ) : (
              "Pending"
            )
          }
        />
      </Panel>
    </div>
  );
}

export function InvestorPropertyDetailFooter({
  wallet,
  investable,
  disabled,
  onInvest,
}: {
  wallet?: string | null;
  investable: boolean;
  disabled?: boolean;
  onInvest: () => void;
}) {
  return (
    <div className="flex shrink-0 items-center justify-between gap-2 border-t border-border bg-card px-4 py-2">
      <span className="min-w-0 truncate font-mono text-[11px] text-muted-foreground">
        {wallet ? shortAddress(wallet, 6, 4) : "Wallet not connected"}
      </span>
      <Button
        type="button"
        size="sm"
        className="h-8 gap-1.5 rounded-md px-3 text-xs font-semibold shadow-sm"
        disabled={disabled || !investable}
        onClick={onInvest}
      >
        <Banknote className="h-3.5 w-3.5" />
        Invest
      </Button>
    </div>
  );
}

function DetailMetric({
  label,
  value,
  subValue,
  className,
}: {
  label: string;
  value: React.ReactNode;
  subValue?: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("min-w-0", className)}>
      <div className="text-[9px] font-semibold uppercase tracking-wide text-muted-foreground">{label}</div>
      <div className="mt-0.5 text-sm font-semibold leading-tight tabular-nums text-foreground">{value}</div>
      {subValue ? <div className="text-[11px] font-medium text-muted-foreground">{subValue}</div> : null}
    </div>
  );
}

function Panel({ title, children, className }: { title: string; children: React.ReactNode; className?: string }) {
  return (
    <div className={cn("rounded-lg border border-border bg-muted/20 p-2.5", className)}>
      <h3 className="text-xs font-semibold text-foreground">{title}</h3>
      <div className="mt-1.5 space-y-1.5">{children}</div>
    </div>
  );
}

function Row({
  label,
  value,
  emphasize,
}: {
  label: string;
  value: React.ReactNode;
  emphasize?: boolean;
}) {
  return (
    <div className="flex items-center justify-between gap-3 text-xs">
      <span className="text-muted-foreground">{label}</span>
      <span
        className={cn(
          "shrink-0 text-right font-medium text-foreground",
          emphasize && "font-semibold tabular-nums",
        )}
      >
        {value}
      </span>
    </div>
  );
}

function CopyField({
  label,
  value,
  fallback,
  explorer,
  mono,
  copyValue,
  fullText,
  linkStyle,
}: {
  label: string;
  value?: string | null;
  fallback?: string;
  explorer?: string;
  mono?: boolean;
  copyValue?: string | null;
  fullText?: boolean;
  linkStyle?: boolean;
}) {
  const [copied, setCopied] = useState(false);
  const raw = copyValue ?? value;
  const display = !raw
    ? fallback || "—"
    : fullText
      ? String(raw)
      : shortAddress(String(raw), 6, 4);

  async function copy() {
    if (!raw) return;
    try {
      await navigator.clipboard.writeText(raw);
      setCopied(true);
      toast.success("Copied");
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      toast.error("Could not copy");
    }
  }

  return (
    <div className="flex items-center justify-between gap-2 text-xs">
      <span className="shrink-0 text-muted-foreground">{label}</span>
      <div className="flex min-w-0 items-center gap-0.5">
        {explorer && raw ? (
          <a
            href={explorer}
            target="_blank"
            rel="noreferrer"
            className={cn(
              "font-medium hover:underline",
              linkStyle ? "text-primary" : "text-foreground",
              mono && "font-mono text-xs",
            )}
            onClick={(e) => e.stopPropagation()}
          >
            {display}
          </a>
        ) : (
          <span
            className={cn(
              "font-medium",
              linkStyle && raw ? "text-primary" : "text-foreground",
              mono && "font-mono text-xs",
            )}
          >
            {display}
          </span>
        )}
        {raw ? (
          <Button type="button" variant="ghost" size="icon" className="h-5 w-5 shrink-0" onClick={() => void copy()}>
            {copied ? <Check className="h-2.5 w-2.5 text-success" /> : <Copy className="h-2.5 w-2.5" />}
          </Button>
        ) : null}
      </div>
    </div>
  );
}
