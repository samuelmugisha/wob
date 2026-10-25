"use client";

import { useCallback, useEffect, useState } from "react";
import { api, formatDate, JUDGE_SCORE_LABELS, type JudgeTally, type Me } from "@/lib/api";

const STATUS: Record<JudgeTally["status"], { text: string; tone: string }> = {
  winner: { text: "Winner", tone: "success" },
  provisional: { text: "Provisional: scores still missing", tone: "warning" },
  tie: { text: "Tie at the top: the committee decides", tone: "warning" },
  no_scores: { text: "No scores yet", tone: "muted" },
};

/** Every judge's scores, totals and averages per category, ranked to choose the winner.
 * Judges never see this page. */
export default function JudgesScoresPage() {
  const [tallies, setTallies] = useState<JudgeTally[] | null>(null);
  const [me, setMe] = useState<Me | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    api.judgeTally().then(setTallies, (e: Error) => setError(e.message));
  }, []);
  useEffect(load, [load]);
  useEffect(() => {
    api.me().then(setMe, () => setMe(null));
  }, []);
  const isAdmin = me?.permissions.manage_users ?? false;

  async function act(action: () => Promise<unknown>) {
    setError(null);
    try {
      await action();
      load();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  function close(t: JudgeTally) {
    if (!window.confirm(`Close scoring for ${t.name}? Judges can no longer change their scores.`)) return;
    act(() => api.closeJudging(t.id));
  }

  function reopen(t: JudgeTally) {
    const reason = window.prompt(`Reopen scoring for ${t.name} so judges can change their scores? Reason (recorded in the audit log):`);
    if (reason === null) return;
    if (!reason.trim()) {
      setError("Give a reason for reopening scoring.");
      return;
    }
    act(() => api.reopenJudging(t.id, reason.trim()));
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Judges&apos; Scores</h1>
          <p className="muted" style={{ margin: 0 }}>
            Each judge scores the finalists from 0 to 3 on their own. Finalists are ranked by their average
            score, and the highest average wins once all {tallies?.[0]?.expected_judges ?? 3} judges have scored
            everyone. Confidential: judges can&apos;t see this page.
          </p>
        </div>
      </div>
      {error && <div className="notice error">{error}</div>}
      {tallies === null && !error && <p className="muted">Loading…</p>}
      {tallies && tallies.length > 1 && (
        <nav className="card pack-index" aria-label="Categories">
          {tallies.map((t) => (
            <a key={t.id} href={`#${t.code}`} className="text-link">
              {t.name}
            </a>
          ))}
        </nav>
      )}
      {tallies?.map((t) => {
        const status = STATUS[t.status];
        const leaders = t.candidates.filter((c) => t.leaders.includes(c.finalist_id));
        return (
          <section key={t.id} id={t.code} className="card">
            <div className="card-head">
              <h2>{t.name}</h2>
              <div className="inline-form" style={{ marginTop: 0 }}>
                {t.closed_at ? (
                  <>
                    <span className="small muted">
                      Scoring closed {formatDate(t.closed_at)}
                      {t.closed_by ? ` by ${t.closed_by}` : ""}
                    </span>
                    {isAdmin && (
                      <button className="secondary" onClick={() => reopen(t)}>
                        Reopen scoring
                      </button>
                    )}
                  </>
                ) : (
                  t.status !== "no_scores" && (
                    <button className="secondary" onClick={() => close(t)}>
                      Close scoring
                    </button>
                  )
                )}
              </div>
            </div>
            <div className="tally-head">
              <span className={`badge ${status.tone}`}>{status.text}</span>
              {leaders.length > 0 && (
                <span className="tally-winner">
                  {leaders.map((c) => c.full_name).join(" and ")} · average {leaders[0].average} / {t.max_score}
                </span>
              )}
              <span className="small muted">
                {t.judges.length} of {t.expected_judges} judges have scored
                {t.judges.length > 0 ? `: ${t.judges.map((j) => j.name).join(", ")}` : ""}
              </span>
            </div>
            {t.candidates.length === 0 ? (
              <div className="empty small">No judge has scored a finalist in this category yet.</div>
            ) : (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Rank</th>
                      <th>Finalist</th>
                      {t.judges.map((j) => (
                        <th key={j.id} className="num">
                          {j.name}
                        </th>
                      ))}
                      <th className="num">Total</th>
                      <th className="num">Average</th>
                    </tr>
                  </thead>
                  <tbody>
                    {t.candidates.map((c) => (
                      <tr key={c.finalist_id}>
                        <td>
                          {c.rank}
                          {c.is_tie && <span className="badge warning">Tie</span>}
                        </td>
                        <td>
                          <strong>{c.full_name}</strong>
                          {c.organisation && <div className="muted small">{c.organisation}</div>}
                          {c.judges_scored < t.judges.length && (
                            <span className="badge warning">
                              {c.judges_scored} of {t.judges.length} scored
                            </span>
                          )}
                          <ul className="tally-comments small">
                            {c.scores.map((s) => (
                              <li key={s.judge_id}>
                                <strong>{s.judge_name}</strong> ({s.score} {JUDGE_SCORE_LABELS[s.score]}): {s.comment}
                              </li>
                            ))}
                          </ul>
                        </td>
                        {t.judges.map((j) => {
                          const s = c.scores.find((x) => x.judge_id === j.id);
                          return (
                            <td key={j.id} className="num">
                              {s ? s.score : <span className="muted">—</span>}
                            </td>
                          );
                        })}
                        <td className="num">{c.total}</td>
                        <td className="num">
                          <strong>{c.average}</strong>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        );
      })}
    </>
  );
}
