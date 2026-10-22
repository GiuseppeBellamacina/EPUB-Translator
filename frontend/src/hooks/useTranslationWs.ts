import { useCallback, useRef, useState } from "react";
import type { JobEvent } from "../lib/api";

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
}

const MAX_EVENTS = 500;

/** Runs a translation over the WebSocket; keeps its events, newest first. */
export function useTranslationWs(onFinished?: () => void) {
  const wsRef = useRef<WebSocket | null>(null);
  const [isConnected, setIsConnected] = useState(false);
  const [events, setEvents] = useState<JobEvent[]>([]);

  const startTranslation = useCallback(
    (options: TranslateOptions) => {
      const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
      const ws = new WebSocket(`${protocol}//${window.location.host}/ws/translate/${options.bookId}`);
      wsRef.current = ws;
      setEvents([]);

      ws.onopen = () => {
        setIsConnected(true);
        ws.send(
          JSON.stringify({
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
          }),
        );
      };
      ws.onmessage = (message) => {
        const event: JobEvent = JSON.parse(message.data);
        setEvents((prev) => [event, ...prev].slice(0, MAX_EVENTS));
      };
      ws.onclose = () => {
        setIsConnected(false);
        wsRef.current = null;
        onFinished?.();
      };
      ws.onerror = () => setIsConnected(false);
    },
    [onFinished],
  );

  const stopTranslation = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ action: "stop" }));
    }
  }, []);

  return { startTranslation, stopTranslation, isConnected, events, setEvents };
}
