"use client";

import type { AIAction } from "./types";
import { getRoleFromPath, type RoleKey } from "./quick-actions";

const delay = (ms: number) => new Promise((resolve) => window.setTimeout(resolve, ms));

/** Investor copilot must never auto-submit on-chain dialogs from chat. */
const INVESTOR_NO_AUTO_SUBMIT_MODALS = new Set(["INVEST_PROPERTY", "CLAIM_REWARDS"]);

const MODAL_RETRIES = 6;
const MODAL_RETRY_DELAY = 220;

const ACTION_EVENT = "estatechain:ai-action";
const COMPLETION_EVENT = "estatechain:ai-completion";
const PENDING_TTL = 8000;

export type AICompletionStatus = "success" | "error";

export type AICompletionEvent = {
  modal: string;
  status: AICompletionStatus;
  message?: string;
};

type PendingOpen = {
  action: AIAction;
  expiresAt: number;
};

const pendingModalOpens = new Map<string, PendingOpen>();
const workflowFormValues = new Map<string, Record<string, string>>();

declare global {
  interface Window {
    __estatechainPendingModalActions?: Record<string, PendingOpen[]>;
  }
}

function nowMs() {
  return typeof performance !== "undefined" ? performance.now() : Date.now();
}

function rememberPendingOpen(action: AIAction) {
  if (!action.modal || action.type !== "OPEN_MODAL") return;
  pendingModalOpens.set(action.modal, { action, expiresAt: nowMs() + PENDING_TTL });
}

function rememberPendingAction(action: AIAction) {
  if (!action.modal) return;
  window.__estatechainPendingModalActions ??= {};
  const queued = window.__estatechainPendingModalActions[action.modal] ?? [];
  queued.push({ action, expiresAt: nowMs() + PENDING_TTL });
  window.__estatechainPendingModalActions[action.modal] = queued;
}

export function emitAction(action: AIAction) {
  if (typeof window === "undefined") return;
  rememberPendingOpen(action);
  rememberPendingAction(action);
  window.dispatchEvent(new CustomEvent<AIAction>(ACTION_EVENT, { detail: action }));
}

export function subscribeAction(handler: (action: AIAction) => void) {
  if (typeof window === "undefined") return () => {};
  const listener = (e: Event) => handler((e as CustomEvent<AIAction>).detail);
  window.addEventListener(ACTION_EVENT, listener);
  return () => window.removeEventListener(ACTION_EVENT, listener);
}

export function takePendingModalOpen(modal: string, propertyId?: number | string): AIAction | null {
  const p = pendingModalOpens.get(modal);
  if (!p) return null;
  if (p.expiresAt < nowMs()) {
    pendingModalOpens.delete(modal);
    return null;
  }
  if (propertyId !== undefined) {
    if (String(p.action.property_id ?? "") !== String(propertyId)) return null;
  }
  pendingModalOpens.delete(modal);
  return p.action;
}

export function takePendingModalActions(modal: string): AIAction[] {
  const queued = window.__estatechainPendingModalActions?.[modal] ?? [];
  if (window.__estatechainPendingModalActions) {
    delete window.__estatechainPendingModalActions[modal];
  }
  const valid = queued.filter((p) => p.expiresAt >= nowMs()).map((p) => p.action);
  if (!valid.some((action) => action.type === "OPEN_MODAL")) return valid;
  return valid;
}

export function clearPendingModalActions(modal: string) {
  if (window.__estatechainPendingModalActions) {
    delete window.__estatechainPendingModalActions[modal];
  }
  pendingModalOpens.delete(modal);
  workflowFormValues.delete(modal);
}

/**
 * Snapshot of every FILL_FIELD value the agent has written for the given
 * modal in the current workflow. Submitted forms should prefer this over
 * the React form state: it's untouched by render races, and it's exactly
 * what the agent intended to submit.
 */
export function getWorkflowFormValues(modal: string): Record<string, string> {
  return { ...(workflowFormValues.get(modal) ?? {}) };
}

export function emitCompletion(event: AICompletionEvent) {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent<AICompletionEvent>(COMPLETION_EVENT, { detail: event }));
}

export function subscribeCompletion(handler: (event: AICompletionEvent) => void) {
  if (typeof window === "undefined") return () => {};
  const listener = (e: Event) => handler((e as CustomEvent<AICompletionEvent>).detail);
  window.addEventListener(COMPLETION_EVENT, listener);
  return () => window.removeEventListener(COMPLETION_EVENT, listener);
}

export function waitForCompletion(modal: string, timeoutMs = 120_000): Promise<AICompletionEvent | null> {
  if (typeof window === "undefined") return Promise.resolve(null);
  return new Promise((resolve) => {
    let timer = 0;
    const unsub = subscribeCompletion((ev) => {
      if (ev.modal !== modal) return;
      window.clearTimeout(timer);
      unsub();
      resolve(ev);
    });
    timer = window.setTimeout(() => {
      unsub();
      resolve(null);
    }, timeoutMs);
  });
}

export function focusField(modal: string, field: string) {
  if (typeof document === "undefined") return;
  // Never steal focus from the AI chat textbox — if the user is mid-
  // conversation their next keystroke must land in chat, not in the
  // form the agent is filling out. (Voice mode renders no chat input,
  // so this guard naturally no-ops there and we focus normally.)
  const chatInput = document.querySelector<HTMLInputElement>(
    "[data-ai-chat-input]",
  );
  if (chatInput && !chatInput.disabled) return;
  const node = document.querySelector<HTMLInputElement | HTMLTextAreaElement | HTMLButtonElement>(
    `[data-workflow-field="${modal}.${field}"]`,
  );
  node?.focus();
  if (node instanceof HTMLInputElement) node.select();
}

async function waitForModalField(modal: string, timeoutMs = 5000) {
  if (typeof document === "undefined") return;
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    if (document.querySelector(`[data-workflow-field^="${modal}."]`)) return;
    await delay(100);
  }
}

/**
 * Try to open the modal on the current page.
 *
 * Returns true if either the modal is already open OR a trigger button was
 * found and clicked. Returns false when the modal can't be opened from the
 * current route (e.g. the user is on a different dashboard page).
 *
 * The previous implementation always blocked for ~3s waiting for the field
 * to appear, even when no trigger existed — that caused multi-second hangs
 * on every FILL_FIELD action coming in from the AI. We now only wait when
 * we actually clicked something.
 */
function workflowTriggerSelector(modal: string, propertyId?: number | string) {
  const base = `[data-workflow-modal-trigger="${modal}"]`;
  if (propertyId === undefined || propertyId === null || propertyId === "") return base;
  return `${base}[data-workflow-property-id="${propertyId}"]`;
}

async function openWorkflowModal(modal: string, propertyId?: number | string): Promise<boolean> {
  if (typeof document === "undefined") return false;
  if (document.querySelector(`[data-workflow-field^="${modal}."]`)) return true;

  const scoped =
    propertyId !== undefined && propertyId !== null && propertyId !== ""
      ? document.querySelector<HTMLButtonElement>(workflowTriggerSelector(modal, propertyId))
      : null;
  const trigger =
    scoped ??
    document.querySelector<HTMLButtonElement>(`[data-workflow-modal-trigger="${modal}"]`);
  if (!trigger) return false;
  trigger.click();
  await waitForModalField(modal, 3000);
  return Boolean(document.querySelector(`[data-workflow-field^="${modal}."]`));
}

async function waitForWorkflowModalReady(
  modal: string,
  propertyId?: number | string,
  timeoutMs = 6000,
) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    if (document.querySelector(`[data-workflow-field^="${modal}."]`)) return true;
    await delay(120);
    if (propertyId !== undefined && propertyId !== null && propertyId !== "") {
      const trigger = document.querySelector<HTMLButtonElement>(
        workflowTriggerSelector(modal, propertyId),
      );
      trigger?.click();
    }
  }
  return Boolean(document.querySelector(`[data-workflow-field^="${modal}."]`));
}

function setWorkflowInputValue(modal: string, field: string, value: string) {
  if (typeof document === "undefined") return;
  const input = document.querySelector<HTMLInputElement | HTMLTextAreaElement>(
    `[data-workflow-field="${modal}.${field}"]`,
  );
  if (!input) return;
  const descriptor = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(input), "value");
  descriptor?.set?.call(input, value);
  input.dispatchEvent(new Event("input", { bubbles: true }));
  input.dispatchEvent(new Event("change", { bubbles: true }));
}

/**
 * Brief visual pulse on the submit button so the user can SEE the agent
 * clicking it. We add a temporary outline + scale class, focus the button
 * (which paints the focus ring), then dispatch a real ``click`` so the
 * form's normal onSubmit handler runs — same code path a human user takes
 * when they tap "Create" themselves.
 */
async function clickWorkflowSubmitVisibly(
  modal: string,
  propertyId?: number | string,
): Promise<boolean> {
  if (typeof document === "undefined") return false;
  const opened = await openWorkflowModal(modal, propertyId);
  if (!opened) {
    console.info(
      "[AI Action] Workflow form not on this page; cannot submit:",
      modal,
    );
    return false;
  }
  await waitForModalField(modal);

  // Hydrate any cached field values into the DOM (and React state) so the
  // mutation receives the values the user dictated, even on the first
  // mount after a navigation.
  const values = workflowFormValues.get(modal) ?? {};
  for (const [field, value] of Object.entries(values)) {
    setWorkflowInputValue(modal, field, value);
  }
  await delay(250); // let React flush state

  const form = document.querySelector<HTMLFormElement>(`form[data-workflow-form="${modal}"]`);
  if (!form) {
    console.info("[AI Action] Workflow form node missing after open:", modal);
    return false;
  }
  const submitBtn = form.querySelector<HTMLButtonElement>('button[type="submit"]');
  if (!submitBtn || submitBtn.disabled) {
    // Fallback — submit programmatically. Less visual but still triggers
    // the form's onSubmit (which is what runs the mutation).
    console.log("[AI Action] Submit button missing/disabled; falling back to requestSubmit:", modal);
    form.requestSubmit();
    return true;
  }

  // Visual "press" effect: focus → highlight class → click → release.
  submitBtn.scrollIntoView({ block: "nearest", behavior: "smooth" });
  submitBtn.focus({ preventScroll: true });
  submitBtn.classList.add("ai-agent-clicking");
  await delay(220); // long enough for the human eye to see the ring/pulse
  console.log("[AI Action] Visibly clicking submit button:", modal);
  submitBtn.click();
  // Keep the highlight on briefly so the click is unmistakable, then drop it.
  window.setTimeout(() => submitBtn.classList.remove("ai-agent-clicking"), 600);
  return true;
}

export function roleFromBrowserPath(): RoleKey | null {
  if (typeof window === "undefined") return null;
  return getRoleFromPath(window.location.pathname);
}

/**
 * Strip investor on-chain auto-submits. Manual Invest / Claim buttons are unchanged.
 */
export function sanitizeActionsForRole(role: RoleKey | null, actions: AIAction[]): AIAction[] {
  if (role !== "investor") return actions;
  return actions.filter((action) => {
    if (action.type !== "SUBMIT_FORM" || !action.modal) return true;
    return !INVESTOR_NO_AUTO_SUBMIT_MODALS.has(action.modal);
  });
}

/** Execute a single UI action. */
export async function executeAction(action: AIAction, router: { push: (href: string) => void }) {
  console.log("[AI Action] Executing:", action.type, action);
  if (action.type === "NAVIGATE" && action.route) {
    console.log("[AI Action] Navigating to:", action.route);
    router.push(action.route);
    await delay(600); // Wait for page to mount
    console.log("[AI Action] Navigation complete, waiting for mount...");
    return;
  }
  if (action.type === "OPEN_MODAL" && action.modal) {
    console.log("[AI Action] Opening modal:", action.modal, action.property_id);
    workflowFormValues.delete(action.modal);
    clearPendingModalActions(action.modal);
    const opened = await openWorkflowModal(action.modal, action.property_id ?? undefined);
    // Always emit the OPEN_MODAL event so listeners that mount later (after
    // a navigation) can pick it up via takePendingModalOpen.
    for (let i = 0; i < MODAL_RETRIES; i++) {
      emitAction(action);
      await delay(MODAL_RETRY_DELAY);
    }
    if (opened) {
      await delay(400); // Extra wait for modal to fully render
      console.log("[AI Action] Modal should be open now");
    } else {
      console.info(
        "[AI Action] OPEN_MODAL emitted but no trigger on this page (modal will open on navigation):",
        action.modal,
      );
    }
    return;
  }
  if (action.type === "FOCUS_FIELD" && action.modal && action.field) {
    console.log("[AI Action] Focusing field:", action.modal, action.field);
    focusField(action.modal, action.field);
    return;
  }
  if (action.type === "FILL_FIELD" && action.modal && action.field) {
    console.log("[AI Action] Filling field:", action.modal, action.field, "=", action.value);
    // Remember the value regardless of whether the form is mounted — the
    // dialog component drains pending actions on mount, so navigating to
    // the page later will still hydrate the form with these values.
    const values = workflowFormValues.get(action.modal) ?? {};
    values[action.field] = String(action.value ?? "");
    workflowFormValues.set(action.modal, values);
    // Try to fill the live input if the modal is reachable from the
    // current page; otherwise emit-only so navigation-on-mount works.
    const opened = await openWorkflowModal(action.modal, action.property_id ?? undefined);
    if (opened) {
      await waitForModalField(action.modal);
      setWorkflowInputValue(action.modal, action.field, String(action.value ?? ""));
    }
    emitAction(action);
    await delay(opened ? 150 : 30); // Allow React state to flush
    return;
  }
  if (action.type === "SUBMIT_FORM" && action.modal) {
    console.log("[AI Action] Submitting form (visible click):", action.modal);
    await waitForWorkflowModalReady(action.modal, action.property_id ?? undefined);
    const clicked = await clickWorkflowSubmitVisibly(
      action.modal,
      action.property_id ?? undefined,
    );
    // Emit the action AFTER the click so any listener that wants to react
    // to "the agent just hit submit" can do so without colliding with the
    // form's own onSubmit handler.
    if (clicked) {
      await delay(400);
      emitAction(action);
    } else {
      // Couldn't reach the form — surface the action so the dialog (if it
      // mounts later via NAVIGATE) can pick it up from the pending queue.
      emitAction(action);
    }
    return;
  }
  console.log("[AI Action] Unknown action type or missing fields:", action);
}

export async function executeActions(
  actions: AIAction[],
  router: { push: (href: string) => void },
  opts?: { role?: RoleKey | null },
) {
  const role = opts?.role ?? roleFromBrowserPath();
  const safe = sanitizeActionsForRole(role, actions);
  for (const action of safe) {
    await executeAction(action, router);
  }
}

/* -------------------------------------------------------------------------- */
/*  Backward-compatible aliases (old action-bus API)                        */
/* -------------------------------------------------------------------------- */

export function preventCloseFromWorkflowBubble(event: { target: EventTarget | null; preventDefault: () => void }) {
  const target = event.target as Element | null;
  if (target && typeof (target as Element).closest === "function") {
    if (target.closest(`[data-workflow-bubble]`)) {
      event.preventDefault();
    }
  }
}

export function isWorkflowModalAction(action: AIAction, modal: string) {
  return "modal" in action && action.modal === modal;
}

export function workflowPropertyMatches(action: AIAction, propertyId: number | string) {
  if (!("property_id" in action) || action.property_id === undefined || action.property_id === null) return false;
  return String(action.property_id) === String(propertyId);
}

export const focusWorkflowField = focusField;
export const emitWorkflowAction = emitAction;
export const subscribeWorkflowAction = subscribeAction;
export const takePendingWorkflowActions = takePendingModalActions;
export const clearPendingWorkflowActions = clearPendingModalActions;
export const emitWorkflowCompletion = emitCompletion;
export const subscribeWorkflowCompletion = subscribeCompletion;
export const waitForWorkflowCompletion = waitForCompletion;
