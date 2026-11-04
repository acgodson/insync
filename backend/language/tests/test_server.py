"""The dev server over a real WebSocket (FastAPI TestClient)."""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch, tmp_path):
    for k, v in {"OFFLINE": "1", "STT": "none", "TTS_MODE": "app", "SIGN_PAUSE_S": "0.2",
                 "VOCAB_LOCAL": str(tmp_path / "v.json")}.items():
        monkeypatch.setenv(f"ALMERO_{k}", v)
    from language.server import app
    with TestClient(app) as c:
        yield c


def recv_until(ws, kind, limit=10):
    seen = []
    for _ in range(limit):
        m = ws.receive_json()
        seen.append(m)
        if m["type"] == kind:
            return m, seen
    raise AssertionError(f"no {kind}: {seen}")


def test_health_and_vocab(client):
    h = client.get("/health").json()
    assert h["ok"] and h["signs"] >= 30 and h["stt"] == "none"
    labels = [s["label"] for s in client.get("/vocab").json()["signs"]]
    assert "HELLO" in labels and "CANT-BREATHE" in labels


def test_both_directions_reach_every_client(client):
    with client.websocket_connect("/ws") as app_ws, client.websocket_connect("/ws") as ui:
        ui.send_json({"type": "ui_ready", "ts": 0, "view": "projector"})
        app_ws.send_json({"type": "profile", "ts": 0, "head": {}})
        app_ws.send_json({"type": "dev_say", "ts": 0, "text": "Where is the toilet?"})
        for ws in (app_ws, ui):
            cap, _ = recv_until(ws, "caption")
            play, _ = recv_until(ws, "avatar_play")
            assert cap["speaker"] == "bob" and play["signs"] == ["WHERE", "TOILET"]
        app_ws.send_json({"type": "sign_candidates", "ts": 0, "items": [{"label": "FIRE", "confidence": 0.9}]})
        s, _ = recv_until(ui, "sentence")
        assert s["text"] == "Fire! There's a fire!" and s["speaker"] == "alice"
        assert sorted(client.get("/health").json()["clients"]) == ["app", "projector"]


def test_bad_messages_dont_kill_the_socket(client):
    with client.websocket_connect("/ws") as ws:
        ws.send_text("not json")
        ws.send_json({"no": "type"})
        ws.send_json({"type": "frame", "ts": 0, "jpeg": "", "w": 504, "h": 896})  # recognition's, ignored
        ws.send_json({"type": "dev_say", "ts": 0, "text": "Hello"})
        m, _ = recv_until(ws, "avatar_play")
        assert m["signs"] == ["HELLO"]
