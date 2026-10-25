"use client";

import { useEffect, useState } from "react";
import { api, formatDate, JUDGE_SCORE_LABELS, type JudgeScore } from "@/lib/api";

/** A judge's own 0–3 score and comment for one finalist. Other judges' scores are never shown. */
export default function JudgeScoreForm({
  categoryId,
  finalistId,
  name,
  saved,
  closed,
  onSaved,
}: {
  categoryId: string;
  finalistId: string;
  name: string;
  saved: JudgeScore | null;
  closed: boolean;
  onSaved: (score: JudgeScore) => void;
}) {
  const [score, setScore] = useState<number | null>(saved?.score ?? null);
  const [comment, setComment] = useState(saved?.comment ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const unsaved = score !== (saved?.score ?? null) || comment.trim() !== (saved?.comment ?? "");

  // Warn before leaving with a score that hasn't been saved.
  useEffect(() => {
    if (!unsaved || closed) return;
    const warn = (e: BeforeUnloadEvent) => e.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [unsaved, closed]);

  async function save(event: React.FormEvent) {
    event.preventDefault();
    if (score === null) return;
    setBusy(true);
    setError(null);
    try {
      onSaved(await api.saveJudgeScore(categoryId, finalistId, score, comment.trim()));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (closed) {
    return saved ? (
      <div className="small">
        <strong>
          {saved.score} · {JUDGE_SCORE_LABELS[saved.score]}
        </strong>
        <div className="muted">{saved.comment}</div>
        <div className="muted">Scoring is closed.</div>
      </div>
    ) : (
      <div className="muted small">Scoring closed before you scored.</div>
    );
  }

  return (
    <form onSubmit={save} className="judge-score">
      <div className="scale" role="radiogroup" aria-label={`Your score for ${name}`}>
        {JUDGE_SCORE_LABELS.map((label, value) => (
          <label key={value} className={`scale-option${score === value ? " chosen" : ""}`}>
            <input
              type="radio"
              name={`score-${categoryId}-${finalistId}`}
              checked={score === value}
              onChange={() => setScore(value)}
            />
            <span className="rating-num">{value}</span>
            <span className="small muted">{label}</span>
          </label>
        ))}
      </div>
      <textarea
        rows={3}
        value={comment}
        onChange={(e) => setComment(e.target.value)}
        placeholder="Your comments"
        aria-label={`Your comments on ${name}`}
        maxLength={4000}
        required
      />
      <div className="inline-form" style={{ marginTop: 0 }}>
        <button type="submit" disabled={busy || score === null || !comment.trim() || !unsaved}>
          {busy ? "Saving…" : saved ? "Update score" : "Save score"}
        </button>
        <span className="muted small">
          {unsaved ? (saved ? "Unsaved changes" : "Not scored yet") : saved ? `Saved ${formatDate(saved.updated_at)}` : ""}
        </span>
      </div>
      {error && <div className="notice error">{error}</div>}
    </form>
  );
}
