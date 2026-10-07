# check_attack_matrix.py — reference

Depth for `check_attack_matrix.py`. The contract of record is the script's own `--help` (`python scripts/tool_registry.py show check_attack_matrix`); this page holds only the reasoning behind it.

## Why two modes, and why they are not one

`bgpdd-secure` reads the attack matrix twice, at two moments with different truths on disk. At Phase 1 the table has been authored and nothing has been probed, so every Verdict cell is legitimately blank; at Phase 3 Cipher's report exists and a blank Verdict is an unprobed row. A single mode would have to pick one of those as the error, and whichever it picked would be wrong half the time.

So `--lint-only` gates **shape** — every row complete, the tier token bare, the environment preamble present — and verdict-dependent rules deliberately never fire there. Results mode gates **execution**, and adds the rules that only make sense once a verdict exists.

## Why the report cross-reference exists

A matrix can be internally consistent and still describe work nobody did: every row filled in, every Verdict `PASS`, and no corresponding check line anywhere in the security report. The matrix is authored by the same agent that authors the report, so the two agreeing with each other proves only that one author was consistent.

`--report` turns the pairing into a checkable one. The three rules it adds each close a specific way the two documents drifted apart in practice:

- a matrix row with no check line in the report is a row that was planned and never executed, however its Verdict cell reads;
- a `not agent-testable` row whose **report** check line was nonetheless closed `PASS` is the more interesting case, and the rule is deliberately independent of the matrix's own Verdict cell — an agent that could not test a row does not get to record a pass for it in either document;
- an access-control row that declared a two-account precondition must show two distinct identities in its evidence, because the whole class is about one identity reaching another's data, and a single-identity probe cannot observe it.

## Why a qualifying finding has its own rule code

`--require-priority` scans the report's Findings for one at or above the floor `bgpdd-secure` Phase 0 chose. When one is found the lane routes to its remediation phase as a **confirmed vulnerability**, never as a defect loop against the matrix. That routing difference is why the finding carries a rule code of its own instead of reusing another failure's: a reader who sees this code is being told the matrix was fine and the product was not.

The flag requires `--report`, since there is nothing to scan without one — a floor applied to no findings list would report a clean pass over a scan that never happened.

## Why the target-host check exists (H1)

`bgpdd-secure` is "staging or local only — never production", and until this rule the gate checked only that the preamble's `Authorization:` and `Scope exclusions:` labels existed — a matrix whose base URL was the production API linted clean. Convention #9: the restraint bites exactly when the Orchestrator wants to start probing, so it is now a host check, in **both** modes (a matrix edited between Phase 1 and Phase 3 is caught at Phase 3).

- **What counts as a target.** The host of every `scheme://host` URL outside a fence, and each bare `host[:port]` on a `Base URL(s):` line. Lines under `Forbidden host(s):`, `Scope exclusion(s):`, `Staging host(s):` and `Reference(s):` — and their indented continuation lines — are skipped: they name hosts the lane must NOT probe, or patterns, or citations. Over-collection is deliberate: a stray production URL in prose fails closed, and the fix is to move it under one of those labels or into a fence, never to declare it.
- **What is allowed.** `localhost`, `127.0.0.1`, `[::1]`, `*.localhost`, `*.test` (the reserved names), or an fnmatch match for a pattern on the matrix's own **`Staging hosts:`** line — the one new declaration field, labelled like `Authorization:`. Declaring a host there is the Orchestrator writing down Phase 0 step 2's user confirmation that it is non-production; the gate cannot verify that confirmation, only that it was written down and that everything probed falls inside it.
- **Why too-broad patterns fail.** A pattern with a wildcard in either of its last two labels (`*`, `*.com`, `*.example.*`) is `staging-pattern-too-broad` and allows nothing — a declaration that matches the internet would turn the check back into the self-asserted string it replaced.
- Fixtures: `fixtures/attack-matrix-local-hosts/` (local + declared staging, forbidden/excluded production hosts skipped — exit 0) and `fixtures/attack-matrix-production-host/` (a production base URL with a `*.com` declaration — exit 1, both codes). The self-test lints both.

## Scope limits

- The gate reads the **table**. Whether a cited capture is honest — that it recorded the probe it claims, out of process, against a running surface — stays `check_runtime_evidence.py`'s and `check_agent_report.py`'s job; this gate checks that a `PASS` row's cited path resolves on disk.
- Preconditions are checked for **presence**, not for adequacy. A row that names two accounts it never used passes this rule and fails the report cross-reference instead.
- The tier token is checked as a bare token only; this gate has no opinion about which tier a category belongs in. That judgement lives in the secure lane's own methodology.
