import { useEffect, useState } from "react";
import { Check } from "lucide-react";
import { api, type AppSettings } from "../lib/api";
import { inputClass, labelClass } from "../lib/styles";
import { cn } from "../lib/utils";
import { Card, Heading } from "./ui";

const FIELDS = [
  { key: "max_glossary_terms", label: "Glossary terms per prompt" },
  { key: "max_compendium_entries", label: "Compendium entries per prompt" },
] as const;

/** How much glossary and compendium each prompt gets; read at every chunk, so a change
 * applies to running translations too. */
export function RetrievalSettings() {
  const [values, setValues] = useState<Pick<AppSettings, (typeof FIELDS)[number]["key"]> | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.getSettings().then(setValues).catch(() => {});
  }, []);

  const save = (key: (typeof FIELDS)[number]["key"], raw: string) => {
    const value = Number(raw);
    if (!values || raw === "" || value === values[key]) return;
    setError(null);
    api
      .updateSettings({ [key]: value })
      .then((s) => {
        setValues(s);
        setSaved(key);
      })
      .catch((e) => setError(e instanceof Error ? e.message : "Could not save"));
  };

  return (
    <Card aria-labelledby="retrieval-title" className="mt-6 flex flex-col gap-4 p-5">
      <div>
        <Heading id="retrieval-title">Retrieval</Heading>
        <p className="mb-0 mt-1 text-sm text-muted">
          Glossary and compendium entries sent with each passage: the ones it names first, then
          those named just before it. 0 sends all of them. Changes apply from the next passage, also
          to translations already running.
        </p>
      </div>
      {values && (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          {FIELDS.map(({ key, label }) => (
            <label key={key} className={labelClass}>
              <span className="flex items-center gap-1.5">
                {label}
                {saved === key && <Check className="h-4 w-4 text-accent" aria-label="Saved" />}
              </span>
              <input
                type="number"
                min={0}
                step={10}
                defaultValue={values[key]}
                onBlur={(e) => save(key, e.target.value)}
                onChange={() => setSaved(null)}
                className={cn(inputClass, "h-11 font-normal")}
              />
            </label>
          ))}
        </div>
      )}
      {error && <p className="m-0 text-sm text-danger">{error}</p>}
    </Card>
  );
}
