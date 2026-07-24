# Web App — invoice-emailing fragment

> Scout feature-fragment map. Repo: `acme/web-app` (Vue 3 SPA). Scope: the invoice
> email UI only.

## Role in the feature
Surfaces the invoice email state to tenant admins: a send-status badge on the invoice
detail page, a "Resend email" action, and the billing-contact fallback setting.

## Screens / components
- `InvoiceDetailPage.vue` — shows `EmailStatusBadge` (`Queued`/`Sent`/`Failed`/
  `Never sent`); polls the Notification API status endpoint every 30s while `Queued`.
- `ResendEmailButton.vue` — calls Billing API `POST /api/invoices/{id}/resend-email`;
  disabled while the invoice status is not `Finalized`; shows a toast on 409.
- `BillingContactSettings.vue` — edits the tenant billing contact used as the
  recipient fallback when an invoice has no `RecipientEmail`.

## Code path (resend click)
1. `ResendEmailButton` calls the `useInvoiceEmail().resend(invoiceId)` composable.
2. The composable POSTs to the Billing API; on 202 it sets the badge to `Queued`
   optimistically; on 409 it shows an "Invoice must be finalized first" toast; on a
   network error it shows a generic retry toast.
3. Badge polling resumes until the status leaves `Queued`.

## Cross-service calls
- → Billing API `POST /api/invoices/{id}/resend-email`
- → Notification API `GET /api/emails/invoice/{invoiceId}/status` (30s polling)

## Gotchas observed in code
- The optimistic `Queued` badge is not rolled back if the send later fails
  server-side; only a page refresh re-syncs the badge.
- Polling stops after 10 minutes (`MAX_POLL_MS`) even if the job is still `Queued`.
