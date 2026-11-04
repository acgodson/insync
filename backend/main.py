"""InSync service: room server at /ws, rooms and join page over HTTP, teach upload and library."""
import asyncio
import json
import logging
import uuid

from pathlib import Path

from fastapi import FastAPI, File, Form, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

import config
import pipeline
import rooms
from toolkit import segment

logging.basicConfig(level=logging.INFO, format="%(name)s %(message)s")   # language module: Claude / voice status
for noisy in ("httpx", "httpcore", "huggingface_hub"):
    logging.getLogger(noisy).setLevel(logging.WARNING)

app = FastAPI(title="InSync service")
NO_CACHE = {"Cache-Control": "no-cache, must-revalidate"}   # browsers must re-check the HTML after each deploy
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])  # uploads from the app's WebView


@app.get("/health")
def health():
    return {"ok": True, "threshold": config.CONFIDENCE_THRESHOLD, "takes_required": config.TAKES_REQUIRED}


@app.get("/library")
def library(language: str = config.DEFAULT_LANGUAGE):
    out = []
    for path in sorted((config.LIBRARY_DIR / language).glob("*.json")):
        lib = json.loads(path.read_text())
        views = [t.get("view", "glasses") for t in lib["takes"]]
        out.append({"label": lib["label"], "takes": len(lib["takes"]), "view": max(set(views), key=views.count) if views else ""})
    return out


@app.post("/teach/upload")
async def teach_upload(label: str = Form(...), file: UploadFile = File(...), language: str = Form(config.DEFAULT_LANGUAGE)):
    config.UPLOAD_DIR.mkdir(exist_ok=True)
    tmp = config.UPLOAD_DIR / f"{uuid.uuid4().hex}_{file.filename or 'take'}"
    try:
        tmp.write_bytes(await file.read())
        data, n_frames = await asyncio.to_thread(pipeline.take_from_video, tmp)
    except ValueError as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=422)
    finally:
        tmp.unlink(missing_ok=True)   # never persist video
    path = config.LIBRARY_DIR / language / f"{label}.json"
    total = segment.append_takes(path, label, language, "upload", [pipeline.take_record(data, "upload", "front")])
    return {"ok": True, "label": label, "takes": total, "frames": n_frames, "view": "front"}


# --- Rooms ---

@app.post("/rooms")
def create_room(request: Request):
    room = rooms.create()
    host = request.headers.get("host", "localhost:8000")
    return {"code": room.code, "link": f"{request.url.scheme}://{host}/join/{room.code}"}


@app.get("/rooms/{code}")
def get_room(code: str):
    room = rooms.rooms.get(code.upper())
    if not room:
        return JSONResponse({"error": "no such room"}, status_code=404)
    return {"code": room.code, "participants": room.people()}


@app.get("/")
def root_page():
    """The hosted signer UI is the front door: open it in any browser with a webcam."""
    return FileResponse(Path(__file__).parent.parent / "web" / "dist" / "index.html", headers=NO_CACHE)


@app.get("/app")
def signer_page():
    """Signer web UI (web/dist/index.html) for the phone's prod mode or a laptop browser (?service=...)."""
    return FileResponse(Path(__file__).parent.parent / "web" / "dist" / "index.html", headers=NO_CACHE)


@app.get("/join/{code}")
def join_page(code: str):
    """The join link opens the same meeting-room page as the signer, in participant mode (Speak / Sign choice)."""
    return FileResponse(Path(__file__).parent.parent / "web" / "dist" / "index.html", headers=NO_CACHE)


@app.get("/join-lite/{code}")
def join_lite_page(code: str):
    """The old lightweight participant page (captions and voice only), kept as a fallback."""
    return FileResponse(Path(__file__).parent / "static" / "join.html", headers=NO_CACHE)


# --- WebSocket: /ws?room=<code>&role=signer|participant&name=<name> ---

@app.websocket("/ws")
async def ws(socket: WebSocket, room: str = "", role: str = "signer", name: str = ""):
    await socket.accept()
    code = room.upper()
    signer = role != "participant"
    r = rooms.rooms.get(code)
    if r is None:
        if not signer:
            await socket.close(code=4404, reason="no such room")
            return
        r = rooms.create(code or None)   # unknown code or no code: create it (private room without a code)
    if signer:
        await r.join_signer(socket, name or "Signer")
    else:
        await r.join_participant(socket, name or "Guest")
    try:
        while True:
            try:
                m = json.loads(await socket.receive_text())
            except json.JSONDecodeError:
                continue
            if not isinstance(m, dict):
                continue
            try:
                if not signer:
                    await r.handle_participant(socket, m)
                elif r.signer is socket and r.session:
                    await r.session.handle(m)
            except Exception as e:  # keep the connection alive on any handler error
                print("message error:", m.get("type"), repr(e))
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        await r.leave(socket)
