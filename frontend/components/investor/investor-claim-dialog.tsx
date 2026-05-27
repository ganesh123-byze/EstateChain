"use client";

import { useCallback, useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { CheckCircle2, ShieldCheck, Wallet } from "lucide-react";
import { api } from "@/lib/api";
import { queryKeys } from "@/lib/queries";
import type { ClaimRewardsConfirmResponse, ClaimRewardsPrepareResponse, ClaimableRewardProperty } from "@/lib/types";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { cn, shortAddress } from "@/lib/utils";
import { sendClaimRewardsTx } from "@/components/investor/contract-actions";
import {
  emitWorkflowCompletion,
  isWorkflowModalAction,
  subscribeWorkflowAction,
  workflowPropertyMatches,
} from "@/lib/ai/action-executor";

export function useInvestorClaimRewardsListener(
  claimableProperties: ClaimableRewardProperty[] | undefined,
  setSelected: (reward: ClaimableRewardProperty | null) => void,
) {
  useEffect(() => {
    return subscribeWorkflowAction((action) => {
      if (!isWorkflowModalAction(action, "CLAIM_REWARDS")) return;
      if (action.type !== "OPEN_MODAL") return;
      const match = (claimableProperties ?? []).find((reward) =>
        workflowPropertyMatches(action, reward.property_id),
      );
      if (match) setSelected(match);
    });
  }, [claimableProperties, setSelected]);
}

export function InvestorClaimDialog({
  wallet,
  reward,
  onClose,
}: {
  wallet: string | null;
  reward: ClaimableRewardProperty | null;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [step, setStep] = useState<"idle" | "prepare" | "wallet" | "confirm">("idle");
  const [busy, setBusy] = useState(false);
  const open = Boolean(reward);

  const onClaim = useCallback(async () => {
    if (!wallet || !reward) return;
    setBusy(true);
    try {
      setStep("prepare");
      const prepared = await api.post<ClaimRewardsPrepareResponse>("/rewards/prepare-claim", {
        property_id: reward.property_id,
        investor_wallet: wallet,
      });
      setStep("wallet");
      const tx = await sendClaimRewardsTx({
        rentContractAddress: prepared.rent_contract_address,
        propertyId: reward.property_id,
      });
      await tx.wait();
      setStep("confirm");
      const result = await api.post<ClaimRewardsConfirmResponse>("/rewards/confirm-claim", {
        property_id: reward.property_id,
        investor_wallet: wallet,
        tx_hash: tx.hash,
      });
      toast.success(`Claimed ${result.claimed_amount_eth} ETH.`);
      emitWorkflowCompletion({
        modal: "CLAIM_REWARDS",
        status: "success",
        message: `Claimed ${result.claimed_amount_eth} ETH from ${reward.property_name ?? `Property #${reward.property_id}`}.`,
      });
      queryClient.invalidateQueries({ queryKey: ["investor"] });
      queryClient.invalidateQueries({ queryKey: queryKeys.transactions });
      onClose();
      setStep("idle");
    } catch (err: any) {
      const errMsg = err?.message || "Claim failed.";
      toast.error(errMsg);
      emitWorkflowCompletion({ modal: "CLAIM_REWARDS", status: "error", message: errMsg });
    } finally {
      setBusy(false);
    }
  }, [onClose, queryClient, reward, wallet]);

  useEffect(() => {
    return subscribeWorkflowAction((action) => {
      if (!isWorkflowModalAction(action, "CLAIM_REWARDS")) return;
      if (action.property_id !== undefined && !workflowPropertyMatches(action, reward?.property_id ?? "")) return;
      if (action.type === "SUBMIT_FORM") {
        const tryClaim = (attemptsLeft: number) => {
          window.setTimeout(() => {
            if (open) {
              void onClaim();
              return;
            }
            if (attemptsLeft > 0) tryClaim(attemptsLeft - 1);
          }, 180);
        };
        tryClaim(24);
      }
    });
  }, [onClaim, open, reward?.property_id]);

  return (
    <Dialog open={open} onOpenChange={(next) => !busy && !next && onClose()}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Claim rental yield</DialogTitle>
          <DialogDescription>{reward?.property_name ?? "Property reward"}</DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div className="rounded-lg border border-border bg-muted/30 p-3">
            <div className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">Claimable amount</div>
            <div className="mt-1 text-2xl font-semibold">{reward?.claimable_amount_eth ?? "0"} ETH</div>
            <div className="mt-1 text-xs text-muted-foreground">Wallet {shortAddress(wallet, 6, 4)}</div>
          </div>
          <div className="space-y-2 text-xs text-muted-foreground">
            <Step active={step === "prepare"} done={["wallet", "confirm"].includes(step)} icon={ShieldCheck} label="Preparing claim transaction" />
            <Step active={step === "wallet"} done={step === "confirm"} icon={Wallet} label="Confirming withdrawal in MetaMask" />
            <Step active={step === "confirm"} done={false} icon={CheckCircle2} label="Confirming and indexing claim" />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button onClick={onClaim} disabled={busy || !wallet}>
            {busy ? "Processing…" : "Claim via MetaMask"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function Step({
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
