"use client";

import { useEffect, useMemo, useState } from "react";
import { ArrowUpRight, Search } from "lucide-react";
import { InvestorTopbar } from "@/components/investor/investor-topbar";
import { InvestorInvestDialog } from "@/components/investor/investor-invest-dialog";
import { PropertyDetailDialog } from "@/components/properties/property-detail-dialog";
import { PropertyListingCard } from "@/components/properties/property-listing-card";
import { availablePropertyTokens, propertyIsInvestable } from "@/components/investor/investor-utils";
import { useCurrentWallet } from "@/components/investor/use-current-wallet";
import { EmptyState } from "@/components/common/empty";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { useProperties } from "@/lib/queries";
import type { Property } from "@/lib/types";
import {
  isWorkflowModalAction,
  subscribeWorkflowAction,
  takePendingModalOpen,
  workflowPropertyMatches,
} from "@/lib/ai/action-executor";

export default function InvestorMarketplacePage() {
  const wallet = useCurrentWallet();
  const properties = useProperties();
  const [search, setSearch] = useState("");
  const investable = useMemo(
    () =>
      (properties.data ?? []).filter((p) => {
        const q = search.trim().toLowerCase();
        return !q || p.name.toLowerCase().includes(q) || (p.location || "").toLowerCase().includes(q);
      }),
    [properties.data, search],
  );

  return (
    <>
      <InvestorTopbar title="Marketplace" subtitle="Browse tokenized properties and invest with MetaMask" />
      <main className="flex-1 space-y-4 p-4 lg:p-6">
        <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
          <div>
            <h2 className="text-sm font-medium">Available opportunities</h2>
            <p className="text-xs text-muted-foreground">
              Primary sales are executed directly against each property SecurityToken contract.
            </p>
          </div>
          <div className="relative w-full md:w-72">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search properties…"
              className="h-9 pl-8 text-sm"
            />
          </div>
        </div>

        {properties.isLoading ? (
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
            {Array.from({ length: 6 }).map((_, i) => (
              <Skeleton key={i} className="h-[420px] rounded-xl" />
            ))}
          </div>
        ) : investable.length === 0 ? (
          <EmptyState title="No properties found" description="Try a different search term or wait for new listings." />
        ) : (
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
            {investable.map((property) => (
              <MarketplaceCard key={property.id} property={property} wallet={wallet} />
            ))}
          </div>
        )}
      </main>
    </>
  );
}

function MarketplaceCard({ property, wallet }: { property: Property; wallet: string | null }) {
  const investable = propertyIsInvestable(property);
  const rentReady = Boolean(property.rent_enabled && Number(property.monthly_rent_eth ?? 0) > 0);
  const [detailOpen, setDetailOpen] = useState(false);
  const [investOpen, setInvestOpen] = useState(false);

  useEffect(() => {
    if (takePendingModalOpen("INVEST_PROPERTY", property.id)) {
      setDetailOpen(true);
      setInvestOpen(true);
    }
    return subscribeWorkflowAction((action) => {
      if (!isWorkflowModalAction(action, "INVEST_PROPERTY")) return;
      if (action.type === "OPEN_MODAL" && workflowPropertyMatches(action, property.id)) {
        setDetailOpen(true);
        setInvestOpen(true);
      }
    });
  }, [property.id]);

  return (
    <>
      <PropertyListingCard
        property={property}
        onClick={() => setDetailOpen(true)}
        statusLabel={investable ? "Open" : rentReady ? "Rent ready" : "Closed"}
        statusVariant={investable || rentReady ? "success" : "warning"}
        actionLabel="Invest"
        actionIcon={<ArrowUpRight className="h-3.5 w-3.5" />}
        actionDisabled={!wallet || !investable}
        onActionClick={() => {
          setDetailOpen(false);
          setInvestOpen(true);
        }}
      />

      <PropertyDetailDialog
        property={property}
        open={detailOpen}
        onOpenChange={setDetailOpen}
        role="investor"
        wallet={wallet}
        onPrimaryAction={() => setInvestOpen(true)}
        primaryDisabled={!wallet || !investable}
      />
      <InvestorInvestDialog property={property} wallet={wallet} open={investOpen} onOpenChange={setInvestOpen} />
    </>
  );
}
