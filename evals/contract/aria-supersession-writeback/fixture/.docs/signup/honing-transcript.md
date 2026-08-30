# Honing Transcript — Signup Email Verification

Rex, 2026-08-18. One question at a time; the user's answers below are authoritative and
were folded into `requirements.md`.

**Q1 — What has to be true before a new account can sign in?**
> They have to click the link we email them. Nothing else. No SMS, no support override —
> if we add a second path we have a second thing to get wrong.

**Q2 — How long should an unused verification link keep working?**
> A day. Long enough that someone who signs up at night and reads their mail in the
> morning is fine, short enough that a forwarded email from last month is worthless.

**Q3 — Which email provider are we sending through?**
> Mailgrid. That is already decided — we are on an annual contract with them and it is
> paid through next June. This is not a question I want reopened; whatever we build sends
> through Mailgrid.

**Q4 — Should a link work more than once?**
> No. One click verifies you. After that the link is spent. If someone clicks it twice
> they should just see that they are verified, not an error.

**Q5 — When a link is not usable, how much should the response say?**
> As little as possible. Same answer whether the token is fake, spent, or too old. I do
> not want that endpoint turned into a way to find out which tokens are real.

**Q6 — Anything about the tokens themselves?**
> Do not log them. Not in the app logs, not in the error tracker, not in analytics. If a
> token shows up in a log line, somebody with log access can verify someone else's
> account.

**Q7 — What is the stack?**
> Node on the API side, Postgres for storage. Same as everything else we run. Also fixed.
