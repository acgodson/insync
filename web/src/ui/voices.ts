// Alice's voice: how her signs sound when InSync says them out loud.
import { el, icon, store } from "./dom";

const ACCENTS: Record<string, string> = {
  "en-GB": "British", "en-US": "American", "en-NG": "Nigerian", "en-AU": "Australian", "en-IN": "Indian",
  "en-ZA": "South African", "en-IE": "Irish", "en-CA": "Canadian", "en-NZ": "New Zealand", "en-KE": "Kenyan",
  "en-GH": "Ghanaian", "en-TZ": "Tanzanian", "en-SG": "Singaporean", "en-PH": "Filipino", "en-HK": "Hong Kong",
};

// Joke voices that ship with macOS. Nobody should speak for Alice as "Bubbles".
const NOVELTY = /^(Albert|Bad News|Bahh|Bells|Boing|Bubbles|Cellos|Good News|Jester|Organ|Superstar|Trinoids|Whisper|Wobble|Zarvox|Fred|Junior|Kathy|Ralph)\b/i;

const canSpeak = "speechSynthesis" in window;
let voices: SpeechSynthesisVoice[] = [];
let chosen = store.get("voice") ?? "";
export let rate = Number(store.get("rate") ?? 1);
const listeners = new Set<() => void>();

const accentOf = (v: SpeechSynthesisVoice) => ACCENTS[v.lang.replace("_", "-")] ?? v.lang;
const cleanName = (v: SpeechSynthesisVoice) =>
  v.name.replace(/^(Microsoft|Google|Apple)\s+/i, "").replace(/\s*Online \(Natural\)/i, "").replace(/\s*-\s*English.*$/i, "").replace(/\s*\(.*\)$/, "");

function loadVoices() {
  voices = speechSynthesis.getVoices().filter((v) => /^en/i.test(v.lang) && !NOVELTY.test(v.name));
  // British voices first: this is a BSL product, and people choose a voice to match them.
  const rank = (v: SpeechSynthesisVoice) => (accentOf(v) === "British" ? 0 : 1);
  voices.sort((a, b) => rank(a) - rank(b) || accentOf(a).localeCompare(accentOf(b)) || a.name.localeCompare(b.name));
  listeners.forEach((fn) => fn());
}
if (canSpeak) {
  loadVoices();
  speechSynthesis.addEventListener("voiceschanged", loadVoices);
}

export function say(text: string, voice = voices.find((v) => v.voiceURI === chosen)) {
  if (!canSpeak) return;
  const u = new SpeechSynthesisUtterance(text);
  if (voice) {
    u.voice = voice;
    u.lang = voice.lang;
  } else u.lang = "en-GB";
  u.rate = rate;
  speechSynthesis.cancel();
  speechSynthesis.speak(u);
}

/** The name of the voice this person chose, sent with their sentences. */
export const chosenVoiceName = () => voices.find((v) => v.voiceURI === chosen)?.name ?? "";

/** Speak someone else's sentence in the voice they chose, if this device has it. */
export function sayAs(text: string, voiceName?: string, onDone?: () => void) {
  if (!canSpeak) return onDone?.();
  const voice = voices.find((v) => v.name === voiceName) ?? voices.find((v) => v.voiceURI === chosen);
  const u = new SpeechSynthesisUtterance(text);
  if (voice) {
    u.voice = voice;
    u.lang = voice.lang;
  } else u.lang = "en-GB";
  u.rate = rate;
  u.onend = u.onerror = () => onDone?.();
  speechSynthesis.speak(u);
}

export function stopSpeaking() {
  if (canSpeak) speechSynthesis.cancel();
}

export function setRate(value: number) {
  rate = value;
  store.set("rate", String(value));
  say("This is how fast I'll speak.");
}

export function renderVoiceList(box: HTMLElement) {
  const draw = () => {
    if (!box.isConnected && box.childElementCount) {
      listeners.delete(draw);
      return;
    }
    box.textContent = "";
    if (!canSpeak) return void box.appendChild(el("p", "note", "This browser can't speak. Try Chrome or Edge."));
    if (!voices.length) return void box.appendChild(el("p", "note", "Looking for voices on this device"));
    for (const v of voices) {
      const b = el("button", "vopt");
      b.type = "button";
      b.setAttribute("role", "radio");
      b.setAttribute("aria-checked", String(v.voiceURI === chosen));
      const text = el("span", "vt");
      text.append(el("b", undefined, cleanName(v)), el("small", undefined, `${accentOf(v)} English`));
      const play = el("span", "vplay");
      play.innerHTML = icon("play");
      b.append(text, play);
      b.addEventListener("click", () => {
        chosen = v.voiceURI;
        store.set("voice", chosen);
        say("Hi, I'm Alice. Nice to meet you.", v);
        draw();
      });
      box.appendChild(b);
    }
  };
  listeners.add(draw);
  draw();
}
