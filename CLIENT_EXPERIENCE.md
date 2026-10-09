# VICAM client experience — v2.3.0

Current release: see `UPGRADE_V2_5.md` for schema 6, staff roles/MFA, optional invitation emails and document-term comparisons. The release history below describes the earlier portal introduction.

This source-code update adds an invited-client portal and staff collaboration tools. It must be installed and the server restarted before it changes your running website.

## What is included

| Feature | How it works |
|---|---|
| Client portal | Verified contacts receive a single-use invitation, set a password and sign in at `/client`. Each account is linked to one client organization. |
| Project progress | Staff publish a stage, public summary, next milestone, estimated target date and action needed from the client. Internal scope and assignments remain private. |
| Quotation approval | Staff share a generated original PDF. Clients accept a current sent quotation or request changes. The response records the account, time and exact copy checksum. Acceptance updates the quotation to accepted and shows a confirmation. |
| Invoices | Explicitly shared original PDFs are downloadable. Current recorded payment/balance totals are shown separately from the immutable PDF. The portal does not collect payments. |
| Follow-ups | Staff see new enquiries waiting two calendar days, open tasks due today, sent quotations waiting seven days or reaching their validity date, overdue unpaid invoices and contracts ending within 30 days or already expired. |
| Support | Clients create requests with reference numbers and exchange messages with staff. Ticket status is managed in the existing CRM. Internal ticket descriptions are not exposed. |
| File sharing | Staff and clients share PDF, PNG, JPG or text requirements/handover files. Downloads require sign-in and client ownership. |
| Website experience | Client sign-in links, service-specific optional questions, clear submission next steps, FAQs and real project examples after staff approval. |

## First use

1. Sign in to the existing staff workspace at `http://127.0.0.1:8000/admin/clients`.
2. Open **Client experience** in its header (`/admin/client-experience`).
3. Choose a client. Confirm the intended contact's identity and email.
4. Under **Portal access**, create an invitation and send its link privately. The link expires after 24 hours and can be used once. A fresh invitation also resets a forgotten password; old sessions are invalidated when it is used.
5. Under **Project updates**, choose a project and publish a short client-facing update. Only published projects appear in the client portal.
6. In **Client records**, set a quotation to Sent or invoice to Issued and generate its original PDF. Under **Share PDFs**, choose the record and share the exact copy.
7. The invited client opens the link, chooses a password and sees the shared information at `/client`.
8. Use **Conversations** for client-visible support replies. Private notes remain in the CRM/inbox.
9. Use **Project examples** to draft, edit or publish real examples. Publishing requires confirmation of permission; no sample claims are preloaded.

Invitation links are not automatically emailed. Dashboard reminders do not send email. Existing company enquiry alerts retain their prior SMTP workflow. Clients see replies and updates when they open or refresh the portal; the open page refreshes every minute. This is not a live chat or push-notification service.

## Quotation workflow

The client should review the original PDF and terms before accepting. Only current, unexpired, sent quotations can receive a decision. A change request requires a description. Acceptance is repeat-safe and recorded against the exact saved PDF copy; it is an account-recorded approval, not a client digital certificate signature. The original document is not modified.

A changed, withdrawn or expired quotation cannot be approved. After acceptance, the PDF remains the original sent copy and the source status becomes Accepted, so the portal explains that the quotation is now accepted while retaining the original copy. Create a new original PDF if an updated status copy is required. Quotation creation/signing remains subject to the existing issuer permission.

Staff can remove a PDF from the portal. Its bearer QR link remains available until the verification copy is withdrawn in the original document history. Do not distribute QR URLs publicly.

## Files and privacy

- 2 MB per file; 50 MB stored per client. The server enforces both limits.
- Allowed formats: PDF, PNG, JPG/JPEG, UTF-8 plain text. Filenames, content signatures and size are checked; files download as attachments, not executable pages.
- Files are stored as database bytes with a checksum, so the existing SQLite backup command includes them.
- This release does not include an antivirus scanning service. Do not use it as a general-purpose public file host; open documents only from known project contacts.
- Student names, grades, records, credentials, banking details and sensitive case files must not be uploaded. School data collection requires a separate service, agreement and access model.
- Client organization contacts share access to that organization's published projects, shared documents, files and ticket conversations. Create separate client profiles when access must be separated.
- Revoke portal access when a contact or client organization should no longer have access. Archiving a client blocks sign-in and active sessions. Reinviting can re-enable an account.
- Shared projects/files, client conversations and shared financial documents cannot be silently transferred to another client through the CRM.
- Existing staff accounts retain broad CRM access. This update does not add departmental staff roles or MFA.

Use HTTPS and secure cookies on hosting, preserve private signing keys and back up the database. Public examples remain hidden until approved real content is published. Response-time commitments come from service agreements, not from the portal's priority setting.

## Windows upgrade — preserve your existing data

Do not delete the old project folder. Do not replace your database with a new empty one. The download contains application source only; your local database, passwords, signing certificate, `.env` and virtual environment are not bundled.

1. In the terminal running VICAM, press **Ctrl+C** to stop the server. Keep this terminal so its current signing settings remain available.
2. From the existing `VICAM_Backend` folder, create a fresh backup:

```powershell
.\.venv\Scripts\python.exe -m app.manage backup ".\backups\vicam-before-client-portal-$(Get-Date -Format 'yyyyMMdd-HHmmss').sqlite3"
```

3. Extract the new ZIP to a separate folder. Copy its `VICAM_Backend` folder's **contents** into the existing project folder, replacing matching application files. Keep your existing `.venv`, `.env`, data folder, backups and private-signing folder. Do not nest one `VICAM_Backend` folder inside another.
4. In the original terminal, install dependencies and apply the additive migration:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m app.manage init
```

5. Keep the origin consistent with the browser address and restart:

```powershell
$env:PUBLIC_ORIGIN = "http://127.0.0.1:8000"
.\.venv\Scripts\python.exe -m uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000 --no-proxy-headers --no-access-log
```

6. Reload your browser. Confirm existing clients, invoices and payments are still present, then open **Client experience**. For client testing, use a separate browser profile or private window to avoid mixing staff and client sessions.

Your existing PDF signing environment values must still be set. If signing configuration fails, follow SIGNING_SETUP.md; do not disclose passwords. Local invitation URLs work only on the machine running the local server. Remote clients need the hosted HTTPS website.

The migration advances schema 4 to schema 5. Older application versions will reject the updated database. To roll back, stop the server and restore the pre-upgrade database with the older source package; do not run old code against the schema-5 database.

## Validation

The package includes API access-isolation/migration/workflow tests and real-server DOM integration tests. These use disposable databases and test accounts. No company emails, invitations or transactions are sent during tests. Real hosted HTTPS behavior, phone layout and accessibility, actual SMTP delivery and production certificate trust still need checks on the deployment you intend to use.
