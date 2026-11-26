"use client";

import { useRef, useState } from "react";
import { UploadCloud } from "lucide-react";
import { cn, formatBytes } from "@/lib/utils";

export function UploadDropzone({
  accept,
  extension,
  maxBytes,
  onFile,
  disabled,
  hint,
}: {
  accept: string;
  extension: ".zip" | ".apk";
  maxBytes: number;
  onFile: (file: File) => void;
  disabled?: boolean;
  hint: string;
}) {
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  const [error, setError] = useState<string>();

  const pick = (file: File | undefined) => {
    if (!file) return;
    if (!file.name.toLowerCase().endsWith(extension)) {
      setError(`Choose a ${extension} file. “${file.name}” isn't one.`);
      return;
    }
    if (file.size > maxBytes) {
      setError(`That file is ${formatBytes(file.size)}. The limit is ${formatBytes(maxBytes, 0)}.`);
      return;
    }
    if (file.size === 0) {
      setError("That file is empty.");
      return;
    }
    setError(undefined);
    onFile(file);
  };

  return (
    <div>
      <button
        type="button"
        disabled={disabled}
        onClick={() => input.current?.click()}
        onDragOver={(e) => {
          e.preventDefault();
          setOver(true);
        }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setOver(false);
          pick(e.dataTransfer.files[0]);
        }}
        className={cn(
          "flex w-full flex-col items-center justify-center gap-2 rounded-md border border-dashed px-6 py-10 text-center transition-colors disabled:opacity-50",
          over ? "border-foreground/40 bg-surface-2" : "border-border-strong hover:bg-surface-2",
        )}
      >
        <UploadCloud className="size-6 text-muted-foreground" aria-hidden />
        <span className="text-[14px] font-medium">Drop a {extension} file here, or click to choose</span>
        <span className="text-[13px] text-muted-foreground">{hint}</span>
      </button>
      <input
        ref={input}
        type="file"
        accept={accept}
        className="sr-only"
        tabIndex={-1}
        onChange={(e) => {
          pick(e.target.files?.[0]);
          e.target.value = "";
        }}
      />
      {error ? (
        <p className="mt-2 text-[13px] text-destructive" role="alert">
          {error}
        </p>
      ) : null}
    </div>
  );
}
