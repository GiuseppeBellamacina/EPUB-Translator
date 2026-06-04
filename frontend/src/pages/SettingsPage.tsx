import { useEffect, useState } from "react";
import {
  Plus,
  Trash2,
  CheckCircle,
  XCircle,
  Loader2,
  Cpu,
  ExternalLink,
} from "lucide-react";
import { api, type Provider, type ProviderCreate } from "../lib/api";
import { cn } from "../lib/utils";

interface ProviderType {
  value: string;
  label: string;
  description: string;
  defaultModel: string;
  needsApiKey: boolean;
  needsBaseUrl: boolean;
  apiKeyUrl?: string;
  defaultBaseUrl?: string;
}

const PROVIDER_TYPES: ProviderType[] = [
  {
    value: "openai",
    label: "OpenAI",
    description: "GPT-4o, GPT-4o-mini and other OpenAI models",
    defaultModel: "gpt-4o-mini",
    needsApiKey: true,
    needsBaseUrl: false,
    apiKeyUrl: "https://platform.openai.com/api-keys",
  },
  {
    value: "anthropic",
    label: "Anthropic",
    description: "Claude 3.5 Sonnet, Haiku and Opus models",
    defaultModel: "claude-3-5-sonnet-latest",
    needsApiKey: true,
    needsBaseUrl: false,
    apiKeyUrl: "https://console.anthropic.com/settings/keys",
  },
  {
    value: "ollama",
    label: "Ollama",
    description: "Run models locally, no API key required",
    defaultModel: "llama3.1",
    needsApiKey: false,
    needsBaseUrl: true,
    defaultBaseUrl: "http://localhost:11434",
  },
  {
    value: "custom",
    label: "Custom",
    description: "Any OpenAI-compatible endpoint",
    defaultModel: "",
    needsApiKey: true,
    needsBaseUrl: true,
    defaultBaseUrl: "https://api.example.com/v1",
  },
  {
    value: "fake",
    label: "Fake (test)",
    description: "Offline BAU/MIAO transformer for testing the pipeline",
    defaultModel: "fake-meow",
    needsApiKey: false,
    needsBaseUrl: false,
  },
];

export function SettingsPage() {
  const [providers, setProviders] = useState<Provider[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<{
    success: boolean;
    message: string;
  } | null>(null);

  // Form state
  const [form, setForm] = useState<ProviderCreate>({
    name: "",
    provider_type: "openai",
    api_key: "",
    base_url: "",
    default_model: "",
  });

  const selectedType =
    PROVIDER_TYPES.find((t) => t.value === form.provider_type) ||
    PROVIDER_TYPES[0];

  const selectProviderType = (type: ProviderType) => {
    setTestResult(null);
    setForm((prev) => ({
      ...prev,
      provider_type: type.value,
      name: prev.name || type.label,
      default_model: type.defaultModel,
      base_url: type.defaultBaseUrl || "",
    }));
  };

  useEffect(() => {
    api
      .getProviders()
      .then(setProviders)
      .finally(() => setLoading(false));
  }, []);

  const resetForm = () => {
    setForm({
      name: "",
      provider_type: "openai",
      api_key: "",
      base_url: "",
      default_model: "",
    });
    setTestResult(null);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      const provider = await api.createProvider(form);
      setProviders([...providers, provider]);
      setShowForm(false);
      resetForm();
    } catch (err) {
      alert(err instanceof Error ? err.message : "Failed to create provider");
    }
  };

  const handleDelete = async (id: number) => {
    await api.deleteProvider(id);
    setProviders(providers.filter((p) => p.id !== id));
  };

  const handleTest = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      const result = await api.testProvider({
        provider_type: form.provider_type,
        api_key: form.api_key || undefined,
        base_url: form.base_url || undefined,
        model: form.default_model || selectedType.defaultModel || "gpt-4o-mini",
      });
      setTestResult({
        success: result.success,
        message: result.success
          ? "Connection successful!"
          : result.error || "Connection failed",
      });
    } catch (err) {
      setTestResult({
        success: false,
        message: err instanceof Error ? err.message : "Test failed",
      });
    } finally {
      setTesting(false);
    }
  };

  if (loading) {
    return (
      <div className="h-full flex items-center justify-center">
        <Loader2 className="w-8 h-8 animate-spin text-gray-400" />
      </div>
    );
  }

  return (
    <div className="p-8 max-w-3xl mx-auto animate-fade-in-up">
      <div className="flex items-center justify-between mb-2">
        <h1 className="text-2xl font-semibold tracking-tight text-gray-900 dark:text-gray-100">
          LLM providers
        </h1>
        {!showForm && (
          <button
            onClick={() => {
              resetForm();
              setShowForm(true);
            }}
            className="flex items-center gap-2 px-4 py-2.5 bg-gray-900 dark:bg-white text-white dark:text-gray-900 rounded-md hover:bg-gray-800 dark:hover:bg-gray-100 text-sm font-medium transition-colors"
          >
            <Plus className="w-4 h-4" /> Add provider
          </button>
        )}
      </div>
      <p className="text-sm text-gray-500 dark:text-gray-400 mb-6">
        Connect a model provider to start translating your books.
      </p>

      {/* Add provider form */}
      {showForm && (
        <form
          onSubmit={handleSubmit}
          className="surface rounded-lg p-6 mb-6 space-y-6 animate-fade-in-up"
        >
          {/* Step 1: choose provider type */}
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
              Provider type
            </label>
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
              {PROVIDER_TYPES.map((type) => (
                <button
                  key={type.value}
                  type="button"
                  onClick={() => selectProviderType(type)}
                  className={cn(
                    "text-left rounded-md border p-3 transition-colors",
                    form.provider_type === type.value
                      ? "border-gray-900 dark:border-white bg-gray-50 dark:bg-gray-900"
                      : "border-gray-200 dark:border-gray-800 hover:border-gray-300 dark:hover:border-gray-700",
                  )}
                >
                  <div className="text-sm font-medium text-gray-900 dark:text-gray-100">
                    {type.label}
                  </div>
                  <div className="text-xs text-gray-500 dark:text-gray-400 mt-0.5 leading-snug">
                    {type.description}
                  </div>
                </button>
              ))}
            </div>
          </div>

          {/* Step 2: details */}
          <div className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                Display name
              </label>
              <input
                type="text"
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                placeholder={`My ${selectedType.label}`}
                required
                className="w-full rounded-md border border-gray-300 dark:border-gray-700 bg-white dark:bg-[#0a0a0a] px-3 py-2 text-sm text-gray-900 dark:text-gray-100 placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-gray-900 dark:focus:ring-gray-100"
              />
              <p className="text-xs text-gray-400 mt-1">
                A label to recognize this provider in the list.
              </p>
            </div>

            {selectedType.needsApiKey && (
              <div>
                <div className="flex items-center justify-between mb-1">
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300">
                    API key
                  </label>
                  {selectedType.apiKeyUrl && (
                    <a
                      href={selectedType.apiKeyUrl}
                      target="_blank"
                      rel="noreferrer"
                      className="flex items-center gap-1 text-xs text-gray-500 dark:text-gray-400 hover:text-gray-900 dark:hover:text-gray-100"
                    >
                      Get a key <ExternalLink className="w-3 h-3" />
                    </a>
                  )}
                </div>
                <input
                  type="password"
                  value={form.api_key}
                  onChange={(e) =>
                    setForm({ ...form, api_key: e.target.value })
                  }
                  placeholder="sk-..."
                  className="w-full rounded-md border border-gray-300 dark:border-gray-700 bg-white dark:bg-[#0a0a0a] px-3 py-2 text-sm text-gray-900 dark:text-gray-100 placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-gray-900 dark:focus:ring-gray-100"
                />
              </div>
            )}

            {selectedType.needsBaseUrl && (
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                  Base URL
                </label>
                <input
                  type="text"
                  value={form.base_url}
                  onChange={(e) =>
                    setForm({ ...form, base_url: e.target.value })
                  }
                  placeholder={
                    selectedType.defaultBaseUrl || "https://api.example.com/v1"
                  }
                  className="w-full rounded-md border border-gray-300 dark:border-gray-700 bg-white dark:bg-[#0a0a0a] px-3 py-2 text-sm text-gray-900 dark:text-gray-100 placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-gray-900 dark:focus:ring-gray-100"
                />
              </div>
            )}

            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                Default model
              </label>
              <input
                type="text"
                value={form.default_model}
                onChange={(e) =>
                  setForm({ ...form, default_model: e.target.value })
                }
                placeholder={selectedType.defaultModel || "model name"}
                className="w-full rounded-md border border-gray-300 dark:border-gray-700 bg-white dark:bg-[#0a0a0a] px-3 py-2 text-sm text-gray-900 dark:text-gray-100 placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-gray-900 dark:focus:ring-gray-100"
              />
              <p className="text-xs text-gray-400 mt-1">
                Pre-filled with a recommended default — you can change it.
              </p>
            </div>
          </div>

          {/* Test result */}
          {testResult && (
            <div
              className={cn(
                "flex items-center gap-2 p-3 rounded-md text-sm",
                testResult.success
                  ? "bg-gray-100 dark:bg-gray-900 text-gray-900 dark:text-gray-100"
                  : "bg-red-50 dark:bg-red-950 text-red-700 dark:text-red-300",
              )}
            >
              {testResult.success ? (
                <CheckCircle className="w-4 h-4" />
              ) : (
                <XCircle className="w-4 h-4" />
              )}
              {testResult.message}
            </div>
          )}

          <div className="flex gap-2 pt-1">
            <button
              type="button"
              onClick={handleTest}
              disabled={testing}
              className="flex items-center gap-2 px-4 py-2 border border-gray-300 dark:border-gray-700 text-gray-700 dark:text-gray-200 rounded-md hover:bg-gray-50 dark:hover:bg-gray-900 text-sm font-medium disabled:opacity-50 transition-colors"
            >
              {testing ? <Loader2 className="w-4 h-4 animate-spin" /> : null}
              Test connection
            </button>
            <button
              type="submit"
              className="flex items-center gap-2 px-4 py-2 bg-gray-900 dark:bg-white text-white dark:text-gray-900 rounded-md hover:bg-gray-800 dark:hover:bg-gray-100 text-sm font-medium transition-colors"
            >
              Save provider
            </button>
            <button
              type="button"
              onClick={() => {
                setShowForm(false);
                resetForm();
              }}
              className="px-4 py-2 text-gray-500 hover:text-gray-700 dark:hover:text-gray-300 text-sm"
            >
              Cancel
            </button>
          </div>
        </form>
      )}

      {/* Provider list */}
      <div className="space-y-3">
        {providers.length === 0 && !showForm && (
          <div className="text-center py-12 surface rounded-lg">
            <p className="text-gray-700 dark:text-gray-200 font-medium">
              No providers configured
            </p>
            <p className="text-sm text-gray-400 mt-1">
              Add a provider to start translating
            </p>
          </div>
        )}

        {providers.map((provider) => (
          <div
            key={provider.id}
            className="surface rounded-lg p-4 flex items-center justify-between hover:border-gray-300 dark:hover:border-gray-700 transition-colors"
          >
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-md bg-gray-100 dark:bg-gray-900 flex items-center justify-center">
                <Cpu className="w-5 h-5 text-gray-600 dark:text-gray-300" />
              </div>
              <div>
                <h3 className="font-medium text-gray-900 dark:text-gray-100 text-sm">
                  {provider.name}
                </h3>
                <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
                  {provider.provider_type} ·{" "}
                  {provider.default_model || "No default model"}
                  {provider.base_url && ` · ${provider.base_url}`}
                </p>
              </div>
            </div>
            <button
              onClick={() => handleDelete(provider.id)}
              className="p-2 text-gray-400 hover:text-red-600 rounded-md hover:bg-gray-100 dark:hover:bg-gray-900 transition-colors"
              title="Remove"
            >
              <Trash2 className="w-4 h-4" />
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
