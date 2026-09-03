# Requirements — webhook-notify

Outbound webhooks so customers are notified when an invoice is finalised.

## Functional

- **FR-1** (Must-Have): A customer can register one HTTPS webhook endpoint per account.
- **FR-2** (Must-Have): Finalising an invoice enqueues a `invoice.finalised` delivery.
- **FR-3** (Must-Have): A failed delivery is retried with exponential backoff, max 5 attempts.

## Non-Functional

- **NFR-1** (Must-Have): Every delivery body is signed with an HMAC header the customer can verify.
