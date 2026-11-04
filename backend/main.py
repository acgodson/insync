"""InSync service: WebSocket contract at /ws, teach upload and library over HTTP."""
import asyncio
import json
import uuid

from fastapi import FastAPI, File, Form, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

import config
import pipeline
from session import Session
from toolkit import segment

app = FastAPI(title="InSync service")


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


@app.websocket("/ws")
async def ws(socket: WebSocket):
    await socket.accept()
    session = Session(lambda m: socket.send_text(json.dumps(m)))
    try:
        while True:
            try:
                m = json.loads(await socket.receive_text())
            except json.JSONDecodeError:
                continue
            try:
                await session.handle(m)
            except Exception as e:  # keep the connection alive on any handler error
                print("message error:", m.get("type"), repr(e))
    except WebSocketDisconnect:
        pass
    finally:
        session.close()
