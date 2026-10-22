import { useState, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { AlertCircle, ArrowRight, FileText, Languages, ShieldCheck, Upload } from "lucide-react";
import { api, type Book } from "../lib/api";
import { cn } from "../lib/utils";
import { CostEstimate } from "../components/CostEstimate";
import { Button, Card, Page } from "../components/ui";

const STEPS = [
  { icon: FileText, label: "Analyze", desc: "Context and glossary" },
  { icon: Languages, label: "Translate", desc: "Consistent terminology" },
  { icon: ShieldCheck, label: "Review", desc: "Quality control" },
];

export function UploadPage() {
  const [isDragging, setIsDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [uploaded, setUploaded] = useState<Book | null>(null);
  const navigate = useNavigate();

  const handleFile = useCallback(async (file: File) => {
    if (!/\.(epub|pdf)$/i.test(file.name)) {
      setError("Only .epub and .pdf files are supported");
      return;
    }
    setError(null);
    setUploading(true);
    try {
      setUploaded(await api.uploadBook(file));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Upload failed");
    } finally {
      setUploading(false);
    }
  }, []);

  if (uploaded) {
    const isPdf = uploaded.filename.toLowerCase().endsWith(".pdf");
    return (
      <Page
        eyebrow={`${isPdf ? "PDF" : "EPUB"} · ${uploaded.total_chapters} ${isPdf ? "pages" : "chapters"} uploaded`}
        title={uploaded.filename.replace(/\.(epub|pdf)$/i, "")}
        actions={
          <>
            <Button onClick={() => setUploaded(null)}>Upload another</Button>
            <Button variant="primary" onClick={() => navigate(`/translate/${uploaded.id}`)}>
              Continue to translation <ArrowRight className="h-4 w-4" aria-hidden="true" />
            </Button>
          </>
        }
      >
        <Card className="p-6">
          <CostEstimate bookId={uploaded.id} />
        </Card>
      </Page>
    );
  }

  return (
    <Page
      title="Translate a book"
      description="Upload an EPUB or PDF. The translation keeps the same format and layout; only the language changes."
    >
      <label
        onDragOver={(e) => {
          e.preventDefault();
          setIsDragging(true);
        }}
        onDragLeave={() => setIsDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setIsDragging(false);
          const file = e.dataTransfer.files[0];
          if (file) handleFile(file);
        }}
        className={cn(
          "flex h-64 w-full cursor-pointer flex-col items-center justify-center gap-3 rounded-md border border-dashed bg-surface transition-colors",
          isDragging ? "border-accent bg-accent-soft" : "border-line-strong hover:border-ink",
          uploading && "pointer-events-none opacity-60",
        )}
      >
        {uploading ? (
          <div className="h-10 w-10 animate-spin rounded-full border-2 border-line border-t-ink" aria-label="Uploading" />
        ) : (
          <>
            <span className="flex h-12 w-12 items-center justify-center rounded-full bg-ink text-on-ink">
              <Upload className="h-5 w-5" aria-hidden="true" />
            </span>
            <span className="text-sm text-muted">
              <span className="font-semibold text-ink">Click to upload</span> or drag and drop
            </span>
            <span className="text-xs text-faint">.epub or .pdf</span>
          </>
        )}
        <input
          type="file"
          className="sr-only"
          accept=".epub,.pdf"
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) handleFile(file);
          }}
          disabled={uploading}
        />
      </label>

      {error && (
        <div role="alert" className="flex items-center gap-2 rounded-md bg-danger-soft p-3 text-sm text-danger">
          <AlertCircle className="h-4 w-4 shrink-0" aria-hidden="true" />
          {error}
        </div>
      )}

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        {STEPS.map(({ icon: Icon, label, desc }) => (
          <Card key={label} className="flex items-center gap-3 p-4">
            <Icon className="h-5 w-5 text-accent" aria-hidden="true" />
            <div>
              <div className="font-serif text-lg font-medium">{label}</div>
              <div className="text-xs text-muted">{desc}</div>
            </div>
          </Card>
        ))}
      </div>
    </Page>
  );
}
