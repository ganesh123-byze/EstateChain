"use client";

import { InvestorTopbar } from "@/components/investor/investor-topbar";
import { TransactionsTable } from "@/components/transactions/transactions-table";
import { useInvestorTransactions } from "@/lib/queries";
import { useCurrentWallet } from "@/components/investor/use-current-wallet";

export default function InvestorTransactionsPage() {
  const wallet = useCurrentWallet();
  const transactions = useInvestorTransactions(wallet);
  return (
    <>
      <InvestorTopbar title="Transactions" subtitle="Your wallet-scoped investment, yield, and claim activity" />
      <main className="flex-1 space-y-4 p-4 lg:p-6">
        <TransactionsTable
          transactions={transactions.data ?? []}
          loading={transactions.isLoading}
          showTypeFilter
        />
      </main>
    </>
  );
}
