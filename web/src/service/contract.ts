// Message shapes from docs/ui-contract.md and docs/meeting-room-contract.md.
// PROPOSED items still need the backend team's yes or no.

export type Role = "sign" | "speak";
export type Point3 = [number, number, number];

export interface Participant {
  id: string;
  name: string;
  role: Role;
  mic: boolean;
  cam: boolean;
  photo?: string; // a small still from the join screen; there's no live video between laptops
  hand?: boolean;
}

export interface Hand {
  side: "left" | "right";
  points: Point3[]; // 21 MediaPipe points
  visible: boolean;
}

export interface Candidate {
  label: string;
  confidence: number;
}

export type ServiceMessage =
  | { type: "participants"; items: Participant[]; ts: number }
  | { type: "speaking"; id: string; on: boolean; ts: number }
  | { type: "signing"; id: string; on: boolean; teaching?: boolean; ts: number } // so hearing people can see why nothing's happening
  | { type: "leave"; id: string; ts: number }
  | { type: "caption"; speaker: string; text: string; ts: number }
  | { type: "avatar_play"; signs: string[]; fingerspell?: string[]; ts: number }
  | { type: "sentence"; speaker: string; text: string; voice?: string; ts: number }
  | { type: "status"; latency_ms: number; fps: number; ts: number }
  | { type: "landmarks"; hands: Hand[]; ts: number } // fake backend only: stands in for Alice's webcam
  | { type: "sign_candidates"; items: Candidate[]; ts: number }
  | { type: "sign_recognized"; label: string; confidence: number; ts: number }
  | { type: "unknown_sign"; ts: number }
  | { type: "teach_progress"; label: string; take: number; of: number; ts: number }
  | { type: "sign_learned"; label: string; ts: number }
  | { type: "teach_error"; label: string; reason: string; ts: number };

export interface TakeFrame {
  t_ms: number;
  hands: { side: "left" | "right"; points: Point3[] }[];
}

export type UiMessage =
  | { type: "join"; room: string; id: string; name: string; role: Role; photo?: string; ts: number }
  | { type: "state"; mic: boolean; cam: boolean; hand: boolean; ts: number } // PROPOSED
  | { type: "leave"; id: string; ts: number }
  | { type: "speaking"; id: string; on: boolean; ts: number }
  | { type: "signing"; id: string; on: boolean; teaching?: boolean; ts: number }
  | { type: "session"; state: "live" | "paused"; ts: number }
  | { type: "speech_text"; text: string; source: "speech" | "typed"; ts: number } // typed by someone who signs = their sentence
  | { type: "hands"; frames: TakeFrame[]; ts: number }
  | { type: "voice"; name: string; ts: number } // PROPOSED: the voice this signer chose, so it can be sent with their sentences
  | { type: "teach_start"; label: string; ts: number }
  | { type: "teach_stop"; label: string; ts: number }
  | { type: "teach_landmarks"; label: string; source: "camera" | "video"; takes: TakeFrame[][]; ts: number };

// Distributes Omit over the union, so each message keeps its own fields.
export type Draft<T> = T extends unknown ? Omit<T, "ts"> : never;
