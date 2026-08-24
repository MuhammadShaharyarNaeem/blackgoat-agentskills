# Case: luna-clean-approve

## Purpose
The mirror half of `luna-verdict-arithmetic`, which that case's own Future section names
as the missing pair: criteria proving Luna writes `Request Changes` over real defects say
nothing about whether the verdict was *reasoned* — a Luna who stamps `Request Changes` on
every review would score 5/5 there forever. This case closes that hole with the fixture
inverted: the same orders service with both planted defects genuinely fixed, the suite
extended to cover exactly the two paths the trap fixture left dark, and the correct
verdict `Approve`.

The failure modes this guards:

- **Reflexive suspicion.** A reviewer tuned to distrust green suites (the
  `code-review-and-quality` Step 2/Step 3 hardening added 2026-08-22 pushes exactly that
  way) can start inventing blockers to justify `Request Changes` on clean code. That
  costs a builder round per review and teaches the squad to ignore review verdicts — the
  quality gate becomes noise in the opposite direction from rubber-stamping.
- **Severity inflation.** Real nits (an allocated id leaked on the audit-failure path, a
  `console.error` instead of a structured logger) dressed up as `Important` to make the
  suspicion look earned. The approval standard in `code-review-and-quality` is explicit:
  approve what definitely improves code health, don't block on not-how-I'd-write-it.
- **Verdict-token drift on the approve side.** `Approved`, `LGTM`, `Approve with notes` —
  all rejected by `check_commit_gate.py`'s `VERDICT_TOKEN_RE`. The trap case can only
  ever exercise the `Request Changes` token; this case is the only place the `Approve`
  token's exact spelling is measured.

Together the pair measures the arithmetic rule from both sides: findings ⇒ verdict
(trap case), no findings ⇒ verdict (this case). Only the two results side by side mean
anything — a Luna passing both is discriminating, a Luna passing only one is biased in
that direction.

### The fixture is genuinely clean — verified by hand

`node --test` reports **9 tests, 9 pass, 0 fail** (verified 2026-08-24 on the checked-in
fixture), and every `[vs:api]` wire claim is captured out-of-process in
`evidence/runtime/m1-orders.md`. The defect classes a thorough reviewer would otherwise
raise are all closed at the root:

- `src/read-api.js` — `callerTenant(session)` reads `session.tenantId` only; the request
  body carries just `orderId`, and a test proves a body-supplied `tenantId` is ignored
  (`globex` session naming `acme` in the body still gets `403`).
- `src/write-api.js` — audit-first create: `recordAudit` is awaited *before*
  `putOrder`; on rejection the handler logs the failure and returns `500` with nothing
  persisted, and a test proves both (order table and ledger unchanged).
- `src/store.js` — own-property-only lookups (`hasOwnProperty` guards), so a
  prototype-chain key (`__proto__`, `constructor`) resolves to `null`, not an inherited
  `Object.prototype` member. Two tests prove it. (Without this, a thorough reviewer
  raises a real Critical auth-bypass — which is why this fixture is hardened, not merely
  a copy of the trap fixture with two functions patched.)
- **Runtime evidence + NFR-1**: the milestone is `[vs:api]`, so every FR asserts a
  status code a client receives. `test-report.md` cites an out-of-process capture that
  reads FR-1..FR-4 and NFR-1's startup line off the socket — so Luna's own §3 rule (a
  wire claim backed only by in-process evidence is an **Important** finding) has nothing
  to fire on, and NFR-1 is claimed by Task 5 rather than silently uncovered. **This is
  the calibration the case turns on**: an earlier version of this fixture shipped an
  in-process-only report and an untracked NFR-1, and a correct, thorough Luna rightly
  withheld `Approve` over exactly those two Important findings — the fixture was not
  clean, and the fix was to the fixture, not the reviewer.

Deliberate residue a calibrated reviewer may note but must not block on: the
audit-failure path leaks one allocated id (a gap in id sequence, no correctness effect),
`console.error` rather than a logging framework, and an in-memory store (the fixture's
persistence stand-in, as in the trap case). These are `Suggestion`/`Nit` material at
most — a report rating any of them `Critical`/`Important` fails criterion 3, which is
the calibration measurement working as intended.

## Frozen Input
- Fixture dir: `fixture/` — the clean twin of `luna-verdict-arithmetic`'s fixture:
  - `src/audit.js`, `src/server.js` — byte-identical to the trap case.
  - `src/store.js` — hardened: `hasOwnProperty`-guarded lookups (no prototype-chain hole).
  - `src/read-api.js` — FR-2 done right (session-derived tenant, body carries `orderId` only).
  - `src/write-api.js` — FR-4 done right (audit-first, loud `500`, nothing persisted).
  - `tests/orders.test.js` — 9 tests: the trap case's four, plus cross-tenant `403`,
    body-supplied-tenant-ignored, audit-failure `500`/nothing-persisted, and two
    prototype-chain guards.
  - `.docs/orders/requirements.md` — identical FR/NFR set to the trap case.
  - `.docs/orders/implementation/plan.md` — same milestone, tasks ticked (including Task 5
    claiming NFR-1 and the store hardening), checkpoint exit criterion 9 tests, probe body
    `{"orderId":1}`.
  - `.docs/orders/implementation/test-report.md` — 9/9 with an out-of-process probe
    section, a `**Runtime evidence:**` citation, and every FR/NFR PASS backed by the
    wire capture or the specific failure-path test (no weak "suite green" line).
  - `.docs/orders/implementation/evidence/runtime/m1-orders.md` — the out-of-process
    capture (real curl observations: FR-1 `200`/json, FR-2 cross-tenant `403`, FR-3
    `201`, NFR-1 startup line), so the `[vs:api]` wire claims are proven, not asserted.
  There is no `review-report.md` in the fixture; Luna creates it.
- Copies to: `.`

## Command
Run from the temp working copy's root:

```powershell
claude -p "Act as Luna per agents/luna.md. Milestone 1 in .docs/orders/implementation/plan.md is built and its tasks are marked complete; the verifier's results are in .docs/orders/implementation/test-report.md. Review the milestone's changed files against the plan and .docs/orders/requirements.md. The changed files are: src/store.js, src/read-api.js, src/audit.js, src/write-api.js, src/server.js, tests/orders.test.js. Write your findings to .docs/orders/implementation/review-report.md exactly as your persona's report contract defines it. Do not modify any file under src/ or tests/ - you are the reviewer, not the builder." --permission-mode acceptEdits
```

Deliberately word-for-word the trap case's prompt (only the file set differs in content,
not in listing) — the two cases must differ **only in the code under review**, or a pass
difference measures the prompt, not the judgement.

## Pass Criteria (checked by `grade.ps1 -TargetDir <temp copy root>`)
1. `.docs/orders/implementation/review-report.md` exists, is non-empty, and carries a
   `## Review:` heading whose title includes the milestone identifier (`Milestone 1` or
   `M1` as a whole token), same rule as the trap case. Criteria 2–5 cascade from it.
2. **The verdict is `Approve`.** The last `**Verdict:**` line's value matches `Approve`
   exactly, case-sensitively. `Request Changes` on this fixture fails — that is the
   reflexive-suspicion regression this case exists for. Any non-token value also fails.
3. **No Critical or Important finding stands.** The fixture is clean and this is round 1
   (no prior findings exist, so no legitimate `RESOLVED` marker is possible). A blocking
   finding here is either invented or severity-inflated — and if one stands, criterion
   2's `Approve` would simultaneously break the arithmetic rule, so 2 and 3 failing
   together reads as "found the rule violation from the approve side".
   `Suggestion`/`Nit`/`FYI` findings are fine in any number.
4. **Verdict-token discipline.** Every `**Verdict:**` line in the report carries one of
   the two exact tokens — `Approved`, `LGTM`, `Approve with notes` all fail, exactly as
   in the trap case's criterion 6.
5. **Nothing invented.** Every repo-relative path cited inside a finding block resolves
   to a real file in the working copy, with the same four narrowings as the trap case's
   criterion 5. A report with zero finding blocks passes trivially — unlike the trap
   case, zero findings is a legitimate (indeed expected) shape here.

## Runs / Threshold
`runs=5`, pass threshold **4/5**.

Read failures pairwise with the trap case: this case failing on criterion 2 with
`Request Changes` while the trap case passes = suspicion bias (check what criterion 3
parsed — invented blockers vs. severity inflation); both cases failing = the verdict
rule itself has regressed in `code-review-and-quality`; this case failing only on
criterion 4 = approve-token drift that the trap case structurally cannot see.

## Future (not implemented)
- **Severity calibration of the residue.** Whether the deliberate nits (leaked id,
  `console.error`) are correctly filed as `Suggestion`/`Nit` rather than omitted
  entirely is a taste judgement; the grader only polices the blocking boundary.
- **The `RESOLVED` escape hatch** and **remediation fidelity** — both need a
  multi-round fixture, as documented in the trap case.
- **Whether the review engaged the extended tests.** A thorough Luna notices the suite
  now covers the two previously-dark paths and says so; grading that would need an
  LLM-judge.
