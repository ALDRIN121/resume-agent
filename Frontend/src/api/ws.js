const API_BASE = import.meta.env.VITE_API_BASE || "";

const wsBase = () => {
  if (API_BASE.startsWith("http")) {
    const url = new URL(API_BASE);
    url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
    return url.toString().replace(/\/$/, "");
  }
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}${API_BASE}`;
};

// One-shot subscription to a resume-parse job. The backend pushes a short
// sequence of ResumeParseEvent frames and then closes the socket, so we don't
// reconnect here (unlike subscribeRun).
export function subscribeResumeParse(jobId, onEvent, onClose) {
  const socket = new WebSocket(`${wsBase()}/ws/resume-parse/${jobId}`);
  socket.onmessage = (message) => {
    try {
      onEvent(JSON.parse(message.data));
    } catch {
      // ignore malformed frames
    }
  };
  socket.onclose = () => onClose?.();
  return () => socket.close();
}

export function subscribeRun(threadId, onEvent, onStatus) {
  let socket = null;
  let closed = false;
  let retryTimer = null;
  let attempts = 0;

  const connect = () => {
    socket = new WebSocket(`${wsBase()}/ws/runs/${threadId}`);
    onStatus?.("connecting");
    socket.onopen = () => {
      attempts = 0;
      onStatus?.("connected");
    };
    socket.onmessage = (message) => {
      let payload;
      try {
        payload = JSON.parse(message.data);
      } catch {
        return; // ignore malformed frames instead of throwing in the handler
      }
      onEvent(payload);
    };
    socket.onclose = () => {
      if (closed) return;
      onStatus?.("reconnecting");
      const delay = Math.min(4000, 500 * 2 ** attempts++);
      retryTimer = window.setTimeout(connect, delay);
    };
    socket.onerror = () => {
      onStatus?.("error");
      socket?.close();
    };
  };

  connect();

  return () => {
    closed = true;
    if (retryTimer) window.clearTimeout(retryTimer);
    socket?.close();
  };
}
