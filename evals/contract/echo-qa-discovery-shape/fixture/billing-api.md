# Billing API — invoice-emailing fragment

> Scout feature-fragment map. Repo: `acme/billing-api` (ASP.NET Core). Scope: only the
> code paths involved in emailing finalized invoices.

## Role in the feature
Owns invoice finalization. When an invoice transitions to `Finalized`, it queues an
email request to the Notification API. Also exposes the resend endpoint the web app
calls.

## Endpoints
| Method | Route | Purpose |
|---|---|---|
| POST | `/api/invoices/{id}/finalize` | Finalizes a draft invoice; side effect: queues the invoice email |
| POST | `/api/invoices/{id}/resend-email` | Re-queues the invoice email for an already-finalized invoice |

## Code path (finalize)
1. `InvoicesController.Finalize` — validates the invoice is in `Draft` status.
2. `InvoiceService.FinalizeAsync` — sets `Status = Finalized` and `FinalizedAtUtc`,
   persists via `InvoiceRepository`.
3. `InvoiceEmailDispatcher.QueueAsync` — builds an
   `InvoiceEmailRequest { InvoiceId, TenantId, RecipientEmail }` and POSTs it to the
   Notification API at `/api/emails/invoice`.
4. On a non-2xx from the Notification API: logs a warning and writes an
   `EmailDispatchFailures` row — finalization itself still succeeds (email dispatch is
   best-effort at this layer).

## Code path (resend)
1. `InvoicesController.ResendEmail` — 404 if the invoice is not found, 409
   (`invoice_not_finalized`) if status is not `Finalized`.
2. Reuses `InvoiceEmailDispatcher.QueueAsync` (same request shape, `IsResend = true`).

## Data
- `Invoices` table: `Status` (`Draft`/`Finalized`/`Void`), `FinalizedAtUtc`,
  `RecipientEmail` (nullable — falls back to the tenant billing contact when null).
- `EmailDispatchFailures` table: dispatch errors surfaced on the ops dashboard.

## Cross-service calls
- → Notification API `POST /api/emails/invoice` (fire-and-forget with a 10s timeout).

## Gotchas observed in code
- Finalizing an already-finalized invoice returns 409, not an idempotent 200.
- The `RecipientEmail` fallback to the tenant billing contact happens inside
  `InvoiceEmailDispatcher`, not in the service layer.
