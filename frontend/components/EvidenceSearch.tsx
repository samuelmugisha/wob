"use client";

import { useState } from "react";
import { api, type Passage, type SearchResult } from "@/lib/api";

const FLAG_TEXT: Record<string, string> = {
  no_indexed_evidence: "This candidate has no indexed evidence yet.",
  no_matching_passages: "No passages matched.",
  few_passages: "Only a few passages matched: evidence may be thin for this question.",
  no_keyword_matches: "No passage shares keywords with the question; results rely on meaning only.",
  some_evidence_not_embedded_with_current_model:
    "Some documents were indexed with a different embedding model and only match by keyword. Re-process them.",
  low_relevance: "Even the best passage scored low for relevance.",
};

function pageLabel(p: Passage): string | null {
  if (p.page_start === null) return null;
  return p.page_end && p.page_end !== p.page_start
    ? `pp. ${p.page_start}–${p.page_end}`
    : `p. ${p.page_start}`;
}

function matchedBy(p: Passage): string {
  if (p.vector_rank && p.lexical_rank) return "meaning + keywords";
  return p.lexical_rank ? "keywords" : "meaning";
}

/** Hybrid search over one candidate's evidence: what the assessor will see for a question. */
export default function EvidenceSearch({
  categoryId,
  finalistId,
}: {
  categoryId: string;
  finalistId: string;
}) {
  const [query, setQuery] = useState("");
  const [result, setResult] = useState<SearchResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (query.trim().length < 2) return;
    setBusy(true);
    setError(null);
    try {
      setResult(await api.searchEvidence(categoryId, finalistId, query.trim()));
      setExpanded(new Set());
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  function toggle(id: string) {
    setExpanded((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  return (
    <section className="card">
      <h2>Search this candidate&apos;s evidence</h2>
      <p className="muted small" style={{ marginTop: -6 }}>
        Searches only this candidate&apos;s indexed documents, by meaning and by keyword.
      </p>
      <form className="inline-form" onSubmit={submit}>
        <input
          placeholder="e.g. evidence of chairing a board committee"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          maxLength={1000}
        />
        <button type="submit" disabled={busy || query.trim().length < 2}>
          {busy ? "Searching…" : "Search"}
        </button>
      </form>

      {error && <div className="notice error">{error}</div>}
      {result?.flags.map((flag) => (
        <div key={flag} className="notice warning">
          {FLAG_TEXT[flag] ?? flag}
        </div>
      ))}

      {result && result.passages.length > 0 && (
        <>
          <p className="muted small">
            {result.passages.length} most relevant of {result.candidates.fused} candidate passages
            ({result.candidates.indexed_chunks} indexed).
          </p>
          <ol className="results">
            {result.passages.map((p) => {
              const open = expanded.has(p.chunk_id);
              return (
                <li key={p.chunk_id} className="chunk">
                  <header className="muted small">
                    <strong>
                      #{p.rank} · <a href={api.downloadUrl(p.document_id)}>{p.filename}</a>
                    </strong>
                    {pageLabel(p) && <> · {pageLabel(p)}</>}
                    {p.section && <> · {p.section}</>}
                    <span className="badge muted" style={{ marginLeft: 8 }}>
                      {matchedBy(p)}
                    </span>
                  </header>
                  <pre className={open ? undefined : "clamp"}>{p.content}</pre>
                  <button className="link small" onClick={() => toggle(p.chunk_id)}>
                    {open ? "Show less" : "Show full passage"}
                  </button>
                </li>
              );
            })}
          </ol>
        </>
      )}
    </section>
  );
}
