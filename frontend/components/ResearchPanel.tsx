"use client";

import { useCallback, useEffect, useState } from "react";
import { api, formatDate, type Me, type PublicSource, type Quality, type ResearchResponse } from "@/lib/api";

const SOURCE_TYPES: Record<string, string> = {
  official_registry: "Official registry",
  regulator: "Regulator",
  organisation_website: "Organisation website",
  annual_report: "Annual report",
  news_media: "News media",
  professional_body: "Professional body",
  other: "Other",
};

function Highlighted({ passage, quote }: { passage: string; quote: string | null }) {
  const needle = (quote ?? "").replace(/\s+/g, " ").trim().toLowerCase();
  const start = needle ? passage.toLowerCase().indexOf(needle) : -1;
  if (start < 0) return <>{passage}</>;
  return (
    <>
      {passage.slice(0, start)}
      <mark>{passage.slice(start, start + needle.length)}</mark>
      {passage.slice(start + needle.length)}
    </>
  );
}

function SourceReview({ source, onDone }: { source: PublicSource; onDone: () => void }) {
  const [credibility, setCredibility] = useState<Quality | "">("");
  const [identityConfirmed, setIdentityConfirmed] = useState(false);
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const needsIdentity = source.identity_confidence !== "high";

  async function decide(outcome: "accepted" | "rejected") {
    setBusy(true);
    setError(null);
    try {
      await api.reviewSource(source.id, {
        outcome,
        credibility: credibility || undefined,
        identity_confirmed: identityConfirmed,
        notes: notes.trim() || undefined,
      });
      onDone();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="source-review">
      <div className="form-row">
        <div className="field" style={{ flexGrow: 0, flexBasis: 180 }}>
          <label htmlFor={`cred-${source.id}`}>Source credibility</label>
          <select
            id={`cred-${source.id}`}
            value={credibility}
            onChange={(e) => setCredibility(e.target.value as Quality | "")}
          >
            <option value="">Choose…</option>
            <option value="high">High</option>
            <option value="medium">Medium</option>
            <option value="low">Low</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor={`notes-${source.id}`}>Notes (required to reject)</label>
          <input id={`notes-${source.id}`} value={notes} onChange={(e) => setNotes(e.target.value)} />
        </div>
      </div>
      {needsIdentity && (
        <label className="small radio">
          <input
            type="checkbox"
            checked={identityConfirmed}
            onChange={(e) => setIdentityConfirmed(e.target.checked)}
          />
          <span>I have confirmed this page is about this nominee, not someone with the same name.</span>
        </label>
      )}
      <div className="inline-form">
        <button
          onClick={() => decide("accepted")}
          disabled={busy || !credibility || (needsIdentity && !identityConfirmed) || !source.claim_current}
        >
          Accept as evidence
        </button>
        <button className="danger" onClick={() => decide("rejected")} disabled={busy || !notes.trim()}>
          Reject
        </button>
      </div>
      {!source.claim_current && (
        <div className="muted small">The claim was re-extracted since; run research again.</div>
      )}
      {error && <div className="notice error">{error}</div>}
    </div>
  );
}

function SourceCard({ source, canReview, onChanged }: { source: PublicSource; canReview: boolean; onChanged: () => void }) {
  return (
    <article className="claim">
      <div className="claim-head">
        <span>
          <span className={`badge${source.relation === "contradicts" ? " danger" : " success"}`}>
            {source.relation === "contradicts" ? "Contradicts" : "Supports"}
          </span>{" "}
          {source.claim_statement}
        </span>
        {source.reviewer_outcome !== "pending" && (
          <span className={`badge${source.reviewer_outcome === "accepted" ? " success" : " muted"}`}>
            {source.reviewer_outcome === "accepted" ? "Accepted" : "Rejected"}
          </span>
        )}
      </div>
      <div className="small">
        <a href={source.url} target="_blank" rel="noopener noreferrer">
          {source.title || source.url}
        </a>{" "}
        <span className="muted">
          · {source.publisher}
          {source.source_type && ` · ${SOURCE_TYPES[source.source_type] ?? source.source_type}`}
          {source.published_at && ` · published ${source.published_at}`}
          {` · retrieved ${formatDate(source.retrieved_at)}`}
        </span>
      </div>
      <blockquote className="passage small">
        <Highlighted passage={source.evidence_passage} quote={source.quote} />
      </blockquote>
      <div className="small">
        <span className={`badge${source.identity_confidence === "high" ? " muted" : " warning"}`}>
          Identity: {source.identity_confidence ?? "unknown"}
          {source.identity_confirmed && ", confirmed by reviewer"}
        </span>{" "}
        <span className="muted">{source.identity_notes}</span>
      </div>
      {source.reviewer_outcome !== "pending" ? (
        <div className="muted small" style={{ marginTop: 6 }}>
          {source.reviewer_outcome === "accepted" ? "Accepted" : "Rejected"} by {source.reviewed_by}
          {source.reviewed_at && `, ${formatDate(source.reviewed_at)}`}
          {source.credibility && ` · ${source.credibility} credibility`}
          {source.review_notes && ` · ${source.review_notes}`}
        </div>
      ) : (
        canReview && <SourceReview source={source} onDone={onChanged} />
      )}
    </article>
  );
}

/** Credible public sources found for the candidate's claims (FR-13), for reviewers to accept. */
export default function ResearchPanel({ categoryId, finalistId }: { categoryId: string; finalistId: string }) {
  const [data, setData] = useState<ResearchResponse | null>(null);
  const [me, setMe] = useState<Me | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [showDiscarded, setShowDiscarded] = useState(false);

  const load = useCallback(() => {
    api.getResearch(categoryId, finalistId).then(setData, (e: Error) => setError(e.message));
  }, [categoryId, finalistId]);
  useEffect(load, [load]);
  useEffect(() => {
    api.me().then(setMe, () => setMe(null));
  }, []);

  const run = data?.latest_run;
  const active = run?.status === "queued" || run?.status === "running";
  useEffect(() => {
    if (!active) return;
    const timer = setInterval(load, 4000);
    return () => clearInterval(timer);
  }, [active, load]);

  async function start() {
    setBusy(true);
    setError(null);
    try {
      await api.startResearch(categoryId, finalistId);
      load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (!data) return null;
  const canReview = me?.permissions.review_claims ?? false;
  const pending = data.findings.filter((f) => f.reviewer_outcome === "pending");
  const reviewed = data.findings.filter((f) => f.reviewer_outcome !== "pending");

  return (
    <section className="card">
      <div className="toolbar">
        <h2 style={{ margin: 0 }}>Public sources</h2>
        {data.research.enabled && canReview && (
          <button onClick={start} disabled={busy || active}>
            {active ? "Researching…" : run ? "Research again" : "Research public sources"}
          </button>
        )}
      </div>
      <p className="muted small" style={{ marginTop: 0 }}>
        Credible public sources (registries, regulators, organisation sites, annual reports, news)
        that confirm or contradict the claims. Each quote was checked against the page as fetched.
        Nothing counts as evidence until a reviewer accepts it.
      </p>
      {!data.research.enabled && (
        <div className="notice warning">External research is off: {data.research.reason}</div>
      )}
      {error && <div className="notice error">{error}</div>}

      {run && (
        <div className="muted small run-summary">
          {active && <span className="spinner" aria-hidden />}
          {run.status === "succeeded" &&
            `Researched ${formatDate(run.completed_at!)} · ${run.searches} searches · ` +
              `${run.pages_fetched} pages read · ${run.findings_created} findings`}
          {run.status === "queued" && "Queued for research…"}
          {run.status === "running" && "Searching public sources…"}
          {run.status === "failed" && <span className="error-text">Research failed: {run.error}</span>}
        </div>
      )}

      {run?.status === "succeeded" && run.identity_concerns.length > 0 && (
        <div className="notice warning">
          <strong>Possible namesakes</strong>
          <ul>
            {run.identity_concerns.map((c) => (
              <li key={c}>{c}</li>
            ))}
          </ul>
        </div>
      )}

      {pending.length > 0 && <h3 className="subhead">Awaiting review ({pending.length})</h3>}
      {pending.map((s) => (
        <SourceCard key={s.id} source={s} canReview={canReview} onChanged={load} />
      ))}
      {reviewed.length > 0 && <h3 className="subhead">Reviewed</h3>}
      {reviewed.map((s) => (
        <SourceCard key={s.id} source={s} canReview={false} onChanged={load} />
      ))}

      {run?.status === "succeeded" && run.not_found.length > 0 && (
        <div className="notice">
          <strong>No public trace found for {run.not_found.length} claim(s).</strong> This is
          neutral: board work is often confidential, and absence online does not count against a
          nominee.
        </div>
      )}
      {run?.status === "succeeded" && run.discarded.length > 0 && (
        <div className="small">
          <button className="link" onClick={() => setShowDiscarded(!showDiscarded)}>
            {showDiscarded ? "Hide" : "Show"} {run.discarded.length} unverifiable finding
            {run.discarded.length === 1 ? "" : "s"}
          </button>
          {showDiscarded && (
            <ul className="muted">
              {run.discarded.map((d, i) => (
                <li key={i}>
                  {d.url} — <em>{d.reason}</em>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </section>
  );
}
