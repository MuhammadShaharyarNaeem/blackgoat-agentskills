# Data Privacy Checklist

Depth for `security-and-hardening/SKILL.md`'s Data privacy pointer. Cipher runs this as
part of the standing Security Report (`agents/cipher.md` §4) — every line follows that
section's check-line grammar exactly:

```
- <check name>: PASS|FAIL|BLOCKED|NOT RUN — `<command executed>` — exit <N> — <terse counts/result> — capture: evidence/security/<file>.md
```

`capture:` is required on `PASS`/`FAIL` and must record the same exit code the line claims;
`BLOCKED`/`NOT RUN` carry their reason instead and cite nothing. A `PASS`/`FAIL` line with no
capture is refused by the gate (`check_uncaptured`) — see `pipeline-tools/SKILL.md`
(`check_agent_report.py`) for the full grammar this checklist inherits rather than restates.

## PII classes

Classify every field the system touches into one of these before checking where it may
live. A field can belong to more than one class (an email is both an identifier and a
contact method) — audit it under each class it belongs to.

- **Identifiers** — name, government ID, device ID, IP address treated as identifying, any
  internal user/customer ID that maps 1:1 to a real person.
- **Contact** — email address, phone number, mailing address.
- **Financial** — card number, bank account/routing number, billing address, transaction
  history.
- **Health** — any medical, diagnostic, or health-insurance data (PHI where regulated).
- **Credentials** — password, API key, session token, MFA secret, security-question answer.

## Where each class may live

For every store, transport, and sink the system has (application logs, error-tracking
service, analytics events, URLs/query strings, cache keys, message-queue payloads, backups),
name which PII classes are permitted there and which are forbidden. Three forbidden
placements are non-negotiable regardless of store:

- **Never in logs** — no PII class is written to application, access, or error logs in
  plaintext. Structured loggers must redact by field name (see Log redaction below).
- **Never in URLs** — no PII class appears in a URL path or query string (proxies, browser
  history, and access logs all retain URLs verbatim; see `security-and-hardening/SKILL.md`'s
  own privacy rule under Escalate/Ask First for the related "never place personal data in
  URL parameters" boundary).
- **Never in analytics events** — no PII class is sent to a third-party analytics or
  product-metrics pipeline as an event property; use the internal user ID only if the
  analytics vendor is itself a reviewed third-party flow (see Third-party data flows below).

Check line:

```
- PII placement audit: PASS|FAIL — `<grep/scanner command over logs, event schemas, and route definitions>` — exit N — <count of forbidden placements found> — capture: evidence/security/pii-placement.md
```

## Retention rule stated per store

For every store that holds a PII class, a retention period (or "indefinite, because <reason>")
is stated in that store's schema, config, or a co-located policy doc — not only in a
company-wide privacy policy no code enforces. Absence of a stated rule for a store holding
PII is a finding (`Important`, or `Critical` if the class is Financial/Health/Credentials).

Check line:

```
- Retention rule coverage: PASS|FAIL — `<command listing stores vs. documented retention>` — exit N — <N of M stores have a stated rule> — capture: evidence/security/retention-rules.md
```

## Deletion path exists and is tested

For every store holding a PII class, a deletion path (a user-initiated delete, an admin
tool, or a scheduled purge job enforcing the retention rule above) exists AND has a passing
test that exercises it end-to-end — not merely a code path that looks reachable. "Exists in
code, never exercised" is `FAIL`, not `PASS`.

Check line:

```
- Deletion path verified: PASS|FAIL|BLOCKED — `<test command exercising the delete/purge path>` — exit N — <result> — capture: evidence/security/deletion-path.md
```

## Log redaction verified by a capture

Prose claims about redaction are not evidence. Verify it by driving a real request that
carries a synthetic PII value through the system and inspecting the resulting log:

1. Issue a request containing a synthetic, clearly-fake value for the PII class under test
   (e.g. a fabricated card number or email that matches the field's format but is not real
   and not reused from any other fixture).
2. Capture the run: `python {PLUGIN_ROOT}/pipeline-tools/scripts/run_quiet.py --capture .docs/{project-name}/implementation/evidence/security/log-redaction-<class>.md -- <command that issues the request and then greps the resulting log>`.
3. The capture must show the log line for that request present, and the synthetic PII value
   **absent** — replaced by the redaction marker the logger emits (e.g. `[REDACTED]`,
   `***`). Finding the redaction marker is the PASS condition; finding the raw value is FAIL;
   finding neither (the log line is missing entirely) is FAIL, not PASS — it means the
   request was never observed, not that it was safely handled.

Check line:

```
- Log redaction (<PII class>): PASS|FAIL — `<request command> && grep <marker or synthetic value> <log path>` — exit N — <redaction marker found | raw value found | log line absent> — capture: evidence/security/log-redaction-<class>.md
```

Repeat per PII class actually present in the system — a system with no Financial data does
not need a Financial redaction capture, but the checklist's coverage should say so
explicitly (`NOT RUN — no Financial fields in this system`) rather than omit the line.

## Third-party data flows listed

Every third-party service that receives any PII class — analytics, error tracking, email/SMS
delivery, payment processor, support-ticket tool, LLM/AI vendor — is listed with: the PII
classes it receives, the legal basis or contractual justification (DPA on file, or "N/A —
processor never receives this class"), and whether the vendor's own retention terms are
known. An unreviewed third-party flow carrying a PII class is a finding (`Important`, or
`Critical` for Financial/Health/Credentials with no DPA on file).

Check line:

```
- Third-party flow inventory: PASS|FAIL — `<command or manual audit listing outbound integrations vs. PII classes sent>` — exit N — <N flows reviewed, M with a DPA on file> — capture: evidence/security/third-party-flows.md
```
