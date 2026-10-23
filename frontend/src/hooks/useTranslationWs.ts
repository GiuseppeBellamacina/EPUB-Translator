import { useCallback, useRef, useState } from "react";
import type { Features, JobEvent } from "../lib/api";

interface TranslateOptions {
  bookId: number;
  providerId: number;
  sourceLanguage?: string;
  targetLanguage?: string;
  model?: string;
  temperature?: number;
  styleInstructions?: string;
  enableReview?: boolean;
  /** Reviewer model (same provider); defaults to the translation model. */
  reviewModel?: string;
  /** Discard saved progress instead of resuming from it. */
  restart?: boolean;
  features?: Features;
}

const MAX_EVENTS = 500;

/**
 * Starts or follows a translation over the WebSocket; keeps its events, newest first.
 * The job runs on the server: closing the socket only stops following it.
 */
export function useTranslationWs(onFinished?: () => void) {
  const wsRef = useRef<WebSocket | null>(null);
  const [isConnected, setIsConnected] = useState(false);
  const [events, setEvents] = useState<JobEvent[]>([]);
  // the last message received live (events also holds the log loaded on page open)
  const [lastMessage, setLastMessage] = useState<{ bookId: number; event: JobEvent } | null>(null);

  const connect = useCallback(
    (bookId: number, first: object) => {
      wsRef.current?.close();
      const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
      const ws = new WebSocket(`${protocol}//${window.location.host}/ws/translate/${bookId}`);
      wsRef.current = ws;

      ws.onopen = () => {
        setIsConnected(true);
        ws.send(JSON.stringify(first));
      };
      ws.onmessage = (message) => {
        const event: JobEvent = JSON.parse(message.data);
        setEvents((prev) => [event, ...prev].slice(0, MAX_EVENTS));
        setLastMessage({ bookId, event });
      };
      ws.onclose = () => {
        if (wsRef.current !== ws) return; // replaced or the page left
        setIsConnected(false);
        wsRef.current = null;
        onFinished?.();
      };
      ws.onerror = () => setIsConnected(false);
    },
    [onFinished],
  );

  const startTranslation = useCallback(
    (options: TranslateOptions) => {
      setEvents([]);
      connect(options.bookId, {
        action: "start",
        provider_id: options.providerId,
        source_language: options.sourceLanguage || "english",
        target_language: options.targetLanguage || "italian",
        model: options.model,
        temperature: options.temperature ?? 0.0,
        style_instructions: options.styleInstructions || "",
        restart: options.restart ?? false,
        enable_review: options.enableReview ?? true,
        review_model: options.reviewModel || undefined,
        ...options.features,
      });
    },
    [connect],
  );

  /** Follow a job that is already running or queued (e.g. after reopening the page). */
  const watchTranslation = useCallback((bookId: number) => connect(bookId, { action: "watch" }), [connect]);

  const stopTranslation = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ action: "stop" }));
    }
  }, []);

  /** Stop following (the job goes on); for page unmount. */
  const disconnect = useCallback(() => {
    const ws = wsRef.current;
    wsRef.current = null;
    ws?.close();
  }, []);

  return {
    startTranslation,
    watchTranslation,
    stopTranslation,
    disconnect,
    isConnected,
    events,
    setEvents,
    lastMessage,
  };
}
