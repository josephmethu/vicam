# VICAM v2.8.2 — gentle hero introduction

Removed the hero pause/play button. The ribbon makes one gentle 4.5-second movement and settles into a still image; reduced-motion preferences keep it still from the start. The working education pilot is included.

# VICAM v2.8.1 — integrated hero motion control

The hero now uses a compact corner pause/play control with icons, a 44 px minimum tap target and reduced-motion support. The working education pilot from v2.8.0 is included.

# VICAM v2.8.0 — working education pilot

New: protected school records, student/class setup, subjects, assessments, marks entry/correction, progress summaries and teacher-review prompts at `/admin/education`. Uses the existing Python + SQLite backend. Read **EDUCATION_PILOT.md** for PowerShell setup, limitations and upgrade steps.

# VICAM Backend & Client Management — v2.7.4

New in v2.7.4: service cards and opened service pages use matching 3D product illustrations, short introductions, concise detail cards and a working project CTA. Service pages support a subtle float with reduced-motion handling and mobile stacking. The generated illustration atlas is bundled in static/assets/service-artwork.png; separate service illustrations are displayed using SVG viewports. No operational features were removed.

New in v2.7.3: reduced green across the public website and education page. Larger controls and screen graphics now use charcoal and silver/slate; teal is muted and reserved for small accents. The soft-yellow primary hero actions and education mascot screen are preserved.

New in v2.7.2: the integrated website includes the latest education lessons: elementary fractions, algebra, introductory calculus, physics, chemistry, biology and business studies. Examples rotate every 4.5 seconds, with manual topic controls and reduced-motion support. The mascot has a soft yellow screen gradient within cool-silver hardware, and a neutral casing indicator. Backend-connected forms, client sign-in and client management remain integrated.

New in v2.7.1: education hero uses a silver all-in-one monitor with charcoal frame and toolbar, rotating maths/physics/chemistry examples, manual topic controls and reduced-motion support. Floating dots and chart bars were removed from this illustration. The smiling companion has a soft sunshine-yellow face and retains its wave and seated animation.

New in v2.7.0: equipment and warranty records, private draft service-visit reports, explicit portal sharing and client acknowledgements, a paginated client timeline and service dashboard. Existing follow-ups now include upcoming warranty expiries. Read `CLIENT_SERVICES_V2_7.md` for workflows and safe upgrade steps. The public site retains the approved cool-silver palette and matching education buttons.

New in v2.6.17: deeper charcoal, cleaner ivory and richer slate-blue action accents restore contrast and definition in the public site and education view.

New in v2.6.13: quieter public palette with warm ivory, soft charcoal and muted slate-blue accents; copper is limited to small details.

New in v2.6.12: public website, education page, mascot and chat controls use charcoal, warm ivory and copper, including light/dark appearances.

New in v2.6.11: compact desktop Let's chat button with smaller icon, text, padding and shadow; mobile controls retain their touch sizes.

New in v2.6.10: compact desktop theme control, education assistant launcher/monitor and footer, with mobile sizes preserved. Popup perch geometry adjusts to the smaller monitor.

New in v2.6.9: a solid navy popup rim with a small highlight and contact shadow supports the seated education companion.

New in v2.6.8: the seated education monitor rests its raised arm, gently swings both legs and looks down toward the conversation. Its closed-button attention wave remains.

New in v2.6.7: coordinated education mascot travel and popup reveal/close, smooth seated-pose transitions, rapid-toggle cancellation and reduced-motion support.

New in v2.6.6: the education companion moves onto the open guide and sits on its top edge; closing returns it to the launcher. Resizing repositions it and reduced-motion settings skip the hop.

New in v2.6.5: smiling education monitor with a raised-hand classroom attention wave and a naturally moving relaxed arm. Reduced-motion settings keep it still.

New in v2.6.4: subtle, intermittent idle hand movements for the education monitor, disabled for reduced-motion preferences. Greeting gestures continue to take precedence.

New in v2.6.3: curious education companion with a raised eyebrow, hand-to-chin asking gesture and a small question mark.

New in v2.6.2: animated retro monitor companion for the public education website guide, with cartoon gloves/shoes, school-specific guidance and reduced-motion support. This guide uses local scripted replies and does not access student records.

New in v2.6.1: VICAM brand icon and a request-only processing glow in Ask VICAM, with reduced-motion support.

New in v2.6.0: **Ask VICAM**, a read-only staff navigation assistant with permission-checked searches, task help and an optional OpenAI interpreter. Local mode works without an API key. Read `ASK_VICAM.md` for usage and upgrading.

New in v2.5.0: calculated line-item quotations/invoices, staff roles, optional authenticator MFA, verified automatic local backups, client email jobs, opt-in invoice reminders, private CRM history/export and operations status. Read `UPGRADE_V2_5.md` before upgrading. Separate issuing-business deployments only; not shared SaaS.

A runnable FastAPI + SQLite backend with an integrated copy of VICAM's website and a staff enquiry dashboard. The website includes the current education lesson and mascot updates with the approved cool-silver palette. The integrated copy is `static/index.html`; its form and client portal connectors are included in `static/`.

## Included

- Invited-client accounts with single-use setup/reset links, separate sessions and access revocation.
- Explicitly published project stages, summaries, milestones and client actions.
- Shared original quotations/invoices and copy-bound quotation acceptance/change requests.
- Client support requests and conversations, separate from internal descriptions.
- Protected requirements/handover file sharing (PDF/PNG/JPG/TXT, 2 MB per file, 50 MB per client).
- Staff follow-up dashboard for enquiries, tasks, quotations, unpaid overdue invoices and renewals.
- Service-specific enquiry guidance, next-step receipts, FAQs and approved real-project examples.

- Validated project briefs, including the optional CCTV site questions.
- A durable database and a reference receipt for the visitor.
- Duplicate-submit protection for retries of the same brief.
- Staff sign-in with hashed passwords, server-side sessions, HttpOnly cookies and CSRF checks.
- A searchable, paginated inbox; New, In progress, Waiting and Closed statuses.
- Private team notes and an audit record of staff views and changes.
- Enquiry deletion and a database backup command.
- TLS SMTP notifications with a database outbox, delivery status and bounded retries.
- Request limits, an invisible spam field, a request-size limit and security headers.
- A connected website copy preserving the service pages, education demo, theme switch and camera labels.
- An enquiry privacy notice template and consent check before sending.
- Original PDF generation, certificate certification, QR verification, local file comparison and issuer permissions.

This release includes a client management workspace and a separate invited-client portal. It does not include live chat, school accounts or accounting integrations. No real contacts, credentials, client data or student data are bundled. Hosting, SMTP credentials, staff MFA enrollment and external monitoring are not provisioned by this package.

## Run locally

Tested with Python 3.12.14. Use Python 3.12+.

```sh
python -m venv .venv
# macOS/Linux:
source .venv/bin/activate
# Windows PowerShell instead:
# .venv\Scripts\Activate.ps1

pip install -r requirements.txt
```

Copy `.env.example` to `.env` using your file manager (or `cp .env.example .env` on macOS/Linux). The default local address is `http://127.0.0.1:8000`. If you use another hostname or port, update `PUBLIC_ORIGIN` to match it exactly.

```sh
python -m app.manage init
python -m app.manage create-admin --email your-real-staff-email@example.com
```

The email above is an example to replace. Enter a password of at least 12 characters when prompted. Passwords are not command-line arguments and there are no default accounts.

```sh
uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000 --no-proxy-headers --no-access-log
```

- Website: `http://127.0.0.1:8000`
- Enquiry inbox: `http://127.0.0.1:8000/admin`
- Client management: `http://127.0.0.1:8000/admin/clients`
- Privacy notice: `http://127.0.0.1:8000/privacy`
- Health endpoint: `http://127.0.0.1:8000/api/health`

Send a non-sensitive test brief from the website. It should show a reference and appear in the dashboard. Saving a brief still creates a local text file; sending it stores a record on the backend.

## Client management

Open `/admin/clients` and sign in with the same staff account as the enquiry inbox. A hosting service, domain and email are not needed for local testing.

| Module | Working features |
|---|---|
| Clients | Contact details, organization, private notes, active/archive status, linked enquiry history |
| Projects | Scope, client, target date, progress status and assigned staff |
| Tasks | Client/project links, assigned staff, due date, completion and on-screen overdue reminders |
| Quotations | Scope/pricing notes, total, currency, validity date, manual status and printable summary |
| Invoices | Total, currency, due date, issued/void status, recorded payments and outstanding balance |
| Payments | Manual records of payments received, payment date, method and transaction reference |
| Support tickets | Issue details, priority, progress and assigned staff |
| Service contracts | Scope/terms, start/end dates, status, account owner and ending/expired summary count |

Start by adding a client, or select an enquiry in `/admin` and use **Link enquiry to client**. Choose an existing profile or create a new one. An enquiry can be linked once; repeating the same conversion reuses its client. The system does not silently merge clients by matching email addresses. Review existing clients before creating another profile for the same person.

Select a client to view their enquiry history and open their related modules. Use the Client filter, search and pagination to find records. All eight modules support creating, editing and deleting records. Archive a client instead of deleting them when records remain linked. A client linked to an enquiry cannot be deleted while that enquiry remains. Deleting an enquiry removes its client link, while preserving the client.

Create more staff accounts with the existing `create-admin` command to enable assignments. Only active accounts can receive new assignments. All staff still share the same access level; this version does not provide individual client permissions.

Follow-up reminders appear as tasks due today or overdue, using `BUSINESS_TIMEZONE` (default `Africa/Nairobi`). Mark a task Done to clear the reminder. Task follow-ups do not send emails, SMS or calendar notifications. Optional overdue-invoice email reminders require client opt-in and REMINDER_EMAILS_ENABLED or an explicitly scheduled reminder command. Contract counts include active contracts ending within 30 days and active contracts already past their end date; contract status updates are manual.

Payments are **records of money already received**. They do not initiate transactions. M-Pesa, banking, card processing, recurring billing and bank reconciliation are not connected. Amounts are stored as integer minor units; 12,345 represents KES 123.45. Supported currencies use two decimal places: KES, USD, EUR and GBP. Each invoice has one currency, and its payment records use that currency. Payments may not exceed the remaining balance or repeat a transaction reference on the same invoice. Only issued invoices accept payments. Paid/partial/unpaid state is calculated from recorded payments. Invoices with payments cannot change total, currency, client or status until those payment records are corrected or removed.

Quotation/invoice totals can be calculated from line items with document-wide discount and VAT, or retained as legacy manual totals. There is no refund ledger or electronic tax-invoicing integration. See `UPGRADE_V2_5.md` for rounding and tax limitations. **Download draft PDF** generates an unsigned server PDF. **Issue signed PDF** certifies the exact server PDF bytes when a signing certificate and staff issuing permission are configured. These summaries require review of company particulars and tax treatment before customer use. Marking a quotation Sent does not email it. Service contracts record terms; they are not digitally signed contracts.

Private client notes and updates are editable. The audit stores staff identity, action, target and time. New CRM changes also have an administrator-only before/after history; it does not reconstruct earlier changes or cover every collaboration event. No files, passwords, confidential case records or student data should be entered into these general business records.

## Signed PDF and QR verification

1. Save the quotation or invoice and its scope, total and dates.
2. Authorized issuers can select **Download draft PDF** for an explicitly unsigned draft.
3. For a final signed file, set a quotation to Sent or Accepted, or an invoice to Issued, save, then select **Issue signed PDF**. The button is unavailable until signing is configured.
4. The server saves the original PDF bytes, SHA-256, certificate fingerprint and immutable QR snapshot in one transaction. Downloads return those original bytes. Do not print-to-PDF to redistribute a signed original: distribute the downloaded file.
5. Recipients scan the QR on VICAM's confirmed domain, compare saved details, download the original, or select their received PDF to compare its exact SHA-256 locally. Files are not uploaded during comparison.
6. Validate the signature, signer identity and certificate trust in a compatible PDF reader. A file hash match establishes byte equality with the server's copy, not independent company identity.
7. **Withdraw** stops public access to the copy and displays a warning. Staff can still download the saved original. Edits, renamed clients or new payments label old copies as earlier versions; issue a fresh PDF for updates.

Invoices display a green **PAID** or **PARTIALLY PAID** badge according to recorded payments when a new PDF is generated. Unpaid/void invoices do not display these badges. Saved copies retain their original payment state; Live recorded balances are shown separately; a new PDF can record a later payment state without replacing the earlier original.

The certification signature uses SHA-256 and a PAdES signature with DocMDP permitting no changes. It detects covered-byte alterations, and compatible validators can assess prohibited incremental changes. It does not make editing impossible. This implementation has no trusted timestamp, embedded revocation evidence or long-term validation profile; signature trust and certificate status must be checked by recipients. It does not certify tax compliance or receipt of payment.

QR URLs use unguessable 256-bit bearer tokens. Lookup columns store token hashes; the stored PDF necessarily contains the original bearer URL. Public detail mode governs disclosure: restricted mode hides client/scope fields and blocks public PDF downloads; permitted totals and statuses remain available to anyone holding the bearer link. Emails, phone numbers and internal notes are excluded. Protect the database and backups as client data. Deleting the source document removes its stored PDF and redacts its snapshot, keeping a minimal withdrawn tombstone; separately apply backup retention policies.

There is no public document search. Verification responses use no-store/no-referrer/noindex headers and rate limits. The verification token appears in the URL fragment and is sent to the API: configure proxies to avoid logging `/api/verify/` tokens. The QR alone does not authenticate surrounding PDF text. Older pre-v2.2 copies have snapshot verification but no original PDF/file check.

Public scanning requires online hosting with your confirmed HTTPS domain: set `APP_ENV=production`, `PUBLIC_ORIGIN=https://YOUR_ACTUAL_DOMAIN` and `SECURE_COOKIES=true`. Local links are only local tests. Existing URLs do not change when the domain changes. QR generation is local; issuing/withdrawing copies sends no emails.

See **SIGNING_SETUP.md** for certificate configuration, issuer permission and local testing. No company certificate or private key is bundled.

## Upgrading from version 1 or 2

Stop the running server and make a backup using the existing backup command. Install the updated requirements, then copy your existing `.env` settings and private database into the new application deployment. Keep the same `DATABASE_PATH`. Run `python -m app.manage init` and start the application. The additive schema migration creates CRM tables without replacing enquiries, passwords, notes, sessions or the email outbox. Existing enquiries do not become clients until staff explicitly link them. Starting the app also runs the migration. All pre-existing staff accounts receive document issuing permission disabled; grant it explicitly using the command in SIGNING_SETUP.md. Migration version 4 is repeatable; this release refuses to open a database marked with a newer schema version. Keep the backup until the upgraded inbox and client workspace are verified.

## Company email

Set the following in `.env` using details from your email provider:

```ini
COMPANY_EMAIL=your-verified-company-inbox@example.com
MAIL_FROM=your-verified-sender@example.com
SMTP_HOST=your-provider-smtp-host
SMTP_PORT=587
SMTP_MODE=starttls
SMTP_USER=your-provider-username
SMTP_PASSWORD=your-provider-secret
```

These are placeholders, not working VICAM addresses. Use `SMTP_MODE=ssl` and the provider's port when implicit TLS is required. Plaintext SMTP is intentionally unsupported. Restrict `.env` access; never commit it to source control. Production secrets should be stored in the hosting provider's secret settings.

Restart the application after changing settings. The worker checks queued notifications every 30 seconds and uses backoff after failures, up to five attempts. SMTP failures do not remove the enquiry. The staff dashboard shows whether an alert is pending, sending, sent or failed. A successful form receipt confirms database storage, not email delivery or a staff response.

Notifications contain the reference, selected service and dashboard URL, not the full client's brief. SMTP delivery is at-least-once: a process crash after sending but before recording success can cause a duplicate alert. The enquiry itself remains a single record when a visitor retries with the same submission key.

For manual processing:

```sh
python -m app.manage send-notifications
```

## Staff account administration

Administrator, finance and support roles are enforced on the server. Optional authenticator MFA is enrolled through private management commands. Public visitors cannot read stored briefs. School isolation and shared business SaaS remain future work.

```sh
python -m app.manage create-admin --email another-staff-email@example.com
python -m app.manage reset-password --email staff-email@example.com
python -m app.manage disable-admin --email staff-email@example.com
```

Resetting a password and disabling an account revoke its existing sessions. Sessions expire after eight hours by default (`SESSION_HOURS`, maximum 24). There is no public registration or email-based password-reset flow.

## Database and backup

The default database is `data/vicam.sqlite3`. Put this directory on persistent, private storage. The database and its backup contain personal client information and must not be served as static files. This application only exposes its static assets, not the project or data directories.

```sh
python -m app.manage backup backups/vicam-backup-YYYY-MM-DD.sqlite3
```

Choose a new filename each time. This uses SQLite's online backup API. Encrypt and protect backups with your host's storage tools, keep a separate copy and test restoration.

Restore with the application stopped: preserve the current data directory, remove stale SQLite `-wal` and `-shm` sidecars from the old database, and place a validated backup at the configured database path with restrictive file permissions. Restart and verify the inbox. Never replace a live database file while the app is writing to it.

Define an enquiry retention policy before public use. The starter does not silently delete enquiries on a timer. Authorized staff can permanently delete an enquiry and its notes; its minimal audit reference remains. Backup copies need their own retention and deletion procedure. Database file permissions do not provide encryption at rest.

## Hosting the first instance

Deploy the whole application so the website and backend share one origin. SQLite is appropriate for this initial single-instance service; use a persistent volume and backups. For heavier traffic or multiple hosts, migrate to PostgreSQL with a tested migration process before scaling.

For a public deployment:

```ini
APP_ENV=production
PUBLIC_ORIGIN=https://your-actual-domain
SECURE_COOKIES=true
DATABASE_PATH=/your-private-persistent-volume/vicam.sqlite3
```

Use HTTPS termination at a trusted host/reverse proxy. Production configuration refuses to start with an HTTP public origin or insecure cookies. `PUBLIC_ORIGIN` is used for origin checks and links; do not include a path. Enquiry and login rate limits use the connecting client's address. If deploying behind a proxy, configure Uvicorn to trust forwarded headers only from the actual proxy IP addresses, rather than accepting arbitrary visitor-supplied headers. Do not blindly use a wildcard trust setting.

Use a production process manager/host, protect the database volume, configure a verified SMTP sender and staff accounts, and complete your public company contacts. Access logs are disabled in the example command because search query strings may contain client names. No payment or authentication provider has been connected.

Review the included privacy notice against VICAM's actual legal entity, contact details, retention decisions and hosting/email processors before publishing. The form requests only enquiry data; it is not an intake system for confidential financial records, court documents or student records.

The optional Dockerfile builds the same app using a non-root account. Container builds were not exercised in this environment. Mount persistent storage at `/app/data`, pass environment variables, and create staff accounts inside the container before use. A fresh container filesystem alone is not durable storage.

## Tests

```sh
pip install -r requirements-dev.txt
python -m pytest -q
```

`requirements-tested-lock.txt` records the exact environment used for this build, including test dependencies. Automated tests exercise validation, persistence, duplicate-submit handling, authentication, CSRF, origin checks, rate limits, email failure/retry handling, status changes, notes and deletion. Email tests use stubs and do not send real messages.

The build passed 30 Python tests, including the additive upgrade, cross-client project checks, payment balances, validation and access protection. The actual HTTP/DOM integration check exercised all eight workspace modules and enquiry-to-client linking.

Optional repeatable UI interaction check (Node.js 22.22.2+ (22.x), 24.15.0+ (24.x), or 26+ and Python environment required):

```sh
npm install
python tests/run_ui_checks.py
```

It starts a temporary local server on port 8767, creates an isolated test account and data, and closes the server afterward. Run with that port free. Node.js is needed only for this optional test, not for running the backend. The test uses JSDOM, not a visual browser.

Browser layout screenshots, container builds and a real SMTP-provider delivery test remain to be performed in the deployment environment.

## Next modules

1. Live staff chat: staff availability, message storage, notifications and an agreed response workflow.
2. Education expansion: shared school memberships, teacher/parent permissions, assessment imports and reviewed student-data agreements. The administrator-only education pilot is implemented in v2.8.0.
3. Production identity: MFA or an approved identity provider, finer staff roles and session management.

Do not reuse this general enquiry API to import student records. Build and test school isolation and student-data controls first.

## Source references

- FastAPI application lifespan: https://fastapi.tiangolo.com/advanced/events/
- FastAPI response cookies: https://fastapi.tiangolo.com/advanced/response-cookies/
- Python SQLite transactions and backup: https://docs.python.org/3/library/sqlite3.html

See `API.md` for the API contract and `START_HERE.md` for the short setup guide.


## Client experience (v2.3)

See CLIENT_EXPERIENCE.md for workflows, access rules, limits and Windows upgrade instructions.

- Staff tools: `/admin/client-experience` (link in the existing staff header).
- Client sign-in: `/client` (link in the public navigation and footer).
- Existing staff credentials and database records are preserved by the additive schema-5 migration.
- Invitation links are generated for staff to send privately. They are not emailed automatically.
- Follow-up reminders are shown on the staff dashboard. They do not send client emails.
- Student records require a separate system and data-access agreement. They are not collected by the portal.
