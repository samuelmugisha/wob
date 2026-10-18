"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";
import { api, type Category, type Finalist, initials } from "@/lib/api";

type Row = Finalist & { category_name: string };

function FinalistsList() {
  const focusVerification = useSearchParams().get("focus") === "verification";
  const [categories, setCategories] = useState<Category[] | null>(null);
  const [rows, setRows] = useState<Row[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("");
  const [onlyUnverified, setOnlyUnverified] = useState(focusVerification);

  useEffect(() => {
    api.listCategories().then(async (cats) => {
      setCategories(cats);
      const lists = await Promise.all(
        cats.map((c) => api.listFinalists(c.id).then((fs) => fs.map((f) => ({ ...f, category_name: c.name })))),
      );
      setRows(lists.flat());
    }).catch((e: Error) => setError(e.message));
  }, []);

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    return (rows ?? [])
      .filter((r) => !category || r.category_id === category)
      .filter((r) => !q || [r.full_name, r.organisation, r.position_title].some((v) => v?.toLowerCase().includes(q)))
      .filter((r) => !onlyUnverified || r.claims_reviewed < r.claims_total)
      .sort((a, b) =>
        onlyUnverified
          ? b.claims_total - b.claims_reviewed - (a.claims_total - a.claims_reviewed)
          : a.full_name.localeCompare(b.full_name),
      );
  }, [rows, query, category, onlyUnverified]);

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Finalists</h1>
          <p className="muted" style={{ margin: 0 }}>
            Every shortlisted finalist across the award categories.
          </p>
        </div>
      </div>
      {error && <div className="notice error">{error}</div>}
      <section className="card">
        <div className="filter-bar">
          <input
            type="search"
            placeholder="Search by name, organisation or position…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            aria-label="Search finalists"
          />
          <select value={category} onChange={(e) => setCategory(e.target.value)} aria-label="Award category">
            <option value="">All categories</option>
            {categories?.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
          <label className="check">
            <input type="checkbox" checked={onlyUnverified} onChange={(e) => setOnlyUnverified(e.target.checked)} />
            Claims awaiting verification
          </label>
        </div>
        {rows === null && !error && <p className="muted">Loading…</p>}
        {rows && shown.length === 0 && <div className="empty">No finalists match.</div>}
        {shown.length > 0 && (
          <div className="table-wrap">
            <table className="elegant">
              <thead>
                <tr>
                  <th>Finalist</th>
                  <th>Category</th>
                  <th>Documents</th>
                  <th>Claims verified</th>
                  <th>Consent</th>
                </tr>
              </thead>
              <tbody>
                {shown.map((f) => (
                  <tr key={f.finalist_category_id}>
                    <td>
                      <div className="person">
                        <span className="avatar small">{initials(f.full_name)}</span>
                        <div>
                          <Link href={`/categories/${f.category_id}/finalists/${f.id}`}>{f.full_name}</Link>
                          <div className="muted small">
                            {[f.position_title, f.organisation].filter(Boolean).join(", ")}
                          </div>
                        </div>
                      </div>
                    </td>
                    <td>
                      <Link href={`/categories/${f.category_id}`} className="quiet-link">
                        {f.category_name}
                      </Link>
                    </td>
                    <td>{f.document_count || <span className="badge warning">None</span>}</td>
                    <td>
                      {f.claims_total === 0 ? (
                        <span className="muted">—</span>
                      ) : (
                        <span className={`badge${f.claims_reviewed === f.claims_total ? " success" : " warning"}`}>
                          {f.claims_reviewed} / {f.claims_total}
                        </span>
                      )}
                    </td>
                    <td className="small">
                      {f.consent === null ? (
                        <span className="muted">Not recorded</span>
                      ) : !f.consent.assessment ? (
                        <span className="badge danger">Withdrawn</span>
                      ) : f.consent.ai_processing ? (
                        <span className="badge success">AI + human</span>
                      ) : (
                        <span className="badge muted">Human only</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </>
  );
}

export default function FinalistsPage() {
  return (
    <Suspense>
      <FinalistsList />
    </Suspense>
  );
}
