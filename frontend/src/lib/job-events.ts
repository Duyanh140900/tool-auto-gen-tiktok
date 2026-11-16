import { buildApiBase, type JobSnapshot } from "@/lib/api";

export type JobStreamStatus = "idle" | "connecting" | "open" | "closed";

export type JobEventHandlers = {
  onSnapshot: (snapshot: JobSnapshot) => void;
  onStatusChange?: (status: JobStreamStatus) => void;
  onError?: (error: Error | Event) => void;
};

export type JobEventConnection = {
  close: () => void;
};

/**
 * Xây URL websocket.
 *
 * WebSocket upgrade không phải lúc nào cũng được Next.js rewrite proxy ổn định,
 * vì vậy ưu tiên NEXT_PUBLIC_WS_BASE_URL để kết nối trực tiếp FastAPI.
 */
export function buildJobWebSocketUrl(): string {
  const explicitWsBase = process.env.NEXT_PUBLIC_WS_BASE_URL?.trim();
  if (explicitWsBase) {
    return (
      explicitWsBase.replace(/^http/i, "ws").replace(/\/$/, "") +
      "/api/job/ws"
    );
  }

  const apiBase = buildApiBase();
  if (apiBase) {
    return (
      apiBase.replace(/^http/i, "ws").replace(/\/$/, "") + "/api/job/ws"
    );
  }

  if (
    typeof window !== "undefined" &&
    ["localhost", "127.0.0.1"].includes(window.location.hostname)
  ) {
    const protocol = window.location.protocol === "https:" ? "wss" : "ws";
    return `${protocol}://${window.location.hostname}:8000/api/job/ws`;
  }

  const protocol =
    typeof window !== "undefined" && window.location.protocol === "https:"
      ? "wss"
      : "ws";
  return `${protocol}://${window.location.host}/api/job/ws`;
}

function normalizeSnapshot(payload: unknown): JobSnapshot | null {
  if (!payload || typeof payload !== "object") {
    return null;
  }
  const obj = payload as Record<string, unknown>;
  if ("type" in obj && obj.type === "ping") {
    return null;
  }
  if ("job" in obj && obj.job && typeof obj.job === "object") {
    return obj.job as JobSnapshot;
  }
  if ("job_id" in obj && "items" in obj) {
    return obj as unknown as JobSnapshot;
  }
  return null;
}

export function connectJobEvents(handlers: JobEventHandlers): JobEventConnection {
  if (typeof window === "undefined") {
    return { close: () => undefined };
  }
  const url = buildJobWebSocketUrl();
  let socket: WebSocket | null = null;
  let closedByUs = false;
  let errorReported = false;

  const reportErrorOnce = (error: Error | Event) => {
    if (closedByUs || errorReported) {
      return;
    }
    errorReported = true;
    handlers.onError?.(error);
  };

  console.info(`[job-ws] connecting: ${url}`);
  handlers.onStatusChange?.("connecting");

  try {
    socket = new WebSocket(url);
  } catch (error) {
    handlers.onStatusChange?.("closed");
    reportErrorOnce(
      error instanceof Error ? error : new Error("Không thể mở websocket"),
    );
    return {
      close: () => undefined,
    };
  }

  socket.addEventListener("open", () => {
    errorReported = false;
    console.info(`[job-ws] open: ${url}`);
    handlers.onStatusChange?.("open");
  });

  socket.addEventListener("message", (event: MessageEvent) => {
    try {
      const parsed = JSON.parse(event.data as string) as unknown;
      const snapshot = normalizeSnapshot(parsed);
      if (snapshot) {
        handlers.onSnapshot(snapshot);
      }
    } catch (error) {
      handlers.onError?.(
        error instanceof Error ? error : new Error("Invalid websocket payload"),
      );
    }
  });

  socket.addEventListener("error", (event) => {
    console.error(`[job-ws] error: ${url}`, event);
    handlers.onStatusChange?.("closed");
    reportErrorOnce(event);
  });

  const handleClose = (event: CloseEvent) => {
    console.warn(
      `[job-ws] closed: code=${event.code}, reason=${
        event.reason || "none"
      }, clean=${event.wasClean}`,
    );
    handlers.onStatusChange?.("closed");
    reportErrorOnce(
      new Error(
        `WebSocket đã đóng (code ${event.code}${
          event.reason ? `: ${event.reason}` : ""
        })`,
      ),
    );
  };
  socket.addEventListener("close", handleClose);

  return {
    close: () => {
      if (socket && socket.readyState <= WebSocket.OPEN) {
        closedByUs = true;
        socket.close();
      }
      handlers.onStatusChange?.("closed");
    },
  };
}
