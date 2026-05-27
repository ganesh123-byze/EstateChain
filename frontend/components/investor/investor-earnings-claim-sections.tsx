"use client";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/common/empty";
import { useClaimHistory, useInvestorDistributions } from "@/lib/queries";
import { formatDateTime, shortAddress } from "@/lib/utils";
import { txExplorerUrl } from "@/lib/runtime-config";
import { useCurrentWallet } from "@/components/investor/use-current-wallet";

export function InvestorEarningsAndClaimSections() {
  const wallet = useCurrentWallet();
  const distributions = useInvestorDistributions(wallet);
  const history = useClaimHistory(wallet);

  return (
    <section className="grid grid-cols-1 gap-4 xl:grid-cols-2">
      <Card>
        <CardHeader>
          <CardTitle>Earnings by Property</CardTitle>
          <CardDescription>Aggregated rental accruals per property.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-2">
          {distributions.isLoading ? (
            Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-14 w-full" />)
          ) : (distributions.data ?? []).length === 0 ? (
            <EmptyState title="No earnings yet" />
          ) : (
            (distributions.data ?? []).map((row) => (
              <div
                key={row.property_id}
                className="flex items-center justify-between rounded-lg border border-border bg-muted/20 px-3 py-2"
              >
                <div>
                  <div className="text-sm font-medium">{row.property_name ?? `Property #${row.property_id}`}</div>
                  <div className="text-xs text-muted-foreground">
                    {row.payment_count} payments · {row.current_ownership}% ownership
                  </div>
                </div>
                <div className="text-sm font-semibold tabular-nums">{row.total_earned_eth} ETH</div>
              </div>
            ))
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Claim History</CardTitle>
          <CardDescription>Completed withdrawal transactions.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-2">
          {history.isLoading ? (
            Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-14 w-full" />)
          ) : (history.data ?? []).length === 0 ? (
            <EmptyState title="No claims yet" />
          ) : (
            (history.data ?? []).map((claim) => (
              <a
                key={claim.claim_tx_hash}
                href={txExplorerUrl(claim.claim_tx_hash)}
                target="_blank"
                rel="noreferrer"
                className="flex items-center justify-between rounded-lg border border-border bg-muted/20 px-3 py-2 transition-colors hover:bg-muted"
              >
                <div>
                  <div className="text-sm font-medium">{claim.property_name ?? `Property #${claim.property_id}`}</div>
                  <div className="text-xs text-muted-foreground">
                    {claim.payout_count} payout rows · {formatDateTime(claim.claimed_at)} ·{" "}
                    {shortAddress(claim.claim_tx_hash, 7, 5)}
                  </div>
                </div>
                <div className="text-sm font-semibold tabular-nums text-success">{claim.claimed_amount_eth} ETH</div>
              </a>
            ))
          )}
        </CardContent>
      </Card>
    </section>
  );
}
