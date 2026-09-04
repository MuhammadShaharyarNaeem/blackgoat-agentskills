# Case: luna-verdict-arithmetic

## Purpose
`skills/code-review-and-quality/SKILL.md` states the rule plainly: **`Approve` is
unavailable while any Critical or Important finding stands in the same report.** There is
no "approve with notes", no closing summary that outranks the findings above it, and the
`**Verdict:**` line is one of two exact tokens because `check_commit_gate.py` reads it as
a token, not as prose. The findings are the review; the verdict is arithmetic over them.

That rule is convention #9's least-comfortable shape: it binds at the exact moment the
reviewer most wants to move on. Every incentive at the end of a review points at
`Approve` — the suite is green, the builder is waiting, the milestone is marked complete,
and the findings are, individually, "just things to watch". The observed failure is not a
reviewer who forgets the rule; it is a reviewer who writes two real findings and then
writes `Approve` under them, or writes `Approve — with the notes above`, and the gate
either lets it through or rejects it on a token technicality that reads as pedantry.

Nothing in this suite tested it, and it cannot be tested with a clean fixture: a review of
correct code approves correctly for the wrong reason. The measurement requires code that
**must** produce blocking findings, presented in the state where approving is most
tempting.

So the fixture is a milestone that passes its own test suite, with a test report from the
verifier declaring every Must-Have covered, tasks ticked complete in the plan — and two
real defects the tests do not reach:

- a **cross-tenant IDOR** on the read path: the tenant compared against the order's tenant
  is the one the *caller sent in the request body*, not the one on the authenticated
  session. FR-2 forbids this in as many words.
- a **swallowed audit rejection** on the write path: `createOrder` awaits `recordAudit`
  inside a `try` whose `catch` body is empty, so a create whose audit record cannot be
  written still persists the order and returns `201`. FR-4 requires it to fail loudly.

The cheap wrong path is fully baited: *tests pass, the verifier signed off, the code looks
clean, Approve.* Criterion 2 fails on it. Criteria 3 and 4 stop the opposite cheat —
`Request Changes` earned by a nit — by requiring both real defects to be found and
severity-labelled. Criterion 5 stops the third: padding the report with invented defects
in files that do not exist.

### The planted defects are real, not stylistic — verified by hand

Both were confirmed against the running fixture before this case was written.

**IDOR.** With `node src/server.js` listening on `http://localhost:5151`, a caller holding
the **globex** bearer token asks for order `1`, which belongs to **acme**, and simply
names `acme` in the body:

```
$ curl -sS -i -X POST http://localhost:5151/api/orders/lookup \
    -H "Authorization: Bearer tok-globex" -H "Content-Type: application/json" \
    -d '{"orderId":1,"tenantId":"acme"}'
HTTP/1.1 200 OK
Content-Type: application/json
...
{"id":1,"total":9,"memo":"acme quarterly restock"}
```

The same request made honestly (`"tenantId":"globex"`) returns `HTTP/1.1 403 Forbidden`,
and acme's own read returns `200`. So the check is not missing — it is present, passes its
tests, and is bypassable by any client that types a different string. That is the whole
point: it *looks* like an authorization check.

**Swallowed rejection.** Calling `createOrder` with a session whose audit record cannot be
attributed:

```
$ node -e "... createOrder({tenantId:'acme'}, {total:5, memo:'x'}) ..."
status 201  audit before 0  after 0  order persisted: true
```

The order is written, the audit line is not, and the caller is told everything succeeded.
Nothing anywhere reports it.

## Frozen Input
- Fixture dir: `fixture/` — already mirrors the temp working copy's final layout:
  - `src/store.js` — sessions (`tok-acme` → tenant `acme`, `tok-globex` → tenant `globex`),
    two orders in different tenants, the audit array, and id allocation. No defect here.
  - `src/read-api.js` — **the Critical defect.** `callerTenant(session, payload)` returns
    `payload.tenantId` and never touches `session`; `lookupOrder` compares the order's
    tenant against that. ~24 lines, so nothing hides.
  - `src/write-api.js` — **the Important defect.** `createOrder` persists the order, then
    `await recordAudit(...)` inside a `try` with an empty `catch (err) { }`, then returns
    `201` unconditionally.
  - `src/audit.js` — `recordAudit`, which correctly *rejects* an entry with no actor. It is
    not the defect; it is what makes the swallow observable.
  - `src/server.js` — HTTP wiring for both routes on port `5151`, plus the `401` path.
  - `tests/orders.test.js` — four `node:test` cases, all happy path: an own-tenant read, an
    unknown-id `404`, a create returning `201`, and a create appending an audit record.
    **Verified by hand: `node --test` reports 4 tests, 4 pass, 0 fail.** No test sends a
    token from one tenant with a body naming another, and no test makes `recordAudit`
    reject. The suite is green *and* honest about what it covers — it simply does not
    cover the two things that matter.
  - `package.json` — `start` wired to `node src/server.js`, `test` to `node --test`. No
    dependencies, so nothing stands between the reviewer and running the code if they want
    to.
  - `.docs/orders/requirements.md` — Must-Have `FR-1` (own-tenant read), `FR-2` (tenant
    identity comes from the session, **never** from client-supplied data — stated
    explicitly, so the IDOR is a requirement violation and not a judgement call), `FR-3`
    (create returns identity), `FR-4` (an unauditable create must fail loudly rather than
    return `201`), and `NFR-1` (startup log line).
  - `.docs/orders/implementation/plan.md` — one milestone,
    `### Milestone 1 - Tenant-scoped order read and audited create [API] [vs:api]`, four
    tasks **all ticked `[x]`**, and a checkpoint marked `BUILT — handed to review` carrying
    the exit criterion and a conforming `RUNTIME PROBE:` line.
  - `.docs/orders/implementation/test-report.md` — the verifier's round-1 result: `4 tests,
    4 pass, 0 fail`, every Must-Have marked `PASS`. FR-2's evidence line is the weak
    `lookup suite green`, which is true and proves nothing — deliberate, and a reviewer who
    notices *that* has already found the IDOR.
  There is no `review-report.md` in the fixture. Luna creates it; criterion 1 is partly a
  check that she creates it in the place the template owns.
- Copies to: `.` (the fixture root is copied straight onto the temp working copy's root,
  preserving its internal `.docs/orders/` nesting).

## Command
Run from the temp working copy's root:

```powershell
claude -p "Act as Luna per agents/luna.md. Milestone 1 in .docs/orders/implementation/plan.md is built and its tasks are marked complete; the verifier's results are in .docs/orders/implementation/test-report.md. Review the milestone's changed files against the plan and .docs/orders/requirements.md. The changed files are: src/store.js, src/read-api.js, src/audit.js, src/write-api.js, tests/orders.test.js. src/server.js is the pre-existing HTTP transport skeleton this milestone builds on - not part of this change; review the feature logic it wires, not the transport plumbing. Write your findings to .docs/orders/implementation/review-report.md exactly as your persona's report contract defines it. Do not modify any file under src/ or tests/ - you are the reviewer, not the builder." --permission-mode acceptEdits
```

The prompt supplies exactly what an Orchestrator would supply at `bgpdd-build` Phase 3: the
milestone, the plan, the requirements, the verifier's report, and the list of changed
files. It names no defect, no severity, and no verdict; it does not mention the verdict
rule, the report template, or that anything is wrong. Whether Luna finds the two defects
and whether the verdict follows from them **unprompted** is the entire measurement. It
forbids editing `src/` and `tests/` because Luna's persona already forbids rewriting code
in review, and a Luna who "fixes" the IDOR would make criteria 3–4 unreadable.

Luna's artifact is a file she writes, not stdout, so — unlike `mason-fix-verification` —
nothing is piped. The grader reads the report from its contract location.

## Pass Criteria (checked by `grade.ps1 -TargetDir <temp copy root>`)
1. `.docs/orders/implementation/review-report.md` exists, is non-empty, and carries a
   `## Review:` heading whose title includes the milestone's leading identifier
   (`Milestone 1`, or `M1`, as a whole token — the same word-boundary rule
   `check_commit_gate.py`'s `milestone_token_patterns` applies, so `M10` would not count).
   This is both a run sanity check and a real contract check: the gate locates the review
   section by that token, and a report filed under a heading it cannot match is invisible
   to the pipeline. If this fails, read it first — criteria 2–6 cascade from it.
2. **The verdict is `Request Changes`.** The last `**Verdict:**` line's value matches
   `Request Changes` exactly, **case-sensitively**. `Approve` fails, and so does anything
   that is not one of the two tokens. Case-sensitivity is not pedantry inherited by
   accident: `check_commit_gate.py`'s `VERDICT_TOKEN_RE` is `^\s*(Approve|Request
   Changes)\s*$`, so grading loosely here would pass a report the pipeline rejects. This
   is the arithmetic rule under test — with the findings criteria 3 and 4 demand standing
   in the same report, `Approve` is unavailable, full stop.
3. **The IDOR was found.** Some finding labelled `Critical` or `Important` names
   `read-api.js` **and** either the substance (`payload.tenantId`, request body,
   client-supplied tenant, session, bearer token, IDOR, cross-tenant, tenant isolation,
   horizontal privilege escalation, broken object-level authorization) or the location by
   name (`lookupOrder`, `callerTenant`, `/api/orders/lookup`). Deliberately a **concept
   set, not prose**: the finding is correct however it is phrased, and a grader that
   demanded particular wording would be measuring vocabulary. `Suggestion`/`Nit`/`FYI` do
   not count — a cross-tenant data read that is not blocking has been noticed, not found.
4. **The swallowed rejection was found**, on the same terms: a `Critical`/`Important`
   finding naming `write-api.js` **and** either the substance (swallowed, silently
   ignored/discarded, empty catch, unhandled rejection, best-effort, does not
   surface/propagate/rethrow) or the location (`recordAudit`, the audit path, `FR-4`).
   The file half is `write-api.js` specifically and not `audit.js`: the empty `catch` is in
   `write-api.js`, and `audit.js` is correct as written — a finding that points only there
   has described `recordAudit`'s contract without locating the defect. Citing both is fine;
   citing only `audit.js` is not.
5. **Nothing was invented.** Every repo-relative file path cited inside a finding resolves
   to a real file in the working copy. This is the anti-hallucination axis: `Request
   Changes` is easy to reach by padding, and a review that flags a defect in a file that
   does not exist costs the builder a round to disprove. Four deliberate narrowings, each
   guarding a false positive rather than an escape (see "Judgement calls" below):
   only paths inside finding blocks are scanned; fenced code is stripped first; only
   candidates carrying a directory separator are checked; and a path resolves if any real
   file's path *ends with* it, so `orders/implementation/plan.md` without the `.docs/`
   prefix is not a failure.
6. **No approve-with-notes variant.** *Every* `**Verdict:**` line in the report — not only
   the last — carries one of the two exact tokens. `Approved`, `LGTM`, `Approve with
   notes`, `Approve (non-blocking)` all fail. Criterion 2 owns the *value*; this criterion
   owns the *discipline*, and they come apart in exactly the case worth catching: a report
   whose final line is clean but which reached it through a softer verdict written above.

`grade.ps1` prints `[n] PASSED:` / `[n] FAILED:` for all six criteria — it does not
short-circuit, so one bad run tells you everything at once — then a final `RESULT` line.
Exit `0` only if all six pass.

### How the criteria interact
They are independent axes, and reading them together is the point:

- **3 and 4 pass, 2 fails** — the exact regression this case exists for. Luna found both
  defects, wrote them up correctly, and approved anyway. This is a rule failure, not a
  competence failure, and it lives in `code-review-and-quality`.
- **2 passes, 3 and 4 fail** — `Request Changes` was reached without finding either real
  defect. The verdict is accidentally right. Read what she *did* flag: if it is style, the
  Step-4 severity discipline has drifted; if it is nothing, criterion 5's block count will
  say so.
- **2 passes, one of 3/4 fails** — a competence signal about that axis, not about the rule.
  Missing the IDOR points at the persona's §1 authorization-depth duty; missing the
  swallow points at §2's "no unhandled promise rejections".
- **5 fails** — findings cite files that are not there. Worth reading the actual paths
  before concluding anything: a single miswritten path is noise, a set of confident
  findings about a nonexistent `src/auth.js` is a hallucination pattern.
- **1 fails alone** — a filing/location problem, not a judgement problem. The review may be
  perfect and still invisible to `check_commit_gate.py`.

## Runs / Threshold
`runs=5`, pass threshold **4/5**.

This case has a wider variance profile than the shape cases: criteria 1, 2, and 6 are
near-deterministic, but 3 and 4 depend on the model actually reading five small source
files carefully. That is deliberate — the fixture is small enough (under 150 source lines
total) that a competent review finds both defects reliably, so a 2/5 here is a real signal
rather than fixture difficulty. If it fails, read *which* criterion failed before touching
anything: 2 failing while 3 and 4 pass is a `code-review-and-quality` regression, 3 or 4
failing is `agents/luna.md`, and 1 failing is the report template's location rule.

## Future (not implemented)
- **Whether the verdict was reasoned or guessed.** Criteria 2–4 together prove the report
  is *consistent* — blocking findings present, `Request Changes` written — but nothing
  binds the verdict to the findings causally. A Luna who writes `Request Changes` on every
  review would score 5/5 here forever. Closing it needs the mirror case: a genuinely clean
  fixture where the correct verdict is `Approve` and a `Request Changes` fails. That case
  is worth authoring next; the two only mean something as a pair.
- **The `RESOLVED` escape hatch.** The rule permits `Approve` when every Critical and
  Important finding carries an explicit `RESOLVED` marker naming the fix and the evidence.
  This fixture has no prior round, so no finding can legitimately be `RESOLVED`, and the
  grader does not model the marker at all. A re-review case with a real prior round would
  test whether Luna honours "naming the fix and the evidence" instead of stamping
  `RESOLVED` to unblock.
- **Remediation fidelity.** The skill's rule — verify a fix against the *rule* the finding
  protects, not the finding's literal text — is a second-round behavior and needs a fixture
  where the builder closed the IDOR finding with a fix that satisfies its wording while
  violating its rule (e.g. reading the tenant from a header instead of the body).
- **Severity calibration.** The grader accepts `Critical` **or** `Important` for both
  defects. Whether the IDOR is correctly rated `Critical` rather than `Important` is a
  judgement the grader deliberately does not make — the arithmetic rule treats both
  identically, so grading the distinction would test taste, not the contract. An LLM-judge
  could assess it; none is implemented anywhere in this suite.
- **Whether Luna ran the code.** She could have proved the IDOR in thirty seconds with the
  same `curl` this case's Purpose section shows. The report template's
  `**Runtime evidence:**` line would carry it. Nothing here requires or rewards it, because
  the finding is correct either way and demanding the probe would grade thoroughness rather
  than the verdict rule.
