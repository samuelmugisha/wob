"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { IconDocument, IconSearch } from "@/components/Icons";
import {
  api,
  type Category,
  type DocumentKind,
  documentKind,
  type Finalist,
  formatDate,
  IN_PROGRESS_STATUSES,
  type LibraryDocument,
  type LibraryFilters,
  type SourceType,
} from "@/lib/api";

const TABS: { label: string; source?: SourceType }[] = [
  { label: "All Content" },
  { label: "Nomination Forms", source: "nomination_form" },
  { label: "Supporting Documents", source: "supporting_document" },
];

const KINDS: { value: DocumentKind; label: string }[] = [
  { value: "pdf", label: "PDF" },
  { value: "word", label: "Word" },
  { value: "spreadsheet", label: "Spreadsheet" },
  { value: "image", label: "Image" },
  { value: "text", label: "Text" },
  { value: "other", label: "Other" },
];

function StatusBadge({ status }: { status: string }) {
  if (status === "indexed") return <span className="badge success">Indexed</span>;
  if (status === "failed" || status === "rejected") return <span className="badge danger">{status === "failed" ? "Failed" : "Rejected"}</span>;
  if (IN_PROGRESS_STATUSES.includes(status)) return <span className="badge muted">Processing</span>;
  return <span className="badge muted">{status}</span>;
}

export default function KnowledgeBasePage() {
  const [categories, setCategories] = useState<Category[]>([]);
  const [finalists, setFinalists] = useState<Finalist[]>([]);
  const [draft, setDraft] = useState("");
  const [filters, setFilters] = useState<LibraryFilters>({});
  const [result, setResult] = useState<{ total: number; items: LibraryDocument[] } | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.listCategories().then(setCategories, (e: Error) => setError(e.message));
  }, []);
  useEffect(() => {
    if (!filters.category_id) return setFinalists([]);
    api.listFinalists(filters.category_id).then(setFinalists, () => setFinalists([]));
  }, [filters.category_id]);

  const load = useCallback(() => {
    api.library(filters).then(setResult, (e: Error) => setError(e.message));
  }, [filters]);
  useEffect(load, [load]);

  const set = (changes: LibraryFilters) => setFilters((f) => ({ ...f, ...changes }));
  const activeTab = TABS.findIndex((t) => t.source === filters.source_type);

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Knowledge Base</h1>
          <p className="muted" style={{ margin: 0 }}>
            Search and explore all nomination content and supporting documents. To search inside a finalist&apos;s
            evidence, open their page.
          </p>
        </div>
      </div>

      <form
        className="kb-search"
        onSubmit={(e) => {
          e.preventDefault();
          set({ q: draft.trim() || undefined });
        }}
      >
        <span className="kb-search-field">
          <IconSearch size={18} />
          <input
            type="search"
            placeholder="Search across all documents by file name or finalist…"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            aria-label="Search documents"
          />
        </span>
        <button type="submit" className="gold">
          Search
        </button>
      </form>

      <div className="tabs" role="tablist">
        {TABS.map((t, i) => (
          <button
            key={t.label}
            role="tab"
            aria-selected={i === activeTab}
            className={`tab${i === activeTab ? " active" : ""}`}
            onClick={() => set({ source_type: t.source })}
          >
            {t.label}
          </button>
        ))}
      </div>

      {error && <div className="notice error">{error}</div>}

      <div className="kb-layout">
        <aside className="card kb-filters">
          <h3>Filter by</h3>
          <div className="field">
            <label htmlFor="kb-cat">Award category</label>
            <select
              id="kb-cat"
              value={filters.category_id ?? ""}
              onChange={(e) => set({ category_id: e.target.value || undefined, finalist_id: undefined })}
            >
              <option value="">All categories</option>
              {categories.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="kb-kind">Document type</label>
            <select id="kb-kind" value={filters.kind ?? ""} onChange={(e) => set({ kind: (e.target.value || undefined) as DocumentKind | undefined })}>
              <option value="">All types</option>
              {KINDS.map((k) => (
                <option key={k.value} value={k.value}>
                  {k.label}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="kb-fin">Finalist</label>
            <select
              id="kb-fin"
              value={filters.finalist_id ?? ""}
              onChange={(e) => set({ finalist_id: e.target.value || undefined })}
              disabled={!filters.category_id}
            >
              <option value="">{filters.category_id ? "All finalists" : "Choose a category first"}</option>
              {finalists.map((f) => (
                <option key={f.id} value={f.id}>
                  {f.full_name}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="kb-from">Added from</label>
            <input id="kb-from" type="date" value={filters.added_from ?? ""} onChange={(e) => set({ added_from: e.target.value || undefined })} />
          </div>
          <div className="field">
            <label htmlFor="kb-to">Added to</label>
            <input id="kb-to" type="date" value={filters.added_to ?? ""} onChange={(e) => set({ added_to: e.target.value || undefined })} />
          </div>
          <button
            type="button"
            className="secondary"
            onClick={() => {
              setDraft("");
              setFilters({});
            }}
          >
            Clear filters
          </button>
        </aside>

        <section className="card kb-results">
          <h3>
            Documents {result && <span className="muted">({result.total})</span>}
          </h3>
          {result === null && !error && <p className="muted">Loading…</p>}
          {result?.items.length === 0 && <div className="empty">No documents match.</div>}
          {result && result.items.length > 0 && (
            <div className="table-wrap">
              <table className="elegant">
                <thead>
                  <tr>
                    <th>Title</th>
                    <th>Type</th>
                    <th>Finalist</th>
                    <th>Category</th>
                    <th>Source</th>
                    <th>Added</th>
                  </tr>
                </thead>
                <tbody>
                  {result.items.map((d) => (
                    <tr key={d.id}>
                      <td>
                        <span className="doc-title">
                          <IconDocument size={18} />
                          <span>
                            <a href={api.downloadUrl(d.id)}>{d.filename}</a>
                            <span className="doc-status">
                              <StatusBadge status={d.processing_status} />
                            </span>
                          </span>
                        </span>
                      </td>
                      <td>{documentKind(d.mime_type)}</td>
                      <td>
                        <Link href={`/categories/${d.category_id}/finalists/${d.finalist_id}`}>{d.finalist_name}</Link>
                      </td>
                      <td className="small">{d.category_name}</td>
                      <td className="small">{d.source_type === "nomination_form" ? "Nomination" : "Supporting doc"}</td>
                      <td className="small nowrap">{formatDate(d.uploaded_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {result && result.total > result.items.length && (
            <p className="muted small">Showing the {result.items.length} most recent. Narrow the filters to see others.</p>
          )}
        </section>
      </div>
    </>
  );
}
