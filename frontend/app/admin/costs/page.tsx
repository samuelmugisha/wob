"use client";

import { useEffect, useState } from "react";
import { type AiCosts, api, type Category } from "@/lib/api";

const PERIODS: { days: number | null; label: string }[] = [
  { days: 7, label: "Last 7 days" },
  { days: 30, label: "Last 30 days" },
  { days: 90, label: "Last 90 days" },
  { days: null, label: "All time" },
];

// What to change when a step is the biggest share of the cost.
const HINTS: Record<string, string> = {
  web_search: "Fewer searches per research run (RESEARCH_MAX_SEARCHES) would lower it most.",
  research: "A cheaper research model or fewer pages per run (RESEARCH_MAX_FETCHES) would lower it most.",
  assessment: "Assessing only changed candidates, or a lower effort, would lower it most.",
  claims: "Re-extracting claims only when documents change would lower it most.",
};

function money(usd: number): string {
  if (usd === 0) return "$0";
  if (usd < 0.0001) return "<$0.0001";
  if (usd < 1) return `$${usd.toFixed(4)}`;
  return `$${usd.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

const tokens = (n: number) => n.toLocaleString();

/** Estimated AI spend per pipeline step, for administrators. */
export default function AiCostsPage() {
  const [days, setDays] = useState<number | null>(30);
  const [categoryId, setCategoryId] = useState("");
  const [categories, setCategories] = useState<Category[]>([]);
  const [data, setData] = useState<AiCosts | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [hovered, setHovered] = useState<string | null>(null);

  useEffect(() => {
    api.listCategories(true).then(setCategories, () => setCategories([]));
  }, []);
  useEffect(() => {
    setError(null);
    api.aiCosts(days, categoryId || null).then(setData, (e: Error) => setError(e.message));
  }, [days, categoryId]);

  const steps = data?.steps ?? [];
  const max = Math.max(0, ...steps.map((s) => s.cost_usd));
  const top = steps.find((s) => s.cost_usd === max && max > 0);
  const share = top && data && data.total_usd > 0 ? Math.round((top.cost_usd / data.total_usd) * 100) : 0;
  const period = PERIODS.find((p) => p.days === days)?.label.toLowerCase() ?? "";
  const category = categories.find((c) => c.id === categoryId)?.name;

  return (
    <>
      <div className="page-head">
        <div>
          <div className="eyebrow">Where the money went</div>
          <h1>AI costs</h1>
          <p className="muted" style={{ margin: 0 }}>
            Estimated spend per step of the pipeline, from the tokens and searches each job recorded.
          </p>
        </div>
      </div>

      <div className="filter-bar">
        <select value={days ?? ""} onChange={(e) => setDays(e.target.value ? Number(e.target.value) : null)} aria-label="Period">
          {PERIODS.map((p) => (
            <option key={p.label} value={p.days ?? ""}>
              {p.label}
            </option>
          ))}
        </select>
        <select value={categoryId} onChange={(e) => setCategoryId(e.target.value)} aria-label="Category">
          <option value="">All categories</option>
          {categories.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </select>
      </div>

      {error && <div className="notice error">{error}</div>}
      {!data && !error && <p className="muted">Loading…</p>}
      {data && (
        <>
          <section className="card">
            <h2 className="cost-title">
              Cost per step: {category ?? "all categories"}, {period}, {money(data.total_usd)} in total
            </h2>
            <div className="cost-chart" role="list">
              {steps.map((s) => {
                const width = max > 0 ? (s.cost_usd / max) * 100 : 0;
                const tokenTotal = s.input_tokens + s.cache_write_tokens + s.cache_read_tokens + s.output_tokens;
                return (
                  <div
                    key={s.key}
                    role="listitem"
                    tabIndex={0}
                    className="cost-row"
                    onMouseEnter={() => setHovered(s.key)}
                    onMouseLeave={() => setHovered(null)}
                    onFocus={() => setHovered(s.key)}
                    onBlur={() => setHovered(null)}
                    aria-label={`${s.label}: ${money(s.cost_usd)}, ${s.detail}`}
                  >
                    <div className="cost-label">
                      {s.label}
                      <span className="muted small"> ({s.detail})</span>
                    </div>
                    <div className="cost-track">
                      {width > 0 && (
                        <div
                          className={`cost-bar${s === top ? " top" : ""}`}
                          style={{ width: `max(${width}%, 4px)` }}
                        />
                      )}
                      {hovered === s.key && (
                        <div className="cost-tip" role="tooltip">
                          <strong>{s.label}</strong>
                          <div>{money(s.cost_usd)}</div>
                          {tokenTotal > 0 ? (
                            <div className="muted">
                              {tokens(s.input_tokens)} in · {tokens(s.cache_read_tokens)} cached ·{" "}
                              {tokens(s.cache_write_tokens)} cache writes · {tokens(s.output_tokens)} out
                            </div>
                          ) : (
                            <div className="muted">{s.detail}</div>
                          )}
                        </div>
                      )}
                    </div>
                    <div className="cost-value">{money(s.cost_usd)}</div>
                  </div>
                );
              })}
            </div>
            {top ? (
              <p style={{ marginBottom: 0 }}>
                {top.label} is about {share}% of the cost. {HINTS[top.key] ?? ""}
              </p>
            ) : (
              <p className="muted" style={{ marginBottom: 0 }}>
                No AI usage recorded for this period.
              </p>
            )}
          </section>

          <section className="card">
            <h2>Tokens per step</h2>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Step</th>
                    <th className="num">Input</th>
                    <th className="num">Cache reads</th>
                    <th className="num">Cache writes</th>
                    <th className="num">Output</th>
                    <th className="num">Estimated cost</th>
                  </tr>
                </thead>
                <tbody>
                  {steps.map((s) => (
                    <tr key={s.key}>
                      <td>
                        {s.label}
                        <div className="small muted">{s.detail}</div>
                      </td>
                      <td className="num">{tokens(s.input_tokens)}</td>
                      <td className="num">{tokens(s.cache_read_tokens)}</td>
                      <td className="num">{tokens(s.cache_write_tokens)}</td>
                      <td className="num">{tokens(s.output_tokens)}</td>
                      <td className="num">{money(s.cost_usd)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <section className="card">
            <h2>Prices used</h2>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Model (USD per million tokens)</th>
                    <th className="num">Input</th>
                    <th className="num">Cache reads</th>
                    <th className="num">Cache writes</th>
                    <th className="num">Output</th>
                  </tr>
                </thead>
                <tbody>
                  {data.prices.map((p) => (
                    <tr key={p.model}>
                      <td>{p.model}</td>
                      <td className="num">${p.input}</td>
                      <td className="num">${p.cache_read}</td>
                      <td className="num">${p.cache_write}</td>
                      <td className="num">${p.output}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="small muted">Web search: ${data.web_search_per_1000} per 1,000 searches. Web fetch: no fee beyond its tokens.</p>
            <ul className="small muted">
              {data.notes.map((n) => (
                <li key={n}>{n}</li>
              ))}
            </ul>
          </section>
        </>
      )}
    </>
  );
}
