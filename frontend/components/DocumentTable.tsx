"use client";

import { Fragment, useState } from "react";
import { api, type DocumentRecord, formatBytes, formatDate, IN_PROGRESS_STATUSES } from "@/lib/api";
import ChunkViewer from "./ChunkViewer";

const TYPE_LABELS: Record<string, string> = {
  "application/pdf": "PDF",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "Word",
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "Excel",
  "image/png": "Image",
  "image/jpeg": "Image",
};

const STATUS_LABELS: Record<string, string> = {
  pending: "Queued",
  scanning: "Scanning",
  extracting: "Extracting text",
  extracted: "Extracted",
  chunking: "Indexing",
  indexed: "Indexed",
  failed: "Failed",
  rejected: "Rejected",
};

const METHOD_LABELS: Record<string, string> = {
  pdf_text: "text layer",
  ocr: "OCR",
  "pdf_text+ocr": "text layer + OCR",
  docx: "Word",
  xlsx: "spreadsheet",
  image_ocr: "OCR",
};

function StatusCell({ doc }: { doc: DocumentRecord }) {
  if (doc.withdrawn_at) return <span className="badge muted">Withdrawn</span>;
  const status = doc.processing_status;
  const quality = doc.extraction_quality ?? {};
  const tone =
    status === "failed" || status === "rejected"
      ? " danger"
      : status === "indexed" && quality.warnings?.length
        ? " warning"
        : status === "indexed"
          ? " success"
          : "";
  return (
    <>
      <span className={`badge${tone}`}>
        {IN_PROGRESS_STATUSES.includes(status) && <span className="spinner" aria-hidden />}
        {STATUS_LABELS[status] ?? status}
      </span>
      {status === "indexed" && (
        <div className="muted small">
          {quality.chunks ?? 0} passage{quality.chunks === 1 ? "" : "s"}
          {quality.pages ? ` · ${quality.pages} page${quality.pages === 1 ? "" : "s"}` : ""}
          {quality.method ? ` · ${METHOD_LABELS[quality.method] ?? quality.method}` : ""}
          {quality.ocr_mean_confidence !== undefined &&
            ` (${Math.round(quality.ocr_mean_confidence)}% confidence)`}
        </div>
      )}
      {doc.processing_error && <div className="small error-text">{doc.processing_error}</div>}
      {status === "failed" && !doc.processing_error?.includes("gave up") && (
        <div className="muted small">Will retry automatically.</div>
      )}
      {quality.warnings?.map((w) => (
        <div key={w} className="small warning-text">
          ⚠ {w}
        </div>
      ))}
    </>
  );
}

export default function DocumentTable({
  documents,
  onChanged,
}: {
  documents: DocumentRecord[];
  onChanged: () => void;
}) {
  const [withdrawing, setWithdrawing] = useState<string | null>(null);
  const [viewing, setViewing] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  if (documents.length === 0) {
    return <div className="empty">No documents uploaded for this candidate yet.</div>;
  }

  async function reprocess(id: string) {
    setActionError(null);
    try {
      await api.reprocessDocument(id);
      onChanged();
    } catch (e) {
      setActionError((e as Error).message);
    }
  }

  return (
    <div className="table-wrap">
      {actionError && <div className="notice error">{actionError}</div>}
      <table>
        <thead>
          <tr>
            <th>Document</th>
            <th>Type</th>
            <th>Size</th>
            <th>Processing</th>
            <th>Uploaded</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {documents.map((doc) => {
            const canRetry =
              !doc.withdrawn_at &&
              (doc.processing_status === "failed" || doc.processing_status === "rejected");
            const canView = !doc.withdrawn_at && doc.processing_status === "indexed";
            return (
              <Fragment key={doc.id}>
                <tr className={doc.withdrawn_at ? "withdrawn" : undefined}>
                  <td>
                    <a className="doc-name" href={api.downloadUrl(doc.id)}>
                      {doc.filename}
                    </a>
                    <div className="muted small">
                      {doc.source_type === "nomination_form" ? "Nomination form" : "Supporting document"}
                      {doc.archive_name && <> · from {doc.archive_name}</>}
                    </div>
                    {doc.withdrawn_at && (
                      <div className="small">
                        Withdrawn {formatDate(doc.withdrawn_at)}: {doc.withdrawal_reason}
                      </div>
                    )}
                    {withdrawing === doc.id && (
                      <WithdrawForm
                        documentId={doc.id}
                        onCancel={() => setWithdrawing(null)}
                        onDone={() => {
                          setWithdrawing(null);
                          onChanged();
                        }}
                      />
                    )}
                  </td>
                  <td>{TYPE_LABELS[doc.mime_type] ?? doc.mime_type}</td>
                  <td>{formatBytes(doc.size_bytes)}</td>
                  <td>
                    <StatusCell doc={doc} />
                  </td>
                  <td className="small">{formatDate(doc.uploaded_at)}</td>
                  <td className="actions">
                    {canView && (
                      <button
                        className="link"
                        onClick={() => setViewing(viewing === doc.id ? null : doc.id)}
                      >
                        {viewing === doc.id ? "Hide text" : "View text"}
                      </button>
                    )}
                    {canRetry && (
                      <button className="link" onClick={() => reprocess(doc.id)}>
                        Retry
                      </button>
                    )}
                    {!doc.withdrawn_at && withdrawing !== doc.id && (
                      <button className="link" onClick={() => setWithdrawing(doc.id)}>
                        Withdraw
                      </button>
                    )}
                  </td>
                </tr>
                {viewing === doc.id && (
                  <tr className="expanded">
                    <td colSpan={6}>
                      <ChunkViewer documentId={doc.id} />
                    </td>
                  </tr>
                )}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function WithdrawForm({
  documentId,
  onDone,
  onCancel,
}: {
  documentId: string;
  onDone: () => void;
  onCancel: () => void;
}) {
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    try {
      await api.withdrawDocument(documentId, reason.trim());
      onDone();
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit}>
      <div className="inline-form">
        <input
          placeholder="Reason, e.g. uploaded to the wrong candidate"
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          minLength={3}
          required
          autoFocus
        />
        <button type="submit" className="danger" disabled={busy}>
          Withdraw
        </button>
        <button type="button" className="secondary" onClick={onCancel}>
          Cancel
        </button>
      </div>
      <div className="muted small">
        The original is kept for the audit trail but removed from the knowledge base.
      </div>
      {error && <div className="notice error">{error}</div>}
    </form>
  );
}
