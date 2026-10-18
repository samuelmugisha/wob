"use client";

import { useState } from "react";
import { api, type Claim, type ClaimStatus, formatDate, type Review } from "@/lib/api";

export const STATUS_LABELS: Record<ClaimStatus, string> = {
  verified: "Verified",
  corroborated: "Corroborated",
  unverified: "Unverified",
  missing: "Missing evidence",
  disputed: "Disputed",
};

const DECISIONS: { value: ClaimStatus; label: string; help: string }[] = [
  { value: "verified", label: "Verified", help: "Checked against the original document." },
  {
    value: "corroborated",
    label: "Corroborated",
    help: "Supported by two or more independent sources (documents or accepted public sources). Say how they are independent.",
  },
  { value: "disputed", label: "Disputed", help: "The evidence contradicts or does not support it." },
  {
    value: "missing",
    label: "Missing evidence",
    help: "The claim relies on evidence that was not provided.",
  },
  { value: "unverified", label: "Reset to unverified", help: "Undo an earlier decision." },
];

export function statusTone(status: ClaimStatus): string {
  if (status === "verified" || status === "corroborated") return " success";
  if (status === "disputed") return " danger";
  if (status === "missing") return " warning";
  return " muted";
}

function ReviewLine({ review }: { review: Review }) {
  return (
    <>
      <strong>{STATUS_LABELS[review.decision]}</strong> by {review.reviewer} ({review.reviewer_role}),{" "}
      {formatDate(review.created_at)}
      {review.sufficiency && ` · evidence ${review.sufficiency}`}
      {review.credibility && ` · ${review.credibility} credibility`}
      {review.carried_forward && " · carried forward from the previous extraction"}
      {review.notes && <div className="review-notes">{review.notes}</div>}
    </>
  );
}

/** The latest decision, history, and (for reviewers) the form to record a new decision. */
export default function ClaimReview({
  claim,
  canReview,
  onReviewed,
}: {
  claim: Claim;
  canReview: boolean;
  onReviewed: (updated: Claim) => void;
}) {
  const [open, setOpen] = useState(false);
  const [history, setHistory] = useState<Review[] | null>(null);
  const [decision, setDecision] = useState<ClaimStatus>(
    claim.status === "unverified" ? "verified" : claim.status,
  );
  const [notes, setNotes] = useState("");
  const [sufficiency, setSufficiency] = useState<Review["sufficiency"]>(null);
  const [credibility, setCredibility] = useState<Review["credibility"]>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const notesRequired = decision !== "verified";
  const corroborationBlocked = decision === "corroborated" && claim.independent_sources < 2;

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const updated = await api.reviewClaim(claim.id, {
        decision,
        expected_status: claim.status,
        notes: notes.trim() || undefined,
        sufficiency: sufficiency ?? undefined,
        credibility: credibility ?? undefined,
      });
      setOpen(false);
      setNotes("");
      setHistory(null);
      onReviewed(updated);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function toggleHistory() {
    if (history) return setHistory(null);
    try {
      setHistory(await api.listReviews(claim.id));
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <div className="claim-review small">
      {claim.latest_review ? (
        <div className="muted">
          <ReviewLine review={claim.latest_review} />
        </div>
      ) : (
        <div className="muted">Not yet reviewed.</div>
      )}
      <div className="review-actions">
        {canReview && !open && (
          <button className="link" onClick={() => setOpen(true)}>
            {claim.latest_review ? "Change decision" : "Review"}
          </button>
        )}
        {claim.review_count > 1 && (
          <button className="link" onClick={toggleHistory}>
            {history ? "Hide history" : `History (${claim.review_count})`}
          </button>
        )}
      </div>
      {history && (
        <ol className="review-history muted">
          {history.map((r) => (
            <li key={r.id}>
              <ReviewLine review={r} />
            </li>
          ))}
        </ol>
      )}

      {open && (
        <form className="review-form" onSubmit={submit}>
          <fieldset>
            <legend>Decision</legend>
            {DECISIONS.map((d) => (
              <label key={d.value} className="radio">
                <input
                  type="radio"
                  name={`decision-${claim.id}`}
                  value={d.value}
                  checked={decision === d.value}
                  onChange={() => setDecision(d.value)}
                />
                <span>
                  <strong>{d.label}</strong> <span className="muted">{d.help}</span>
                </span>
              </label>
            ))}
          </fieldset>
          {corroborationBlocked && (
            <div className="notice warning">
              Only one independent source supports this claim, so it can be verified but not
              corroborated. Accepting a public source from the research panel can add a second.
            </div>
          )}
          <div className="form-row">
            <div className="field">
              <label htmlFor={`suff-${claim.id}`}>Evidence sufficiency</label>
              <select
                id={`suff-${claim.id}`}
                value={sufficiency ?? ""}
                onChange={(e) => setSufficiency((e.target.value || null) as Review["sufficiency"])}
              >
                <option value="">Not assessed</option>
                <option value="sufficient">Sufficient</option>
                <option value="limited">Limited</option>
                <option value="insufficient">Insufficient</option>
              </select>
            </div>
            <div className="field">
              <label htmlFor={`cred-${claim.id}`}>Source credibility</label>
              <select
                id={`cred-${claim.id}`}
                value={credibility ?? ""}
                onChange={(e) => setCredibility((e.target.value || null) as Review["credibility"])}
              >
                <option value="">Not assessed</option>
                <option value="high">High</option>
                <option value="medium">Medium</option>
                <option value="low">Low</option>
              </select>
            </div>
          </div>
          <div className="field">
            <label htmlFor={`notes-${claim.id}`}>Notes{notesRequired ? " (required)" : " (optional)"}</label>
            <textarea
              id={`notes-${claim.id}`}
              rows={2}
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              required={notesRequired}
              placeholder="What you checked, and against which source"
            />
          </div>
          <div className="inline-form">
            <button type="submit" disabled={busy || corroborationBlocked}>
              {busy ? "Saving…" : "Save decision"}
            </button>
            <button type="button" className="secondary" onClick={() => setOpen(false)}>
              Cancel
            </button>
          </div>
        </form>
      )}
      {error && <div className="notice error">{error}</div>}
    </div>
  );
}
