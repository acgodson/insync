// Add a sign: name it, record it twice with live hand tracking, test it, save it.
import type { HandLandmarker } from "@mediapipe/tasks-vision";
import type { Connection } from "../service/connection";
import type { Hand, TakeFrame } from "../service/contract";
import { $, button, el, icon, toast } from "./dom";
import { drawHands, loadHandTracker, matchScore, toSequence, type Pt } from "./handtrack";

const THRESHOLD = 0.6;
const TAKES = 2;
const RECORD_MS = 2600;
const GLASSES_TIMEOUT_MS = 6000;
const SAVE_TIMEOUT_MS = 10000;

type Screen = "closed" | "name" | "capture" | "test" | "saving" | "done";
type Mode = "glasses" | "camera" | "video";
type Tracker = "off" | "loading" | "ready" | "failed";

const asPt = (points: Hand["points"]): Pt[] => points.map(([x, y, z]) => ({ x, y, z }));

export function createStudio(conn: Connection, opts: { isLive: () => boolean; goLive: () => void; onSaved: (label: string, fromVideo: boolean) => void; onCancelUnknown: () => void; onOpenChange: (open: boolean) => void }) {
  const scrim = $("teachScrim");
  const dlg = $("teach");

  const stageBox = el("div", "feed");
  const video = el("video");
  video.muted = true;
  video.playsInline = true;
  const overlay = el("canvas");
  const statusLine = el("div", "feed-status");
  const countdown = el("div", "feed-count");
  const shutter = el("button", "shutter");
  shutter.type = "button";
  shutter.innerHTML = '<span class="shutter-core"></span>';
  stageBox.append(video, overlay, statusLine, countdown, shutter);

  let screen: Screen = "closed";
  let label = "";
  let fromUnknown = false;
  let mode: Mode = "glasses";
  let stream: MediaStream | null = null;
  let cameraState: "off" | "starting" | "on" | "blocked" = "off";
  let tracker: Tracker = "off";
  let landmarker: HandLandmarker | null = null;
  let hands: Pt[][] = [];
  let takes: number[][][] = [];
  let rawTakes: TakeFrame[][] = [];
  let score: number | null = null;
  let phase: "idle" | "countdown" | "recording" = "idle";
  let purpose: "take" | "test" = "take";
  let frames: (Pt[] | null)[] = [];
  let rawFrames: TakeFrame[] = [];
  let recordStart = 0;
  let message = "";
  let usedVideo = false;
  let lastVideoTs = 0;
  let timer = 0;
  let loop = 0;
  let last: Element | null = null;

  const isOpen = () => screen !== "closed";
  const inStudio = () => screen === "capture" || screen === "test";
  const busy = () => phase !== "idle";

  function clearTakes() {
    if (takes.length && mode === "glasses") conn.send({ type: "teach_stop", label: "" });
    takes = [];
    rawTakes = [];
    score = null;
    message = "";
  }

  function stopCamera() {
    stream?.getTracks().forEach((t) => t.stop());
    stream = null;
    video.srcObject = null;
    cameraState = "off";
  }

  async function startCamera() {
    if (stream) return;
    if (!navigator.mediaDevices?.getUserMedia) {
      cameraState = "blocked";
      return render();
    }
    cameraState = "starting";
    render();
    try {
      stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "user", width: { ideal: 640 }, height: { ideal: 480 } }, audio: false });
      video.removeAttribute("src");
      video.srcObject = stream;
      await video.play().catch(() => {});
      cameraState = "on";
    } catch {
      cameraState = "blocked";
    }
    render();
  }

  async function needTracker() {
    if (tracker === "ready" || tracker === "loading") return;
    tracker = "loading";
    render();
    try {
      landmarker = await loadHandTracker();
      tracker = "ready";
    } catch (err) {
      console.error(err);
      tracker = "failed";
    }
    render();
  }

  function detect() {
    if (mode === "glasses" || !landmarker || video.readyState < 2 || video.paused) return;
    const ts = Math.max(lastVideoTs + 1, performance.now());
    lastVideoTs = ts;
    try {
      hands = landmarker.detectForVideo(video, ts).landmarks.map((pts) => pts.map((p) => ({ x: p.x, y: p.y, z: p.z })));
    } catch {
      hands = [];
    }
  }

  function draw() {
    const w = overlay.clientWidth;
    const h = overlay.clientHeight;
    if (!w || !h) return;
    const dpr = Math.min(2, devicePixelRatio || 1);
    if (overlay.width !== Math.round(w * dpr)) {
      overlay.width = Math.round(w * dpr);
      overlay.height = Math.round(h * dpr);
    }
    const ctx = overlay.getContext("2d")!;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    const vw = mode === "glasses" ? 4 : video.videoWidth || 4;
    const vh = mode === "glasses" ? 3 : video.videoHeight || 3;
    const s = Math.min(w / vw, h / vh);
    const R = { x: (w - vw * s) / 2, y: (h - vh * s) / 2, w: vw * s, h: vh * s };
    drawHands(ctx, hands, R, Math.max(2, w / 220));
  }

  function setStatus() {
    let text = "";
    let cls = "wait";
    if (mode === "glasses") {
      text = hands.length ? "Hand found" : "Simulated signing";
      if (hands.length) cls = "ok";
    } else if (mode === "video") {
      text = tracker === "ready" ? "Reading your video" : "Loading hand tracking";
    } else if (cameraState === "starting") text = "Starting camera";
    else if (cameraState === "blocked") {
      text = "Camera not available";
      cls = "bad";
    } else if (tracker === "loading") text = "Loading hand tracking";
    else if (tracker === "failed") {
      text = "Hand tracking needs internet the first time";
      cls = "bad";
    } else if (hands.length) {
      text = hands.length > 1 ? "Both hands found" : "Hand found";
      cls = "ok";
    } else text = "Show your hand to the camera";
    if (statusLine.textContent !== text) statusLine.textContent = text;
    statusLine.className = `feed-status ${cls}`;
  }

  function tick() {
    if (!inStudio()) return;
    detect();
    draw();
    setStatus();
    if (phase === "recording") {
      // Glasses frames are collected as they arrive, in feed().
      if (mode !== "glasses") {
        frames.push(hands[0] ?? null);
        rawFrames.push({ t_ms: Math.round(performance.now() - recordStart), hands: hands.map((h) => ({ side: "right" as const, points: h.map((p) => [p.x, p.y, p.z] as [number, number, number]) })) });
      }
      if (mode === "camera" && performance.now() - recordStart >= RECORD_MS) finishRecording();
    }
    loop = requestAnimationFrame(tick);
  }

  function capture() {
    if (busy()) return;
    message = "";
    score = null;
    purpose = screen === "test" ? "test" : "take";
    phase = "countdown";
    render();
    let n = 3;
    const step = () => {
      if (!inStudio()) return;
      if (n > 0) {
        countdown.textContent = String(n--);
        timer = window.setTimeout(step, 750);
        return;
      }
      countdown.textContent = "";
      beginRecording();
    };
    step();
  }

  function beginRecording() {
    frames = [];
    rawFrames = [];
    recordStart = performance.now();
    phase = "recording";
    render();
    if (mode !== "glasses") return;
    if (purpose === "test") timer = window.setTimeout(finishRecording, RECORD_MS);
    if (purpose === "take") {
      conn.send({ type: "teach_start", label });
      timer = window.setTimeout(() => {
        phase = "idle";
        message = "That didn't record. Try again";
        render();
      }, GLASSES_TIMEOUT_MS);
    } else conn.mock?.aliceTriesTaught();
  }

  function finishRecording() {
    if (phase !== "recording") return;
    clearTimeout(timer);
    phase = "idle";
    const sequence = toSequence(frames);
    if (!sequence) {
      // The service has already counted this take, so both sides start again together.
      if (mode === "glasses" && purpose === "take") clearTakes();
      message = mode === "video" ? "I couldn't find a hand in that video. Try a clip with your hands clearly in view" : "I couldn't see your hand clearly. Keep it in the frame and try again";
      return render();
    }
    if (purpose === "take") {
      takes.push(sequence);
      rawTakes.push(rawFrames);
      if (takes.length >= TAKES) screen = "test";
    } else score = matchScore(sequence, takes);
    render();
  }

  async function uploadVideo(file: File) {
    if (busy()) return;
    usedVideo = true;
    setModeVideo();
    const url = URL.createObjectURL(file);
    video.srcObject = null;
    video.src = url;
    await needTracker();
    if (tracker !== "ready") {
      message = "Reading hands from a video needs hand tracking, which needs internet the first time";
      return render();
    }
    purpose = "take";
    frames = [];
    rawFrames = [];
    recordStart = performance.now();
    phase = "recording";
    render();
    video.onended = () => {
      finishRecording();
      URL.revokeObjectURL(url);
      video.onended = null;
      video.removeAttribute("src");
      mode = "camera";
      void startCamera();
    };
    video.play().catch(() => {
      phase = "idle";
      message = "That video couldn't be played. Try an MP4 or MOV file";
      render();
    });
  }
  function setModeVideo() {
    stopCamera();
    mode = "video";
  }

  function save() {
    screen = "saving";
    render();
    const fromGlasses = mode === "glasses";
    const sent = fromGlasses
      ? conn.send({ type: "teach_stop", label })
      : conn.send({ type: "teach_landmarks", label, source: usedVideo ? "video" : "camera", takes: rawTakes });
    if (!sent) return failSave("Not connected, so that wasn't saved. Try again when you're back online");
    timer = window.setTimeout(() => failSave("InSync didn't confirm the save. Try again"), SAVE_TIMEOUT_MS);
  }
  function failSave(reason: string) {
    clearTimeout(timer);
    screen = "test";
    score = null;
    message = reason;
    render();
  }

  function close() {
    cancelAnimationFrame(loop);
    clearTimeout(timer);
    stopCamera();
    screen = "closed";
    phase = "idle";
    countdown.textContent = "";
    scrim.hidden = true;
    opts.onOpenChange(false);
    if (last instanceof HTMLElement) last.focus();
  }
  function cancel() {
    if (phase === "recording") return;
    if (fromUnknown) opts.onCancelUnknown();
    conn.send({ type: "teach_stop", label: "" });
    close();
  }

  function enterCapture() {
    takes = [];
    rawTakes = [];
    score = null;
    message = "";
    usedVideo = false;
    screen = "capture";
    mode = "camera";
    if (!opts.isLive()) opts.goLive();
    render();
    cancelAnimationFrame(loop);
    loop = requestAnimationFrame(tick);
    void needTracker();
    void startCamera().then(() => {
      // Rehearsing somewhere with no camera: the fake backend can stand in, and says so.
      if (cameraState === "blocked" && conn.mock && inStudio()) {
        mode = "glasses";
        message = "No camera here, so this is simulated signing";
        render();
      }
    });
  }

  function steps() {
    const bar = el("div", "teach-steps");
    const at = screen === "name" ? 0 : screen === "capture" ? 1 : 2;
    ["Name it", "Record it twice", "Test it"].forEach((t, i) => bar.appendChild(el("span", i === at ? "on" : i < at ? "done" : "", t)));
    return bar;
  }

  function render() {
    scrim.hidden = screen === "closed";
    dlg.className = inStudio() ? "teach studio" : "teach";
    dlg.textContent = "";
    if (screen === "closed") return;
    const WORD = label.toUpperCase();
    const row = el("div", "teach-acts");

    if (screen === "name") {
      const h = el("h3", undefined, fromUnknown ? "What does that sign mean?" : "Add a sign");
      h.id = "teachTitle";
      const input = el("input", "teach-input");
      input.type = "text";
      input.autocomplete = "off";
      input.placeholder = "Northumbria Digital";
      input.value = label;
      input.setAttribute("aria-label", "The word for the new sign");
      const go = () => {
        label = input.value.trim().toLowerCase();
        if (label) enterCapture();
      };
      const next = button("act", "Next", go);
      next.disabled = !input.value.trim();
      input.addEventListener("input", () => (next.disabled = !input.value.trim()));
      input.addEventListener("keydown", (e) => {
        if (e.key === "Enter") go();
      });
      row.append(next, button("ghost", "Cancel", cancel));
      dlg.append(steps(), h, el("p", "teach-text", "Type the word. Names, places and school words are a good start."), input, row);
      input.focus();
    } else if (inStudio()) {
      const left = el("div", "teach-left");
      const right = el("div", "teach-right");
      left.appendChild(stageBox);
      stageBox.classList.toggle("mirror", mode === "camera");
      const ready = mode === "glasses" || (mode === "camera" && cameraState === "on" && tracker === "ready");
      const testing = screen === "test";
      shutter.disabled = busy() || !ready;
      shutter.classList.toggle("recording", phase === "recording");
      shutter.hidden = score !== null || mode === "video";
      shutter.setAttribute("aria-label", testing ? "Test the sign" : `Record take ${takes.length + 1}`);
      const h = el("h3");
      h.id = "teachTitle";
      right.append(steps(), h);
      if (!testing) {
        h.textContent = takes.length ? `Good. Sign ${WORD} once more` : `Sign ${WORD}`;
        right.appendChild(el("p", "teach-text", phase === "countdown" ? "Get ready" : phase === "recording" ? "Recording. Sign at your normal pace" : "Press the button, wait for 3, 2, 1, then sign."));
        if (mode === "camera") {
          const up = el("label", "upl");
          up.innerHTML = `${icon("up")}<span>Upload a video instead</span>`;
          const file = el("input", "sr");
          file.type = "file";
          file.accept = "video/*";
          file.disabled = busy();
          file.setAttribute("aria-label", "Upload a video of the sign");
          file.addEventListener("change", () => {
            if (file.files?.[0]) void uploadVideo(file.files[0]);
          });
          up.appendChild(file);
          right.appendChild(up);
        }
        if (takes.length) row.appendChild(button("ghost", "Start over", () => (clearTakes(), render())));
        const c = button("ghost", "Cancel", cancel);
        c.disabled = phase === "recording";
        row.appendChild(c);
      } else if (score === null) {
        h.textContent = `Test it: sign ${WORD} once more`;
        right.appendChild(el("p", "teach-text", phase === "countdown" ? "Get ready" : phase === "recording" ? "Comparing with your two recordings" : "Press the button and sign it. I'll show how close it is to your recordings."));
        const skip = button("ghost", "Skip test", save);
        skip.disabled = busy();
        row.appendChild(skip);
      } else {
        const pass = score >= THRESHOLD;
        h.textContent = pass ? `I recognised ${WORD}` : "Not recognised";
        const meter = el("div", `score ${pass ? "pass" : ""}`);
        meter.innerHTML = `<div class="score-big">${Math.round(score * 100)}%</div><div class="score-bar"><i style="transform:scaleX(${score.toFixed(3)})"></i></div><div class="score-label"><span>Match with your recordings</span><span>60% to accept</span></div>`;
        right.append(meter, el("p", "teach-text", pass ? "That's close to your recordings. I'll understand it when you sign it." : "That looked different from your recordings. Try the same pace and position."));
        const again = button(pass ? "ghost" : "act", "Test again", () => ((score = null), render()));
        if (pass) row.append(button("act", "Save sign", save), again);
        else row.append(again, button("ghost", "Record again", () => { clearTakes(); screen = "capture"; render(); }), button("ghost", "Save anyway", save));
      }
      if (message) right.appendChild(el("p", "teach-msg", message));
      right.appendChild(row);
      dlg.append(left, right);
    } else if (screen === "saving") {
      const h = el("h3", undefined, `Saving ${WORD}`);
      h.id = "teachTitle";
      dlg.appendChild(h);
    } else {
      const h = el("h3", undefined, `${WORD} is in your signs`);
      h.id = "teachTitle";
      if (!fromUnknown) row.appendChild(button("act", "Add another", () => { label = ""; screen = "name"; render(); }));
      row.appendChild(button(fromUnknown ? "act" : "ghost", "Done", close));
      dlg.append(h, el("p", "teach-text", fromUnknown ? "Carry on. Sign it again and I'll understand it." : "Find it any time under My signs."), row);
    }
  }

  shutter.addEventListener("click", capture);
  addEventListener("keydown", (e) => {
    if (e.key === "Escape" && isOpen()) cancel();
  });

  const open = (start: Screen, unknown: boolean) => {
    if (isOpen()) return;
    last = document.activeElement;
    fromUnknown = unknown;
    label = "";
    screen = start;
    opts.onOpenChange(true);
    render();
  };

  return {
    /** Add a sign, from anywhere. */
    add: () => open("name", false),
    /** The service met a sign it doesn't know, and Alice chose to teach it. */
    teachUnknown: () => open("name", true),
    get open() {
      return isOpen();
    },
    /** Hand points from the glasses, for the glasses recording mode. */
    feed(incoming: Hand[]) {
      if (mode !== "glasses" || !inStudio()) return;
      hands = incoming.map((h) => asPt(h.points));
      if (phase === "recording") frames.push(hands[0] ?? null);
    },
    takeDone() {
      if (mode === "glasses" && phase === "recording") finishRecording();
    },
    learned(name: string) {
      if (screen !== "saving" && screen !== "closed") return;
      clearTimeout(timer);
      if (screen === "saving") {
        opts.onSaved(name, usedVideo);
        stopCamera();
        cancelAnimationFrame(loop);
        label = name;
        screen = "done";
        render();
      }
    },
    failed(reason: string) {
      if (screen === "saving") failSave(reason);
      else toast(reason);
    },
  };
}
