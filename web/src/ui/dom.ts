export const $ = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;

export function el<K extends keyof HTMLElementTagNameMap>(tag: K, cls?: string, text?: string): HTMLElementTagNameMap[K] {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
}

export function button(cls: string, text: string, onClick: () => void) {
  const b = el("button", cls, text);
  b.type = "button";
  b.addEventListener("click", onClick);
  return b;
}

export const icon = (id: string) => `<svg class="i" aria-hidden="true"><use href="#i-${id}" /></svg>`;

let toastTimer = 0;
export function toast(text: string) {
  const t = $("toast");
  t.textContent = text;
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = window.setTimeout(() => (t.hidden = true), 3500);
}

// Storage can throw in private windows, so settings just stop persisting there.
export const store = {
  get(key: string) {
    try {
      return localStorage.getItem(`insync.${key}`);
    } catch {
      return null;
    }
  },
  set(key: string, value: string) {
    try {
      localStorage.setItem(`insync.${key}`, value);
    } catch {
      /* not saved */
    }
  },
  clear() {
    try {
      Object.keys(localStorage)
        .filter((k) => k.startsWith("insync."))
        .forEach((k) => localStorage.removeItem(k));
    } catch {
      /* nothing to clear */
    }
  },
};
