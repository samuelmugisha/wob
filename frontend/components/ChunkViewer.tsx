"use client";

import { useEffect, useState } from "react";
import { api, type Chunk } from "@/lib/api";

function pages(chunk: Chunk): string | null {
  if (chunk.page_number === null) return null;
  if (chunk.page_end === null || chunk.page_end === chunk.page_number) return `p. ${chunk.page_number}`;
  return `pp. ${chunk.page_number}–${chunk.page_end}`;
}

/** The document's text as indexed, so coordinators can check extraction before assessment. */
export default function ChunkViewer({ documentId }: { documentId: string }) {
  const [chunks, setChunks] = useState<Chunk[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.listChunks(documentId).then(setChunks, (e: Error) => setError(e.message));
  }, [documentId]);

  if (error) return <div className="notice error">{error}</div>;
  if (chunks === null) return <p className="muted small">Loading extracted text…</p>;
  if (chunks.length === 0) {
    return <p className="muted small">No text was extracted from this document.</p>;
  }

  return (
    <div className="chunks">
      <p className="muted small" style={{ marginTop: 0 }}>
        Extracted text as indexed for retrieval: {chunks.length} passage
        {chunks.length === 1 ? "" : "s"}. Compare against the original if anything looks wrong.
      </p>
      {chunks.map((chunk) => (
        <article key={chunk.chunk_index} className="chunk">
          <header className="muted small">
            <strong>#{chunk.chunk_index + 1}</strong>
            {pages(chunk) && <> · {pages(chunk)}</>}
            {chunk.section && <> · {chunk.section}</>}
            {chunk.token_count !== null && <> · {chunk.token_count} tokens</>}
            {chunk.has_table && <> · table</>}
            {!chunk.embedded && <span className="warning-text"> · not embedded</span>}
          </header>
          <pre>{chunk.content}</pre>
        </article>
      ))}
    </div>
  );
}
