"""One signer's state: camera frames, segmentation, recognition, teaching, and the language module."""
import asyncio
import base64
import re
import time

import numpy as np

import config
import pipeline
from language.config import Settings
from language.module import LanguageModule
from toolkit import extract, segment

STOP_WORDS = {"a", "an", "the", "is", "are", "am", "to", "of", "in", "on", "at", "and", "or", "it", "this", "that",
              "i", "you", "we", "me", "my", "your", "do", "does", "did", "be", "was", "were", "so", "ok", "okay"}


class Session:
    def __init__(self, send, signer_name="Signer"):
        self.send = send                      # async fn(dict)
        self.signer_name = signer_name
        self.language = config.DEFAULT_LANGUAGE
        self.voice = ""
        self.live = True
        self.landmarker = pipeline.make_hand_landmarker()
        self.segmenter = pipeline.LiveSegmenter()
        self.library = pipeline.load_library(config.LIBRARY_DIR, self.language)
        self.teach_label = None               # label being taught, or None
        self.teach_takes = []                 # feature arrays collected so far
        self.collecting = False
        self.last_ts = 0
        self.latest = None                    # newest frame waiting for the worker
        self.frame_size = (504, 896)
        self.frame_event = asyncio.Event()
        self.frames_in = 0
        self.latencies = []
        # Ephraim's language & voice module: picks signs in context, composes the sentence,
        # glosses hearing speech into avatar signs. Speech-to-text stays on the phone / browser.
        self.lang = LanguageModule(self.send, Settings(
            stt_engine="text", speaker_signer=signer_name, speaker_hearing="Phone mic",
            min_conf=config.CONFIDENCE_THRESHOLD, sign_pause_s=config.SENTENCE_GAP_MS / 1000))
        for label in self.taught_labels:      # taught signs are usable in both directions
            self.lang.vocab.add_sign(label)
        self.tasks = [asyncio.create_task(self.lang.start()),
                      asyncio.create_task(self.worker()), asyncio.create_task(self.status_loop())]

    def close(self):
        for t in self.tasks:
            t.cancel()
        asyncio.ensure_future(self.lang.close())
        self.landmarker.close()

    @property
    def taught_labels(self):
        return sorted({t["label"] for t in self.library})

    async def emit(self, type_, **fields):
        await self.send({"type": type_, "ts": int(time.time() * 1000), **fields})

    # --- Incoming messages ---

    async def handle(self, m):
        t = m.get("type")
        self.seen_types = getattr(self, "seen_types", set())
        if t not in self.seen_types:
            self.seen_types.add(t)
            print(f"first message of type {t!r}: {str({k: (v[:40] + '...' if isinstance(v, str) and len(v) > 40 else v) for k, v in m.items()})}")
        if t == "ui_ready":
            await self.emit("status", latency_ms=0, fps=0)
        elif t == "session":
            self.live = m.get("state") != "paused"
            if not self.live:
                self.segmenter.reset()
                self.latest = None
                await self.emit("landmarks", hands=[])
        elif t == "settings":
            self.language = m.get("language") or self.language
            self.voice = m.get("voice") or self.voice
            self.library = pipeline.load_library(config.LIBRARY_DIR, self.language)
        elif t == "frame":
            if self.live:
                self.latest = (time.monotonic(), m)
                self.frame_event.set()
        elif t == "speech_text":
            if self.live:
                await self.on_speech(m.get("text", ""))
        elif t == "teach_start":
            self.teach_label = m.get("label") or self.teach_label or ""
            self.collecting = True
        elif t == "teach_stop":
            await self.on_teach_stop(m.get("label", ""))

    # --- Frames ---

    async def worker(self):
        while True:
            try:
                await asyncio.wait_for(self.frame_event.wait(), timeout=config.IDLE_FLUSH_S)
            except asyncio.TimeoutError:
                done = self.segmenter.flush()
                if done:
                    await self.on_segment(pipeline.features_from_segment(done, *self.frame_size))
                continue
            self.frame_event.clear()
            if self.latest is None:
                continue
            received, m = self.latest
            self.latest = None
            try:
                await self.process_frame(received, m)
            except Exception as e:  # never let one bad frame end the session
                print("frame error:", repr(e))

    async def process_frame(self, received, m):
        jpeg = base64.b64decode(m["jpeg"])
        image = extract.cv2.imdecode(np.frombuffer(jpeg, np.uint8), extract.cv2.IMREAD_COLOR)
        if image is None:
            return
        h, w = image.shape[:2]
        self.frame_size = (w, h)
        ts = max(int(m.get("ts") or 0), self.last_ts + 1)
        self.last_ts = ts
        hands = await asyncio.to_thread(pipeline.detect_hands, self.landmarker, image, ts)
        await self.emit("landmarks", hands=[hd for hd in pipeline.head_relative(hands, w, h) if hd["visible"]], w=w, h=h)
        self.frames_in += 1
        self.frames_total = getattr(self, "frames_total", 0) + 1
        if self.frames_total == 1 or self.frames_total % 100 == 0:
            print(f"frames received: {self.frames_total} ({w}x{h}), hands visible: {sum(h_['visible'] for h_ in hands.values())}")
        self.latencies.append((time.monotonic() - received) * 1000)
        done = self.segmenter.push(ts, hands)
        if done:
            await self.on_segment(pipeline.features_from_segment(done, w, h))

    # --- Recognition and teaching ---

    async def on_segment(self, features):
        if self.teach_label is not None and self.collecting:
            self.collecting = False
            self.teach_takes.append(features)
            await self.emit("teach_progress", label=self.teach_label, take=len(self.teach_takes), of=config.TAKES_REQUIRED)
            return
        ranked = pipeline.rank(features, self.library)
        items = [{"label": l, "confidence": round(c, 3)} for l, c in ranked[:3]]
        await self.emit("sign_candidates", items=items)
        if not items:
            await self.emit("unknown_sign")
            return
        # The language module picks the sign in context, emits sign_recognized / unknown_sign,
        # and composes the `sentence` after the signer pauses.
        await self.lang.on_sign_candidates(items)

    async def on_teach_stop(self, label):
        if label and self.teach_label is not None and len(self.teach_takes) >= config.TAKES_REQUIRED:
            self.save_takes(label, self.teach_takes, "glasses")
            await self.lang.on_teach_stop(label)
            await self.emit("sign_learned", label=label)
        self.teach_label, self.teach_takes, self.collecting = None, [], False

    def save_takes(self, label, takes, view):
        path = config.LIBRARY_DIR / self.language / f"{label}.json"
        records = [pipeline.take_record(t, "live", view) for t in takes]
        segment.append_takes(path, label, self.language, "phone", records)
        self.library = pipeline.load_library(config.LIBRARY_DIR, self.language)

    # --- Speech -> avatar (hearing side) ---

    async def on_speech(self, text, speaker="Phone mic"):
        """A hearing person's words: caption, then Claude-ordered signs for the avatar.
        If the gloss has no sign for the words (e.g. "whatsapp"), the avatar still fingerspells
        the content words instead of standing still."""
        self.lang.s.speaker_hearing = speaker
        self.lang.last_gloss = None
        await self.lang.on_text(text)
        res = getattr(self.lang, "last_gloss", None)
        if res is not None and not res.items:
            words = [w for w in re.findall(r"[A-Za-z0-9']+", text) if w.lower() not in STOP_WORDS][:3]
            if words:
                await self.emit("avatar_play", signs=[], fingerspell=[w.lower() for w in words])

    # --- Status ---

    async def status_loop(self):
        while True:
            await asyncio.sleep(config.STATUS_INTERVAL_S)
            fps = round(self.frames_in / config.STATUS_INTERVAL_S, 1)
            latency = int(np.mean(self.latencies)) if self.latencies else 0
            self.frames_in, self.latencies = 0, []
            await self.emit("status", latency_ms=latency, fps=fps)
