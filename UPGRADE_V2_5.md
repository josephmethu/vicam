# VICAM v2.5.0 - source upgrade and operations guide

## What this release adds

- Optional line-item quotations/invoices with quantities, unit prices, discount % and VAT %. Existing manual documents retain their original total and issued PDF bytes.
- Server-enforced administrator, finance and support roles; optional authenticator TOTP second factor, encrypted secrets and one-use code checks.
- Automatic local SQLite backups, SHA-256 manifests, integrity checks, retention by copy count, verify and isolated restore commands.
- Immutable issued copies now compare commercial terms separately from recorded payments and operational status. Payment updates no longer label a matching original superseded.
- Explicit portal invitation emails and shared-document notifications, leased retryable email jobs, opt-in overdue invoice reminders and administrative delivery status.
- Administrator-only private client management export and before/after history for CRM changes.
- Operations page and Docker health check. Hosting, SMTP credentials, off-site backups and external monitoring are not provisioned.

## Upgrade your current Windows installation

1. Stop the running server with Ctrl+C. Create a database backup using the existing command. Protect copies of `.env`, certificate/PFX/password and encryption key separately.
2. Extract v2.5 into a separate application folder. Preserve your actual `DATABASE_PATH`, configuration and private signing paths. Do not replace your real database with a sample or test file.
3. Install the new requirements using that folder's Python environment:

```
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m app.manage init
```

4. Start the server using your established uvicorn command. Source downloads do not update your running server automatically. Keep browser hostname/port consistent with PUBLIC_ORIGIN.
5. Test client records, a legacy manual PDF, a calculated quotation, partial payment verification, client access and backup restore. Schema upgrades to version 6 without rewriting existing originals. Older application versions refuse this database; rollback uses the preserved pre-upgrade backup, not the upgraded database.

Existing staff accounts migrate as `admin` to preserve their previous access. Review and assign roles before enrolling additional staff or using the service publicly.

## Calculated pricing

In Quotations or Invoices, select **Calculate total from line items**. Enter description, quantity and unit price for each line; set discount and VAT percentages. Save before issuing a PDF.

The calculation rounds each quantity × unit price half up to the nearest minor unit, sums the rounded lines, rounds the document-wide discount, subtracts it, then calculates and rounds VAT on the net amount. The total is net + VAT. Percentages support up to two decimals; quantities support up to four; the current model applies one discount and one VAT rate to the whole document. Mixed tax rates, exemptions, credit notes, refunds and foreign exchange remain outside this ledger.

Example: two items at KES 100 each produce KES 200 subtotal. A 10% discount subtracts KES 20; 16% VAT on KES 180 adds KES 28.80; total KES 208.80. The 16% default is editable and does not determine the correct treatment of a particular sale. Review applicable tax treatment with the business. No eTIMS integration is added.

The backend calculates the authoritative total and rejects a conflicting submitted total. A paid invoice cannot change its pricing breakdown, total, currency, client or status through the edit endpoint. Existing manual documents remain available; switching an existing document to calculated pricing is a source revision and requires a new issued copy when terms change.

## Staff roles

| Role | Access |
| --- | --- |
| admin | All existing CRM, enquiries, collaboration, issuing when separately permitted, operations, exports and history |
| finance | Read client contact/project summaries; manage quotations, invoices and recorded payments; view/share original copies; queue document notifications; no destructive CRM delete, enquiries, operations or private client notes |
| support | Clients, projects, tasks, tickets, contracts, enquiries and non-financial follow-ups; portal invitations, progress, conversations and files; no financial documents, payments, case publishing, exports, history or destructive deletes |

Use the local management command; it revokes the account's existing sessions:

```
.\.venv\Scripts\python.exe -m app.manage set-role --email REAL_STAFF_EMAIL --role finance
```

New staff creation supports `--role admin`, `--role finance` or `--role support`. Issuing also requires the existing document permission. Permission checks run on the server, not just on hidden tabs. The finance collaboration workflow is available from Client records: share a copy in the portal and queue its notification there. An administrator or support user manages recipient invitations.

## Optional authenticator sign-in

Generate a secret-encryption key once:

```
.\.venv\Scripts\python.exe -m app.manage generate-encryption-key
```

Store the resulting DATA_ENCRYPTION_KEY in protected `.env` or deployment secrets. Never share it or commit it. Keep a protected backup separately from the database; losing it prevents decrypting enrolled MFA secrets and pending invitation emails. Changing it is not automatic key rotation.

Prepare an account's enrollment file in a private folder:

```
.\.venv\Scripts\python.exe -m app.manage prepare-mfa --email REAL_STAFF_EMAIL --destination private-mfa\staff-setup.json
```

Add the file's secret to a TOTP authenticator using SHA-1, six digits and a 30-second period. Keep the clock correct. This release provides a private enrollment file, not a browser enrollment QR screen. Confirm enrollment:

```
.\.venv\Scripts\python.exe -m app.manage enable-mfa --email REAL_STAFF_EMAIL
```

Enter the current authenticator code when prompted. Existing sessions are revoked. Staff login now accepts the password and a fresh authenticator code; each code can be used only once. Securely remove the enrollment file after confirming access. Preserve a controlled local administrator recovery procedure. `disable-mfa --email ...` is a local recovery command that also revokes sessions; no public recovery-code flow is provided. Enforce enrollment operationally for production staff: MFA is optional in this release, not automatically mandatory for every account.

## Automatic backups and recovery

Configure a private directory outside static, separate from the live database directory:

```
BACKUP_DIRECTORY=C:\VICAM_Private\backups
BACKUP_INTERVAL_HOURS=24
BACKUP_KEEP=14
```

Restart the server. A backup is attempted at startup and then at the interval. These are local backups, not off-site disaster recovery. Only verified automatic backups with the tool's own file prefix and paired manifests are pruned by copy count. Corrupt or unrelated files are left for review.

Commands:

```
.\.venv\Scripts\python.exe -m app.manage backup-auto
.\.venv\Scripts\python.exe -m app.manage verify-backup PRIVATE_BACKUP_PATH
.\.venv\Scripts\python.exe -m app.manage restore-backup PRIVATE_BACKUP_PATH --destination private-restore\test.sqlite3
```

Verification checks file hash, SQLite integrity, foreign keys and schema. Restore refuses an existing destination or the configured live database. Test the restored database in an isolated installation before relying on recovery. Database backups include saved PDFs, client files and encrypted MFA secrets; configuration, encryption keys and signing certificates are external and need separate protected backups. On Windows, configure private folder permissions; POSIX mode arguments do not provide Windows ACL management. Configure off-site encrypted copies and retention independently.

## Emails and reminders

SMTP settings are still required. No real email credentials are included. Successful SMTP submission does not prove inbox delivery; the transport remains at-least-once, so a crash after send can cause a duplicate.

- **Portal invitations:** select the email checkbox for a verified recipient. The one-use invitation token is encrypted in the queue. SMTP and DATA_ENCRYPTION_KEY must be configured. Unselected invitations retain the existing private-link workflow.
- **Quotations/invoices:** issue a copy, share it in the client portal and activate the intended client's account. Use **Email portal notification** in copy history. Email directs the recipient to authenticated portal access; it does not attach the PDF or expose its QR bearer link.
- **Overdue invoices:** enable the client's agreed-reminder checkbox. Set REMINDER_EMAILS_ENABLED=true to let the running app queue reminders once per business day at its first worker check. Alternatively schedule `app.manage queue-reminders --confirm` daily using the deployment scheduler or Windows Task Scheduler. Choose one scheduling approach. Only active, opted-in clients with an overdue unpaid issued invoice and an expressly shared copy are considered. A date/invoice key prevents repeated queueing on the same business day. No quote-chasing emails or general marketing campaign are added.

Before sending, jobs recheck eligibility, original terms, sharing, withdrawal and payment/opt-in state. Paid or no-longer-eligible reminders are cancelled. Retries are bounded to five attempts. Delivery states and generic errors appear at `/admin/operations` for administrators. No automatic retry action for exhausted client jobs is provided; review the problem and deliberately queue a new message when appropriate.

The app's worker drains enquiry and client jobs with configured SMTP. For a dedicated scheduled worker, use `app.manage send-notifications`; avoid unnecessary concurrent workers. A process that is asleep or stopped cannot run interval backups or send emails.

## Export, change history and retention

Administrators can open **View change history** on a selected CRM record. Creation, update and deletion capture before/after values from this release onward. This is not a reconstruction of historical changes, immutable external audit storage or a complete history of every collaboration/authentication event.

On a client record, **Download private client export** provides contacts, CRM records, linked enquiries, payment records and metadata for issued copies/files. It excludes passwords, signing keys and bearer tokens; original PDFs and file bytes require their separate authenticated downloads. It is a private management export and includes staff notes, so do not hand it directly to a recipient without reviewing disclosure. The current export is not a complete legal subject-access response or a complete portability package.

History may retain earlier personal information after a source record is deleted. Agree retention before production. Inspect a cutoff with a dry run:

```
.\.venv\Scripts\python.exe -m app.manage purge-history --before YYYY-MM-DD
```

Add `--apply` only for an approved retention cutoff. The command removes history entries before that date. It does not erase original documents, source records, audit events, pending jobs or backup copies. Broader deletion/retention procedures remain an operator responsibility; no arbitrary automatic purge of customer records is enabled.

## Deployment and monitoring gate

Use durable private storage, HTTPS PUBLIC_ORIGIN, APP_ENV=production and SECURE_COOKIES=true. Production rejects test signing certificates. Keep PFX/private keys, DATA_ENCRYPTION_KEY and backups outside static and outside source control. The container runs as a non-root user and now has a health check. Map persistent storage and the appropriate port using your actual hosting setup; no live service is created by this archive.

Set an external uptime monitor to `/api/health`. The endpoint probes an application table without exposing records. `/admin/operations` shows private database, backup and queue status. Agree alerts, escalation, certificate renewal, off-site backups, restoration tests and support ownership. No uptime commitment or production load capacity is established by the test suite.

Each issuing business still needs a separate installation/database/domain/storage/key boundary. Shared SaaS tenant routing, subscriptions, payment-provider confirmation, eTIMS, full custom company branding and advanced school/regulated-sector workflows remain future projects.
