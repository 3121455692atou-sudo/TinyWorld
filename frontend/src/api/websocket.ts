export function connectWorldSocket(worldId: string, onMessage: (message: unknown) => void): WebSocket {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const base = import.meta.env.VITE_WS_BASE ?? (import.meta.env.DEV ? "ws://127.0.0.1:8010" : `${protocol}//${window.location.host}`);
  const ws = new WebSocket(`${base}/ws/worlds/${worldId}`);
  ws.onmessage = (event) => {
    try {
      onMessage(JSON.parse(event.data));
    } catch {
      onMessage(event.data);
    }
  };
  return ws;
}
