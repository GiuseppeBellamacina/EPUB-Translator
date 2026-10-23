import { FEATURES, type Features, type Provider, type RunConfig } from "./api";

export const LANGUAGES = [
  "english", "italian", "spanish", "french", "german", "portuguese", "dutch",
  "polish", "russian", "japanese", "chinese", "korean",
]; // fmt: off

// EPUB metadata often carries ISO codes ("en", "it-IT")
const ISO: Record<string, string> = {
  en: "english", it: "italian", es: "spanish", fr: "french", de: "german", pt: "portuguese",
  nl: "dutch", pl: "polish", ru: "russian", ja: "japanese", zh: "chinese", ko: "korean",
}; // fmt: off

export const languageName = (value: string | null | undefined, fallback: string) =>
  value ? (ISO[value.toLowerCase().split(/[-_]/)[0]] ?? value.toLowerCase()) : fallback;

/** The form state of a run's settings (translate page and queue). */
export interface RunSettings {
  providerId: number | null;
  model: string;
  enableReview: boolean;
  reviewModel: string;
  sourceLang: string;
  targetLang: string;
  style: string;
  features: Features;
}

/** Settings from a stored run config, else defaults (first provider, the book's languages). */
export function settingsFrom(
  config: RunConfig | null,
  providers: Provider[],
  languages: { source?: string | null; target?: string | null } = {},
): RunSettings {
  const known = config && providers.some((p) => p.id === config.provider_id) ? config : null;
  return {
    providerId: known?.provider_id ?? providers[0]?.id ?? null,
    model: known?.model ?? "",
    enableReview: known?.enable_review ?? true,
    reviewModel: known?.review_model ?? "",
    sourceLang: languageName(known?.source_language ?? languages.source, "english"),
    targetLang: languageName(known?.target_language ?? languages.target, "italian"),
    style: known?.style_instructions ?? "",
    features: Object.fromEntries(FEATURES.map(({ key }) => [key, known?.[key] ?? true])) as Features,
  };
}

/** The server's RunConfig (REST queue). */
export function toRunConfig(s: RunSettings): RunConfig {
  return {
    provider_id: s.providerId ?? 0,
    model: s.model || null,
    enable_review: s.enableReview,
    review_model: s.enableReview ? s.reviewModel || null : null,
    source_language: s.sourceLang || null, // "": each book's own
    target_language: s.targetLang,
    style_instructions: s.style,
    ...s.features,
  };
}
