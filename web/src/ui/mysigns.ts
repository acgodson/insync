// My signs: everything InSync knows, with the signs Alice taught first.
import { KNOWN_SIGNS } from "../avatar/signs";
import { $, button, el, icon, store } from "./dom";

export interface MySign {
  word: string;
  video: boolean;
}

function loadMine(): MySign[] {
  try {
    return JSON.parse(store.get("mine") ?? "[]") as MySign[];
  } catch {
    return [];
  }
}

export function createMySigns(opts: { onShow: (word: string) => void; onAdd: () => void }) {
  const mine = loadMine();
  let filter: "all" | "yours" = "all";

  function render() {
    $("signCount").textContent = String(new Set([...KNOWN_SIGNS, ...mine.map((m) => m.word)]).size);
    const list = $("signList");
    list.textContent = "";
    const row = (word: string, meta: string) => {
      const b = el("button", "sign-row");
      b.type = "button";
      b.setAttribute("aria-label", `Show the sign for ${word}`);
      b.innerHTML = icon("play");
      const text = el("span", "row-text");
      text.append(el("b", undefined, word), el("small", undefined, meta));
      b.prepend(text);
      b.addEventListener("click", () => opts.onShow(word));
      list.appendChild(b);
    };
    if (filter === "yours" && !mine.length) {
      const empty = el("div", "sign-empty");
      empty.append(el("b", undefined, "No signs of your own yet"), el("p", undefined, "Teach InSync a name, a place or a school word."), button("act", "Add a sign", opts.onAdd));
      list.appendChild(empty);
    }
    for (const s of [...mine].reverse()) row(s.word, s.video ? "Yours, from a video" : "Yours");
    if (filter === "all") {
      const yours = new Set(mine.map((m) => m.word));
      [...KNOWN_SIGNS].filter((w) => !yours.has(w)).sort().forEach((w) => row(w, "Built in"));
    }
    $("signFilter").querySelectorAll("button").forEach((b) => b.setAttribute("aria-checked", String(b.dataset.f === filter)));
  }

  $("signFilter").querySelectorAll("button").forEach((b) =>
    b.addEventListener("click", () => {
      filter = b.dataset.f as typeof filter;
      render();
    }),
  );
  $("signAdd").addEventListener("click", opts.onAdd);
  render();

  return {
    add(word: string, video: boolean) {
      if (!mine.some((m) => m.word === word)) mine.push({ word, video });
      store.set("mine", JSON.stringify(mine));
      render();
    },
  };
}
