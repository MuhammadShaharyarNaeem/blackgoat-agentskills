---
name: pipeline-tools
description: "Deterministic coverage-gate CLI for the PDD pipelines. Provides check_coverage.py, which verifies every Must-Have FR/NFR in requirements.md is covered by plan.md tasks (plan mode) or by passing tests in test-report.md (test mode). Squad-internal: executed by the Orchestrator at the bgpdd pipeline coverage gates, not delegated to agents."
---

# pipeline-tools

A pure-stdlib Python 3 CLI (`scripts/check_coverage.py`) that makes the requirement-coverage gates in `bgpdd-plan`, `bgpdd-lite`, `bgpdd-build`, and `bgpdd-shipping` machine-checkable instead of a manual read. The Orchestrator runs it directly via a shell action — it is never delegated to an agent.

## Invocation

```bash
python check_coverage.py --requirements <path> --plan <path>          # plan mode
python check_coverage.py --requirements <path> --test-report <path>   # test mode
python check_coverage.py --self-test                                  # runs the bundled unittest suite
```

Exactly one of `--plan` / `--test-report` must be given — both or neither is a usage error (exit 2).

## JSON output shape

The tool always prints exactly one JSON object to stdout (diagnostics go to stderr):

```json
{
  "mode": "plan",
  "requirements_file": "<path as given>",
  "target_file": "<path as given>",
  "must_have": ["FR-1", "FR-2", "NFR-1"],
  "should_have": ["FR-3", "NFR-2"],
  "covered": ["FR-1", "NFR-1", "FR-3"],
  "uncovered": ["FR-2"],
  "uncovered_should": ["NFR-2"],
  "warnings": ["Task 5 has no 'Requirements covered:' field"],
  "result": "FAIL",
  "error": null
}
```

- `uncovered` is the **sole gating array** — Must-Have gaps only. `uncovered_should` is informational and never affects exit code.
- On error: `"result": "ERROR"`, `"error"` holds the message, other arrays hold whatever was parsed before the failure.
- ID arrays are naturally sorted (`FR-2` before `FR-10`).

## Exit codes

- **0** — every Must-Have `FR`/`NFR` is covered (warnings don't affect this).
- **1** — `uncovered` lists at least one Must-Have gap.
- **2** — usage error, a missing/unreadable file, or a structural contract failure (no Must-Have requirements found, no task blocks found in the plan).

## Parsing rules (condensed)

**requirements.md**: MoSCoW section headings (`## / ### / ####` + `Must|Should|Could|Won't Have`, trailing text tolerated) open a tier that closes at the next heading of the same-or-higher level. Within a Must/Should/Could tier, any `**FR-n**` bold ID registers at that tier. `**NFR-n**` IDs are found anywhere in the document via `- **NFR-n** (Must|Should|Could ...)`; an NFR ID with no parseable tier tag defaults to **Must** (fail-safe) and emits a warning. Won't-Have IDs are excluded from all sets unless the same ID also appears in a real tier, in which case the first non-Won't tier wins (with a warning). Duplicate IDs across tiers: first occurrence wins (with a warning). Zero Must-Have IDs found across FRs and NFRs combined → exit 2 ("an empty gate must never silently pass").

**plan.md** (plan mode): task blocks split on `## Task [N]:` (brackets optional). Zero task blocks → exit 2. Within each block, the first `**Requirements covered:**` line's `FR-n`/`NFR-n` tokens are unioned into `covered`. "None"/"N/A" is a legitimate empty value (no warning); a field missing entirely from a task warns by task number; an ID cited in the plan but not defined in requirements warns ("unknown requirement ID ... cited in plan") without failing the gate.

**test-report.md** (test mode): line-based across the whole file — the `#Task [N]:` headers are for humans only. A line is "status-bearing" if it has both an ID token and a status token (`PASS`/`PASSED`/`✅` vs `FAIL`/`FAILED`/`❌`, word-boundary matched; a line with both counts as FAIL). **Latest mention wins** — the last status-bearing line for an ID in file order determines its status. IDs whose only mentions lack a status token get one warning each and are not counted as covered. A missing/unreadable report file → exit 2. A report with zero status-bearing mentions is **not** a structural error — every Must-Have goes to `uncovered` and the gate exits 1 (a report that proves nothing is a coverage failure, not a tool failure).

Quinn's Coverage Ledger format (see `agents/quinn.md` §6) is what the test-report parser expects: within each `#Task [N]:` block, one line per exercised ID —

```
- FR-3: PASS — {test name / evidence}
- NFR-1: FAIL — {failing assertion}
```

Only `PASS`/`FAIL` as the status word, latest mention wins, so a retest appends a fresh line rather than editing history.

## Fixtures & self-test

`fixtures/happy/`, `fixtures/uncovered/`, and `fixtures/malformed/` each hold a `requirements.md` (+ `plan.md` and/or `test-report.md`) exercising the pass, gap, and structural-failure paths respectively. Run the bundled suite either directly or through the CLI:

```bash
python scripts/test_check_coverage.py
python scripts/check_coverage.py --self-test
```

## Single contract authority

The four pipeline coverage gates — `bgpdd-plan` Phase 3.5, `bgpdd-lite` Phase 2.5, `bgpdd-build` Phase 5 Step 2, and `bgpdd-shipping` Step 3.5 — reference this file as the single source of truth for the CLI's contract (invocation, JSON shape, exit codes, parsing rules). They do not restate the parsing rules inline; update them here only.
