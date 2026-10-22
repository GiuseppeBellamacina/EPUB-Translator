const API_BASE = "/api";

const STATUS_MESSAGES: Record<number, string> = {
  413: "File too large for the server",
  502: "Backend unreachable",
  504: "The server took too long to answer",
};

/** Readable error from any failed response: FastAPI JSON or a proxy's HTML page. */
async function errorFrom(res: Response): Promise<Error> {
  const body = await res.text();
  try {
    const detail = JSON.parse(body).detail;
    if (detail) return new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  } catch {
    // not JSON: e.g. nginx's HTML error pages
  }
  return new Error(`${STATUS_MESSAGES[res.status] ?? res.statusText ?? "Request failed"} (HTTP ${res.status})`);
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...options?.headers },
    ...options,
  });
  if (!res.ok) throw await errorFrom(res);
  return res.json();
}

export const api = {
  // Providers
  getProviders: () => request<Provider[]>("/providers"),
  createProvider: (data: ProviderCreate) =>
    request<Provider>("/providers", {
      method: "POST",
      body: JSON.stringify(data),
    }),
  deleteProvider: (id: number) =>
    request("/providers/" + id, { method: "DELETE" }),
  updateProvider: (id: number, data: Partial<ProviderCreate>) =>
    request<Provider>("/providers/" + id, {
      method: "PUT",
      body: JSON.stringify(data),
    }),
  /** Models of a provider that is not saved yet; fails on a bad key/URL. */
  listModelsFor: (data: { provider_type: string; api_key?: string; base_url?: string }) =>
    request<ModelOption[]>("/providers/models", {
      method: "POST",
      body: JSON.stringify(data),
    }),
  testProvider: (data: TestConnection) =>
    request<{ success: boolean; response?: string; error?: string }>(
      "/providers/test",
      { method: "POST", body: JSON.stringify(data) },
    ),

  // Books
  getBooks: () => request<Book[]>("/books"),
  getBook: (id: number) => request<BookDetail>("/books/" + id),
  deleteBook: (id: number) => request<{ status: string }>(`/books/${id}`, { method: "DELETE" }),
  uploadBook: async (file: File): Promise<Book> => {
    const form = new FormData();
    form.append("file", file);
    const res = await fetch(`${API_BASE}/upload`, {
      method: "POST",
      body: form,
    });
    if (!res.ok) throw await errorFrom(res);
    return res.json();
  },
  getPreview: (bookId: number, chapter: number) =>
    request<Preview>(`/books/${bookId}/preview?chapter_index=${chapter}`),
  downloadBook: (bookId: number) => `${API_BASE}/books/${bookId}/download`,
  getEstimate: (
    bookId: number,
    options: { refreshPrices?: boolean; providerId?: number; model?: string } = {},
  ) => {
    const query = new URLSearchParams();
    if (options.refreshPrices) query.set("refresh_prices", "true");
    if (options.providerId !== undefined && options.model) {
      query.set("provider_id", String(options.providerId));
      query.set("model", options.model);
    }
    const qs = query.toString();
    return request<CostEstimate>(`/books/${bookId}/estimate${qs ? `?${qs}` : ""}`);
  },
  getProviderModels: (providerId: number, refresh = false) =>
    request<ModelOption[]>(
      `/providers/${providerId}/models${refresh ? "?refresh=true" : ""}`,
    ),
  getProgress: (bookId: number) => request<BookProgress>(`/books/${bookId}/progress`),
  /** Pause a running job that this page is not connected to (e.g. after navigating away). */
  stopTranslation: (bookId: number) =>
    request<{ status: string }>(`/translate/${bookId}/stop`, { method: "POST" }),

  // Glossary
  getGlossary: (bookId: number) =>
    request<GlossaryEntry[]>(`/glossary/${bookId}`),
  updateGlossary: (bookId: number, entries: GlossaryEntryCreate[]) =>
    request(`/glossary/${bookId}`, {
      method: "PUT",
      body: JSON.stringify({ entries }),
    }),
  addGlossaryEntry: (bookId: number, entry: GlossaryEntryCreate) =>
    request<GlossaryEntry>(`/glossary/${bookId}/entry`, {
      method: "POST",
      body: JSON.stringify(entry),
    }),

  // Queue: books translated one after another on the server
  getQueue: () => request<QueueState>("/queue"),
  addToQueue: (bookIds: number[], config: RunConfig, keepGlossary: boolean) =>
    request<{ queued: number }>("/queue", {
      method: "POST",
      body: JSON.stringify({ ...config, book_ids: bookIds, keep_glossary: keepGlossary }),
    }),
  startQueue: () => request("/queue/start", { method: "POST" }),
  stopQueue: () => request("/queue/stop", { method: "POST" }),
  removeFromQueue: (itemId: number) => request(`/queue/${itemId}`, { method: "DELETE" }),
  clearFinished: () => request("/queue", { method: "DELETE" }),
};

// Types
export interface Provider {
  id: number;
  name: string;
  provider_type: string;
  base_url: string | null;
  default_model: string | null;
  params: Record<string, unknown> | null;
  is_active: boolean;
  /** "config" = managed by config.yaml, "user" = created in the UI */
  source: "config" | "user";
}

export interface ProviderCreate {
  name: string;
  provider_type: string;
  api_key?: string;
  base_url?: string;
  default_model?: string;
  params?: Record<string, unknown>;
}

export interface TestConnection {
  provider_type: string;
  api_key?: string;
  base_url?: string;
  model: string;
  temperature?: number;
}

export interface Book {
  id: number;
  filename: string;
  source_language: string;
  target_language: string;
  status: string;
  total_chapters: number;
  translated_chapters: number;
  created_at: string;
}

export interface BookDetail extends Book {
  chapters: Chapter[];
}

export interface Chapter {
  id: number;
  item_id: string;
  title: string | null;
  order_index: number;
  status: string;
  has_original: boolean;
  has_translation: boolean;
}

export interface Preview {
  chapter_index: number;
  total_chapters: number;
  original_text: string;
  translated_text: string;
  original_html: string;
}

export interface GlossaryEntry {
  id: number;
  source_term: string;
  target_term: string;
  context: string | null;
  do_not_translate: boolean;
  user_edited: boolean;
}

export interface GlossaryEntryCreate {
  source_term: string;
  target_term: string;
  context?: string;
  do_not_translate?: boolean;
}

export interface ModelUsage {
  input_tokens: number;
  output_tokens: number;
  cost: number;
}

export interface ModelEstimate {
  provider: "openai" | "anthropic";
  model: string;
  input_per_million: number;
  output_per_million: number;
  reasoning: boolean;
  with_review: ModelUsage;
  without_review: ModelUsage;
}

export interface CostEstimate {
  profile: {
    units: number;
    chunks: number;
    source_tokens: number;
    context_tokens: number;
    analysis_tokens: number;
  };
  target_language: string;
  prices_fetched_at: number;
  prices_source: "live" | "cache" | "stale-cache" | "bundled";
  models: ModelEstimate[];
}

export interface ModelOption {
  id: string;
  label: string;
  input_per_million: number | null;
  output_per_million: number | null;
  reasoning: boolean | null;
}

/** A message sent by the translation WebSocket (also kept server-side for /progress). */
export interface JobEvent {
  event: string;
  chapter_index?: number;
  total_chapters?: number;
  chunk_index?: number;
  total_chunks?: number;
  message?: string;
  data?: Record<string, unknown>;
  /** server time, seconds since epoch */
  ts?: number;
}

export interface BookProgress {
  status: string;
  running: boolean;
  total_units: number;
  completed_units: number;
  failed_units: number[];
  in_flight: number[];
  started_at: string | null;
  eta_seconds: number | null;
  /** newest first */
  recent_events: JobEvent[];
  /** settings of the last run (null for runs before they were stored) */
  config: RunConfig | null;
  /** waiting in the queue: "pending", or "paused" after a stop/restart */
  queue_status: "pending" | "paused" | null;
}

/** A run's settings, as the server stores them (snake_case). */
export interface RunConfig {
  provider_id: number;
  model?: string | null;
  review_model?: string | null;
  enable_review: boolean;
  source_language?: string | null;
  target_language?: string | null;
  style_instructions: string;
}

export interface QueueItem {
  id: number;
  book_id: number;
  filename: string;
  status: "pending" | "running" | "paused" | "done" | "failed";
  error: string | null;
  keep_glossary: boolean;
  config: RunConfig;
  completed_units: number;
  total_units: number;
}

export interface QueueState {
  running: boolean;
  items: QueueItem[];
}
