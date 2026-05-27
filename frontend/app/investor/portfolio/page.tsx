"use client";

import { useMemo } from "react";
import { Building2, Coins, History, Wallet } from "lucide-react";
import { Cell, Pie, PieChart as RePieChart, ResponsiveContainer, Tooltip } from "recharts";
import { motion } from "framer-motion";
import { InvestorTopbar } from "@/components/investor/investor-topbar";
import { InvestorKpiCard } from "@/components/investor/investor-kpi-card";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/common/empty";
import { InvestmentSimulationWorkbench } from "@/components/investor/investment-simulation-workbench";
import { useInvestorYieldSummary, usePortfolio, useProperties, useWalletBalances } from "@/lib/queries";
import { cn, formatCurrency, shortAddress } from "@/lib/utils";
import { pickColor } from "@/lib/charts";
import { buildInvestorMetrics, holdingValue, humanTokenAmount, ownershipPercent } from "@/components/investor/investor-utils";
import { useCurrentWallet } from "@/components/investor/use-current-wallet";

export default function InvestorPortfolioPage() {
  const wallet = useCurrentWallet();
  const properties = useProperties();
  const portfolio = usePortfolio(wallet);
  const yieldSummary = useInvestorYieldSummary(wallet);
  const balances = useWalletBalances(wallet);
  const holdings = portfolio.data?.holdings ?? [];
  const propertyMap = useMemo(() => new Map((properties.data ?? []).map((p) => [Number(p.id), p])), [properties.data]);
  const metrics = buildInvestorMetrics(holdings, properties.data ?? []);
  const chartData = holdings.map((h) => {
    const property = propertyMap.get(Number(h.property_id));
    return {
      id: h.property_id,
      name: h.property_name.length > 18 ? `${h.property_name.slice(0, 16)}…` : h.property_name,
      value: holdingValue(h, property),
    };
  }).filter((item) => item.value > 0);

  const simulationSlices = useMemo(
    () => chartData.filter((c) => c.value > 0).map((c) => ({ id: c.id, name: c.name, value: c.value })),
    [chartData],
  );

  return (
    <>
      <InvestorTopbar title="Portfolio" subtitle="Token holdings, ownership percentages, and wallet balances" />
      <main className="flex-1 space-y-4 p-4 lg:p-6">
        <section className="grid grid-cols-2 gap-1.5 sm:grid-cols-2 xl:grid-cols-4">
          <InvestorKpiCard
            title="Estimated Value"
            value={formatCurrency(metrics.estimatedValue)}
            icon={Wallet}
            variant="violet"
            loading={properties.isLoading || portfolio.isLoading}
          />
          <InvestorKpiCard
            title="Properties Owned"
            value={String(metrics.propertiesOwned)}
            icon={Building2}
            variant="mint"
            loading={portfolio.isLoading}
          />
          <InvestorKpiCard
            title="Total Earned"
            value={`${yieldSummary.data?.total_earned_eth ?? "0"} ETH`}
            icon={Coins}
            variant="sky"
            loading={yieldSummary.isLoading}
          />
          <InvestorKpiCard
            title="Payout Records"
            value={String(yieldSummary.data?.total_payouts ?? 0)}
            icon={History}
            variant="periwinkle"
            loading={yieldSummary.isLoading}
          />
        </section>

        <section className="grid grid-cols-1 gap-4 xl:grid-cols-[0.72fr_1.28fr]">
          <Card>
            <CardHeader>
              <CardTitle>Allocation</CardTitle>
              <CardDescription>Estimated value share by property.</CardDescription>
            </CardHeader>
            <CardContent>
              {portfolio.isLoading || properties.isLoading ? (
                <Skeleton className="h-[260px] w-full" />
              ) : chartData.length === 0 ? (
                <div className="grid h-[260px] place-items-center text-sm text-muted-foreground">No holdings yet.</div>
              ) : (
                <>
                  <ResponsiveContainer width="100%" height={220}>
                    <RePieChart>
                      <Pie data={chartData} dataKey="value" nameKey="name" cx="50%" cy="50%" innerRadius={58} outerRadius={86} paddingAngle={2} stroke="hsl(var(--card))" strokeWidth={2}>
                        {chartData.map((item, index) => <Cell key={item.id} fill={pickColor(index)} />)}
                      </Pie>
                      <Tooltip contentStyle={{ background: "hsl(var(--popover))", border: "1px solid hsl(var(--border))", borderRadius: 8, fontSize: 12 }} formatter={(v: number) => [formatCurrency(v), "Value"]} />
                    </RePieChart>
                  </ResponsiveContainer>
                  <div className="space-y-1.5">
                    {chartData.map((item, index) => (
                      <div key={item.id} className="flex items-center justify-between text-xs">
                        <div className="flex items-center gap-2"><span className="h-2 w-2 rounded-full" style={{ background: pickColor(index) }} /> {item.name}</div>
                        <span className="tabular-nums text-muted-foreground">{formatCurrency(item.value)}</span>
                      </div>
                    ))}
                  </div>
                </>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Holdings</CardTitle>
              <CardDescription>Ownership positions reconciled from SecurityToken balances.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              {portfolio.isLoading || properties.isLoading ? (
                Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} className="h-20 w-full" />)
              ) : holdings.length === 0 ? (
                <EmptyState title="No property tokens yet" description="Your purchased ownership tokens will appear here after confirmation." />
              ) : (
                holdings.map((holding) => {
                  const property = propertyMap.get(Number(holding.property_id));
                  const pct = ownershipPercent(holding, property);
                  const value = holdingValue(holding, property);
                  return (
                    <div key={holding.property_id} className="rounded-xl border border-border bg-card p-4">
                      <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                        <div className="min-w-0">
                          <div className="flex flex-wrap items-center gap-2">
                            <h3 className="truncate text-sm font-semibold">{holding.property_name}</h3>
                            <Badge variant="outline" className="rounded-md">{property?.token_symbol ?? "TOKEN"}</Badge>
                          </div>
                          <p className="mt-1 text-xs text-muted-foreground">{property?.location ?? `Property #${holding.property_id}`}</p>
                        </div>
                        <div className="grid grid-cols-2 gap-3 text-right text-xs md:min-w-[280px]">
                          <Fact label="Tokens" value={humanTokenAmount(holding.token_amount)} />
                          <Fact label="Est. value" value={formatCurrency(value)} />
                          <Fact label="Ownership" value={`${pct.toFixed(4)}%`} />
                          <Fact label="Token" value={shortAddress(property?.token_address, 6, 4)} />
                        </div>
                      </div>
                      <Progress value={Math.min(pct, 100)} className="mt-3 h-1.5" indicatorClassName={cn(pct > 1 ? "bg-success" : "bg-primary")} />
                    </div>
                  );
                })
              )}
            </CardContent>
          </Card>
        </section>

        {simulationSlices.length > 1 ? (
          <motion.section
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.35, ease: [0.22, 1, 0.36, 1] }}
          >
            <InvestmentSimulationWorkbench
              slices={simulationSlices}
              totalValue={metrics.estimatedValue}
              loading={portfolio.isLoading || properties.isLoading}
            />
          </motion.section>
        ) : null}

        <Card>
          <CardHeader>
            <CardTitle>Wallet Tokens</CardTitle>
            <CardDescription>Live token balances read from deployed property contracts.</CardDescription>
          </CardHeader>
          <CardContent className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
            {balances.isLoading ? (
              Array.from({ length: 3 }).map((_, i) => <Skeleton key={i} className="h-20 w-full" />)
            ) : (balances.data?.tokens ?? []).length === 0 ? (
              <div className="md:col-span-2 xl:col-span-3"><EmptyState title="No token balances" /></div>
            ) : (
              (balances.data?.tokens ?? []).map((token) => (
                <div key={`${token.token_address}-${token.property_id}`} className="rounded-lg border border-border bg-muted/20 p-3">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="text-sm font-medium">{token.property_name}</div>
                      <div className="mt-1 font-mono text-[11px] text-muted-foreground">{shortAddress(token.token_address, 6, 4)}</div>
                    </div>
                    <Badge variant="muted">{token.symbol}</Badge>
                  </div>
                  <div className="mt-3 text-lg font-semibold tabular-nums">{Number(token.balance ?? 0).toLocaleString("en-US", { maximumFractionDigits: 4 })}</div>
                </div>
              ))
            )}
          </CardContent>
        </Card>
      </main>
    </>
  );
}

function Fact({ label, value }: { label: string; value: React.ReactNode }) {
  return <div><div className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">{label}</div><div className="font-medium tabular-nums">{value}</div></div>;
}
