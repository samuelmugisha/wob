"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { IconDocument, IconDownload } from "@/components/Icons";
import JudgeScoreForm from "@/components/JudgeScoreForm";
import { api, formatBytes, formatDate, type JudgeScore, type JudgesPackCategory, type Me } from "@/lib/api";

const ORDINAL = ["", "1st", "2nd", "3rd"];

/** Each category's top three finalists from its latest ranking, with their reports and documents,
 * for judges to work through in one place and score. */
export default function JudgesPackPage() {
  const [pack, setPack] = useState<JudgesPackCategory[] | null>(null);
  const [me, setMe] = useState<Me | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(() => {
    api.judgesPack().then(setPack, (e: Error) => setError(e.message));
  }, []);
  useEffect(load, [load]);
  useEffect(() => {
    api.me().then(setMe, () => setMe(null));
  }, []);
  const canGenerate = me?.permissions.generate_reports ?? false;
  const canScore = me?.permissions.score_candidates ?? false;

  function scored(categoryId: string, finalistId: string, score: JudgeScore) {
    setPack((all) =>
      all?.map((c) =>
        c.id !== categoryId
          ? c
          : { ...c, finalists: c.finalists.map((f) => (f.finalist_id === finalistId ? { ...f, my_score: score } : f)) },
      ) ?? null,
    );
  }

  /** Generate the reports this category's pack is missing, from its latest ranking. */
  async function generateMissing(category: JudgesPackCategory) {
    setBusy(category.id);
    setError(null);
    try {
      if (!category.category_report) {
        await api.createReport({ kind: "category", category_id: category.id });
      }
      for (const f of category.finalists.filter((f) => !f.report)) {
        await api.createReport({ kind: "individual", category_id: category.id, finalist_id: f.finalist_id });
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
      load();
    }
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Judges&apos; Pack</h1>
          <p className="muted" style={{ margin: 0 }}>
            The top three finalists in each category&apos;s latest ranking, with their reports and documents.
            Rankings are provisional and advisory: the committee decides. Confidential to the judging panel.
            {canScore && (
              <>
                {" "}
                Score each finalist from 0 to 3 with your comments. Your scores are seen only by the awards
                team, never by the other judges.
              </>
            )}
          </p>
        </div>
      </div>
      {error && <div className="notice error">{error}</div>}
      {pack === null && !error && <p className="muted">Loading…</p>}
      {pack && pack.length > 1 && (
        <nav className="card pack-index" aria-label="Categories">
          {pack.map((c) => (
            <a key={c.id} href={`#${c.code}`} className="text-link">
              {c.name}
            </a>
          ))}
        </nav>
      )}
      {pack?.map((category) => {
        const missing = (category.category_report ? 0 : 1) + category.finalists.filter((f) => !f.report).length;
        const mine = category.finalists.filter((f) => f.my_score).length;
        return (
          <section key={category.id} id={category.code} className="card">
            <div className="card-head">
              <h2>{category.name}</h2>
              {category.ranking_id && (
                <span className="small muted">
                  <span className={`badge${category.production ? " success" : " warning"}`}>
                    {category.production ? "Production ranking" : "Practice ranking"}
                  </span>{" "}
                  Ranked {formatDate(category.ranked_at!)}
                  {canScore && category.finalists.length > 0 && (
                    <>
                      {" "}
                      <span className={`badge${mine === category.finalists.length ? " success" : ""}`}>
                        {category.judging_closed
                          ? "Scoring closed"
                          : `You've scored ${mine} of ${category.finalists.length}`}
                      </span>
                    </>
                  )}
                </span>
              )}
            </div>
            {category.hidden_for_calibration ? (
              <div className="empty small">Hidden while you are a blind rater in this category&apos;s calibration study.</div>
            ) : !category.ranking_id ? (
              <div className="empty small">
                Not ranked yet. <Link href={`/categories/${category.id}`}>Open the category</Link> to assess and rank it.
              </div>
            ) : category.finalists.length === 0 ? (
              <div className="empty small">No finalist has a complete score in the latest ranking.</div>
            ) : (
              <>
                <div className="inline-form pack-actions">
                  {category.category_report ? (
                    <a href={api.reportUrl(category.category_report.id)} target="_blank" rel="noopener" className="text-link">
                      <IconDownload size={16} /> Category comparison report
                    </a>
                  ) : (
                    <span className="muted small">No category report yet.</span>
                  )}
                  {canGenerate && missing > 0 && (
                    <button className="secondary" onClick={() => generateMissing(category)} disabled={busy !== null}>
                      {busy === category.id ? "Generating…" : `Generate ${missing} missing report${missing === 1 ? "" : "s"}`}
                    </button>
                  )}
                </div>
                <div className="pack-finalists">
                  {category.finalists.map((f) => (
                    <article key={f.finalist_id} className="pack-finalist">
                      <div className="pack-rank">
                        {ORDINAL[f.rank] ?? f.rank}
                        {f.is_tie && <span className="badge warning">Tie</span>}
                      </div>
                      <h3>
                        <Link href={`/categories/${category.id}/finalists/${f.finalist_id}`}>{f.full_name}</Link>
                      </h3>
                      <div className="small muted">
                        {[f.position_title, f.organisation].filter(Boolean).join(", ") || " "}
                      </div>
                      <div className="pack-score">
                        {f.score_display} <span className="muted small">/ {category.scale_high} · {f.points_display} points</span>
                      </div>
                      {f.unreviewed_criteria.length > 0 && (
                        <div className="small">
                          <span className="badge warning">
                            {f.unreviewed_criteria.length} AI rating{f.unreviewed_criteria.length === 1 ? "" : "s"} not yet reviewed
                          </span>
                        </div>
                      )}
                      {canScore && (
                        <>
                          <h4>Your score</h4>
                          <JudgeScoreForm
                            categoryId={category.id}
                            finalistId={f.finalist_id}
                            name={f.full_name}
                            saved={f.my_score}
                            closed={category.judging_closed}
                            onSaved={(score) => scored(category.id, f.finalist_id, score)}
                          />
                        </>
                      )}
                      <h4>Report</h4>
                      {f.report ? (
                        <a href={api.reportUrl(f.report.id)} target="_blank" rel="noopener" className="text-link">
                          <IconDownload size={16} /> Individual report
                        </a>
                      ) : (
                        <div className="muted small">Not generated yet.</div>
                      )}
                      <h4>Documents ({f.documents.length})</h4>
                      {f.documents.length === 0 ? (
                        <div className="muted small">No documents.</div>
                      ) : (
                        <ul className="pack-docs">
                          {f.documents.map((d) => (
                            <li key={d.id}>
                              <a href={api.downloadUrl(d.id)} target="_blank" rel="noopener" className="text-link">
                                <IconDocument size={16} /> {d.filename}
                              </a>{" "}
                              <span className="muted small">
                                {d.source_type === "nomination_form" ? "Nomination form" : "Supporting"} ·{" "}
                                {formatBytes(d.size_bytes)}
                              </span>
                            </li>
                          ))}
                        </ul>
                      )}
                    </article>
                  ))}
                </div>
              </>
            )}
          </section>
        );
      })}
    </>
  );
}
