"use client";

import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { Archive, Pencil, Rocket } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { PropertyDetailDialog } from "@/components/properties/property-detail-dialog";
import { PropertyListingCard } from "@/components/properties/property-listing-card";
import { useDeleteProperty, useDeployPropertyToken } from "@/lib/mutations";
import { useEditPropertyDialog } from "./edit-property-dialog";
import type { Property } from "@/lib/types";
import { isWorkflowModalAction, subscribeWorkflowAction, workflowPropertyMatches } from "@/lib/ai/action-executor";
import { useCurrentWallet } from "@/components/investor/use-current-wallet";

export function PropertyCard({ property }: { property: Property }) {
  const remove = useDeleteProperty();
  const deployToken = useDeployPropertyToken();
  const { openEdit } = useEditPropertyDialog();
  const wallet = useCurrentWallet();
  const canManage = Boolean(
    wallet && property.owner_wallet && property.owner_wallet.toLowerCase() === wallet.toLowerCase(),
  );
  const [detailOpen, setDetailOpen] = useState(false);

  const rentReady = Boolean(property.rent_enabled && Number(property.monthly_rent_eth ?? 0) > 0);
  const statusLabel = property.token_address
    ? rentReady
      ? "Rent ready"
      : "Listed"
    : "Setup pending";
  const statusVariant = property.token_address ? (rentReady ? "success" : "default") : "warning";

  useEffect(() => {
    return subscribeWorkflowAction((action) => {
      if (!canManage) return;
      if (!isWorkflowModalAction(action, "EDIT_PROPERTY")) return;
      if (action.type === "OPEN_MODAL" && workflowPropertyMatches(action, property.id)) {
        openEdit(property);
      }
    });
  }, [canManage, openEdit, property]);

  async function handleDeployToken() {
    try {
      await deployToken.mutateAsync(property.id);
      toast.success("Token contract deployed.");
    } catch (e: any) {
      toast.error(e?.message || "Token deployment failed.");
    }
  }

  async function handleArchive() {
    if (!window.confirm(`Archive or delete ${property.name}? Active on-chain/history records will be preserved.`)) return;
    try {
      const result = await remove.mutateAsync(property.id);
      toast.success(result.mode === "archived" ? "Property archived." : "Property deleted.");
    } catch (e: any) {
      toast.error(e?.message || "Archive failed.");
    }
  }

  return (
    <>
      <motion.div layout className="h-full">
        <PropertyListingCard
          property={property}
          onClick={() => setDetailOpen(true)}
          statusLabel={statusLabel}
          statusVariant={statusVariant}
          actionLabel="Manage"
          onActionClick={() => setDetailOpen(true)}
          toolbar={
            canManage ? (
              <TooltipProvider delayDuration={150}>
                <div className="flex w-full items-center gap-1">
                  {!property.token_address ? (
                    <IconAction
                      icon={<Rocket className="h-3.5 w-3.5" />}
                      label="Deploy token"
                      busy={deployToken.isPending}
                      variant="primary"
                      onClick={() => void handleDeployToken()}
                    />
                  ) : null}
                  <IconAction
                    icon={<Pencil className="h-3.5 w-3.5" />}
                    label="Edit property"
                    onClick={() => openEdit(property)}
                  />
                  <IconAction
                    icon={<Archive className="h-3.5 w-3.5" />}
                    label="Archive or delete"
                    busy={remove.isPending}
                    onClick={() => void handleArchive()}
                  />
                </div>
              </TooltipProvider>
            ) : undefined
          }
        />
      </motion.div>

      <PropertyDetailDialog
        property={property}
        open={detailOpen}
        onOpenChange={setDetailOpen}
        role="property_owner"
        wallet={wallet}
        onPrimaryAction={canManage ? () => openEdit(property) : undefined}
        primaryDisabled={!canManage}
      />
    </>
  );
}

function IconAction({
  icon,
  label,
  onClick,
  busy,
  variant,
}: {
  icon: React.ReactNode;
  label: string;
  onClick: () => void;
  busy?: boolean;
  variant?: "primary";
}) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button
          variant={variant === "primary" ? "default" : "ghost"}
          size="icon"
          className="h-7 w-7"
          disabled={busy}
          onClick={onClick}
        >
          {icon}
        </Button>
      </TooltipTrigger>
      <TooltipContent>{label}</TooltipContent>
    </Tooltip>
  );
}
