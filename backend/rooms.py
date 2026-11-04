"""Rooms: one signer (with its recognition Session) and any number of browser participants."""
import json
import random
import time

from session import Session

CODE_LETTERS = "ABCDEFGHJKMNPQRSTUVWXYZ"   # no I, L, O
rooms = {}                                  # code -> Room
ROOM_TTL_S = 3 * 3600                       # an empty room is kept this long so reconnects and late joiners find it


def new_code():
    while True:
        code = "".join(random.choice(CODE_LETTERS) for _ in range(4))
        if code not in rooms:
            return code


def create(code=None):
    code = code or new_code()
    rooms[code] = Room(code)
    return rooms[code]


def message(type_, **fields):
    return {"type": type_, "ts": int(time.time() * 1000), **fields}


async def send_to(ws, m):
    try:
        await ws.send_text(json.dumps(m))
    except Exception:   # a dead socket never breaks the room
        pass


class Room:
    def __init__(self, code):
        self.code = code
        self.signer = None          # websocket or None
        self.signer_name = "Signer"
        self.participants = []      # [{"name", "ws"}]
        self.session = None
        self.last_active = time.time()

    def people(self):
        out = [{"name": self.signer_name, "role": "signer"}] if self.signer else []
        return out + [{"name": p["name"], "role": "participant"} for p in self.participants]

    @property
    def empty(self):
        return self.signer is None and not self.participants

    # --- Sending ---

    async def to_signer(self, m):
        if self.signer:
            await send_to(self.signer, m)

    async def to_participants(self, m):
        for p in list(self.participants):
            await send_to(p["ws"], m)

    async def to_all(self, m):
        await self.to_signer(m)
        await self.to_participants(m)

    async def broadcast_room(self):
        await self.to_all(message("room", code=self.code, participants=self.people()))

    # --- Session output: everything goes to the signer, some of it to participants too ---

    async def on_session_emit(self, m):
        await self.to_signer(m)
        if m["type"] == "sentence" and m.get("text"):
            await self.to_participants(message("caption", speaker=m["speaker"], text=m["text"]))
            await self.to_participants(message("speak", text=m["text"]))
            # TODO(phase2): Claude ordering before speaking, ElevenLabs voice server-side
        elif m["type"] == "caption":   # phone mic or a participant's words, captioned for everyone
            await self.to_participants(m)
        elif m["type"] == "speech_audio":   # ElevenLabs voice for the signer's sentence: participants play it
            await self.to_participants(m)
        elif m["type"] == "landmarks":   # the signer's hand traces, drawn on the signer's tile for participants
            await self.to_participants(m)

    # --- Joining and leaving ---

    async def join_signer(self, ws, name):
        self.last_active = time.time()
        old = self.signer
        self.signer, self.signer_name = ws, name
        if old is not None:
            try:
                await old.close(code=4000, reason="replaced by another signer")
            except Exception:
                pass
        if self.session is None:
            self.session = Session(self.on_session_emit, name)
        self.session.signer_name = name   # a replacing signer brings its own name
        self.session.lang.s.speaker_signer = name
        await self.broadcast_room()

    async def join_participant(self, ws, name):
        self.last_active = time.time()
        self.participants.append({"name": name, "ws": ws})
        await self.broadcast_room()

    async def leave(self, ws):
        if self.signer is ws:
            self.signer = None
        self.participants = [p for p in self.participants if p["ws"] is not ws]
        self.last_active = time.time()
        if self.empty:
            # Keep the room (code, link) alive for ROOM_TTL_S; the recognition session is rebuilt on the next signer join
            if self.session:
                self.session.close()
                self.session = None
        else:
            await self.broadcast_room()

    # --- Participant messages ---

    async def handle_participant(self, ws, m):
        who = next((p["name"] for p in self.participants if p["ws"] is ws), "Guest")
        print(f"room {self.code}: participant {who} sent {m.get('type')!r} {str(m.get('text', ''))[:60]!r}")
        if m.get("type") != "speech_text":
            return
        text = (m.get("text") or "").strip()
        if not text:
            return
        name = next((p["name"] for p in self.participants if p["ws"] is ws), "Guest")
        if self.session:
            # The session emits caption (routed to everyone below) and avatar_play (signer only)
            await self.session.on_speech(text, speaker=name)
        else:
            await self.to_participants(message("caption", speaker=name, text=text))


def sweep():
    """Drop rooms that have been empty for longer than ROOM_TTL_S."""
    now = time.time()
    for code, r in list(rooms.items()):
        if r.empty and now - r.last_active > ROOM_TTL_S:
            rooms.pop(code, None)
