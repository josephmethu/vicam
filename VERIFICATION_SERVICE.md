# VICAM document verification pilot - v2.5.0

This release adds a service page and enquiry choice, configurable issuer name/contact/registration, quotation expiry, current business-recorded invoice payments/balance, and an optional restricted public verification view. Existing immutable PDF copies, signature support, withdrawal, client portal approvals and private document sharing remain available.

## Business installation boundary

Use ONE independent deployment per issuing business. Each needs its own database, storage/backups, HTTPS origin, staff accounts, email configuration and signing certificate/private key. Ordinary CRM clients are recipients, not issuing business tenants. Do not put competing businesses in one database. This release has no shared SaaS tenant routing, subscription billing, self-service onboarding or company-logo uploader; the website and portal shell retain VICAM service branding. Issuer text is configurable on PDFs and verification results.

## Configure before issuing

Add to that deployment's `.env`:

```
BUSINESS_NAME=Example Engineering Limited
BUSINESS_REGISTRATION=Replace with the genuine registration reference
COMPANY_EMAIL=replace-with-business-email@example.com
VERIFICATION_PUBLIC_DETAILS=false
```

Use an actual email before production. Business name/registration are operator-entered particulars, not independently certified identity. Follow `.env.example` for PUBLIC_ORIGIN, production cookies and certificate settings. Production blocks local test signing. Never distribute PFX passwords or keys with the source archive.

`VERIFICATION_PUBLIC_DETAILS=false` hides recipient name, organization, project and scope from bearer-link responses, and blocks public original-PDF downloads. The page still exposes reference, total, date, issuer, current status and payments to anyone holding the link. Share sensitive PDFs through the existing authenticated client portal. Default true preserves existing local workflows; explicitly change it for commercial pilots after agreeing disclosure with the business.

## Issued and live information

The saved snapshot and original PDF bytes never change when a payment is recorded. Verification displays live recorded payments, balance, payment status and the check timestamp separately. This is not bank reconciliation or proof that money cleared. Reload the page for a fresh check. Commercial terms are compared separately from payment and operational status. Payment updates do not mark an unchanged commercial copy superseded; price, scope, recipient or issuer changes still can. File SHA-256 comparison checks the exact original separately.

For a sent quotation past its valid-until date (business timezone), the verification view warns expired. Accepted/declined quotations retain their recorded outcome. An expiry warning does not rewrite an issued PDF. Accepted quotations are account-recorded approvals of a specific shared copy, not client certificate signatures.

## Upgrade a local installation

1. Stop the server and use the existing backup command. Copy `.env` and signing keys to protected storage separately. Keep the old application folder for rollback.
2. Extract the new source into a separate folder. Preserve your original database path, `.env` and private key paths. Do not overwrite your database with an example or test database.
3. Install `requirements.txt` with your existing environment or a new `.venv`, run `python -m app.manage init`, then restart using your established uvicorn command. Schema upgrades to version 6; read UPGRADE_V2_5.md for backup and rollback guidance.
4. Sign in, check clients, generate a disposable test document, check QR, private/public visibility and payments. Changing issuer particulars can make old copies superseded and require a fresh copy before portal sharing or approval. Do not silently replace historical originals.
5. Keep production deployment separate from this local upgrade. A source download does not update your running Windows installation automatically.

## Pilot launch gate

Review business identity and domain ownership; set issuer details; obtain signing certificate if promising signed documents; confirm recipient disclosure; test HTTPS, separate installation isolation, expired quotation, changed file, withdrawal, partial and full payment, client approval and backup restore. Agree support hours, retention, export and termination terms. Run a controlled pilot before public launch. Calculated document-wide discount and VAT are available; no KRA/eTIMS, payment gateway, timestamp authority or external audit service is included.

See the accompanying VICAM Quotation & Invoice Verification Playbook for business validation, commercial pricing examples, operating procedures and the phased roadmap.
