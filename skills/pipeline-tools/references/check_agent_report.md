# check_agent_report.py — reference

Depth for the `check_agent_report.py` section of `../SKILL.md`: the parsing rules, the producer-side grammar pointers, and the fixture inventory.

### Parsing rules (condensed)

- **Gated section**: the report splits on level-2 (`## `) headings; the **LAST** section containing a `**Verdict:**` line is gated — each audit/verification round appends a fresh section, so the last one is the current round (the same last-matching-section rule `check_commit_gate.py` uses). Text before the first `## ` heading is preamble and never gated. Within the section, the **LAST** `**Verdict:**` line wins and must be the exact token `Pass` or `Fail`; an unparseable latest line fail-safes to no-verdict rather than falling back to an earlier line.
- **Check lines**: a list item of the form `- <name>: <STATUS> <rest>` where `<name>` contains no colon and `<STATUS>` — exactly `PASS`, `FAIL`, `BLOCKED`, or `NOT RUN`, uppercase — immediately follows the first colon. Anything else is prose and ignored. Duplicate names within the section deduplicate with **latest mention wins**, mirroring the coverage-ledger convention.
- **Evidence**: a `PASS` or `FAIL` line must cite its exit code (`exit <N>`, case-insensitive, `exit code <N>` tolerated) — the terse proof an execution happened; a `NOT RUN` or `BLOCKED` line must carry a non-empty reason. A line missing either lands in `unevidenced` and fails the gate.
- **The capture citation**: a `PASS` or `FAIL` line must ALSO carry `capture: <path>` (backticks tolerated) naming a `run_quiet.py --capture` artifact under an `evidence/` segment, with no `..`, resolved against the report's directory, then `--repo`, then the cwd. `NOT RUN` / `BLOCKED` lines are exempt. See *Why the capture citation exists* below.
- **Findings**: a list item starting `- **Critical**` in the gated section counts as a standing Critical finding; any count above zero fails the gate regardless of the verdict token. Lower severities (Important, Suggestion, Nit, FYI) are the report author's routing signal, not this gate's.
- **Zero check lines** is a gate failure (exit 1), not a structural error — a report that proves nothing is an evidence failure, not a tool failure (the same rule as test mode's zero status-bearing mentions).

The producer-side grammar lives in `agents/cipher.md` §4, `agents/vera.md` (Verification Report) and `shipping-and-launch/SKILL.md` (post-deploy report); `bgpdd-shipping` Step 3 references this section as the single contract authority.

## Why the capture citation exists

**Until it did, this gate read nothing unforgeable.** Every other term is text the reporting agent types: the status token, the command in backticks, the exit code, the counts, the verdict. A wholly invented report passed — and `- Secrets scan: PASS — `git grep -n secret` — exit 1 — 0 matches` costs exactly as little to write as to run. The gate's own docstring called the exit code "the terse proof an execution happened", which it never was; it was a claim *about* an execution.

So an executed line must cite the artifact that recorded the run, and the citation is checked all the way down: the capture exists, carries its `<capture>.meta.json` sidecar, still hashes to that sidecar's `capture_sha256`, satisfies the body/sidecar agreement contract (`../SKILL.md`), and records an `exit_code` **equal to the exit code the line claims**. That last term is what binds the capture to *this* line — without it, one green capture cited on every line would back the whole report.

**`--allow-uncaptured` waives the citation and nothing else.** A cited capture that disagrees is never waived — the same split `check_runtime_evidence.py --allow-missing-sidecar` draws between an absent sidecar (a legacy artifact) and a present one that contradicts itself (a forgery). The one named reason for the flag is grading a report authored before this contract; it prints a loud stderr warning and lands `allow_uncaptured: true` in the JSON, so a waived run is visibly waived in the ledger record.

**Migration.** Reports authored under 2.3.0 or earlier fail with `check_uncaptured` on every executed line. The fix is not to edit the report: re-run each check through `python scripts/run_quiet.py --capture .docs/{project-name}/implementation/evidence/<security|verify>/<check>.md -- <the command>` and cite each artifact on its line. **The shipped `fixtures/agent-report-happy/` reports predate this contract and now fail** — they need a capture (and sidecar) per line, the same way `fixtures/runtime-evidence-*/` carry theirs.

### Fixtures & self-test

- `fixtures/agent-report-happy/` — a `security-report.md` and a `verification-report.md`, all lines evidenced and `PASS`, verdict `Pass`; both exit **0** *once each line cites a capture* (see Migration above).
- `fixtures/agent-report-sad/` — a `security-report.md` whose `Pass` verdict stands over a failing scanner, an unevidenced `PASS`, a `NOT RUN` item, and a Critical finding (exit **1**); a `verification-report.md` with an honest `Fail` verdict over FAIL/BLOCKED items (still exit **1** — the gate is green-or-blocked, honesty routes, it does not pass); and `no-verdict.md`, a report with no verdict-bearing section (exit **2**).

`python scripts/check_agent_report.py --self-test` runs a bundled in-process `unittest` suite (temp files, real captures + sidecars) covering the happy path, each failure cause, last-section and last-verdict-line precedence, duplicate-name latest-wins, lowercase-status-is-prose, the three structural errors, and the citation set: a wholly typed 2.3.0-shaped report, `--allow-uncaptured`'s waiver and its limit, an exempt `NOT RUN`/`BLOCKED` pair, a missing file, a citation outside `evidence/`, a `..` path, a sidecar-less capture, an edited capture, a flipped sidecar, a headerless capture, a capture of a *different* run (exit code mismatch), and a backticked citation.

## Why `--milestone` and `--ledger` exist here (P2b)

Neither flag changes this gate's own verdict, but `--ledger`'s `inputs` now carry the report **plus every cited capture and its sidecar**, so a later `--require-ledger-gates check_agent_report.py` re-hashes them and catches an artifact edited after this gate passed. `--milestone` scopes the run's ledger record so a later `check_commit_gate.py --require-ledger-gates check_agent_report.py` can find it: an unscoped record answers for every milestone, which is exactly the over-broad approval `ambiguous_review_section` refuses on the review side. A gate whose result cannot be attributed to a milestone cannot be depended on by the gate that owns the commit.
