"use client";

import { useRef, useState } from "react";
import { api, formatBytes, type SourceType, type UploadResult } from "@/lib/api";

const ACCEPT = ".pdf,.docx,.xlsx,.png,.jpg,.jpeg,.zip";
const MAX_FILE_BYTES = 50 * 1024 * 1024; // matches the API's max_file_bytes
const UPLOAD_BATCH_BYTES = 100 * 1024 * 1024; // must stay below proxyClientMaxBodySize

/** Groups files into requests of at most UPLOAD_BATCH_BYTES each. */
function batches(files: File[]): File[][] {
  const result: File[][] = [];
  let current: File[] = [];
  let size = 0;
  for (const file of files) {
    if (current.length > 0 && size + file.size > UPLOAD_BATCH_BYTES) {
      result.push(current);
      current = [];
      size = 0;
    }
    current.push(file);
    size += file.size;
  }
  if (current.length > 0) result.push(current);
  return result;
}

export default function UploadPanel({
  categoryId,
  finalistId,
  onUploaded,
}: {
  categoryId: string;
  finalistId: string;
  onUploaded: () => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [files, setFiles] = useState<File[]>([]);
  const [sourceType, setSourceType] = useState<SourceType>("supporting_document");
  const [dragging, setDragging] = useState(false);
  const [progress, setProgress] = useState<number | null>(null);
  const [result, setResult] = useState<UploadResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  function addFiles(list: FileList | null) {
    if (!list) return;
    setResult(null);
    setError(null);
    setFiles((current) => {
      const seen = new Set(current.map((f) => `${f.name}:${f.size}`));
      return [...current, ...Array.from(list).filter((f) => !seen.has(`${f.name}:${f.size}`))];
    });
  }

  async function upload() {
    setProgress(0);
    setError(null);
    setResult(null);

    const tooLarge = files.filter((f) => f.size > MAX_FILE_BYTES);
    const sendable = files.filter((f) => f.size <= MAX_FILE_BYTES);
    const combined: UploadResult = {
      import_id: "",
      replayed: false,
      accepted: [],
      skipped: tooLarge.map((f) => ({ filename: f.name, reason: "file is larger than 50 MB" })),
    };
    const totalBytes = sendable.reduce((sum, f) => sum + f.size, 0) || 1;
    let sentBytes = 0;
    const remaining = [...sendable];

    try {
      for (const batch of batches(sendable)) {
        const batchBytes = batch.reduce((sum, f) => sum + f.size, 0);
        const outcome = await api.uploadDocuments(categoryId, finalistId, batch, sourceType, (p) =>
          setProgress((sentBytes + p * batchBytes) / totalBytes),
        );
        sentBytes += batchBytes;
        combined.accepted.push(...outcome.accepted);
        combined.skipped.push(...outcome.skipped);
        remaining.splice(0, batch.length);
      }
      setFiles([]);
    } catch (e) {
      // Keep the files that were not sent so the coordinator can retry them.
      setFiles(remaining);
      setError((e as Error).message);
    } finally {
      setProgress(null);
      if (combined.accepted.length > 0 || combined.skipped.length > 0) setResult(combined);
      if (combined.accepted.length > 0) onUploaded();
    }
  }

  const uploading = progress !== null;

  return (
    <section className="card">
      <h2>Upload documents</h2>
      <div
        className={`dropzone${dragging ? " active" : ""}`}
        role="button"
        tabIndex={0}
        onClick={() => inputRef.current?.click()}
        onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && inputRef.current?.click()}
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          addFiles(e.dataTransfer.files);
        }}
      >
        <strong>Drop files here</strong> or click to choose
        <div className="small">PDF, Word (DOCX), Excel (XLSX), PNG/JPG images, or a ZIP of these · up to 50 MB each</div>
        <input
          ref={inputRef}
          type="file"
          multiple
          accept={ACCEPT}
          hidden
          onChange={(e) => {
            addFiles(e.target.files);
            e.target.value = "";
          }}
        />
      </div>

      {files.length > 0 && (
        <>
          <ul className="staged">
            {files.map((file) => (
              <li key={`${file.name}:${file.size}`}>
                <span>{file.name}</span>
                <span className="muted">
                  {formatBytes(file.size)}{" "}
                  {!uploading && (
                    <button
                      className="link"
                      onClick={() => setFiles((all) => all.filter((f) => f !== file))}
                    >
                      remove
                    </button>
                  )}
                </span>
              </li>
            ))}
          </ul>
          <div className="form-row">
            <div className="field" style={{ flexGrow: 0, flexBasis: 260 }}>
              <label htmlFor="source-type">Document type</label>
              <select
                id="source-type"
                value={sourceType}
                onChange={(e) => setSourceType(e.target.value as SourceType)}
                disabled={uploading}
              >
                <option value="supporting_document">Supporting document</option>
                <option value="nomination_form">Nomination form</option>
              </select>
            </div>
            <button onClick={upload} disabled={uploading}>
              {uploading ? "Uploading…" : `Upload ${files.length} file${files.length === 1 ? "" : "s"}`}
            </button>
            {!uploading && (
              <button className="secondary" onClick={() => setFiles([])}>
                Clear
              </button>
            )}
          </div>
        </>
      )}

      {uploading && <progress value={progress} max={1} style={{ marginTop: 12 }} />}
      {error && <div className="notice error">Upload failed: {error}</div>}
      {result && <UploadSummary result={result} />}
    </section>
  );
}

function UploadSummary({ result }: { result: UploadResult }) {
  const accepted = result.accepted.length;
  return (
    <>
      {accepted > 0 && (
        <div className="notice success">
          {accepted} document{accepted === 1 ? "" : "s"} added to this candidate&apos;s evidence and
          queued for processing.
        </div>
      )}
      {result.skipped.length > 0 && (
        <div className="notice warning">
          {result.skipped.length} file{result.skipped.length === 1 ? " was" : "s were"} not added:
          <ul>
            {result.skipped.map((s, i) => (
              <li key={i}>
                <strong>{s.filename}</strong> — {s.reason}
              </li>
            ))}
          </ul>
        </div>
      )}
    </>
  );
}
