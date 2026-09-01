---
name: pipeline-tools
description: "Deterministic stdlib-Python CLI family for the PDD pipeline gates. check_coverage.py gates Must-Have FR/NFR coverage in plan, test and design modes; check_commit_gate.py runs the bgpdd-build milestone commit gate and can commit; check_agent_report.py gates Cipher and Vera durable reports; check_runtime_evidence.py gates observed-runtime captures (transport, provenance sidecar, client allowlist, freshness, keys); check_acceptance_suite.py gates the acceptance matrix and its results; check_ship_decision.py gates Dep GO/NO-GO; check_blockers.py gates an empty blockers array; next_milestone.py derives the next pending milestone; mark_milestone.py writes the completion marker; update_state.py is the sanctioned writer for orchestrator-state.json; run_quiet.py runs builds and tests and writes capture artifacts; check_dependency_tables.py and check_frontmatter.py lint agent dependency tables and frontmatter. Squad-internal: run by the Orchestrator at the bgpdd gates, never delegated."
---

# pipeline-tools

A family of pure-stdlib Python 3 CLIs under `scripts/` that convert the bgpdd pipelines' prose gates into commands with exit codes. The Orchestrator runs them directly via a shell action — they are never delegated to an agent, and there is no manual open-and-read substitute for any of them.

This file is the **lean contract spine**: per script, what it is for, how it is invoked, its flags, its JSON keys, its exit codes, and its problem codes. Rationale, observed-failure narratives, parsing grammars, fixture inventories, scope-limit essays and self-test case lists live in `references/<script-name>.md` and are loaded on demand.

## Single contract authority

The pipeline gates — `bgpdd-plan` Phase 3.5, `bgpdd-lite` Phase 2.5, `bgpdd-build` Phase 2 and Phase 5, `bgpdd-verify` Phase 3, `bgpdd-shipping` Steps 0.3–3.5, and `bgpdd-bugfix` — reference this file as the single source of truth for every CLI's contract (invocation, flags, JSON shape, exit codes, parsing rules). They do not restate the rules inline; update them here only. The file therefore stays at this path: fourteen files across the pipelines, the personas and the sibling skills cite it by name.

## Gate ledger

Every gate in this family accepts `--ledger <path>` and appends **exactly one JSON line per run, on every exit path** (creating parent directories):

```json
{"ts": "<ISO-8601 UTC>", "gate": "<script basename>", "argv": ["..."], "milestone": "<--milestone value or null>", "inputs": {"<path as given>": "<sha256 hex or null>"}, "verdict": "PASS|FAIL|ERROR", "exit": 0}
```

`inputs` carries every file path argument the script read. `verdict` maps exit 0/1/2 to PASS/FAIL/ERROR. Writing the ledger is **best-effort**: a ledger that cannot be written never changes the gate's own verdict — it is an audit trail for LATER gates, not a term in this one. `update_state.py --resolve-blocker` additionally records `"action": "resolve-blocker"` and `"evidence": "<text>"`. The CLI still cannot judge whether "trust me" is real evidence; the ledger makes the claim durable and attributable instead of gone the moment the array shrinks.

Carrying `--ledger`: `check_commit_gate.py`, `check_agent_report.py`, `check_acceptance_suite.py`, `check_ship_decision.py`, `check_coverage.py`, `check_blockers.py`, `check_runtime_evidence.py`, `update_state.py`, `mark_milestone.py`. `next_milestone.py` READS the ledger but never writes it. The pipelines pass `--ledger .docs/{project-name}/implementation/gates.jsonl` on every gate invocation (Orchestrator Contract §4).

## Fenced blocks and encoding

Every verdict/status parser blanks fenced regions (three backticks or three tildes) before parsing, preserving line count, and every file read uses `utf-8-sig`. A verdict or status token inside a fence is a TEMPLATE or a captured transcript, never an assertion — and because these parsers resolve latest-mention-wins, a pasted example silently overrode the real verdict. A BOM previously made a valid report exit 2. `check_coverage.py`'s plan and design modes are the labelled exception (convention #8) — see `references/check_coverage.md`.

## check_coverage.py

Verifies every Must-Have FR/NFR in `requirements.md` is covered: by `plan.md` tasks (plan mode), by evidenced passing tests in `test-report.md` (test mode), or by an in-place supersession annotation in `detailed-design.md` (design mode). Plan mode additionally runs five gating lints; design mode runs the supersession/citation lints only.

```bash
python check_coverage.py --requirements <path> --plan <path>          # plan mode
python check_coverage.py --requirements <path> --test-report <path>   # test mode
python check_coverage.py --requirements <path> --design <path>        # design mode
python check_coverage.py ... [--ledger <path>]
python check_coverage.py --self-test
```

- **Flags** — exactly one of `--plan` / `--test-report` / `--design` (more than one or none is exit 2); `--requirements` required in every mode; `--ledger` optional.
- **JSON keys** — `mode`, `requirements_file`, `target_file`, `must_have`, `should_have`, `covered`, `uncovered`, `uncovered_should`, `blocked`, `unevidenced`, `warnings`, `lint_failures`, `result`, `error`. `uncovered` and `lint_failures` are the two gating arrays. `lint_failures` entries are `{check, task, detail}`, where `check` is one of `literal-count`, `consumes-provides`, `path-hygiene`, `runtime-criterion`, `domain-tag` (plan mode) or `supersession-annotation`, `fr-citation` (design mode).
- **Test-mode evidence rule** — a status is read only from a list item (`- FR-3: PASS — …`). A `PASS` whose evidence half cites nothing checkable (an exit code, a `file::test-name`, or a `**Runtime evidence:**` / `evidence/runtime/` citation) is recorded `UNEVIDENCED`: status-bearing, NOT covered, so the Must-Have lands in `uncovered`.
- **Exit codes** — **0** every Must-Have covered and no lint failed; **1** a Must-Have gap or any lint failure; **2** usage error, missing/unreadable file, or a structural contract failure (no Must-Have requirements, no task blocks).
- **Self-test** — `--self-test` runs **126** cases; `python scripts/test_check_coverage.py` runs the same suite directly. Depth (parsing grammars, the five lints, fixtures, the authoring smoke test): `references/check_coverage.md`.

## check_commit_gate.py

Makes the `bgpdd-build` milestone commit gate machine-run instead of a manual two-file read: it checks the milestone's latest review verdict, whether that review postdates the diff, and whether the blockers ledger is clean, then — on a pass — performs the commit itself, so a skipped gate is loud (no commit exists) rather than silent.

```bash
python check_commit_gate.py --review-report <path> --state <path> \
    --milestone "<title>" --changed-files <p1> [<p2> ...] \
    [--commit --message "<msg>"] [--repo <dir>] [--ignore-unscoped] \
    [--require-rendered-evidence] [--verify-tree] \
    [--ledger <path>] [--require-ledger-gates <name>[,<name>...]] \
    [--require-runtime-evidence --runtime-report <path> \
     [--surface <key>] [--require-key <name>]... [--expect-status <N>] \
     [--forbid-host <pattern>]... [--require-build-marker <value>] \
     [--require-openapi-reachable] [--allow-missing-sidecar] \
     [--openapi-doc <path> --openapi-route <path> [--openapi-method <verb>]]]
python check_commit_gate.py --self-test
```

- **Flags** — `--repo` defaults to `.`. Every runtime-evidence assertion flag forwards to `check_runtime_evidence.py`; any of them passed *without* `--require-runtime-evidence` is exit 2, never a silent no-op. `--ledger` and `--allow-missing-sidecar` forward when the child script declares them. `--require-ledger-gates` requires `--ledger` (else exit 2) and demands that each named gate's latest ledger entry for this milestone record `PASS` **and** still hash the same inputs.
- **Section boundaries** — ANY heading of level 2–6 closes a `## Review:` section. **Migration**: a `**Verdict:**` line must appear BEFORE any subheading inside its review section, or the section reads as no-verdict and fails closed.
- **JSON keys** — `milestone`, `review_report`, `state_file`, `review_found`, `verdict`, `ambiguous_review_section`, `stale`, `blocking`, `unscoped_blockers`, `rendered_evidence`, `rendered_evidence_ok`, `undeclared_changes`, `tree_verified`, `runtime_evidence`, `runtime_evidence_ok`, `ledger`, `require_ledger_gates`, `ledger_gate_problems`, `ledger_gates_ok`, `warnings`, `committed`, `result`, `error`. **Problem codes**: `ledger_gate_problems` entries carry `ledger_missing`, `ledger_failed` or `ledger_stale`.
- **Exit codes** — **0** gate passed (and committed, with `--commit`); **1** gate failed (`verdict` not `Approve`, `ambiguous_review_section`, `stale`, non-empty `blocking`, unignored `unscoped_blockers`, `rendered_evidence_ok: false`, `runtime_evidence_ok: false`, `ledger_gates_ok: false`, or `tree_verified: false`); **2** usage error, a `--changed-files` path that does not exist (`changed_file_missing`), unreadable artifact, invalid state JSON, git failure, or a structural failure from the delegated runtime gate.
- **Self-test** — **57** cases. Depth (delegation rationale, parsing rules, the ledger-gate essay): `references/check_commit_gate.md`.

## check_agent_report.py

Verifies a durable agent report (Cipher's `security-report.md`, Vera's `verification-report.md`) backs its `Pass` verdict with evidenced check lines and zero Critical findings. Deliberately terse: the evidence contract is command + exit code + counts per line — the gate never requires (and the report must never contain) full scanner output or log dumps.

```bash
python check_agent_report.py --report <path> [--milestone "<title>"] [--ledger <path>]
python check_agent_report.py --self-test
```

- **Flags** — `--milestone` scopes this run's ledger record so a later `check_commit_gate.py --require-ledger-gates check_agent_report.py` can find it. Neither optional flag changes the gate's own verdict.
- **JSON keys** — `report`, `section`, `verdict`, `checks`, `passed`, `failed`, `blocked`, `not_run`, `unevidenced`, `critical_findings`, `warnings`, `result`, `error`.
- **Exit codes** — **0** verdict exactly `Pass`, at least one check line, every line `PASS` and evidenced, zero Critical findings; **1** any other verdict (an unparseable latest verdict fail-safes to no-verdict), a non-empty `failed`/`blocked`/`not_run`/`unevidenced`, a standing Critical, or zero check lines; **2** usage error, missing/empty/unreadable report, or no `## ` section carrying a `**Verdict:**` line.
- **Self-test** — **24** cases. Depth (check-line grammar, producer-side pointers, fixtures): `references/check_agent_report.md`.

## check_runtime_evidence.py

Converts `runtime-evidence`'s prose rule — *an in-process observation can fail a wire claim but never pass one* — into an artifact that has to exist on disk. It reads a durable report (`test-report.md` in build, `verification-report.md` in shipping), collects its `**Runtime evidence:**` citations, and verifies each cited capture: provenance sidecar, out-of-process transport, allowlisted client, freshness, and required response keys. `runtime-evidence/SKILL.md` owns the capture artifact and citation grammar; this section owns only the CLI contract.

```bash
python check_runtime_evidence.py --report <path> --milestone "<title>" \
    --changed-files <p1> [<p2> ...] [--repo <dir>] \
    [--surface <key>] [--require-key <name>]... [--expect-status <N>] \
    [--forbid-host <pattern>]... [--require-build-marker <value>] \
    [--min-captures <N>] [--require-openapi-reachable] \
    [--allow-missing-sidecar] [--ledger <path>] \
    [--openapi-doc <path> --openapi-route <path> [--openapi-method <verb>]]
python check_runtime_evidence.py --self-test
```

- **Flags** — `--report` and `--milestone` required; `--repo` defaults to `.`; `--min-captures` defaults to `1` and **must be >= 1** (`0` is an argparse error, exit 2 — a gate that passes with zero accepted captures once reported `PASS` while its own JSON named an in-process transport); `--require-key` and `--forbid-host` are repeatable and are supplied by the **caller**, never declared by the producer. `--allow-missing-sidecar` waives sidecar **absence** only. There is deliberately **no `--allow-stale` / `--ignore-freshness` override** — a divergence from `check_commit_gate.py`'s `--ignore-unscoped` precedent (convention #8), because freshness is the specific gap the observed failure walked through.
- **JSON keys, top level** — `report`, `milestone`, `citations`, `captures`, `accepted`, `rejected`, `missing_keys`, `stale`, `in_process_transport`, `sidecar_missing`, `sidecar_hash_mismatch`, `probe_failed_exit`, `probe_not_client`, `probe_exempt`, `allow_missing_sidecar`, `min_captures`, `warnings`, `result`, `error`, plus the OpenAPI set `openapi_unreachable`, `require_openapi_reachable`, `openapi_doc`, `openapi_route`, `openapi_method`, `schema_resolved`, `schema_unresolvable_reason`, `declared_properties`, `declared_absent`, `observed_undeclared`. An ERROR payload carries `error_code` alongside `error`.
- **JSON keys, per capture** — `path`, `exists`, `cited_under_evidence_runtime`, `milestone_match`, `fresh`, `surface`, `transport`, `probe_command`, `probe_client`, `probe_exempt_reason`, `sidecar`, `sidecar_present`, `sidecar_exit_code`, `sidecar_capture_sha256_ok`, `sidecar_waived`, `status`, `body_parsed`, `body_keys`, `missing_keys`, `build_marker`, `openapi_url`, `openapi_status`, `openapi_reachable`, `schema_compared`, `schema_skipped_reason`, `observed_scope`, `declared_absent`, `observed_undeclared`, `problems` and `problem_codes` — empty `problems` means accepted.
- **Problem codes** — `sidecar_missing`, `sidecar_hash_mismatch`, `probe_failed_exit`, `probe_not_client`, `in_process_transport`, `stale`, `changed_file_missing`; `problems` entries are formatted `"<code>: <prose>"`.
- **Exit codes** — **0** at least `--min-captures` accepted captures for this milestone and `declared_absent` empty; **1** any evidence failure (no citation, missing file, cited outside `evidence/runtime/`, no capture naming this milestone, stale, in-process transport, build/test-runner/search probe, a non-allowlisted client, a missing/mismatched/non-zero-exit sidecar, forbidden host, missing required key, status or build-marker mismatch, unreachable OpenAPI under its flag, or a declared-but-absent schema property); **2** structural/usage — missing `--report`/`--milestone`, unreadable report, a cited capture with no `## Captured output` section, a `--changed-files` path that does not exist (`changed_file_missing`), `--min-captures 0`, or an incomplete/invalid `--openapi-*` combination.
- **Self-test** — **91** cases. Depth (sidecar and client-allowlist essays, OpenAPI flags, parsing rules, scope limits, fixtures): `references/check_runtime_evidence.md`.

## check_acceptance_suite.py

Gates the **feature-scoped** walkthrough, one scope up from every other gate here: per-milestone evidence proves each brick, nothing else proves the wall stands. Execution mode gates Alex's `acceptance-matrix.md` against Quinn's `acceptance-results.md`; structure mode (`--lint-only`) gates that the matrix is well-formed at plan time, before any code exists. Run at `bgpdd-build` Phase 5 before Dep writes the prep ship-decision, at `bgpdd-verify` Phase 3, and again at `bgpdd-shipping` Stage 1 as regression.

```bash
# Execution mode — gates that the matrix was RUN (build Phase 5, verify Phase 3, shipping Stage 1)
python check_acceptance_suite.py --matrix <path> --results <path> \
    [--repo <dir>] [--require-priority P0[,P1]] [--min-scenarios <N>] \
    [--changed-files <p1> [<p2> ...]] [--ledger <path>]
# Structure mode — gates that the matrix is WELL-FORMED (bgpdd-plan Phase 3.5)
python check_acceptance_suite.py --lint-only --matrix <path> \
    [--requirements <path>] [--min-scenarios <N>] [--ledger <path>]
python check_acceptance_suite.py --self-test
```

- **Flags** — `--repo` defaults to `.`, `--min-scenarios` to `1`. `--require-priority` is **"at or above"** (so `P1` gates {P0, P1}); omitting it gates every scenario. `--results` with `--lint-only`, `--requirements` without `--lint-only`, and `--changed-files` with `--lint-only` are each exit 2, never a silent ignore. `--changed-files` adds freshness: the results file's mtime must be `>=` the newest changed file. **Deliberate divergence (convention #8):** `bgpdd-build` Phase 5 step 2.5b and `bgpdd-verify` Phase 3 do NOT pass `--changed-files` — the results are produced by the Quinn delegation immediately before the gate, so freshness is by construction; `bgpdd-shipping`'s later re-execution is the one call site where staleness is possible, and it passes the flag.
- **Manual evidence must BE a capture** — cited under `evidence/runtime/`, existing, non-empty, and carrying a `## Captured output` section; whether it is honest stays `check_runtime_evidence.py`'s job.
- **JSON keys** — `matrix`, `results`, `requirements`, `lint_only`, `require_priority`, `min_scenarios`, `changed_files`, `stale_results`, `scenarios`, `gated_scenarios`, `steps`, `steps_gated`, `passed`, `failed`, `blocked`, `not_run`, `missing_results`, `unevidenced_manual`, `dangling_inverse`, `undeclared_inverse`, `extra_results`, `warnings`, `result`, `error`, plus the structure-mode set `linted_scenarios`, `exempt_steps`, `invalid_exemption`, `missing_priority`, `missing_step_table`, `missing_columns`, `unrecognized_mode`, `missing_stores`, `duplicate_keys`, `malformed_steps`, and — only with `--requirements` — `must_have`, `should_have`, `uncovered_should`, `lint_failures`. Every key is present in both modes.
- **Exit codes** — **0** gated scenarios ≥ `--min-scenarios`, at least one gated step had a result, and the blocking arrays empty; **1** any gated step missing a result, any gated `FAIL`/`BLOCKED`/`NOT RUN`, an unevidenced gated manual step, any dangling `[inverse of N]`, an unparsed gated step table, `stale_results`, too few scenarios, zero gated steps, or (structure mode) any structural defect or uncited Must-Have; **2** mode-separation violations, missing/unreadable matrix or results, no parseable scenario or result line, `changed_file_missing`, a `--requirements` file with zero Must-Haves, or a bad `--require-priority` token.
- **Self-test** — **90** cases. Depth (structure-mode conditions, results grammar, parsing rules, mode divergences, fixtures): `references/check_acceptance_suite.md`.

## check_ship_decision.py

Makes Dep's `ship-decision.md` GO/NO-GO machine-verifiable: it requires an unambiguous labeled `GO` or `NO-GO` (Ship Decision / Verdict / Recommendation line), a Rollback heading, and a post-deploy checklist section. Used at `bgpdd-build` Phase 5 step 6 (shape-only — a prep NO-GO is a legitimate result), `bgpdd-shipping` Step 0.4, and Step 3 (`--require-go`).

```bash
python check_ship_decision.py --report <path> [--require-go] [--ledger <path>]
python check_ship_decision.py --self-test
```

- **Exit codes** — `--require-go` fails (exit 1) when the latest verdict is `NO-GO` rather than `GO`. **0** structurally valid decision (and `GO`, under `--require-go`); **1** gate failed (NO-GO under `--require-go`, or incomplete/ambiguous decision content); **2** usage error, missing/empty/unreadable report, or structural non-conformance.
- **Self-test** — **13** cases. Depth (verdict grammar, last-section-wins, the eval-grader divergence): `references/check_ship_decision.md`.

## check_blockers.py

Makes the blockers-ledger gate machine-run: it reads `orchestrator-state.json` and exits non-zero when any standing blocker remains. Used at `bgpdd-shipping` Step 0.5.

```bash
python check_blockers.py --state <path> [--ledger <path>]
python check_blockers.py --self-test
```

- **Exit codes** — **0** `blockers` is empty; **1** one or more standing blockers (JSON stdout lists them); **2** usage/structural failure (missing state, invalid JSON, missing `blockers` field).
- **Self-test** — **6** cases. Depth: `references/check_blockers.md`.

## next_milestone.py

Makes "what's the next milestone to build" a mechanical derivation from `plan.md` instead of a full re-read — roughly 2K tokens against the ~73k a whole-plan re-read costs. It also detects a stale `milestone_cursor`, and can emit the runtime gate's arguments straight from the plan's `RUNTIME PROBE:` line.

```bash
python next_milestone.py --plan <path> [--state <path>] [--ledger <path>] [--emit-gate-args]
python next_milestone.py --self-test
```

- **Flags** — `--plan` required. `--state` adds the stale-cursor check (`cursor` is `null` without it). `--ledger` is **advisory only, exit codes unchanged**: it populates `unbacked_complete`, every `[x]` milestone with no PASS `check_commit_gate.py` ledger entry; a missing ledger file warns. `--emit-gate-args` populates `gate_args`.
- **JSON keys** — `plan_file`, `result`, `next_milestone` (`{title, line, domain, surface}`), `milestone_text`, `remaining`, `completed_count`, `total_count`, `cursor` (`{stored, matches_next, stale}`), `gate_args` (`{surface, expect_status, require_keys, forbid_hosts}`), `unbacked_complete`, `warnings`, `error`.
- **Exit codes and result values** — **0** `NEXT` or `DONE`; **1** `MIXED` — the family name for "the plan cannot be executed as written" (mixed `[UI]`/`[API]` tags, `UNTAGGED`, or a missing/unknown `[vs:<surface>]` tag), a planning defect rather than a routing decision to improvise past: they share a verdict because the Orchestrator's action is identical — halt and route back through Alex — and are told apart by `warnings`; **2** usage error, unreadable file, invalid `--state` JSON, a state file missing `milestone_cursor`, or zero milestone headings in the plan.
- **Self-test** — **39** cases. Depth (milestone grammar, the completion convention, `--emit-gate-args` semantics, fixtures): `references/next_milestone.md`.

## mark_milestone.py

The write side of the `[x]` completion convention `next_milestone.py` reads. Until it existed, a milestone could be marked done by typing three characters: no commit, no gate, no evidence. It appends the marker only when the completion is backed, and leaves a ledger record either way.

```bash
python mark_milestone.py --plan <path> --milestone "<title>" [--repo <dir>] \
    [--require-commit] [--ledger <path>] [--require-gates <name>[,<name>...]]
python mark_milestone.py --self-test
```

- **Flags** — `--require-commit` demands that HEAD's history carry a commit naming the milestone (`git log --fixed-strings --grep="<title>"`). `--require-gates` (default `check_commit_gate.py`) demands that each named gate's LATEST ledger entry for this milestone record `PASS`, and requires `--ledger`. The title match is case-insensitive and **whole-token**: `Milestone 1` never marks `Milestone 10`. Line endings and BOM survive; the diff is one character.
- **Problem codes** (exit **1**, in `problems`) — `milestone_not_found`, `ambiguous_milestone`, `already_complete`, `no_commit`, `ledger_missing`, `ledger_failed`.
- **Exit codes** — **0** the marker was appended; **1** a refusal above; **2** missing `--plan`/`--milestone`, an unreadable plan, no milestone headings, `--require-gates` without `--ledger`, or a git failure.
- **Deliberate divergence (convention #8)** from `check_commit_gate.py --require-ledger-gates`, which re-hashes inputs: this checks the VERDICT only.
- **Self-test** — **20** cases. Depth: `references/mark_milestone.md`.

## update_state.py

**The sanctioned read-modify-write path for `orchestrator-state.json`**, replacing hand-edits that risk malformed JSON or silent blocker deletion. Every invocation validates the existing file (if any), applies the requested action(s), stamps `updated`, and writes atomically before printing the resulting full state as JSON.

```bash
python update_state.py --state <path> \
    [--init --project-name <name>] \
    [--set-cursor <title|null>] [--set-pipeline <name>] \
    [--set-feature <feature|null>] [--set-branch <name>] \
    [--set-artifact <name>=<path>] \
    [--add-blocker "<text>"] \
    [--resolve-blocker "<substring>" --evidence "<text>"] [--ledger <path>]
python update_state.py --self-test
```

- At least one action is required per invocation; any combination may be given in one call.
- **`--init --project-name <name>`**: creates the skeleton (`schema` `"1"`, `project_name`, `feature: null`, `pipeline: ""`, `branch: null`, `milestone_cursor: null`, `artifacts: {}`, `blockers: []`) if the file does not exist; a **no-op with a warning** if it does, while other actions in the same call still apply.
- **`--set-cursor` / `--set-pipeline` / `--set-branch` / `--set-feature`**: set those fields verbatim. The **literal string `null`** sets the JSON field to `null`.
- **`--set-artifact <name>=<path>`** (repeatable): merges into `artifacts`; the literal value `null` stores JSON `null`. A spec with no `=` is a usage error.
- **`--add-blocker "<text>"`** (repeatable): appends verbatim, preserving existing entries.
- **`--resolve-blocker "<substring>" --evidence "<text>"`**: removes every matching entry (case-insensitive). **`--evidence` is required and must be non-empty** — omitting it is a usage error, not a silent no-op. A substring matching nothing warns and changes nothing. Every removal also appends a line to `blockers-resolved.log` beside the state file. Pipelines pass `--ledger` on this action.
- **Exit codes** — **0** the action(s) applied and the file was written; **2** usage/structural failure (missing `--state`, no action, `--init` without `--project-name`, `--resolve-blocker` without non-empty `--evidence`, a bad `--set-artifact` spec, a state file that is not a JSON object, or a missing state file without `--init`).
- **Self-test** — **20** cases. Depth (atomicity, the blocker-ledger rule this mechanizes): `references/update_state.md`.

## run_quiet.py

Runs a build or test command, writes its **full** merged stdout+stderr to a log on disk, and prints a short report to stdout: header, an error excerpt with context, and a tail. With `--capture` it also writes a conforming runtime-evidence capture artifact plus the provenance sidecar the runtime gate requires. It exists so a transcript carries only what it needs to diagnose a failure while nothing is actually lost.

```bash
python run_quiet.py --log <path> [--context N] [--tail N] [--timeout SECONDS] -- <command and args...>
python run_quiet.py --capture <path> [--capture-field Name=value]... [--log <path>] -- <command and args...>
python run_quiet.py --self-test
```

- **Flags** — one of `--log` or `--capture` is required, plus a command after `--`. Defaults: `--context 5`, `--tail 15`, `--timeout 240` (seconds). Everything after `--` is passed to the child verbatim (no shell). `--capture-field` without `--capture` is a usage error.
- **`--capture` field ownership** — `--capture-field Name=value` supplies only the descriptive header (`Title`, `Milestone`, `Requirement IDs`, `Surface`, `Transport`, `Base URL`, `Environment`, `Config repointed`, `Build marker`, `OpenAPI`). A field name the tool owns — `Probe command`, `Captured`, `Exit code`, `Duration`, `Log` — is **rejected, not overwritten**: exit **2**, no capture written. That refusal is the integrity property of this mode.
- **The sidecar** — `--capture <path>` also writes `<path>.meta.json` recording `argv`, `cwd`, `host`, `pid`, `started`/`finished` (ISO-8601 UTC), `exit_code` (124 on timeout), `body_sha256` (over the captured text as embedded), `capture_sha256` (over the finished capture FILE's bytes), `tool: "run_quiet.py"` and `schema: 1`. Its path is printed on the `sidecar:` line of the stdout summary. `check_runtime_evidence.py` requires it.
- **Exit codes** — passthrough of the child's own exit code; **124** the child was killed for exceeding `--timeout` (best-effort process-tree kill); **2** structural/usage failure (no `--log`/`--capture`, no command after `--`, a log or capture path that cannot be created or written, an owned `--capture-field`, or a command that could not be launched). **Windows caveat**: the child is launched without a shell, so Python cannot exec a `.cmd`/`.bat` shim — invoke `npx.cmd`/`npm.cmd`, or bypass the shim (`node node_modules/@playwright/test/cli.js`).
- **Self-test** — **20** cases. Depth (sidecar rationale and the `.gitattributes` caveat, report shape, error profile, the no-information-lost guarantee): `references/run_quiet.md`.

## check_dependency_tables.py

Statically validates every agent's `## Methodology Dependencies` section: (a) the section carries the canonical "NOT Skill-tool invocables" wording, and (b) every `{PLUGIN_ROOT}` path in its table resolves to a real file. `agents/blackgoat.md` is excluded (CLAUDE.md convention #7).

```bash
python check_dependency_tables.py <skills_dir>
python check_dependency_tables.py --self-test
```

- **Flags** — `<skills_dir>` is the plugin's `skills/` directory (i.e. `{PLUGIN_ROOT}`); `agents/` is located as its sibling. Paths are matched **with or without surrounding backticks**.
- **Exit codes** — **0** every table valid; **1** at least one violation, with a per-violation report on stdout (a dangling path, a missing guard sentence, or an agent with no Methodology Dependencies section at all); **2** usage error, or a missing/empty `agents/` directory — it fails closed rather than reporting a vacuous pass.
- **Self-test** — **9** cases. Depth: `references/check_dependency_tables.md`.

## check_frontmatter.py

Validates the YAML frontmatter of every `agents/*.md` and `skills/*/SKILL.md`. An unquoted scalar containing `": "` makes a real YAML parser reject the whole block, so the runtime silently sees no persona and no skill trigger — which had already happened three times in this repo before anything checked for it.

```bash
python check_frontmatter.py <root_dir>
python check_frontmatter.py --self-test
```

- **Checks** — (a) the leading `---` block exists and closes; (b) every non-blank, non-comment line inside is a `key: value` pair; (c) a plain (unquoted) scalar value never contains `": "`; (d) a value opening with a quote closes with a matching one; (e) every required key is present (agents: `name`, `description`, `model`, `role`, `phase`, `squad`, `reports-to`; skills: `name`, `description`); (f) `model:` where present is one of `opus`/`sonnet`/`haiku`; (g) `description:` is ≤ 1024 chars (**warning only**); (h) every `skills/bgpdd-*/SKILL.md` carries `trigger: /bgpdd-<name>` matching its folder. `agents/blackgoat.md` is exempt from (b)–(h) and checked only for existence.
- **JSON keys** — `result`, `files_checked`, `errors`, `warnings`; each `errors`/`warnings` entry is `{file, line, problem}`.
- **Exit codes** — **0** `result: PASS` (warnings do not gate); **1** at least one error; **2** usage error (missing or non-directory `root`), or a root carrying neither `agents/` nor `skills/`.
- **Self-test** — **9** cases. Depth: `references/check_frontmatter.md`.
