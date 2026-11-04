// A guided tour. Steps whose target isn't on screen are left out.
import { $, button, el } from "./dom";

const STEPS: { target: string; title: string; text: string }[] = [
  { target: "pinned", title: "The main tile", text: "The biggest tile, with captions inside it. Pin any other tile to swap what's here." },
  { target: "capsBox", title: "Captions", text: "Everything said or signed appears here, with the speaker's name." },
  { target: "tile-self", title: "Your tile", text: "Sign here. The dots show what Almero can see of your hands." },
  { target: "pauseBtn", title: "Pause Almero", text: "Stops recognition and speech. Typing in the transcript still works." },
  { target: "addSign", title: "Add a sign", text: "Teach Almero a name or a word: record it twice, test it, save it." },
  { target: "transcriptBtn", title: "Transcript", text: "The whole conversation, and a place to type." },
  { target: "moreBtn", title: "More", text: "My signs, and your voice and interpreter." },
];

export function createTour() {
  const root = $("tour");
  const ring = $("tourRing");
  const tip = $("tourTip");
  let steps = STEPS;
  let index = -1;

  const end = () => {
    index = -1;
    root.hidden = true;
  };

  const place = () => {
    if (index < 0) return;
    const step = steps[index];
    const app = $("app").getBoundingClientRect();
    const r = $(step.target).getBoundingClientRect();
    const pad = 6;
    Object.assign(ring.style, {
      left: `${r.left - app.left - pad}px`,
      top: `${r.top - app.top - pad}px`,
      width: `${r.width + pad * 2}px`,
      height: `${r.height + pad * 2}px`,
    });

    tip.textContent = "";
    const row = el("div", "tip-row");
    const nav = el("div", "tip-row");
    const nextBtn = button("act", index === steps.length - 1 ? "Done" : "Next", () => {
      if (index >= steps.length - 1) return end();
      index++;
      place();
    });
    nav.append(
      button("ghost", index ? "Back" : "Skip", () => {
        if (!index) return end();
        index--;
        place();
      }),
      nextBtn,
    );
    row.append(el("span", "count", `${index + 1} of ${steps.length}`), nav);
    tip.append(el("h4", undefined, step.title), el("p", undefined, step.text), row);

    const width = Math.min(320, app.width - 24);
    const height = tip.offsetHeight || 150;
    const below = r.bottom - app.top + 14;
    const above = r.top - app.top - height - 14;
    tip.style.left = `${Math.max(12, Math.min(r.left - app.left, app.width - width - 12))}px`;
    tip.style.top = `${below + height < app.height - 12 ? below : above > 12 ? above : Math.max(12, (app.height - height) / 2)}px`;
    nextBtn.focus();
  };

  addEventListener("resize", place);
  addEventListener("keydown", (e) => {
    if (e.key === "Escape" && index >= 0) end();
  });

  return {
    start() {
      steps = STEPS.filter((s) => document.getElementById(s.target));
      index = 0;
      root.hidden = false;
      place();
    },
  };
}
