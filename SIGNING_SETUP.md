# VICAM PDF signing setup

## Grant issuing permission

Existing accounts are migrated with issuing disabled. Staff without this permission can read/edit CRM records and download originals, but cannot issue or withdraw copies. Grant permission on the private server:

```sh
python -m app.manage set-document-permission --email YOUR_STAFF_EMAIL --allow
```

Use `--deny` to revoke. Either command invalidates that account's sessions; sign in again. New accounts can be created using `create-admin --email YOUR_STAFF_EMAIL --can-issue-documents`. Protect server administration access.

## Production certificate

Obtain a document-signing certificate for VICAM from a provider whose trust chain your recipients' PDF readers recognize. The application requires an encrypted PKCS#12/PFX containing its matching RSA (2048+ bits) or EC (256+ bits) private key, signing certificate and relevant intermediate certificates. Certificate key usage must include digitalSignature and contentCommitment/nonRepudiation. Confirm compatibility with your provider before purchasing. This software supports exportable software keys, not a remote signing/HSM integration.

Mount the certificate as a private server secret outside the static directory and source package, readable only by the app's service account. Supply its password through the hosting secret manager; do not put it in source control, logs or a shared ZIP. Set:

```ini
PDF_SIGNING_MODE=certificate
PDF_SIGNING_PFX=/private/secrets/vicam-signing.p12
PDF_SIGNING_PASSWORD=YOUR_PRIVATE_SECRET
```

Restart the server. Invalid/missing/expired certificates prevent startup. Issuance reloads the certificate and fails atomically if signing becomes unavailable: there is no unsigned fallback for signed issuance. Production rejects test mode and self-issued certificates. Use trusted HTTPS hosting and a confirmed PUBLIC_ORIGIN for live QR verification.

A non-self-issued certificate alone does not establish public trust. The deployment operator must validate the certificate chain and company identity with the issuing provider and test the result in recipients' PDF readers. Runtime issuance does not fetch online certificate revocation status. Establish certificate revocation/renewal procedures and stop signing immediately if the key is compromised. Keep previous certificates and original PDFs available for validation.

This is baseline PAdES certification with DocMDP no changes, SHA-256 and an embedded certificate chain. It has no trusted timestamp, embedded revocation evidence or long-term validation profile. Recipients must validate trust and certificate status separately. A handwritten-looking mark is not needed; use the reader's signature panel.

## Local test only

With signing initially disabled, create a private, encrypted test certificate:

```sh
python -m app.manage create-test-signing-certificate /PRIVATE_TEST_FOLDER/vicam-test.p12
```

The command prompts for a matching password of at least 12 characters, creates a new file with restrictive permissions and refuses to overwrite. It is unavailable in production. Configure `PDF_SIGNING_MODE=test`, its private path and password, restart, sign in with issuing permission, and issue a saved sent/accepted quotation or issued invoice.

The PDF explicitly says LOCAL TEST SIGNATURE. It is self-signed and untrusted by default. Do not send it as proof of VICAM's company identity. Test certificates are not bundled with this package.

## Document workflow

Enter/save the scope, pricing and final status, issue the PDF, and send the exact downloaded file through your chosen process. Issuing does not email it. Downloads preserve the original signed bytes. Changes to source records create an earlier-version warning; issue a new original for updated terms. Withdraw stops public access but does not destroy staff originals or alter previously downloaded signature bytes.

Recipients scan on VICAM's confirmed domain, compare details, and optionally select their PDF for a local exact-file comparison. No client PDF is uploaded. A copied QR on an edited PDF still fails exact byte comparison. Readers should independently validate the certificate signature.

Totals and VAT/discount treatment remain manually entered in this version; it does not provide a calculated item/tax ledger or tax authority integration. Review company particulars and customer-facing billing requirements before use.
