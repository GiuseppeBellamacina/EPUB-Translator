import { useState, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import {
  Upload,
  FileText,
  AlertCircle,
  Languages,
  ShieldCheck,
} from "lucide-react";
import { api } from "../lib/api";
import { cn } from "../lib/utils";

export function UploadPage() {
  const [isDragging, setIsDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();

  const handleFile = useCallback(
    async (file: File) => {
      if (!file.name.endsWith(".epub")) {
        setError("Only .epub files are supported");
        return;
      }

      setError(null);
      setUploading(true);

      try {
        const book = await api.uploadBook(file);
        navigate(`/translate/${book.id}`);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Upload failed");
      } finally {
        setUploading(false);
      }
    },
    [navigate],
  );

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setIsDragging(false);
      const file = e.dataTransfer.files[0];
      if (file) handleFile(file);
    },
    [handleFile],
  );

  const handleInputChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (file) handleFile(file);
    },
    [handleFile],
  );

  return (
    <div className="h-full flex items-center justify-center p-8">
      <div className="max-w-lg w-full animate-fade-in-up">
        <div className="text-center mb-8">
          <h1 className="text-2xl font-semibold mb-2 tracking-tight text-gray-900 dark:text-gray-100">
            Translate an EPUB
          </h1>
          <p className="text-sm text-gray-500 dark:text-gray-400">
            Upload your EPUB file to start an intelligent translation with
            consistent terminology
          </p>
        </div>

        {/* Drop zone */}
        <label
          onDragOver={(e) => {
            e.preventDefault();
            setIsDragging(true);
          }}
          onDragLeave={() => setIsDragging(false)}
          onDrop={handleDrop}
          className={cn(
            "group flex flex-col items-center justify-center w-full h-60 border border-dashed rounded-lg cursor-pointer transition-colors duration-200",
            isDragging
              ? "border-gray-900 dark:border-gray-100 bg-gray-50 dark:bg-gray-900"
              : "border-gray-300 dark:border-gray-700 bg-white dark:bg-[#0a0a0a] hover:border-gray-400 dark:hover:border-gray-600",
            uploading && "opacity-50 pointer-events-none",
          )}
        >
          <div className="flex flex-col items-center justify-center pt-5 pb-6">
            {uploading ? (
              <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-gray-900 dark:border-gray-100" />
            ) : (
              <>
                <div className="w-12 h-12 rounded-lg bg-gray-900 dark:bg-white flex items-center justify-center mb-4">
                  <Upload className="w-6 h-6 text-white dark:text-gray-900" />
                </div>
                <p className="mb-1 text-sm text-gray-600 dark:text-gray-300">
                  <span className="font-semibold text-gray-900 dark:text-gray-100">
                    Click to upload
                  </span>{" "}
                  or drag and drop
                </p>
                <p className="text-xs text-gray-400">EPUB files only</p>
              </>
            )}
          </div>
          <input
            type="file"
            className="hidden"
            accept=".epub"
            onChange={handleInputChange}
            disabled={uploading}
          />
        </label>

        {/* Error */}
        {error && (
          <div className="mt-4 flex items-center gap-2 p-3 bg-red-50/80 dark:bg-red-900/20 border border-red-200/60 dark:border-red-900/30 rounded-xl text-red-700 dark:text-red-300 text-sm">
            <AlertCircle className="w-4 h-4 shrink-0" />
            {error}
          </div>
        )}

        {/* Info */}
        <div className="mt-8 grid grid-cols-3 gap-3 text-center">
          {[
            { icon: FileText, label: "Analyze", desc: "Context & glossary" },
            { icon: Languages, label: "Translate", desc: "With consistency" },
            {
              icon: ShieldCheck,
              label: "Review",
              desc: "Quality control",
            },
          ].map(({ icon: Icon, label, desc }) => (
            <div key={label} className="p-4 surface rounded-lg">
              <Icon className="w-4 h-4 text-gray-500 dark:text-gray-400 mx-auto mb-2" />
              <p className="font-semibold text-gray-900 dark:text-gray-100 text-sm">
                {label}
              </p>
              <p className="text-xs text-gray-500 mt-0.5">{desc}</p>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
