"use client";

import { useState } from "react";
import { BadgeCheck, Check, Copy, MapPin, Pencil, Receipt } from "lucide-react";
import { toast } from "sonner";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import {
  InvestorPropertyDetailContent,
  InvestorPropertyDetailFooter,
} from "@/components/investor/investor-property-detail-content";
import {
  investorPropertyDetailDialogClass,
  investorPropertyDetailScrollBodyClass,
  propertyDetailScrollBodyClass,
} from "@/components/properties/property-form-shared";
import { PropertyImageGallery } from "@/components/properties/property-image-gallery";
import { availablePropertyTokens, propertyIsInvestable, propertyUnitValue } from "@/components/investor/investor-utils";
import { useProperty } from "@/lib/queries";
import { addressExplorerUrl, RUNTIME_CONFIG } from "@/lib/runtime-config";
import type { Property, Role } from "@/lib/types";
import { cn, formatCurrency, formatDateTime, formatNumber, percent, shortAddress } from "@/lib/utils";

export type PropertyDetailRole = Role;

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
    ? " Rental yield is distributed on-chain to token holders when rent is collected."
    : " Rent distribution can be enabled once the owner configures monthly rent on-chain.";
  return `${property.name} is a tokenized real estate listing in ${location}. Ownership is represented by ${property.token_symbol} security tokens on ${chainLabel()}.${rentNote}`;
}

export function PropertyDetailDialog({
  property: initialProperty,
  open,
  onOpenChange,
  role,
  wallet,
  onPrimaryAction,
  primaryDisabled,
  isActiveRental,
}: {
  property: Property | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  role: PropertyDetailRole;
  wallet?: string | null;
  onPrimaryAction?: () => void;
  primaryDisabled?: boolean;
  isActiveRental?: boolean;
}) {
  const propertyQuery = useProperty(open ? initialProperty?.id : null);
  const property = propertyQuery.data ?? initialProperty;
  const loading = propertyQuery.isLoading && !property;
  const isInvestor = role === "investor";

  if (!initialProperty && !open) return null;

  const sold = Number(property?.tokens_sold ?? 0);
  const supply = Number(property?.token_supply ?? 0);
  const soldPct = Number(property?.sold_percentage ?? percent(sold, supply));
  const tokenPrice = Number(property?.token_sale_price_eth ?? 0);
  const monthlyRent = Number(property?.monthly_rent_eth ?? 0);
  const available = property ? availablePropertyTokens(property) : 0;
  const investable = property ? propertyIsInvestable(property) : false;
  const unitValue = propertyUnitValue(property);
  const rentReady = Boolean(property?.rent_enabled && monthlyRent > 0);

  const primaryLabel =
    role === "tenant"
      ? property?.current_cycle_paid
        ? "Rent paid"
        : "Pay rent"
      : "Edit property";

  const primaryIcon = role === "tenant" ? Receipt : Pencil;

  const footerHint =
    role === "tenant"
      ? property?.current_cycle_paid
        ? property.next_rent_due_at
          ? `Next rent due ${formatDateTime(property.next_rent_due_at)}.`
          : "Rent is paid for the current cycle."
        : rentReady
          ? "Pay rent via MetaMask to the RentDistribution contract."
          : "Rent has not been configured for this property."
      : "Update listing details, images, and pricing from the admin panel.";

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className={
          isInvestor
            ? investorPropertyDetailDialogClass
            : cn(
                "flex min-h-0 max-h-[min(92vh,920px)] flex-col gap-0 overflow-hidden p-0 sm:max-w-lg sm:rounded-2xl",
              )
        }
      >
        {loading || !property ? (
          <div
            className={cn(
              isInvestor ? investorPropertyDetailScrollBodyClass : propertyDetailScrollBodyClass,
              "space-y-4 p-6",
            )}
          >
            <Skeleton className="aspect-[16/10] w-full rounded-xl" />
            <Skeleton className="h-6 w-2/3" />
            <Skeleton className="h-32 w-full" />
          </div>
        ) : isInvestor ? (
          <>
            <div className={cn(investorPropertyDetailScrollBodyClass, "px-4 py-3.5")}>
              <InvestorPropertyDetailContent property={property} />
            </div>
            {onPrimaryAction ? (
              <InvestorPropertyDetailFooter
                wallet={wallet}
                investable={investable}
                disabled={primaryDisabled}
                onInvest={() => {
                  onOpenChange(false);
                  onPrimaryAction();
                }}
              />
            ) : null}
          </>
        ) : (
          <>
            <div className={propertyDetailScrollBodyClass}>
              <div className="p-5 pb-4">
                <DialogHeader className="space-y-3 p-0 text-left">
                  <div className="flex flex-wrap items-start justify-between gap-2 pr-6">
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <DialogTitle className="text-lg font-semibold leading-tight">
                          #{property.id} {property.name}
                        </DialogTitle>
                        <Badge variant="outline" className="font-mono text-[10px]">
                          {property.token_symbol}
                        </Badge>
                      </div>
                      <div className="mt-1.5 flex flex-wrap items-center gap-2">
                        {rentReady ? (
                          <Badge variant="success" className="text-[10px]">
                            Rent ready
                          </Badge>
                        ) : (
                          <Badge variant="muted" className="text-[10px]">
                            Rent not set
                          </Badge>
                        )}
                        {isActiveRental ? (
                          <Badge variant="outline" className="text-[10px]">
                            Active rental
                          </Badge>
                        ) : null}
                      </div>
                      <p className="mt-1 flex items-center gap-1 text-xs text-muted-foreground">
                        <MapPin className="h-3 w-3 shrink-0" />
                        {property.location || "—"}
                      </p>
                    </div>
                  </div>
                </DialogHeader>

                <div className="mt-4">
                  <PropertyImageGallery
                    images={property.images}
                    propertyId={property.id}
                    title={property.name}
                  />
                </div>

                <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-4">
                  <StatPill
                    label="Monthly rent"
                    value={monthlyRent > 0 ? `${monthlyRent.toFixed(4)} ETH` : "—"}
                  />
                  <StatPill label="Property value" value={formatCurrency(property.total_value)} />
                  <StatPill label="Supply" value={formatNumber(supply)} />
                  <StatPill label="Ownership sold" value={`${soldPct.toFixed(1)}%`} />
                </div>

                <div className="mt-3 rounded-lg border border-border bg-muted/20 px-3 py-2.5">
                  <div className="mb-1.5 flex items-center justify-between text-[11px]">
                    <span className="text-muted-foreground">Token sale progress</span>
                    <span className="font-semibold tabular-nums">
                      {formatNumber(sold)} / {formatNumber(supply)}
                    </span>
                  </div>
                  <Progress value={soldPct} className="h-1.5" />
                </div>

                <div className="mt-4 grid gap-3 sm:grid-cols-2">
                  <InfoCard title="Property description">
                    <p className="text-xs leading-relaxed text-muted-foreground">
                      {propertyDescription(property)}
                    </p>
                  </InfoCard>

                  <InfoCard title="Property details">
                    <InfoRow label="Listing ID" value={`#${property.id}`} />
                    <InfoRow label="Token symbol" value={property.token_symbol} />
                    <InfoRow label="Token price" value={`${tokenPrice.toFixed(4)} ETH`} />
                    <InfoRow label="Per-token value" value={formatCurrency(unitValue)} />
                    <InfoRow label="Available tokens" value={formatNumber(available)} />
                    <InfoRow
                      label="Rent program"
                      value={property.rent_enabled ? "Enabled" : "Disabled"}
                    />
                  </InfoCard>

                  <InfoCard title="Payment information">
                    <InfoRow label="Payment currency" value="ETH" />
                    <InfoRow label="Payment network" value={chainLabel()} />
                    <InfoRow
                      label="Monthly rent"
                      value={monthlyRent > 0 ? `${monthlyRent.toFixed(4)} ETH` : "Not configured"}
                    />
                    <InfoRow
                      label="Billing cycle"
                      value={property.rent_cycle_label || "Monthly in advance"}
                    />
                    <InfoRow
                      label="Cycle status"
                      value={
                        property.current_cycle_paid ? "Paid" : property.can_pay_rent ? "Due" : "—"
                      }
                    />
                  </InfoCard>

                  <InfoCard title="Smart contract">
                    <CopyRow
                      label="Security token"
                      value={property.token_address}
                      fallback="Pending deployment"
                      explorer={
                        property.token_address ? addressExplorerUrl(property.token_address) : undefined
                      }
                    />
                    <InfoRow
                      label="Property NFT"
                      value={property.nft_token_id != null ? `#${property.nft_token_id}` : "Not minted"}
                    />
                    <InfoRow label="Token standard" value="ERC-20 SecurityToken" />
                    <CopyRow label="Created by" value={property.owner_wallet} fallback="—" mono />
                    <InfoRow
                      label="Verified on-chain"
                      value={
                        property.token_address ? (
                          <span className="inline-flex items-center gap-1 text-success">
                            <BadgeCheck className="h-3.5 w-3.5" /> Yes
                          </span>
                        ) : (
                          "Pending"
                        )
                      }
                    />
                  </InfoCard>
                </div>
              </div>
            </div>

            <Separator />

            <DialogFooter className="flex shrink-0 flex-col gap-2 border-t border-border bg-card/95 px-5 py-3 sm:flex-row sm:items-center sm:justify-between">
              <p className="text-left text-[11px] leading-snug text-muted-foreground sm:max-w-[55%]">
                {footerHint}
              </p>
              <div className="flex w-full shrink-0 gap-2 sm:w-auto">
                <Button type="button" variant="outline" size="sm" onClick={() => onOpenChange(false)}>
                  Close
                </Button>
                {onPrimaryAction ? (
                  <Button
                    type="button"
                    size="sm"
                    disabled={primaryDisabled}
                    onClick={() => {
                      onOpenChange(false);
                      onPrimaryAction();
                    }}
                  >
                    {primaryLabel}
                    {(() => {
                      const Icon = primaryIcon;
                      return <Icon className="h-3.5 w-3.5" />;
                    })()}
                  </Button>
                ) : null}
              </div>
            </DialogFooter>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}

function StatPill({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-border bg-card px-2.5 py-2 text-center shadow-sm">
      <div className="text-[9px] font-semibold uppercase tracking-wide text-muted-foreground">{label}</div>
      <div className="mt-0.5 truncate text-xs font-semibold tabular-nums">{value}</div>
    </div>
  );
}

function InfoCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-border bg-card p-3 shadow-sm">
      <h4 className="text-xs font-semibold text-foreground">{title}</h4>
      <div className="mt-2 space-y-1.5">{children}</div>
    </div>
  );
}

function InfoRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-3 text-xs">
      <span className="shrink-0 text-muted-foreground">{label}</span>
      <span className="text-right font-medium text-foreground">{value}</span>
    </div>
  );
}

function CopyRow({
  label,
  value,
  fallback,
  explorer,
  mono,
}: {
  label: string;
  value?: string | null;
  fallback: string;
  explorer?: string;
  mono?: boolean;
}) {
  const [copied, setCopied] = useState(false);
  const display = value ? shortAddress(value, 8, 6) : fallback;

  async function copy() {
    if (!value) return;
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      toast.success("Copied to clipboard");
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      toast.error("Could not copy");
    }
  }

  return (
    <div className="flex items-center justify-between gap-2 text-xs">
      <span className="text-muted-foreground">{label}</span>
      <div className="flex min-w-0 items-center gap-1">
        {explorer ? (
          <a
            href={explorer}
            target="_blank"
            rel="noreferrer"
            className={cn("truncate font-medium text-primary hover:underline", mono && "font-mono")}
            onClick={(e) => e.stopPropagation()}
          >
            {display}
          </a>
        ) : (
          <span className={cn("truncate font-medium", mono && "font-mono")}>{display}</span>
        )}
        {value ? (
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="h-6 w-6 shrink-0"
            onClick={(e) => {
              e.stopPropagation();
              void copy();
            }}
          >
            {copied ? <Check className="h-3 w-3 text-success" /> : <Copy className="h-3 w-3" />}
          </Button>
        ) : null}
      </div>
    </div>
  );
}
