# VICAM client management — v2.7.0

This release adds equipment, warranties, service visits and a client activity timeline to your existing CRM. Quotation approval, project stages, follow-ups and the client portal were already available and remain connected.

## What you can do

- Record cameras, recorders, computers, network devices and access-control equipment with manufacturer, model, serial number, location, installation date and warranty end date.
- Edit equipment, mark it in repair or retire it. Retained records protect the service history.
- Keep equipment private or explicitly show it in the client portal. Internal equipment notes are never included in client responses.
- Save and edit draft visit reports with technician, date, work completed, findings and next steps. Link a report to the client's project and equipment.
- Review and share a report. Sharing locks its content and stores a SHA-256 content hash. Correct a shared report with a new report; the original stays intact. The hash is an integrity reference, not a certificate-backed signature.
- Let an invited client review a shared report, leave a comment and acknowledge it. The account, time and first acknowledgement are retained. Acknowledgement means receipt/review; it does not collect a payment or act as a legal signature.
- Review a timeline of enquiries, team-note events, projects, project updates, tasks, quotations, invoices, payments, contracts, support tickets, equipment, service reports and acknowledgements. Open the source record for its details. Support staff do not see financial timeline entries.
- See active equipment, repairs, warranties ending within 30 days and reports awaiting acknowledgement. Administrators also see pending quotations and outstanding balances separated by currency.
- See upcoming warranty expiries in the existing Follow-ups workspace. These are dashboard reminders, not automatic warranty emails.

## Staff workflow

1. Sign in at `/admin/clients`.
2. Open **Equipment & visits** in the top bar, or visit `/admin/service-records`.
3. Choose a client. Add equipment and warranty information. Select a project when relevant.
4. Open **Service reports**, record the completed work and save a draft.
5. Review the saved report, then choose **Share with client**. Shared reports are locked.
6. In **Client experience → Portal access**, invite the verified client contact if they do not already have access.
7. The client signs in at `/client`, opens **Equipment & visits**, reviews the report and acknowledges it.
8. Refresh the staff page to see the acknowledgement and activity timeline.

Administrators and support staff can manage service records. Finance staff retain their existing financial workspace and cannot access equipment or visit records. All writes reuse session, CSRF and origin protection. Client access is limited to the signed-in client's explicitly shared records.

Quotation acceptance remains in **Client experience → Share PDFs** and **Client portal → Quotes & invoices**. Project stages remain in **Client experience → Project updates**. Follow-up tasks and support contracts remain in Client records.

## Update your Windows installation

The ZIP does not automatically update the software running on your desktop.

1. From the existing VICAM folder, create a backup with the working backup command. Keep that backup outside the application folder you are updating.
2. Stop the running server with **Ctrl+C** in its terminal.
3. Extract the updated source ZIP into a separate folder.
4. Copy the updated `app`, `static` and `tests` folders, plus the requirements and documentation, into your existing VICAM folder, replacing the old code files. Preserve your existing `.env`, `.venv`, database/data folder, backups and private signing/MFA keys. Do not replace or delete those private files.
5. Open PowerShell in that existing VICAM folder and run:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m app.manage init
.\.venv\Scripts\python.exe -m uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000 --no-proxy-headers --no-access-log
```

Use your existing working port if it is different. Keep the existing `PUBLIC_ORIGIN` matching that port. Do not start a second server on a port already in use.

The additive schema-7 migration creates new tables while preserving existing records and accounts. After upgrading, verify an existing client, quotation and invoice, then test one equipment record and one report with a test client. Older source versions cannot open the upgraded schema; rollback requires restoring the pre-upgrade database backup together with the old code.

## Verification performed

The automated checks cover existing CRM workflows and the additions: role permissions, private drafts, client isolation, cross-client/project link rejection, published-report locking, CSRF, acknowledgement idempotency, audit entries, safe text rendering, equipment edits, client review and logout cleanup. The upgrade migration is tested for repeatability and retention of existing client data.
