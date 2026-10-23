"use client";

import { useCallback, useEffect, useState } from "react";
import { api, type Claim, type ClaimsResponse, formatDate, type Me } from "@/lib/api";
import ClaimReview, { STATUS_LABELS, statusTone } from "./ClaimReview";

const TYPE_LABELS: Record<string, string> = {
  position: "Positions",
  achievement: "Achievements",
  outcome: "Outcomes",
  award: "Awards",
  qualification: "Qualifications",
  membership: "Memberships",
  advocacy: "Advocacy and mentoring",
  other: "Other",
};

function formatPeriodDate(value: string | null, precision: string | null): string | null {
  if (!value) return null;
  const [y, m, d] = value.split("-");
  if (precision === "year") return y;
  const month = new Date(Number(y), Number(m) - 1).toLocaleString(undefined, { month: "short" });
  return precision === "month" ? `${month} ${y}` : `${Number(d)} ${month} ${y}`;
}

function period(c: Claim): string | null {
  const start = formatPeriodDate(c.period_start, c.period_start_precision);
  const end = formatPeriodDate(c.period_end, c.period_end_precision);
  if (start && end) return `${start} – ${end}`;
  if (start) return `${start} –`;
  return c.period_text;
}

function Source({ q }: { q: { document_id: string | null; filename: string | null; page: number | null } }) {
  if (!q.document_id) return null;
  return (
    <a href={api.downloadUrl(q.document_id)} className="small">
      {q.filename}
      {q.page ? `, p. ${q.page}` : ""}
    </a>
  );
}

function ResolveContradiction({ runId, index, onResolved }: {
  runId: string;
  index: number;
  onResolved: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    try {
      await api.resolveContradiction(runId, index, text.trim());
      setOpen(false);
      onResolved();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  if (!open) {
    return (
      <button className="link small" onClick={() => setOpen(true)}>
        Record resolution
      </button>
    );
  }
  return (
    <form onSubmit={submit}>
      <div className="inline-form">
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="How it was resolved, and from which source"
          minLength={3}
          required
          autoFocus
        />
        <button type="submit">Save</button>
        <button type="button" className="secondary" onClick={() => setOpen(false)}>
          Cancel
        </button>
      </div>
      {error && <div className="notice error">{error}</div>}
    </form>
  );
}

/** Claims extracted from the candidate's evidence (FR-06) and their verification (FR-07). */
export default function ClaimsPanel({ categoryId, finalistId }: { categoryId: string; finalistId: string }) {
  const [data, setData] = useState<ClaimsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [showDiscarded, setShowDiscarded] = useState(false);
  const [onlyUnreviewed, setOnlyUnreviewed] = useState(false);
  const [me, setMe] = useState<Me | null>(null);

  useEffect(() => {
    api.me().then(setMe, () => setMe(null));
  }, []);
  const canReview = me?.permissions.review_claims ?? false;
  const canExtract = me?.permissions.manage_evidence ?? false;

  const load = useCallback(() => {
    api.listClaims(categoryId, finalistId).then(setData, (e: Error) => setError(e.message));
  }, [categoryId, finalistId]);
  useEffect(load, [load]);

  const run = data?.latest_run;
  const active = run?.status === "queued" || run?.status === "running";
  useEffect(() => {
    if (!active) return;
    const timer = setInterval(load, 3000);
    return () => clearInterval(timer);
  }, [active, load]);

  async function extract() {
    const reviewed = data?.verification.reviewed ?? 0;
    if (
      reviewed > 0 &&
      !window.confirm(
        `${reviewed} claim(s) have been reviewed. Re-extracting replaces all claims: reviews ` +
          "carry over only to identical claims that are not contradicted; the rest will need " +
          "reviewing again. Continue?",
      )
    ) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const result = await api.extractClaims(categoryId, finalistId);
      setWarnings(result.warnings);
      load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (!data) {
    return (
      <section className="card">
        <h2>Claims</h2>
        {error ? <div className="notice error">{error}</div> : <p className="muted">Loading…</p>}
      </section>
    );
  }

  function replaceClaim(updated: Claim) {
    setData((current) =>
      current && { ...current, claims: current.claims.map((c) => (c.id === updated.id ? updated : c)) },
    );
    load(); // refresh the summary counts
  }

  const groups = new Map<string, Claim[]>();
  const visible = onlyUnreviewed ? data.claims.filter((c) => !c.latest_review) : data.claims;
  for (const c of visible) {
    const key = c.claim_type ?? "other";
    groups.set(key, [...(groups.get(key) ?? []), c]);
  }
  const discardedClaims = run?.discarded.filter((d) => d.kind === "claim") ?? [];

  return (
    <section className="card">
      <div className="toolbar">
        <h2 style={{ margin: 0 }}>Claims</h2>
        {data.extraction.enabled && canExtract && (
          <button onClick={extract} disabled={busy || active}>
            {active ? "Extracting…" : data.claims.length ? "Re-extract claims" : "Extract claims"}
          </button>
        )}
      </div>
      <p className="muted small" style={{ marginTop: 0 }}>
        Factual claims found in this candidate&apos;s indexed evidence. Every quote has been checked
        against the source; claims without a verifiable quote are discarded. Under the jury&apos;s decision,
        claims a supporting document backs are verified automatically; the rest start unverified until a
        reviewer checks them.
      </p>

      {!data.extraction.enabled && (
        <div className="notice warning">Claim extraction is off: {data.extraction.reason}</div>
      )}
      {error && <div className="notice error">{error}</div>}
      {warnings.map((w) => (
        <div key={w} className="notice warning">
          {w}
        </div>
      ))}

      {run && (
        <div className="muted small run-summary">
          {active && <span className="spinner" aria-hidden />}
          {run.status === "succeeded" &&
            `Extracted ${formatDate(run.completed_at!)} · ${run.claims_created} claims · ` +
              `${run.served_by_models.join(", ") || run.llm_model} · ${run.prompt_version}` +
              (run.claims_carried_forward
                ? ` · ${run.claims_carried_forward} review(s) carried forward`
                : "")}
          {run.status === "queued" && "Queued for extraction…"}
          {run.status === "running" && "Reading the evidence and extracting claims…"}
          {run.status === "failed" && (
            <span className="error-text">
              Extraction failed: {run.error}
              {run.next_attempt_at && ` Retrying at ${formatDate(run.next_attempt_at)}.`}
            </span>
          )}
        </div>
      )}

      {data.verification.total > 0 && (
        <div className="verification-summary">
          <div>
            <strong>
              {data.verification.reviewed} of {data.verification.total}
            </strong>{" "}
            claims reviewed
            <progress value={data.verification.reviewed} max={data.verification.total} />
          </div>
          <div className="small">
            {(Object.keys(STATUS_LABELS) as Claim["status"][])
              .filter((s) => data.verification.by_status[s] > 0)
              .map((s) => (
                <span key={s} className={`badge${statusTone(s)}`}>
                  {STATUS_LABELS[s]}: {data.verification.by_status[s]}
                </span>
              ))}
            {data.verification.unresolved_contradictions > 0 && (
              <span className="badge warning">
                {data.verification.unresolved_contradictions} unresolved contradiction
                {data.verification.unresolved_contradictions === 1 ? "" : "s"}
              </span>
            )}
          </div>
          <label className="small muted">
            <input
              type="checkbox"
              checked={onlyUnreviewed}
              onChange={(e) => setOnlyUnreviewed(e.target.checked)}
            />{" "}
            Only claims not yet reviewed
          </label>
        </div>
      )}

      {run?.status === "succeeded" && run.contradictions.length > 0 && (
        <div className="notice warning">
          <strong>Contradictions for reviewers to resolve</strong>
          <ul>
            {run.contradictions.map((c, i) => {
              const resolution = run.contradiction_resolutions[String(i)];
              return (
                <li key={i}>
                  {c.description}
                  <ul>
                    {c.evidence.map((e, j) => (
                      <li key={j}>
                        “{e.quote}” — <Source q={e} />
                      </li>
                    ))}
                  </ul>
                  {resolution ? (
                    <div className="resolution">
                      ✓ Resolved by {resolution.resolved_by}, {formatDate(resolution.created_at)}:{" "}
                      {resolution.resolution}
                    </div>
                  ) : (
                    canReview && <ResolveContradiction runId={run.id} index={i} onResolved={load} />
                  )}
                </li>
              );
            })}
          </ul>
        </div>
      )}

      {run?.status === "succeeded" && run.missing_information.length > 0 && (
        <div className="notice">
          <strong>Not found in the evidence</strong>
          <ul>
            {run.missing_information.map((m) => (
              <li key={m}>{m}</li>
            ))}
          </ul>
        </div>
      )}

      {[...groups.entries()].map(([type, claims]) => (
        <div key={type} className="claim-group">
          <h3>{TYPE_LABELS[type] ?? type}</h3>
          {claims.map((c) => (
            <article key={c.id} className="claim">
              <div className="claim-head">
                <span>{c.statement}</span>
                <span className={`badge${statusTone(c.status)}`}>
                  {STATUS_LABELS[c.status]}
                </span>
              </div>
              <div className="muted small">
                {[c.role, c.entity, period(c)].filter(Boolean).join(" · ")}
                {c.independent_sources > 1 && ` · ${c.independent_sources} independent sources`}
              </div>
              {c.quantitative_outcomes.length > 0 && (
                <div className="small">
                  {c.quantitative_outcomes
                    .map((o) => `${o.metric}: ${o.value}${o.unit ? ` ${o.unit}` : ""}`)
                    .join(" · ")}
                </div>
              )}
              {c.limitations && <div className="small warning-text">⚠ {c.limitations}</div>}
              <ul className="quotes">
                {c.evidence.map((e, i) => (
                  <li key={i} className={e.relation === "contradicts" ? "contradicts" : undefined}>
                    {e.relation === "contradicts" && <strong>Contradicted by: </strong>}“{e.quote}” —{" "}
                    {e.url ? (
                      <a href={e.url} target="_blank" rel="noopener noreferrer" className="small">
                        {e.publisher} (public source)
                      </a>
                    ) : (
                      <Source q={e} />
                    )}
                    {e.document_withdrawn && <span className="warning-text small"> (document withdrawn)</span>}
                  </li>
                ))}
              </ul>
              <ClaimReview claim={c} canReview={canReview} onReviewed={replaceClaim} />
            </article>
          ))}
        </div>
      ))}

      {run?.status === "succeeded" && discardedClaims.length > 0 && (
        <div className="small">
          <button className="link" onClick={() => setShowDiscarded(!showDiscarded)}>
            {showDiscarded ? "Hide" : "Show"} {discardedClaims.length} discarded claim
            {discardedClaims.length === 1 ? "" : "s"}
          </button>
          {showDiscarded && (
            <ul className="muted">
              {discardedClaims.map((d, i) => (
                <li key={i}>
                  {d.statement} — <em>{d.reason}</em>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </section>
  );
}
