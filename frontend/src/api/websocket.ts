export function connectWorldSocket(worldId: string, onMessage: (message: unknown) => void): { close: () => void } {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const base = import.meta.env.VITE_WS_BASE ?? (import.meta.env.DEV ? "ws://127.0.0.1:8010" : `${protocol}//${window.location.host}`);
  let closed = false;
  let ws: WebSocket | null = null;
  let reconnectTimer: number | null = null;
  let reconnectDelayMs = 500;

  const clearReconnect = () => {
    if (reconnectTimer !== null) {
      window.clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
  };

  const scheduleReconnect = () => {
    if (closed || reconnectTimer !== null) return;
    reconnectTimer = window.setTimeout(() => {
      reconnectTimer = null;
      connect();
    }, reconnectDelayMs);
    reconnectDelayMs = Math.min(reconnectDelayMs * 2, 10_000);
  };

  const connect = () => {
    if (closed) return;
    ws = new WebSocket(`${base}/ws/worlds/${worldId}`);
    ws.onopen = () => {
      reconnectDelayMs = 500;
    };
    ws.onmessage = (event) => {
      try {
        onMessage(JSON.parse(event.data));
      } catch {
        onMessage(event.data);
      }
    };
    ws.onerror = () => {
      ws?.close();
    };
    ws.onclose = () => {
      if (ws) {
        ws.onopen = null;
        ws.onmessage = null;
        ws.onerror = null;
        ws.onclose = null;
      }
      ws = null;
      scheduleReconnect();
    };
  };

  connect();

  return {
    close: () => {
      closed = true;
      clearReconnect();
      ws?.close();
      ws = null;
    },
  };
}
