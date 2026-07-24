# Notification API — invoice-emailing fragment

> Scout feature-fragment map. Repo: `acme/notification-api` (ASP.NET Core + Hangfire).
> Scope: the invoice email pipeline only.

## Role in the feature
Receives invoice email requests from the Billing API, renders the invoice email from a
template, sends it through the SMTP gateway, and retries transient failures.

## Endpoints
| Method | Route | Purpose |
|---|---|---|
| POST | `/api/emails/invoice` | Accepts an `InvoiceEmailRequest`, enqueues a render+send job, returns 202 |
| GET | `/api/emails/invoice/{invoiceId}/status` | Latest send status for an invoice (`Queued`/`Sent`/`Failed`) |

## Code path (send)
1. `InvoiceEmailController.Enqueue` — validates `RecipientEmail` format; 400
   (`invalid_recipient`) on failure.
2. `EmailJobScheduler.Enqueue` — persists an `EmailJobs` row (`Status = Queued`) and
   schedules `InvoiceEmailJob`.
3. `InvoiceEmailJob.ExecuteAsync` — fetches the invoice PDF from the Billing API,
   renders `InvoiceEmailTemplate` (subject includes the invoice number), sends via
   `SmtpGateway`.
4. Success: `Status = Sent`, `SentAtUtc` stamped. SMTP failure: up to 3 retries with
   1/5/15-minute backoff, then `Status = Failed` with `LastError` recorded.

## Data
- `EmailJobs` table: `InvoiceId`, `TenantId`, `Status`, `AttemptCount`, `LastError`,
  `SentAtUtc`.

## Cross-service calls
- ← Billing API posts email requests here.
- → Billing API `GET /api/invoices/{id}/pdf` during template rendering.

## Gotchas observed in code
- Duplicate enqueues for the same `InvoiceId` within 5 minutes are coalesced (dedupe
  key: `InvoiceId + Template`), so a rapid double "resend" sends exactly one email.
- The status endpoint returns 404 until the first `EmailJobs` row exists — the web app
  treats that 404 as "never sent".
