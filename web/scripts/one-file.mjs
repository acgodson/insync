// Builds the fake-backend app into one HTML file you can double-click and share.
// Hand tracking's runtime loads from a CDN, so it needs internet. The avatar isn't included.
// Run: node scripts/one-file.mjs ../demo/Almero-test.html
import { readFile, readdir, writeFile, rm } from "node:fs/promises";
import { build } from "vite";

const out = process.argv[2] ?? "../demo/Almero-test.html";
const dir = "build-onefile";
process.env.VITE_MEDIAPIPE_WASM = "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.14/wasm";
await build({
  base: "./",
  logLevel: "warn",
  define: { "import.meta.env.VITE_MOCK": JSON.stringify("1") },
  build: {
    outDir: dir,
    assetsInlineLimit: 100_000_000, // fonts become part of the file
    cssCodeSplit: false,
    modulePreload: false,
    rollupOptions: { output: { format: "iife", inlineDynamicImports: true } },
  },
  publicDir: false,
});
const assets = await readdir(`${dir}/assets`);
const css = await readFile(`${dir}/assets/${assets.find((f) => f.endsWith(".css"))}`, "utf8");
const js = await readFile(`${dir}/assets/${assets.find((f) => f.endsWith(".js"))}`, "utf8");
let html = await readFile(`${dir}/index.html`, "utf8");
html = html.replace(/<link rel="stylesheet"[^>]*>/, () => `<style>${css}</style>`);
html = html.replace(/<script[^>]*src="[^"]*"[^>]*><\/script>/, "");
html = html.replace("</body>", () => `<script>${js.replace(/<\/script/gi, "<\\/script")}</script></body>`);
await writeFile(out, html);
await rm(dir, { recursive: true });
console.log(out, (html.length / 1e6).toFixed(2), "MB");
