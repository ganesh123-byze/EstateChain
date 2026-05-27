"use client";

/**
 * Minimal voice client — ElevenLabs Scribe STT (backend) + ElevenLabs TTS (backend).
 *
 * Recording: MediaRecorder captures mic audio. We watch the live mic level
 * with a Web Audio analyser and auto-stop after ~1.4 s of silence so the
 * user doesn't have to click twice. Clicking the mic again cancels early.
 *
 * Playback: a single shared HTMLAudioElement. `stopSpeaking()` cancels any
 * in-flight TTS request and pauses playback so a new utterance can start
 * cleanly without overlap.
 */

import { apiPostMultipart, getApiBase, getToken } from "@/lib/api";
import { RUNTIME_CONFIG } from "@/lib/runtime-config";

const SILENCE_RMS = 0.012;
const SILENCE_HOLD_MS = 1400;
const MAX_RECORD_MS = 30_000;

/* -------------------------------------------------------------------------- */
/*  Recording                                                                 */
/* -------------------------------------------------------------------------- */

type RecorderHandle = {
  stop: () => void;
  cancel: () => void;
  done: Promise<Blob | null>;
};

let _recorder: RecorderHandle | null = null;

export function isRecording() {
  return _recorder !== null;
}

function pickMimeType(): string {
  const candidates = [
    "audio/webm;codecs=opus",
    "audio/webm",
    "audio/mp4",
    "audio/ogg;codecs=opus",
  ];
  for (const t of candidates) {
    if (typeof MediaRecorder !== "undefined" && MediaRecorder.isTypeSupported(t)) {
      return t;
    }
  }
  return "";
}

function fileExtForMime(mime: string): string {
  if (mime.includes("webm")) return "webm";
  if (mime.includes("mp4")) return "m4a";
  if (mime.includes("ogg")) return "ogg";
  return "webm";
}

async function startRecording(): Promise<RecorderHandle> {
  if (typeof window === "undefined" || !navigator.mediaDevices?.getUserMedia) {
    throw new Error("Microphone is not available in this browser.");
  }

  const stream = await navigator.mediaDevices.getUserMedia({
    audio: {
      echoCancellation: true,
      noiseSuppression: true,
      autoGainControl: true,
      channelCount: 1,
    },
  });

  const mimeType = pickMimeType();
  const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
  const chunks: BlobPart[] = [];
  let cancelled = false;
  let stopped = false;

  recorder.ondataavailable = (e) => {
    if (e.data && e.data.size > 0) chunks.push(e.data);
  };

  const audioCtx = new (window.AudioContext || (window as any).webkitAudioContext)();
  const source = audioCtx.createMediaStreamSource(stream);
  const analyser = audioCtx.createAnalyser();
  analyser.fftSize = 1024;
  source.connect(analyser);
  const buffer = new Float32Array(analyser.fftSize);

  let lastVoiceAt = performance.now();
  let sawVoice = false;
  let watchHandle = 0;

  const stop = () => {
    if (stopped) return;
    stopped = true;
    window.clearInterval(watchHandle);
    try {
      if (recorder.state !== "inactive") recorder.stop();
    } catch {
      /* ignore */
    }
    stream.getTracks().forEach((t) => t.stop());
    audioCtx.close().catch(() => {});
  };

  const cancel = () => {
    cancelled = true;
    stop();
  };

  const recordStartedAt = performance.now();
  watchHandle = window.setInterval(() => {
    analyser.getFloatTimeDomainData(buffer);
    let sumSq = 0;
    for (let i = 0; i < buffer.length; i++) sumSq += buffer[i] * buffer[i];
    const rms = Math.sqrt(sumSq / buffer.length);
    const now = performance.now();
    if (rms > SILENCE_RMS) {
      lastVoiceAt = now;
      sawVoice = true;
    }
    if (sawVoice && now - lastVoiceAt > SILENCE_HOLD_MS) {
      stop();
    } else if (now - recordStartedAt > MAX_RECORD_MS) {
      stop();
    }
  }, 100);

  const done: Promise<Blob | null> = new Promise((resolve) => {
    recorder.onstop = () => {
      if (cancelled || chunks.length === 0) {
        resolve(null);
        return;
      }
      const type = mimeType || "audio/webm";
      resolve(new Blob(chunks, { type }));
    };
  });

  recorder.start(250);
  return { stop, cancel, done };
}

/** Begin a recording session. Resolves with the transcribed text (or empty if cancelled). */
export async function recordAndTranscribe(): Promise<string> {
  if (_recorder) {
    return "";
  }
  const handle = await startRecording();
  _recorder = handle;
  try {
    const blob = await handle.done;
    if (!blob) return "";
    return await transcribeBlob(blob);
  } finally {
    if (_recorder === handle) _recorder = null;
  }
}

/** Stop the current recording early (still transcribes whatever was captured). */
export function stopRecording() {
  _recorder?.stop();
}

/** Cancel the current recording without transcribing. */
export function cancelRecording() {
  _recorder?.cancel();
  _recorder = null;
}

async function transcribeBlob(blob: Blob): Promise<string> {
  const ext = fileExtForMime(blob.type);
  const form = new FormData();
  form.append("file", blob, `speech.${ext}`);
  const res = await apiPostMultipart<{ text: string }>("/api/ai/voice/transcribe", form);
  return (res?.text || "").trim();
}

/* -------------------------------------------------------------------------- */
/*  Playback (TTS)                                                            */
/* -------------------------------------------------------------------------- */

let _audio: HTMLAudioElement | null = null;
let _ttsAbort: AbortController | null = null;
let _speaking = false;
const _speakingListeners = new Set<(v: boolean) => void>();

function setSpeaking(v: boolean) {
  if (_speaking === v) return;
  _speaking = v;
  _speakingListeners.forEach((cb) => cb(v));
}

export function isSpeaking() {
  return _speaking;
}

export function onSpeakingChange(cb: (v: boolean) => void): () => void {
  _speakingListeners.add(cb);
  cb(_speaking);
  return () => _speakingListeners.delete(cb);
}

/** Stop any current playback and abort any in-flight TTS fetch. */
export function stopSpeaking() {
  _ttsAbort?.abort();
  _ttsAbort = null;
  if (_audio) {
    try {
      _audio.pause();
      _audio.removeAttribute("src");
      _audio.load();
    } catch {
      /* ignore */
    }
    _audio = null;
  }
  setSpeaking(false);
}

function pickBrowserVoice(): SpeechSynthesisVoice | null {
  const synth = window.speechSynthesis;
  if (!synth) return null;
  const voices = synth.getVoices();
  if (!voices.length) return null;
  const wantFemale = RUNTIME_CONFIG.workflowTtsGender === "female";
  const hint = wantFemale
    ? /female|samantha|victoria|zira|aria|jenny|sonia/i
    : /male|daniel|david|mark|guy|ryan|andrew/i;
  return (
    voices.find((v) => hint.test(v.name) && v.lang.toLowerCase().startsWith("en")) ??
    voices.find((v) => v.lang.toLowerCase().startsWith("en")) ??
    voices[0] ??
    null
  );
}

async function waitForBrowserVoices(synth: SpeechSynthesis): Promise<void> {
  if (synth.getVoices().length > 0) return;
  await new Promise<void>((resolve) => {
    const done = () => resolve();
    synth.addEventListener("voiceschanged", done, { once: true });
    window.setTimeout(done, 300);
  });
}

async function speakWithBrowser(text: string, signal: AbortSignal): Promise<void> {
  const synth = window.speechSynthesis;
  if (!synth) throw new Error("Speech synthesis is not available in this browser.");

  await waitForBrowserVoices(synth);

  return new Promise<void>((resolve, reject) => {
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.rate = RUNTIME_CONFIG.workflowTtsRate;
    const voice = pickBrowserVoice();
    if (voice) utterance.voice = voice;

    const onAbort = () => {
      synth.cancel();
      setSpeaking(false);
      reject(new DOMException("Aborted", "AbortError"));
    };
    if (signal.aborted) {
      onAbort();
      return;
    }
    signal.addEventListener("abort", onAbort, { once: true });

    utterance.onend = () => {
      signal.removeEventListener("abort", onAbort);
      setSpeaking(false);
      resolve();
    };
    utterance.onerror = () => {
      signal.removeEventListener("abort", onAbort);
      setSpeaking(false);
      reject(new Error("Browser speech synthesis failed."));
    };

    setSpeaking(true);
    synth.cancel();
    synth.speak(utterance);
  });
}

async function playMp3Blob(blob: Blob, signal: AbortSignal): Promise<void> {
  const url = URL.createObjectURL(blob);
  const audio = new Audio(url);
  _audio = audio;
  setSpeaking(true);

  await new Promise<void>((resolve, reject) => {
    const cleanup = () => {
      URL.revokeObjectURL(url);
      if (_audio === audio) {
        _audio = null;
        setSpeaking(false);
      }
    };
    const finish = () => {
      cleanup();
      resolve();
    };
    const fail = () => {
      cleanup();
      reject(new Error("Audio playback failed."));
    };
    if (signal.aborted) {
      cleanup();
      reject(new DOMException("Aborted", "AbortError"));
      return;
    }
    signal.addEventListener(
      "abort",
      () => {
        try {
          audio.pause();
        } catch {
          /* ignore */
        }
        cleanup();
        reject(new DOMException("Aborted", "AbortError"));
      },
      { once: true },
    );
    audio.onended = finish;
    audio.onerror = fail;
    void audio.play().catch(fail);
  });
}

/** Fetch ElevenLabs MP3 from the backend, then play. Falls back to browser TTS. */
async function speakWithElevenLabs(text: string, signal: AbortSignal): Promise<void> {
  const base = getApiBase();
  const token = getToken();
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (token) headers.Authorization = `Bearer ${token}`;

  const response = await fetch(`${base}/api/ai/voice/speak`, {
    method: "POST",
    signal,
    headers,
    body: JSON.stringify({ text }),
  });

  if (!response.ok) {
    let detail = `TTS failed (${response.status})`;
    try {
      const body = await response.json();
      if (body?.detail) detail = String(body.detail);
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }

  const blob = await response.blob();
  if (signal.aborted) return;
  await playMp3Blob(blob, signal);
}

/**
 * Read assistant text aloud (ElevenLabs via backend, browser voice as fallback).
 * No-op when workflow TTS is disabled via NEXT_PUBLIC_WORKFLOW_TTS_ENABLED=false.
 */
export async function speak(text: string): Promise<void> {
  const clean = (text || "").trim();
  if (!clean || typeof window === "undefined" || !RUNTIME_CONFIG.workflowTtsEnabled) return;

  stopSpeaking();
  const abort = new AbortController();
  _ttsAbort = abort;

  try {
    await speakWithElevenLabs(clean, abort.signal);
  } catch (err) {
    if ((err as Error).name === "AbortError") return;
    stopSpeaking();
    const browserAbort = new AbortController();
    _ttsAbort = browserAbort;
    try {
      await speakWithBrowser(clean, browserAbort.signal);
    } catch (fallbackErr) {
      if ((fallbackErr as Error).name === "AbortError") return;
      throw fallbackErr;
    }
  } finally {
    if (_ttsAbort === abort) _ttsAbort = null;
  }
}

/** Call once on a user gesture to unlock audio autoplay on iOS/Safari. */
export function unlockAudio() {
  if (typeof window === "undefined") return;
  try {
    const a = new Audio();
    a.muted = true;
    a.src =
      "data:audio/mpeg;base64,SUQzBAAAAAAAI1RTU0UAAAAPAAADTGF2ZjU4Ljc2LjEwMAAAAAAAAAAAAAAA//tQwAAAAAAAAAAAAAAAAAAAAAAASW5mbwAAAA8AAAACAAABIADAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA//////////////////////////8AAAA8TEFNRTMuMTAwAc0AAAAAAAAAABRgJAJAQgAAYAAAASAaW4D3LAAAAAAAAAAAAAAAAA";
    void a.play().then(() => a.pause()).catch(() => {});
  } catch {
    /* ignore */
  }
}
