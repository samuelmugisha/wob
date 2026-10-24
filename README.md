# WOB Awards 2026 – AI-Powered RAG Finalists Ranking

This system assesses judge-shortlisted finalists using their submitted evidence, retrieval-augmented generation (RAG) and human verification, and produces provisional rankings within each award category. It implements *AI-Powered RAG Technical Specification v1.0*.

> AI rankings are advisory. The awards committee retains responsibility for final deliberation and winner approval.

## How it works

![RAG pipeline: documents are scanned, extracted, chunked and embedded into PostgreSQL with pgvector; queries use hybrid retrieval and reranking to pick passages that Claude reads, and every cited quote is verified before human review, ranking and reports.](docs/images/rag-pipeline.svg)

**Indexing.** When the coordinator uploads documents:
1. The background worker scans each file for viruses.
2. It extracts the text, using OCR for scans.
3. It splits the text into overlapping chunks of about 700 tokens.
4. It embeds the chunks locally.
5. It stores them in PostgreSQL with pgvector, alongside a full-text keyword index.

**Querying.** A query is a rubric criterion, a claim to check, or a search.
1. Hybrid retrieval searches that finalist's evidence only, by meaning and by exact words.
2. A reranker picks the 10 best passages.
3. Claude reads those passages and returns claims or a rating on the rubric's scale, each citing its quotes.
4. Every quote is checked against the passage it cites.
5. Reviewers approve or adjust each rating before it counts towards the ranking and reports.

## Layout (spec §15)

```
backend/          FastAPI app, Alembic migrations, tests
frontend/         Next.js coordinator UI
ai/               prompts, rubrics, evaluation sets, output schemas
infrastructure/   docker compose (Postgres 17 + pgvector), deployment
docs/             architecture, API, operations
```

## Local setup

Requires Docker and [uv](https://docs.astral.sh/uv/).

```bash
cp .env.example .env          # set POSTGRES_PASSWORD (and both URLs) and SECRET_KEY
make db-up                    # Postgres + pgvector on 127.0.0.1:5432 (creates wob and wob_test)
make migrate                  # apply schema to wob
make user EMAIL=you@org NAME="Your Name" ROLE=admin   # prints a set-password link
make test                     # rebuilds wob_test from scratch, runs the suite
make api                      # API in Docker on http://127.0.0.1:8000 (docs at /docs)
cd frontend && npm install    # once
make web                      # coordinator UI on http://localhost:3000
make worker                   # ClamAV + ingestion worker in Docker (first start: ~5 min)
make benchmark                # retrieval recall benchmark (see ai/evaluation/README.md)
```

The API and worker run in Docker because the local embedding and reranking models need ONNX Runtime, which has no build for Intel Macs. `make api-local` runs the API on the host with reload, but without those models search falls back to keywords only.

## Evidence knowledge base

The awards coordinator works through **Category → Candidate → Documents**:

1. Create the award categories (until the committee's 11 categories are seeded).
2. Add each category's shortlisted candidates. A person shortlisted in two categories is added to each one, and their evidence is kept separately per category.
3. Upload the candidate's files: PDF, DOCX, XLSX, PNG/JPG, or a ZIP of these (50 MB per file). Choose *Nomination form* or *Supporting document*.

Uploading to a specific candidate counts as the coordinator's confirmation of the candidate–document mapping (FR-03). Each upload goes through these checks:

- **File type** is detected from the content, not the file name.
- **ZIP files** are expanded with limits on member count and total size. Nested archives, encrypted entries and unsafe paths are rejected.
- **Duplicates** (same SHA-256 for the same candidate) are skipped.
- **Every upload is audited.** Each request also carries an idempotency key, so retrying a request doesn't store files twice.

Originals can't be deleted. A mistaken upload is *withdrawn* with a reason: it stays on record for the audit trail and is excluded from the knowledge base.

### Processing pipeline

The ingestion worker (`app/workers/ingest.py`, run by `make worker`) turns uploads into searchable evidence:

1. **Integrity and malware check:** the stored file's SHA-256 must match the upload, then ClamAV scans it. Infected files are *rejected* and never parsed.
2. **Extraction:**
   - PDFs: text, headings (by font size) and ruled tables, with page numbers. Pages with no text layer are OCR'd with Tesseract.
   - Word: headings, paragraphs and tables in document order.
   - Excel: one table per sheet.
   - Images: OCR'd.

   Quality indicators (pages, OCR pages and confidence, empty pages, warnings) are stored on the document.
3. **Chunking:** about 700 tokens per chunk (900 at most) with ~100 tokens of overlap. Each chunk carries its section path and page range. Tables are kept whole, or split row by row with the header repeated.
4. **Embedding and indexing:** chunks are embedded (by default `nomic-embed-text-v1.5`, run locally, so evidence never leaves the server) and stored with a full-text index. Retrieval reads the `knowledge_base_chunks` view, which includes only indexed, non-withdrawn documents.

Postgres is the job queue (`FOR UPDATE SKIP LOCKED`), so several workers can run side by side.
- **Temporary failures** (for example, the scanner is down) retry with backoff: 1, 2, 4, 8 minutes, then the worker gives up.
- **Unreadable files** (corrupt or password-protected) are rejected.
- **Retrying:** coordinators can retry failed or rejected documents from the UI.
- **Checking the text:** *View text* shows exactly what was indexed.

Without Docker, `uv run python -m app.workers.ingest` runs the worker on the host. That needs Tesseract installed and `uv sync --extra local-embeddings`, or `EMBEDDING_PROVIDER=voyage`.

**Files are encrypted at rest.** Each file is encrypted with its own AES-256-GCM key, which is wrapped by a key from `FILE_ENCRYPTION_KEYS`; see `app/services/storage.py`. Without a key configured, the system refuses to store files. Maintenance commands:
- `make encrypt-storage`: encrypts legacy plaintext files.
- `make rotate-file-key`: re-wraps file keys to a new master key without re-encrypting the files.
- `make verify-storage`: decrypts every file and checks it against the SHA-256 recorded in the database.

Back the keys up separately from the data: losing them makes every stored file unreadable.

**Data protection:** see [docs/operations/data-protection-review.md](docs/operations/data-protection-review.md). Real nomination data must not be loaded, and the AI features must stay off, until its action plan is complete.

Set `EMBEDDING_DIM` to match the chosen embedding model **before** the first migration. Changing it later requires a new migration and re-embedding all chunks.

### Importing nomination forms

`python -m app.cli import-form-evidence FILE --as EMAIL` takes a Google Forms export (`.xlsx`, one sheet per award category; `-` reads it from standard input) and attaches each response, as a supporting document, to the finalist of the same name in that category. Matching ignores case, accents, punctuation and titles such as Dr or Mrs. Sheet titles cut short at 31 characters still match their category.

- **What goes in the document:** the nominee's organisation and title, every written answer under its question, and each referee's name and organisation. Emails, phone numbers, date of birth and the declaration are left out, because the documents go to the AI and to research. Uploaded-file answers are Google Drive links the server can't open, so they're listed for a coordinator to fetch and upload.
- **What it skips:** responses that match no finalist, nominees who withdrew consent to assessment (or haven't given it when uploads require consent), and nominees already imported.
- **Profile details:** where the system has no organisation or title for a nominee, the form's are used.
- **Afterwards:** claim extraction is queued for each nominee who got a document. The worker indexes the documents first, so under the jury decision the claims they support are verified.
- **Preview first:** without `--yes` it only shows what it would do. Only admin and coordinator accounts can run it, and each import is audited as `nomination_form.imported`.
- **Running it on the server** without leaving a copy there: `ssh … 'cd /opt/wob/infrastructure/deployment && docker compose --env-file /etc/wob/env exec -T api python -m app.cli import-form-evidence - --as EMAIL' < WOB_Evidence.xlsx`. Keep these exports in `docs/attachments/`, which git ignores.

### Hybrid retrieval

`GET /api/v1/categories/{category}/finalists/{finalist}/search?q=…` (or `?criterion_id=…`) returns the passages an assessor sees for a question or rubric criterion (spec §5.3, FR-05). The same search is in the UI under *Search this candidate's evidence*.

1. **Candidate filter first.** Both searches run only over this finalist-category's chunks in `knowledge_base_chunks`, so withdrawn and unprocessed documents never appear. Every result is re-checked before it is returned.
2. **Vector search:** exact cosine top 20, using the same embedding model as the passages. Exact rather than approximate search avoids HNSW-with-filter shortfalls; a candidate has at most a few hundred chunks.
3. **Keyword search:** Postgres full text, top 20. The query's terms are ORed, so long criterion descriptions still match.
4. **Fusion and reranking:** reciprocal rank fusion (k = 60) merges the lists, then a cross-encoder (`jina-reranker-v1-turbo-en`, local) reranks. The top 10 passages are returned (configurable 1–50).
5. **Flags** warn the assessor about thin or uncertain retrieval: `no_indexed_evidence`, `few_passages`, `no_keyword_matches`, `some_evidence_not_embedded_with_current_model` and `low_relevance`. `low_relevance` stays off until `RERANK_MIN_SCORE` is calibrated on the pilot.

Each response records the model IDs and settings used, and each search is written to the audit log with the passages it returned. `POST …/citations/verify` checks that cited passage IDs belong to this candidate and that the quoted text really occurs in them (spec §13: 100% citation resolution).

### Claim extraction (FR-06)

`POST …/claims/extract` (or *Extract claims* on the candidate page) queues a run. The worker sends the candidate's indexed passages to Claude Opus 5.5 (`claude-opus-5-5`). Settings: adaptive thinking, effort `high`, JSON-schema structured output, server-side refusal fallback. Prompt: `app/prompts/claim_extraction.py`, versioned and stored with every run. Claude returns claims with their claim type, role, organisation, period and figures, plus contradictions and missing information.

Nothing the model returns is trusted as-is:
- **Quotes:** every quote must occur in the passage it cites. Claims without a verifiable supporting quote are discarded and listed on the run.
- **Status:** claims start `unverified`, or `disputed` when contradicting evidence was quoted. Verification is the reviewers' job (FR-07).
- **Large evidence sets:** they are split into batches, and a batch whose output is too long for one response is split in half and retried.
- **Re-runs:** a re-run supersedes the previous claims, which are kept for history.

**Off by default.** This sends nomination evidence, which is personal data, to Anthropic: cross-border processing that spec §12 requires to be reviewed first. It runs only with `LLM_PROVIDER=anthropic`, `EXTERNAL_AI_PROCESSING_APPROVED=true` and an `ANTHROPIC_API_KEY`. Until then the API and the UI say why it is off.

### Claim verification (FR-07)

Reviewers, coordinators and admins record a decision on each claim (`POST /api/v1/claims/{id}/reviews`, or *Review* under each claim in the UI). Judges and committee members can see decisions but not make them. Each decision is an append-only review row, and the claim's status is the latest decision.

| Decision | Rule |
|---|---|
| verified | At least one supporting document still in the knowledge base. Notes optional. |
| corroborated | Supporting quotes from two or more distinct documents. Notes required: say why they are independent. |
| disputed / missing / reset to unverified | Notes required. |

- **Sufficiency and credibility:** reviewers can rate evidence sufficiency and source credibility separately (spec §6).
- **No silent overwrites:** each request carries the status the reviewer saw (`expected_status`). If someone else has changed it since, the request returns 409 instead of overwriting their decision.
- **Contradictions:** contradictions found during extraction are resolved with a written resolution (`POST /api/v1/claim-extraction-runs/{id}/contradictions/{index}/resolutions`).
- **Re-extraction:** a review carries over to an identical claim only when that claim isn't contradicted and still meets its rule. The carried review is marked as such. All other claims need reviewing again.
- **Progress:** the category page shows how many claims each candidate has had reviewed.
- **Jury decision: supporting documents are a credible source of truth (23 October 2026).** When claims are extracted, every new claim that a passage of a non-withdrawn *supporting document* supports is marked verified automatically. Claims contradicted by any evidence, and claims backed only by the nomination form, are left for a reviewer. The decision is recorded with no reviewer and basis `jury_supporting_documents` (database-enforced: it can only verify). It shows as "Jury decision (automatic)" and is audited as `claim.verified_automatically`. A reviewer can still change it, and it carries forward on re-extraction like any review. Claims extracted earlier are verified by `make verify-supporting-claims` (`python -m app.cli verify-supporting-claims`), which `deploy.sh` runs after every deploy and which skips claims anyone has already decided on. `JURY_VERIFIES_SUPPORTING_DOCUMENTS=false` stops new automatic verifications.

### External research (FR-13)

*Research public sources* on the candidate page, or `POST …/research`, queues a run for reviewers and coordinators. Claude searches the web for credible sources (registries, regulators, organisation websites, annual reports, professional bodies, established news) with two aims: confirming or contradicting the candidate's current claims, and finding public evidence for each criterion of the category's current rubric. Research needs claims or a rubric, so candidates who uploaded no documents can still be researched by criterion. Social and user-generated sites are excluded (`RESEARCH_BLOCKED_DOMAINS`). The run uses the `web_search_20250305` and `web_fetch_20250910` tools, the versions without dynamic filtering, so that every fetched page comes back verbatim.

- **Quotes are checked.** A finding is kept only if its quote appears in a page fetched during that run (PDFs are read locally). Anything else is discarded and listed, with the reason.
- **Credible supporting findings are accepted automatically.** A finding is accepted without a reviewer when it supports its claim or criterion, comes from an official registry, regulator, annual report or professional body (recorded as high credibility) or the organisation's own website (medium), and Claude was highly confident the page is about this nominee. It is labelled *Auto-accepted*, logged as `external_source.auto_accepted`, and not accepted again when a later run finds the same page for the same claim or criterion. A reviewer can still reject it, with notes, which removes it from the claim's evidence. Findings from research run before this rule existed are accepted by the same rules with `make auto-accept-research` (in production: `docker compose --env-file /etc/wob/env exec api python -m app.cli auto-accept-research`); running it again changes nothing.
- **Everything else waits for a reviewer.** This includes evidence that contradicts a nominee, news and other sites, and possible namesakes. Accepting requires a credibility rating. If Claude was not highly confident the page is about this nominee rather than a namesake, the reviewer must also confirm identity. Rejecting requires notes. The database enforces all of these rules.
- **Accepted sources become claim evidence.** Each distinct website counts as one independent source toward *corroborated*. Accepted sources stay attached when an identical claim is re-extracted.
- **Accepted criterion findings go to assessment.** They are tagged with the criterion's code and name as they stood at research time, and are given to the AI as public sources (S#) when it rates the candidate on any criterion. A reviewer-accepted one doesn't attach to a claim, so it doesn't count toward *corroborated*.
- **Auto-accepted criterion findings are linked to the claims they support.** After each research run, Claude reads the candidate's current claims and the auto-accepted criterion sources and says which claims each source directly supports. A link is kept only if its quote occurs in the source; it then shows as public evidence on the claim and counts toward *corroborated*, and each link is audited as `external_source.matched_to_claim`. Sources are matched once, and again against new claims after re-extraction. Matching needs claim extraction enabled and the candidate's consent to AI processing, and a failure never fails the research or extraction run. Rejecting the source removes its links. Earlier research is matched with `make match-research-claims` (`python -m app.cli match-research-claims`), which `deploy.sh` runs after every deploy.
- **"Not found online" is neutral.** It is listed, never counted against a nominee (spec §6). The prompt also forbids researching private life or sensitive personal attributes.
- **Off by default.** Research runs only with `RESEARCH_ENABLED=true` in addition to the claim-extraction approval settings, because it sends nominee names and claims to Anthropic and searches the web about them.

### Rubrics, assessment and ranking (FR-08 to FR-10)

**Rubrics.** Each category has versioned rubrics, managed on the category page. Coordinators create and edit drafts; *Start from draft template* gives five illustrative criteria, labelled as such. The committee or an admin approves and then freezes a rubric. A frozen rubric can't be changed (database-enforced), and assessments use the latest frozen version, or the latest draft until one exists.

**Rating scales.** The board moved from the original 1–5 scale to **0–3**: 0 None (no evidence that the criterion is met), 1 Poor (weak, partial or indirect evidence), 2 Good (clear evidence) and 3 Excellent (strong, well-evidenced and outstanding). Each rubric version records its scale. New versions use 0–3, and versions created before the change keep 1–5, so their ratings, rankings and reports stay valid. The scale can be changed on a draft that nobody has rated. The AI prompt, its output schema, reviews, human ratings, calibration, ranking points, reports and the screens all follow the scale of the rubric in use. Any rating above the lowest level (2+ on 1–5, 1+ on 0–3) needs a verified supporting citation to be approved, and the database rejects any rating outside its version's scale.

**Administrator changes.** Only an admin can unfreeze a rubric (back to approved, with a reason recorded in the audit log) or amend an approved one. An amendment stays approved under the admin's name, and the audit log records the criteria before and after. Criteria are updated in place by code, so ratings already made stay linked to them; a criterion that has ratings can be reworded but not removed. Rankings keep the rubric status they were calculated under, so earlier production rankings stay production. The database allows these changes only when the application sets `wob.rubric_admin` for the transaction.

**Assessment.** `POST /api/v1/assessments` queues a run for a category. For every finalist and criterion, the worker:
1. retrieves that finalist's top passages for the criterion through hybrid search;
2. adds the finalist's claims with their verification status, and any accepted public sources;
3. asks Claude Opus 5.5 (prompt `app/prompts/criterion_assessment.py`) for a rating on the rubric's scale (see *Rating scales*), with a rationale, citations, evidence sufficiency and reasons for review.

Each request sees one finalist only. Citations are checked against the evidence. A rating of 2 or more without a verified supporting citation is flagged `uncited_rating` and can't be approved. Each result is saved as soon as it's made, so a failed run resumes where it stopped.

**Quality review.** Reviewers approve each rating, adjust it with a reason (the AI's rating is kept), or reject it for re-assessment.

**Ranking.** `POST /api/v1/rankings` calculates a snapshot from a completed run:
- Score: the mean of the effective ratings, or the weighted mean.
- Order: ranked on exact decimal scores, displayed to 2 decimals and as points out of 100 (×20 on 1–5, ×100/3 on 0–3).
- Ties share a rank and stay provisional.
- Rejected or missing ratings leave a finalist unscored rather than partially averaged, and unreviewed ratings are listed.
- Close results (within 0.25) are highlighted.
- Snapshots are append-only.
- Only snapshots taken on a frozen rubric count as production; the rest are shown as practice rankings.

The arithmetic is covered by reference tests (`tests/test_ranking_math.py`).

### AI calibration (FR-15)

Before AI ratings are relied on, committee raters rate the same items blind, and the AI is compared with them (*AI calibration* on the category page).

1. **Creating a study.** Admins, coordinators or committee members create a study from the latest completed assessment run. It covers every AI-rated finalist × criterion item, and they name the raters (committee, judges, reviewers or admins).
2. **Rating blind.** Until each rater submits, the category's AI ratings, ranking, reports and assessment reviews are hidden from them. Their worksheet (`/calibration/{id}`) shows only the criterion and the finalist's evidence. They rate on the study's rubric scale and confirm, when submitting, that they rated without seeing the AI's output.
3. **Results.** The AI's original (pre-review) ratings are compared with every rater:
   - **Measures:** quadratic-weighted kappa, exact and within-one-point agreement, bias (AI minus the human average) and mean absolute difference, overall and per criterion.
   - **Baseline:** the same figures for rater vs rater, so the AI is judged against how far the committee itself agrees.
   - **Code:** `app/services/calibration_metrics.py`, with hand-verified reference tests.
4. **Closing.** Closing a study stores an immutable result (database-enforced): *passed*, *failed* or *inconclusive* (fewer than 20 items, or no variation).
   - **Thresholds** are proposals for the committee to confirm: kappa at least 0.6 and within 0.1 of the raters' own; within one point at least 90% of the time; bias within ±0.5 overall and ±0.75 per criterion.
   - **Where it shows:** the latest result appears next to the ranking and in every report's provenance.

AI ratings are never adjusted automatically. A failed or biased criterion points to the rubric wording or the assessment prompt to revise, followed by a new study.

### Deliberation reports (FR-11)

`POST /api/v1/reports`, or *Deliberation reports* on the category page, generates a PDF from a ranking snapshot (by default, the latest). Admins, coordinators and the committee can generate reports; everyone signed in can read them.

- **Individual report:**
  - identity, category, rubric version and status, provisional rank and score;
  - each criterion's rating with its review status, rationale and verified citations;
  - key strengths (ratings of 4 or more) and limitations;
  - claim verification counts, unresolved claims and contradictions;
  - questions for judges;
  - a provenance appendix: snapshot, models, prompt versions, retrieval settings, and evidence documents with their SHA-256.
- **Category report** (landscape): the ranking matrix with every criterion rating (* = not reviewed), close results and ties, the criteria with the largest spread, unresolved verification per finalist, questions for judges, finalist summaries and provenance.

Every report carries the committee disclaimer and a confidentiality footer. Reports on a rubric that isn't frozen are marked *PRACTICE ONLY* in text and with an image watermark, which is kept out of the text layer so search, copying and screen readers aren't affected.

Scores, ranks and ratings come from the immutable snapshot. A rating reviewed after the snapshot is pointed out rather than silently mixed in. Strengths, limitations and questions are generated by rules from the reviewed record (`app/services/reports/questions.py`), so they can't invent issues. Each PDF is stored with its SHA-256 and size, and generation and every download are audited. Reports are generated within the request, since they take about a second.

### Judges' pack

*Judges' Pack* in the menu (`GET /api/v1/judges-pack`) gathers each category's top three finalists from its latest ranking, with everyone tied for third included. For each finalist it shows the rank, the score, any AI ratings not yet reviewed, the individual report generated from that ranking, and their documents. Withdrawn documents are left out, and so are files that haven't passed the malware scan. Each category also links its category report. Users who can generate reports get a button that creates any missing reports from the latest ranking. Every signed-in user can open the pack, and blind raters in an open calibration study don't see that category. Downloads go through the usual audited endpoints.

### Authentication (spec §9, §12)

- **Accounts are invitation-only.** An admin creates an account on the *Users* page (or with `make user`), which produces a one-time set-password link valid for 72 hours. *New link* (or `make invite EMAIL=…`) resets a forgotten password: it signs the person out and resets their two-factor setup.
- **Invitation emails.** When an admin invites someone or issues a new link, the person is emailed a button to set their password. The admin also sees whether the email was sent. If it wasn't, or email isn't set up, the link is shown so it can be shared another way.
  - Configure it with `EMAIL_BACKEND=smtp` plus the `SMTP_*` and `EMAIL_FROM` settings in `.env.example`.
  - `EMAIL_BACKEND=console` writes emails to the API log, for local testing.
  - DigitalOcean blocks SMTP ports 25, 465 and 587, so on a droplet use a provider that accepts port 2525.
- **Passwords** are hashed with Argon2id and must be at least 12 characters and not based on the email address.
- **Lockout:** five failed sign-ins lock the account for 15 minutes. Every failure returns the same message, so responses never reveal whether an account exists or is locked.
- **Two-factor authentication (TOTP)** is available to everyone and required for admin and committee roles (`MFA_REQUIRED_ROLES`). Until it is on, those users can only reach their account page. TOTP secrets are encrypted with a key derived from `SECRET_KEY`.
- **Browser sessions** use an HttpOnly, SameSite=Strict, Secure cookie, so scripts can't read the token and it isn't sent cross-site. Sessions last 12 hours and end after 60 minutes idle.
- **API clients** sign in with `"issue_bearer_token": true` and send `Authorization: Bearer …` (30-day tokens).
- **Tokens** are stored only as SHA-256 hashes. Signing out, changing your password, an admin changing your role, or deactivation ends the relevant sessions immediately.
- **Audit:** every sign-in, failure, lockout, invitation, two-factor change and account change is recorded in the audit log.
- **Local development:** set `COOKIE_SECURE=false`, because browsers only send Secure cookies over HTTPS. Production must serve the UI over HTTPS and keep it `true`.

### AI provider

`LLM_PROVIDER` is `disabled` (default), `anthropic` (Claude API, `ANTHROPIC_API_KEY`), or `openrouter`. The `openrouter` option sends the same requests to OpenRouter's Anthropic-compatible endpoint using `OPENROUTER_API_KEY` and `OPENROUTER_MODEL` (default `anthropic/claude-opus-5.5`). Any hosted provider also needs `EXTERNAL_AI_PROCESSING_APPROVED=true`.

Through OpenRouter:
- Requests are pinned to Anthropic as the serving provider, with no fallback to Bedrock, Vertex or Azure, and only to providers that don't collect data.
- Claude's server-side refusal fallback isn't available, so a refused request fails and can be retried.
- OpenRouter becomes an additional processor: name it in the finalist notice (part B) before processing real nominations.
- External research doesn't work through OpenRouter: it rejects Claude's web-fetch results when a paused research turn is sent back. Set `RESEARCH_PROVIDER=anthropic` with an `ANTHROPIC_API_KEY` so research calls Anthropic directly while claims and assessment stay on OpenRouter.
- Research costs are kept down by default: it runs on `RESEARCH_MODEL` (default `claude-haiku-5-5`) at `RESEARCH_EFFORT=medium`, with at most 10 searches and 10 page fetches per run, 10,000 tokens of text kept per page (`research_max_*` in `app/config.py`), and prompt caching so resumed runs re-read fetched pages at cache rates. Set `RESEARCH_MODEL=claude-opus-5-5` for stronger identity and source judgement at a higher cost.

### AI costs

*AI Costs* in the menu (admins only; `GET /api/v1/admin/ai-costs?days=&category_id=`) estimates what each step of the pipeline has cost, for a period and for all categories or one. The steps are claim extraction, research (Claude's reading and reasoning, web searches and web fetches), assessment, and evidence search and reranking, which runs on the server for free. Costs are calculated from the tokens and searches each job records, at Anthropic's list prices in `app/services/ai_costs.py` (update `PRICES` when prices change). The page charts cost per step, highlights the largest, and lists tokens per step, the prices used and the limits of the estimate. It isn't a bill: OpenRouter, negotiated rates and US-only inference are charged differently. Linking research findings to claims isn't recorded yet.

### Tracing (LangSmith)

Set `LANGSMITH_TRACING=true` and `LANGSMITH_API_KEY` (and optionally `LANGSMITH_PROJECT`, default `wob-awards-2026`, and `LANGSMITH_ENDPOINT` for an EU workspace) to trace what the worker is doing. Each research run, claim extraction and assessment run is one trace. Inside it are the steps (each criterion assessed, retrieval, matching sources to claims) and every Claude call, with timing, model, token use and cost, retries and errors.

**Metadata only.** The consent form and the data protection review don't cover LangSmith, so traces never contain prompts, evidence, AI output or error messages. Inputs are reduced to internal IDs, outputs to token counts (plus searches and pages for research), and errors to their type. This is enforced in `app/services/tracing.py`, whatever LangSmith's own settings say, and `tests/test_tracing.py` checks it. To see a run's content, look it up by its ID in the app.

### Data protection controls (Uganda DPPA 2019)

See [docs/operations/data-protection-review.md](docs/operations/data-protection-review.md) for the full review.

- **Consent records.** The coordinator records each finalist's consent on the finalist page, from the signed notice (Appendix A of the review). There are three parts: A, assessment; B, AI processing by Anthropic in the US; C, public-web research. B and C require A. The records are append-only, so a withdrawal is a new record. The system enforces them:
  - uploads need part A only if `UPLOAD_REQUIRES_CONSENT=true` (off by default); an explicit withdrawal of part A always stops uploads
  - claim extraction and AI assessment need part B
  - research needs part C
  - the assessment worker skips finalists without part B and lists them under the run's `skipped`
- **Human ratings.** Reviewers enter ratings for any criterion the AI did not rate. These ratings count in the ranking like approved AI ratings, but are excluded from calibration studies.
- **Human-only assessment.** When AI is switched off, *Start human-only assessment* on the category page creates a run in which reviewers enter every rating.
- **Subject-access export** (s.24). On the finalist page, *Export all data (access request)* produces a ZIP of:
  - the decrypted documents
  - the finalist's individual reports
  - `data.json`, covering consents, claims and reviews, public sources, ratings, rankings, calibration ratings, processors, and an access log with other people identified by role only

  The export is available to admin and secretariat, and each export is audited.
- **Purge** (s.16, s.18). Admins can permanently delete one finalist's data from the finalist page (*Erase all data…*) by giving a reason and typing the finalist's name. The purge deletes, in one transaction:
  - documents, text and embeddings
  - claims, sources and ratings
  - ranking entries, calibration items, consents and reports (category reports too, since they name the finalist)

  Audit events about the finalist keep their action and time, but their details are redacted. Files are deleted after the transaction commits, which destroys their per-file keys (crypto-shredding). The purge is the only path past the database's immutability triggers (`SET LOCAL wob.purge`).
- **Retention.** Admins set a retention date per category on the category page. Schedule `make purge-expired` to run daily; it purges every category past its date.
- **Hiding a category.** An admin can use *Hide category* on a category's page, for example for a test category. A hidden category drops out of category lists, the dashboard, rankings, the knowledge base and the judges' pack. Nothing in it changes or is deleted, its own link still works, and admins still see it, greyed out, on *Award Categories* so they can show it again (`PUT /api/v1/categories/{id}/visibility`, audited).
- **Deleting a category.** To remove a whole category, such as a test category, run `python -m app.cli delete-category CODE` (`make delete-category CODE=…`). On its own it only previews what would go. Add `--yes` (`YES=1`) and it purges every finalist as above, then deletes the category's calibration studies, assessments, rankings, reports, draft rubrics and the category itself, and records `category.deleted` in the audit log. It refuses, before removing anything, if the category has an approved or frozen rubric or a closed calibration study, because the database protects those.

## Database guarantees

The schema enforces these rules from the spec, so a bug in application code can't break them:

| Rule | Mechanism |
|---|---|
| Ratings are integers on their rubric version's scale (1–5 or 0–3) | Triggers check AI, reviewer and calibration ratings and ranking scores against the version's scale |
| No cross-finalist evidence (§5.3, §12) | `finalist_category_id` carried on chunks, claims, citations, with composite FKs |
| Only confirmed documents are indexed (FR-03) | Trigger blocks chunks until `mapping_confirmed_at` is set |
| Originals are immutable (§5.1) | Trigger protects file metadata; documents can't be deleted |
| Frozen rubrics can't change (§7) | Triggers: created as draft; weighted rubrics need every weight before freezing |
| Incomplete criteria aren't silently omitted (§7.2) | Ranking entries carry `criteria_assessed`/`criteria_total`; score and rank are null unless complete |
| Audit trail and ranking snapshots are append-only (FR-12) | `forbid_mutation()` triggers |

Deviation from the spec excerpt: `documents.finalist_category_id` is nullable, so imported files can be stored before an administrator confirms which finalist they belong to.
