import "@fontsource/atkinson-hyperlegible-next/400.css";
import "@fontsource/atkinson-hyperlegible-next/500.css";
import "@fontsource/atkinson-hyperlegible-next/600.css";
import "@fontsource/atkinson-hyperlegible-mono/400.css";
import "./styles.css";
import { Stage } from "./avatar/stage";
import { AVATAR_ON, PRODUCT } from "./brand";
import type { Candidate, Participant, Role, ServiceMessage } from "./service/contract";
import { connect, type Connection, type LinkState } from "./service/connection";
import { $, button, el, store, toast } from "./ui/dom";
import type { Pt } from "./ui/handtrack";
import { createJoin, type JoinInfo } from "./ui/join";
import { createLanding } from "./ui/landing";
import { createMySigns } from "./ui/mysigns";
import { applyTone, createPersonalise } from "./ui/personalise";
import { SelfView } from "./ui/selfview";
import { createListener, micLevel } from "./ui/speech";
import { createStudio } from "./ui/studio";
import { createTour } from "./ui/tour";
import { chosenVoiceName, sayAs, stopSpeaking } from "./ui/voices";

const AVATAR_URL = `${import.meta.env.BASE_URL}models/interpreter.vrm`;
const INTERPRETER = "interpreter";
const params = new URLSearchParams(location.search);
const EASE = "cubic-bezier(.22,1,.36,1)";

// One-laptop backup: both views side by side, sharing a room in this browser.
if (params.get("split")) renderSplit();
else start();

function renderSplit() {
  document.title = `${PRODUCT}, one laptop`;
  document.body.classList.add("split");
  $("app").remove();
  const frame = (role: Role, name: string) => {
    const f = el("iframe");
    f.title = `${name}'s view`;
    f.allow = "camera; microphone";
    f.src = `?role=${role}&name=${name}`;
    return f;
  };
  document.body.append(frame("sign", "Alice"), frame("speak", "Sam"));
}

function initials(name: string) {
  return name.trim().split(/\s+/).map((w) => w[0]).join("").slice(0, 2).toUpperCase();
}

function start() {
  const setIcon = (btn: HTMLElement, id: string) => btn.querySelector("use")!.setAttribute("href", `#i-${id}`);
  const setLabel = (btn: HTMLElement, text: string) => (btn.querySelector("span")!.textContent = text);
  const app = $("app");
  const room = $("room");
  const canvas = el("canvas", "stage");
  canvas.setAttribute("aria-label", "Signing avatar");
  const stage = new Stage(canvas);
  const selfView = new SelfView();
  const tour = createTour();

  // ---------- who's here
  let me: Participant = { id: "", name: "", role: "sign", mic: false, cam: true };
  let roomCode = "";
  let people: Participant[] = [];
  let conn: Connection = { send: () => false, close: () => {} };
  let pinned: string | null = null;
  const speaking = new Set<string>();
  const viaAlmero = new Set<string>();
  const signingNow = new Map<string, { teaching: boolean }>();

  const person = (id: string) => people.find((p) => p.id === id);
  const signer = () => people.find((p) => p.role === "sign");
  const signerName = () => signer()?.name ?? "Alice";
  const others = () => people.filter((p) => p.id !== me.id);
  const defaultPin = () => (me.role === "sign" ? INTERPRETER : (signer()?.id ?? INTERPRETER));
  const pinnedId = () => (pinned && (pinned === INTERPRETER || person(pinned)) ? pinned : defaultPin());

  if (AVATAR_ON) {
    void stage.load(AVATAR_URL, () => {}).then(
      () => applyTone(stage),
      (err) => {
        console.error(err);
        toast("The avatar couldn't load. Captions still work");
      },
    );
  }
  // With the avatar off, the tile shows the sign being signed, as a word.
  const gloss = el("div", "gloss");
  gloss.setAttribute("aria-hidden", "true");
  document.documentElement.classList.toggle("no-avatar", !AVATAR_ON);

  // ---------- the band: captions and every message, in one reading place inside the main tile
  const band = el("div", "band");
  const paceLine = el("div", "pace-line");
  const paceFill = el("i");
  paceLine.appendChild(paceFill);
  paceLine.hidden = true;
  const banner = el("p", "banner");
  banner.setAttribute("role", "status");
  banner.hidden = true;
  const statusEl = el("div", "sign-status");
  statusEl.hidden = true;
  const pacing = el("p", "pacing");
  pacing.hidden = true;
  const hint = el("p", "hint");
  hint.hidden = true;
  const interim = el("p", "interim");
  interim.hidden = true;
  const emptyRoom = el("div", "empty-room");
  const caps = el("div", "caps");
  caps.id = "capsBox";
  caps.setAttribute("aria-live", "polite");
  band.append(paceLine, banner, statusEl, pacing, hint, caps, interim, emptyRoom);

  function renderEmpty() {
    const alone = others().length === 0;
    emptyRoom.hidden = !alone;
    caps.hidden = alone || !captionsOn;
    if (!alone) return;
    emptyRoom.textContent = "";
    const code = el("span", "empty-code", roomCode);
    const copy = button("ghost small", "Copy room code", async () => {
      try {
        await navigator.clipboard.writeText(roomCode);
        toast("Room code copied");
      } catch {
        toast("Couldn't copy. The code is on screen");
      }
    });
    emptyRoom.append(el("p", "empty-title", "Waiting for others to join"), code, copy);
  }

  // ---------- tiles. Each keeps one element for its life, so pinning can animate it.
  const tiles = new Map<string, HTMLElement>();

  function micIcon(on: boolean) {
    return `<svg class="i" aria-label="${on ? "Mic on" : "Mic off"}"><use href="#i-${on ? "mic" : "mic-off"}" /></svg>`;
  }

  function makeTile(id: string) {
    const t = el("div", "tile");
    t.id = id === me.id ? "tile-self" : `tile-${id}`;
    t.dataset.id = id;
    const chipEl = el("span", "tile-chip");
    chipEl.hidden = true;
    const name = el("span", "tile-name");
    const pin = button("tile-pin", "", () => togglePin(id));
    pin.innerHTML = '<svg class="i"><use href="#i-pin" /></svg>';
    if (id === INTERPRETER) {
      t.classList.add("interp");
      if (!AVATAR_ON) t.append(gloss);
      t.append(el("span", "tile-paused", `${PRODUCT} paused`));
    } else {
      const p = person(id)!;
      if (id === me.id) {
        t.classList.add("self");
        t.appendChild(el("div", "tile-circle", initials(p.name)));
        t.appendChild(selfView.root); // above the initials, which only show when the camera's off
        t.appendChild(el("span", "tile-paused", `${PRODUCT} paused`));
      } else if (p.photo) {
        const img = el("img", "tile-photo");
        img.src = p.photo;
        img.alt = "";
        t.appendChild(img);
      } else {
        t.appendChild(el("div", "tile-circle", initials(p.name)));
      }
      if (p.role === "sign") t.classList.add("signer");
    }
    t.append(chipEl, name, pin);
    // Tapping a small tile pins it, the way phone call apps do.
    t.addEventListener("click", (e) => {
      if (app.clientWidth < 640 && !(e.target as HTMLElement).closest("button") && t.parentElement?.id === "strip") togglePin(id);
    });
    t.classList.add("enter");
    t.addEventListener("animationend", () => t.classList.remove("enter"), { once: true });
    return t;
  }

  function updateTile(t: HTMLElement, id: string, big: boolean) {
    const name = t.querySelector<HTMLElement>(".tile-name")!;
    const pin = t.querySelector<HTMLElement>(".tile-pin")!;
    pin.setAttribute("aria-label", big ? "Unpin this tile" : "Pin this tile");
    pin.setAttribute("aria-pressed", String(big));
    const bars = '<span class="bars" aria-hidden="true"><i></i><i></i><i></i></span>';
    if (id === INTERPRETER) {
      name.textContent = me.role === "sign" ? "Signing avatar" : `What ${signerName()} sees`;
      return;
    }
    const p = person(id);
    if (!p) return;
    const label = id === me.id ? "You" : p.role === "sign" ? `${p.name}, signs via ${PRODUCT}` : p.name;
    const label2 = el("span");
    label2.textContent = label;
    name.innerHTML = `${p.mic || p.role === "sign" ? "" : micIcon(false)}${bars}`;
    name.appendChild(label2);
    t.classList.toggle("hand", !!p.hand);
  }

  function togglePin(id: string) {
    pinned = pinnedId() === id ? null : id;
    renderTiles();
  }

  function renderTiles() {
    if (room.hidden) return;
    const big = pinnedId();
    const ids = [INTERPRETER, ...people.map((p) => p.id)];
    // Remember where everything was, so moves can glide instead of jump.
    const before = new Map<string, DOMRect>();
    tiles.forEach((t, id) => before.set(id, t.getBoundingClientRect()));

    for (const [id, t] of [...tiles]) {
      if (!ids.includes(id)) {
        t.remove();
        tiles.delete(id);
      }
    }
    for (const id of ids) if (!tiles.has(id)) tiles.set(id, makeTile(id));

    const pinEl = $("pinned");
    const strip = $("strip");
    const bigTile = tiles.get(big)!;
    if (bigTile.parentElement !== pinEl) pinEl.replaceChildren(bigTile);
    bigTile.appendChild(band);
    for (const id of ids) if (id !== big) strip.appendChild(tiles.get(id)!);
    for (const id of ids) updateTile(tiles.get(id)!, id, id === big);

    // The canvas lives in the avatar's tile; keep its signing clear of the band.
    const interp = tiles.get(INTERPRETER)!;
    if (canvas.parentElement !== interp) stage.mount(interp);
    if (big === INTERPRETER) stage.setInsets(8, 156);
    else stage.setInsets(8, 24);
    selfView.root.classList.toggle("off", !me.cam);

    requestAnimationFrame(() => {
      tiles.forEach((t, id) => {
        const was = before.get(id);
        if (!was || t.classList.contains("enter")) return;
        const now = t.getBoundingClientRect();
        if (!now.width || (was.left === now.left && was.top === now.top && was.width === now.width)) return;
        t.animate(
          [{ transform: `translate(${was.left - now.left}px, ${was.top - now.top}px) scale(${was.width / now.width}, ${was.height / now.height})`, transformOrigin: "top left" }, { transform: "none", transformOrigin: "top left" }],
          { duration: 280, easing: EASE },
        );
      });
    });
    renderLive();
    renderEmpty();
    $("peopleCount").textContent = String(people.length);
    renderPeople();
  }

  /** Everything that shows who's doing what right now. */
  function renderLive() {
    tiles.forEach((t, id) => {
      const chipEl = t.querySelector<HTMLElement>(".tile-chip")!;
      let chip = "";
      if (id === INTERPRETER) {
        const playing = avatarPlaying;
        const speaker = avatarSpeaker ? person(avatarSpeaker)?.name : "";
        chip = playing ? `Signing ${speaker ? `${speaker}'s` : "the"} words` : "Ready";
        t.classList.toggle("speaking", playing);
      } else {
        const s = signingNow.get(id);
        const via = viaAlmero.has(id);
        if (s) chip = s.teaching ? "Teaching a sign" : "Signing";
        else if (via) chip = `Speaking via ${PRODUCT}`;
        t.classList.toggle("speaking", speaking.has(id) || via);
        t.classList.toggle("signing", !!s);
        const p = person(id);
        if (p?.photo && id !== me.id && !chip) chip = "Photo from join";
      }
      if (t.classList.contains("hand")) chip = chip ? `${chip} · Hand raised` : "Hand raised";
      chipEl.textContent = chip;
      chipEl.hidden = !chip;
    });

    // The band: what a hearing person needs to wait for, and anyone asking to talk.
    const elsewhere = [...signingNow.entries()].find(([id]) => id !== me.id);
    const handUp = others().find((p) => p.hand);
    let message = "";
    if (!live) message = `${PRODUCT} is paused. Typing in the transcript still works`;
    else if (link === "lost") message = "Connection lost. Reconnecting";
    else if (elsewhere) {
      const who = person(elsewhere[0])?.name ?? "Alice";
      message = elsewhere[1].teaching ? `${who} is teaching a sign. This takes about a minute` : `${who} is signing. Please wait`;
    } else if (handUp) message = `${handUp.name} wants to say something`;
    banner.textContent = message;
    banner.hidden = !message;

    const waiting = speakers().find((id) => id !== me.id);
    hint.textContent = waiting ? `${person(waiting)?.name ?? "Someone"} is speaking…` : "";
    hint.hidden = !waiting || me.role !== "sign";
  }
  const speakers = () => [...speaking].filter((id) => person(id)?.role === "speak");

  function renderPeople() {
    const box = $("partPeople");
    box.textContent = "";
    for (const p of people) {
      const row = el("div", "person");
      const text = el("span", "row-text");
      text.append(el("b", undefined, p.id === me.id ? `${p.name} (you)` : p.name), el("small", undefined, `${p.role === "sign" ? "Signs" : "Speaks"}${p.hand ? " · hand raised" : ""}`));
      const mic = el("span", "person-mic");
      mic.innerHTML = micIcon(p.mic);
      row.append(text, mic);
      box.appendChild(row);
    }
  }

  // ---------- captions and transcript
  let captionsOn = true;
  function displayName(p: Participant | undefined, fallback: string) {
    if (!p) return fallback;
    if (p.id === me.id) return p.role === "sign" ? `You, via ${PRODUCT}` : "You";
    return p.role === "sign" ? `${p.name}, via ${PRODUCT}` : p.name;
  }
  function addLine(speakerId: string, text: string) {
    const p = person(speakerId);
    const who = displayName(p, speakerId);
    const tint = p?.role === "sign" ? "alice" : "bob";
    const line = el("p", `line ${tint} rise`);
    line.append(el("span", "who", who), el("span", "words", text));
    caps.appendChild(line);
    const lines = caps.querySelectorAll(".line");
    if (lines.length > 2) lines[0].remove();

    const entry = el("div", `entry ${tint}`);
    const head = el("div", "entry-head");
    head.append(el("b", "who", who), el("span", "count", new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })));
    entry.append(head, el("p", undefined, text));
    const tr = $("transcript");
    tr.appendChild(entry);
    tr.scrollTop = tr.scrollHeight;
  }
  function setCaptions(on: boolean) {
    captionsOn = on;
    renderEmpty();
    $("ccBtn").setAttribute("aria-pressed", String(on));
    $("ccBtn").classList.toggle("off", !on);
  }
  $("ccBtn").addEventListener("click", () => setCaptions(!captionsOn));

  // ---------- Alice's status: what Almero thinks she signed, in plain words
  let signed: string[] = [];
  function showStatus(text: string, actions: HTMLElement[] = []) {
    statusEl.hidden = false;
    statusEl.textContent = text;
    statusEl.append(...actions);
  }
  const candidateText = (items: Candidate[]) => {
    const top = items[0];
    if (!top) return "Signing…";
    return top.confidence < 0.6 ? `Maybe ${top.label.toUpperCase()}?` : top.label.toUpperCase();
  };

  // ---------- the avatar's progress, and pacing for people who speak
  let avatarPlaying = false;
  let avatarSpeaker = "";
  stage.onProgress = (items, index) => {
    avatarPlaying = index >= 0;
    gloss.textContent = index >= 0 ? items[index].label.toUpperCase() : "";
    gloss.classList.toggle("idle", index < 0);
    pacing.hidden = me.role !== "speak" || index < 0;
    pacing.textContent = `Wait: ${signerName()} is still watching the signing`;
    paceLine.hidden = index < 0;
    paceFill.style.transform = `scaleX(${index < 0 ? 0 : (index + 1) / Math.max(1, items.length)})`;
    renderLive();
  };

  // ---------- status, pause and auto-pause
  let live = true;
  let link: LinkState = "connecting";
  let autoPauseMs = 2 * 60 * 1000;
  let lastActivity = performance.now();
  const touch = () => (lastActivity = performance.now());

  function renderStatus() {
    const lost = link !== "open";
    $("status").className = `status ${lost ? "lost" : live ? "live" : "paused"}`;
    $("statusText").textContent = link === "connecting" ? "Connecting" : link === "lost" ? "Reconnecting" : live ? "Live" : "Paused";
    const pause = $("pauseBtn");
    setIcon(pause, live ? "pause" : "play");
    pause.setAttribute("aria-pressed", String(!live));
    pause.setAttribute("aria-label", live ? `Pause ${PRODUCT}` : `Resume ${PRODUCT}`);
    setLabel(pause, live ? "Pause" : "Resume");
    room.classList.toggle("is-paused", !live);
    renderLive();
  }

  function setLive(on: boolean) {
    if (on === live) return;
    live = on;
    conn.send({ type: "session", state: on ? "live" : "paused" });
    touch();
    if (!on) stopSpeaking();
    void applyDevices();
    renderStatus();
  }
  $("pauseBtn").addEventListener("click", () => setLive(!live));
  setInterval(() => {
    if (room.hidden || !live || !autoPauseMs || studio.open || performance.now() - lastActivity < autoPauseMs) return;
    setLive(false);
  }, 1000);

  // ---------- mic and camera
  const listener = createListener(
    (text) => {
      touch();
      interim.hidden = true;
      conn.send({ type: "speech_text", text, source: "speech" });
    },
    (message) => toast(message),
    (text) => {
      interim.textContent = text;
      interim.hidden = !text;
    },
  );
  let stopLevel: (() => void) | null = null;
  let loudUntil = 0;
  let saidSpeaking = false;

  async function applyDevices() {
    const hearing = me.role === "speak" && me.mic && live;
    listener.set(hearing);
    if (hearing && !stopLevel) {
      stopLevel = await micLevel((level) => {
        const now = performance.now();
        if (level > 0.12) loudUntil = now + 600;
        const on = now < loudUntil;
        if (on !== saidSpeaking) {
          saidSpeaking = on;
          conn.send({ type: "speaking", id: me.id, on });
        }
      }).catch(() => null);
    } else if (!hearing && stopLevel) {
      stopLevel();
      stopLevel = null;
      if (saidSpeaking) conn.send({ type: "speaking", id: me.id, on: false });
      saidSpeaking = false;
    }
    if (me.cam && live) await selfView.start();
    else selfView.stop();
    selfView.root.classList.toggle("off", !me.cam);
  }
  function sendState() {
    conn.send({ type: "state", mic: me.mic, cam: me.cam, hand: !!me.hand });
    renderTiles();
  }
  function setMicButton() {
    const b = $("micBtn");
    setIcon(b, me.mic ? "mic" : "mic-off");
    b.setAttribute("aria-pressed", String(me.mic));
    b.setAttribute("aria-label", me.mic ? "Turn microphone off" : "Turn microphone on");
    // A signer's mic is off by default, so that isn't a warning for them.
    b.classList.toggle("off", !me.mic && me.role === "speak");
  }
  function setCamButton() {
    const b = $("camBtn");
    setIcon(b, me.cam ? "cam" : "cam-off");
    b.setAttribute("aria-pressed", String(me.cam));
    b.setAttribute("aria-label", me.cam ? "Turn camera off" : "Turn camera on");
    b.classList.toggle("off", !me.cam);
  }
  $("micBtn").addEventListener("click", () => {
    me.mic = !me.mic;
    setMicButton();
    void applyDevices();
    sendState();
  });
  $("camBtn").addEventListener("click", () => {
    me.cam = !me.cam;
    setCamButton();
    void applyDevices();
    sendState();
  });
  $("handBtn").addEventListener("click", () => {
    me.hand = !me.hand;
    $("handBtn").setAttribute("aria-pressed", String(me.hand));
    sendState();
  });

  // ---------- reading Alice's hands
  selfView.canTrack = () => me.role === "sign" && live && me.cam && !studio.open && !room.hidden;
  let frameBuffer: { t_ms: number; hands: { side: "right"; points: [number, number, number][] }[] }[] = [];
  let lastSend = 0;
  let handsGoneAt = 0;
  let iAmSigning = false;
  function setMySigning(on: boolean, teaching = false) {
    if (on === iAmSigning && !teaching) return;
    iAmSigning = on;
    conn.send({ type: "signing", id: me.id, on, teaching });
    if (on) signingNow.set(me.id, { teaching });
    else signingNow.delete(me.id);
    renderLive();
    // Her hands dropped with signs waiting: tell her Almero is working on it.
    if (!on && signed.length) showStatus(`${signed.join(" · ")}. Translating…`);
  }
  function noteHands(present: boolean) {
    if (me.role !== "sign" || studio.open) return;
    if (present) {
      handsGoneAt = 0;
      setMySigning(true);
    } else if (iAmSigning) {
      handsGoneAt ||= performance.now();
      if (performance.now() - handsGoneAt > 700) setMySigning(false);
    }
  }
  selfView.onFrame = (hands: Pt[][]) => {
    if (hands.length) touch();
    noteHands(hands.length > 0);
    if (conn.mock) return conn.mock.webcamFrame(hands[0] ?? null);
    const now = performance.now();
    frameBuffer.push({ t_ms: Math.round(now), hands: hands.map((h) => ({ side: "right", points: h.map((p) => [p.x, p.y, p.z]) })) });
    if (now - lastSend > 300) {
      conn.send({ type: "hands", frames: frameBuffer });
      frameBuffer = [];
      lastSend = now;
    }
  };

  // ---------- add a sign, and my signs
  const mySigns = createMySigns({
    onShow: (word) => stage.play([word], []),
    onAdd: () => studio.add(),
  });
  const studio = createStudio(
    {
      get mock() {
        return conn.mock;
      },
      send: (m) => conn.send(m),
      close: () => {},
    },
    {
      isLive: () => live,
      goLive: () => setLive(true),
      onSaved(label, fromVideo) {
        mySigns.add(label, fromVideo);
        showStatus(`${label.toUpperCase()} is saved. Sign it again`);
      },
      onCancelUnknown() {
        statusEl.hidden = true;
      },
      onOpenChange(open) {
        // So the hearing person can see why nothing's happening.
        if (me.role === "sign") setMySigning(open, open);
      },
    },
  );
  $("addSign").addEventListener("click", () => studio.add());

  // ---------- panels
  type Panel = "people" | "transcript" | "signs" | null;
  let panel: Panel = null;
  function setPanel(next: Panel) {
    panel = next;
    room.classList.toggle("has-panel", !!panel);
    $("panel").hidden = !panel;
    $("partPeople").hidden = panel !== "people";
    $("partTranscript").hidden = panel !== "transcript";
    $("partSigns").hidden = panel !== "signs";
    $("panelTitle").textContent = panel === "people" ? "People" : panel === "transcript" ? "Transcript" : "My signs";
    $("peopleBtn").setAttribute("aria-pressed", String(panel === "people"));
    $("transcriptBtn").setAttribute("aria-pressed", String(panel === "transcript"));
    if (panel === "transcript") {
      const tr = $("transcript");
      tr.scrollTop = tr.scrollHeight;
    }
  }
  const togglePanel = (p: Panel) => setPanel(panel === p ? null : p);
  $("peopleBtn").addEventListener("click", () => togglePanel("people"));
  $("transcriptBtn").addEventListener("click", () => togglePanel("transcript"));
  $("panelClose").addEventListener("click", () => setPanel(null));

  // ---------- typing
  const sayInput = $<HTMLInputElement>("say");
  $("composer").addEventListener("submit", (e) => {
    e.preventDefault();
    const text = sayInput.value.trim();
    if (!text) return;
    if (!conn.send({ type: "speech_text", text, source: "typed" })) return toast("Not connected yet, so that wasn't sent. Your text is still here");
    sayInput.value = "";
    touch();
  });
  function typeInstead() {
    setPanel("transcript");
    sayInput.focus();
  }

  // ---------- personalise
  const personalise = createPersonalise(stage, () => {
    conn.send({ type: "voice", name: chosenVoiceName() });
    stage.mount(tiles.get(INTERPRETER)!);
    renderTiles();
  });
  $("voiceBtn").addEventListener("click", () => personalise.open());

  // ---------- more menu
  const menu = $("menu");
  const moreBtn = $("moreBtn");
  function toggleMenu(open = menu.hidden) {
    menu.hidden = !open;
    moreBtn.setAttribute("aria-expanded", String(open));
  }
  moreBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    toggleMenu();
  });
  $("mSigns").addEventListener("click", () => setPanel("signs"));
  $("mPers").addEventListener("click", () => personalise.open());
  $("mTour").addEventListener("click", () => tour.start());
  $("mPeople").addEventListener("click", () => setPanel("people"));
  $("mTranscript").addEventListener("click", () => setPanel("transcript"));
  $("mCc").addEventListener("click", () => setCaptions(!captionsOn));

  const infoBtn = $("infoBtn");
  const infoPop = $("infoPop");
  infoBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    infoPop.hidden = !infoPop.hidden;
    infoBtn.setAttribute("aria-expanded", String(!infoPop.hidden));
  });
  infoPop.addEventListener("click", (e) => e.stopPropagation());
  document.addEventListener("click", () => {
    toggleMenu(false);
    infoPop.hidden = true;
  });

  // A soft sound for hearing people only. Nothing relies on it: the band says it in words.
  function chime() {
    try {
      const ctx = new AudioContext();
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.frequency.value = 660;
      gain.gain.setValueAtTime(0.08, ctx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.4);
      osc.connect(gain).connect(ctx.destination);
      osc.start();
      osc.stop(ctx.currentTime + 0.4);
      osc.onended = () => void ctx.close();
    } catch {
      /* no sound, and nothing lost */
    }
  }

  // ---------- the service
  function handle(m: ServiceMessage) {
    switch (m.type) {
      case "participants": {
        const known = new Set(people.map((p) => p.id));
        const handsUp = new Set(people.filter((p) => p.hand).map((p) => p.id));
        people = m.items;
        for (const p of people) {
          if (!known.has(p.id) && p.id !== me.id) toast(`${p.name} joined`);
          if (p.hand && !handsUp.has(p.id) && p.id !== me.id && me.role === "speak") chime();
        }
        renderTiles();
        break;
      }
      case "leave":
        toast(`${person(m.id)?.name ?? "Someone"} left`);
        people = people.filter((p) => p.id !== m.id);
        renderTiles();
        break;
      case "speaking":
        if (m.on) speaking.add(m.id);
        else speaking.delete(m.id);
        renderLive();
        break;
      case "signing":
        if (m.id === me.id) break;
        if (m.on) signingNow.set(m.id, { teaching: !!m.teaching });
        else signingNow.delete(m.id);
        renderLive();
        break;
      case "caption":
        touch();
        avatarSpeaker = m.speaker;
        addLine(m.speaker, m.text);
        break;
      case "avatar_play":
        touch();
        stage.enqueue(m.signs); // BSL fingerspelling needs two hands, so unknown words stay in the captions
        break;
      case "sentence":
        touch();
        addLine(m.speaker, m.text);
        if (m.speaker === me.id) {
          signed = [];
          // Her words went out in her name, so she can read them and put them right.
          showStatus(`${PRODUCT} said: “${m.text}”`, [button("link", "Not what I meant", notWhatIMeant)]);
        }
        if (me.role === "speak" && live) {
          viaAlmero.add(m.speaker);
          renderLive();
          sayAs(m.text, m.voice, () => {
            viaAlmero.delete(m.speaker);
            renderLive();
          });
        }
        break;
      case "landmarks":
        if (m.hands.length) touch();
        if (me.role === "sign") {
          selfView.showSimulated(live ? m.hands.map((h) => h.points.map(([x, y, z]) => ({ x, y, z }))) : []);
          noteHands(m.hands.length > 0);
          // The fake backend ends its stream with an empty frame, so don't wait for more.
          if (!m.hands.length && iAmSigning && !studio.open) setMySigning(false);
        }
        studio.feed(m.hands);
        break;
      case "sign_candidates":
        if (me.role === "sign" && signed.length === 0) showStatus(candidateText(m.items));
        break;
      case "sign_recognized":
        touch();
        if (me.role !== "sign") break;
        signed.push(m.label.toUpperCase());
        showStatus(`${signed.join(" · ")}…`);
        break;
      case "unknown_sign":
        touch();
        if (me.role !== "sign") break;
        signed = [];
        showStatus("I don't know that sign yet.", [button("link", "Add a sign", () => studio.teachUnknown()), button("link", "Type instead", typeInstead)]);
        break;
      case "teach_progress":
        studio.takeDone();
        break;
      case "sign_learned":
        studio.learned(m.label);
        break;
      case "teach_error":
        studio.failed(m.reason);
        break;
    }
  }
  function notWhatIMeant() {
    conn.send({ type: "speech_text", text: "Sorry, that's not what I meant. One moment.", source: "typed" });
    typeInstead();
  }

  // ---------- joining and leaving
  const landing = createLanding(stage, () => join.show());
  const join = createJoin(selfView, enterRoom, () => landing.show());
  let startedAt = 0;

  function enterRoom(info: JoinInfo) {
    me = { id: `p-${Math.random().toString(36).slice(2, 8)}`, name: info.name, role: info.role, mic: info.mic, cam: info.cam, photo: info.photo };
    roomCode = info.room;
    people = [me];
    pinned = null;
    live = true;
    speaking.clear();
    viaAlmero.clear();
    signingNow.clear();
    iAmSigning = false;
    tiles.forEach((t) => t.remove());
    tiles.clear();
    caps.textContent = "";
    $("transcript").textContent = "";
    statusEl.hidden = true;
    signed = [];
    setPanel(null);
    $("join").hidden = true;
    $("left").hidden = true;
    room.hidden = false;
    room.classList.toggle("role-sign", me.role === "sign");
    $("voiceBtn").hidden = me.role !== "sign";
    $("roomName").textContent = info.roomName;
    infoPop.textContent = "";
    infoPop.append(
      el("p", "count", `Room code ${roomCode}`),
      el("p", undefined, "Experimental. The avatar signs one sign at a time, so it isn't full BSL, and Deaf users haven't tested it yet. For interviews, medical or legal appointments, book a qualified interpreter."),
    );
    startedAt = Date.now();
    setMicButton();
    setCamButton();
    setCaptions(true);
    conn = connect(me, roomCode, handle, (state) => {
      link = state;
      renderStatus();
    });
    if (me.role === "sign") {
      selfView.loadTracker();
      conn.send({ type: "voice", name: chosenVoiceName() });
    }
    renderStatus();
    renderTiles();
    void applyDevices();
    touch();
  }

  function leave() {
    conn.send({ type: "leave", id: me.id });
    conn.close();
    conn = { send: () => false, close: () => {} };
    listener.set(false);
    stopSpeaking();
    selfView.stop();
    stopLevel?.();
    stopLevel = null;
    room.hidden = true;
    $("demo").hidden = true;
    $("left").hidden = false;
  }
  $("leaveBtn").addEventListener("click", leave);
  $("rejoin").addEventListener("click", () => {
    $("left").hidden = true;
    join.show();
  });
  $("leftHome").addEventListener("click", () => {
    $("left").hidden = true;
    landing.show();
  });
  addEventListener("beforeunload", () => conn.close());

  // ---------- the clock
  const tickClock = () => {
    $("clock").textContent = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    const secs = Math.floor((Date.now() - startedAt) / 1000);
    $("elapsed").textContent = `${String(Math.floor(secs / 60)).padStart(2, "0")}:${String(secs % 60).padStart(2, "0")}`;
  };
  tickClock();
  setInterval(tickClock, 1000);

  // ---------- presenter controls, press D. Never part of the product UI.
  const demo = $("demo");
  const toggleDemo = () => {
    if (!room.hidden && conn.mock) demo.hidden = !demo.hidden;
  };
  function segment(boxId: string, options: [string, () => void][], selected = 0) {
    const box = $(boxId);
    options.forEach(([label, run], i) => {
      const b = button("seg-btn", label, () => {
        box.querySelectorAll("button").forEach((x) => x.setAttribute("aria-checked", String(x === b)));
        run();
      });
      b.setAttribute("role", "radio");
      b.setAttribute("aria-checked", String(i === selected));
      box.appendChild(b);
    });
  }
  $("demoPlay").addEventListener("click", () => {
    if (!live) setLive(true);
    conn.mock?.playDemo();
  });
  $("demoStop").addEventListener("click", () => conn.mock?.stop());
  const setSpeed = (s: number) => {
    conn.mock?.setSpeed(s);
    stage.setSpeed(s);
  };
  segment("demoSpeed", [
    ["1×", () => setSpeed(1)],
    ["2×", () => setSpeed(2)],
  ]);
  for (const [label, line] of [
    ["Stand-up question", "Morning everyone, quick stand-up. Alice, can you take the client call on Monday?"],
    ["Ten o'clock", "Ten o'clock, with Northumbria Digital."],
    ["See you tomorrow", "See you tomorrow"],
  ]) {
    $("demoTeacher").appendChild(button("pill-btn", label, () => conn.mock?.otherSays(line)));
  }
  $("demoAlice").appendChild(button("pill-btn", "Yes · Question · Time", () => conn.mock?.aliceSigns(["yes", "question", "time"])));
  for (const [label, sign] of [
    ["Yes", "yes"],
    ["No", "no"],
    ["Help", "help"],
    ["Thank you", "thanks"],
  ]) {
    $("demoAlice").appendChild(button("pill-btn", label, () => conn.mock?.aliceSigns([sign])));
  }
  $("demoAlice").appendChild(button("pill-btn dashed", "A sign it doesn't know", () => conn.mock?.aliceSignsUnknown()));
  $("demoAlice").appendChild(button("pill-btn", "The sign just taught", () => conn.mock?.aliceSignsLearned()));
  segment("demoScreen", [
    ["Full screen", () => app.classList.remove("framed")],
    ["Phone size", () => app.classList.add("framed")],
  ]);
  $("demoReset").addEventListener("click", () => {
    store.clear();
    location.reload();
  });
  segment("demoAuto", [
    ["2 min", () => (autoPauseMs = 2 * 60 * 1000)],
    ["15 s, to show it", () => (autoPauseMs = 15 * 1000)],
    ["Off", () => (autoPauseMs = 0)],
  ]);
  $("demoClose").addEventListener("click", toggleDemo);

  addEventListener("keydown", (e) => {
    const typing = e.target instanceof HTMLInputElement;
    if (!typing && !e.metaKey && !e.ctrlKey && e.key.toLowerCase() === "d") toggleDemo();
    if (e.key === "Escape") toggleMenu(false);
  });
  // Phones have no D key: five quick taps on the logo open the same controls.
  let taps = 0;
  let tapTimer = 0;
  document.querySelector(".room-right .mark")?.addEventListener("click", () => {
    clearTimeout(tapTimer);
    tapTimer = window.setTimeout(() => (taps = 0), 800);
    if (++taps === 5) {
      taps = 0;
      toggleDemo();
    }
  });

  renderStatus();
  // The one-laptop mode goes straight to joining; everyone else starts at the landing page.
  if (params.get("role") || params.get("join")) join.show();
  else landing.show();
}
