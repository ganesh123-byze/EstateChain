"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api, getApiBase, getToken } from "./api";
import { queryKeys } from "./queries";
import type { Property } from "./types";

export type CreatePropertyPayload = {
  name: string;
  location: string;
  total_value: string | number;
  token_supply: string | number;
  token_symbol: string;
  token_sale_price_eth: string | number;
  monthly_rent_eth?: string | number | null;
  images?: string[];
};

/** Discrete backend stages for the create-property pipeline. */
export type CreatePropertyStep =
  | "creating"
  | "created"
  | "deploying_token"
  | "token_deployed"
  | "finalizing_inventory"
  | "inventory_done"
  | "syncing_rent"
  | "rent_synced"
  | "rent_sync_skipped"
  | "done"
  | "error";

export type CreatePropertyEvent = {
  step: CreatePropertyStep;
  property?: Property;
  property_id?: number;
  duplicate?: boolean;
  detail?: string;
};

export function useCreateProperty() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: CreatePropertyPayload) => api.post<Property>("/properties", payload),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.properties }),
  });
}

/**
 * Streaming version of useCreateProperty. Calls the SSE endpoint
 * `POST /properties/stream` and invokes `onProgress` for each
 * stage event so the dialog can light up the matching row.
 *
 * Resolves with the final property on success and rejects with
 * an Error carrying the backend `detail` string on failure.
 */
export function useCreatePropertyStream() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({
      payload,
      onProgress,
      signal,
    }: {
      payload: CreatePropertyPayload;
      onProgress?: (event: CreatePropertyEvent) => void;
      signal?: AbortSignal;
    }): Promise<Property> => {
      const base = getApiBase();
      const token = getToken();
      const res = await fetch(`${base}/properties/stream`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Accept: "text/event-stream",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify(payload),
        signal,
      });
      if (!res.ok) {
        const errText = await res.text().catch(() => "");
        let detail = `HTTP ${res.status}`;
        try {
          const parsed = JSON.parse(errText);
          if (parsed?.detail) detail = String(parsed.detail);
        } catch {
          if (errText) detail = errText;
        }
        throw new Error(detail);
      }
      const reader = res.body?.getReader();
      if (!reader) throw new Error("No response body");
      const decoder = new TextDecoder();
      let sseBuffer = "";
      let finalProperty: Property | null = null;
      let finalError: string | null = null;
      let rentSyncWarning: string | null = null;

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        sseBuffer += decoder.decode(value, { stream: true });
        const parts = sseBuffer.split("\n\n");
        sseBuffer = parts.pop() || "";
        for (const part of parts) {
          for (const line of part.split("\n")) {
            if (!line.startsWith("data: ")) continue;
            const raw = line.slice(6).trim();
            if (!raw) continue;
            let event: CreatePropertyEvent;
            try {
              event = JSON.parse(raw) as CreatePropertyEvent;
            } catch {
              continue;
            }
            onProgress?.(event);
            if (event.step === "done" && event.property) {
              finalProperty = event.property;
            } else if (event.step === "rent_sync_skipped") {
              rentSyncWarning = event.detail || "Rent was not synced on-chain.";
            } else if (event.step === "error") {
              finalError = event.detail || "Property creation failed.";
            }
          }
        }
      }

      if (finalError) throw new Error(finalError);
      if (!finalProperty) throw new Error("Property creation finished without a result.");
      if (rentSyncWarning) {
        (finalProperty as Property & { rentSyncWarning?: string }).rentSyncWarning = rentSyncWarning;
      }
      return finalProperty;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.properties }),
  });
}

export function useUpdateProperty(id: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: CreatePropertyPayload) =>
      api.put<Property>(`/properties/${id}`, payload),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.properties }),
  });
}

export function useDeleteProperty() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (propertyId: number) =>
      api.del<{ status: string; property_id: number; mode: "deleted" | "archived" }>(`/properties/${propertyId}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.properties }),
  });
}

export function useDeployPropertyToken() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (propertyId: number) =>
      api.post<Property>(`/properties/${propertyId}/deploy-token`),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.properties }),
  });
}

export function useRepairSaleInventory() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (propertyId: number) =>
      api.post<Property>(`/properties/${propertyId}/repair-sale-inventory`),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.properties }),
  });
}

export function useMintPropertyNft() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: { property_id: number; to_address: string; token_uri: string }) =>
      api.post<Property>(`/properties/${payload.property_id}/mint-nft`, {
        to_address: payload.to_address,
        token_uri: payload.token_uri,
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.properties }),
  });
}

export function useSyncRentChain() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (propertyId: number) =>
      api.post<{ status: string; investor_count: number }>(`/properties/${propertyId}/sync-rent-chain`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.properties });
      qc.invalidateQueries({ queryKey: queryKeys.rentAnalytics });
    },
  });
}

export function useSetRent() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: { property_id: number; monthly_rent_eth: string | number }) =>
      api.post(`/properties/${payload.property_id}/set-rent`, {
        monthly_rent_eth: payload.monthly_rent_eth,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.properties });
      qc.invalidateQueries({ queryKey: queryKeys.rentAnalytics });
    },
  });
}

export function useIssueTokens() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: {
      property_id: number;
      to_address: string;
      amount: string | number;
      email?: string | null;
    }) =>
      api.post<Property>(`/properties/${payload.property_id}/issue-tokens`, {
        to_address: payload.to_address,
        amount: payload.amount,
        email: payload.email ?? null,
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.properties }),
  });
}

