"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { ArrowUpRight, Building2, LineChart } from "lucide-react";
import { InvestorTopbar } from "@/components/investor/investor-topbar";
import { InvestorKpiCard } from "@/components/investor/investor-kpi-card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import {
  useClaimableRewards,
  useInvestorTransactions,
  useInvestorYieldSummary,
  usePortfolio,
  useProperties,
  useWalletBalances,
} from "@/lib/queries";
import { cn, formatDateTime, formatEth, formatNumber } from "@/lib/utils";
import { txExplorerUrl } from "@/lib/runtime-config";
import {
  InvestorClaimDialog,
  useInvestorClaimRewardsListener,
} from "@/components/investor/investor-claim-dialog";
import { InvestorEarningsAndClaimSections } from "@/components/investor/investor-earnings-claim-sections";
import type { ClaimableRewardProperty } from "@/lib/types";
import { buildInvestorMetrics, humanTokenAmount, ownershipPercent } from "@/components/investor/investor-utils";
import { useCurrentWallet } from "@/components/investor/use-current-wallet";

export default function InvestorDashboardPage() {
  const wallet = useCurrentWallet();
  const properties = useProperties();
  const portfolio = usePortfolio(wallet);
  const balances = useWalletBalances(wallet);
  const yieldSummary = useInvestorYieldSummary(wallet);
  const claimable = useClaimableRewards(wallet);
  const transactions = useInvestorTransactions(wallet);

  const propertyMap = useMemo(
    () => new Map((properties.data ?? []).map((p) => [Number(p.id), p])),
    [properties.data],
  );
  const metrics = useMemo(
    () => buildInvestorMetrics(portfolio.data?.holdings ?? [], properties.data ?? []),
    [portfolio.data?.holdings, properties.data],
  );
  const loading = properties.isLoading || portfolio.isLoading;
  const holdings = portfolio.data?.holdings ?? [];
  const claimableProperties = claimable.data?.properties ?? [];
  const nextClaim = claimableProperties[0];
  const [selectedClaim, setSelectedClaim] = useState<ClaimableRewardProperty | null>(null);
  useInvestorClaimRewardsListener(claimableProperties, setSelectedClaim);

  return (
    <>
      <InvestorTopbar
        title="Investor Dashboard"
        subtitle="Your holdings, yield, wallet health, and latest on-chain activity"
      />
      <main className="flex-1 space-y-4 p-4 lg:p-6">
        <section className="grid grid-cols-2 gap-1.5">
          <InvestorKpiCard
            title="Tokens Held"
            value={formatNumber(metrics.totalTokens, 4)}
            icon={Building2}
            variant="violet"
            loading={loading}
          />
          <InvestorKpiCard
            title="Wallet Balance"
            value={formatEth(balances.data?.native?.balance ?? "0", { digits: 4 })}
            icon={LineChart}
            variant="mint"
            loading={balances.isLoading}
          />
        </section>

        <section className="grid grid-cols-1 gap-4 xl:grid-cols-[1.35fr_0.65fr]">
          <Card className="overflow-hidden">
            <CardHeader className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
              <div>
                <CardTitle>Portfolio at a Glance</CardTitle>
                <CardDescription>Estimated ownership value from indexed token balances.</CardDescription>
              </div>
              <Button asChild size="sm" variant="outline">
                <Link href="/investor/portfolio">Open Portfolio <ArrowUpRight className="h-3.5 w-3.5" /></Link>
              </Button>
            </CardHeader>
            <CardContent className="space-y-3">
              {loading ? (
                Array.from({ length: 3 }).map((_, i) => <Skeleton key={i} className="h-16 w-full" />)
              ) : holdings.length === 0 ? (
                <div className="grid min-h-[210px] place-items-center rounded-lg border border-dashed border-border text-center">
                  <div className="max-w-sm px-6">
                    <div className="text-sm font-medium">No holdings yet</div>
                    <p className="mt-1 text-xs text-muted-foreground">Browse the marketplace and purchase property tokens to start earning rental yield.</p>
                    <Button asChild size="sm" className="mt-4">
                      <Link href="/investor/marketplace">Explore Marketplace</Link>
                    </Button>
                  </div>
                </div>
              ) : (
                holdings.slice(0, 4).map((holding) => {
                  const property = propertyMap.get(Number(holding.property_id));
                  const pct = ownershipPercent(holding, property);
                  return (
                    <div key={holding.property_id} className="rounded-lg border border-border bg-muted/20 p-3">
                      <div className="flex items-start justify-between gap-3">
                        <div>
                          <div className="text-sm font-medium">{holding.property_name}</div>
                          <div className="mt-0.5 text-xs text-muted-foreground">{property?.location ?? `Property #${holding.property_id}`}</div>
                        </div>
                        <div className="text-right">
                          <div className="text-sm font-semibold">{humanTokenAmount(holding.token_amount)} {property?.token_symbol ?? "TOKENS"}</div>
                          <div className="text-xs text-muted-foreground">{pct.toFixed(3)}% ownership</div>
                        </div>
                      </div>
                      <Progress value={Math.min(pct, 100)} className="mt-3 h-1.5" />
                    </div>
                  );
                })
              )}
            </CardContent>
          </Card>

          <Card className="relative overflow-hidden">
            <div className="pointer-events-none absolute -right-20 -top-24 h-48 w-48 rounded-full bg-primary/20 blur-3xl" />
            <CardHeader>
              <CardTitle>Yield Center</CardTitle>
              <CardDescription>Claimable rental rewards from the RentDistribution contract.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div>
                <div className="text-3xl font-semibold tracking-tight">{claimable.data?.total_claimable_eth ?? "0"} ETH</div>
                <div className="mt-1 text-xs text-muted-foreground">
                  Total claimed: {claimable.data?.total_claimed_eth ?? yieldSummary.data?.total_claimed_eth ?? "0"} ETH
                </div>
              </div>
              {nextClaim ? (
                <div className="rounded-lg border border-border bg-card p-3">
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <div className="text-sm font-medium">{nextClaim.property_name ?? `Property #${nextClaim.property_id}`}</div>
                      <div className="text-xs text-muted-foreground">{nextClaim.pending_payouts} pending accruals</div>
                    </div>
                    <Badge variant="success">{nextClaim.claimable_amount_eth} ETH</Badge>
                  </div>
                </div>
              ) : (
                <div className="rounded-lg border border-dashed border-border p-3 text-xs text-muted-foreground">
                  No claimable rewards yet.
                </div>
              )}
              <Button
                className="w-full"
                disabled={!nextClaim}
                onClick={() => nextClaim && setSelectedClaim(nextClaim)}
              >
                Claim rewards
              </Button>
            </CardContent>
          </Card>
        </section>

        <InvestorEarningsAndClaimSections />

        <Card>
            <CardHeader className="flex flex-row items-start justify-between gap-4">
              <div>
                <CardTitle>Recent Activity</CardTitle>
                <CardDescription>Your latest indexed Sepolia transactions.</CardDescription>
              </div>
              <Button asChild size="sm" variant="outline">
                <Link href="/investor/transactions">View All</Link>
              </Button>
            </CardHeader>
            <CardContent className="space-y-2">
              {transactions.isLoading ? (
                Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-12 w-full" />)
              ) : (transactions.data ?? []).length === 0 ? (
                <div className="grid h-[210px] place-items-center text-sm text-muted-foreground">No activity yet.</div>
              ) : (
                (transactions.data ?? []).slice(0, 5).map((tx) => (
                  <a key={tx.tx_hash} href={txExplorerUrl(tx.tx_hash)} target="_blank" rel="noreferrer" className="flex items-center justify-between gap-3 rounded-lg border border-border bg-muted/20 px-3 py-2 transition-colors hover:bg-muted">
                    <div className="min-w-0">
                      <div className="truncate text-sm font-medium">{tx.action_label}</div>
                      <div className="text-xs text-muted-foreground">{tx.property_name ?? "Platform"} · {formatDateTime(tx.timestamp)}</div>
                    </div>
                    <div className={cn("text-right text-xs font-medium", tx.type === "REWARDS_CLAIMED" ? "text-success" : "text-foreground")}>{tx.display_amount} {tx.amount_unit}</div>
                  </a>
                ))
              )}
            </CardContent>
        </Card>
      </main>
      <InvestorClaimDialog wallet={wallet} reward={selectedClaim} onClose={() => setSelectedClaim(null)} />
    </>
  );
}

