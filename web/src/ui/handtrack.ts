// Hand tracking in the browser, and comparing two recordings of a sign.
import type { HandLandmarker } from "@mediapipe/tasks-vision";

const MODEL = "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task";

export interface Pt {
  x: number;
  y: number;
  z: number;
}

let loading: Promise<HandLandmarker> | null = null;

/** Loads once. The model file downloads the first time, so that needs internet. */
export function loadHandTracker() {
  loading ??= (async () => {
    const { FilesetResolver, HandLandmarker: Landmarker } = await import("@mediapipe/tasks-vision");
    const files = await FilesetResolver.forVisionTasks(`${import.meta.env.BASE_URL}mediapipe/wasm`);
    const options = (delegate: "GPU" | "CPU") => ({ baseOptions: { modelAssetPath: MODEL, delegate }, runningMode: "VIDEO" as const, numHands: 2 });
    return Landmarker.createFromOptions(files, options("GPU")).catch(() => Landmarker.createFromOptions(files, options("CPU")));
  })();
  loading.catch(() => (loading = null)); // let it try again later
  return loading;
}

export const HAND_BONES = [[0, 1], [1, 2], [2, 3], [3, 4], [0, 5], [5, 6], [6, 7], [7, 8], [5, 9], [9, 10], [10, 11], [11, 12], [9, 13], [13, 14], [14, 15], [15, 16], [13, 17], [0, 17], [17, 18], [18, 19], [19, 20]];

/** Draws hand points on a canvas. Amber, because these are Alice's hands. */
export function drawHands(ctx: CanvasRenderingContext2D, hands: Pt[][], R: { x: number; y: number; w: number; h: number }, lw: number) {
  ctx.lineCap = "round";
  ctx.strokeStyle = ctx.fillStyle = "#f0b54a";
  ctx.lineWidth = lw;
  for (const hand of hands) {
    for (const [a, b] of HAND_BONES) {
      ctx.beginPath();
      ctx.moveTo(R.x + hand[a].x * R.w, R.y + hand[a].y * R.h);
      ctx.lineTo(R.x + hand[b].x * R.w, R.y + hand[b].y * R.h);
      ctx.stroke();
    }
    for (const p of hand) {
      ctx.beginPath();
      ctx.arc(R.x + p.x * R.w, R.y + p.y * R.h, lw * 1.2, 0, Math.PI * 2);
      ctx.fill();
    }
  }
}

const FRAMES = 24;

/** Turns a recording into 24 evenly spaced frames, relative to the wrist and hand size. */
export function toSequence(frames: (Pt[] | null)[]): number[][] | null {
  const valid = frames.filter((f): f is Pt[] => !!f);
  if (valid.length < Math.max(6, frames.length * 0.35)) return null;
  const features = valid.map((pts) => {
    const w = pts[0];
    const m = pts[9];
    const size = Math.hypot(m.x - w.x, m.y - w.y, m.z - w.z) || 1e-3;
    const f: number[] = [];
    for (let i = 1; i < 21; i++) f.push((pts[i].x - w.x) / size, (pts[i].y - w.y) / size, (pts[i].z - w.z) / size);
    f.push((w.x - 0.5) * 4, (w.y - 0.5) * 4);
    return f;
  });
  return Array.from({ length: FRAMES }, (_, k) => features[Math.round((k * (features.length - 1)) / (FRAMES - 1))]);
}

/** Dynamic time warping: how far apart two movements are, even at different speeds. */
export function dtw(a: number[][], b: number[][]) {
  const D = Array.from({ length: a.length + 1 }, () => new Float64Array(b.length + 1).fill(Infinity));
  D[0][0] = 0;
  for (let i = 1; i <= a.length; i++) {
    for (let j = 1; j <= b.length; j++) {
      let sum = 0;
      for (let k = 0; k < a[i - 1].length; k++) {
        const d = a[i - 1][k] - b[j - 1][k];
        sum += d * d;
      }
      D[i][j] = Math.sqrt(sum / a[i - 1].length) + Math.min(D[i - 1][j], D[i][j - 1], D[i - 1][j - 1]);
    }
  }
  return D[a.length][b.length] / (a.length + b.length);
}

/** 0 to 1: how close an attempt is, measured against how close the two takes were to each other. */
export function matchScore(attempt: number[][], takes: number[][][]) {
  const expected = Math.max(dtw(takes[0], takes[1]), 0.06);
  const ratio = Math.min(dtw(attempt, takes[0]), dtw(attempt, takes[1])) / expected;
  return Math.max(0.03, Math.min(0.97, ratio <= 1 ? 0.97 : 0.97 * Math.exp(-0.85 * (ratio - 1))));
}
