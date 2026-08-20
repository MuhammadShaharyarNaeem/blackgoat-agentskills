---
name: security-and-hardening
description: Hardens code against vulnerabilities. Use when handling user input, authentication, data storage, or external integrations. Use when building any feature that accepts untrusted data, manages user sessions, or interacts with third-party services. Squad-internal execution contract loaded by agents via their Methodology Dependencies table.
---

# Security and Hardening

Treat every external input as hostile, every secret as sacred, every authorization check as mandatory. Security isn't a phase — it constrains every line of code touching user data, authentication, or external systems.

## Worker Execution Contract

This is the operational spine. Follow it as written.

### Process: Threat Model First

Controls bolted on without a threat model are guesses. Spend five minutes thinking like an attacker before hardening:

1. **Map trust boundaries.** Where untrusted data enters: HTTP requests, form fields, file uploads, webhooks, third-party APIs, message queues, **LLM output**. Every boundary is attack surface.
2. **Name the assets.** Credentials, PII, payment data, admin actions, money movement.
3. **Run STRIDE per boundary** — a quick lens, not a ceremony:

| Threat | Ask | Typical mitigation |
|---|---|---|
| **S**poofing | Can someone impersonate a user/service? | Authentication, signature verification |
| **T**ampering | Can data be altered in transit or at rest? | Integrity checks, parameterized queries, HTTPS |
| **R**epudiation | Can an action be denied later? | Audit logging of security events |
| **I**nformation disclosure | Can data leak? | Encryption, field allowlists, generic errors |
| **D**enial of service | Can it be overwhelmed? | Rate limiting, input size caps, timeouts |
| **E**levation of privilege | Can a user gain rights they shouldn't? | Authorization checks, least privilege |

4. **Write abuse cases beside use cases.** For each feature: "how would I misuse this?" → make that the first test.

Can't name the trust boundaries for a feature → not ready to secure it. OWASP **A04: Insecure Design** — most breaches begin in design, not code.

### The Three-Tier Boundary System

#### Always Do (No Exceptions)

- **Validate all external input** at the system boundary (API routes, form handlers)
- **Parameterize all database queries** — never concatenate user input into SQL
- **Encode output** to prevent XSS (use framework auto-escaping, don't bypass it)
- **Use HTTPS** for all external communication
- **Hash passwords** with bcrypt/scrypt/argon2 (never store plaintext)
- **Set security headers** (CSP, HSTS, X-Frame-Options, X-Content-Type-Options)
- **Use httpOnly, secure, sameSite cookies** for sessions
- **Run `npm audit`** (or equivalent) before every release
- **Mask PII in UI**: never render Personally Identifiable Information (PII) in plain text; apply a UI-level masking function before rendering.

#### Ask First (Requires Human Approval)

- Adding new authentication flows or changing auth logic
- Storing new categories of sensitive data (PII, payment info)
- Adding new external service integrations
- Changing CORS configuration
- Adding file upload handlers
- Modifying rate limiting or throttling
- Granting elevated permissions or roles

#### Never Do

- **Never commit secrets** to version control (API keys, passwords, tokens)
- **Never log sensitive data** (passwords, tokens, full credit card numbers)
- **Never trust client-side validation** as a security boundary
- **Never disable security headers** for convenience
- **Never use `eval()` or `innerHTML`** with user-provided data
- **Never store sessions in client-accessible storage** (localStorage for auth tokens)
- **Never expose stack traces** or internal error details to users

### OWASP Prevention Areas

One-line prevention rule per category. For code patterns and worked examples, see the [security deep dive](references/security-deep-dive.md).

- **Injection (SQL/NoSQL/OS command):** parameterize every query — never concatenate user input.
- **Broken Authentication:** hash passwords with bcrypt/argon2; manage sessions via httpOnly, secure, sameSite cookies.
- **XSS:** rely on framework auto-escaping; sanitize (e.g. DOMPurify) if you must render HTML.
- **Broken Access Control:** check resource ownership on every request — authentication is not authorization.
- **Security Misconfiguration:** set security headers (helmet), a Content Security Policy, and a CORS origin allowlist.
- **Sensitive Data Exposure:** strip sensitive fields from API responses; secrets come from environment variables.
- **SSRF:** allowlist scheme + host for any server-side fetch of user-influenced URLs, reject private/reserved IPs, forbid redirects.

### AI / LLM Rule

Treat all model output as untrusted input — never pass it into `eval`, SQL, a shell, or `innerHTML`. Keep secrets and cross-tenant data out of prompts. Full OWASP-LLM mapping and code patterns are in the [security deep dive](references/security-deep-dive.md).

### Secrets

Never commit secrets to version control; if a secret is ever committed, rotate it immediately — deleting the line or rewriting history is not enough.

### Security Review Checklist

```markdown
### Authentication
- [ ] Passwords hashed with bcrypt/scrypt/argon2 (salt rounds ≥ 12)
- [ ] Session tokens are httpOnly, secure, sameSite
- [ ] Login has rate limiting
- [ ] Password reset tokens expire

### Authorization
- [ ] Every endpoint checks user permissions
- [ ] Users can only access their own resources
- [ ] Admin actions require admin role verification

### Input
- [ ] All user input validated at the boundary
- [ ] SQL queries are parameterized
- [ ] HTML output is encoded/escaped
- [ ] Server-side URL fetches are allowlisted (no SSRF to internal services)

### Data
- [ ] No secrets in code or version control
- [ ] Sensitive fields excluded from API responses
- [ ] PII encrypted at rest (if applicable)

### Infrastructure
- [ ] Security headers configured (CSP, HSTS, etc.)
- [ ] CORS restricted to known origins
- [ ] Dependencies audited for vulnerabilities
- [ ] Error messages don't expose internals

### Supply Chain
- [ ] Lockfile committed; CI installs with `npm ci`
- [ ] New dependencies reviewed (maintenance, downloads, postinstall scripts)

### AI / LLM (if used)
- [ ] Model output treated as untrusted (no eval/SQL/innerHTML/shell)
- [ ] Secrets and other users' data kept out of prompts
- [ ] Tool/agent permissions scoped; destructive actions require confirmation
```

### Verification Checklist

After implementing security-relevant code:

- [ ] `npm audit` shows no critical or high vulnerabilities
- [ ] No secrets in source code or git history
- [ ] All user input validated at system boundaries
- [ ] Authentication and authorization checked on every protected endpoint
- [ ] Security headers present in response (check with browser DevTools)
- [ ] Error responses don't expose internal details
- [ ] Rate limiting active on auth endpoints
- [ ] Server-side URL fetches validated against an allowlist (no SSRF)
- [ ] LLM/model output validated and encoded before use (if AI features present)

### Escalate When

| WHEN | DO |
|---|---|
| Any "Ask First" boundary item comes up | Stop; report to the Orchestrator (manager) for approval before proceeding |
| A critical/high vulnerability has no available fix | Report to the Orchestrator (manager) with triage findings |
| Can't name the trust boundaries for a feature | Escalate to the Orchestrator (manager) rather than harden blind |

## See Also

Detailed checklists and pre-commit verification steps: `{PLUGIN_ROOT}/../references/security-checklist.md`.

## Deep Dive

Read on demand — not needed to execute the contract above:

- [Security deep dive](references/security-deep-dive.md) — when to use, the full OWASP Top 10 pattern walkthroughs with code, input validation and file upload safety, npm-audit triage, supply-chain hygiene, rate limiting, secrets management detail, the full Securing AI/LLM Features section, common rationalizations, and red flags.
