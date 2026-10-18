"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { IconArrow } from "@/components/Icons";
import { api, type Category, type CategoryRankings, formatDate } from "@/lib/api";

const PREVIEW = 5;

export default function RankingsPage() {
  const [items, setItems] = useState<{ category: Category; data: CategoryRankings }[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .listCategories()
      .then((cats) => Promise.all(cats.map((c) => api.categoryRankings(c.id).then((data) => ({ category: c, data })))))
      .then(setItems, (e: Error) => setError(e.message));
  }, []);

  return (
    <>
      <div className="page-head">
        <div>
          <h1>AI Rankings</h1>
          <p className="muted" style={{ margin: 0 }}>
            The latest provisional ranking in each category. Rankings are advisory: the committee decides.
          </p>
        </div>
      </div>
      {error && <div className="notice error">{error}</div>}
      {items === null && !error && <p className="muted">Loading…</p>}
      {items?.length === 0 && <div className="card empty">No award categories yet.</div>}
      <div className="ranking-grid">
        {items?.map(({ category, data }) => {
          const ranking = data.ranking;
          return (
            <section key={category.id} className="card ranking-card">
              <div className="card-head">
                <h2>{category.name}</h2>
                {ranking && (
                  <span className={`badge${ranking.production ? " success" : " warning"}`}>
                    {ranking.production ? "Frozen rubric" : "Practice"}
                  </span>
                )}
              </div>
              {data.hidden_for_calibration ? (
                <div className="notice warning small">Hidden while you take part in a calibration study.</div>
              ) : !ranking ? (
                <div className="empty small">
                  {category.finalist_count === 0 ? "No finalists yet." : "No ranking calculated yet."}
                </div>
              ) : (
                <>
                  <ol className="mini-ranking">
                    {ranking.entries.slice(0, PREVIEW).map((e) => (
                      <li key={e.finalist_category_id}>
                        <span className="mini-rank">{e.rank ?? "—"}</span>
                        <Link href={`/categories/${category.id}/finalists/${e.finalist_id}`}>{e.full_name}</Link>
                        {e.is_tie && <span className="badge warning">tie</span>}
                        <strong className="mini-score">{e.score_display ?? "—"}</strong>
                      </li>
                    ))}
                  </ol>
                  <div className="muted small">
                    Calculated {formatDate(ranking.created_at)} · {ranking.entries.length} finalist
                    {ranking.entries.length === 1 ? "" : "s"}
                  </div>
                </>
              )}
              <Link href={`/categories/${category.id}#ranking`} className="text-link">
                Open category ranking <IconArrow size={16} />
              </Link>
            </section>
          );
        })}
      </div>
    </>
  );
}
