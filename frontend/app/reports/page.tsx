"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { IconDownload } from "@/components/Icons";
import { api, type Category, formatBytes, formatDate, type ReportRecord } from "@/lib/api";

export default function ReportsPage() {
  const [items, setItems] = useState<{ category: Category; reports: ReportRecord[] }[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .listCategories()
      .then((cats) => Promise.all(cats.map((c) => api.listReports(c.id).then((reports) => ({ category: c, reports })))))
      .then(setItems, (e: Error) => setError(e.message));
  }, []);

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Deliberation Reports</h1>
          <p className="muted" style={{ margin: 0 }}>
            Category and individual reports for the committee. Generate new reports from a category&apos;s page.
          </p>
        </div>
      </div>
      {error && <div className="notice error">{error}</div>}
      {items === null && !error && <p className="muted">Loading…</p>}
      {items?.map(({ category, reports }) => (
        <section key={category.id} className="card">
          <div className="card-head">
            <h2>{category.name}</h2>
            <Link href={`/categories/${category.id}#reports`} className="text-link">
              Generate reports
            </Link>
          </div>
          {reports.length === 0 ? (
            <div className="empty small">No reports yet.</div>
          ) : (
            <div className="table-wrap">
              <table className="elegant">
                <thead>
                  <tr>
                    <th>Report</th>
                    <th>Created</th>
                    <th>Size</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {reports.map((r) => (
                    <tr key={r.id}>
                      <td>
                        {r.kind === "category" ? "Category report" : `Individual report: ${r.finalist_name ?? "finalist"}`}
                      </td>
                      <td>{formatDate(r.created_at)}</td>
                      <td>{r.size_bytes ? formatBytes(r.size_bytes) : "—"}</td>
                      <td className="actions">
                        {r.status === "succeeded" ? (
                          <a href={api.reportUrl(r.id)} className="text-link">
                            <IconDownload size={16} /> Download PDF
                          </a>
                        ) : r.status === "failed" ? (
                          <span className="error-text small">Failed: {r.error}</span>
                        ) : (
                          <span className="muted small">
                            <span className="spinner" aria-hidden />
                            Generating…
                          </span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      ))}
    </>
  );
}
