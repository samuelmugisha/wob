"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, type CategoryRankings, formatDate, type Me, type RatingScale, ratingTone, SCALE_RANGE } from "@/lib/api";

function ratingClass(value: number | null, unreviewed: boolean, scale: RatingScale): string {
  if (value === null) return "rating missing";
  return `rating ${ratingTone(value, scale)}${unreviewed ? " unreviewed" : ""}`;
}

/** Assessment runs and the provisional ranking with its criterion breakdown (FR-09, FR-10). */
export default function RankingPanel({
  categoryId,
  data,
  me,
  onChanged,
}: {
  categoryId: string;
  data: CategoryRankings;
  me: Me | null;
  onChanged: () => void;
}) {
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const canRun = me?.permissions.manage_evidence ?? false;
  const run = data.latest_run;
  const active = run?.status === "queued" || run?.status === "running";
  const ranking = data.ranking;
  const stale = ranking && run && ranking.run_id !== run.id && run.status === "succeeded";

  useEffect(() => {
    if (!active) return;
    const timer = setInterval(onChanged, 4000);
    return () => clearInterval(timer);
  }, [active, onChanged]);

  async function act(action: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await action();
      onChanged();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card" id="ranking">
      <div className="toolbar">
        <h2 style={{ margin: 0 }}>Assessment and provisional ranking</h2>
        {canRun && (
          <div className="inline-form" style={{ marginTop: 0 }}>
            <button
              className="secondary"
              onClick={() => act(() => api.startAssessment(categoryId))}
              disabled={busy || active || !data.rubric || !data.assessment.enabled}
            >
              {active ? "Assessing…" : run ? "Re-assess all finalists" : "Assess finalists"}
            </button>
            {!data.assessment.enabled && (
              <button
                className="secondary"
                onClick={() => act(() => api.startHumanAssessment(categoryId))}
                disabled={busy || active || !data.rubric}
                title="Reviewers enter every rating; no AI is used"
              >
                Start human-only assessment
              </button>
            )}
            <button
              onClick={() => act(() => api.calculateRanking(categoryId))}
              disabled={busy || run?.status !== "succeeded"}
            >
              Calculate ranking
            </button>
          </div>
        )}
      </div>
      {!data.assessment.enabled && (
        <div className="notice warning">
          AI assessment is off: {data.assessment.reason}. A human-only assessment is still possible: reviewers
          enter each rating on the finalist pages.
        </div>
      )}
      {error && <div className="notice error">{error}</div>}

      {run && (
        <div className="muted small run-summary">
          {active && <span className="spinner" aria-hidden />}
          {active && `Assessing: ${run.items_done} of ${run.items_total} criterion ratings done`}
          {run.status === "succeeded" &&
            `Assessed ${formatDate(run.completed_at!)} · ${run.items_done} criterion ratings · ` +
              `${run.served_by_models.join(", ") || run.llm_model} · ${run.prompt_version}`}
          {run.status === "failed" && (
            <span className="error-text">
              Assessment stopped after {run.items_done} of {run.items_total}: {run.error}
              {run.next_attempt_at && ` Resuming at ${formatDate(run.next_attempt_at)}.`}
            </span>
          )}
        </div>
      )}

      {data.calibration && !data.hidden_for_calibration && (
        <div className={`notice ${data.calibration.outcome === "passed" ? "success" : "warning"}`}>
          <strong>AI calibration: {data.calibration.outcome}</strong> ({data.calibration.name},{" "}
          {formatDate(data.calibration.closed_at)}
          {run && data.calibration.run_id !== run.id ? ", on an earlier assessment run" : ""})
          {data.calibration.reasons.length > 0 && (
            <ul>
              {data.calibration.reasons.map((r) => (
                <li key={r}>{r}</li>
              ))}
            </ul>
          )}
        </div>
      )}
      {!data.calibration && ranking && (
        <div className="notice warning">
          AI ratings have not been calibrated against committee raters yet (FR-15).
        </div>
      )}
      {data.hidden_for_calibration ? (
        <div className="notice warning">
          The ranking is hidden while you take part in a calibration study for this category.
        </div>
      ) : (
        !ranking && <div className="empty">No ranking calculated yet.</div>
      )}
      {ranking && (
        <>
          <div className={`notice ${ranking.production ? "" : "warning"}`}>
            <strong>
              {ranking.production
                ? "Provisional ranking on the frozen rubric."
                : `Practice ranking: rubric version ${ranking.rubric_version} is ${ranking.rubric_status}, not frozen.`}
            </strong>{" "}
            Calculated {formatDate(ranking.created_at)} · {ranking.weighting} weighting ·{" "}
            {ranking.calculation_version}
          </div>
          {stale && (
            <div className="notice warning">A newer assessment has finished: recalculate to use it.</div>
          )}
          <div className="table-wrap">
            <table className="ranking">
              <thead>
                <tr>
                  <th>Rank</th>
                  <th>Finalist</th>
                  <th>Score ({SCALE_RANGE[ranking.scale].label})</th>
                  <th>/100</th>
                  {ranking.criteria.map((c) => (
                    <th key={c.id} title={c.description} className="criterion-col">
                      {c.name}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {ranking.entries.map((e) => (
                  <tr key={e.finalist_category_id}>
                    <td>
                      {e.rank ?? "—"}
                      {e.is_tie && <span className="badge warning">tie</span>}
                    </td>
                    <td>
                      <Link href={`/categories/${categoryId}/finalists/${e.finalist_id}`}>{e.full_name}</Link>
                      {e.organisation && <div className="muted small">{e.organisation}</div>}
                      {e.score === null && (
                        <div className="small warning-text">
                          No score: {e.missing_criteria.length} criteria not assessed or rejected
                        </div>
                      )}
                      {e.unreviewed_criteria.length > 0 && (
                        <div className="small muted">{e.unreviewed_criteria.length} ratings not yet reviewed</div>
                      )}
                    </td>
                    <td>
                      <strong>{e.score_display ?? "—"}</strong>
                    </td>
                    <td>{e.points_display ?? "—"}</td>
                    {ranking.criteria.map((c) => (
                      <td key={c.id}>
                        <span
                          className={ratingClass(e.ratings[c.code] ?? null, e.unreviewed_criteria.includes(c.code), ranking.scale)}
                          title={e.unreviewed_criteria.includes(c.code) ? "Not yet reviewed" : undefined}
                        >
                          {e.ratings[c.code] ?? "—"}
                        </span>
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="muted small">
            Ranked by full-precision score; ties remain provisional pending the committee&apos;s tie-break
            procedure. Dashed ratings have not been reviewed. Open a finalist for the cited evidence behind
            each rating.
          </p>
          {ranking.close_results.length > 0 && (
            <div className="notice warning">
              <strong>Close results</strong>
              <ul>
                {ranking.close_results.map((c, i) => (
                  <li key={i}>
                    {c.higher} and {c.lower}: {c.difference} apart
                  </li>
                ))}
              </ul>
            </div>
          )}
          <div className="notice">{ranking.disclaimer}</div>
        </>
      )}
    </section>
  );
}
