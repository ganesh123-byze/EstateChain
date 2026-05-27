"""ChatGPT-style duplex voice streaming.

Flow per turn:
  1. Frontend captures mic continuously; runs local VAD; on end-of-speech
     uploads the segment via /api/ai/voice/transcribe (HTTP, ElevenLabs Scribe).
  2. Frontend sends {"type": "intent", "text": "..."} over this WS.
  3. We stream LangGraph tokens to the frontend AND into ElevenLabs TTS WS.
     ElevenLabs returns PCM16 chunks (output_format=pcm_16000), which we
     forward to the browser. PCM is decode-safe per chunk (unlike chunked MP3)
     so playback can begin immediately with minimal latency.
  4. Frontend can send {"type": "interrupt"} for barge-in, which cancels the
     in-flight LLM + TTS streams.

Rapid back-to-back utterances are serialized (one turn at a time). A new intent
cancels the in-flight turn, always emits ``interrupted`` or ``complete`` so the
client leaves the "thinking" state, and the LangGraph stream is closed on cancel
so the worker cannot hang.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
from typing import AsyncIterator

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from backend.ai.agent import stream_agent
from backend.ai.checkpointer import get_saver
from backend.ai.chunk_buffer import SmartChunkBuffer
from backend.ai.config import get_settings
from backend.ai.schemas import ChatMessage
from backend.db.connection import get_connection
from backend.services.auth import AuthError, AuthUser, resolve_authenticated_user

LOGGER = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ai/voice", tags=["ai-voice"])

# ElevenLabs WS endpoint streams audio as base64 chunks in PCM at the requested rate.
_TTS_SAMPLE_RATE = 16000
_TTS_OUTPUT_FORMAT = f"pcm_{_TTS_SAMPLE_RATE}"

# Hard limits so a stuck LLM/TTS turn cannot wedge the voice worker forever.
_VOICE_TURN_TIMEOUT_SEC = 120.0
_CANCEL_JOIN_TIMEOUT_SEC = 12.0


async def _elevenlabs_tts_stream(
    text_chunks: asyncio.Queue,
    out_audio: asyncio.Queue,
    cancel: asyncio.Event,
    voice_id: str,
) -> None:
    """Pump LLM token chunks into ElevenLabs WS TTS; push PCM bytes to ``out_audio``.

    ``text_chunks`` carries str pieces. A ``None`` sentinel signals end-of-text.
    Pushes ``None`` to ``out_audio`` when finished (success, cancel, or error).
    """
    settings = get_settings()
    if not settings.elevenlabs_api_key:
        await out_audio.put(None)
        return

    import websockets

    url = (
        f"wss://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream-input"
        f"?model_id={settings.elevenlabs_model}"
        f"&output_format={_TTS_OUTPUT_FORMAT}"
        f"&inactivity_timeout=20"
    )

    try:
        async with websockets.connect(url, max_size=8 * 1024 * 1024) as ws:
            await ws.send(json.dumps({
                "text": " ",
                "voice_settings": {
                    "stability": 0.45,
                    "similarity_boost": 0.8,
                    "style": 0.15,
                    "use_speaker_boost": True,
                },
                "generation_config": {
                    "chunk_length_schedule": [80, 120, 180, 250],
                },
                "xi_api_key": settings.elevenlabs_api_key,
            }))

            async def pump_text():
                while True:
                    if cancel.is_set():
                        try:
                            await ws.send(json.dumps({"text": ""}))
                        except Exception:
                            pass
                        return
                    try:
                        chunk = await asyncio.wait_for(text_chunks.get(), timeout=0.1)
                    except asyncio.TimeoutError:
                        continue
                    if chunk is None:
                        await ws.send(json.dumps({"text": " ", "flush": True}))
                        await ws.send(json.dumps({"text": ""}))
                        return
                    if not chunk:
                        continue
                    await ws.send(json.dumps({"text": chunk, "try_trigger_generation": True}))

            send_task = asyncio.create_task(pump_text())

            try:
                while True:
                    if cancel.is_set():
                        break
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=0.2)
                    except asyncio.TimeoutError:
                        if cancel.is_set():
                            break
                        continue
                    try:
                        data = json.loads(raw)
                    except (TypeError, ValueError):
                        continue
                    audio_b64 = data.get("audio")
                    if audio_b64:
                        try:
                            pcm = base64.b64decode(audio_b64)
                            await out_audio.put(pcm)
                        except Exception as exc:  # noqa: BLE001
                            LOGGER.warning("TTS chunk decode error: %s", exc)
                    if data.get("isFinal"):
                        break
            finally:
                send_task.cancel()
                try:
                    await send_task
                except Exception:
                    pass
    except Exception as exc:  # noqa: BLE001
        LOGGER.error("ElevenLabs TTS WS failed: %s", exc)
    finally:
        await out_audio.put(None)


def _anonymous() -> AuthUser:
    return AuthUser(
        id=0,
        wallet_address="0x0000000000000000000000000000000000000000",
        role="investor",
        email=None,
        kyc_status="unverified",
        active=True,
    )


def _authenticate(token: str | None) -> AuthUser:
    """Resolve the JWT from the query param into an AuthUser; anon on failure."""
    if not token:
        return _anonymous()
    db = None
    try:
        db = get_connection()
        return resolve_authenticated_user(db, token)
    except AuthError:
        return _anonymous()
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("Voice WS auth failed: %s", exc)
        return _anonymous()
    finally:
        if db is not None:
            try:
                db.close()
            except Exception:
                pass


async def _stream_agent_events(
    user: AuthUser,
    history: list[ChatMessage],
    db,
    *,
    thread_id: str,
    checkpointer,
    cancel: asyncio.Event,
) -> AsyncIterator[dict]:
    """Wrap ``stream_agent`` so cancel closes the async generator (no orphan LLM work)."""
    agen = stream_agent(user, history, db, thread_id=thread_id, checkpointer=checkpointer)
    try:
        async for event in agen:
            if cancel.is_set():
                break
            yield event
    finally:
        await agen.aclose()


@router.websocket("/stream")
async def voice_duplex_stream(websocket: WebSocket, token: str | None = Query(default=None)):
    """Persistent duplex voice channel for the chat UI."""
    await websocket.accept()

    user = _authenticate(token)
    thread_id = f"voice:{user.wallet_address or user.id}"

    # State for the *current* in-flight turn so we can cancel on interrupt.
    cur_cancel: asyncio.Event | None = None
    cur_text_q: asyncio.Queue | None = None
    cur_tasks: list[asyncio.Task] = []
    cur_assistant_replied: bool = False

    # Serialize voice turns — rapid back-to-back utterances are queued so we
    # never start a second turn before the first has fully torn down.
    intent_queue: asyncio.Queue[str | None] = asyncio.Queue()
    intent_worker: asyncio.Task | None = None
    turn_lock = asyncio.Lock()
    turn_active = False

    # Server-side conversation history. The HTTP /chat path receives the full
    # transcript from the client every turn, but the voice WS only receives the
    # latest user utterance, so we must remember prior turns here.
    history: list[ChatMessage] = []

    def _rollback_incomplete_user_turn() -> None:
        """Drop the last user line if this turn never produced an assistant reply."""
        if history and history[-1].role == "user":
            history.pop()

    async def _cancel_current(*, rollback_user: bool = True) -> None:
        nonlocal cur_cancel, cur_text_q, cur_tasks, cur_assistant_replied
        if cur_cancel:
            cur_cancel.set()
        if cur_text_q is not None:
            try:
                cur_text_q.put_nowait(None)
            except Exception:
                pass
        for t in cur_tasks:
            if not t.done():
                t.cancel()
        if cur_tasks:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*cur_tasks, return_exceptions=True),
                    timeout=_CANCEL_JOIN_TIMEOUT_SEC,
                )
            except asyncio.TimeoutError:
                LOGGER.warning("Voice turn task cancel timed out after %.0fs", _CANCEL_JOIN_TIMEOUT_SEC)
        if rollback_user and not cur_assistant_replied:
            _rollback_incomplete_user_turn()
        cur_cancel = None
        cur_text_q = None
        cur_tasks = []
        cur_assistant_replied = False

    async def _safe_send(payload: dict) -> None:
        try:
            await websocket.send_json(payload)
        except Exception:
            pass

    async def _finish_turn_client_state(*, turn_completed: bool, partial_reply: str = "") -> None:
        """Ensure the UI leaves 'thinking' even when a turn was cancelled mid-flight."""
        if not turn_completed:
            if partial_reply.strip():
                await _safe_send({
                    "type": "complete",
                    "reply": partial_reply.strip(),
                    "actions": [],
                })
            else:
                await _safe_send({"type": "interrupted"})

    async def _execute_turn(user_text: str) -> tuple[bool, str]:
        """Run one voice turn. Returns (complete_sent, partial_reply_text)."""
        nonlocal cur_cancel, cur_text_q, cur_tasks, cur_assistant_replied, turn_active

        await _cancel_current(rollback_user=False)
        cancel = asyncio.Event()
        text_q: asyncio.Queue = asyncio.Queue()
        audio_q: asyncio.Queue = asyncio.Queue()
        cur_cancel = cancel
        cur_text_q = text_q
        cur_assistant_replied = False
        turn_completed = False
        partial_reply = ""

        voice_id = get_settings().elevenlabs_voice_id
        history.append(ChatMessage(role="user", content=user_text))

        async def llm_pump():
            nonlocal cur_assistant_replied, turn_completed, partial_reply
            checkpointer = await get_saver()
            full_text = ""
            chunker = SmartChunkBuffer(min_chars=25, max_chars=60)
            db = None
            try:
                db = get_connection()
            except Exception as exc:  # noqa: BLE001
                LOGGER.warning("Voice turn: DB connect failed (read-only mode): %s", exc)
                db = None
            try:
                async for event in _stream_agent_events(
                    user,
                    history,
                    db,
                    thread_id=thread_id,
                    checkpointer=checkpointer,
                    cancel=cancel,
                ):
                    if event.get("type") == "token":
                        delta = event.get("content") or ""
                        if delta:
                            full_text += delta
                            partial_reply = full_text
                            await _safe_send({"type": "token", "text": delta})
                            for chunk in chunker.feed(delta):
                                await text_q.put(chunk + " ")
                    elif event.get("type") == "tool_start":
                        await _safe_send({
                            "type": "tool_start",
                            "name": event.get("name", ""),
                        })
                    elif event.get("type") == "complete":
                        actions = event.get("actions") or []
                        reply = event.get("reply") or full_text
                        partial_reply = reply or full_text
                        tail = chunker.flush()
                        if tail:
                            await text_q.put(tail + " ")
                        elif not full_text and reply:
                            await text_q.put(reply)
                        if reply:
                            history.append(ChatMessage(role="assistant", content=reply))
                            cur_assistant_replied = True
                        await _safe_send({
                            "type": "complete",
                            "reply": reply,
                            "actions": actions,
                        })
                        turn_completed = True
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                LOGGER.exception("LLM pump failed: %s", exc)
                await _safe_send({"type": "error", "detail": str(exc)[:200]})
            finally:
                if db is not None:
                    try:
                        db.close()
                    except Exception:
                        pass
                tail = chunker.flush()
                if tail and not cancel.is_set():
                    try:
                        await text_q.put(tail + " ")
                    except Exception:
                        pass
                try:
                    await text_q.put(None)
                except Exception:
                    pass

        async def tts_pump():
            await _elevenlabs_tts_stream(text_q, audio_q, cancel, voice_id)

        async def audio_pump():
            while True:
                if cancel.is_set():
                    try:
                        while True:
                            chunk = audio_q.get_nowait()
                            if chunk is None:
                                return
                    except asyncio.QueueEmpty:
                        pass
                    return
                chunk = await audio_q.get()
                if chunk is None:
                    await _safe_send({"type": "audio_end"})
                    return
                try:
                    await websocket.send_json({
                        "type": "audio",
                        "chunk": base64.b64encode(chunk).decode("ascii"),
                        "sample_rate": _TTS_SAMPLE_RATE,
                    })
                except Exception:
                    return

        cur_tasks = [
            asyncio.create_task(llm_pump()),
            asyncio.create_task(tts_pump()),
            asyncio.create_task(audio_pump()),
        ]

        try:
            await asyncio.gather(*cur_tasks, return_exceptions=True)
        except Exception as exc:  # noqa: BLE001
            LOGGER.exception("Voice turn gather failed: %s", exc)

        return turn_completed, partial_reply

    async def _intent_worker() -> None:
        """Process one voice intent at a time; always reset client state after each turn."""
        nonlocal turn_active
        while True:
            user_text = await intent_queue.get()
            if user_text is None:
                return
            turn_completed = False
            partial_reply = ""
            async with turn_lock:
                turn_active = True
                try:
                    turn_completed, partial_reply = await asyncio.wait_for(
                        _execute_turn(user_text),
                        timeout=_VOICE_TURN_TIMEOUT_SEC,
                    )
                except asyncio.TimeoutError:
                    LOGGER.warning("Voice turn timed out after %.0fs", _VOICE_TURN_TIMEOUT_SEC)
                    await _cancel_current()
                    await _safe_send({
                        "type": "error",
                        "detail": "Voice response timed out. Please try again.",
                    })
                except Exception as exc:  # noqa: BLE001
                    LOGGER.exception("Voice intent worker failed: %s", exc)
                    await _cancel_current()
                    await _safe_send({"type": "error", "detail": str(exc)[:200]})
                finally:
                    turn_active = False
                    await _finish_turn_client_state(
                        turn_completed=turn_completed,
                        partial_reply=partial_reply,
                    )

    async def _enqueue_intent(text: str) -> None:
        """Cancel any in-flight turn, coalesce backlog to the latest utterance, queue it."""
        async with turn_lock:
            if turn_active or cur_tasks:
                await _cancel_current()
            while not intent_queue.empty():
                try:
                    intent_queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
            await intent_queue.put(text)

    try:
        await websocket.send_json({"type": "ready", "sample_rate": _TTS_SAMPLE_RATE})
        intent_worker = asyncio.create_task(_intent_worker())
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except (TypeError, ValueError):
                continue
            kind = msg.get("type")
            if kind == "intent":
                text = (msg.get("text") or "").strip()
                if text:
                    await _enqueue_intent(text)
            elif kind == "interrupt":
                async with turn_lock:
                    await _cancel_current()
                    while not intent_queue.empty():
                        try:
                            intent_queue.get_nowait()
                        except asyncio.QueueEmpty:
                            break
                await _safe_send({"type": "interrupted"})
            elif kind == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # noqa: BLE001
        LOGGER.error("Voice WS error: %s", exc)
    finally:
        if intent_worker is not None:
            try:
                await intent_queue.put(None)
            except Exception:
                pass
            try:
                await asyncio.wait_for(intent_worker, timeout=5.0)
            except Exception:
                intent_worker.cancel()
        await _cancel_current(rollback_user=False)
        try:
            await websocket.close()
        except Exception:
            pass
