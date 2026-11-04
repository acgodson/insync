// Where the hands go for each sign. Positions are in metres on a 1.44 m shoulder
// height: x = the signer's own right, y = up, z = forward. Face spots sit low and
// to the side because the wrist is the target: the hand rises above it, and a
// VRoid head is large for its body, so higher spots would cover the eyes.
// PLACEHOLDER MOVEMENTS, not checked BSL. A Deaf BSL signer needs to check or replace these.

export type Vec3 = [number, number, number];
/** Curl per finger: thumb, index, middle, ring, little. 0 is straight, 1 is closed. */
export type Curls = [number, number, number, number, number];

export const SPOTS = {
  restR: [0.27, 0.97, 0],
  restL: [-0.27, 0.97, 0],
  chin: [0.06, 1.33, 0.2],
  mouth: [0.08, 1.38, 0.2],
  forehead: [0.17, 1.5, 0.2],
  forehead2: [0.23, 1.54, 0.22],
  side: [0.27, 1.54, 0.1],
  forward: [0.12, 1.29, 0.38],
  chest: [0.04, 1.19, 0.21],
  chest_up: [0.04, 1.29, 0.21],
  chest_low: [0.04, 1.09, 0.23],
  chest2: [0.14, 1.17, 0.25],
  chest_nod: [0.04, 1.12, 0.21],
  chest_l: [-0.1, 1.21, 0.23],
  chest_r: [0.2, 1.21, 0.25],
  fs: [0.19, 1.33, 0.27],
  lpalm: [-0.04, 1.08, 0.23],
  lchest: [-0.08, 1.17, 0.23],
  lchest_l: [-0.21, 1.21, 0.21],
  lfwd: [-0.12, 1.26, 0.36],
} satisfies Record<string, Vec3>;

export type Spot = keyof typeof SPOTS;

export const SHAPES = {
  flat: [0.1, 0, 0, 0, 0],
  fist: [0.8, 1, 1, 1, 1],
  point: [0.8, 0, 1, 1, 1],
  spread: [0, 0, 0, 0, 0],
  ok: [0.7, 0.85, 0, 0, 0],
  v: [0.8, 0, 0, 1, 1],
  y: [0, 1, 1, 1, 0],
  c: [0.35, 0.45, 0.45, 0.45, 0.45],
  rest: [0.25, 0.25, 0.3, 0.35, 0.4],
} satisfies Record<string, Curls>;

export type Shape = keyof typeof SHAPES;

export interface SignDef {
  r: Spot[];
  s: Shape;
  l?: Spot[];
  ls?: Shape;
}

const SIGNS: Record<string, SignDef> = {
  hello: { r: ["forehead2", "side"], s: "flat" },
  hi: { r: ["forehead2", "side"], s: "flat" },
  good: { r: ["chin", "forward"], s: "flat" },
  morning: { r: ["chest_low", "chest_up"], l: ["lpalm"], s: "flat", ls: "flat" },
  you: { r: ["forward"], s: "point" },
  me: { r: ["chest"], s: "point" },
  understand: { r: ["forehead", "forehead2"], s: "point" },
  homework: { r: ["chest", "chest2", "chest"], l: ["lpalm"], s: "fist", ls: "flat" },
  yes: { r: ["chest", "chest_nod", "chest", "chest_nod"], s: "fist" },
  no: { r: ["chest_up", "chest"], s: "v" },
  help: { r: ["chest_low", "chest_up"], l: ["lpalm"], s: "fist", ls: "flat" },
  which: { r: ["chest_r", "chest_l"], l: ["lchest", "lchest_l"], s: "fist", ls: "fist" },
  okay: { r: ["chest", "forward"], s: "ok" },
  together: { r: ["chest_r", "chest"], l: ["lchest_l", "lchest"], s: "fist", ls: "fist" },
  thank: { r: ["chin", "forward"], s: "flat" },
  thanks: { r: ["chin", "forward"], s: "flat" },
  please: { r: ["chest", "chest2", "chest"], s: "flat" },
  what: { r: ["forward", "chest_r"], l: ["lfwd"], s: "spread", ls: "spread" },
  question: { r: ["side", "forward"], s: "point" },
  go: { r: ["chest", "forward"], l: ["lfwd"], s: "point", ls: "point" },
  fraction: { r: ["chest_up", "chest_low"], l: ["lpalm"], s: "flat", ls: "flat" },
  water: { r: ["chin", "mouth", "chin"], s: "v" },
  need: { r: ["chest", "chest_low"], s: "point" },
  want: { r: ["forward", "chest"], l: ["lfwd"], s: "spread", ls: "spread" },
  see: { r: ["forehead", "forward"], s: "v" },
  read: { r: ["chest_up", "chest_low"], l: ["lpalm"], s: "v", ls: "flat" },
  book: { r: ["chest"], l: ["lchest"], s: "flat", ls: "flat" },
  class: { r: ["chest_r", "chest_l"], s: "c" },
  now: { r: ["chest_low", "chest_nod"], l: ["lchest"], s: "y", ls: "y" },
  today: { r: ["chest_low"], l: ["lchest"], s: "y", ls: "y" },
  tomorrow: { r: ["side", "forward"], s: "fist" },
  name: { r: ["chest_up"], l: ["lchest"], s: "v", ls: "v" },
  page: { r: ["chest_up", "chest"], l: ["lpalm"], s: "flat", ls: "flat" },
  write: { r: ["chest_up", "chest2"], l: ["lpalm"], s: "ok", ls: "flat" },
  sit: { r: ["chest_up", "chest_low"], l: ["lchest"], s: "v", ls: "v" },
  stop: { r: ["chest_up", "chest_low"], l: ["lpalm"], s: "flat", ls: "flat" },
  finish: { r: ["chest", "chest_r"], l: ["lchest", "lchest_l"], s: "spread", ls: "spread" },
  again: { r: ["chest_up", "chest_low"], l: ["lpalm"], s: "c", ls: "flat" },
};

export const KNOWN_SIGNS = new Set(Object.keys(SIGNS));

const LETTER_SHAPES: Shape[] = ["fist", "flat", "c", "ok", "point", "v", "y", "spread"];
const PLACEHOLDER_SPOTS: Spot[] = ["chest", "chin", "forward", "chest_r", "side", "chest_up"];

// A sign we have no movement for still plays, as a repeatable generic movement.
function placeholderSign(word: string): SignDef {
  let h = 0;
  for (const c of word) h = (h * 31 + c.charCodeAt(0)) % 997;
  const a = PLACEHOLDER_SPOTS[h % 6];
  return { r: [a, PLACEHOLDER_SPOTS[(h >> 2) % 6], a], s: LETTER_SHAPES[h % 8], l: h % 3 === 0 ? ["lpalm"] : undefined, ls: "flat" };
}

export interface TimelineItem {
  kind: "sign" | "letter";
  label: string;
  def: SignDef;
  ms: number;
}

export function buildTimeline(signs: string[], fingerspell: string[]): TimelineItem[] {
  const items: TimelineItem[] = signs.map((label) => ({ kind: "sign", label, def: SIGNS[label] ?? placeholderSign(label), ms: 850 }));
  for (const word of fingerspell) {
    for (const ch of word.toUpperCase()) {
      const shape = LETTER_SHAPES[Math.abs(ch.charCodeAt(0) - 65) % LETTER_SHAPES.length];
      items.push({ kind: "letter", label: ch, def: { r: ["fs"], s: shape }, ms: 380 });
    }
  }
  return items;
}

/** Where a hand is, `p` (0 to 1) of the way along its list of spots. */
export function along(keys: Spot[], p: number, wobble = false): Vec3 {
  if (keys.length === 1) {
    const k = SPOTS[keys[0]];
    return [k[0], k[1] + (wobble ? Math.sin(p * Math.PI * 2) * 0.01 : 0), k[2]];
  }
  const x = p * (keys.length - 1);
  const i = Math.min(Math.floor(x), keys.length - 2);
  const raw = x - i;
  const t = raw * raw * (3 - 2 * raw);
  const a = SPOTS[keys[i]];
  const b = SPOTS[keys[i + 1]];
  return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t];
}
