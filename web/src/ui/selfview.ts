// The signer's own webcam, with hand tracking drawn on it. One instance moves
// between the join screen and the "You" tile.
import { drawHands, loadHandTracker, type Pt } from "./handtrack";
import { el } from "./dom";
import type { HandLandmarker } from "@mediapipe/tasks-vision";

const DETECT_MS = 50; // 20 a second is plenty, and kinder to the laptop

export class SelfView {
  readonly root = el("div", "selfview");
  /** Called once per tracked frame with the first hand, or null when none is seen. */
  onFrame: ((hands: Pt[][]) => void) | null = null;
  /** Whether tracking should run right now. */
  canTrack: () => boolean = () => false;
  state: "off" | "starting" | "on" | "blocked" = "off";

  private video = el("video");
  private overlay = el("canvas");
  private stream: MediaStream | null = null;
  private landmarker: HandLandmarker | null = null;
  private loadFailed = false;
  private hands: Pt[][] = [];
  private lastDetect = 0;
  private lastTs = 0;
  private simulated = false;
  private detectCost = 0;

  constructor() {
    this.video.muted = true;
    this.video.playsInline = true;
    this.root.append(this.video, this.overlay);
    const loop = () => {
      this.tick();
      requestAnimationFrame(loop);
    };
    requestAnimationFrame(loop);
  }

  attach(slot: HTMLElement) {
    slot.prepend(this.root);
  }

  async start() {
    if (this.stream) return true;
    if (!navigator.mediaDevices?.getUserMedia) {
      this.state = "blocked";
      return false;
    }
    this.state = "starting";
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "user", width: { ideal: 640 }, height: { ideal: 480 } }, audio: false });
      this.video.srcObject = this.stream;
      await this.video.play().catch(() => {});
      this.state = "on";
      return true;
    } catch {
      this.state = "blocked";
      return false;
    }
  }

  stop() {
    this.stream?.getTracks().forEach((t) => t.stop());
    this.stream = null;
    this.video.srcObject = null;
    this.state = "off";
    this.hands = [];
    this.draw();
  }

  loadTracker() {
    if (this.landmarker || this.loadFailed) return;
    loadHandTracker().then(
      (l) => (this.landmarker = l),
      (err) => {
        console.error(err);
        this.loadFailed = true;
      },
    );
  }

  get trackerFailed() {
    return this.loadFailed;
  }

  /** Dots from the fake backend, for rehearsing without a camera. */
  showSimulated(hands: Pt[][]) {
    this.simulated = hands.length > 0;
    this.hands = hands;
    this.draw();
  }

  /** A small still for other people's tiles. There's no live video between laptops. */
  snapshot(): string | undefined {
    if (this.state !== "on" || !this.video.videoWidth) return undefined;
    const canvas = el("canvas");
    canvas.width = 320;
    canvas.height = Math.round((320 * this.video.videoHeight) / this.video.videoWidth);
    const ctx = canvas.getContext("2d");
    if (!ctx) return undefined;
    ctx.translate(canvas.width, 0);
    ctx.scale(-1, 1);
    ctx.drawImage(this.video, 0, 0, canvas.width, canvas.height);
    return canvas.toDataURL("image/jpeg", 0.7);
  }

  private tick() {
    if (this.simulated || this.state !== "on") return;
    if (!this.canTrack() || !this.landmarker || this.video.readyState < 2) {
      if (this.hands.length) {
        this.hands = [];
        this.draw();
      }
      return;
    }
    const now = performance.now();
    // Slower laptops take longer per frame, so give the page room to breathe between them.
    if (now - this.lastDetect < Math.max(DETECT_MS, this.detectCost * 3)) return;
    this.lastDetect = now;
    const ts = Math.max(this.lastTs + 1, now);
    this.lastTs = ts;
    try {
      this.hands = this.landmarker.detectForVideo(this.video, ts).landmarks.map((pts) => pts.map((p) => ({ x: p.x, y: p.y, z: p.z })));
    } catch {
      this.hands = [];
    }
    this.detectCost = performance.now() - now;
    this.draw();
    this.onFrame?.(this.hands);
  }

  private draw() {
    const w = this.overlay.clientWidth;
    const h = this.overlay.clientHeight;
    if (!w || !h) return;
    const dpr = Math.min(2, devicePixelRatio || 1);
    if (this.overlay.width !== Math.round(w * dpr)) {
      this.overlay.width = Math.round(w * dpr);
      this.overlay.height = Math.round(h * dpr);
    }
    const ctx = this.overlay.getContext("2d")!;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    const vw = this.video.videoWidth || 4;
    const vh = this.video.videoHeight || 3;
    // The video uses object-fit: cover, so the picture may run past the tile.
    const s = Math.max(w / vw, h / vh);
    drawHands(ctx, this.hands, { x: (w - vw * s) / 2, y: (h - vh * s) / 2, w: vw * s, h: vh * s }, Math.max(1.5, w / 260));
  }
}
