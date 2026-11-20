// WebSocket with automatic reconnection.
import { syncClock } from "./ui.js";

export function connect(path, { onMessage, onStatus }) {
  let ws = null;
  let retry = 0;
  let queue = [];
  let closedByUs = false;

  function open() {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    ws = new WebSocket(`${proto}://${location.host}${path}`);
    ws.onopen = () => {
      retry = 0;
      onStatus?.(true);
      for (const m of queue) ws.send(m);
      queue = [];
    };
    ws.onmessage = (ev) => {
      let msg;
      try { msg = JSON.parse(ev.data); } catch { return; }
      if (msg.now) syncClock(msg.now);
      onMessage(msg);
    };
    ws.onclose = () => {
      onStatus?.(false);
      if (closedByUs) return;
      retry = Math.min(retry + 1, 6);
      setTimeout(open, 300 * retry);
    };
  }

  // Phones sleep: reconnect as soon as the page is visible again.
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible" && ws && ws.readyState > 1) open();
  });

  open();
  return {
    send(obj) {
      const text = JSON.stringify(obj);
      if (ws && ws.readyState === 1) ws.send(text);
      else queue.push(text);
    },
    reopen() { if (ws) ws.close(); },
    close() { closedByUs = true; ws?.close(); },
  };
}
