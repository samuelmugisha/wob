"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import {
  IconArrow,
  IconBook,
  IconCheck,
  IconChevron,
  IconClipboard,
  IconDocument,
  IconDownload,
  IconInfo,
  IconPeople,
  IconPerson,
  IconSparkle,
} from "@/components/Icons";
import { api, type Dashboard } from "@/lib/api";

function StatCard({
  icon,
  label,
  value,
  note,
}: {
  icon: React.ReactNode;
  label: string;
  value: React.ReactNode;
  note: string;
}) {
  return (
    <div className="stat-card">
      <span className="stat-icon">{icon}</span>
      <div>
        <div className="stat-label">{label}</div>
        <div className="stat-value">{value}</div>
        <div className="stat-note">{note}</div>
      </div>
    </div>
  );
}

function CategoryChart({ data }: { data: Dashboard["by_category"] }) {
  const max = Math.max(1, ...data.map((c) => c.finalists));
  if (data.length === 0) return <div className="empty">No award categories yet.</div>;
  return (
    <div className="bar-chart" role="img" aria-label="Finalists in each award category">
      {data.map((c, i) => (
        <Link key={c.id} href={`/categories/${c.id}`} className="bar-col" title={`${c.name}: ${c.finalists} finalists`}>
          <span className="bar-value">{c.finalists}</span>
          <span className="bar-track">
            <span className={`bar${i % 2 ? " gold" : ""}`} style={{ height: `${(c.finalists / max) * 100}%` }} />
          </span>
          <span className="bar-label">{c.name}</span>
        </Link>
      ))}
    </div>
  );
}

function ProgressRing({ value }: { value: number }) {
  const r = 52;
  const c = 2 * Math.PI * r;
  return (
    <svg viewBox="0 0 128 128" className="ring" role="img" aria-label={`${value}% complete`}>
      <circle cx="64" cy="64" r={r} className="ring-track" />
      <circle
        cx="64"
        cy="64"
        r={r}
        className="ring-value"
        strokeDasharray={`${(c * value) / 100} ${c}`}
        transform="rotate(-90 64 64)"
      />
      <text x="64" y="64" className="ring-text" dominantBaseline="central" textAnchor="middle">
        {value}%
      </text>
    </svg>
  );
}

export default function DashboardPage() {
  const [data, setData] = useState<Dashboard | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.dashboard().then(setData, (e: Error) => setError(e.message));
  }, []);

  if (error) return <div className="notice error">{error}</div>;
  if (!data) return <p className="muted">Loading…</p>;

  const p = data.progress;
  const total = p.nominations;
  const steps = [
    { label: "Documents ingested", done: p.documents_indexed },
    { label: "Evidence extracted by AI", done: p.evidence_extracted },
    { label: "AI ratings completed", done: p.assessed },
    { label: "Verification checks completed", done: p.claims_verified },
  ];
  const overall = total ? Math.round((steps.reduce((sum, s) => sum + s.done, 0) / (steps.length * total)) * 100) : 0;
  const ready = data.categories_with_finalists > 0 && data.categories_ranked === data.categories_with_finalists;

  return (
    <div className="dashboard">
      <div className="stat-grid">
        <StatCard
          icon={<IconPerson size={26} />}
          label="Finalists"
          value={data.finalists}
          note={`Across ${data.categories} award categor${data.categories === 1 ? "y" : "ies"}`}
        />
        <StatCard
          icon={<IconDocument size={26} />}
          label="Supporting Documents"
          value={data.documents}
          note="Nomination forms and evidence files"
        />
        <StatCard
          icon={<IconSparkle size={26} />}
          label="AI Evidence Extracted"
          value={p.evidence_extracted}
          note={`Of ${total} nomination${total === 1 ? "" : "s"}, from all sources`}
        />
        <StatCard
          icon={<IconPeople size={26} />}
          label="Ready for Deliberation"
          value={ready ? "Yes" : "Not yet"}
          note={`${data.categories_ranked} of ${data.categories_with_finalists} categories ranked`}
        />
      </div>

      <div className="dash-grid">
        <section className="card">
          <h2>Finalists by Award Category</h2>
          <CategoryChart data={data.by_category} />
        </section>

        <section className="card">
          <h2>AI Ranking Progress</h2>
          <div className="progress-panel">
            <ProgressRing value={overall} />
            <ul className="progress-steps">
              {steps.map((s) => {
                const complete = total > 0 && s.done === total;
                return (
                  <li key={s.label}>
                    <span className={`step-check${complete ? " done" : ""}`}>{complete && <IconCheck size={12} />}</span>
                    <span>{s.label}</span>
                    <span className="step-count">
                      {s.done}/{total}
                    </span>
                  </li>
                );
              })}
            </ul>
          </div>
        </section>

        <section className="card">
          <div className="card-head">
            <h2>
              Top AI-Ranked Finalists <span className="muted">(Preview)</span>{" "}
              <span
                className="info"
                title="Highest provisional scores across categories, from each category's latest ranking. Advisory only: the committee decides."
              >
                <IconInfo size={16} />
              </span>
            </h2>
            <Link href="/rankings" className="text-link">
              View All Rankings <IconArrow size={16} />
            </Link>
          </div>
          {data.rankings_hidden > 0 && (
            <div className="notice warning small">
              Rankings for {data.rankings_hidden} categor{data.rankings_hidden === 1 ? "y are" : "ies are"} hidden while
              you take part in a calibration study.
            </div>
          )}
          {data.top_ranked.length === 0 ? (
            <div className="empty">No rankings calculated yet.</div>
          ) : (
            <div className="table-wrap">
              <table className="elegant">
                <thead>
                  <tr>
                    <th>Rank</th>
                    <th>Name</th>
                    <th>Category</th>
                    <th>AI Score</th>
                    <th>Key Strengths (top two levels)</th>
                  </tr>
                </thead>
                <tbody>
                  {data.top_ranked.map((t) => (
                    <tr key={`${t.category_id}-${t.finalist_id}`}>
                      <td>
                        {t.rank ?? "—"}
                        {t.is_tie && <span className="badge warning">tie</span>}
                      </td>
                      <td>
                        <Link href={`/categories/${t.category_id}/finalists/${t.finalist_id}`}>{t.full_name}</Link>
                      </td>
                      <td>
                        {t.category_name}
                        {!t.production && <span className="badge muted">practice</span>}
                      </td>
                      <td>
                        <strong>{t.score_display}</strong>
                        {t.score_display && <span className="muted"> / {t.scale_high}</span>}
                      </td>
                      <td className="muted">{t.strengths.length ? t.strengths.join(", ") : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <p className="muted small" style={{ marginBottom: 0 }}>
            Rank is within each finalist&apos;s own category.
          </p>
        </section>

        <section className="card">
          <h2>Quick Actions</h2>
          <div className="quick-actions">
            {[
              { href: "/finalists", icon: <IconPerson size={20} />, label: "View All Finalists" },
              { href: "/knowledge-base", icon: <IconBook size={20} />, label: "Open Knowledge Base" },
              { href: "/reports", icon: <IconDownload size={20} />, label: "Download Deliberation Reports" },
              { href: "/finalists?focus=verification", icon: <IconClipboard size={20} />, label: "Manage Verification" },
            ].map((a) => (
              <Link key={a.href} href={a.href} className="quick-action">
                <span className="qa-icon">{a.icon}</span>
                <span>{a.label}</span>
                <IconChevron size={18} />
              </Link>
            ))}
          </div>
        </section>
      </div>
    </div>
  );
}
