"use client";

import { useCallback, useEffect, useState } from "react";
import { api, type CriterionAssessment, formatDate, type Me } from "@/lib/api";

const SCALE: Record<number, string> = {
  1: "Not demonstrated / no evidence",
  2: "Weak evidence",
  3: "Adequate evidence",
  4: "Strong evidence",
  5: "Exceptional, well-evidenced",
};

const FLAG_TEXT: Record<string, string> = {
  uncited_rating: "No verified citation supports this rating: it cannot be approved above 1",
  citations_discarded: "Some citations could not be verified and were dropped",
  contradicting_evidence: "Contradicting evidence was cited",
  rubric_not_frozen: "Rubric not frozen: practice assessment",
  "retrieval:few_passages": "Little evidence found for this criterion",
  "retrieval:no_keyword_matches": "No keyword matches: evidence matched by meaning only",
  "retrieval:no_indexed_evidence": "The candidate has no indexed evidence",
  "retrieval:no_matching_passages": "No passages matched this criterion",
  "retrieval:low_relevance": "Even the best passage scored low for relevance",
};

function Review({ item, onDone }: { item: CriterionAssessment; onDone: () => void }) {
  const [open, setOpen] = useState(false);
  const [adjusted, setAdjusted] = useState<string>("");
  const [notes, setNotes] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function decide(decision: "approved" | "rejected") {
    setError(null);
    try {
      await api.reviewAssessment(item.id, {
        decision,
        adjusted_rating: adjusted ? Number(adjusted) : undefined,
        notes: notes.trim() || undefined,
      });
      setOpen(false);
      onDone();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  if (!open) {
    return (
      <button className="link small" onClick={() => setOpen(true)}>
        {item.status === "proposed" ? "Review rating" : "Change review"}
      </button>
    );
  }
  return (
    <div className="source-review">
      <div className="form-row">
        <div className="field" style={{ flexGrow: 0, flexBasis: 240 }}>
          <label htmlFor={`adj-${item.id}`}>Rating</label>
          <select id={`adj-${item.id}`} value={adjusted} onChange={(e) => setAdjusted(e.target.value)}>
            <option value="">Keep AI rating ({item.rating})</option>
            {[1, 2, 3, 4, 5].map((n) => (
              <option key={n} value={n}>
                Adjust to {n}: {SCALE[n]}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor={`rn-${item.id}`}>Notes (required to adjust or reject)</label>
          <input id={`rn-${item.id}`} value={notes} onChange={(e) => setNotes(e.target.value)} />
        </div>
      </div>
      <div className="inline-form">
        <button onClick={() => decide("approved")}>Approve</button>
        <button className="danger" onClick={() => decide("rejected")}>
          Reject for re-assessment
        </button>
        <button className="secondary" onClick={() => setOpen(false)}>
          Cancel
        </button>
      </div>
      {error && <div className="notice error">{error}</div>}
    </div>
  );
}

function HumanRating({
  runId,
  finalistId,
  criterion,
  onDone,
}: {
  runId: string;
  finalistId: string;
  criterion: { id: string; name: string; description: string };
  onDone: () => void;
}) {
  const [rating, setRating] = useState("");
  const [sufficiency, setSufficiency] = useState<"sufficient" | "limited" | "insufficient">("sufficient");
  const [rationale, setRationale] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function save(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    try {
      await api.humanRating({
        run_id: runId,
        finalist_id: finalistId,
        criterion_id: criterion.id,
        rating: Number(rating),
        rationale: rationale.trim(),
        sufficiency,
      });
      onDone();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <form className="claim assessment" onSubmit={save}>
      <strong>{criterion.name}</strong>
      <div className="small muted">{criterion.description}</div>
      <div className="form-row">
        <div className="field" style={{ flexGrow: 0, flexBasis: 260 }}>
          <label htmlFor={`hr-${criterion.id}`}>Rating</label>
          <select id={`hr-${criterion.id}`} value={rating} onChange={(e) => setRating(e.target.value)} required>
            <option value="">Choose…</option>
            {[1, 2, 3, 4, 5].map((n) => (
              <option key={n} value={n}>
                {n}: {SCALE[n]}
              </option>
            ))}
          </select>
        </div>
        <div className="field" style={{ flexGrow: 0, flexBasis: 160 }}>
          <label htmlFor={`hs-${criterion.id}`}>Evidence</label>
          <select
            id={`hs-${criterion.id}`}
            value={sufficiency}
            onChange={(e) => setSufficiency(e.target.value as typeof sufficiency)}
          >
            <option value="sufficient">Sufficient</option>
            <option value="limited">Limited</option>
            <option value="insufficient">Insufficient</option>
          </select>
        </div>
      </div>
      <div className="field">
        <label htmlFor={`hn-${criterion.id}`}>Rationale, citing the documents</label>
        <textarea
          id={`hn-${criterion.id}`}
          rows={2}
          minLength={10}
          value={rationale}
          onChange={(e) => setRationale(e.target.value)}
          required
        />
      </div>
      <div>
        <button type="submit" disabled={!rating}>
          Save human rating
        </button>
      </div>
      {error && <div className="notice error">{error}</div>}
    </form>
  );
}

/** The candidate's proposed criterion ratings with cited evidence (FR-08) and quality review. */
export default function AssessmentPanel({ categoryId, finalistId }: { categoryId: string; finalistId: string }) {
  const [data, setData] = useState<Awaited<ReturnType<typeof api.candidateAssessments>> | null>(null);
  const [me, setMe] = useState<Me | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    api.candidateAssessments(categoryId, finalistId).then(setData, (e: Error) => setError(e.message));
  }, [categoryId, finalistId]);
  useEffect(load, [load]);
  useEffect(() => {
    api.me().then(setMe, () => setMe(null));
  }, []);

  if (!data) return error ? <div className="notice error">{error}</div> : null;
  const canReview = me?.permissions.review_claims ?? false;
  const unrated =
    data.run && data.rubric && canReview && !data.hidden_for_calibration
      ? data.rubric.criteria.filter((c) => !data.items.some((i) => i.criterion_id === c.id))
      : [];

  return (
    <section className="card">
      <h2>Criterion assessment</h2>
      <p className="muted small" style={{ marginTop: -6 }}>
        AI-proposed ratings on the committee&apos;s 1–5 scale, each with the evidence it cites. Advisory
        only: reviewers check each rating; the committee decides.
      </p>
      {data.hidden_for_calibration ? (
        <div className="notice warning">
          AI ratings are hidden while you take part in a calibration study for this category, so your own
          ratings stay independent. They reappear once you submit your calibration ratings.
        </div>
      ) : (
        !data.run && <div className="empty">This category has not been assessed yet.</div>
      )}
      {data.run && data.rubric && (
        <div className="muted small run-summary">
          Rubric version {data.rubric.version} ({data.rubric.status}) · assessed{" "}
          {data.run.completed_at ? formatDate(data.run.completed_at) : "in progress"}
        </div>
      )}
      {unrated.length > 0 && (
        <div className="notice">
          {data.run!.llm_model === "human"
            ? "This is a human-only assessment: enter each rating below."
            : "The AI did not rate this finalist on the criteria below (no consent to AI processing, or a criterion added later). Enter human ratings; they count in the ranking."}
        </div>
      )}
      {unrated.map((c) => (
        <HumanRating key={c.id} runId={data.run!.id} finalistId={finalistId} criterion={c} onDone={load} />
      ))}
      {data.items.map((item) => (
        <article key={item.id} className="claim assessment">
          <div className="claim-head">
            <span>
              <strong>{item.criterion_name}</strong>
            </span>
            <span className={`rating r${item.effective_rating}`} title={SCALE[item.effective_rating]}>
              {item.effective_rating}
            </span>
          </div>
          <div className="small muted">
            {item.source === "human" ? "Human rating · " : ""}
            {SCALE[item.effective_rating]} · evidence {item.sufficiency}
            {item.reviewer_rating !== null && ` · AI proposed ${item.rating}, adjusted by reviewer`}
          </div>
          <p className="rationale">{item.rationale}</p>
          {item.limitations && <div className="small warning-text">⚠ {item.limitations}</div>}
          {item.citations.length > 0 && (
            <ul className="quotes">
              {item.citations.map((c, i) => (
                <li key={i} className={c.relation === "contradicts" ? "contradicts" : undefined}>
                  {c.relation === "contradicts" && <strong>Contradicts: </strong>}“{c.quote}” —{" "}
                  {c.url ? (
                    <a href={c.url} target="_blank" rel="noopener noreferrer">
                      {c.publisher}
                    </a>
                  ) : (
                    c.document_id && (
                      <a href={api.downloadUrl(c.document_id)}>
                        {c.filename}
                        {c.page ? `, p. ${c.page}` : ""}
                      </a>
                    )
                  )}
                </li>
              ))}
            </ul>
          )}
          {item.flags.length > 0 && (
            <div className="flags">
              {item.flags.map((f) => (
                <span key={f} className={`badge${f === "uncited_rating" ? " danger" : " warning"}`}>
                  {FLAG_TEXT[f] ?? f}
                </span>
              ))}
            </div>
          )}
          <div className="claim-review small">
            {item.status === "proposed" ? (
              <span className="muted">Not yet reviewed.</span>
            ) : (
              <span className="muted">
                <strong>{item.status === "approved" ? "Approved" : "Rejected"}</strong> by {item.reviewed_by}
                {item.reviewed_at && `, ${formatDate(item.reviewed_at)}`}
                {item.review_notes && `: ${item.review_notes}`}
              </span>
            )}{" "}
            {canReview && <Review item={item} onDone={load} />}
          </div>
        </article>
      ))}
    </section>
  );
}
