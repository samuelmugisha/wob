"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import CalibrationPanel from "@/components/CalibrationPanel";
import RankingPanel from "@/components/RankingPanel";
import RetentionPanel from "@/components/RetentionPanel";
import ReportsPanel from "@/components/ReportsPanel";
import RubricPanel from "@/components/RubricPanel";
import { api, type Category, type CategoryRankings, type Finalist, type Me } from "@/lib/api";

export default function CategoryPage() {
  const { categoryId } = useParams<{ categoryId: string }>();
  const [category, setCategory] = useState<Category | null>(null);
  const [finalists, setFinalists] = useState<Finalist[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [rankings, setRankings] = useState<CategoryRankings | null>(null);
  const [me, setMe] = useState<Me | null>(null);

  const load = useCallback(() => {
    api.getCategory(categoryId).then(setCategory, (e: Error) => setError(e.message));
    api.listFinalists(categoryId).then(setFinalists, (e: Error) => setError(e.message));
  }, [categoryId]);
  useEffect(load, [load]);

  const loadRankings = useCallback(() => {
    api.categoryRankings(categoryId).then(setRankings, (e: Error) => setError(e.message));
  }, [categoryId]);
  useEffect(loadRankings, [loadRankings]);
  useEffect(() => {
    api.me().then(setMe, () => setMe(null));
  }, []);

  return (
    <>
      <nav className="breadcrumb">
        <Link href="/categories">Categories</Link>
        <span>›</span>
        <span>{category?.name ?? "…"}</span>
      </nav>
      <div className="page-head">
        <div>
          <h1>{category?.name ?? "Loading…"}</h1>
          {category?.description && <p className="muted" style={{ margin: 0 }}>{category.description}</p>}
        </div>
        <div className="inline-form">
          {category && me?.permissions.manage_users && (
            <button
              className="secondary"
              onClick={() =>
                api
                  .setCategoryVisibility(categoryId, !category.hidden_at)
                  .then(setCategory, (e: Error) => setError(e.message))
              }
            >
              {category.hidden_at ? "Show category" : "Hide category"}
            </button>
          )}
          {!showForm && <button onClick={() => setShowForm(true)}>Add candidate</button>}
        </div>
      </div>

      {category?.hidden_at && (
        <div className="notice warning">
          This category is hidden: it doesn&apos;t appear in lists, the dashboard, rankings or the judges&apos; pack.
          Nothing in it has been changed or deleted.
        </div>
      )}

      {showForm && (
        <AddCandidateForm
          categoryId={categoryId}
          onCancel={() => setShowForm(false)}
          onAdded={() => {
            setShowForm(false);
            load();
          }}
        />
      )}

      {error && <div className="notice error">{error}</div>}

      <section className="card">
        <h2>Shortlisted candidates</h2>
        {finalists === null && !error && <p className="muted">Loading…</p>}
        {finalists?.length === 0 && (
          <div className="empty">No candidates in this category yet. Add the shortlisted finalists.</div>
        )}
        {finalists && finalists.length > 0 && (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Candidate</th>
                  <th>Organisation</th>
                  <th>Documents</th>
                  <th>Consent</th>
                  <th>Claims reviewed</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {finalists.map((f) => (
                  <tr key={f.id}>
                    <td>
                      <Link href={`/categories/${categoryId}/finalists/${f.id}`}>{f.full_name}</Link>
                      {f.position_title && <div className="muted small">{f.position_title}</div>}
                      {f.eligibility_flagged && <span className="badge warning">Eligibility flagged</span>}
                    </td>
                    <td>{f.organisation ?? <span className="muted">—</span>}</td>
                    <td>
                      {f.document_count === 0 ? (
                        <span className="badge warning">No documents</span>
                      ) : (
                        f.document_count
                      )}
                    </td>
                    <td className="small">
                      {f.consent === null ? (
                        <span className="badge warning">None recorded</span>
                      ) : !f.consent.assessment ? (
                        <span className="badge danger">Withdrawn</span>
                      ) : (
                        <span className={`badge${f.consent.ai_processing ? " success" : " muted"}`}>
                          {f.consent.ai_processing ? "AI + human" : "Human only"}
                        </span>
                      )}
                    </td>
                    <td>
                      {f.claims_total === 0 ? (
                        <span className="muted">—</span>
                      ) : (
                        <span className={`badge${f.claims_reviewed === f.claims_total ? " success" : " muted"}`}>
                          {f.claims_reviewed} / {f.claims_total}
                        </span>
                      )}
                    </td>
                    <td style={{ textAlign: "right" }}>
                      <Link href={`/categories/${categoryId}/finalists/${f.id}`}>Upload / view →</Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {rankings && (
        <>
          <RubricPanel
            categoryId={categoryId}
            rubric={rankings.working_rubric ?? rankings.rubric}
            inUse={rankings.working_rubric ? rankings.rubric : null}
            me={me}
            onChanged={loadRankings}
          />
          <RankingPanel categoryId={categoryId} data={rankings} me={me} onChanged={loadRankings} />
          <ReportsPanel categoryId={categoryId} ranking={rankings.ranking} me={me} />
          <RetentionPanel categoryId={categoryId} me={me} />
          <CalibrationPanel
            categoryId={categoryId}
            me={me}
            hasRun={rankings.latest_run?.status === "succeeded" || rankings.hidden_for_calibration}
          />
        </>
      )}
    </>
  );
}

function AddCandidateForm({
  categoryId,
  onAdded,
  onCancel,
}: {
  categoryId: string;
  onAdded: () => void;
  onCancel: () => void;
}) {
  const [fullName, setFullName] = useState("");
  const [organisation, setOrganisation] = useState("");
  const [position, setPosition] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.addFinalist(categoryId, {
        full_name: fullName.trim(),
        organisation: organisation.trim() || undefined,
        position_title: position.trim() || undefined,
      });
      onAdded();
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  }

  return (
    <form className="card" onSubmit={submit}>
      <h2>Add shortlisted candidate</h2>
      <div className="form-row">
        <div className="field">
          <label htmlFor="f-name">Full name</label>
          <input id="f-name" value={fullName} onChange={(e) => setFullName(e.target.value)} autoFocus required />
        </div>
        <div className="field">
          <label htmlFor="f-org">Organisation (optional)</label>
          <input id="f-org" value={organisation} onChange={(e) => setOrganisation(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="f-pos">Position (optional)</label>
          <input id="f-pos" value={position} onChange={(e) => setPosition(e.target.value)} />
        </div>
        <button type="submit" disabled={busy}>{busy ? "Adding…" : "Add"}</button>
        <button type="button" className="secondary" onClick={onCancel}>Cancel</button>
      </div>
      {error && <div className="notice error">{error}</div>}
    </form>
  );
}
