// The only file that knows whether we're on the real service or the fake one.
import type { Draft, Participant, ServiceMessage, UiMessage } from "./contract";
import { MockRoom } from "./mock";

export type LinkState = "connecting" | "open" | "lost";

export interface Connection {
  /** Returns false when the message couldn't be sent. */
  send(m: Draft<UiMessage>): boolean;
  /** Only present on the fake backend. */
  mock?: MockRoom;
  close(): void;
}

const stamp = (m: Draft<UiMessage>) => ({ ...m, ts: Date.now() }) as UiMessage;

export function connect(me: Participant, room: string, onMessage: (m: ServiceMessage) => void, onLink: (s: LinkState) => void): Connection {
  const url: string | undefined = import.meta.env.VITE_SERVICE_URL;
  if (import.meta.env.VITE_MOCK === "1" || !url) {
    const mock = new MockRoom(me, room, onMessage);
    queueMicrotask(() => onLink("open"));
    return { mock, send: (m) => (mock.send(stamp(m)), true), close: () => mock.close() };
  }

  let socket: WebSocket;
  let delay = 1000;
  let closed = false;
  const open = () => {
    onLink("connecting");
    socket = new WebSocket(url);
    socket.onopen = () => {
      delay = 1000;
      socket.send(JSON.stringify(stamp({ type: "join", room, id: me.id, name: me.name, role: me.role, photo: me.photo })));
      onLink("open");
    };
    socket.onmessage = (e) => {
      try {
        onMessage(JSON.parse(e.data as string) as ServiceMessage);
      } catch {
        console.warn("Ignored a message that wasn't JSON", e.data);
      }
    };
    socket.onclose = () => {
      if (closed) return;
      onLink("lost");
      setTimeout(open, delay);
      delay = Math.min(delay * 2, 5000);
    };
  };
  open();

  return {
    send(m) {
      if (socket.readyState !== WebSocket.OPEN) return false;
      socket.send(JSON.stringify(stamp(m)));
      return true;
    },
    close() {
      closed = true;
      socket.close();
    },
  };
}
