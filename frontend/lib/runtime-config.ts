function stripTrailingSlash(url: string): string {
  return url.trim().replace(/\/$/, "");
}

/** Prefer https for public API URL when env uses http (avoids mixed content on Vercel). */
export function coerceApiBaseUrlForBuild(url: string): string {
  const u = stripTrailingSlash(url);
  if (!u) return u;
  const isLocal = /^(https?:\/\/)(localhost|127\.0\.0\.1)(:\d+)?(\/|$)/i.test(u);
  if (!isLocal && process.env.NODE_ENV === "production" && u.startsWith("http://")) {
    return "https://" + u.slice("http://".length);
  }
  return u;
}

const ttsEnabledRaw = process.env.NEXT_PUBLIC_WORKFLOW_TTS_ENABLED;
const ttsGenderRaw = (process.env.NEXT_PUBLIC_WORKFLOW_TTS_GENDER || "female").toLowerCase();

export const RUNTIME_CONFIG = {
  apiBaseUrl: coerceApiBaseUrlForBuild(process.env.NEXT_PUBLIC_API_BASE_URL || ""),
  chainId: Number(process.env.NEXT_PUBLIC_CHAIN_ID || 11155111),
  explorerTxBase: process.env.NEXT_PUBLIC_EXPLORER_TX_BASE || "https://sepolia.etherscan.io/tx/",
  /** Read assistant replies aloud (browser Speech Synthesis — pick male/female hints per OS voices). */
  workflowTtsEnabled: ttsEnabledRaw !== "false" && ttsEnabledRaw !== "0",
  workflowTtsGender: ttsGenderRaw === "male" ? ("male" as const) : ("female" as const),
  workflowTtsRate: Math.min(1.25, Math.max(0.75, Number(process.env.NEXT_PUBLIC_WORKFLOW_TTS_RATE || "1") || 1)),
  /** Pause after TTS before restarting mic (continuous voice session). */
  workflowVoiceContinuationDelayMs: Math.min(
    4000,
    Math.max(200, Number(process.env.NEXT_PUBLIC_WORKFLOW_VOICE_CONTINUE_DELAY_MS || "750") || 750),
  ),
};

export function expectedChainHex(): string {
  return "0x" + RUNTIME_CONFIG.chainId.toString(16);
}

export function txExplorerUrl(hash?: string | null): string {
  if (!hash) return "#";
  return `${RUNTIME_CONFIG.explorerTxBase}${hash}`;
}

export function addressExplorerUrl(address?: string | null): string {
  if (!address) return "#";
  const base = RUNTIME_CONFIG.explorerTxBase.replace(/\/tx\/?$/i, "/address/");
  return `${base}${address}`;
}
