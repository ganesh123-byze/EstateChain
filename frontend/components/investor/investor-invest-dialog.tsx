"use client";

import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { CheckCircle2, ShieldCheck, Wallet } from "lucide-react";
import { api } from "@/lib/api";
import { queryKeys } from "@/lib/queries";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { cn, formatNumber, shortAddress } from "@/lib/utils";
import type { InvestmentPrepareResponse, Property } from "@/lib/types";
import { investmentCostWei } from "@/components/investor/investor-utils";
import { sendInvestmentTx } from "@/components/investor/contract-actions";
import {
  emitWorkflowCompletion,
  focusWorkflowField,
  isWorkflowModalAction,
  preventCloseFromWorkflowBubble,
  subscribeWorkflowAction,
  workflowPropertyMatches,
} from "@/lib/ai/action-executor";

export function InvestorInvestDialog({
  property,
  wallet,
  open,
  onOpenChange,
}: {
  property: Property;
  wallet: string | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const queryClient = useQueryClient();
  const formRef = useRef<HTMLFormElement | null>(null);
  const [amount, setAmount] = useState("1");
  const [step, setStep] = useState<"idle" | "prepare" | "wallet" | "confirm">("idle");
  const [busy, setBusy] = useState(false);
  const tokenAmount = Math.max(0, Math.trunc(Number(amount || 0)));
  const costWei = investmentCostWei(property, tokenAmount);
  const costEth = Number(costWei) / 1e18;

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (!wallet || !property.token_address || tokenAmount <= 0) return;
    setBusy(true);
    try {
      setStep("prepare");
      const prepared = await api.post<InvestmentPrepareResponse>("/investments/prepare", {
        property_id: property.id,
        investor_wallet: wallet,
        token_amount: tokenAmount,
      });
      setStep("wallet");
      const tx = await sendInvestmentTx({
        tokenAddress: property.token_address,
        propertyId: property.id,
        tokenAmount,
        valueWei: prepared.eth_amount_wei,
      });
      const receipt = await tx.wait();
      setStep("confirm");
      await api.post(`/investments/${prepared.investment_id}/confirm`, { tx_hash: tx.hash });
      toast.success(`Investment confirmed in block ${receipt?.blockNumber ?? "latest"}.`);
      emitWorkflowCompletion({
        modal: "INVEST_PROPERTY",
        status: "success",
        message: `Investment confirmed: ${tokenAmount} ${property.token_symbol || "tokens"} in ${property.name}.`,
      });
      queryClient.invalidateQueries({ queryKey: ["investor"] });
      queryClient.invalidateQueries({ queryKey: queryKeys.properties });
      onOpenChange(false);
      setStep("idle");
    } catch (err: any) {
      const errMsg = err?.message || "Investment failed.";
      toast.error(errMsg);
      emitWorkflowCompletion({ modal: "INVEST_PROPERTY", status: "error", message: errMsg });
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    return subscribeWorkflowAction((action) => {
      if (!isWorkflowModalAction(action, "INVEST_PROPERTY")) return;
      if (action.property_id !== undefined && !workflowPropertyMatches(action, property.id)) return;
      if (action.type === "FILL_FIELD" && action.field === "token_amount") {
        setAmount(String(action.value ?? ""));
        return;
      }
      if (action.type === "FOCUS_FIELD" && action.field) {
        window.setTimeout(() => focusWorkflowField("INVEST_PROPERTY", action.field!), 80);
        return;
      }
      if (action.type === "SUBMIT_FORM") {
        const trySubmit = (attemptsLeft: number) => {
          window.setTimeout(() => {
            if (formRef.current) {
              formRef.current.requestSubmit();
              return;
            }
            if (attemptsLeft > 0) trySubmit(attemptsLeft - 1);
          }, 180);
        };
        trySubmit(24);
      }
    });
  }, [property.id]);

  return (
    <Dialog open={open} onOpenChange={(next) => !busy && onOpenChange(next)}>
      <DialogContent
        className="max-w-md"
        onPointerDownOutside={preventCloseFromWorkflowBubble}
        onInteractOutside={preventCloseFromWorkflowBubble}
      >
        <DialogHeader>
          <DialogTitle>Invest in {property.name}</DialogTitle>
          <DialogDescription>
            Buy ownership tokens directly from the property SecurityToken contract.
          </DialogDescription>
        </DialogHeader>
        <form ref={formRef} onSubmit={onSubmit} className="space-y-4">
          <div className="grid gap-1.5">
            <Label>Token amount</Label>
            <Input
              data-workflow-field="INVEST_PROPERTY.token_amount"
              type="number"
              min="1"
              step="1"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              required
            />
          </div>
          <div className="grid grid-cols-2 gap-3 rounded-lg border border-border bg-muted/30 p-3 text-xs">
            <InvestFact label="Estimated cost" value={`${costEth.toFixed(6)} ETH`} />
            <InvestFact label="Wallet" value={shortAddress(wallet, 6, 4)} />
            <InvestFact label="Token price" value={`${Number(property.token_sale_price_eth ?? 0).toFixed(4)} ETH`} />
            <InvestFact label="Available" value={formatNumber(property.tokens_available ?? 0)} />
          </div>
          <div className="space-y-2 text-xs text-muted-foreground">
            <InvestStep
              active={step === "prepare"}
              done={["wallet", "confirm"].includes(step)}
              icon={ShieldCheck}
              label="Preparing backend quote"
            />
            <InvestStep
              active={step === "wallet"}
              done={step === "confirm"}
              icon={Wallet}
              label="Confirming transaction in MetaMask"
            />
            <InvestStep active={step === "confirm"} done={false} icon={CheckCircle2} label="Indexing investment on backend" />
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={busy}>
              Cancel
            </Button>
            <Button type="submit" disabled={busy || tokenAmount <= 0 || !wallet}>
              {busy ? "Processing…" : "Invest via MetaMask"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function InvestFact({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">{label}</span>
      <span className="font-medium tabular-nums">{value}</span>
    </div>
  );
}

function InvestStep({
  active,
  done,
  icon: Icon,
  label,
}: {
  active: boolean;
  done: boolean;
  icon: React.ComponentType<{ className?: string }>;
  label: string;
}) {
  return (
    <div
      className={cn(
        "flex items-center gap-2 rounded-md border border-border px-2.5 py-2",
        active && "border-primary/40 bg-primary/5 text-primary",
        done && "border-success/40 bg-success/5 text-success",
      )}
    >
      <Icon className="h-3.5 w-3.5" /> {label}
    </div>
  );
}
