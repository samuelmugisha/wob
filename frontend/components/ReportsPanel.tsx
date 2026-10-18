"use client";

import { useCallback, useEffect, useState } from "react";
import { api, formatBytes, formatDate, type Me, type Ranking, type ReportRecord } from "@/lib/api";

/** PDF deliberation reports generated from the latest ranking snapshot (FR-11). */
export default function ReportsPanel({
  categoryId,
  ranking,
  me,
}: {
  categoryId: string;
  ranking: Ranking | null;
  me: Me | null;
}) {
  const [reports, setReports] = useState<ReportRecord[] | null>(null);
  const [finalistId, setFinalistId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const canGenerate = me?.permissions.generate_reports ?? false;

  const load = useCallback(() => {
    api.listReports(categoryId).then(setReports, (e: Error) => setError(e.message));
  }, [categoryId]);
  useEffect(load, [load]);

  async function generate(kind: "individual" | "category") {
    setBusy(true);
    setError(null);
    try {
      await api.createReport({
        kind,
        category_id: categoryId,
        finalist_id: kind === "individual" ? finalistId : undefined,
      });
      load(); // the new report appears at the top of the list
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card" id="reports">
      <h2>Deliberation reports</h2>
      <p className="muted small" style={{ marginTop: -6 }}>
        PDFs built from the latest ranking: the category comparison, or one finalist&apos;s scorecard with
        cited evidence, open verification and questions for judges. Confidential to the committee.
      </p>
      {!ranking && <div className="empty">Calculate a ranking first.</div>}
      {ranking && canGenerate && (
        <div className="inline-form">
          <button onClick={() => generate("category")} disabled={busy}>
            Category report
          </button>
          <select value={finalistId} onChange={(e) => setFinalistId(e.target.value)} style={{ maxWidth: 260 }}>
            <option value="">Choose a finalist…</option>
            {ranking.entries.map((e) => (
              <option key={e.finalist_id} value={e.finalist_id}>
                {e.full_name}
              </option>
            ))}
          </select>
          <button className="secondary" onClick={() => generate("individual")} disabled={busy || !finalistId}>
            Individual report
          </button>
        </div>
      )}
      {error && <div className="notice error">{error}</div>}
      {reports && reports.length > 0 && (
        <div className="table-wrap" style={{ marginTop: 12 }}>
          <table>
            <thead>
              <tr>
                <th>Report</th>
                <th>Generated</th>
                <th>Size</th>
                <th>SHA-256</th>
              </tr>
            </thead>
            <tbody>
              {reports.map((r) => (
                <tr key={r.id}>
                  <td>
                    {r.status === "succeeded" ? (
                      <a href={api.reportUrl(r.id)} target="_blank" rel="noopener">
                        {r.kind === "category" ? "Category comparison" : `Individual: ${r.finalist_name}`}
                      </a>
                    ) : (
                      <span className="error-text">Failed: {r.error}</span>
                    )}
                    {ranking && r.snapshot_id !== ranking.id && (
                      <div className="small muted">From an earlier ranking</div>
                    )}
                  </td>
                  <td className="small">{formatDate(r.created_at)}</td>
                  <td className="small">{r.size_bytes ? formatBytes(r.size_bytes) : "—"}</td>
                  <td className="small muted" title={r.sha256_hash ?? undefined}>
                    {r.sha256_hash?.slice(0, 12)}…
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
