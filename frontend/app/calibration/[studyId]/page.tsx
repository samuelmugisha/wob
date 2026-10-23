"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { api, type ScaleLevel, type StudySummary, type WorksheetItem } from "@/lib/api";

/** A rater's blind worksheet: evidence-based ratings without seeing the AI's (FR-15). */
export default function CalibrationWorksheet() {
  const { studyId } = useParams<{ studyId: string }>();
  const [study, setStudy] = useState<StudySummary | null>(null);
  const [items, setItems] = useState<WorksheetItem[] | null>(null);
  const [levels, setLevels] = useState<ScaleLevel[]>([]);
  const [attest, setAttest] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    api.studyItems(studyId).then(
      (data) => {
        setStudy(data.study);
        setItems(data.items);
        setLevels(data.scale_levels);
      },
      (e: Error) => setError(e.message),
    );
  }, [studyId]);
  useEffect(load, [load]);

  async function save(item: WorksheetItem, rating: number, notes?: string) {
    setError(null);
    setItems((all) => all?.map((i) => (i.id === item.id ? { ...i, rating, notes: notes ?? i.notes } : i)) ?? null);
    try {
      await api.saveCalibrationRating(studyId, item.id, rating, notes ?? item.notes ?? undefined);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function submit() {
    try {
      await api.submitCalibration(studyId);
      window.location.assign(`/categories/${study?.category_id}`);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  if (error && !items) return <div className="notice error">{error}</div>;
  if (!items || !study) return <p className="muted">Loading…</p>;

  const rated = items.filter((i) => i.rating !== null).length;
  const finalists = [...new Set(items.map((i) => i.finalist_name))];
  const submitted = study.you?.submitted;

  return (
    <>
      <nav className="breadcrumb">
        <Link href={`/categories/${study.category_id}`}>Back to category</Link>
      </nav>
      <h1>{study.name}</h1>
      <div className="notice">
        Rate each finalist on each criterion from the evidence, as you would in judging. The AI&apos;s ratings
        and the ranking are hidden from you until you submit, so your ratings stay independent. Open a
        finalist to read their documents, claims and evidence search.
      </div>
      {submitted && <div className="notice success">You have submitted your ratings. Thank you.</div>}
      {error && <div className="notice error">{error}</div>}

      {finalists.map((name) => {
        const theirs = items.filter((i) => i.finalist_name === name);
        return (
          <section key={name} className="card">
            <div className="toolbar">
              <h2 style={{ margin: 0 }}>{name}</h2>
              <Link href={`/categories/${study.category_id}/finalists/${theirs[0].finalist_id}`} target="_blank">
                Open evidence ↗
              </Link>
            </div>
            {theirs.map((item) => (
              <div key={item.id} className="worksheet-item">
                <strong>{item.criterion.name}</strong>
                <div className="small">{item.criterion.description}</div>
                {item.criterion.evidence_expectations && (
                  <div className="small muted">Evidence expected: {item.criterion.evidence_expectations}</div>
                )}
                <div className="scale">
                  {levels.map(({ rating: value, label, definition }) => (
                    <label
                      key={value}
                      className={`scale-option${item.rating === value ? " chosen" : ""}`}
                      title={`${label}: ${definition}`}
                    >
                      <input
                        type="radio"
                        name={`r-${item.id}`}
                        checked={item.rating === value}
                        disabled={submitted}
                        onChange={() => save(item, value)}
                      />
                      <span className="rating-num">{value}</span>
                      <span className="small">{label}</span>
                    </label>
                  ))}
                </div>
                <input
                  className="small"
                  placeholder="Notes (optional)"
                  defaultValue={item.notes ?? ""}
                  disabled={submitted || item.rating === null}
                  onBlur={(e) => item.rating !== null && e.target.value !== (item.notes ?? "") && save(item, item.rating, e.target.value)}
                />
              </div>
            ))}
          </section>
        );
      })}

      {!submitted && (
        <section className="card">
          <p>
            {rated} of {items.length} rated.
          </p>
          <label className="radio">
            <input type="checkbox" checked={attest} onChange={(e) => setAttest(e.target.checked)} />
            <span>I rated from the evidence without seeing the AI&apos;s ratings or ranking for this category.</span>
          </label>
          <button onClick={submit} disabled={!attest || rated < items.length} style={{ marginTop: 8 }}>
            Submit my ratings
          </button>
        </section>
      )}
    </>
  );
}
