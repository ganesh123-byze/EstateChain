"use client";

import { useEffect, useRef, useState } from "react";
import { Check, Loader2, Plus } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import {
  useCreatePropertyStream,
  type CreatePropertyEvent,
  type CreatePropertyStep,
} from "@/lib/mutations";
import type { Property } from "@/lib/types";
import { cn } from "@/lib/utils";
import { PropertyImageUploader } from "@/components/properties/property-image-uploader";
import {
  clearPendingWorkflowActions,
  emitWorkflowCompletion,
  focusWorkflowField,
  getWorkflowFormValues,
  isWorkflowModalAction,
  preventCloseFromWorkflowBubble,
  subscribeWorkflowAction,
  takePendingModalOpen,
  takePendingWorkflowActions,
} from "@/lib/ai/action-executor";
import {
  PropertyFormField,
  calculateTokenPriceEth,
  formatTokenPriceEth,
  propertyDialogBodyClass,
  propertyDialogContentClass,
  propertyDialogFooterClass,
  propertyFormClass,
  propertyFormGridClass,
} from "@/components/properties/property-form-shared";

/**
 * Render order of the progress card. Each row maps to:
 *   - `intent` step  → row is active (spinner + bold)
 *   - `done` step    → row is completed (green check + green bar)
 *
 * The order matches the backend pipeline:
 *   creating → deploying_token → finalizing_inventory → syncing_rent
 */
const CREATE_STEPS: ReadonlyArray<{
  label: string;
  intent: CreatePropertyStep;
  done: CreatePropertyStep;
}> = [
  { label: "Creating property…",    intent: "creating",            done: "created" },
  { label: "Deploying token…",      intent: "deploying_token",     done: "token_deployed" },
  { label: "Finalizing inventory…", intent: "finalizing_inventory", done: "inventory_done" },
  { label: "Syncing rent on-chain…", intent: "syncing_rent",        done: "rent_synced" },
];

/** Indices of completed/active rows derived from the SSE event stream. */
function deriveStepStatus(events: CreatePropertyStep[]): {
  active: number; // -1 if nothing started yet
  completedCount: number;
} {
  let active = -1;
  let completedCount = 0;
  for (const e of events) {
    const intentIdx = CREATE_STEPS.findIndex((s) => s.intent === e);
    if (intentIdx >= 0) {
      active = intentIdx;
      completedCount = Math.max(completedCount, intentIdx);
    }
    const doneIdx = CREATE_STEPS.findIndex((s) => s.done === e);
    if (doneIdx >= 0) {
      completedCount = Math.max(completedCount, doneIdx + 1);
      // Bump active forward to the next non-completed row so the spinner
      // sits on the upcoming stage instead of the just-finished one.
      if (doneIdx + 1 < CREATE_STEPS.length) active = doneIdx + 1;
      else active = -1;
    }
    if (e === "done") {
      completedCount = CREATE_STEPS.length;
      active = -1;
    }
  }
  return { active, completedCount };
}

const initial = {
  name: "",
  location: "",
  total_value: "",
  token_supply: "",
  token_symbol: "",
  monthly_rent_eth: "",
  images: [] as string[],
};

type FormState = typeof initial;

const TEXT_FIELDS: ReadonlyArray<keyof FormState> = [
  "name",
  "location",
  "total_value",
  "token_supply",
  "token_symbol",
  "monthly_rent_eth",
];

export function CreatePropertyDialog() {
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState<FormState>(initial);
  // Stream of SSE step events so the progress card can light up rows
  // as the backend advances through deploy → inventory → rent sync.
  const [stepEvents, setStepEvents] = useState<CreatePropertyStep[]>([]);
  const formRef = useRef<HTMLFormElement | null>(null);
  const create = useCreatePropertyStream();
  const tokenPriceEth = calculateTokenPriceEth(form.total_value, form.token_supply);
  const { active: activeStepIdx, completedCount } = deriveStepStatus(stepEvents);

  function update<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((f) => ({ ...f, [key]: value }));
  }

  // Resolve the values to submit, in priority order:
  //   1. `workflowFormValues` cache — the agent writes every FILL_FIELD
  //      value here synchronously, untouched by any render race. This is
  //      the most authoritative source for agent-driven submits.
  //   2. Live DOM inputs — what the user (or agent) most recently set.
  //   3. React form state — for the pure manual path where 1 & 2 agree.
  // The previous bug was that a fresh-page session would work but a
  // second create in the *same* session would submit with values that
  // matched neither the form on screen nor what the user dictated;
  // reading from the cache eliminates that drift.
  function resolveSubmitValues(fallback: FormState): FormState {
    const cache = getWorkflowFormValues("CREATE_PROPERTY");
    const readDom = (k: Exclude<keyof FormState, "images">): string => {
      if (typeof document === "undefined") return "";
      const el = document.querySelector<HTMLInputElement>(
        `[data-workflow-field="CREATE_PROPERTY.${k}"]`,
      );
      return el?.value ?? "";
    };
    const pick = (k: Exclude<keyof FormState, "images">): string => {
      // String() because numeric inputs deliver everything as strings
      // anyway, and JSON.stringify on the payload tolerates both.
      const fromCache = cache[k];
      if (fromCache !== undefined && fromCache !== "") return String(fromCache);
      const fromDom = readDom(k);
      if (fromDom) return fromDom;
      return String(fallback[k] ?? "");
    };
    return {
      name: pick("name"),
      location: pick("location"),
      total_value: pick("total_value"),
      token_supply: pick("token_supply"),
      token_symbol: pick("token_symbol"),
      monthly_rent_eth: pick("monthly_rent_eth"),
      // Images live only in React state (uploader has no DOM mirror).
      images: fallback.images,
    };
  }

  // ───────────────────────────────────────────────────────────────
  // Submit — SINGLE source of truth for "create the property".
  //
  // Runs the same way whether the user clicked Create themselves OR
  // the AI agent clicked it via the action-executor's visible
  // button-press. On success we emit the workflow-completion event,
  // which is what makes the chat bubble / voice session say
  // "Property created successfully" — without it the agent stays
  // silent and the UI looks frozen.
  // ───────────────────────────────────────────────────────────────
  async function submitWorkflowForm(stateValues: FormState) {
    setStepEvents([]); // reset any leftover progress from a prior attempt
    // Resolve from the agent's workflow cache → DOM → React state.
    // See `resolveSubmitValues` for why the cache wins (it's untouched
    // by render races and is exactly what the agent intended to submit).
    const values = resolveSubmitValues(stateValues);
    console.log("[CreateProperty] submitting payload:", {
      name: values.name,
      location: values.location,
      total_value: values.total_value,
      token_supply: values.token_supply,
      token_symbol: values.token_symbol,
      monthly_rent_eth: values.monthly_rent_eth,
    });
    // Mirror the live values back into React state so the visible
    // fields, the progress card, and the form-reset paths all agree.
    setForm(values);
    try {
      const price = calculateTokenPriceEth(values.total_value, values.token_supply);
      const created = await create.mutateAsync({
        payload: {
          name: values.name.trim(),
          location: values.location.trim(),
          total_value: values.total_value,
          token_supply: values.token_supply,
          token_symbol: values.token_symbol.trim(),
          token_sale_price_eth: price > 0 ? price : "",
          monthly_rent_eth: values.monthly_rent_eth ? values.monthly_rent_eth : null,
          images: values.images,
        },
        onProgress: (event: CreatePropertyEvent) => {
          // Append the step so the derived status updates in real time.
          setStepEvents((prev) => [...prev, event.step]);
        },
      });
      const named = values.name.trim();
      const msg = named
        ? `Property '${named}' created successfully.`
        : "Property created successfully.";
      const rentWarning = (created as Property & { rentSyncWarning?: string }).rentSyncWarning;
      clearPendingWorkflowActions("CREATE_PROPERTY");
      toast.success(msg);
      if (rentWarning) {
        toast.warning(
          "Token deployed, but rent was not synced. Redeploy platform contracts with your deployer wallet (`npm run deploy:sepolia`), then use Sync Rent Chain on the property.",
          { duration: 12000 },
        );
      }
      emitWorkflowCompletion({
        modal: "CREATE_PROPERTY",
        status: "success",
        message: msg,
      });
      // Hold the all-green progress card on screen for a beat so the user
      // sees the final completed state, then auto-close.
      window.setTimeout(() => {
        setForm(initial);
        setStepEvents([]);
        setOpen(false);
        // Reset the React Query mutation so the next create starts from a
        // fully clean slate (no lingering data / success flag carried over).
        create.reset();
      }, 650);
    } catch (err: any) {
      clearPendingWorkflowActions("CREATE_PROPERTY");
      const errMsg = err?.message || "Failed to create property.";
      toast.error(errMsg);
      emitWorkflowCompletion({ modal: "CREATE_PROPERTY", status: "error", message: errMsg });
      // Keep stepEvents so the user can see which stage failed, but mark
      // a terminal error so the spinner stops.
      setStepEvents((prev) => [...prev, "error"]);
      // Reset the mutation so the retry-after-error path doesn't inherit
      // a stale isError/error from the previous attempt.
      create.reset();
    }
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    await submitWorkflowForm(form);
  }

  // ───────────────────────────────────────────────────────────────
  // AI agent listener — open the dialog, fill / focus fields.
  //
  // We deliberately DO NOT submit from here. The action-executor
  // performs a visible click on the Create button when it gets a
  // SUBMIT_FORM action, which goes through the form's normal
  // onSubmit handler above. One submit path, no double-fires.
  // ───────────────────────────────────────────────────────────────
  useEffect(() => {
    const handleAction = (action: any) => {
      if (!isWorkflowModalAction(action, "CREATE_PROPERTY")) return;

      if (action.type === "OPEN_MODAL") {
        setForm(initial);
        setOpen(true);
        return;
      }

      if (action.type === "FILL_FIELD" && action.field) {
        const key = action.field as keyof FormState;
        if (!TEXT_FIELDS.includes(key)) return;
        const value = String(action.value ?? "");
        setForm((f) => ({ ...f, [key]: value }));
        // Mirror into the live DOM input so the visible field matches
        // React state even if the user is mid-edit on something else.
        const input = document.querySelector<HTMLInputElement>(
          `[data-workflow-field="CREATE_PROPERTY.${key}"]`,
        );
        if (input && input.value !== value) {
          const desc = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(input), "value");
          desc?.set?.call(input, value);
          input.dispatchEvent(new Event("input", { bubbles: true }));
        }
        return;
      }

      if (action.type === "FOCUS_FIELD" && action.field) {
        window.setTimeout(
          () => focusWorkflowField("CREATE_PROPERTY", action.field!),
          80,
        );
        return;
      }

      // SUBMIT_FORM intentionally NOT handled here — the action-
      // executor clicks the visible Create button which triggers
      // onSubmit above.
    };

    // Catch an OPEN_MODAL that arrived before mount (e.g. fired
    // during the NAVIGATE that landed us on this page).
    if (takePendingModalOpen("CREATE_PROPERTY")) {
      setForm(initial);
      setOpen(true);
    }
    const drain = () => {
      for (const a of takePendingWorkflowActions("CREATE_PROPERTY")) handleAction(a);
    };
    drain();
    const timers = [80, 240, 600, 1200].map((ms) => window.setTimeout(drain, ms));
    const unsubscribe = subscribeWorkflowAction(handleAction);
    return () => {
      timers.forEach((t) => window.clearTimeout(t));
      unsubscribe();
    };
  }, []);

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button size="sm" className="gap-1.5" data-workflow-modal-trigger="CREATE_PROPERTY">
          <Plus className="h-3.5 w-3.5" />
          Create Property
        </Button>
      </DialogTrigger>
      <DialogContent
        className={propertyDialogContentClass}
        onPointerDownOutside={preventCloseFromWorkflowBubble}
        onInteractOutside={preventCloseFromWorkflowBubble}
        // Radix auto-focuses the first focusable child when a dialog opens.
        // During an AI-driven flow that pulls keyboard focus out of the chat
        // textbox, so the user's next keystroke vanishes into the name
        // input instead of their next chat message. Prevent that — the chat
        // remains the authoritative input while the agent drives the form.
        onOpenAutoFocus={(e) => {
          if (typeof document === "undefined") return;
          const chat = document.querySelector<HTMLInputElement>(
            '[data-ai-chat-input]',
          );
          if (chat && !chat.disabled) e.preventDefault();
        }}
      >
        <DialogHeader className="border-b border-border/60 px-6 pb-3 pt-5">
          <DialogTitle>Create Property</DialogTitle>
          <DialogDescription>
            The platform will deploy the token and sync the rent setup after creation.
          </DialogDescription>
        </DialogHeader>
        <form
          ref={formRef}
          onSubmit={onSubmit}
          className={cn(propertyFormClass, propertyDialogBodyClass)}
          data-workflow-form="CREATE_PROPERTY"
        >
          <PropertyFormField label="Name">
            <Input
              data-workflow-field="CREATE_PROPERTY.name"
              required
              value={form.name}
              onChange={(e) => update("name", e.target.value)}
              placeholder="Oceanview Apartments"
            />
          </PropertyFormField>
          <PropertyFormField label="Location">
            <Input
              data-workflow-field="CREATE_PROPERTY.location"
              required
              value={form.location}
              onChange={(e) => update("location", e.target.value)}
              placeholder="Miami, USA"
            />
          </PropertyFormField>
          <div className={propertyFormGridClass}>
            <PropertyFormField label="Total Value (ETH)">
              <Input
                data-workflow-field="CREATE_PROPERTY.total_value"
                required
                type="number"
                min="0"
                step="any"
                inputMode="decimal"
                value={form.total_value}
                onChange={(e) => update("total_value", e.target.value)}
                placeholder="10"
              />
            </PropertyFormField>
            <PropertyFormField label="Token Supply">
              <Input
                data-workflow-field="CREATE_PROPERTY.token_supply"
                required
                type="number"
                min="1"
                step="1"
                inputMode="numeric"
                value={form.token_supply}
                onChange={(e) => update("token_supply", e.target.value)}
                placeholder="10000"
              />
            </PropertyFormField>
          </div>
          <div className={propertyFormGridClass}>
            <PropertyFormField label="Symbol">
              <Input
                data-workflow-field="CREATE_PROPERTY.token_symbol"
                required
                value={form.token_symbol}
                onChange={(e) => update("token_symbol", e.target.value)}
                placeholder="OCEAN"
              />
            </PropertyFormField>
            <PropertyFormField label="Token Price (ETH, auto)">
              <Input
                readOnly
                tabIndex={-1}
                value={formatTokenPriceEth(tokenPriceEth)}
                placeholder="Calculated"
                className="bg-muted/40"
              />
            </PropertyFormField>
          </div>
          <p className="-mt-1 break-words text-xs text-muted-foreground">
            {tokenPriceEth > 0
              ? `${formatTokenPriceEth(tokenPriceEth)} per token (total value ÷ supply).`
              : "Enter total value in ETH and token supply to calculate price."}
          </p>
          <PropertyFormField label="Monthly Rent (ETH, optional)">
            <Input
              data-workflow-field="CREATE_PROPERTY.monthly_rent_eth"
              type="number"
              min="0"
              step="any"
              inputMode="decimal"
              value={form.monthly_rent_eth}
              onChange={(e) => update("monthly_rent_eth", e.target.value)}
              placeholder="0.5"
            />
          </PropertyFormField>
          <PropertyImageUploader
            images={form.images}
            onChange={(images) => setForm((f) => ({ ...f, images }))}
          />
          {(create.isPending || stepEvents.includes("error")) && (
            <div className="rounded-lg border border-border bg-muted/25 p-3">
              {/* Top-line progress bar — fills from 0% → 100% as backend
                  steps complete. Visible motion so the user knows the
                  deploy / sync stages are advancing. */}
              <div className="mb-3 h-1.5 w-full overflow-hidden rounded-full bg-muted">
                <div
                  className="h-full rounded-full bg-success transition-[width] duration-500 ease-out"
                  style={{
                    width: `${Math.min(
                      100,
                      Math.round((completedCount / CREATE_STEPS.length) * 100),
                    )}%`,
                  }}
                />
              </div>
              <ul className="space-y-1.5 text-xs">
                {CREATE_STEPS.map((step, index) => {
                  const isCompleted = index < completedCount;
                  const isActive = index === activeStepIdx;
                  return (
                    <li
                      key={step.label}
                      className={cn(
                        "flex items-center gap-2 transition-colors",
                        isCompleted
                          ? "text-success"
                          : isActive
                          ? "font-medium text-foreground"
                          : "text-muted-foreground",
                      )}
                    >
                      <span
                        className={cn(
                          "grid h-4 w-4 shrink-0 place-items-center rounded-full",
                          isCompleted
                            ? "bg-success/15 text-success"
                            : isActive
                            ? "bg-primary/15 text-primary"
                            : "bg-muted-foreground/15 text-muted-foreground/60",
                        )}
                      >
                        {isCompleted ? (
                          <Check className="h-2.5 w-2.5" strokeWidth={3} />
                        ) : isActive ? (
                          <Loader2 className="h-2.5 w-2.5 animate-spin" />
                        ) : (
                          <span className="h-1 w-1 rounded-full bg-current" />
                        )}
                      </span>
                      {step.label}
                    </li>
                  );
                })}
              </ul>
            </div>
          )}
          <DialogFooter className={propertyDialogFooterClass}>
            <Button type="button" variant="outline" size="sm" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button type="submit" size="sm" disabled={create.isPending}>
              {create.isPending ? "Creating…" : "Create"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
