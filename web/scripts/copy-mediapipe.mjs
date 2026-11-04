// Copies hand tracking's runtime files into public/, so they load from our own
// address instead of a CDN. Runs after npm install.
import { cp } from "node:fs/promises";

await cp("node_modules/@mediapipe/tasks-vision/wasm", "public/mediapipe/wasm", { recursive: true });
