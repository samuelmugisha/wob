"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import AssessmentPanel from "@/components/AssessmentPanel";
import ClaimsPanel from "@/components/ClaimsPanel";
import ConsentPanel from "@/components/ConsentPanel";
import DataRightsPanel from "@/components/DataRightsPanel";
import DocumentTable from "@/components/DocumentTable";
import EvidenceSearch from "@/components/EvidenceSearch";
import { IconArrow, IconChevron, IconDocument, IconFolder, IconLink, IconShield } from "@/components/Icons";
import ResearchPanel from "@/components/ResearchPanel";
import UploadPanel from "@/components/UploadPanel";
import {
  api,
  type Category,
  type CategoryRankings,
  type ClaimsResponse,
  type DocumentRecord,
  type Finalist,
  IN_PROGRESS_STATUSES,
  initials,
  type Me,
  type ResearchResponse,
} from "@/lib/api";

const TABS = [
  { id: "overview", label: "Overview" },
  { id: "summary", label: "AI Evidence Summary" },
  { id: "documents", label: "Supporting Documents" },
  { id: "claims", label: "Claims & Verification" },
  { id: "research", label: "External Research" },
] as const;
type TabId = (typeof TABS)[number]["id"];

function ScoreCircle({ score }: { score: string | null }) {
  return (
    <div className="score-circle" aria-label={score ? `Overall score ${score} out of 5` : "No overall score"}>
      <span>{score ?? "—"}</span>
    </div>
  );
}

function scoreWords(score: number): string {
  if (score >= 4.5) return "Exceptional, well-evidenced across the criteria.";
  if (score >= 3.5) return "Strong evidence across the criteria.";
  if (score >= 2.5) return "Adequate evidence across the criteria.";
  if (score >= 1.5) return "Weak evidence across the criteria.";
  return "Little evidence for the criteria.";
}

function EvidenceSummary({
  categoryId,
  finalistId,
  rankings,
  documents,
}: {
  categoryId: string;
  finalistId: string;
  rankings: CategoryRankings | null;
  documents: DocumentRecord[] | null;
}) {
  const [claims, setClaims] = useState<ClaimsResponse | null>(null);
  const [research, setResearch] = useState<ResearchResponse | null>(null);
  useEffect(() => {
    api.listClaims(categoryId, finalistId).then(setClaims, () => setClaims(null));
    api.getResearch(categoryId, finalistId).then(setResearch, () => setResearch(null));
  }, [categoryId, finalistId]);

  const ranking = rankings?.hidden_for_calibration ? null : rankings?.ranking;
  const entry = ranking?.entries.find((e) => e.finalist_id === finalistId) ?? null;
  const active = (documents ?? []).filter((d) => !d.withdrawn_at);
  const accepted = research?.findings.filter((f) => f.reviewer_outcome === "accepted").length ?? 0;

  return (
    <>
      <div className="summary-grid">
        <section className="card">
          <h2>Evidence by Criteria</h2>
          {rankings?.hidden_for_calibration ? (
            <div className="notice warning small">Hidden while you take part in a calibration study for this category.</div>
          ) : !entry || !ranking ? (
            <div className="empty small">No ranking has been calculated for this finalist yet.</div>
          ) : (
            <ul className="criteria-bars">
              {ranking.criteria.map((c) => {
                const value = entry.ratings[c.code] ?? null;
                return (
                  <li key={c.id}>
                    <span className="crit-name" title={c.description}>
                      {c.name}
                    </span>
                    <span className="crit-track">
                      <span className="crit-fill" style={{ width: `${((value ?? 0) / 5) * 100}%` }} />
                    </span>
                    <span className="crit-value">{value ?? "—"}</span>
                  </li>
                );
              })}
            </ul>
          )}
          {ranking && !ranking.production && (
            <p className="muted small">Practice ranking: the rubric is not frozen yet.</p>
          )}
        </section>

        <div className="summary-side">
          <section className="card">
            <h2>Overall AI Score</h2>
            <div className="overall">
              <ScoreCircle score={entry?.score_display ?? null} />
              <div className="small">
                <div className="muted">/ 5{entry?.rank ? ` · rank ${entry.rank}${entry.is_tie ? " (tie)" : ""}` : ""}</div>
                {entry?.score ? scoreWords(Number(entry.score)) : "Not scored yet."}
              </div>
            </div>
          </section>
          <section className="card">
            <h2>Key Evidence Sources</h2>
            <ul className="source-list">
              <li>
                <IconDocument size={16} /> Nomination forms ({active.filter((d) => d.source_type === "nomination_form").length})
              </li>
              <li>
                <IconFolder size={16} /> Supporting documents ({active.filter((d) => d.source_type === "supporting_document").length})
              </li>
              <li>
                <IconLink size={16} /> External sources accepted ({accepted})
              </li>
              <li>
                <IconShield size={16} /> Claims verified ({claims?.verification.reviewed ?? 0} of {claims?.verification.total ?? 0})
              </li>
            </ul>
          </section>
        </div>
      </div>
      <AssessmentPanel categoryId={categoryId} finalistId={finalistId} />
    </>
  );
}

export default function CandidatePage() {
  const { categoryId, finalistId } = useParams<{ categoryId: string; finalistId: string }>();
  const [category, setCategory] = useState<Category | null>(null);
  const [finalist, setFinalist] = useState<Finalist | null>(null);
  const [siblings, setSiblings] = useState<Finalist[]>([]);
  const [rankings, setRankings] = useState<CategoryRankings | null>(null);
  const [documents, setDocuments] = useState<DocumentRecord[] | null>(null);
  const [showWithdrawn, setShowWithdrawn] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [me, setMe] = useState<Me | null>(null);
  const [tab, setTab] = useState<TabId>("overview");

  useEffect(() => {
    const fromHash = window.location.hash.slice(1) as TabId;
    if (TABS.some((t) => t.id === fromHash)) setTab(fromHash);
  }, []);
  function choose(id: TabId) {
    setTab(id);
    history.replaceState(null, "", `#${id}`);
  }

  const loadDocuments = useCallback(() => {
    api
      .listDocuments(categoryId, finalistId, showWithdrawn)
      .then(setDocuments, (e: Error) => setError(e.message));
  }, [categoryId, finalistId, showWithdrawn]);

  useEffect(() => {
    api.getCategory(categoryId).then(setCategory, (e: Error) => setError(e.message));
    api.getFinalist(categoryId, finalistId).then(setFinalist, (e: Error) => setError(e.message));
    api.listFinalists(categoryId).then(setSiblings, () => setSiblings([]));
    api.categoryRankings(categoryId).then(setRankings, () => setRankings(null));
  }, [categoryId, finalistId]);
  useEffect(loadDocuments, [loadDocuments]);
  useEffect(() => {
    api.me().then(setMe, () => setMe(null));
  }, []);

  // Refresh while the worker is still processing any document.
  const processing = documents?.some(
    (d) => !d.withdrawn_at && IN_PROGRESS_STATUSES.includes(d.processing_status),
  );
  useEffect(() => {
    if (!processing) return;
    const timer = setInterval(loadDocuments, 3000);
    return () => clearInterval(timer);
  }, [processing, loadDocuments]);

  const entry = rankings?.hidden_for_calibration
    ? null
    : rankings?.ranking?.entries.find((e) => e.finalist_id === finalistId) ?? null;
  const index = siblings.findIndex((s) => s.id === finalistId);
  const prev = index > 0 ? siblings[index - 1] : null;
  const next = index >= 0 && index < siblings.length - 1 ? siblings[index + 1] : null;
  const href = (f: Finalist) => `/categories/${categoryId}/finalists/${f.id}${tab === "overview" ? "" : `#${tab}`}`;

  return (
    <>
      <nav className="breadcrumb">
        <Link href="/finalists">Finalists</Link>
        <span>/</span>
        <Link href={`/categories/${categoryId}`}>{category?.name ?? "…"}</Link>
        <span>/</span>
        <span>{finalist?.full_name ?? "…"}</span>
      </nav>

      <section className="card profile-card">
        <div className="profile-head">
          <span className="avatar large">{finalist ? initials(finalist.full_name) : ""}</span>
          <div className="profile-text">
            <div className="profile-name">
              <h1>{finalist?.full_name ?? "Loading…"}</h1>
              {entry?.rank && (
                <span className="rank-badge">
                  AI Rank #{entry.rank}
                  {entry.is_tie ? " (tie)" : ""}
                </span>
              )}
            </div>
            {category && (
              <Link href={`/categories/${categoryId}`} className="profile-category">
                <IconFolder size={16} /> {category.name}
              </Link>
            )}
            {(finalist?.position_title || finalist?.organisation) && (
              <div className="muted small">
                {[finalist?.position_title, finalist?.organisation].filter(Boolean).join(", ")}
              </div>
            )}
          </div>
          <div className="profile-nav">
            {prev ? (
              <Link href={href(prev)} className="pager">
                <IconChevron dir="left" size={14} /> Previous
              </Link>
            ) : (
              <span className="pager disabled">
                <IconChevron dir="left" size={14} /> Previous
              </span>
            )}
            {next ? (
              <Link href={href(next)} className="pager">
                Next <IconChevron size={14} />
              </Link>
            ) : (
              <span className="pager disabled">
                Next <IconChevron size={14} />
              </span>
            )}
          </div>
        </div>
        <div className="tabs" role="tablist">
          {TABS.map((t) => (
            <button
              key={t.id}
              role="tab"
              aria-selected={tab === t.id}
              className={`tab${tab === t.id ? " active" : ""}`}
              onClick={() => choose(t.id)}
            >
              {t.label}
            </button>
          ))}
        </div>
      </section>

      {error && <div className="notice error">{error}</div>}

      {tab === "overview" && (
        <>
          <section className="card">
            <h2>Nomination</h2>
            <dl className="facts">
              <div>
                <dt>Category</dt>
                <dd>{category?.name ?? "…"}</dd>
              </div>
              <div>
                <dt>Position</dt>
                <dd>{finalist?.position_title ?? "—"}</dd>
              </div>
              <div>
                <dt>Organisation</dt>
                <dd>{finalist?.organisation ?? "—"}</dd>
              </div>
              <div>
                <dt>Documents</dt>
                <dd>{finalist?.document_count ?? "…"}</dd>
              </div>
              <div>
                <dt>Claims verified</dt>
                <dd>{finalist ? `${finalist.claims_reviewed} of ${finalist.claims_total}` : "…"}</dd>
              </div>
              <div>
                <dt>Overall AI score</dt>
                <dd>{entry?.score_display ? `${entry.score_display} / 5` : "—"}</dd>
              </div>
            </dl>
            {finalist?.eligibility_flagged && <div className="notice warning">Eligibility has been flagged for review.</div>}
            <button className="link" onClick={() => choose("summary")}>
              View the AI evidence summary <IconArrow size={14} />
            </button>
          </section>
          <ConsentPanel
            categoryId={categoryId}
            finalistId={finalistId}
            me={me}
            onChanged={() => api.getFinalist(categoryId, finalistId).then(setFinalist)}
          />
          {finalist && <DataRightsPanel categoryId={categoryId} finalistId={finalistId} name={finalist.full_name} me={me} />}
        </>
      )}

      {tab === "summary" && (
        <EvidenceSummary categoryId={categoryId} finalistId={finalistId} rankings={rankings} documents={documents} />
      )}

      {tab === "documents" && (
        <>
          <UploadPanel categoryId={categoryId} finalistId={finalistId} onUploaded={loadDocuments} />
          <section className="card">
            <div className="toolbar">
              <h2 style={{ margin: 0 }}>Documents</h2>
              <label>
                <input type="checkbox" checked={showWithdrawn} onChange={(e) => setShowWithdrawn(e.target.checked)} />
                Show withdrawn
              </label>
            </div>
            {documents === null ? (
              <p className="muted">Loading…</p>
            ) : (
              <DocumentTable documents={documents} onChanged={loadDocuments} />
            )}
          </section>
          <EvidenceSearch categoryId={categoryId} finalistId={finalistId} />
        </>
      )}

      {tab === "claims" && <ClaimsPanel categoryId={categoryId} finalistId={finalistId} />}

      {tab === "research" && <ResearchPanel categoryId={categoryId} finalistId={finalistId} />}
    </>
  );
}
