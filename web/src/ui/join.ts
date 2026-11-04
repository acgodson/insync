// The join screen: name, role, room code, and a camera and mic check.
import type { Role } from "../service/contract";
import { $, store, toast } from "./dom";
import type { SelfView } from "./selfview";
import { micLevel } from "./speech";

export interface JoinInfo {
  name: string;
  role: Role;
  room: string;
  roomName: string;
  mic: boolean;
  cam: boolean;
  photo?: string;
}

const NAMES: Record<Role, string> = { sign: "Alice", speak: "Sam" };

export function createJoin(selfView: SelfView, onJoin: (info: JoinInfo) => void, onBack: () => void) {
  const params = new URLSearchParams(location.search);
  const presetRole = params.get("role") as Role | null;
  // The one-laptop mode sets these per window, so they mustn't overwrite what's saved.
  const remember = !presetRole;

  const nameInput = $<HTMLInputElement>("joinName");
  const roomInput = $<HTMLInputElement>("joinRoom");
  let role: Role = presetRole ?? (store.get("role") === "speak" ? "speak" : "sign");
  let cam = true;
  let mic = role === "speak";
  let stopLevel: (() => void) | null = null;
  let wrapped = false;

  nameInput.value = params.get("name") ?? store.get("name") ?? NAMES[role];

  const setIcon = (b: HTMLElement, id: string) => b.querySelector("use")!.setAttribute("href", `#i-${id}`);

  function renderRole() {
    document.querySelectorAll<HTMLElement>(".role").forEach((b) => b.setAttribute("aria-checked", String(b.dataset.role === role)));
    $("joinTip").hidden = role !== "speak";
  }

  async function applyCamera() {
    const msg = $("previewMsg");
    const b = $("joinCam");
    setIcon(b, cam ? "cam" : "cam-off");
    b.setAttribute("aria-pressed", String(cam));
    b.setAttribute("aria-label", cam ? "Turn camera off" : "Turn camera on");
    selfView.root.classList.toggle("off", !cam);
    if (!cam) {
      selfView.stop();
      msg.textContent = "Camera is off";
      msg.hidden = false;
      return;
    }
    msg.textContent = "Starting camera";
    msg.hidden = false;
    const ok = await selfView.start();
    msg.textContent = "The camera is blocked or missing. Allow it in the browser";
    msg.hidden = ok;
  }

  async function applyMic() {
    const b = $("joinMic");
    setIcon(b, mic ? "mic" : "mic-off");
    b.setAttribute("aria-pressed", String(mic));
    b.setAttribute("aria-label", mic ? "Turn microphone off" : "Turn microphone on");
    stopLevel?.();
    stopLevel = null;
    const bar = $("joinLevel");
    bar.style.transform = "scaleX(0)";
    if (!mic) return;
    try {
      stopLevel = await micLevel((level) => (bar.style.transform = `scaleX(${level.toFixed(3)})`));
    } catch {
      mic = false;
      setIcon(b, "mic-off");
      b.setAttribute("aria-pressed", "false");
      toast("The microphone is blocked or missing. You can still type");
    }
  }

  document.querySelectorAll<HTMLElement>(".role").forEach((b) =>
    b.addEventListener("click", () => {
      const next = b.dataset.role as Role;
      // Keep a typed name, but swap the suggested one with the role.
      if (nameInput.value === NAMES[role]) nameInput.value = NAMES[next];
      role = next;
      if (mic !== (role === "speak")) {
        mic = role === "speak";
        void applyMic();
      }
      renderRole();
    }),
  );
  $("joinCam").addEventListener("click", () => {
    cam = !cam;
    void applyCamera();
  });
  $("joinMic").addEventListener("click", () => {
    mic = !mic;
    void applyMic();
  });
  $("joinCopy").addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(roomInput.value);
      toast("Room code copied");
    } catch {
      toast("Couldn't copy. Select the code and copy it by hand");
    }
  });
  $("joinBack").hidden = !!presetRole;
  $("joinBack").addEventListener("click", () => {
    stopLevel?.();
    stopLevel = null;
    selfView.stop();
    $("join").hidden = true;
    onBack();
  });
  $("joinForm").addEventListener("submit", (e) => {
    e.preventDefault();
    const name = nameInput.value.trim() || NAMES[role];
    const room = roomInput.value.trim() || "alm-7k2-q9p";
    if (remember) {
      store.set("name", name);
      store.set("role", role);
    }
    stopLevel?.();
    stopLevel = null;
    onJoin({ name, role, room, roomName: $("joinTitle").textContent ?? "", mic, cam, photo: selfView.snapshot() });
  });

  return {
    show() {
      $("join").hidden = false;
      renderRole();
      selfView.attach($("preview"));
      void applyCamera();
      void applyMic();
      // Dots on the preview only for people who sign, so they can check their hands show.
      if (role === "sign" || !presetRole) selfView.loadTracker();
      if (!wrapped) {
        wrapped = true;
        const inRoom = selfView.canTrack;
        selfView.canTrack = () => inRoom() || (!$("join").hidden && role === "sign" && cam);
      }
    },
  };
}
