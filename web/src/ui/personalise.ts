// Make it yours: the interpreter who signs to Alice, and the voice that speaks for her.
import type { Stage } from "../avatar/stage";
import { AVATAR_ON } from "../brand";
import { $, button, el, icon, store, toast } from "./dom";
import { rate, renderVoiceList, setRate } from "./voices";

const TONES: { id: string; name: string; skin: number | null }[] = [
  { id: "own", name: "As designed", skin: null },
  { id: "t1", name: "Light", skin: 0xf0cfb4 },
  { id: "t2", name: "Light medium", skin: 0xdcae86 },
  { id: "t3", name: "Medium", skin: 0xbd8a5f },
  { id: "t4", name: "Medium deep", skin: 0x95633f },
  { id: "t5", name: "Deep", skin: 0x6b452c },
  { id: "t6", name: "Very deep", skin: 0x47301f },
];

let tone = store.get("tone") ?? "own";

export function applyTone(stage: Stage) {
  stage.setTone(TONES.find((t) => t.id === tone)?.skin ?? null);
}

export function renderToneList(box: HTMLElement, stage: Stage) {
  box.textContent = "";
  if (!stage.canTone) return void box.appendChild(el("p", "note", "This character's skin can't be changed here"));
  for (const t of TONES) {
    const b = el("button", t.skin === null ? "sw own" : "sw");
    b.type = "button";
    b.title = t.name;
    b.setAttribute("role", "radio");
    b.setAttribute("aria-label", `${t.name} skin tone`);
    b.setAttribute("aria-checked", String(tone === t.id));
    if (t.skin !== null) b.style.background = `#${t.skin.toString(16).padStart(6, "0")}`;
    b.addEventListener("click", () => {
      tone = t.id;
      store.set("tone", t.id);
      applyTone(stage);
      stage.play(["hello"], []);
      renderToneList(box, stage);
    });
    box.appendChild(b);
  }
}

/** Lets someone swap in their own VRM character. Lasts until the page reloads. */
export function characterUpload(stage: Stage, onLoaded: () => void) {
  const label = el("label", "upl");
  label.innerHTML = `${icon("up")}<span>Add a character</span>`;
  const input = el("input", "sr");
  input.type = "file";
  input.accept = ".vrm";
  input.setAttribute("aria-label", "Add a VRM character");
  input.addEventListener("change", async () => {
    const file = input.files?.[0];
    if (!file) return;
    const url = URL.createObjectURL(file);
    try {
      await stage.load(url, () => {});
      applyTone(stage);
      stage.play(["hello"], []);
      toast("Your character is now the signing avatar");
      onLoaded();
    } catch (err) {
      console.error(err);
      toast("That file couldn't be used. Choose a VRM character");
    } finally {
      URL.revokeObjectURL(url);
    }
  });
  label.appendChild(input);
  return label;
}

export function createPersonalise(stage: Stage, onClose: () => void) {
  const scrim = $("persScrim");
  const dlg = $("pers");
  let last: Element | null = null;

  const close = () => {
    scrim.hidden = true;
    onClose();
    if (last instanceof HTMLElement) last.focus();
  };

  const render = () => {
    dlg.textContent = "";
    const head = el("div", "pers-head");
    const titles = el("div");
    const h = el("h3", undefined, AVATAR_ON ? "Choose your avatar and voice" : "Choose your voice");
    h.id = "persTitle";
    titles.append(h);
    const backBtn = button("back", "", close);
    backBtn.innerHTML = `${icon("back")}Back`;
    head.append(backBtn, titles);

    const grid = el("div", "pers-grid");
    const left = el("div", "pers-sec");
    const slot = el("div", "pers-slot");
    slot.id = "persSlot";
    const swatches = el("div", "sws");
    swatches.setAttribute("role", "radiogroup");
    swatches.setAttribute("aria-label", "Avatar skin tone");
    renderToneList(swatches, stage);
    left.append(slot, el("h4", undefined, "Signing avatar"), swatches, characterUpload(stage, render));

    const right = el("div", "pers-sec");
    const voices = el("div", "vlist");
    voices.setAttribute("role", "radiogroup");
    voices.setAttribute("aria-label", "Your voice");
    renderVoiceList(voices);
    const speedRow = el("label", "speed", "Speed");
    const speed = el("input");
    speed.type = "range";
    speed.min = "0.7";
    speed.max = "1.4";
    speed.step = "0.05";
    speed.value = String(rate);
    speed.addEventListener("change", () => setRate(Number(speed.value)));
    speedRow.appendChild(speed);
    right.append(el("h4", undefined, "Your voice"), voices, speedRow);
    if (AVATAR_ON) grid.append(left);
    else grid.classList.add("voice-only");
    grid.append(right);

    const foot = el("div", "pers-foot");
    foot.appendChild(button("act", "Done", close));
    dlg.append(head, grid, foot);
    if (AVATAR_ON) stage.mount(slot);
  };

  scrim.addEventListener("click", (e) => {
    if (e.target === scrim) close();
  });
  addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !scrim.hidden) close();
  });

  return {
    open() {
      last = document.activeElement;
      scrim.hidden = false;
      render();
      (dlg.querySelector('[aria-checked="true"]') as HTMLElement | null)?.focus();
    },
  };
}
