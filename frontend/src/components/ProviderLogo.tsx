import { FlaskConical, Server, Sparkles } from "lucide-react";
import anthropic from "@lobehub/icons-static-svg/icons/anthropic.svg?raw";
import cohere from "@lobehub/icons-static-svg/icons/cohere.svg?raw";
import deepseek from "@lobehub/icons-static-svg/icons/deepseek.svg?raw";
import google from "@lobehub/icons-static-svg/icons/gemini.svg?raw";
import meta from "@lobehub/icons-static-svg/icons/meta.svg?raw";
import microsoft from "@lobehub/icons-static-svg/icons/microsoft.svg?raw";
import mistral from "@lobehub/icons-static-svg/icons/mistral.svg?raw";
import moonshot from "@lobehub/icons-static-svg/icons/moonshot.svg?raw";
import nvidia from "@lobehub/icons-static-svg/icons/nvidia.svg?raw";
import ollama from "@lobehub/icons-static-svg/icons/ollama.svg?raw";
import openai from "@lobehub/icons-static-svg/icons/openai.svg?raw";
import openrouter from "@lobehub/icons-static-svg/icons/openrouter.svg?raw";
import perplexity from "@lobehub/icons-static-svg/icons/perplexity.svg?raw";
import qwen from "@lobehub/icons-static-svg/icons/qwen.svg?raw";
import xai from "@lobehub/icons-static-svg/icons/xai.svg?raw";
import zhipu from "@lobehub/icons-static-svg/icons/zhipu.svg?raw";
import { cn } from "../lib/utils";

// Monochrome brand marks (fill="currentColor"), from @lobehub/icons-static-svg (MIT)
const LOGOS: Record<string, { svg: string; name: string }> = {
  openai: { svg: openai, name: "OpenAI" },
  anthropic: { svg: anthropic, name: "Anthropic" },
  openrouter: { svg: openrouter, name: "OpenRouter" },
  ollama: { svg: ollama, name: "Ollama" },
  google: { svg: google, name: "Google" },
  meta: { svg: meta, name: "Meta" },
  mistral: { svg: mistral, name: "Mistral" },
  deepseek: { svg: deepseek, name: "DeepSeek" },
  qwen: { svg: qwen, name: "Qwen" },
  nvidia: { svg: nvidia, name: "NVIDIA" },
  xai: { svg: xai, name: "xAI" },
  cohere: { svg: cohere, name: "Cohere" },
  microsoft: { svg: microsoft, name: "Microsoft" },
  moonshot: { svg: moonshot, name: "Moonshot" },
  zhipu: { svg: zhipu, name: "Zhipu" },
  perplexity: { svg: perplexity, name: "Perplexity" },
};

// OpenRouter-style vendor prefixes (`vendor/model`)
const PREFIXES: Record<string, string> = {
  "meta-llama": "meta",
  mistralai: "mistral",
  "x-ai": "xai",
  moonshotai: "moonshot",
  "z-ai": "zhipu",
  thudm: "zhipu",
  qwen: "qwen",
};

// Bare model ids
const MODEL_PATTERNS: [RegExp, string][] = [
  [/^(gpt|o\d|chatgpt|text-)/, "openai"],
  [/^claude/, "anthropic"],
  [/^(gemini|gemma)/, "google"],
  [/^llama/, "meta"],
  [/^(mistral|mixtral|codestral|ministral)/, "mistral"],
  [/^qwen/, "qwen"],
  [/^deepseek/, "deepseek"],
  [/^(grok)/, "xai"],
  [/^(nemotron)/, "nvidia"],
  [/^(phi)/, "microsoft"],
];

/** Which brand mark identifies a provider and/or one of its models. */
function vendorOf(
  providerType?: string | null,
  baseUrl?: string | null,
  modelId?: string | null,
): string | null {
  if (modelId?.includes("/")) {
    const prefix = modelId.split("/")[0].toLowerCase();
    const vendor = PREFIXES[prefix] ?? prefix;
    if (LOGOS[vendor]) return vendor;
  }
  if (modelId) {
    const id = modelId.toLowerCase();
    const hit = MODEL_PATTERNS.find(([re]) => re.test(id));
    if (hit) return hit[1];
  }
  if (providerType === "custom" && baseUrl?.includes("openrouter")) return "openrouter";
  if (providerType && LOGOS[providerType]) return providerType;
  return null;
}

export function ProviderLogo({
  providerType,
  baseUrl,
  modelId,
  className,
  label = true,
}: {
  providerType?: string | null;
  baseUrl?: string | null;
  modelId?: string | null;
  className?: string;
  /** false when a visible name is right next to the logo */
  label?: boolean;
}) {
  const vendor = vendorOf(providerType, baseUrl, modelId);
  const size = cn("inline-flex h-5 w-5 shrink-0 items-center justify-center text-ink", className);

  if (!vendor) {
    const Icon =
      providerType === "fake" ? FlaskConical : providerType === "custom" ? Server : Sparkles;
    return <Icon className={size} aria-hidden="true" strokeWidth={1.8} />;
  }
  const { svg, name } = LOGOS[vendor];
  return (
    <span
      className={cn(size, "[&>svg]:h-full [&>svg]:w-full")}
      role={label ? "img" : undefined}
      aria-label={label ? name : undefined}
      aria-hidden={label ? undefined : true}
      // Trusted, bundled SVG from the icon package (no user input)
      dangerouslySetInnerHTML={{ __html: svg }}
    />
  );
}
