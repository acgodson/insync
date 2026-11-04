"""Language-only WebSocket server: the frozen contract over a real socket.

Lets the Flutter app and the web UI connect to Cluster C before the full backend
exists, and shows integration exactly how the module is wired.

    cd backend
    uvicorn language.server:app --host 0.0.0.0 --port 8000

    ws://<laptop-ip>:8000/ws    the contract (send ui_ready first if you're a UI)
    GET /health                 what's running (Claude on/off, voice chain, clients)
    GET /vocab                  the sign labels, for recognition and the avatar

Every message the module emits goes to every connected client. Dev-only message
types start with `dev_` so they can never collide with the contract.
"""
from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from .config import Settings
from .module import LanguageModule

log = logging.getLogger("almero.language.server")

LANGUAGE_TYPES = {"audio", "teach_stop", "profile"}
RECOGNITION_TYPES = {"frame", "motion", "teach_start"}  # Cluster B's; accepted and ignored here


class Hub:
    """Connected clients and what they are (phone, projector, app...)."""

    def __init__(self):
        self.clients: dict[WebSocket, str] = {}

    async def broadcast(self, msg: dict) -> None:
        for ws in list(self.clients):
            try:
                await ws.send_json(msg)
            except Exception:
                self.clients.pop(ws, None)


hub = Hub()
state: dict = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    for noisy in ("httpx", "httpx2", "huggingface_hub", "faster_whisper"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    s = Settings()
    lang = LanguageModule(hub.broadcast, s)
    await lang.start()
    state.update(lang=lang, settings=s, ignored=0)
    yield
    await lang.close()


app = FastAPI(title="Almero language service", lifespan=lifespan)


@app.get("/health")
async def health():
    lang: LanguageModule = state["lang"]
    s: Settings = state["settings"]
    return {
        "ok": True,
        "claude": s.claude_model if lang.claude.enabled else "off (rule-based fallback)",
        "stt": lang.stt.name,
        "tts_mode": s.tts_mode,
        "tts": lang.tts.describe() if s.tts_mode != "app" else "app speaks `sentence` itself",
        "signs": len(lang.vocab.labels),
        "clients": sorted(hub.clients.values()),
        "recognition_messages_ignored": state.get("ignored", 0),
    }


@app.get("/vocab")
async def vocab():
    v = state["lang"].vocab
    return {"language": v.language, "signs": [
        {"label": s.label, "english": s.english, "tier": s.tier, "emergency": s.emergency}
        for s in sorted(v.signs.values(), key=lambda s: s.label)]}


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    hub.clients[ws] = "client"
    lang: LanguageModule = state["lang"]
    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
                t = msg["type"]
            except (ValueError, KeyError, TypeError):
                log.warning("dropped malformed message: %.120s", raw)
                continue
            try:
                if t == "ui_ready":
                    hub.clients[ws] = msg.get("view", "ui")
                    log.info("UI connected: %s", hub.clients[ws])
                elif t in LANGUAGE_TYPES:
                    if t == "profile":
                        hub.clients[ws] = "app"
                    await lang.handle(msg)
                elif t == "sign_candidates":
                    # In the full backend this is an in-process call from recognition/.
                    # Don't block this socket's audio while Claude picks; order is kept by the module's lock.
                    asyncio.ensure_future(lang.on_sign_candidates(msg["items"]))
                elif t == "dev_say":          # typed speech, for testing without a mic
                    await lang.on_text(msg["text"])
                elif t == "dev_end":          # end Alice's utterance now
                    await lang.end_signing()
                elif t == "dev_flush_audio":  # end Bob's utterance now (push-to-talk release)
                    await lang.flush_audio()
                elif t in RECOGNITION_TYPES:
                    state["ignored"] = state.get("ignored", 0) + 1
                else:
                    log.warning("unknown message type %r", t)
            except Exception:
                log.exception("error handling %s", t)  # one bad message never kills the socket
    except WebSocketDisconnect:
        pass
    finally:
        hub.clients.pop(ws, None)
