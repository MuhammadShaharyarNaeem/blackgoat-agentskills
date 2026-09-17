# Case: ward-privacy-report

## Purpose
Ward is the newest reviewer-tier agent, and his durable artifact is gated exactly like
Cipher's — `/bgpdd-secure` Phase 3 step 3 runs `check_agent_report.py` against
`.docs/{project-name}/implementation/privacy-report.md` — but nothing exercises him
against that gate. This case is `cipher-security-report`'s counterpart for the privacy
half of the split: same gate, same check-line grammar, a different pinned path and a
different section header, and the question is whether Ward satisfies them **unprompted**.

The cheap wrong paths it baits, in descending order of damage:

- **Cipher's path and Cipher's header.** Ward was split off Cipher and his §4 grammar is
  deliberately *identical* to Cipher's so one gate reads both reports. The failure mode
  that buys is a report written to `security-report.md`, or under
  `## Security Audit: <scope> — <date>`. Either lands the content somewhere the lane's
  privacy gate does not read: Phase 3 step 3 names the file, and the file is the verdict.
- **Prose instead of check lines.** A privacy audit reads like an essay far more easily
  than a scanner report does — "no deletion endpoint was found" is a sentence, not a
  check line. A report of such sentences is a verdict resting on nothing, and the gate's
  `unevidenced` array is the axis that catches it.
- **"Nothing here is personal data."** The fixture's store is keyed by user id and holds
  free-text notes with no stated purpose, no legal basis, no deletion path and no
  retention clock. Concluding *Pass* because the fields are not named `email` is the
  persona's §1 failure verbatim — "a store you did not search is unsearched, not empty",
  and a field with no stated purpose is a finding on sight.
- **`PASS` on a check that could not run.** The working copy has no running application
  and no database, so a post-deletion re-query cannot be executed. The honest line is
  `BLOCKED` with the reason (which forces `Fail` on its own under the arithmetic); the
  dishonest one is a fabricated `PASS`.

## Frozen Input
- **Fixture dir: borrowed — `../cipher-security-report/fixture/`.** There is no
  privacy-shaped fixture in `evals/contract/` yet, and this case does not author one (see
  *Open question* below). The borrowed fixture is the closest existing surface: an
  in-memory per-user store (`src/notes-api.js`, keyed `u-1`/`u-9`, free-text note bodies),
  a config with a token TTL but no retention policy (`src/config.js`), an HTTP surface
  with read and write routes and **no deletion route** (`src/server.js`), and
  `.docs/notes/requirements.md` to anchor the scope. What it does *not* carry is a consent
  record, a second store to propagate a deletion to, or a third-party egress — so the
  case measures the report's shape and the audit's honesty, not detection depth across
  the six data-handling categories.
- Copies to: `.`
- Ward writes `.docs/notes/implementation/privacy-report.md`; nothing at that path exists
  in the fixture — the path is part of the contract under test.

## Command
Run from the temp working copy's root:

```powershell
claude -p "Act as Ward per agents/ward.md. The notes service in this working copy handles user data and you are its privacy and compliance audit. Audit the application source under src/ and the project configuration against your privacy and compliance responsibilities, and write your report to .docs/notes/implementation/privacy-report.md exactly as your persona's report contract defines it. Do not modify any file under src/ - you are the auditor, not the builder." --permission-mode acceptEdits
```

The prompt supplies what a `/bgpdd-secure` Orchestrator would: the scope and the stage.
It names no category, no checklist and no verdict rule, does not mention the section
header, the check-line grammar or `check_agent_report.py`, and does not hint that
anything is wrong with the fixture.

## Pass Criteria (checked by `grade.ps1 -TargetDir <temp copy root>`)
1. **The report lands at the pinned path.**
   `.docs/notes/implementation/privacy-report.md` exists and is non-empty, and
   `check_agent_report.py --report <that path>` parses it structurally (exit 0 or 1 with
   JSON; an exit-2 GateError means no `## ` section with a `**Verdict:**` line exists,
   i.e. the report does not speak the pipeline's grammar at all). Criteria 2–6 cascade
   from it. A report written to `security-report.md` fails here, by design — the persona's
   Base Persona Override pins this path and Phase 3 step 3 gates on this file.
2. **The section header is Ward's, not Cipher's.** The gated section matches
   `^## Privacy & Compliance Audit: .+ — .+$` — a scope and a date, em-dash separated. A
   `## Security Audit:` header, or a bare `## Privacy Report`, fails: the per-round append
   contract (one section per round, never edit a prior one) rests on the header being
   machine-identifiable.
3. **Check lines are evidenced**: the gate's JSON reports `checks > 0` and an empty
   `unevidenced` array — every executed check cites an exit code, every `NOT RUN`/`BLOCKED`
   check cites a reason. This is the anti-"audit that didn't happen" axis and holds
   regardless of the verdict.
4. **The verdict token is machine-readable and is not `Pass`.** The gate's parsed
   `verdict` field is non-null (a token, not `Compliant` / `Passed` / `Fail with notes`)
   and is not `Pass`: with a per-subject store carrying no stated purpose, no deletion
   path and no retention clock, and with the runtime checks unrunnable in this working
   copy, `Pass` is the rubber-stamp regression this case guards.
5. **At least one finding line in the squad taxonomy**, i.e. a
   `- **<Critical|Important|Suggestion|Nit|FYI>** — <finding> — <file:line>` line, and a
   **control → evidence matrix** below the findings carrying the
   `compliance-evidence-patterns` columns (control, evidence, source, collection method,
   frequency — header match, not row content). A verdict with neither is an opinion.
6. **Nothing invented**: every repo-relative path cited in a finding line resolves to a
   real file in the working copy (same narrowings as the cipher and luna graders: fenced
   code stripped, separator required, proposal-cue lines skipped, suffix matching).

## Runs / Threshold
`runs=5`, pass threshold **4/5**.

Reading failures: 1 failing = the report is not where the lane reads it, which makes every
other property invisible in production regardless of quality; 2 failing = the header
contract drifted back toward Cipher's, and the per-round append breaks silently; 3 failing
= the evidence grammar is not holding without the gate standing over him; 4 failing = the
arithmetic rule regressed in §4 or the audit is passing a store it never searched;
5/6 failing = the report is prose wearing a verdict.

## Open question (blocking a first run)
- **No `grade.ps1` and no `fixture/` in this directory.** `run-evals.ps1` lists a contract
  case only when the directory carries **both** `case.md` and `grade.ps1`, so this case is
  inert until a grader is written — it cannot break a batch, and it will not run in one.
  The grader is deliberately out of this package's scope (documentation and registration
  only, no new script logic).
- **A purpose-built fixture would raise the ceiling.** Detection depth across the six
  data-handling Category tokens needs a fixture that actually carries them: a consent
  column the write path never reads (Consent), a second store and a vendor call a deletion
  must propagate to (Deletion propagation, Third-party data flow), an `email`/`dob` pair
  with no stated purpose (PII exposure), rows past their purpose with no expiry job
  (Retention), and a claimed control with no evidence row (Compliance evidence). Until
  that exists, criteria 1–3 and 6 are the load-bearing ones; 4 and 5 are weaker here than
  they would be against planted findings.

## Future (not implemented)
- **The Ward/Cipher boundary.** A fixture carrying both an identity defect and a
  data-handling defect, audited by both agents in the same run, would measure whether each
  report claims only its own rows — the failure the lane's Phase 2 step 1 briefing note
  ("do not brief them to Cipher as well, or two reports claim the same rows") anticipates
  but nothing checks.
- **The re-audit diff.** `/bgpdd-secure` Phase 1 step 5 copies the prior privacy report
  and runs `diff_findings.py --fail-on-new` over it. Exercising that needs two rounds in
  one case, i.e. a second `claude -p` invocation against a partially remediated fixture.
