import { create } from "zustand";
import type { Book, BookDetail, Provider } from "../lib/api";

interface AppState {
  // Books
  books: Book[];
  currentBook: BookDetail | null;
  setBooks: (books: Book[]) => void;
  setCurrentBook: (book: BookDetail | null) => void;
  updateBookStatus: (bookId: number, status: string) => void;

  // Providers
  providers: Provider[];
  setProviders: (providers: Provider[]) => void;
  selectedProviderId: number | null;
  setSelectedProviderId: (id: number | null) => void;

  // Translation progress
  translationProgress: TranslationProgress | null;
  setTranslationProgress: (progress: TranslationProgress | null) => void;

  // UI
  sidebarOpen: boolean;
  toggleSidebar: () => void;
}

export interface TranslationProgress {
  event: string;
  chapter_index: number;
  total_chapters: number;
  chunk_index: number;
  total_chunks: number;
  message: string;
  data?: Record<string, unknown>;
}

export const useStore = create<AppState>((set) => ({
  books: [],
  currentBook: null,
  setBooks: (books) => set({ books }),
  setCurrentBook: (book) => set({ currentBook: book }),
  updateBookStatus: (bookId, status) =>
    set((state) => ({
      books: state.books.map((b) => (b.id === bookId ? { ...b, status } : b)),
    })),

  providers: [],
  setProviders: (providers) => set({ providers }),
  selectedProviderId: null,
  setSelectedProviderId: (id) => set({ selectedProviderId: id }),

  translationProgress: null,
  setTranslationProgress: (progress) => set({ translationProgress: progress }),

  sidebarOpen: true,
  toggleSidebar: () => set((state) => ({ sidebarOpen: !state.sidebarOpen })),
}));
