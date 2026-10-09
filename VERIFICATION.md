# VICAM v2.3.0 verification — 7 October 2026

- 40 Python tests passed on Python 3.12.14. New coverage includes client/staff session separation, CSRF, client ownership, one-time/expired invitations, password reset, access revocation, explicit project publication, current/expired/stale quote decisions, repeat-safe acceptance, support conversations, file validation/download isolation and follow-up balances.
- An additive schema-4-to-5 migration was exercised twice against existing clients and an original PDF artifact; data, issuer permission and stored PDF bytes remained intact. Future schemas are rejected.
- A temporary real Uvicorn server plus JSDOM exercised staff publishing, private invitation activation, the client portal, quotation acceptance, staff/client support replies, file upload, permission-confirmed public examples, service-specific questions and logout cleanup. Existing staff/CRM/PDF workflow checks also passed.
- JavaScript syntax checks passed. No hosted deployment or actual company messages were sent.
- DOM integration checks are not visual browser or phone layout tests. Real hosted HTTPS cookies, phone layout/accessibility, actual SMTP delivery and production certificate trust still require checks on the intended deployment.
- One Starlette/httpx TestClient deprecation warning remains. No antivirus service, MFA, client push notifications, automatic reminder emails, payment collection or student-data system was added.

## Prior PDF verification retained


- 30 automated Python tests passed on Python 3.12.14, covering enquiry/CRM workflows, permissions, migration and document verification.
- The additive schema-4 upgrade preserves enquiries/passwords and adds issuer permission (disabled by default for existing accounts) and original PDF storage. Repeated initialization succeeds; future schemas are rejected.
- A signed quotation generated with an isolated local test certificate passed pyHanko signature integrity, mathematical validity, DocMDP and explicit test-root trust validation. That temporary certificate was explicitly trusted only within the test; this does not demonstrate public CA trust or VICAM's real identity.
- Changing signed PDF metadata bytes failed integrity validation. Replacing visible page contents in an incremental revision preserved the original signature's mathematics but failed DocMDP and overall validation, demonstrating why recipients must check modification permissions as well as signature validity.
- Missing signing keys and inappropriate draft status caused atomic issuance failure with no snapshot/PDF left behind. Unconfigured signing and staff without issuer permission were denied. Production configuration rejected local test identities.
- Downloaded bytes matched their saved SHA-256. Corrupted stored PDF bytes caused an unavailable warning; public downloads stopped after withdrawal. Staff originals remained downloadable until source deletion, which removed PDF bytes and redacted snapshots.
- Existing QR snapshot tests cover immutable versions, excluded contact fields, hashed lookup tokens, client/payment changes, void invoices, withdrawal, deletion, integrity failures, CSRF and verification headers.
- The HTTP/DOM test used a real temporary Uvicorn server and JSDOM to exercise staff login, all eight CRM modules, draft and signed PDF issuance/downloads, public verification, local exact-file matching and altered-file warnings, withdrawal, validation feedback, logout cleanup and enquiry-to-client linking.
- JavaScript syntax checks passed. The generated server-PDF QR was independently decoded with ZXing to its exact expected URL. A rendered quotation PDF was visually inspected for layout, legible totals and QR placement. Render/decoding tools are build checks, not application dependencies.

Repeat tests with README.md commands. Test accounts, data and signing keys are created only in temporary directories and are not bundled as application defaults. Email tests use stubs; no external messages or transactions were sent.

The UI check uses JSDOM, not a visual browser. Real phone scanning, compatible PDF reader trust validation, a real SMTP delivery test, a container build and a deployment review remain to be performed with VICAM's actual certificate, domain and hosting. One Starlette/httpx TestClient deprecation warning remains. No trusted timestamp or long-term signature validation service was tested or implemented.

Payment-badge update: 10 document/signature tests re-run and passed. Both green PAID/PARTIALLY PAID invoice variants were rendered and checked, with exact payments/balances. Unpaid, void and quotation variants were checked to omit the green badge. Existing original PDFs remain unchanged; payment updates require a newly generated copy.

Compact-header update (7 October 2026): desktop computed styles checked in JSDOM for a 56 px minimum bar height, 5 px vertical padding, 128 px logo and 11 px navigation text. Mobile CSS retains 44 px menu/theme targets with a 112 px logo (104 px on very narrow screens). Header navigation labels, menu aria-controls and theme controls remain present. This CSS-only change does not alter backend workflows.

Education-header update: embedded and standalone header computed styles checked for a 56 px minimum masthead, 128 px desktop logo, 11 px navigation and 44 px CTA. Dark/light logo filters, home links, embedded navigation messaging and student-data protection text verified.

Wordmark update: the approved tall-V concept is implemented as five custom vector glyphs without font dependencies. Main/education inline SVGs and shared software header SVG checked for geometry, accessible home links, 128 px public sizing and dark/light filter behavior; rendered wordmark visually inspected.

Further header reduction: main and education mastheads now use a 48 px minimum height, 1 px vertical padding and a 108 px desktop wordmark. Mobile wordmarks are 96/90 px, retaining 44 px menu, theme and education CTA targets. Desktop computed sizes and accessible logo links checked in JSDOM.
