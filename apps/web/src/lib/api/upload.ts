import { IS_MOCK } from "@/lib/env";

/**
 * PUTs a file to the pre-signed URL from an UploadSession with progress.
 * fetch() can't report upload progress, so this uses XHR.
 */
export function uploadToSignedUrl(
  url: string,
  file: File,
  onProgress: (percent: number) => void,
  signal?: AbortSignal,
): Promise<void> {
  if (IS_MOCK) return mockUpload(file, onProgress, signal);

  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("PUT", url);
    xhr.setRequestHeader("Content-Type", file.type || "application/octet-stream");
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) onProgress(Math.round((e.loaded / e.total) * 100));
    };
    xhr.onload = () =>
      xhr.status >= 200 && xhr.status < 300
        ? resolve()
        : reject(new Error(`Upload failed (${xhr.status}).`));
    xhr.onerror = () => reject(new Error("Upload failed. Check your connection and try again."));
    xhr.onabort = () => reject(new DOMException("Upload cancelled", "AbortError"));
    signal?.addEventListener("abort", () => xhr.abort(), { once: true });
    xhr.send(file);
  });
}

/** Dev-only: simulates upload progress so the wizard UI can be exercised. */
function mockUpload(file: File, onProgress: (p: number) => void, signal?: AbortSignal) {
  return new Promise<void>((resolve, reject) => {
    let pct = 0;
    const step = Math.max(4, Math.round(40 / Math.max(1, file.size / (5 * 1024 * 1024))));
    const t = setInterval(() => {
      pct = Math.min(100, pct + step);
      onProgress(pct);
      if (pct >= 100) {
        clearInterval(t);
        resolve();
      }
    }, 120);
    signal?.addEventListener("abort", () => {
      clearInterval(t);
      reject(new DOMException("Upload cancelled", "AbortError"));
    });
  });
}
