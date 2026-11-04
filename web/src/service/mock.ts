// A fake backend that speaks the contract, so the room works with no service.
// Windows in the same browser share a room, which is how the one-laptop mode works.
// Anyone missing gets a bot: a Sam for Alice, an Alice for Sam.
import { KNOWN_SIGNS } from "../avatar/signs";
import { store } from "../ui/dom";
import { matchScore, toSequence, type Pt } from "../ui/handtrack";
import type { Draft, Hand, Participant, Point3, ServiceMessage, UiMessage } from "./contract";

const SYNONYMS: Record<string, string> = { hi: "hello", thanks: "thank", i: "me", ok: "okay", fractions: "fraction" };
const EXTRA_WORDS = ["everyone", "quick", "can", "take", "client", "call", "monday", "ten", "time", "clock"];

const FPS = 15;
const TAKES = 2;
const BASE_LIBRARY = ["yes", "no", "help", "thanks", "question", "time"];
const NEW_SIGNS = ["newsign", "water", "custom"];
const DISTRACTORS = ["sit", "give", "stop", "half", "two", "number"];
const ACCEPT = 0.6;

const SPOTS: Record<string, Point3> = {
  rest: [0.3, -0.5, 0],
  chest_low: [0.1, 0.25, 0],
  chest: [0.08, 0.05, 0],
  chest_side: [0.45, 0.1, 0],
  chin: [0.05, -0.05, 0],
  mouth: [0, -0.2, 0],
  forward: [0.2, -0.1, 0.4],
  forehead: [0.1, -0.5, 0],
  ear: [0.5, -0.3, 0],
};

const GESTURES: Record<string, { path: string[]; ms: number; curl: number }> = {
  yes: { path: ["rest", "chest", "chin", "chest", "chin", "rest"], ms: 1800, curl: 0.9 },
  no: { path: ["rest", "chest", "chest_side", "chest", "rest"], ms: 1500, curl: 0.5 },
  help: { path: ["rest", "chest_low", "chest", "chin", "rest"], ms: 1700, curl: 0.4 },
  thanks: { path: ["rest", "chin", "mouth", "forward", "rest"], ms: 1600, curl: 0 },
  question: { path: ["rest", "chest_side", "forward", "chest", "rest"], ms: 1600, curl: 0.6 },
  time: { path: ["rest", "chest", "chest_side", "chest", "rest"], ms: 1400, curl: 0.7 },
  newsign: { path: ["rest", "chest", "forehead", "ear", "chest", "rest"], ms: 2000, curl: 0.2 },
  water: { path: ["rest", "chin", "mouth", "chin", "mouth", "rest"], ms: 1800, curl: 0.3 },
  custom: { path: ["rest", "chest_side", "chin", "chest_side", "rest"], ms: 1700, curl: 0.5 },
};

function pathAt(path: string[], p: number): Point3 {
  const x = Math.min(p, 0.9999) * (path.length - 1);
  const i = Math.floor(x);
  const raw = x - i;
  const t = raw * raw * (3 - 2 * raw);
  const a = SPOTS[path[i]];
  const b = SPOTS[path[i + 1]];
  return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t];
}

// 21 points in MediaPipe order, in "0 to 1 of the picture" space around the centre. A little
// jitter, as real tracking has.
function handPoints(c: Point3, curl: number): Point3[] {
  const jitter = () => (Math.random() - 0.5) * 0.004;
  const wrist: Point3 = [c[0] + jitter(), c[1] + 0.12 + jitter(), c[2] + jitter()];
  const points: Point3[] = [wrist];
  const fingers = [
    { bx: -0.05, a: -0.95, len: [0.045, 0.04, 0.03, 0.025] },
    { bx: -0.03, a: -0.15, len: [0.06, 0.04, 0.03, 0.025] },
    { bx: 0, a: 0, len: [0.06, 0.045, 0.03, 0.025] },
    { bx: 0.025, a: 0.15, len: [0.055, 0.04, 0.03, 0.025] },
    { bx: 0.05, a: 0.32, len: [0.05, 0.03, 0.025, 0.02] },
  ];
  for (const f of fingers) {
    let x = wrist[0] + f.bx;
    let y = wrist[1];
    let z = wrist[2];
    let bend = 0;
    f.len.forEach((len, j) => {
      const l = j === 0 ? len : len * (1 - curl * 0.35);
      if (j > 0) bend += curl * 0.7;
      x += Math.sin(f.a) * l;
      y += Math.cos(f.a) * Math.cos(bend) * l;
      z -= Math.sin(bend) * l;
      points.push([x, y, z]);
    });
  }
  return points;
}

const PHRASES: Record<string, string> = { yes: "Yes", no: "No", help: "I need help", thanks: "Thank you", question: "I have a question", time: "Time" };

// Stands in for Claude composing English from the signs.
function compose(signs: string[]): string {
  if (signs.includes("question") && signs.includes("time")) return `${signs.includes("yes") ? "Yes. " : ""}What time is it?`;
  return `${signs.map((s) => PHRASES[s] ?? s.charAt(0).toUpperCase() + s.slice(1)).join(". ")}.`;
}

type Step = { wait: number; say?: string; signs?: string[]; awaitLearned?: boolean; lastLearned?: boolean };
const DEMO: Step[] = [
  { wait: 600, say: "Morning everyone, quick stand-up. Alice, can you take the client call on Monday?" },
  { wait: 9000, signs: ["yes", "question", "time"] },
  { wait: 9000, say: "Ten o'clock, with Northumbria Digital." },
  { wait: 5000, signs: ["newsign"], awaitLearned: true },
  { wait: 1200, lastLearned: true },
];

type Wire = { k: "hello" | "here"; who: Participant } | { k: "bye"; id: string } | { k: "msg"; m: ServiceMessage };

export class MockRoom {
  private channel: BroadcastChannel | null = null;
  private peers = new Map<string, Participant>();
  private paused = false;
  private speed = 1;
  private run = 0; // bumped to cancel anything scheduled
  private vocab = new Set([...KNOWN_SIGNS, ...EXTRA_WORDS]);
  private learned: Record<string, string> = {}; // simulated gesture to the label Alice taught
  private lastLearned = "";
  private taught: Record<string, number[][][]> = {}; // real camera signs, recognised on this machine
  private queue: string[] = [];
  private busy = false;
  private pending: string[] = []; // recognised signs waiting to become a sentence
  private teaching: string | null = null;
  private takes = 0;
  private recording = false;
  private script: { at: number } | null = null;
  private live: (Pt[] | null)[] = []; // the webcam's current movement
  private gap = 0;
  private voice = "";
  private botHere = false;

  constructor(private me: Participant, room: string, private emit: (m: ServiceMessage) => void) {
    try {
      this.taught = JSON.parse(store.get("taught") ?? "{}") as typeof this.taught;
      Object.keys(this.taught).forEach((w) => this.vocab.add(w));
    } catch {
      this.taught = {};
    }
    if ("BroadcastChannel" in window) {
      this.channel = new BroadcastChannel(`almero-${room}`);
      this.channel.onmessage = (e) => this.receive(e.data as Wire);
      this.post({ k: "hello", who: me });
    }
    queueMicrotask(() => this.pushParticipants());
    // The other person arrives a moment later, as people do.
    setTimeout(() => {
      this.botHere = true;
      this.pushParticipants();
    }, 2500);
  }

  private post(w: Wire) {
    this.channel?.postMessage(w);
  }

  private receive(w: Wire) {
    if (w.k === "hello" || w.k === "here") {
      this.peers.set(w.who.id, w.who);
      if (w.k === "hello") this.post({ k: "here", who: this.me });
      this.pushParticipants();
    } else if (w.k === "bye") {
      this.peers.delete(w.id);
      this.pushParticipants();
    } else if (w.k === "msg") this.emit(w.m);
  }

  /** The other side of the conversation: a real window if there is one, otherwise a bot. */
  private other(): Participant {
    const want = this.me.role === "sign" ? "speak" : "sign";
    const real = [...this.peers.values()].find((p) => p.role === want);
    if (real) return real;
    return want === "speak" ? { id: "bot-sam", name: "Sam", role: "speak", mic: true, cam: false } : { id: "bot-alice", name: "Alice", role: "sign", mic: false, cam: true };
  }

  private pushParticipants() {
    const items = [this.me, ...this.peers.values()];
    const other = this.other();
    if (this.botHere && !items.some((p) => p.id === other.id)) items.push(other);
    this.push({ type: "participants", items });
  }

  private later(ms: number, fn: () => void) {
    const run = this.run;
    setTimeout(() => {
      if (run === this.run) fn();
    }, ms / this.speed);
  }

  private push(m: Draft<ServiceMessage>) {
    this.emit({ ...m, ts: Date.now() } as ServiceMessage);
  }

  /** To everyone in the room, including this window. */
  private relay(m: Draft<ServiceMessage>) {
    const full = { ...m, ts: Date.now() } as ServiceMessage;
    this.emit(full);
    this.post({ k: "msg", m: full });
  }

  setSpeed(speed: number) {
    this.speed = speed;
  }

  close() {
    this.run++;
    this.post({ k: "bye", id: this.me.id });
    this.channel?.close();
  }

  send(m: UiMessage) {
    switch (m.type) {
      case "state":
        Object.assign(this.me, { mic: m.mic, cam: m.cam, hand: m.hand });
        this.post({ k: "here", who: this.me });
        this.pushParticipants();
        break;
      case "speaking":
        this.relay({ type: "speaking", id: m.id, on: m.on });
        break;
      case "signing":
        this.relay({ type: "signing", id: m.id, on: m.on, teaching: m.teaching });
        break;
      case "voice":
        this.voice = m.name;
        break;
      case "session":
        this.paused = m.state === "paused";
        if (this.paused) {
          this.queue = [];
          this.live = [];
          this.push({ type: "landmarks", hands: [] });
        }
        break;
      case "speech_text":
        if (this.me.role === "sign") this.relay({ type: "sentence", speaker: this.me.id, text: m.text, voice: this.voice });
        else this.speak(this.me.id, m.text);
        break;
      case "hands":
        break; // the real service reads these; here the page calls webcamFrame directly
      case "teach_start":
        this.teaching ??= this.freshGesture();
        if (this.recording || this.takes >= TAKES) return;
        this.recording = true;
        this.stream(this.teaching, () => {
          this.takes++;
          this.recording = false;
          this.push({ type: "teach_progress", label: m.label, take: this.takes, of: TAKES });
        });
        break;
      case "teach_stop":
        if (m.label && this.takes >= TAKES) this.learn(m.label);
        else {
          this.takes = 0;
          this.teaching = null;
        }
        break;
      case "teach_landmarks": {
        const takes = m.takes.map((t) => toSequence(t.map((f) => (f.hands[0] ? f.hands[0].points.map(([x, y, z]) => ({ x, y, z })) : null))));
        if (takes.every((t): t is number[][] => !!t)) {
          this.taught[m.label] = takes;
          store.set("taught", JSON.stringify(this.taught));
        }
        this.later(400, () => this.learn(m.label));
        break;
      }
    }
  }

  private freshGesture() {
    return NEW_SIGNS.find((g) => !this.learned[g]) ?? "custom";
  }

  private learn(label: string) {
    this.learned[this.teaching ?? this.freshGesture()] = label;
    this.lastLearned = label;
    this.vocab.add(label);
    this.teaching = null;
    this.takes = 0;
    this.push({ type: "sign_learned", label });
    this.advanceScript();
  }

  /** One frame from Alice's webcam. Recognises signs she has taught, on this machine. */
  webcamFrame(hand: Pt[] | null) {
    if (this.paused) return;
    if (hand) {
      this.live.push(hand);
      this.gap = 0;
      if (this.live.length > 200) this.live = [];
      return;
    }
    if (!this.live.length || ++this.gap < 8) return;
    const frames = this.live;
    this.live = [];
    this.gap = 0;
    let moved = 0;
    for (let i = 1; i < frames.length; i++) moved += Math.hypot(frames[i]![0].x - frames[i - 1]![0].x, frames[i]![0].y - frames[i - 1]![0].y);
    if (frames.length < 12 || moved < 0.15) return; // a hand drifting through, not a sign
    const attempt = toSequence(frames);
    if (!attempt) return;
    const ranked = Object.entries(this.taught)
      .map(([label, takes]) => ({ label, confidence: Math.round(matchScore(attempt, takes) * 100) / 100 }))
      .sort((a, b) => b.confidence - a.confidence);
    const best = ranked[0];
    if (best) this.push({ type: "sign_candidates", items: ranked.slice(0, 3) });
    if (best && best.confidence >= ACCEPT) this.accept(best.label, best.confidence);
    else this.push({ type: "unknown_sign" });
  }

  private accept(label: string, confidence: number) {
    this.push({ type: "sign_recognized", label, confidence });
    this.pending.push(label);
    this.later(1600, () => {
      if (!this.busy && !this.queue.length) this.flushSentence();
    });
  }

  /** Stands in for the other person's mic. */
  otherSays(text: string) {
    if (this.me.role === "speak") this.speak(this.me.id, text);
    else this.speak(this.other().id, text);
  }

  /** Stands in for Alice signing to her webcam. */
  aliceSigns(signs: string[]) {
    if (this.paused) return;
    this.queue.push(...signs);
    this.nextSign();
  }

  /** Alice signs something the library doesn't know. */
  aliceSignsUnknown() {
    this.aliceSigns([this.freshGesture()]);
  }

  /** Alice signs the one she just taught, and now it's understood. */
  aliceSignsLearned() {
    const gesture = Object.keys(this.learned).find((g) => this.learned[g] === this.lastLearned);
    if (gesture) this.aliceSigns([gesture]);
  }

  /** Alice repeats the sign she's teaching, so the page can test it. */
  aliceTriesTaught() {
    if (this.teaching) this.stream(this.teaching, () => {});
  }

  playDemo() {
    this.stop();
    this.script = { at: 0 };
    this.runStep();
  }

  stop() {
    this.run++;
    this.script = null;
    this.queue = [];
    this.pending = [];
    this.busy = false;
    this.recording = false;
    this.push({ type: "landmarks", hands: [] });
  }

  private runStep() {
    if (!this.script) return;
    const step = DEMO[this.script.at];
    if (!step) return void (this.script = null);
    this.later(step.wait, () => {
      if (step.say) this.otherSays(step.say);
      if (step.signs) this.aliceSigns(step.signs);
      if (step.lastLearned) this.aliceSigns([Object.keys(this.learned).find((g) => this.learned[g] === this.lastLearned) ?? "newsign"]);
      if (!step.awaitLearned) this.advanceScript();
    });
  }

  private advanceScript() {
    if (!this.script) return;
    this.script.at++;
    this.runStep();
  }

  private speak(speaker: string, text: string) {
    this.relay({ type: "speaking", id: speaker, on: true });
    this.later(200, () => this.relay({ type: "caption", speaker, text }));
    this.later(500, () => {
      const signs: string[] = [];
      for (const raw of text.split(/\s+/)) {
        const lower = raw.replace(/[^A-Za-z']/g, "").toLowerCase();
        const sign = SYNONYMS[lower] ?? lower;
        if (this.vocab.has(sign)) signs.push(sign);
        // Anything else stays in the captions: BSL fingerspelling needs two hands, so it isn't faked.
      }
      this.relay({ type: "avatar_play", signs });
    });
    this.later(1500, () => this.relay({ type: "speaking", id: speaker, on: false }));
  }

  private stream(name: string, done: () => void) {
    const g = GESTURES[name] ?? GESTURES.custom;
    const frames = Math.round((g.ms * FPS) / 1000);
    for (let f = 0; f <= frames; f++) {
      this.later((f * 1000) / FPS, () => {
        const c = pathAt(g.path, f / frames);
        const centre: Point3 = [0.5 - c[0], 0.5 + c[1], c[2]];
        const hand: Hand = { side: "right", points: handPoints(centre, g.curl), visible: true };
        this.push({ type: "landmarks", hands: [hand] });
      });
    }
    this.later(g.ms + 10, () => {
      this.push({ type: "landmarks", hands: [] });
      done();
    });
  }

  private label(name: string) {
    return this.learned[name] ?? (BASE_LIBRARY.includes(name) ? name : null);
  }

  private nextSign() {
    if (this.busy || this.recording) return;
    const name = this.queue.shift();
    if (!name) return;
    this.busy = true;
    // With a bot Alice, this window has to say she's signing; a real one says so herself.
    const botSigner = this.me.role === "speak" ? this.other().id : null;
    if (botSigner) this.push({ type: "signing", id: botSigner, on: true });
    this.stream(name, () => {
      if (botSigner) this.push({ type: "signing", id: botSigner, on: false });
      const label = this.label(name);
      const others = DISTRACTORS.filter((d) => d !== name);
      if (label) {
        const confidence = (78 + ((name.length * 7) % 14)) / 100;
        this.later(250, () =>
          this.push({ type: "sign_candidates", items: [{ label, confidence }, { label: others[0], confidence: 0.08 }, { label: others[1], confidence: 0.04 }] }),
        );
        this.later(700, () => {
          this.push({ type: "sign_recognized", label, confidence });
          this.pending.push(label);
          this.busy = false;
          if (this.queue.length) this.later(300, () => this.nextSign());
          else this.later(700, () => this.flushSentence());
        });
      } else {
        this.later(250, () =>
          this.push({ type: "sign_candidates", items: [{ label: others[3], confidence: 0.31 }, { label: others[4], confidence: 0.22 }, { label: others[5], confidence: 0.18 }] }),
        );
        this.later(650, () => {
          this.teaching = name;
          this.takes = 0;
          this.queue = [];
          this.busy = false;
          this.pending = [];
          this.push({ type: "unknown_sign" });
        });
      }
    });
  }

  private flushSentence() {
    if (!this.pending.length) return;
    const speaker = this.me.role === "sign" ? this.me.id : this.other().id;
    this.relay({ type: "sentence", speaker, text: compose(this.pending), voice: this.voice });
    this.pending = [];
  }
}
