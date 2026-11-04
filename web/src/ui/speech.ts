// The browser's speech recognition, for people who speak. Chrome and Edge send the
// audio to the browser maker's servers, so this needs internet.
type Recognition = {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  onresult: ((e: { resultIndex: number; results: ArrayLike<ArrayLike<{ transcript: string }> & { isFinal: boolean }> }) => void) | null;
  onend: (() => void) | null;
  onerror: ((e: { error: string }) => void) | null;
  start(): void;
  stop(): void;
};

const Ctor = (window as unknown as { SpeechRecognition?: new () => Recognition; webkitSpeechRecognition?: new () => Recognition }).SpeechRecognition ?? (window as unknown as { webkitSpeechRecognition?: new () => Recognition }).webkitSpeechRecognition;

export const canHearSpeech = !!Ctor;

export function createListener(onFinal: (text: string) => void, onProblem: (message: string) => void, onInterim: (text: string) => void = () => {}) {
  let rec: Recognition | null = null;
  let wanted = false;
  const start = () => {
    if (!Ctor) return onProblem("This browser can't turn speech into text. Use Chrome, or type in the transcript");
    if (rec) return;
    rec = new Ctor();
    rec.lang = "en-GB";
    rec.continuous = true;
    rec.interimResults = true;
    rec.onresult = (e) => {
      let interim = "";
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const text = e.results[i][0].transcript.trim();
        if (e.results[i].isFinal) {
          if (text) onFinal(text);
        } else interim += `${text} `;
      }
      onInterim(interim.trim());
    };
    rec.onerror = (e) => {
      if (e.error === "not-allowed" || e.error === "service-not-allowed") {
        wanted = false;
        onProblem("The microphone is blocked. Allow it in the browser, or type in the transcript");
      } else if (e.error === "network") {
        onProblem("Speech to text needs internet. You can type in the transcript");
      }
    };
    // Browsers end recognition after a silence, so carry on while the mic is meant to be on.
    rec.onend = () => {
      rec = null;
      if (wanted) start();
    };
    rec.start();
  };
  return {
    set(on: boolean) {
      wanted = on;
      if (on) start();
      else rec?.stop();
    },
  };
}

/** A live 0 to 1 loudness from the mic, for the level meter and the speaking ring. */
export async function micLevel(onLevel: (level: number) => void) {
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  const ctx = new AudioContext();
  const analyser = ctx.createAnalyser();
  analyser.fftSize = 512;
  ctx.createMediaStreamSource(stream).connect(analyser);
  const data = new Uint8Array(analyser.fftSize);
  let running = true;
  const tick = () => {
    if (!running) return;
    analyser.getByteTimeDomainData(data);
    let sum = 0;
    for (const v of data) sum += (v - 128) ** 2;
    onLevel(Math.min(1, Math.sqrt(sum / data.length) / 40));
    requestAnimationFrame(tick);
  };
  tick();
  return () => {
    running = false;
    stream.getTracks().forEach((t) => t.stop());
    void ctx.close();
  };
}
