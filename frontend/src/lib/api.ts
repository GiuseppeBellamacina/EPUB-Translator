const API_BASE = "/api";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...options?.headers },
    ...options,
  });
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(error.detail || res.statusText);
  }
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
  testProvider: (data: TestConnection) =>
    request<{ success: boolean; response?: string; error?: string }>(
      "/providers/test",
      { method: "POST", body: JSON.stringify(data) },
    ),

  // Books
  getBooks: () => request<Book[]>("/books"),
  getBook: (id: number) => request<BookDetail>("/books/" + id),
  uploadBook: async (file: File): Promise<Book> => {
    const form = new FormData();
    form.append("file", file);
    const res = await fetch(`${API_BASE}/upload`, {
      method: "POST",
      body: form,
    });
    if (!res.ok) throw new Error((await res.json()).detail);
    return res.json();
  },
  getPreview: (bookId: number, chapter: number) =>
    request<Preview>(`/books/${bookId}/preview?chapter_index=${chapter}`),
  downloadBook: (bookId: number) => `${API_BASE}/books/${bookId}/download`,

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
