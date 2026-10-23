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
  getSettings: () => request<AppSettings>("/settings"),
  updateSettings: (data: { max_parallel_books: number }) =>
    request<AppSettings>("/settings", { method: "PUT", body: JSON.stringify(data) }),
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
  getBookmarks: (bookId: number) => request<Bookmark[]>(`/books/${bookId}/bookmarks`),
  /** Pause a running job that this page is not connected to (e.g. after navigating away). */
  stopTranslation: (bookId: number) =>
    request<{ status: string }>(`/translate/${bookId}/stop`, { method: "POST" }),

  // Glossary
  getCompendium: (bookId: number) => request<CompendiumItem[]>(`/compendium/${bookId}`),
  updateCompendium: (bookId: number, entries: CompendiumItem[]) =>
    request(`/compendium/${bookId}`, { method: "PUT", body: JSON.stringify({ entries }) }),
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
  // single entries: also while translating (the running job uses them at once)
  editGlossaryEntry: (bookId: number, id: number, entry: GlossaryEntryCreate) =>
    request<GlossaryEntry>(`/glossary/${bookId}/entry/${id}`, { method: "PUT", body: JSON.stringify(entry) }),
  deleteGlossaryEntry: (bookId: number, id: number) =>
    request(`/glossary/${bookId}/entry/${id}`, { method: "DELETE" }),
  saveCompendiumEntry: (bookId: number, entry: CompendiumItem) =>
    // bookmarked: translated passages naming it, rechecked by the doubt review (gender changed)
    request<CompendiumItem & { bookmarked?: number }>(`/compendium/${bookId}/entry${entry.id ? `/${entry.id}` : ""}`, {
      method: entry.id ? "PUT" : "POST",
      body: JSON.stringify(entry),
    }),
  deleteCompendiumEntry: (bookId: number, id: number) =>
    request(`/compendium/${bookId}/entry/${id}`, { method: "DELETE" }),

  // Queue: books translated one after another on the server
  getQueue: () => request<QueueState>("/queue"),
  addToQueue: (bookIds: number[], config: RunConfig, keep: { glossary: boolean; compendium: boolean }) =>
    request<{ queued: number }>("/queue", {
      method: "POST",
      body: JSON.stringify({
        ...config,
        book_ids: bookIds,
        keep_glossary: keep.glossary,
        keep_compendium: keep.compendium,
      }),
    }),
  /** New order of a queue's waiting books (running and finished ones stay in place). */
  reorderBatch: (batchId: number, itemIds: number[]) =>
    request(`/queue/${batchId}/order`, { method: "PUT", body: JSON.stringify({ item_ids: itemIds }) }),
  /** Add books to the end of an existing queue (its settings, carry-over continues). */
  addToBatch: (batchId: number, bookIds: number[]) =>
    request<{ queued: number }>(`/queue/${batchId}/books`, {
      method: "POST",
      body: JSON.stringify({ book_ids: bookIds }),
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

/** A passage translated with a doubt, revisited by the end-of-book doubt review. */
export interface Bookmark {
  id: number;
  unit: number;
  block: number;
  quote: string;
  reason: string;
  source: string | null;
  translation: string | null;
  status: "open" | "fixed" | "kept";
  resolution: string | null;
  note: string | null;
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
  /** the queue the book belongs to, when it has other books too */
  queue: { batch_id: number; items: QueueItem[] } | null;
}

/** A run's feature switches (RunConfig), all on by default. */
export const FEATURES = [
  { key: "analysis", label: "Opening analysis", hint: "Summary, first terms and characters" },
  { key: "use_glossary", label: "Use the glossary", hint: "Its terms in every prompt" },
  { key: "learn_glossary", label: "Learn new terms", hint: "Names and terms the model finds" },
  { key: "enforce_glossary", label: "Enforce the glossary", hint: "Replace terms left untranslated" },
  { key: "use_compendium", label: "Use the compendium", hint: "Genders and notes in every prompt" },
  { key: "learn_compendium", label: "Learn characters", hint: "New characters, genders, aliases" },
  { key: "doubt_review", label: "Doubt review", hint: "Revisit the guesses at the end of the book" },
] as const;
export type Features = Record<(typeof FEATURES)[number]["key"], boolean>;

/** A run's settings, as the server stores them (snake_case). */
export interface RunConfig extends Partial<Features> {
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
  keep_compendium: boolean;
  /** the queue the book was added to (books of one queue carry glossary/compendium) */
  batch_id: number | null;
  config: RunConfig;
  completed_units: number;
  total_units: number;
}

export interface QueueState {
  running: boolean;
  items: QueueItem[];
}

export const COMPENDIUM_KINDS = ["character", "place", "organization", "item", "other"] as const;
export const GENDERS = ["male", "female", "unknown", "n/a"] as const;

/** A character, place or other element of a book, as the translation knows it. */
export interface CompendiumItem {
  id?: number;
  name: string;
  kind: (typeof COMPENDIUM_KINDS)[number];
  gender: (typeof GENDERS)[number];
  aliases: string[];
  notes: string;
  /** set when the translation corrected the gender: the words of the text that prove it */
  evidence?: string;
  /** edited by the user: the translation never changes it again */
  user_edited: boolean;
}

/** Queue item status → the book status pill it shows as. */
export const QUEUE_PILL: Record<QueueItem["status"], string> = {
  pending: "queued",
  running: "translating",
  paused: "paused",
  done: "completed",
  failed: "failed",
};

/** Translation defaults (a provider's params override them). */
export interface AppSettings {
  /** books translated at the same time */
  max_parallel_books: number;
  defaults: {
    requests_per_second: number;
    max_concurrency: number;
    max_retries: number;
    chunk_tokens: number;
  };
}

/** Provider params the UI edits; other keys in Provider.params are kept as they are. */
export const PROVIDER_PARAMS = [
  { key: "requests_per_second", label: "Requests per second", hint: "0 = no limit", step: "0.05" },
  { key: "max_concurrency", label: "Chapters in parallel", hint: "per book", step: "1" },
  { key: "max_retries", label: "Retries on errors", hint: "429 / 5xx, with backoff", step: "1" },
  { key: "chunk_tokens", label: "Text per call (tokens)", hint: "300–3000; more = fewer calls", step: "100" },
] as const;
export const OUTPUT_METHODS = ["", "function_calling", "json_mode", "json_schema"] as const;
