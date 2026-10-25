# Data protection review: WOB Awards 2026 evidence and ranking system

| | |
|---|---|
| **Status** | Draft for the data protection officer (DPO) and legal counsel. **Not legal advice.** |
| **Prepared** | 18 October 2026, against the system as built (database migration 0009) |
| **Law assessed** | Data Protection and Privacy Act, 2019 (Uganda) ("the Act"); Data Protection and Privacy Regulations, 2021 (S.I. No. 21 of 2021) ("the Regulations") |
| **Texts used** | The Act: Parliament of Uganda copy, read section by section from a scanned PDF (OCR). The Regulations: a third-party published copy. Counsel should confirm wording against the official gazetted texts. |
| **Decision needed** | Whether, and on which conditions, real nomination data may be loaded, and whether `EXTERNAL_AI_PROCESSING_APPROVED` may be switched on. |

## 1. Summary

The system can be operated lawfully, but **not yet**. Before any real nomination data is loaded:

1. **A lawful basis must be secured for each finalist.** Section 7 permits processing without consent only in listed cases (law, public duty, contract, medical purposes, legal obligation). An awards evaluation by a private body fits none of them clearly. Unlike the GDPR, the Act has no general "legitimate interests" basis. The safe course is informed, recorded **consent from each finalist**, covering AI-assisted assessment, cross-border processing and public-web research (§4.1). Counsel may instead conclude that the awards entry terms form a contract (s.7(2)(c)), but that needs a positive legal view.
2. **Cross-border processing must rest on consent.** Claim extraction, assessment and web research send evidence text to Anthropic in the United States. The Personal Data Protection Office (PDPO) has not published the adequacy list provided for in Regulation 30(4), so the WOB would have to *prove* US adequacy itself (Reg 30(5)). Consent under s.19(b) / Reg 30(1)(b) is the practical route, and Reg 30(3) requires a form suited to the data. Without consent, the AI features must stay off. Everything else (upload, indexing, search, human review, ranking, reports) runs on infrastructure the WOB controls and transfers nothing abroad.
3. **The organisation must register with the PDPO** (s.29, Reg 15; renewed every 12 months, Reg 20), **designate a DPO** (s.6, Reg 47), and complete a **data protection impact assessment** (Reg 12). This review can serve as the basis for that assessment.
4. **The system needed three additions**, now built (October 2026):
   - **(a) Retention and secure deletion.** Records cannot currently be deleted, by design (s.18(4)–(5)).
   - **(b) Data-subject access export** (s.24, Reg 35: a decision within 7 days).
   - **(c) Per-finalist consent records** that the AI and research features check before running.

   All three are implemented. See the *Implemented* notes in §4.1, §4.5 and §4.10.
5. **Hosting must provide** encryption of the database at rest, TLS, backups, and a hosting location decision (§4.8).

Strong points already in place: the AI features are switched off by default; files are encrypted at rest; there is two-factor sign-in with role-based access and a full audit trail; the AI is advisory with mandatory human review (s.27); and every AI output is checked against the source evidence.

## 2. The processing

### 2.1 Purpose
To assist the judging committee of the Women on Boards Awards 2026 in assessing shortlisted finalists against approved criteria. The system organises submitted evidence, extracts and verifies factual claims, proposes advisory ratings with citations, and produces provisional rankings and deliberation reports. **The committee makes all decisions.** No winner is selected automatically.

### 2.2 People whose data is processed

| Data subjects | Data | Source |
|---|---|---|
| **Finalists** | Name, organisation, position. Nomination forms, CVs, reference letters, board records, photos. Extracted text and claims. Ratings, rationales, rankings and reports about them. Public-web findings about them. | Nominators (often third parties), the finalists themselves, public websites |
| **Third parties named in evidence** (referees, colleagues, co-directors) | Names, roles and opinions contained in documents | The same documents, incidentally |
| **System users** (secretariat, reviewers, judges, committee) | Name, email, role, password hash, encrypted two-factor secret, sign-in times, IP address and browser of sessions, audit trail of their actions | The users themselves and the system |

**Special personal data (s.9).** Health, financial information, religious or political beliefs and sexual life may appear incidentally, for example personal finances in a CV or health in a reference letter. The system does not seek these categories. The research prompt forbids recording sensitive attributes. Section 9(3)(b) permits processing such data with freely given consent, which the consent in Appendix A should cover expressly, and nominators should be asked not to include it.

### 2.3 Data flows and recipients

| Flow | What leaves WOB control | Where | Status |
|---|---|---|---|
| Upload, malware scan (ClamAV), text extraction and OCR (Tesseract), embeddings (nomic, local) and reranking (jina, local) | Nothing. Models run on WOB servers. | WOB hosting | On |
| **Claim extraction, criterion assessment** (Claude, Anthropic) | Finalist name, category, evidence passages, claims | Anthropic, United States | **Off** until approval |
| **External research** (Claude web search and fetch) | Finalist name, organisation, claims; search queries reach search providers through Anthropic | Anthropic, United States, plus web search providers | **Off** until approval and `RESEARCH_ENABLED` |
| Voyage AI embeddings and reranking (optional alternative) | Evidence passages | Voyage AI, United States | Off, not configured |
| Model and virus-signature downloads (Hugging Face, ClamAV) | No personal data. Ordinary download requests only. | United States / EU | On |

## 3. How the system is built: controls relevant to the Act

| Control | Implementation |
|---|---|
| Access control | Invitation-only accounts with five roles; every API endpoint checks the role. Judges and committee members can read but not change evidence; only admins manage users. (`app/security/auth.py`) |
| Authentication | Argon2id passwords (8 characters or more); accounts lock after 5 failures; sign-in errors are uniform, so they don't reveal whether an account exists; two-factor (TOTP) is required for admin and committee roles; HttpOnly, SameSite=Strict session cookies with a 12-hour lifetime and 60-minute idle timeout; tokens are stored only as hashes. (`app/security/accounts.py`) |
| Encryption at rest, files | Each file has its own AES-256-GCM key, wrapped by a master key held outside the database and storage. Each file is bound to its storage path; any tampering is detected. Key rotation and a verification command are provided. (`app/services/storage.py`) |
| Encryption at rest, database | **Not provided by the application.** Extracted text, claims and ratings sit in PostgreSQL. This must come from the hosting platform (encrypted disks or a managed database). |
| Encryption in transit | **Deployment responsibility:** TLS on all public endpoints; database connections inside a private network. |
| Audit trail | Append-only, enforced by the database: uploads, downloads, searches, reviews, rankings, reports, every sign-in and account change. (`audit_events`) |
| Integrity | Originals are immutable with SHA-256 fingerprints; ranking snapshots are append-only; reports record their fingerprints. |
| Isolation | Retrieval is filtered to one finalist before search; database constraints stop evidence or citations crossing between finalists. |
| AI safeguards | Off by default. A double switch: provider plus approval flag, with a separate switch for web research. Prompts treat evidence and web pages as untrusted data. Every quote is verified against its source; unverifiable output is discarded. Ratings of 2 or more cannot be approved without a verified citation. |
| Human decision (s.27) | AI ratings are proposals. Reviewers approve, adjust or reject each one. Rankings are labelled provisional and advisory, and the committee approves winners. |
| Minimisation | Evidence is limited to the finalist's own submission and accepted public sources. Social and user-generated sites are excluded from research. The research prompt forbids private-life research. |

## 4. Assessment against the Act and Regulations

### 4.1 Lawful basis: consent (s.7, s.2)
- **Requirement:** prior consent, "freely given, specific, informed and unambiguous" (s.2), unless an exception in s.7(2) applies. Where consent is the basis, a data subject's objection stops processing (s.7(3); Reg 10).
- **Assessment:** no s.7(2) exception clearly applies to a private awards body. Regulation 10(2)(b)–(3) mentions "legitimate interest", but only as a limit on the right to object, and the burden of proof lies on the controller (Reg 10(4)). It is not a free-standing basis in s.7.
- **Action:**
  1. Obtain each finalist's written consent (Appendix A) before their data is loaded.
  2. Keep separate, optional consents for AI-assisted processing abroad and for public-web research, offering a fully human assessment to anyone who declines. This keeps consent "freely given" and avoids disadvantaging those who decline.
  3. **System change:** record consent per finalist (date, version of the notice, scope) and have the extraction, assessment and research features refuse to run for finalists without the matching consent.
   - *Implemented.* Records are append-only (`finalist_consents`) and capture the notice version, method and who recorded them. Uploads need part A when `UPLOAD_REQUIRES_CONSENT=true` (off by default: turn it on before real nominations are loaded; a recorded withdrawal always blocks uploads), claim extraction and AI assessment need part B, and research needs part C. Finalists without part B are skipped by the AI assessment and rated by humans instead, which keeps consent freely given.

### 4.2 Collection from others and notice (s.11, s.13)
- **Requirement:** collect directly from the data subject unless s.11(2) applies, for example consent to collection from another source (s.11(2)(c)). Before collection, or as soon as practicable when the data comes from a third party (s.13(2)), inform the person of the items in s.13(1): nature of the data, who is collecting it, purpose, whether supplying it is voluntary, consequences of not supplying it, recipients, rights of access and correction, and retention period.
- **Assessment:** nominations are often submitted by others, and documents name third parties.
- **Action:**
  - Give each finalist the notice in Appendix A as soon as they are shortlisted, before upload.
  - Ask nominators to include third parties' details only where necessary, and to confirm that referees agreed to provide references.

### 4.3 Special personal data (s.9)
- **Assessment:** this data is incidental, not sought. Section 9(3)(b) allows processing with freely given consent.
- **Action:** cover it in the consent wording; ask nominators not to include it; reviewers should withdraw documents containing unnecessary special data. (The withdrawal function exists; withdrawn documents leave the knowledge base.)

### 4.4 Purpose, minimality and quality (s.12, s.14, s.15, s.17)
- **Assessment:**
  - **Purpose:** one specific purpose, the 2026 awards assessment, and the system processes nothing else.
  - **Minimality:** evidence is limited to the submission and accepted public sources.
  - **Quality:** claims are verified by reviewers, and quotes are checked mechanically against sources.
- **Action:** use the data for no other purpose, for example marketing or future awards, without new consent (s.17).

### 4.5 Retention and destruction (s.18)
- **Requirement:** keep data no longer than necessary (s.18(1)). Data used to make a decision about a person must be kept long enough to let them request access (s.18(3)(b)). At the end of the period, destroy, delete or de-identify it so it cannot be reconstructed (s.18(4)–(5)).
- **Gap:** the system makes originals, audit events and ranking snapshots **impossible to delete** (protections against tampering), and has no retention schedule or purge tool.
- **Action:**
  1. The committee sets a retention schedule. Suggested: evidence and derived data until N months after the awards are announced and any appeal window has closed; anonymised results and audit metadata for longer, if justified.
  2. **System change:** a controlled, audited purge that deletes a finalist's files, which also destroys their per-file keys and makes the ciphertext unrecoverable. It must also delete the extracted text, embeddings, claims, assessments and reports, and de-identify audit records. It should run through an admin command that deliberately bypasses the immutability rules and logs itself.
   - *Implemented.* There are two routes:
     - An admin can purge a single finalist from the UI, giving a reason and typing the name to confirm.
     - `make purge-expired` (run daily) purges every category whose retention date (set by an admin) has passed.

     Audit records keep the action and time, but their details are redacted. Files are crypto-shredded after commit. Action 1 (the committee's schedule) is still open.

### 4.6 Cross-border processing (s.19, Reg 30)
- **Requirement:** processing or storage outside Uganda is allowed only if the WOB can *demonstrate to the PDPO* either adequate protection, at least equivalent to the Act, in the destination country, or the data subject's consent (Reg 30(1)). Consent must be "in manner and form" suited to the data (Reg 30(3)). Onward transfer to a third country needs *express* consent (Reg 30(2)). If the destination isn't on the PDPO's list, the controller must prove adequacy (Reg 30(5)).
- **Assessment:**
  - The PDPO adequacy list has, as far as published sources show, not been issued.
  - The United States has no general federal data protection law equivalent to the Act, so adequacy would be hard to show.
  - In July 2025 the PDPO found Google in breach partly for failing to demonstrate safeguards on cross-border transfers, so the office is actively scrutinising this.
- **Action:**
  1. Rely on **consent** for the Anthropic processing (Appendix A, part B), and record it.
  2. Keep a transfer record for the PDPO: what is sent, why, to whom, the safeguards, and the consents held.
  3. **Verify in Anthropic's current commercial terms and data processing addendum:**
     - how long API inputs and outputs are retained, and whether zero-data-retention is available to the WOB
     - confirmation that API data isn't used for model training
     - the sub-processors and their locations (onward transfers, Reg 30(2))
     - the data-processing terms required by s.21(2)
  4. Decide the **hosting location** of the system itself. A server outside Uganda, for example a cloud region in South Africa, is itself processing outside Uganda, and the same rule applies. Hosting in Uganda avoids the question for the core system.

### 4.7 Processors (s.21, s.22)
- **Requirement:** a written contract requiring the processor to maintain confidentiality and security (s.21(2)); processors act only on the controller's authority (s.22).
- **Action:** data processing agreements with the hosting provider and, if AI features are used, with Anthropic. Also with any IT contractor who operates the system.

### 4.8 Security (s.20, Reg 31–32)
- **Requirement:** appropriate technical and organisational measures. Identify risks, maintain safeguards, verify them regularly, and update them (s.20(2)). Follow generally accepted practice (s.20(3)).
- **Assessment:** application controls are strong (§3).
- **Remaining deployment items:**
  - TLS everywhere
  - an encrypted database volume or managed encrypted database
  - **encrypted, tested backups**, with the file-encryption keys backed up *separately* (losing the keys loses every file)
  - a secrets manager for `SECRET_KEY` and `FILE_ENCRYPTION_KEYS`
  - rate limiting at the reverse proxy
  - monitoring and alerts
  - OS and container patching
  - a penetration test before the pilot (spec §14 sprint 5)
- **Organisational:**
  - a confidentiality undertaking from every user
  - a least-privilege role assignment
  - prompt deactivation when people leave
  - a periodic access review: the Users page lists roles and last sign-in

### 4.9 Breach notification (s.23, Reg 33)
- **Requirement:** if personal data may have been accessed or acquired by an unauthorised person, notify the PDPO **immediately** (Reg 33(1)), not within a fixed window such as the GDPR's 72 hours. Use Form 7 with the content in Reg 33(3): nature of the breach, the data affected, the categories and approximate number of people affected, likely consequences, remedial measures, and DPO contact. The PDPO then decides whether and how the affected people are told (s.23(2)–(3)).
- **Action:** a written incident procedure naming who decides and who files Form 7. The audit log, session records and access logs support investigation. The ability to revoke all sessions and rotate keys exists.

### 4.10 Rights of data subjects (s.16, s.24–s.28; Reg 35–39)

| Right | Time limit | System support | Gap |
|---|---|---|---|
| Access (s.24, Reg 35) | Decision within 7 days (Reg 35(3)); comply within 30 days (s.24(9)) | Data exists and is traceable per finalist *Implemented:* one-click ZIP export (admin and secretariat) covering documents, reports, consents, claims, reviews, sources, ratings, rankings, calibration ratings, processors and an access log, with other people identified by role only (s.24(4)). Each export is audited. |
| Correction and deletion (s.16, Reg 29, Reg 39) | Within 30 days (Reg 39(2)) | Withdraw documents; correct claims through review | Deletion via the purge tool (§4.5), *implemented* |
| Prevent processing (s.25, Reg 36) | Reply within 14 days | Stopping is possible: withdraw evidence, skip the finalist | Procedure only |
| Automated decision-taking (s.27, Reg 38) | Reply within 14 days | **Satisfied by design:** no decision is based solely on automated processing; reviewers check every rating and the committee decides | Keep this true in practice; record committee decisions |
| Complaints (s.31, Reg 40) | — | — | Publish a contact point (the DPO) in the notice |

### 4.11 Registration and DPO (s.6, s.29; Reg 15, 20, 47)
- **Action:**
  - Register the WOB with the PDPO as a data collector/controller (Form 2), stating the nature and purpose of the processing. Registration is valid for 12 months (Reg 20), so renew it.
  - Designate a DPO (s.6). Their duties under Reg 47(3) include audits, a record of processing activities (this document is a start), and handling data-subject requests.

### 4.12 Data protection impact assessment (Reg 12)
- **Requirement:** where processing poses a high risk to people's rights and freedoms, assess the impact *before* processing. The assessment must include a description of the processing, the risks, and the measures to address them.
- **Assessment:** AI-assisted evaluation of named individuals, cross-border transfer and public-web research together make this likely high risk.
- **Action:** the DPO adopts §2–§5 of this document, with their own risk ratings, as the impact assessment and signs it off before the pilot.

## 5. Risk register

| # | Risk | Likelihood | Impact | Mitigation in place | Residual action |
|---|---|---|---|---|---|
| R1 | Processing without a valid lawful basis | High without action | High | AI off by default | Consent per finalist (§4.1); system-enforced consent records |
| R2 | Unlawful cross-border transfer to Anthropic | High if AI enabled without consent | High | Double opt-in switches | Consent; transfer record; DPA (§4.6) |
| R3 | AI produces inaccurate or unfair statements about a finalist | Medium | High | Quotes verified mechanically; uncited ratings blocked; human review; advisory labelling | Calibration against human reviewers (FR-15) before relying on ratings |
| R4 | Web research finds a namesake, or private or irrelevant information | Medium | Medium | Identity confidence, reviewer confirmation required, social media excluded, private life excluded | Reviewer training |
| R5 | Unauthorised access to evidence | Low–medium | High | MFA, roles, lockout, session controls, audit, file encryption | TLS, database encryption, patching, pen test |
| R6 | Loss of keys or data | Low | High | Keys separate from data | Separate key backup; restore tests |
| R7 | Data kept longer than necessary | High without action | Medium | — | Retention schedule and purge tool (§4.5) |
| R8 | Cannot answer an access request in time | Medium | Medium | Traceable per-finalist data | Export tool (§4.10) |
| R9 | Prompt injection in submitted or web documents | Medium | Medium | Untrusted-data prompts; outputs constrained to a schema and verified; no tool access to systems | Include in pilot tests (spec §13) |
| R10 | Third parties named in documents unaware of processing | Medium | Low | Minimisation guidance | Nominator guidance; referee confirmation |

## 6. Action plan

**Before any real nomination data is loaded**

| Action | Owner |
|---|---|
| Designate DPO; register with PDPO | WOB leadership |
| Adopt this review as the impact assessment (Reg 12), with DPO risk ratings | DPO |
| Approve the finalist notice and consent (Appendix A) and collect consents | DPO and secretariat |
| Decide the hosting location (Uganda or abroad, see §4.6) and sign a DPA with the host | Leadership and IT |
| Deploy with TLS, an encrypted database volume, encrypted backups, keys in a secrets manager, and proxy rate limiting | IT |
| Set the retention schedule | Committee and DPO |
| Write the breach procedure (Form 7, immediate notification) | DPO |
| ~~Build: consent records gating AI features, purge tool, access-request export~~ (done) | Engineering |

**Before switching on AI features** (`LLM_PROVIDER=anthropic`, `EXTERNAL_AI_PROCESSING_APPROVED=true`)

| Action | Owner |
|---|---|
| Consent for cross-border AI processing held for every finalist processed (system-enforced) | Secretariat |
| Anthropic terms verified: retention, zero-data-retention option, training use, sub-processors; DPA signed | DPO and legal |
| Transfer record prepared for the PDPO | DPO |
| Calibration of AI ratings against human reviewers in the pilot (FR-15) | Committee and engineering |

**Before switching on web research** (`RESEARCH_ENABLED=true`): everything above, plus research consent and reviewer guidance on identity confirmation.

## Appendix A: draft notice and consent for finalists

*To be adapted and approved by the DPO and counsel. It covers the items required by s.13(1).*

> **How the Women on Boards Awards 2026 will use your information**
>
> **Who we are.** [WOB legal name, address], contact: [DPO name, email].
>
> **What we collect.** Your name, organisation and position, and the nomination materials submitted for you (nomination form, CV, letters, board records and similar). These may have been provided by your nominator. We also record our reviewers' assessments of that material.
>
> **Why.** Only to assess your nomination for the [category] award in 2026. Judges deliberate and the awards committee decides; no decision is made automatically.
>
> **Is it required?** Providing information is voluntary, but we cannot assess a nomination without supporting evidence.
>
> **Who receives it.** The awards secretariat, evidence reviewers, judges and committee members, and our hosting provider [name, country]. If you agree in part B, also Anthropic PBC (United States).
>
> **How long we keep it.** Until [date / N months after the awards are announced and any appeal is closed]. It is then deleted beyond recovery, except [anonymised statistics].
>
> **Your rights.** You can ask what we hold about you and who has seen it, ask us to correct or delete it, object to processing, and ask that no decision about you is based solely on automated processing. Contact [DPO]. You may complain to the Personal Data Protection Office.
>
> **A. Assessment.** I consent to the processing of my personal data, including any health, financial or other special personal data contained in my nomination materials, for the assessment of my nomination as described above. ☐
>
> **B. AI-assisted assessment (optional).** I consent to my nomination materials being processed by an AI service operated by Anthropic PBC in the United States, to extract factual claims and propose advisory ratings that human reviewers check. I understand the US does not have data protection law equivalent to Uganda's. If I do not consent, my nomination will be assessed by human reviewers only, with no disadvantage. ☐
>
> **C. Public-source checks (optional).** I consent to the awards using an AI web-research service (Anthropic PBC, United States) to look for public information confirming my professional claims, such as company websites, registries and news. Personal social media and private life are excluded. ☐
>
> Name, signature, date. Notice version [v1].

## Appendix B: sources

- Data Protection and Privacy Act, 2019 (Uganda), Parliament of Uganda copy: <https://bills.parliament.ug/attachments/Data%20Protection%20and%20Privacy%20Act%202019.pdf>; also on ULII: <https://www.ulii.org/akn/ug/act/2019/9>
- Data Protection and Privacy Regulations, 2021 (S.I. No. 21 of 2021), published copy: <https://pmlawhub.com/wp-content/uploads/2025/12/Data-Protection-and-Privacy-Regulations-SI-No-21-of-2021-Uganda-1.pdf>
- DLA Piper Africa, "Uganda's Data Protection regulator clarifies compliance requirements for offshore entities" (2025), on the unpublished adequacy list: <https://www.dlapiperafrica.com/en/uganda/insights/2025/CLIENT-ALERT>
- CIPESA, "Ugandan Regulator Finds Google in Breach of Country's Data Protection Law" (July 2025): <https://cipesa.org/2025/07/ugandan-regulator-finds-google-in-breach-of-countrys-data-protection-law-orders-local-registration/>
- Cliffe Dekker Hofmeyr, "To register or not to register" (2025), on the PDPO Google decision: <https://www.cliffedekkerhofmeyr.com/en/news/publications/2025/Sectors/Technology-Communications/technology-and-communications-alert-13-august-to-register-or-not-to-register-the-ugandan-personal-data-protection-offices-decision-on-the-registration-of-data-controllers>
- DLA Piper, Data Protection Laws of the World: Uganda: <https://www.dlapiperdataprotection.com/?t=law&c=UG>
