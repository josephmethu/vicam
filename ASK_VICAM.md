# Ask VICAM — backend v2.6.1

Ask VICAM is a small staff assistant for finding records and understanding common tasks. It appears at the bottom right of the enquiry, client management, client experience and operations pages after staff sign-in. The button and panel use the V from the VICAM wordmark. A subtle cyan glow runs only while a request is being checked; reduced-motion preferences receive a static highlight. It is separate from the public website's Let's chat button.

## What works immediately

Local navigation needs no company email, external AI account or API key. Open **Ask VICAM**, type a request or choose an example, then open a result or the filtered view.

Examples:

- Show unpaid invoices
- Show overdue invoices
- Which quotations expire this week?
- Find client Acme
- Show projects for Acme
- Show Acme's projects
- Show active projects
- Show tasks due today
- Show open support tickets
- Show active contracts
- How do I record a payment?
- How do I invite a client?
- How do I check backups?

Local mode recognizes these patterns; it is not a general conversation model. If several clients match a name, choose the appropriate filtered link. Search results show up to ten records and a link to the full filtered list. Due dates use BUSINESS_TIMEZONE (Africa/Nairobi by default). This week means today through Sunday, including those dates. Overdue excludes today; tasks due today excludes completed tasks.

## Permissions and limits

Every request requires a staff session and CSRF token. The assistant checks the staff role again for the requested records and help topics. Finance staff can find financial documents but cannot use operations or portal-administration help. Support staff cannot retrieve quotations, invoices or payments. Administrators retain their existing access.

The assistant does not create quotations, issue PDFs, send email, delete records, record payments or initiate bank transfers. It gives instructions and links; users continue through existing forms. Results reflect the database at the time of the lookup. Check the opened record before making a decision.

## Optional AI interpretation

For unfamiliar wording, an administrator can configure an OpenAI connection in the private `.env` file:

```dotenv
ASSISTANT_AI_KEY=your-private-api-key
ASSISTANT_AI_MODEL=your-compatible-model-id
```

Configure both values or leave both empty. Select a model supporting the Responses API and strict JSON-schema structured outputs. Restart the application after changing configuration. The key stays on the server. API charges are separate from ChatGPT subscriptions. Review provider terms, data handling and spending limits before enabling it.

When configured, staff see an unchecked **Use AI for unfamiliar wording** option. Local patterns are still handled locally. For an unrecognized request with that option selected, only the typed request is sent to OpenAI. A staff member could include personal or confidential information in that text; avoid doing so unnecessarily. Retrieved records, private notes, database contents and session credentials are not included in the model request.

The model only classifies a navigation request into a limited schema. The server validates the classification, enforces staff permissions, performs parameterized searches and builds links. Model output cannot supply SQL, URLs or executable actions. Requests use `store: false`; this flag is not a promise of zero provider retention. Provider policies still apply. The application does not retain question text or chat history; lookup audit entries contain only the record category.

If AI is unavailable, the assistant falls back to local examples. The UI labels local and AI interpretation separately. No API key or live model call is included in this package. Automated tests use a mocked provider; a live connection still needs testing with your chosen model and key.

Official API format reference: https://developers.openai.com/api/docs/guides/structured-outputs

## Updating your existing installation

1. Make a backup using your existing backup procedure. Stop the running server with Ctrl+C in its terminal.
2. Extract the new source into a separate folder. Preserve your old installation until the new one is checked.
3. Transfer your private `.env`, database, client uploads and configured private signing/MFA files according to your existing upgrade guide. Do not overwrite them with empty examples. Preserve relative paths or adjust them to the new locations. Keep the encryption key used by existing MFA and invitations.
4. Create/install the Python environment using the README. This release adds no dependency and keeps database schema version 6.
5. Start the updated server using your existing command and matching PUBLIC_ORIGIN. Open the staff dashboard and refresh the page. Sign in and test **Show unpaid invoices**.

Downloading the ZIP does not update the copy already running on your computer. You do not need to enable external AI to test the assistant.

## Validation

The package includes API tests for authorization, CSRF, filtered balances and dates, client matching, result limits, mutation blocking, private audit logging, structured AI requests and failure fallback. Browser/DOM integration checks cover sign-in activation, text-safe rendering, filtered links, permission refusals and cleanup after logout, including delayed replies.

Future draft preparation and actions need separate implementation, review previews, explicit approval and audit trails. They are not enabled in this release.
