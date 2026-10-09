# VICAM backend v2.8.0 — start here

This package turns the project enquiry form into a working service and provides a private staff inbox and client management workspace.

1. Install Python 3.12 or newer on the computer/server running the backend.
2. Open a terminal in this folder and follow the commands in README.md.
3. Create your staff account with `python -m app.manage create-admin --email YOUR_EMAIL`.
4. Start the server. Open `http://127.0.0.1:8000` for the website and `http://127.0.0.1:8000/admin` for the staff inbox.
5. Send a test brief from the website. Sign in to the inbox to view it and link it to a client profile.
6. Open `http://127.0.0.1:8000/admin/clients` to manage clients, projects, tasks, quotations, invoices, recorded payments, tickets and contracts.

There is no bundled password. Choose your own when creating the staff account.

Enquiries work without SMTP. They are stored in the inbox. To receive company email alerts, configure the verified company email and SMTP settings in `.env`, then restart the server.

The package is source code, not a published website. Double-clicking its HTML files cannot start the backend. A computer or hosted server must run the application.

A working administrator-only education pilot is now available at `/admin/education`. Add schools, students, subjects, assessments and marks, then review progress. Read EDUCATION_PILOT.md for setup, scope and calculations. The public education illustration and automated chat guide remain demonstrations; teacher/parent/student accounts and live staff chat are not included.

This v2.8.0 package includes the updated website and education screen. You do not need to replace its HTML with a separate preview file.

Upgrading an existing version? Back up the database first, preserve `.env` and `DATABASE_PATH`, install the new requirements, and run `python -m app.manage init`. See the upgrade section in README.md.

For PDFs, grant document issuing permission, then use **Download draft PDF**. To enable **Issue signed PDF**, configure the signing certificate as described in SIGNING_SETUP.md. Local test signatures are clearly labelled and do not establish VICAM's identity. Public QR scanning requires online HTTPS hosting and your confirmed domain. Issuing does not email the document.

New in v2.3: open `/admin/client-experience` after staff sign-in to manage client invitations, published updates, shared PDFs/files, conversations and follow-ups. Clients sign in at `/client`. Read CLIENT_EXPERIENCE.md before upgrading an existing installation.
