// The landing page. Its hero is the real avatar and the real caption styles,
// running a short conversation, rather than a picture of the product.
import type { Stage } from "../avatar/stage";
import { AVATAR_ON } from "../brand";
import { $, el } from "./dom";

const SCENES: { who: string; tint: "bob" | "alice"; text: string; signs?: string[]; chip: string }[] = [
  { who: "Sam", tint: "bob", text: "Can you take the client call on Monday?", signs: ["you", "question", "good"], chip: "Signing Sam's words" },
  { who: "Alice, via Almero", tint: "alice", text: "Yes. What time is it?", chip: "Ready" },
  { who: "Sam", tint: "bob", text: "Ten o'clock. Thank you.", signs: ["today", "thank"], chip: "Signing Sam's words" },
  { who: "Alice, via Almero", tint: "alice", text: "Thank you. See you then.", chip: "Ready" },
];
const SCENE_MS = 4800;

export function createLanding(stage: Stage, onOpen: () => void) {
  const root = $("landing");
  const tile = $("heroTile");
  const caps = $("heroCaps");
  const chip = $("heroChip");
  const still = matchMedia("(prefers-reduced-motion: reduce)").matches;
  let timer = 0;
  let at = 0;
  const gloss = el("div", "gloss");
  if (!AVATAR_ON) tile.prepend(gloss);

  function line(i: number) {
    const s = SCENES[i];
    const p = el("p", `line ${s.tint}`);
    p.append(el("span", "who", s.who), el("span", "words", s.text));
    caps.appendChild(p);
    const lines = caps.querySelectorAll(".line");
    if (lines.length > 2) lines[0].remove();
    chip.textContent = s.chip;
    if (!AVATAR_ON) gloss.textContent = (s.signs ?? []).join(" · ").toUpperCase();
    tile.classList.toggle("speaking", !!s.signs);
    if (s.signs && !still) stage.play(s.signs, []);
  }

  function run() {
    line(at);
    at = (at + 1) % SCENES.length;
    if (!still) timer = window.setTimeout(run, SCENE_MS);
  }

  const open = () => {
    clearTimeout(timer);
    root.hidden = true;
    onOpen();
  };
  for (const id of ["landTop", "landCta", "landEnd"]) $(id).addEventListener("click", open);

  return {
    show() {
      root.hidden = false;
      root.scrollTop = 0;
      stage.mount(tile);
      stage.setInsets(16, 148);
      caps.textContent = "";
      at = 0;
      clearTimeout(timer);
      run();
    },
  };
}
