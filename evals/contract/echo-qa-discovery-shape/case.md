# Case: echo-qa-discovery-shape

## Purpose
Guards against Echo producing a discovery QA baseline the downstream planning squad
can't consume: a missing `overview.md`, `QA/code-workflow.md`, or `QA/manual-testing.md`,
or a `manual-testing.md` that drops the strict `GO → DO → ASSERT` table structure and
P0/P1/P2 priority flags required by `agents/echo.md`. Aria reads `overview.md` first and
drills into the QA docs on demand during bgpdd-plan Phase 2 — if the trio is incomplete,
or the manual baseline is free-form prose instead of the table format, the legacy
behavior baseline silently degrades into something nobody can regression-test against.

## Frozen Input
- Fixture dir: `fixture/` — three Scout-style per-API feature-fragment maps for an
  invented `invoice-emailing` feature: `billing-api.md` (invoice finalization triggers
  an email request; resend endpoint), `notification-api.md` (renders and sends the
  email, retries with backoff), and `web-app.md` (status badge, resend button,
  billing-contact fallback setting). Together they contain the endpoints, code paths,
  tables, and cross-service calls Echo needs to synthesize the overview and
  reverse-engineer a manual test baseline. Echo writes new files only — she does not
  modify the per-API inputs.
- Copies to: `.docs/summary/invoice-emailing`

## Command
Run from the temp working copy's root:

```powershell
claude -p "Act as Echo per agents/echo.md. Read all per-API files in .docs/summary/invoice-emailing/ and synthesize, in this order: (1) .docs/summary/invoice-emailing/overview.md, (2) .docs/summary/invoice-emailing/QA/code-workflow.md, (3) .docs/summary/invoice-emailing/QA/manual-testing.md. manual-testing.md must use the strict GO -> DO -> ASSERT table structure for each test case, with P0/P1/P2 priority flags, per agents/echo.md." --permission-mode acceptEdits
```

## Pass Criteria (checked by `grade.ps1 -TargetDir <temp copy root>`)
1. `.docs/summary/invoice-emailing/billing-api.md` is present (fixture sanity check).
2. `.docs/summary/invoice-emailing/overview.md` was produced.
3. `.docs/summary/invoice-emailing/QA/code-workflow.md` was produced.
4. `.docs/summary/invoice-emailing/QA/manual-testing.md` was produced.
5. `manual-testing.md` contains at least one markdown table row with adjacent `GO`,
   `DO`, and `ASSERT` columns in that order (extra columns before `GO` or after
   `ASSERT` are fine).
6. `manual-testing.md` contains at least one `P0` priority flag AND at least one `P1`
   or `P2` flag.

`grade.ps1` exits `0` only if all six pass; otherwise it exits `1` and prints which
criterion failed.

## Runs / Threshold
`runs=5`, pass threshold **4/5**.

## Future (not implemented)
Whether the manual test cases are *faithful* to the fixture's code workflows (right
preconditions, right assertions, the real regression risks) is a judgment call outside
what a shape-checker can decide. Not implemented here.
