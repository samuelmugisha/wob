export type Category = {
  id: string;
  award_year: number;
  code: string;
  name: string;
  description: string | null;
  finalist_count: number;
  document_count: number;
};

export type Finalist = {
  id: string;
  finalist_category_id: string;
  category_id: string;
  full_name: string;
  organisation: string | null;
  position_title: string | null;
  eligibility_flagged: boolean;
  document_count: number;
  claims_total: number;
  claims_reviewed: number;
  consent: { assessment: boolean; ai_processing: boolean; web_research: boolean } | null;
};

export type SourceType = "nomination_form" | "supporting_document";

export type DocumentRecord = {
  id: string;
  filename: string;
  mime_type: string;
  size_bytes: number;
  sha256_hash: string;
  source_type: SourceType;
  processing_status: string;
  archive_name: string | null;
  archive_member: string | null;
  uploaded_at: string;
  withdrawn_at: string | null;
  withdrawal_reason: string | null;
  processing_error: string | null;
  processing_attempts: number;
  processed_at: string | null;
  extraction_quality: ExtractionQuality;
};

export type ExtractionQuality = {
  method?: string;
  pages?: number;
  chunks?: number;
  tables?: number;
  ocr_pages?: number[];
  ocr_mean_confidence?: number;
  empty_pages?: number[];
  warnings?: string[];
};

export type Chunk = {
  chunk_index: number;
  page_number: number | null;
  page_end: number | null;
  section: string | null;
  token_count: number | null;
  content: string;
  has_table: boolean;
  embedded: boolean;
};

export type Passage = {
  rank: number;
  chunk_id: string;
  document_id: string;
  filename: string;
  source_type: SourceType;
  page_start: number | null;
  page_end: number | null;
  section: string | null;
  content: string;
  vector_rank: number | null;
  lexical_rank: number | null;
  fused_score: number;
  rerank_score: number | null;
};

export type SearchResult = {
  query: string;
  passages: Passage[];
  flags: string[];
  candidates: Record<string, number>;
  config: Record<string, unknown>;
};

export type CitedQuote = {
  chunk_id: string;
  document_id: string;
  filename: string;
  page: number | null;
  quote: string;
};

export type ExtractionRun = {
  id: string;
  status: "queued" | "running" | "succeeded" | "failed" | "cancelled";
  llm_model: string;
  served_by_models: string[];
  prompt_version: string;
  batches: number;
  usage: Record<string, number>;
  claims_created: number;
  claims_carried_forward: number;
  contradictions: { description: string; evidence: CitedQuote[] }[];
  contradiction_resolutions: Record<string, { resolution: string; resolved_by: string; created_at: string }>;
  missing_information: string[];
  discarded: { kind: string; reason: string; statement?: string; quote?: string; context?: string }[];
  attempts: number;
  error: string | null;
  next_attempt_at: string | null;
  created_at: string;
  completed_at: string | null;
};

export type ClaimEvidence = {
  relation: "supports" | "contradicts";
  quote: string;
  chunk_id: string | null;
  document_id: string | null;
  filename: string | null;
  page: number | null;
  document_withdrawn: boolean;
  external_source_id: string | null;
  url: string | null;
  publisher: string | null;
};

export type ClaimStatus = "verified" | "corroborated" | "unverified" | "missing" | "disputed";

export type Review = {
  id: string;
  reviewer: string;
  reviewer_role: string;
  previous_status: ClaimStatus | null;
  decision: ClaimStatus;
  notes: string | null;
  sufficiency: "sufficient" | "limited" | "insufficient" | null;
  credibility: "high" | "medium" | "low" | null;
  carried_forward: boolean;
  created_at: string;
};

export type ReviewInput = {
  decision: ClaimStatus;
  expected_status: ClaimStatus;
  notes?: string;
  sufficiency?: Review["sufficiency"];
  credibility?: Review["credibility"];
};

export type Me = {
  id: string;
  email: string;
  display_name: string;
  role: string;
  mfa_enabled: boolean;
  mfa_setup_required: boolean;
  permissions: {
    manage_evidence: boolean;
    review_claims: boolean;
    approve_rubrics: boolean;
    administer_rubrics: boolean;
    generate_reports: boolean;
    manage_users: boolean;
  };
};

export type Claim = {
  id: string;
  statement: string;
  claim_type: string | null;
  entity: string | null;
  role: string | null;
  period_start: string | null;
  period_start_precision: "year" | "month" | "day" | null;
  period_end: string | null;
  period_end_precision: "year" | "month" | "day" | null;
  period_text: string | null;
  quantitative_outcomes: { metric: string; value: string; unit: string | null }[];
  limitations: string | null;
  status: ClaimStatus;
  evidence: ClaimEvidence[];
  supporting_documents: number;
  independent_sources: number;
  latest_review: Review | null;
  review_count: number;
};

export type ClaimsResponse = {
  extraction: { enabled: boolean; reason: string | null; model?: string };
  verification: {
    total: number;
    reviewed: number;
    by_status: Record<ClaimStatus, number>;
    unresolved_contradictions: number;
  };
  latest_run: ExtractionRun | null;
  claims: Claim[];
};

export type ResearchRun = {
  id: string;
  status: "queued" | "running" | "succeeded" | "failed" | "cancelled";
  llm_model: string;
  served_by_models: string[];
  searches: number;
  pages_fetched: number;
  findings_created: number;
  criterion_codes: string[];
  not_found: { claim_id?: string; criterion_code?: string; note: string }[];
  identity_concerns: string[];
  discarded: { ref?: string; claim_ref?: string; url: string; quote: string; reason: string }[];
  error: string | null;
  next_attempt_at: string | null;
  created_at: string;
  completed_at: string | null;
};

export type Quality = "high" | "medium" | "low";

export type PublicSource = {
  id: string;
  claim_id: string | null;
  claim_statement: string | null;
  claim_current: boolean;
  criterion_code: string | null;
  criterion_name: string | null;
  relation: "supports" | "contradicts" | null;
  publisher: string;
  url: string;
  title: string | null;
  published_at: string | null;
  retrieved_at: string;
  quote: string | null;
  evidence_passage: string;
  source_type: string | null;
  identity_confidence: Quality | null;
  identity_notes: string | null;
  identity_confirmed: boolean;
  credibility: Quality | null;
  reviewer_outcome: "pending" | "accepted" | "rejected";
  auto_accepted: boolean;
  reviewed_by: string | null;
  reviewed_at: string | null;
  review_notes: string | null;
};

export type JudgesPackReport = { id: string; created_at: string };

export type JudgesPackFinalist = {
  finalist_id: string;
  full_name: string;
  organisation: string | null;
  position_title: string | null;
  rank: number;
  is_tie: boolean;
  score_display: string | null;
  points_display: string | null;
  unreviewed_criteria: string[];
  report: JudgesPackReport | null;
  documents: { id: string; filename: string; mime_type: string; size_bytes: number; source_type: SourceType }[];
};

export type JudgesPackCategory = {
  id: string;
  code: string;
  name: string;
  ranking_id: string | null;
  ranked_at: string | null;
  production: boolean;
  hidden_for_calibration: boolean;
  category_report: JudgesPackReport | null;
  finalists: JudgesPackFinalist[];
};

export type ResearchResponse = {
  research: { enabled: boolean; reason: string | null };
  latest_run: ResearchRun | null;
  findings: PublicSource[];
};

export type Criterion = {
  id: string;
  code: string;
  name: string;
  description: string;
  evidence_expectations: string | null;
  weight: string | null;
  position: number;
};

export type Rubric = {
  id: string;
  version: number;
  status: "draft" | "approved" | "frozen";
  weighting: "equal" | "weighted";
  notes: string | null;
  approved_at: string | null;
  frozen_at: string | null;
  created_at: string;
  criteria: Criterion[];
};

export type CriterionInput = {
  code: string;
  name: string;
  description: string;
  evidence_expectations?: string | null;
  weight?: string | number | null;
};

export type AssessmentRun = {
  id: string;
  status: "queued" | "running" | "succeeded" | "failed" | "cancelled";
  rubric_status: Rubric["status"] | null;
  llm_model: string;
  served_by_models: string[];
  prompt_version: string;
  items_total: number;
  items_done: number;
  skipped: { finalist: string; reason: string; finalist_category_id?: string }[];
  error: string | null;
  next_attempt_at: string | null;
  created_at: string;
  completed_at: string | null;
};

export type AssessmentCitation = {
  relation: "supports" | "contradicts";
  quote: string;
  document_id: string | null;
  filename: string | null;
  page: number | null;
  url: string | null;
  publisher: string | null;
};

export type CriterionAssessment = {
  id: string;
  criterion_id: string;
  criterion_code: string;
  criterion_name: string;
  rating: number;
  reviewer_rating: number | null;
  effective_rating: number;
  rationale: string;
  limitations: string | null;
  sufficiency: "sufficient" | "limited" | "insufficient";
  flags: string[];
  review_required: boolean;
  status: "proposed" | "reviewed" | "approved" | "rejected";
  source: "ai" | "human";
  review_notes: string | null;
  reviewed_by: string | null;
  reviewed_at: string | null;
  citations: AssessmentCitation[];
  discarded_citations: { ref: string; quote: string; reason: string }[];
};

export type RankingEntry = {
  finalist_id: string;
  finalist_category_id: string;
  full_name: string;
  organisation: string | null;
  score: string | null;
  score_display: string | null;
  points_display: string | null;
  rank: number | null;
  is_tie: boolean;
  criteria_assessed: number;
  criteria_total: number;
  missing_criteria: string[];
  unreviewed_criteria: string[];
  ratings: Record<string, number | null>;
};

export type Ranking = {
  id: string;
  run_id: string;
  created_at: string;
  rubric_version: number;
  rubric_status: Rubric["status"];
  production: boolean;
  weighting: Rubric["weighting"];
  calculation_version: string;
  is_provisional: boolean;
  criteria: Criterion[];
  entries: RankingEntry[];
  close_results: { higher: string; lower: string; difference: string }[];
  disclaimer: string;
};

export type CategoryRankings = {
  assessment: { enabled: boolean; reason: string | null };
  rubric: Rubric | null;
  latest_run: AssessmentRun | null;
  ranking: Ranking | null;
  hidden_for_calibration: boolean;
  calibration: { id: string; name: string; outcome: string; run_id: string; closed_at: string; reasons: string[] } | null;
};

export type StudySummary = {
  id: string;
  category_id: string;
  run_id: string;
  name: string;
  status: "open" | "closed" | "cancelled";
  outcome: "passed" | "failed" | "inconclusive" | null;
  created_at: string;
  closed_at: string | null;
  items: number;
  raters: { name: string; rated: number; submitted: boolean }[];
  you: { rated: number; submitted: boolean } | null;
  thresholds: Record<string, number>;
};

export type WorksheetItem = {
  id: string;
  finalist_id: string;
  finalist_name: string;
  criterion: { name: string; description: string; evidence_expectations: string | null };
  rating: number | null;
  notes: string | null;
};

export type AgreementStats = {
  items: number;
  rated_items: number;
  ai_vs_human: { exact: number | null; within_one: number | null; qwk: number | null };
  human_vs_human: { exact: number | null; within_one: number | null; qwk: number | null };
  bias: number | null;
  mean_absolute_error: number | null;
  pairs: Record<string, number>;
};

export type CalibrationResults = {
  outcome: "passed" | "failed" | "inconclusive";
  reasons: string[];
  raters_completed: number;
  finalists: number;
  overall: AgreementStats;
  by_criterion: Record<string, AgreementStats>;
  thresholds: Record<string, number>;
  computed_at: string;
};

export type ReportRecord = {
  id: string;
  kind: "individual" | "category";
  category_id: string;
  finalist_category_id: string | null;
  finalist_name: string | null;
  snapshot_id: string;
  status: "queued" | "running" | "succeeded" | "failed" | "cancelled";
  sha256_hash: string | null;
  size_bytes: number | null;
  generator_version: string | null;
  error: string | null;
  created_at: string;
};

export type Dashboard = {
  finalists: number;
  nominations: number;
  categories: number;
  documents: number;
  categories_ranked: number;
  categories_with_finalists: number;
  progress: {
    nominations: number;
    documents_indexed: number;
    evidence_extracted: number;
    assessed: number;
    claims_verified: number;
  };
  by_category: { id: string; name: string; finalists: number; documents: number; ranked: boolean }[];
  top_ranked: {
    finalist_id: string;
    category_id: string;
    category_name: string;
    full_name: string;
    organisation: string | null;
    rank: number | null;
    is_tie: boolean;
    score_display: string | null;
    strengths: string[];
    production: boolean;
  }[];
  rankings_hidden: number;
};

export type DocumentKind = "pdf" | "word" | "spreadsheet" | "image" | "text" | "other";

export type LibraryDocument = DocumentRecord & {
  finalist_id: string;
  finalist_name: string;
  category_id: string;
  category_name: string;
};

export type LibraryFilters = {
  q?: string;
  category_id?: string;
  finalist_id?: string;
  source_type?: SourceType;
  kind?: DocumentKind;
  added_from?: string;
  added_to?: string;
};

/** A short label for a document's file type. */
export function documentKind(mime: string): string {
  if (mime === "application/pdf") return "PDF";
  if (mime.includes("wordprocessingml") || mime === "application/msword") return "Word";
  if (mime.includes("spreadsheetml") || mime === "text/csv") return "Spreadsheet";
  if (mime.startsWith("image/")) return "Image";
  if (mime.startsWith("text/")) return "Text";
  return "File";
}

export function initials(name: string): string {
  const words = name.replace(/^(dr|prof|mr|mrs|ms|hon)\.?\s+/i, "").split(/\s+/).filter(Boolean);
  return ((words[0]?.[0] ?? "") + (words.length > 1 ? words[words.length - 1][0] : "")).toUpperCase();
}

export type Invitation = {
  user: UserAccount;
  invite_link: string;
  expires_in_hours: number;
  email_enabled: boolean;
  email_sent: boolean;
  email_error: string | null;
};

export type Role = "admin" | "secretariat" | "reviewer" | "judge" | "committee";

export const ROLE_LABELS: Record<Role, string> = {
  admin: "Administrator",
  secretariat: "Awards coordinator",
  reviewer: "Evidence reviewer",
  judge: "Judge",
  committee: "Committee member",
};

export type UserAccount = {
  id: string;
  email: string;
  display_name: string;
  role: Role;
  is_active: boolean;
  mfa_enabled: boolean;
  has_password: boolean;
  last_login_at: string | null;
  locked: boolean;
};

export type Consent = {
  notice_version: string;
  assessment: boolean;
  ai_processing: boolean;
  web_research: boolean;
  method: "signed_form" | "email" | "online" | "other";
  reference: string | null;
  recorded_by: string | null;
  recorded_at: string;
};

/** Statuses the ingestion worker will still move on from by itself. */
export const IN_PROGRESS_STATUSES = ["pending", "scanning", "extracting", "extracted", "chunking"];

export type UploadResult = {
  import_id: string;
  replayed: boolean;
  accepted: DocumentRecord[];
  skipped: { filename: string; reason: string }[];
};

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public code?: string,
  ) {
    super(message);
  }
}

const PUBLIC_PAGES = ["/login", "/accept-invite"];

/** Send the browser to sign in (or to two-factor setup) when the API says so. */
function handleAuthFailure(status: number, detail: string): void {
  if (typeof window === "undefined") return;
  const here = window.location.pathname + window.location.search;
  if (status === 401 && !PUBLIC_PAGES.includes(window.location.pathname)) {
    window.location.assign(`/login?next=${encodeURIComponent(here)}`);
  } else if (status === 403 && detail.startsWith("mfa_setup_required") && window.location.pathname !== "/account") {
    window.location.assign("/account?setup=mfa");
  }
}

function errorDetail(body: unknown, fallback: string): string {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object" && "message" in detail) {
    return String((detail as { message: unknown }).message);
  }
  if (Array.isArray(detail)) {
    return detail.map((d: { msg?: string }) => d.msg ?? JSON.stringify(d)).join("; ");
  }
  return fallback;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api/v1${path}`, { credentials: "same-origin", ...init });
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    const message = errorDetail(body, response.statusText);
    const code = (body as { detail?: { code?: string } } | null)?.detail?.code;
    if (!path.startsWith("/auth/")) handleAuthFailure(response.status, message);
    throw new ApiError(response.status, message, code);
  }
  return body as T;
}

const json = (method: string, data: unknown): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(data),
});

export const api = {
  listCategories: () => request<Category[]>("/categories"),
  dashboard: () => request<Dashboard>("/dashboard"),
  library: (filters: LibraryFilters) => {
    const params = new URLSearchParams();
    for (const [key, value] of Object.entries(filters)) if (value) params.set(key, value);
    return request<{ total: number; items: LibraryDocument[] }>(`/documents?${params}`);
  },
  createCategory: (data: { code: string; name: string; description?: string }) =>
    request<Category>("/categories", json("POST", data)),
  getCategory: (id: string) => request<Category>(`/categories/${id}`),

  listFinalists: (categoryId: string) =>
    request<Finalist[]>(`/categories/${categoryId}/finalists`),
  addFinalist: (
    categoryId: string,
    data: { full_name: string; organisation?: string; position_title?: string },
  ) => request<Finalist>(`/categories/${categoryId}/finalists`, json("POST", data)),
  getFinalist: (categoryId: string, finalistId: string) =>
    request<Finalist>(`/categories/${categoryId}/finalists/${finalistId}`),

  listDocuments: (categoryId: string, finalistId: string, includeWithdrawn: boolean) =>
    request<DocumentRecord[]>(
      `/categories/${categoryId}/finalists/${finalistId}/documents?include_withdrawn=${includeWithdrawn}`,
    ),
  withdrawDocument: (id: string, reason: string) =>
    request<DocumentRecord>(`/documents/${id}/withdraw`, json("POST", { reason })),
  downloadUrl: (id: string) => `/api/v1/documents/${id}/content`,
  searchEvidence: (categoryId: string, finalistId: string, q: string) =>
    request<SearchResult>(
      `/categories/${categoryId}/finalists/${finalistId}/search?q=${encodeURIComponent(q)}`,
    ),
  listClaims: (categoryId: string, finalistId: string) =>
    request<ClaimsResponse>(`/categories/${categoryId}/finalists/${finalistId}/claims`),
  extractClaims: (categoryId: string, finalistId: string) =>
    request<{ run: ExtractionRun; warnings: string[] }>(
      `/categories/${categoryId}/finalists/${finalistId}/claims/extract`,
      { method: "POST" },
    ),
  me: () => request<Me>("/me"),
  login: (email: string, password: string, otp?: string) =>
    request<{ user: Me }>("/auth/login", json("POST", { email, password, otp: otp || undefined })),
  logout: () => fetch("/api/v1/auth/logout", { method: "POST", credentials: "same-origin" }),
  acceptInvite: (token: string, password: string) =>
    request<{ user: Me }>("/auth/accept-invite", json("POST", { token, password })),
  changePassword: (current_password: string, new_password: string) =>
    request<null>("/auth/password", json("POST", { current_password, new_password })),
  mfaSetup: () => request<{ secret: string; otpauth_uri: string }>("/auth/mfa/setup", { method: "POST" }),
  mfaEnable: (otp: string) => request<Me>("/auth/mfa/enable", json("POST", { otp })),
  listUsers: () => request<UserAccount[]>("/users"),
  createUser: (email: string, display_name: string, role: Role) =>
    request<Invitation>(
      "/users",
      json("POST", { email, display_name, role }),
    ),
  updateUser: (id: string, changes: { role?: Role; is_active?: boolean; display_name?: string }) =>
    request<UserAccount>(`/users/${id}`, json("PATCH", changes)),
  reissueInvite: (id: string) =>
    request<Invitation>(`/users/${id}/invite`, {
      method: "POST",
    }),
  reviewClaim: (claimId: string, input: ReviewInput) =>
    request<Claim>(`/claims/${claimId}/reviews`, json("POST", input)),
  listReviews: (claimId: string) => request<Review[]>(`/claims/${claimId}/reviews`),
  resolveContradiction: (runId: string, index: number, resolution: string) =>
    request<ExtractionRun>(
      `/claim-extraction-runs/${runId}/contradictions/${index}/resolutions`,
      json("POST", { resolution }),
    ),
  getResearch: (categoryId: string, finalistId: string) =>
    request<ResearchResponse>(`/categories/${categoryId}/finalists/${finalistId}/research`),
  startResearch: (categoryId: string, finalistId: string) =>
    request<ResearchRun>(`/categories/${categoryId}/finalists/${finalistId}/research`, {
      method: "POST",
    }),
  reviewSource: (
    sourceId: string,
    input: { outcome: "accepted" | "rejected"; credibility?: Quality; identity_confirmed?: boolean; notes?: string },
  ) => request<PublicSource>(`/external-sources/${sourceId}/review`, json("POST", input)),
  listRubrics: (categoryId: string) => request<Rubric[]>(`/categories/${categoryId}/rubrics`),
  createRubric: (
    categoryId: string,
    body: { use_template?: boolean; criteria?: CriterionInput[]; weighting?: Rubric["weighting"] },
  ) => request<Rubric>(`/categories/${categoryId}/rubrics`, json("POST", body)),
  updateRubric: (
    rubricId: string,
    body: { criteria: CriterionInput[]; weighting: Rubric["weighting"]; notes: string | null },
  ) => request<Rubric>(`/rubrics/${rubricId}`, json("PUT", body)),
  approveRubric: (rubricId: string) =>
    request<Rubric>(`/rubrics/${rubricId}/approve`, { method: "POST" }),
  freezeRubric: (rubricId: string) =>
    request<Rubric>(`/rubrics/${rubricId}/freeze`, { method: "POST" }),
  unfreezeRubric: (rubricId: string, reason: string) =>
    request<Rubric>(`/rubrics/${rubricId}/unfreeze`, json("POST", { reason })),
  categoryRankings: (categoryId: string) =>
    request<CategoryRankings>(`/categories/${categoryId}/rankings`),
  startAssessment: (categoryId: string) =>
    request<AssessmentRun>("/assessments", json("POST", { category_id: categoryId })),
  calculateRanking: (categoryId: string) =>
    request<Ranking>("/rankings", json("POST", { category_id: categoryId })),
  candidateAssessments: (categoryId: string, finalistId: string) =>
    request<{
      assessment: { enabled: boolean; reason: string | null };
      run: AssessmentRun | null;
      rubric: Rubric | null;
      items: CriterionAssessment[];
      hidden_for_calibration: boolean;
    }>(`/categories/${categoryId}/finalists/${finalistId}/assessments`),
  reviewAssessment: (
    assessmentId: string,
    body: { decision: "approved" | "rejected"; adjusted_rating?: number; notes?: string },
  ) => request<CriterionAssessment>(`/criterion-assessments/${assessmentId}/review`, json("POST", body)),
  listReports: (categoryId: string) => request<ReportRecord[]>(`/categories/${categoryId}/reports`),
  createReport: (body: { kind: "individual" | "category"; category_id: string; finalist_id?: string }) =>
    request<ReportRecord>("/reports", json("POST", body)),
  reportUrl: (id: string) => `/api/v1/reports/${id}/download`,
  judgesPack: () => request<JudgesPackCategory[]>("/judges-pack"),
  listStudies: (categoryId: string) => request<StudySummary[]>(`/categories/${categoryId}/calibration-studies`),
  eligibleRaters: () => request<{ id: string; display_name: string; role: string }[]>("/calibration/eligible-raters"),
  createStudy: (categoryId: string, name: string, raterIds: string[]) =>
    request<StudySummary>("/calibration-studies", json("POST", { category_id: categoryId, name, rater_ids: raterIds })),
  studyItems: (studyId: string) =>
    request<{ study: StudySummary; items: WorksheetItem[] }>(`/calibration-studies/${studyId}/items`),
  saveCalibrationRating: (studyId: string, itemId: string, rating: number, notes?: string) =>
    request<{ saved: boolean }>(`/calibration-studies/${studyId}/ratings`, json("PUT", { item_id: itemId, rating, notes })),
  submitCalibration: (studyId: string) =>
    request<StudySummary>(`/calibration-studies/${studyId}/submit`, json("POST", { attest_blind: true })),
  studyResults: (studyId: string) =>
    request<{ study: StudySummary; final: boolean; results: CalibrationResults }>(`/calibration-studies/${studyId}/results`),
  closeStudy: (studyId: string) =>
    request<{ study: StudySummary; final: boolean; results: CalibrationResults }>(`/calibration-studies/${studyId}/close`, {
      method: "POST",
    }),
  getConsent: (categoryId: string, finalistId: string) =>
    request<{ current: Consent | null; history: Consent[] }>(`/categories/${categoryId}/finalists/${finalistId}/consent`),
  recordConsent: (
    categoryId: string,
    finalistId: string,
    body: Omit<Consent, "recorded_by" | "recorded_at">,
  ) => request<Consent>(`/categories/${categoryId}/finalists/${finalistId}/consent`, json("POST", body)),
  startHumanAssessment: (categoryId: string) =>
    request<AssessmentRun>("/assessments", json("POST", { category_id: categoryId, mode: "human" })),
  humanRating: (body: {
    run_id: string;
    finalist_id: string;
    criterion_id: string;
    rating: number;
    rationale: string;
    sufficiency: "sufficient" | "limited" | "insufficient";
  }) => request<CriterionAssessment>("/criterion-assessments/human", json("POST", body)),
  getRetention: (categoryId: string) =>
    request<{ retention_until: string | null }>(`/categories/${categoryId}/retention`),
  setRetention: (categoryId: string, retention_until: string | null) =>
    request<{ retention_until: string | null }>(`/categories/${categoryId}/retention`, json("PUT", { retention_until })),
  exportUrl: (categoryId: string, finalistId: string) =>
    `/api/v1/categories/${categoryId}/finalists/${finalistId}/export`,
  purgeFinalist: (categoryId: string, finalistId: string, reason: string, confirm_name: string) =>
    request<{ purged: boolean; counts: Record<string, number> }>(
      `/categories/${categoryId}/finalists/${finalistId}/purge`,
      json("POST", { reason, confirm_name }),
    ),
  listChunks: (id: string) => request<Chunk[]>(`/documents/${id}/chunks`),
  reprocessDocument: (id: string) =>
    request<DocumentRecord>(`/documents/${id}/reprocess`, { method: "POST" }),

  /** Multipart upload with progress reporting (fetch has no upload progress events). */
  uploadDocuments(
    categoryId: string,
    finalistId: string,
    files: File[],
    sourceType: SourceType,
    onProgress: (fraction: number) => void,
  ): Promise<UploadResult> {
    const form = new FormData();
    files.forEach((file) => form.append("files", file, file.name));
    form.append("source_type", sourceType);

    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open("POST", `/api/v1/categories/${categoryId}/finalists/${finalistId}/documents`);
      xhr.setRequestHeader("Idempotency-Key", crypto.randomUUID());
      xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(e.loaded / e.total);
      xhr.onerror = () => reject(new ApiError(0, "Network error — the upload did not complete."));
      xhr.onload = () => {
        let body: unknown = null;
        try {
          body = JSON.parse(xhr.responseText);
        } catch {}
        if (xhr.status >= 200 && xhr.status < 300) return resolve(body as UploadResult);
        const message = errorDetail(body, xhr.statusText || "Upload failed");
        handleAuthFailure(xhr.status, message);
        reject(new ApiError(xhr.status, message));
      };
      xhr.send(form);
    });
  },
};

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function formatDate(iso: string): string {
  return new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

export function slugify(text: string): string {
  return text
    .toLowerCase()
    .normalize("NFKD")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 64);
}
