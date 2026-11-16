"use client";

import { useEffect, useRef, useState } from "react";

import { connectJobEvents, type JobStreamStatus } from "@/lib/job-events";
import type { JobSnapshot } from "@/lib/api";

export type EventStreamState = JobStreamStatus;

const RETRY_DELAY_MS = 3000;

export function useJobEvents(enabled = true) {
  const [snapshot, setSnapshot] = useState<JobSnapshot | null>(null);
  const [status, setStatus] = useState<EventStreamState>(enabled ? "connecting" : "idle");
  const [error, setError] = useState<string | null>(null);
  const retryTimerRef = useRef<number | null>(null);
  // Lưu connection hiện tại để đóng khi unmount/retry.
  const connectionRef = useRef<ReturnType<typeof connectJobEvents> | null>(null);
  // Cờ chống gọi onError nhiều lần khi tự đóng do cleanup.
  const closingRef = useRef(false);

  useEffect(() => {
    if (!enabled) {
      return;
    }

    const clearRetry = () => {
      if (retryTimerRef.current !== null) {
        window.clearTimeout(retryTimerRef.current);
        retryTimerRef.current = null;
      }
    };

    const closeCurrent = () => {
      closingRef.current = true;
      try {
        connectionRef.current?.close();
      } catch {
        // ignore
      }
      connectionRef.current = null;
    };

    const openConnection = () => {
      closingRef.current = false;
      clearRetry();

      const connection = connectJobEvents({
        onSnapshot(nextSnapshot) {
          setSnapshot(nextSnapshot);
          setError(null);
        },
        onStatusChange(nextStatus) {
          setStatus(nextStatus);
        },
        onError(nextError) {
          if (closingRef.current) {
            return;
          }
          const message =
            nextError instanceof Error
              ? nextError.message
              : "Không thể kết nối realtime";
          setError(message);
          setStatus("closed");
          // Lên lịch reconnect, chỉ tạo duy nhất một connection tại một thời điểm.
          clearRetry();
          retryTimerRef.current = window.setTimeout(() => {
            openConnection();
          }, RETRY_DELAY_MS);
        },
      });
      connectionRef.current = connection;
    };

    openConnection();

    return () => {
      clearRetry();
      closeCurrent();
    };
  }, [enabled]);

  return {
    snapshot,
    status,
    error,
    setSnapshot,
  };
}
