"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { api, type CalibrationResults, formatDate, type Me, type StudySummary } from "@/lib/api";

const pct = (v: number | null | undefined) => (v === null || v === undefined ? "—" : `${Math.round(v * 100)}%`);
const num = (v: number | null | undefined, digits = 2) => (v === null || v === undefined ? "—" : v.toFixed(digits));
const signed = (v: number | null | undefined) =>
  v === null || v === undefined ? "—" : `${v > 0 ? "+" : ""}${v.toFixed(2)}`;

function ResultsView({ results, final }: { results: CalibrationResults; final: boolean }) {
  const o = results.overall;
  return (
    <div className="calibration-results">
      <div className={`notice ${results.outcome === "passed" ? "success" : "warning"}`}>
        <strong>
          {final ? "Outcome" : "Interim outcome"}: {results.outcome}
        </strong>{" "}
        · {o.rated_items} items · {results.raters_completed} rater(s) · {results.finalists} finalist(s)
        {results.reasons.length > 0 && (
          <ul>
            {results.reasons.map((r) => (
              <li key={r}>{r}</li>
            ))}
          </ul>
        )}
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th />
              <th title="Quadratic-weighted kappa: 1 perfect, 0 chance level">Weighted kappa</th>
              <th>Exact match</th>
              <th>Within 1 point</th>
              <th title="AI minus human average; positive means the AI rates higher">AI bias</th>
              <th>Mean abs. difference</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>AI vs committee raters</td>
              <td>{num(o.ai_vs_human.qwk)}</td>
              <td>{pct(o.ai_vs_human.exact)}</td>
              <td>{pct(o.ai_vs_human.within_one)}</td>
              <td>{signed(o.bias)}</td>
              <td>{num(o.mean_absolute_error)}</td>
            </tr>
            <tr className="muted">
              <td>Raters vs each other (baseline)</td>
              <td>{num(o.human_vs_human.qwk)}</td>
              <td>{pct(o.human_vs_human.exact)}</td>
              <td>{pct(o.human_vs_human.within_one)}</td>
              <td />
              <td />
            </tr>
          </tbody>
        </table>
      </div>
      <h3 className="subhead">By criterion</h3>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Criterion</th>
              <th>Items</th>
              <th>AI kappa</th>
              <th>Raters kappa</th>
              <th>Within 1</th>
              <th>AI bias</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(results.by_criterion).map(([name, s]) => (
              <tr key={name}>
                <td>{name}</td>
                <td>{s.rated_items}</td>
                <td>{num(s.ai_vs_human.qwk)}</td>
                <td>{num(s.human_vs_human.qwk)}</td>
                <td>{pct(s.ai_vs_human.within_one)}</td>
                <td className={s.bias !== null && Math.abs(s.bias) > (results.thresholds.max_criterion_bias ?? 0.75) ? "error-text" : undefined}>
                  {signed(s.bias)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="muted small">
        Thresholds (proposed, for committee approval): kappa ≥ {results.thresholds.min_qwk}, no more than{" "}
        {results.thresholds.max_gap_to_humans} below the raters&apos; own agreement, within one point ≥{" "}
        {pct(results.thresholds.min_within_one)}, average bias ≤ ±{results.thresholds.max_bias} (±
        {results.thresholds.max_criterion_bias} per criterion), at least {results.thresholds.min_items} items.
        Where the AI is biased on a criterion, review that criterion&apos;s wording and the assessment prompt;
        AI ratings are never adjusted automatically.
      </p>
    </div>
  );
}

function NewStudy({ categoryId, onCreated }: { categoryId: string; onCreated: () => void }) {
  const [open, setOpen] = useState(false);
  const [people, setPeople] = useState<{ id: string; display_name: string; role: string }[]>([]);
  const [chosen, setChosen] = useState<Set<string>>(new Set());
  const [name, setName] = useState("Calibration study");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (open) api.eligibleRaters().then(setPeople, (e: Error) => setError(e.message));
  }, [open]);

  async function create(event: React.FormEvent) {
    event.preventDefault();
    try {
      await api.createStudy(categoryId, name.trim(), [...chosen]);
      setOpen(false);
      onCreated();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  if (!open) {
    return (
      <button className="secondary" onClick={() => setOpen(true)}>
        New calibration study
      </button>
    );
  }
  return (
    <form className="calibration-new" onSubmit={create}>
      <div className="field">
        <label htmlFor="study-name">Name</label>
        <input id="study-name" value={name} onChange={(e) => setName(e.target.value)} required />
      </div>
      <fieldset>
        <legend className="small muted">
          Raters: choose at least two so their agreement with each other gives a baseline
        </legend>
        {people.map((p) => (
          <label key={p.id} className="radio small">
            <input
              type="checkbox"
              checked={chosen.has(p.id)}
              onChange={(e) => {
                const next = new Set(chosen);
                if (e.target.checked) next.add(p.id);
                else next.delete(p.id);
                setChosen(next);
              }}
            />
            <span>
              {p.display_name} <span className="muted">({p.role})</span>
            </span>
          </label>
        ))}
      </fieldset>
      <p className="muted small">
        Raters rate every AI-assessed finalist and criterion of the latest assessment, without seeing the AI&apos;s
        ratings: rankings, AI ratings and reports for this category are hidden from them until they submit.
      </p>
      <div className="inline-form">
        <button type="submit" disabled={chosen.size === 0}>
          Start study
        </button>
        <button type="button" className="secondary" onClick={() => setOpen(false)}>
          Cancel
        </button>
      </div>
      {error && <div className="notice error">{error}</div>}
    </form>
  );
}

/** Calibration of AI ratings against blind committee ratings (FR-15). */
export default function CalibrationPanel({ categoryId, me, hasRun }: { categoryId: string; me: Me | null; hasRun: boolean }) {
  const [studies, setStudies] = useState<StudySummary[] | null>(null);
  const [shown, setShown] = useState<{ id: string; final: boolean; results: CalibrationResults } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const canManage = me ? ["admin", "secretariat", "committee"].includes(me.role) : false;

  const load = useCallback(() => {
    api.listStudies(categoryId).then(setStudies, (e: Error) => setError(e.message));
  }, [categoryId]);
  useEffect(load, [load]);

  async function show(id: string, close = false) {
    setError(null);
    try {
      if (close && !window.confirm("Close the study? Results become final and ratings can no longer change.")) return;
      const data = close ? await api.closeStudy(id) : await api.studyResults(id);
      setShown({ id, final: data.final, results: data.results });
      if (close) load();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <section className="card">
      <div className="toolbar">
        <h2 style={{ margin: 0 }}>AI calibration</h2>
        {canManage && hasRun && <NewStudy categoryId={categoryId} onCreated={load} />}
      </div>
      <p className="muted small" style={{ marginTop: 0 }}>
        Committee raters rate the same items blind; the AI&apos;s ratings are compared with theirs, and with their
        agreement with each other, before AI ratings are relied on (spec §16).
      </p>
      {error && <div className="notice error">{error}</div>}
      {studies?.length === 0 && <div className="empty">No calibration studies yet.</div>}
      {studies?.map((s) => (
        <article key={s.id} className="claim">
          <div className="claim-head">
            <span>
              <strong>{s.name}</strong>{" "}
              <span className="muted small">
                · {s.items} items · started {formatDate(s.created_at)}
              </span>
            </span>
            <span className={`badge${s.outcome === "passed" ? " success" : s.status === "open" ? " muted" : " warning"}`}>
              {s.status === "open" ? "Open" : s.outcome}
            </span>
          </div>
          <div className="small muted">
            Raters:{" "}
            {s.raters.map((r) => `${r.name} (${r.submitted ? "submitted" : `${r.rated}/${s.items}`})`).join(", ")}
          </div>
          <div className="inline-form">
            {s.you && s.status === "open" && !s.you.submitted && (
              <Link href={`/calibration/${s.id}`} className="button-link">
                Rate now ({s.you.rated}/{s.items})
              </Link>
            )}
            {canManage && (!s.you || s.you.submitted) && (
              <button className="secondary" onClick={() => show(s.id)}>
                {s.status === "closed" ? "Results" : "Interim results"}
              </button>
            )}
            {canManage && s.status === "open" && (!s.you || s.you.submitted) && (
              <button className="secondary" onClick={() => show(s.id, true)}>
                Close study
              </button>
            )}
          </div>
          {shown?.id === s.id && <ResultsView results={shown.results} final={shown.final} />}
        </article>
      ))}
    </section>
  );
}
