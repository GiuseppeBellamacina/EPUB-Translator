import { useRef, useCallback, useState } from "react";
import { useStore, type TranslationProgress } from "../stores/appStore";

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

export function useTranslationWs() {
  const wsRef = useRef<WebSocket | null>(null);
  const [isConnected, setIsConnected] = useState(false);
  const [logs, setLogs] = useState<TranslationProgress[]>([]);
  const [liveText, setLiveText] = useState("");
  const setTranslationProgress = useStore((s) => s.setTranslationProgress);
  const updateBookStatus = useStore((s) => s.updateBookStatus);

  const startTranslation = useCallback(
    (options: TranslateOptions) => {
      const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
      const wsUrl = `${protocol}//${window.location.host}/ws/translate/${options.bookId}`;

      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;
      setLogs([]);
      setLiveText("");

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

      ws.onmessage = (event) => {
        const data: TranslationProgress = JSON.parse(event.data);
        setTranslationProgress(data);
        setLogs((prev) => [...prev, data]);

        const translated = data.data?.translated_text;
        if (
          (data.event === "chunk_translated" ||
            data.event === "chunk_accepted") &&
          typeof translated === "string"
        ) {
          setLiveText((prev) =>
            prev ? prev + "\n\n" + translated : translated,
          );
        } else if (data.event === "chapter_start") {
          setLiveText((prev) =>
            prev ? prev + "\n\n\u2014\u2014\u2014\n\n" : prev,
          );
        }

        if (data.event === "job_complete") {
          const failed = (data.data?.failed_units as unknown[] | undefined) ?? [];
          updateBookStatus(options.bookId, failed.length ? "failed" : "completed");
        } else if (data.event === "cancelled") {
          updateBookStatus(options.bookId, "paused");
        }
      };

      ws.onclose = () => {
        setIsConnected(false);
        setTranslationProgress(null);
        wsRef.current = null;
      };

      ws.onerror = () => {
        setIsConnected(false);
      };
    },
    [setTranslationProgress, updateBookStatus],
  );

  const stopTranslation = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ action: "stop" }));
    }
  }, []);

  const disconnect = useCallback(() => {
    wsRef.current?.close();
  }, []);

  return {
    startTranslation,
    stopTranslation,
    disconnect,
    isConnected,
    logs,
    liveText,
  };
}
