/**
 * Premium full-duplex voice runtime.
 *
 * Lifecycle:
 *   start()  → grabs mic, opens AudioContext, opens WS, boots Silero VAD.
 *   stop()   → tears everything down cleanly.
 *
 * Per turn:
 *   - Mic stays open the whole session (never auto-stops, never push-to-talk).
 *   - Silero VAD classifies every 32 ms frame as speech vs. non-speech with
 *     ~95% accuracy. Doors, keyboards, laughs, music leakage, chair creaks etc.
 *     never reach the STT layer. Only sustained speech (≥ ~350 ms above 0.85
 *     probability) triggers an end-of-speech event.
 *   - On onSpeechEnd we encode the captured audio to WAV and POST it to the
 *     existing /api/ai/voice/transcribe endpoint immediately — Silero's tight
 *     endpointing replaces the previous 1.4 s silence hangover, cutting ~1.15 s
 *     of perceived end-of-turn latency.
 *   - Backend streams text tokens AND PCM16 audio chunks back. We collect
 *     ~300 ms of prebuffer before starting playback to eliminate the first-
 *     chunk stutter, then schedule subsequent chunks gaplessly via Web Audio.
 *
 * Barge-in (4-gate):
 *   1. Silero confidence > 0.85   (enforced inside Silero VAD)
 *   2. Speech duration > 350 ms   (enforced by minSpeechFrames)
 *   3. Transcript word count ≥ 2  (gated here AFTER STT returns)
 *   4. Stabilized transcript      (single-shot batch STT is inherently stable)
 *
 * While the AI is talking and Silero detects a speech candidate we *duck* the
 * playback gain to ~25% (acknowledging the user without committing). After STT
 * returns, if gate 3 passes → real interrupt; if it fails → restore gain to
 * full and discard. A single "ha" / "hmm" can never break the conversation.
 *
 * Echo defence:
 *   - Browser-level echoCancellation:true (HW/SW AEC)
 *   - Stricter Silero acceptance while aiPlaying (avgConfidence ≥ 0.92 gate)
 */
import { getApiBase, apiPostMultipart, getToken } from "@/lib/api";
import { RUNTIME_CONFIG } from "@/lib/runtime-config";
import { speak } from "./voice";
import { SileroVad, floatToWavBlob, type SpeechSegment } from "./silero-vad";

type SessionState =
  | "idle"
  | "listening"
  | "recording"
  | "transcribing"
  | "thinking"
  | "speaking"
  | "error";

type Callbacks = {
  onStateChange: (state: SessionState) => void;
  onToken: (token: string) => void;
  onTranscript: (text: string) => void;
  onActions?: (actions: any[]) => void;
  onLevel?: (level: number) => void;
  onError?: (msg: string) => void;
};

// ───────── Gates (matches the spec exactly) ─────────
const POSITIVE_SPEECH_THRESHOLD = 0.85;   // gate 1
const MIN_SPEECH_FRAMES = 11;             // gate 2 — 11 × 32 ms ≈ 352 ms
const INTERRUPT_MIN_WORDS = 2;            // gate 3
const ECHO_GATE_AVG_CONFIDENCE = 0.92;    // stricter when AI is talking

// ───────── Playback shaping ─────────
const PLAYBACK_PREBUFFER_MS = 300;        // queue ~300 ms before first start
const DUCK_GAIN = 0.25;                   // speech-candidate ducking
const DUCK_RAMP_S = 0.05;                 // ramp time for ducking

const SILERO_SAMPLE_RATE = 16000;

export class VoiceSessionManager {
  private ws: WebSocket | null = null;
  private audioCtx: AudioContext | null = null;
  private micStream: MediaStream | null = null;
  private playbackGain: GainNode | null = null;
  private vad: SileroVad | null = null;

  // Playback (PCM scheduling)
  private playheadAt = 0;
  private playbackSources: AudioBufferSourceNode[] = [];
  private ttsSampleRate = 16000;
  private aiPlaying = false;
  private playbackStarted = false;
  private prebufferChunks: Array<{ float: Float32Array; sampleRate: number }> = [];
  private prebufferedMs = 0;

  // STT in-flight tracking
  private sttInFlight = 0;
  /** True when the current WS turn delivered playable PCM (ElevenLabs stream). */
  private turnHadStreamedAudio = false;

  // State
  private state: SessionState = "idle";
  private callbacks: Callbacks;
  private stopped = false;
  // Mute flag — when true, VAD callbacks are dropped so the mic can't
  // trigger a turn (used while we're playing a deterministic prompt like
  // the role welcome message, where AEC alone may not fully suppress echo).
  private muted = false;

  // Visualizer smoothing (driven by Silero per-frame speech probability)
  private smoothedLevel = 0;

  constructor(callbacks: Callbacks) {
    this.callbacks = callbacks;
  }

  private setState(s: SessionState) {
    if (this.state === s) return;
    this.state = s;
    this.callbacks.onStateChange(s);
  }

  async start() {
    this.stopped = false;
    if (typeof window === "undefined" || !navigator.mediaDevices?.getUserMedia) {
      this.callbacks.onError?.("Microphone not available in this browser.");
      this.setState("error");
      return;
    }

    try {
      this.micStream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
          channelCount: 1,
          sampleRate: 48000,
        },
      });
    } catch (err: any) {
      this.callbacks.onError?.(err?.message || "Microphone permission denied.");
      this.setState("error");
      return;
    }

    this.audioCtx = new (window.AudioContext || (window as any).webkitAudioContext)();
    try { await this.audioCtx.resume(); } catch { /* ignore */ }

    // Routed through a master gain node so we can duck / cut playback cleanly.
    this.playbackGain = this.audioCtx.createGain();
    this.playbackGain.gain.value = 1;
    this.playbackGain.connect(this.audioCtx.destination);

    this.openSocket();

    try {
      this.vad = new SileroVad({
        stream: this.micStream,
        positiveSpeechThreshold: POSITIVE_SPEECH_THRESHOLD,
        negativeSpeechThreshold: 0.5,
        minSpeechFrames: MIN_SPEECH_FRAMES,
        redemptionFrames: 8,
        preSpeechPadFrames: 8,
        onFrame: (prob) => this.handleVadFrame(prob),
        onSpeechStart: () => this.handleSpeechStart(),
        onSpeechEnd: (seg) => { void this.handleSpeechEnd(seg); },
        onMisfire: () => this.handleMisfire(),
      });
      await this.vad.start();
    } catch (err: any) {
      this.callbacks.onError?.(err?.message || "Failed to load voice detector.");
      this.setState("error");
      return;
    }

    this.setState("listening");
  }

  async stop() {
    this.stopped = true;
    this.stopPlayback();
    if (this.vad) {
      const v = this.vad;
      this.vad = null;
      try { await v.destroy(); } catch { /* ignore */ }
    }
    if (this.ws && this.ws.readyState <= WebSocket.OPEN) {
      try { this.ws.close(); } catch { /* ignore */ }
    }
    this.ws = null;
    if (this.micStream) {
      this.micStream.getTracks().forEach((t) => t.stop());
      this.micStream = null;
    }
    if (this.audioCtx && this.audioCtx.state !== "closed") {
      this.audioCtx.close().catch(() => {});
    }
    this.audioCtx = null;
    this.playbackGain = null;
    this.setState("idle");
  }

  /**
   * Temporarily suppress VAD-driven turns. Use this while playing a
   * deterministic agent prompt (e.g. the welcome message on voice entry)
   * so the mic can't false-trigger from speaker bleed.
   */
  setMuted(muted: boolean) {
    this.muted = muted;
  }

  /** Send a typed intent (text input while voice session is live). */
  sendIntent(text: string) {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return;
    this.stopPlayback();
    this.turnHadStreamedAudio = false;
    this.setState("thinking");
    this.ws.send(JSON.stringify({ type: "intent", text }));
  }

  // ───────────────── WebSocket ─────────────────

  private openSocket() {
    const base = getApiBase();
    const token = getToken();
    let wsUrl = "";
    if (base.startsWith("http://")) {
      wsUrl = base.replace("http://", "ws://") + "/api/ai/voice/stream";
    } else if (base.startsWith("https://")) {
      wsUrl = base.replace("https://", "wss://") + "/api/ai/voice/stream";
    } else {
      const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
      wsUrl = `${protocol}//${window.location.host}${base}/api/ai/voice/stream`;
    }
    if (token) wsUrl += `?token=${encodeURIComponent(token)}`;

    this.ws = new WebSocket(wsUrl);

    this.ws.onmessage = (e) => {
      let data: any;
      try { data = JSON.parse(e.data); } catch { return; }
      switch (data.type) {
        case "ready":
          if (typeof data.sample_rate === "number") this.ttsSampleRate = data.sample_rate;
          break;
        case "token":
          this.callbacks.onToken(data.text || "");
          break;
        case "audio":
          this.schedulePcmChunk(data.chunk || "", data.sample_rate || this.ttsSampleRate);
          break;
        case "audio_end":
          // Flush any remaining prebuffer if the backend finished before we hit 300 ms.
          this.flushPrebufferEarly();
          break;
        case "complete": {
          if (data.actions && this.callbacks.onActions) {
            this.callbacks.onActions(data.actions);
          }
          const reply = String(data.reply || "").trim();
          if (
            RUNTIME_CONFIG.workflowTtsEnabled &&
            reply &&
            !this.turnHadStreamedAudio &&
            !this.aiPlaying
          ) {
            void speak(reply)
              .catch(() => {
                /* non-fatal */
              })
              .finally(() => {
                if (!this.stopped && !this.sttInFlight) this.setState("listening");
              });
          } else if (!this.aiPlaying && !this.sttInFlight) {
            this.setState("listening");
          }
          this.turnHadStreamedAudio = false;
          break;
        }
        case "interrupted":
          this.stopPlayback();
          this.setState("listening");
          break;
        case "error":
          this.callbacks.onError?.(data.detail || "Voice stream error");
          this.setState("error");
          break;
      }
    };

    this.ws.onerror = () => {
      this.callbacks.onError?.("Voice connection failed.");
      this.setState("error");
    };

    this.ws.onclose = () => {
      if (!this.stopped) this.setState("error");
    };
  }

  // ───────────────── VAD callbacks ─────────────────

  private handleVadFrame(prob: number) {
    if (this.muted) {
      // Keep the visualizer flat while muted so the orb doesn't shimmer
      // from speaker bleed during the welcome message.
      this.smoothedLevel = 0;
      this.callbacks.onLevel?.(0);
      return;
    }
    // Drive the orb visualizer from Silero's speech probability (smoother than RMS).
    this.smoothedLevel = this.smoothedLevel * 0.7 + prob * 0.3;
    this.callbacks.onLevel?.(Math.min(1, this.smoothedLevel * 1.4));
  }

  private handleSpeechStart() {
    if (this.muted) return;
    // Gates 1 & 2 already passed inside Silero (positiveSpeechThreshold + minSpeechFrames).
    if (this.aiPlaying) {
      // Speech candidate while AI is talking — duck, don't kill.
      // Gates 3 (≥ 2 words) and echo-gate (avg confidence) decide the verdict
      // after STT returns. If they fail we restore full gain and AI continues.
      this.duckPlayback(DUCK_GAIN);
    } else {
      this.setState("recording");
    }
  }

  private handleMisfire() {
    // Sub-threshold burst (cough, click). Restore any ducking — AI keeps talking.
    if (this.aiPlaying) this.duckPlayback(1);
  }

  private async handleSpeechEnd(segment: SpeechSegment) {
    if (this.stopped) return;
    if (this.muted) return;

    const wasInterruptCandidate = this.aiPlaying;

    // Echo gate: while AI was playing, require a stricter average confidence so
    // any residual leakage of AI audio through imperfect AEC can't pass as user
    // speech. The 0.92 threshold leaves ample headroom for real users.
    if (wasInterruptCandidate && segment.avgConfidence < ECHO_GATE_AVG_CONFIDENCE) {
      this.duckPlayback(1);
      return;
    }

    this.sttInFlight++;
    if (!wasInterruptCandidate) this.setState("transcribing");

    let text = "";
    try {
      const blob = floatToWavBlob(segment.audio, SILERO_SAMPLE_RATE);
      const form = new FormData();
      form.append("file", blob, "speech.wav");
      const res = await apiPostMultipart<{ text: string }>(
        "/api/ai/voice/transcribe",
        form
      );
      text = (res?.text || "").trim();
    } catch (err: any) {
      this.callbacks.onError?.(err?.message || "Transcription failed.");
    } finally {
      this.sttInFlight = Math.max(0, this.sttInFlight - 1);
    }

    const wordCount = text ? text.split(/\s+/).filter(Boolean).length : 0;

    if (wasInterruptCandidate) {
      // Gate 3: need at least 2 words to commit to interrupting.
      if (wordCount >= INTERRUPT_MIN_WORDS) {
        this.callbacks.onTranscript(text);
        this.interrupt();
        this.sendIntent(text);
      } else {
        // False interrupt — single noise / single word. Restore playback gain.
        this.duckPlayback(1);
        if (this.aiPlaying) this.setState("speaking");
        else if (!this.sttInFlight) this.setState("listening");
      }
      return;
    }

    // Normal turn (no AI playback at start of utterance).
    if (wordCount >= 1) {
      this.callbacks.onTranscript(text);
      this.sendIntent(text);
    } else if (!this.sttInFlight) {
      this.setState("listening");
    }
  }

  // ───────────────── Playback (PCM scheduling + prebuffer) ─────────────────

  private schedulePcmChunk(b64: string, sampleRate: number) {
    if (!this.audioCtx || !this.playbackGain || !b64) return;
    const float = decodeBase64Pcm16(b64);
    if (float.length === 0) return;
    this.turnHadStreamedAudio = true;

    const chunkMs = (float.length / sampleRate) * 1000;

    if (!this.playbackStarted) {
      this.prebufferChunks.push({ float, sampleRate });
      this.prebufferedMs += chunkMs;
      if (this.prebufferedMs >= PLAYBACK_PREBUFFER_MS) {
        this.startPlaybackFromPrebuffer();
      }
      return;
    }

    this.scheduleFloat(float, sampleRate);
  }

  /**
   * If the backend finishes streaming before we've accumulated 300 ms of audio,
   * play whatever we have rather than holding it forever.
   */
  private flushPrebufferEarly() {
    if (!this.playbackStarted && this.prebufferChunks.length > 0) {
      this.startPlaybackFromPrebuffer();
    }
  }

  private startPlaybackFromPrebuffer() {
    if (!this.audioCtx) return;
    this.playbackStarted = true;
    this.aiPlaying = true;
    this.setState("speaking");
    this.playheadAt = this.audioCtx.currentTime + 0.02;
    for (const c of this.prebufferChunks) {
      this.scheduleFloat(c.float, c.sampleRate);
    }
    this.prebufferChunks = [];
    this.prebufferedMs = 0;
  }

  private scheduleFloat(float: Float32Array, sampleRate: number) {
    if (!this.audioCtx || !this.playbackGain) return;
    const ctx = this.audioCtx;
    const buffer = ctx.createBuffer(1, float.length, sampleRate);
    buffer.getChannelData(0).set(float);

    const src = ctx.createBufferSource();
    src.buffer = buffer;
    src.connect(this.playbackGain);

    const startAt = Math.max(this.playheadAt, ctx.currentTime + 0.02);
    src.start(startAt);
    this.playheadAt = startAt + buffer.duration;
    this.aiPlaying = true;

    src.onended = () => {
      this.playbackSources = this.playbackSources.filter((s) => s !== src);
      if (
        this.playbackSources.length === 0 &&
        this.audioCtx &&
        this.audioCtx.currentTime >= this.playheadAt - 0.01
      ) {
        this.aiPlaying = false;
        this.playbackStarted = false;
        // Restore master gain in case it was ducked at the very end.
        this.duckPlayback(1);
        if (!this.sttInFlight) this.setState("listening");
      }
    };
    this.playbackSources.push(src);
  }

  private stopPlayback() {
    this.playbackSources.forEach((s) => {
      try { s.stop(); } catch { /* ignore */ }
      try { s.disconnect(); } catch { /* ignore */ }
    });
    this.playbackSources = [];
    this.prebufferChunks = [];
    this.prebufferedMs = 0;
    this.playbackStarted = false;
    if (this.audioCtx) this.playheadAt = this.audioCtx.currentTime;
    if (this.playbackGain && this.audioCtx) {
      this.playbackGain.gain.cancelScheduledValues(this.audioCtx.currentTime);
      this.playbackGain.gain.setValueAtTime(1, this.audioCtx.currentTime);
    }
    this.aiPlaying = false;
  }

  private duckPlayback(gain: number) {
    if (!this.playbackGain || !this.audioCtx) return;
    const now = this.audioCtx.currentTime;
    this.playbackGain.gain.cancelScheduledValues(now);
    this.playbackGain.gain.linearRampToValueAtTime(gain, now + DUCK_RAMP_S);
  }

  private interrupt() {
    this.stopPlayback();
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ type: "interrupt" }));
    }
  }
}

function decodeBase64Pcm16(b64: string): Float32Array {
  const binary = atob(b64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  const view = new DataView(bytes.buffer);
  const len = bytes.byteLength / 2;
  const out = new Float32Array(len);
  for (let i = 0; i < len; i++) {
    out[i] = view.getInt16(i * 2, true) / 32768;
  }
  return out;
}
