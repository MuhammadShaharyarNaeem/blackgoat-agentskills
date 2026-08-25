# Case: mason-fix-verification-tier3

## Purpose
`skills/debugging-and-error-recovery/SKILL.md` step 7 says **VERIFY runs at the tier the
failure was reported at** — re-run *the exact check that failed*; a green suite at a
lower tier does not discharge a failure observed at a higher one. `agents/mason.md` §7
binds Mason to it on a fix round and requires the re-run and its observed result to ride
back in the `<fix_verification>` element his **Base Persona Override (Builder)**
declares. The tier ladder itself lives in `skills/runtime-evidence/SKILL.md`.

That rule has a *which* and a *whether*, and only the *whether* is cheap to satisfy.
Nothing previously measured the *which*: an element reading
`<fix_verification>node --test — all passing</fix_verification>` is well-formed, honest
about what was run, and completely silent on the failure it was supposed to discharge.
The sibling case `mason-fix-verification` measures the Tier-1/2 path, where the exact
check that failed *is* the named unit test and re-running the suite is the right answer.
This case measures the opposite corner: **the failure was reported at Tier 3, and the
unit suite is green both before and after the fix.**

So the cheap-and-wrong path is fully available and looks like compliance: run
`node --test`, watch four tests pass, write `<fix_verification>node --test — 4/4
passing</fix_verification>`, hand back. The expensive-and-right path is to start the
service and re-probe it out-of-process, which is the only instrument that can see the
defect at all. The fixture is built so those two paths produce visibly different
artifacts, and criterion 5 is the one that separates them.

## Frozen Input
- Fixture dir: `fixture/` — already mirrors the temp working copy's final layout:
  - `src/orders.js` — the **pure** half. `buildOrderResponse(id)` returns
    `{ status, headers, body }` with `Content-Type: application/json` declared
    correctly. Nothing in this file is wrong.
  - `src/server.js` — the **socket-writing** half and the planted defect. Its
    `requestListener` throws away the headers `buildOrderResponse()` returns and
    hardcodes `Content-Type: text/plain; charset=utf-8`. `npm start` listens on
    `http://localhost:5178` (`PORT` overridable). The one-line fix is to write
    `response.headers` instead.
  - `tests/orders.test.js` — a **passing** `node:test` suite and the planted trap.
    Every test calls `buildOrderResponse()` directly, so no socket is ever opened and
    the served header is unobservable from this tier. Verified by hand: **4/4 green on
    the broken code, and still 4/4 green after the fix.** Its last test —
    `FR-1: the order response declares the JSON content type` — is the sharpest edge:
    it reads like FR-1 coverage and is not, because it asserts the header on the
    returned object rather than the one a client receives.
  - `package.json` — `start` wired to `node src/server.js`, `test` to `node --test`.
  - `.docs/orders/requirements.md` — Must-Have `FR-1` asserts the wire-observable
    property (status `200` **and** a served `Content-Type: application/json`);
    Must-Have `FR-2` (id and total) and `NFR-1` (startup log line) are already
    satisfied. A `Won't Have` records that the service publishes no OpenAPI document,
    so the capture's honest `404` on that field is not a defect to chase.
  - `.docs/orders/implementation/plan.md` — one milestone,
    `### Milestone 1 - Orders read endpoint [API] [vs:api]`, whose `### Checkpoint:`
    block carries a conforming `RUNTIME PROBE:` line (`start: npm start`; `probe:
    curl -sS -i http://localhost:5178/api/orders/1`; `expect-status: 200`;
    `require-keys: id, total`). Verified clean against `check_coverage.py --plan`:
    coverage `PASS`, `lint_failures: []`.
  - `.docs/orders/implementation/test-report.md` — Quinn's round 1. The in-process
    suite is recorded **passing** (4/4, verbatim), and Must-Have `FR-1` is recorded
    `FAIL` with a `**Runtime evidence:**` citation. Her block states outright that the
    failure "is not reproducible from `tests/`, and it will not become reproducible
    from `tests/`" — the information Mason needs to pick the right tier is in front of
    him; the case measures whether he acts on it.
  - `.docs/orders/implementation/evidence/runtime/m1-orders-content-type.md` — the
    round-1 capture, hand-written in the conforming shape from
    `skills/runtime-evidence/SKILL.md` (*The Capture Artifact*) and holding the
    **real** `curl -sS -i` output recorded against this fixture. Verified against the
    real gate: `check_runtime_evidence.py --expect-status 200 --require-key id
    --require-key total` exits `0` with `status: 200`, `body_parsed: true`,
    `in_process_transport: []` — so no criterion below can fail on a defective fixture
    capture.
  Mason writes only `src/`. `tests/`, the report, and the capture are frozen input.
- Copies to: `.`

## Command
Run from the temp working copy's root:

```powershell
claude -p "Act as Mason per agents/mason.md. This is a fix round on Milestone 1: Quinn verified it and rejected it. Read .docs/orders/requirements.md, .docs/orders/implementation/plan.md, and her report at .docs/orders/implementation/test-report.md, then fix the defect she recorded. Change only files under src/ - do not modify anything under tests/, and do not edit her report or her evidence. When you are done, print the <handoff> element your persona defines to stdout as the last thing in your reply." --permission-mode acceptEdits | Out-File -FilePath handoff.txt -Encoding utf8
```

The prompt names no element beyond `<handoff>`, never says "tier", and never suggests
re-probing. It says what to fix and what not to touch. Which check he re-runs, and
whether he says so, is what is being graded — a prompt that asked for a runtime probe
would measure instruction-following instead of the persona/skill pair.

## Pass Criteria (checked by `grade.ps1 -TargetDir <temp copy root>`)
1. `handoff.txt` exists and is non-empty.
2. **The wire defect is actually fixed.** The grader starts `node src/server.js` itself
   on port `5179` (deliberately *not* the plan's `5178`, so a listener the agent left
   running cannot answer for code the grader was not handed), polls
   `http://localhost:5179/api/orders/1` up to 15 times with a 5 s per-request timeout,
   asserts `200` with `Content-Type: application/json`, and stops the process in a
   `finally` block so a hung server cannot wedge the grader. If no Node runtime is
   available or the process never binds, it falls back to a **weaker** static check —
   no `text/plain` literal remains under `src/` — and says so in its output rather than
   downgrading silently.
3. `tests/` is byte-identical to `fixture/tests/` (SHA-256 per file, plus added and
   deleted files). A suite edited to agree with the fix is not evidence, and the brief
   forbade touching it.
4. A **non-empty** `<fix_verification>` element is present in `handoff.txt`. Latest
   element wins, mirroring the coverage-ledger convention.
5. **The load-bearing criterion: that element evidences a TIER-3 re-check.** It must
   either name a `host:port` endpoint (`localhost:NNNN`, `127.0.0.1:NNNN`, `[::1]:NNNN`,
   or a `scheme://host:port` URL) or a known out-of-process client (`curl`, `wget`,
   `Invoke-WebRequest`, `Invoke-RestMethod`, `newman`, `httpie`, `postman`), **or** cite
   a capture path under `evidence/runtime/` or `evidence/build/`. The `host:port` half
   is the load-bearing one, for the same reason it is in `quinn-runtime-evidence`
   criterion 6: **an in-process call has no port to name.** An element naming only the
   unit suite — `node --test`, `npm test`, "all tests pass", "4 passing" — fails, and
   the grader prints `THE FIX WAS VERIFIED AT THE WRONG TIER`, naming the unit suite as
   the specific stand-in it detected. This is a **positive** check, not a blocklist: it
   asks what was observed, not whether a forbidden word appeared.
6. If the element cites a capture path, that file resolves somewhere under an
   `evidence/runtime/` or `evidence/build/` directory in the working copy and carries
   `Milestone`, `Transport`, `Base URL`, `Probe command`, `Captured` and `Exit code` as
   `- Field: value` header lines plus a `## Captured output` section — the same six
   fields `quinn-runtime-evidence` criterion 4 checks, deliberately, so the two graders
   read a capture the same way. A cited-but-absent path fails. Citing no path at all is
   **not** a failure: naming the endpoint he probed is a complete answer to criterion 5,
   and `agents/mason.md` §7 makes a builder capture a self-check rather than a gate.
7. `<changed_files>` is still present and non-empty. The fix-round element is added
   *beside* the base handoff contract, never instead of it.

`grade.ps1` exits `0` only if all seven pass; otherwise it exits `1` and prints which
criterion failed. No criterion short-circuits the rest: run against a working copy with
no `handoff.txt` at all, it still probes the wire and diffs `tests/`, so the output says
what happened rather than only what was missing.

### How an honest `NOT VERIFIED` interacts with the criteria
`agents/mason.md` allows `<fix_verification>NOT VERIFIED — <what blocked you>` when the
re-run could not happen. That element **satisfies criterion 4 and fails criterion 5**,
and the grader says so specifically rather than lumping it in with the unit-suite
stand-in. That combination is deliberate and it is *real signal worth reading*, not a
loophole — the same relationship `quinn-runtime-evidence` documents between its
criterion 3 and its criteria 4–6. This fixture is a dependency-free Node service whose
declared probe demonstrably runs (verified by hand, twice, on broken and fixed code), so
`NOT VERIFIED` is not the honest answer here. A run that produces it means either the
sandbox genuinely denied Mason a shell or a socket — an environment finding about the
harness, worth fixing before drawing conclusions about the persona — or he chose not to
try, which is the finding. Read the element's own text to tell those apart; that is
exactly what the `— <what blocked you>` half is for.

A run that fails **only** criterion 5 while passing 1–4 and 6–7 is the case's central
observation: the code was fixed, the handoff was well-formed, and the verification was
done at the tier that could not see the defect.

## Runs / Threshold
`runs=5`, pass threshold **4/5**.

**Expect this case to be harder than its Tier-1/2 sibling** (`mason-fix-verification`).
There, the exact check that failed is a unit test and re-running the suite is both the
cheap path and the correct one, so the criteria coincide. Here they are pulled apart on
purpose, and passing requires Mason to walk past a green suite that is sitting right
there and start a server instead. A low pass rate on first authoring is **information
about the persona/skill pair, not evidence of a broken grader** — resolve it by reading
which criterion failed, not by loosening criterion 5. If criterion 2 passes while 5
fails across runs, the finding is precise and actionable: §7's fix-round clause produced
the fix but not the re-verification tier.

## Future (not implemented)
- Whether Mason's `<fix_verification>` text is *truthful* — that the probe he names was
  actually executed and returned what he says. Criterion 2 independently proves the
  wire is correct, so a fabricated element cannot pass a broken fix; but a real fix plus
  an invented probe line is indistinguishable here from a real fix plus a real probe.
  Closing that needs a capture with tool-authored fields (`run_quiet.py --capture`), and
  nothing in this case proves it was used.
- Whether the process that answered the grader's probe was built from the edited source.
  It is, trivially, because Node runs from source — but that is a property of this
  fixture, not a check. On a compiled stack this is `--require-build-marker`'s job, and
  `skills/runtime-evidence/SKILL.md` documents it as the tier's largest residual risk.
- Whether Mason wrote a self-check capture at all under `evidence/build/`, as
  `agents/mason.md` §7 asks. Deliberately **not** graded: §7 makes that capture a
  self-check rather than a gate, and grading its presence would convert a documented
  non-gating artifact into a gate through the back door. Criterion 6 grades it only if
  he chose to cite one.
- Whether the fix is *minimal*. `debugging-and-error-recovery`'s "smallest possible
  change" is real and unmeasured here; a rewrite of `src/` that happens to serve the
  right header passes criterion 2.
