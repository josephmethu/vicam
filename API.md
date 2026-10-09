# API contract

The website and API run on the same origin. JSON requests use `Content-Type: application/json`. Cross-origin browser writes are rejected. Request bodies are limited to 32 KiB. No public endpoint returns stored client records.

## Public endpoints

| Method | Route | Purpose |
|---|---|---|
| GET | `/api/health` | Database connectivity status |
| GET | `/api/public/config` | Submission availability and configured public company email |
| POST | `/api/enquiries` | Validate and durably store a brief |

Example body:

```json
{
  "name": "Example Client",
  "email": "client@example.com",
  "service": "CCTV & Surveillance",
  "requirements": "Plan camera coverage for the entrance and parking area.",
  "organization": "Example Organization",
  "phone": "",
  "timeline": "Within 1–3 months",
  "site_type": "Office or business premises",
  "existing_system": "No existing cameras",
  "coverage_areas": "Entrance and parking",
  "consent": true,
  "website": ""
}
```

`name`, `email`, `service`, `requirements` and explicit `consent: true` are required. Name: 2–100 characters; email: maximum 150; requirements: 10–4000. Optional organization: 120; phone: 40; timeline: 80; site type and existing system: 100 each; coverage: 1000. Text is trimmed. Extra fields are rejected. The `website` spam field must be empty. Site/coverage details are discarded for non-CCTV services.

Allowed services: Education & Student Performance, CCTV & Surveillance, Cybersecurity, Cloud & Infrastructure, Managed IT Support, Software Development, Data & AI, Not sure yet.

Success returns HTTP 201 with a reference and receipt message. It does not confirm notification delivery. The frontend sends a UUID `X-Idempotency-Key`; retrying an unchanged brief with that key returns the same receipt. Reusing a key for changed contents returns 409. If no key is sent, each POST creates a new submission.

Public submissions are limited to 10 per hour per connecting address. Validation failures do not persist records. Payload-too-large: 413; validation: 422; rate limit: 429; cross-origin write: 403.

## Staff endpoints

| Method | Route | Purpose |
|---|---|---|
| POST | `/api/auth/login` | Email/password sign-in; sets HttpOnly session cookie |
| GET | `/api/auth/me` | Staff email, current CSRF token, email readiness, can_issue_documents and pdf_signing_mode |
| POST | `/api/auth/logout` | Revoke current session |
| GET | `/api/admin/enquiries` | Search/paginate brief summaries |
| GET | `/api/admin/enquiries/{id}` | Full brief, notes and delivery state |
| PATCH | `/api/admin/enquiries/{id}` | Update status |
| POST | `/api/admin/enquiries/{id}/notes` | Add a private note |
| POST | `/api/admin/enquiries/{id}/retry-notification` | Requeue an email alert when configured |
| DELETE | `/api/admin/enquiries/{id}` | Permanently delete the brief and related records |

Login body: `{"email":"staff@example.com","password":"your-own-password"}`. There are no default credentials. Sign-in is limited to five attempts per account/address per 15 minutes and 30 per address per 15 minutes. A successful login also consumes an attempt.

All private requests require the session cookie. Private writes also require `X-CSRF-Token` from login or `/api/auth/me`. The dashboard keeps this token in memory, not browser local storage. Staff sessions expire and disabled accounts immediately lose access.

Inbox query parameters: `q` (maximum 100 characters), `status` (new, in_progress, waiting, closed), `page` (integer >=1). Each page contains at most 25 records. Response: `items`, `total`, `page`, `page_size`.

Status body: `{"status":"in_progress"}`. Note body: `{"text":"Arrange an initial site discussion."}` (1–2000 characters). Notification retry accepts `{}`. A notification already being sent cannot be requeued. Stored notes are treated as text in the UI.

No API accepts file attachments or student-assessment imports. OpenAPI/Swagger UI is disabled in this starter.

## Client management endpoints (v2)

All routes below require the same active staff session. All writes require `X-CSRF-Token`. `POST` and `PUT` require JSON. Each kind is restricted to: `clients`, `projects`, `tasks`, `quotes`, `invoices`, `payments`, `tickets`, `contracts`.

| Method | Route | Purpose |
|---|---|---|
| GET | `/api/admin/crm/summary` | Active client/project counts, due tasks, open tickets, ending/expired contracts |
| GET | `/api/admin/crm/staff` | Active staff IDs and email addresses for assignments |
| POST | `/api/admin/crm/convert/{enquiry_id}` | Link an enquiry to a client; `{}` creates a profile, `{"client_id":"..."}` links an existing one |
| GET | `/api/admin/crm/{kind}` | Search and paginate records |
| GET | `/api/admin/crm/{kind}/{id}` | Full record; client details include linked enquiry summaries |
| POST | `/api/admin/crm/{kind}` | Create a record (201) |
| PUT | `/api/admin/crm/{kind}/{id}` | Replace editable fields; send all fields to retain optional values |
| DELETE | `/api/admin/crm/{kind}/{id}` | Permanently delete an unreferenced record |

List parameters: `q` (100 characters max), `page` (1+, 25 per page), optional `client_id`; `invoice_id` is available only on payments. `due_only=true` is available only on tasks. The response contains `items`, `total`, `page`, `page_size`. Invoices include calculated `paid_minor`, `balance_minor` and `payment_status`; tasks include `overdue`. Full model definitions and bounds are in `app/crm.py`.

Common client-linked fields: `client_id`, `title` (2–160 chars), `description` (0–4000 chars). Records have generated immutable `id`, `reference`, `created_at`, `updated_at`; do not submit those fields. Extra fields are rejected. All dates use `YYYY-MM-DD`. Optional dates, projects and assigned staff use `null` rather than an empty string. Contract end date must be on or after start date.

Client example:

```json
{"name":"Example Client","email":"client@example.com","organization":"Example Firm","phone":"","notes":"Discuss support requirements.","status":"active"}
```

Project example:

```json
{"client_id":"CLIENT_ID","title":"Office network","description":"Network setup and support.","status":"active","assigned_to":1,"due_date":"2026-11-01"}
```

Tasks have `due_date` (required), `assigned_to`, optional `project_id`, and status open/done/cancelled. Tickets have optional `project_id`, `assigned_to`, priority low/normal/high/urgent, and status open/in_progress/waiting/resolved. Projects use planned/active/on_hold/completed/cancelled. Clients use active/archived. Contracts add `start_date`, `end_date`, `assigned_to`, and draft/active/ended/cancelled status.

Invoice example:

```json
{"client_id":"CLIENT_ID","project_id":null,"title":"Office support","description":"Annual support scope and pricing notes.","amount_minor":12345,"currency":"KES","status":"issued","due_date":"2026-11-01"}
```

Quotes use the same amount/currency fields with draft/sent/accepted/declined/expired status. Invoice status is draft/issued/void. `amount_minor` must be a JSON integer from 1 to 999999999999. Currency is KES/USD/EUR/GBP; this value uses hundredths. No tax or currency conversion is performed.

Payment example:

```json
{"invoice_id":"INVOICE_ID","amount_minor":2345,"paid_date":"2026-10-02","method":"mpesa","external_reference":"YOUR-REAL-RECEIPT-REFERENCE"}
```

Methods: bank_transfer/mpesa/cash/card/other. Receipt reference: 1–100 characters, unique per invoice. Payment currency comes from its invoice. An issued invoice and sufficient outstanding balance are required. Editing a payment recalculates its effect on the balance. Once an invoice has payments, changing its total, currency, client or status returns 409. Deleting a referenced client/project/invoice returns 409. A project can only be linked to records belonging to the same client; invalid links return 409 or 404. Unknown record kinds return 404. Invalid model fields return 422.

No route collects funds, emails documents, sends task reminders or creates legally signed contracts. The dashboard is `/admin/clients`.

## Document verification (v2.2, schema 4)

| Method | Path | Behavior |
|---|---|---|
| POST | `/api/admin/documents/{kind}/{id}/copies` | Issuer + CSRF; snapshot, QR and unsigned draft PDF (201) |
| POST | `/api/admin/documents/{kind}/{id}/signed-pdf` | Issuer + CSRF; snapshot, QR and certified original PDF (201) |
| GET | `/api/admin/documents/{kind}/{id}/copies` | Staff; copy history with hash and signing mode |
| GET | `/api/admin/documents/copies/{copy_id}/pdf` | Staff; original PDF download, including withdrawn originals |
| POST | `/api/admin/documents/copies/{copy_id}/revoke` | Issuer + CSRF; withdraw public verification |
| GET | `/api/verify/{token}` | Public bearer link; saved snapshot/warning and available PDF metadata |
| GET | `/api/verify/{token}/pdf` | Public bearer link; original current/earlier PDF, 410 if withdrawn/unavailable |

Kinds: `quotes`, `invoices`. Issuing POSTs use `{}`; snapshots always come from stored records. Responses include `id`, `issued_at`, `snapshot`, `fingerprint`, `verification_url`, `qr_data_uri`, `local_only`, `download_url`, `pdf_sha256`, `signing_mode`, `certificate_sha256`. Signing modes: disabled (unsigned draft), test (untrusted local identity), certificate. Signed issuance requires quotation sent/accepted or invoice issued. Signing disabled, generation/signing failure, inappropriate status or void invoice: 409; missing issuing permission: 403; unknown record/token: 404. Failures roll back both snapshot and PDF.

Verification states: current, superseded, withdrawn, unavailable. Current/superseded include immutable snapshot, record fingerprint, issued time, current status and message. New copies also include original PDF SHA-256, signing mode, certificate fingerprint and public download URL. Earlier versions retain original bytes. Withdrawal/voiding/deletion hides public details and prevents public PDF downloads. Corrupted snapshot/PDF is unavailable. Pre-v2.2 records still verify but have no stored PDF.

Public checks/downloads share a 120/IP/hour limit. Responses use no-store/no-referrer/noindex. No public search exists. The stored PDF contains the raw QR bearer URL even though the lookup uses a hashed token. Avoid tokens in logs/analytics. Protect PDFs, databases and backups.

A local SHA-256 comparison checks byte identity with the saved original. Certificate identity, chain trust, revocation and allowed modifications are separately assessed in a compatible PDF reader. Withdrawal updates online business status; it cannot retroactively alter a downloaded signature. This baseline PAdES certification has no trusted timestamp or embedded long-term validation evidence.

## Client experience (v2.3, schema 5)

All `/api/admin/experience/*` endpoints use the existing staff session and CSRF header. Client endpoints use a separate `vicam_client_session` HttpOnly/SameSite cookie and their own `X-CSRF-Token`. CSRF is returned by client login/activation/me. Origin checks apply to writes. Authentication responses and private pages are not cached.

| Endpoint | Purpose |
|---|---|
| GET `/api/admin/experience/follow-ups` | Computed staff follow-up queue |
| GET `/api/admin/experience/clients/{id}/access` | Portal account/invitation status |
| POST `/api/admin/experience/clients/{id}/invite` | `{email}` -> one-time activation/reset URL (24 hours) |
| POST `/api/admin/experience/clients/{id}/revoke-access` | Disable accounts, delete sessions and invites |
| GET/PUT/DELETE `/api/admin/experience/projects/{id}/progress` | Read/publish/unpublish stage, summary, next_milestone, waiting_on, target_date |
| POST `/api/admin/experience/clients/{id}/documents` | Share `{copy_id}` of a current eligible original PDF |
| DELETE `/api/admin/experience/clients/{id}/documents/{copy_id}` | Remove portal access |
| GET `/api/admin/experience/decisions?client_id=...` | Recorded quotation responses |
| GET/POST `/api/admin/experience/tickets/{id}/messages` | Public conversation; POST `{text}` |
| GET/POST `/api/admin/experience/clients/{id}/files` | List/share files |
| GET `/api/admin/experience/files/{id}/download` | Download attachment |
| DELETE `/api/admin/experience/files/{id}` | Permanently remove file |
| GET/POST `/api/admin/experience/case-studies` | List/create project examples |
| PUT/DELETE `/api/admin/experience/case-studies/{id}` | Edit/delete example |
| GET `/api/public/case-studies` | Only published, permission-confirmed examples |
| POST `/api/client/activate` | `{token,password}` -> consume invite and establish client session |
| POST `/api/client/login` | `{email,password}` -> client session |
| GET `/api/client/me` | Client display profile and CSRF |
| POST `/api/client/logout` | End session |
| GET `/api/client/projects` | Own explicitly published progress |
| GET `/api/client/documents` | Own shared PDFs and recorded balances/decisions |
| GET `/api/client/documents/{copy_id}/pdf` | Authorized original PDF |
| POST `/api/client/documents/{copy_id}/decision` | `{action: accept\|request_changes,message}`; current sent quote only |
| GET/POST `/api/client/tickets` | Own requests / `{title,description,priority,project_id}` |
| GET/POST `/api/client/tickets/{id}/messages` | Own public conversation / `{text}` |
| GET/POST `/api/client/files` | Own attachments / upload |
| GET `/api/client/files/{id}/download` | Ownership-protected attachment |

File upload payload: `{name,content_base64,project_id: null|ID}`; the only larger JSON endpoints have a 2,850,000-byte body cap. File bytes are capped at 2 MB, stored total at 50 MB/client. Other writes retain their 32 KB cap. Project ownership is enforced. Downloads are attachment/octet-stream with no-store and nosniff.

Case payload: `{title,service,problem,solution,result,published,permission_confirmed}`. Publishing without confirmed permission returns 422. Enquiry payload accepts optional `service_context` (max 1,000 characters) for service-specific answers; old enquiry clients remain compatible.


## Education pilot (v2.8.0)

All routes require an administrator session; writes require X-CSRF-Token. Schools are scoped to their creating administrator.

- GET/POST `/api/admin/education/schools`
- PUT `/api/admin/education/schools/{school_id}` (name, target)
- GET `/api/admin/education/schools/{school_id}/workspace`
- POST `/api/admin/education/schools/{school_id}/students` (code, name, class_name)
- PUT/DELETE `/api/admin/education/schools/{school_id}/students/{student_id}`
- POST `/api/admin/education/schools/{school_id}/subjects` (name)
- POST `/api/admin/education/schools/{school_id}/assessments` (subject_id, title, topic, class_name, assessed_on, max_score)
- GET/PUT `/api/admin/education/schools/{school_id}/assessments/{assessment_id}/results`
- GET `/api/admin/education/schools/{school_id}/progress`

Results accept `{"items":[{"student_id":"...","score":25}]}` (up to 200 rows). A null score removes a result; omitted students remain unchanged. Rows are all validated before writing. Cross-school and wrong-class references are rejected. Read EDUCATION_PILOT.md for calculation limits.
