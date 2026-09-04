---
name: pipeline-tools
description: "Deterministic stdlib-Python CLIs for the PDD pipeline gates. check_coverage.py gates Must-Have FR/NFR coverage (plan, test, design modes); check_commit_gate.py runs the commit gate and can commit; check_agent_report.py gates Cipher and Vera reports; check_runtime_evidence.py gates runtime captures (transport, sidecar, freshness); check_bugfix_intake.py, check_red_green.py and next_bugfix_route.py gate the bugfix report, RED/GREEN pair and route; check_acceptance_suite.py gates the acceptance matrix; check_ship_decision.py gates GO/NO-GO, rehearsal and baseline; check_blockers.py gates the blockers ledger; next_milestone.py and mark_milestone.py read/write milestone completion; update_state.py is the sanctioned orchestrator-state.json writer; run_quiet.py writes logs and captures; record_run.py and summarize_run.py roll up run telemetry; detect_stack.py reports stacks; check_quick_close.py closes a bgpdd-quick change (note, captured check, frozen paths, size bound, commit); review_package.py packages the diff Luna reviews; check_dependency_tables.py and check_frontmatter.py are the static lints. Squad-internal: run by the Orchestrator, never delegated."
---

# pipeline-tools

A family of pure-stdlib Python 3 CLIs under `scripts/` that convert the bgpdd pipelines' prose gates into commands with exit codes. The Orchestrator runs them directly via a shell action — they are never delegated to an agent, and there is no manual open-and-read substitute for any of them.

This file is the **lean contract spine**: per script, what it is for, how it is invoked, its flags, its JSON keys, its exit codes, and its problem codes. Rationale, observed-failure narratives, parsing grammars, fixture inventories, scope-limit essays and self-test case lists live in `references/<script-name>.md` and are loaded on demand.

## Single contract authority

The pipeline gates — `bgpdd-plan` Phase 3.5, `bgpdd-lite` Phase 2.5, `bgpdd-build` Phase 2 and Phase 5, `bgpdd-verify` Phase 3, `bgpdd-shipping` Steps 0.3–3.5, and `bgpdd-bugfix`, `bgpdd-quick` — reference this file as the single source of truth for every CLI's contract (invocation, flags, JSON shape, exit codes, parsing rules). They do not restate the rules inline; update them here only. The file therefore stays at this path: fourteen files across the pipelines, the personas and the sibling skills cite it by name.

## Gate ledger

Every gate in this family accepts `--ledger <path>` and appends **exactly one JSON line per run, on every exit path** (creating parent directories):

```json
{"ts": "<ISO-8601 UTC>", "gate": "<script basename>", "argv": ["..."], "milestone": "<--milestone value or null>", "inputs": {"<path as given; a cited capture is keyed by its resolved path relative to the cwd>": "<sha256 hex or null>"}, "verdict": "PASS|FAIL|ERROR", "exit": 0}
```

`inputs` carries every file path argument the script read. `verdict` maps exit 0/1/2 to PASS/FAIL/ERROR. Writing the ledger is **best-effort**: a ledger that cannot be written never changes the gate's own verdict — it is an audit trail for LATER gates, not a term in this one. `update_state.py --resolve-blocker` additionally records `"action": "resolve-blocker"` and `"evidence": "<text>"`. The CLI still cannot judge whether "trust me" is real evidence; the ledger makes the claim durable and attributable instead of gone the moment the array shrinks.

Carrying `--ledger`: `check_commit_gate.py`, `check_quick_close.py`, `check_agent_report.py`, `check_acceptance_suite.py`, `check_ship_decision.py`, `check_coverage.py`, `check_blockers.py`, `check_runtime_evidence.py`, `check_bugfix_intake.py`, `check_red_green.py`, `next_bugfix_route.py`, `update_state.py`, `mark_milestone.py`. `next_milestone.py` and `summarize_run.py` READ the ledger but never write it; `next_bugfix_route.py` both reads and writes it (it refuses to route without a recorded intake PASS). `record_run.py` carries no `--ledger` flag at all — it is not a gate; it writes the other durable record, the run log, described below. The pipelines pass `--ledger .docs/{project-name}/implementation/gates.jsonl` on every gate invocation (Orchestrator Contract §4).

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
    [--max-changed-files <N> [--waiver <path>]] \
    [--ledger <path>] [--require-ledger-gates <name>[,<name>...]] \
    [--require-runtime-evidence --runtime-report <path> \
     [--surface <key>] [--require-key <name>]... [--expect-status <N>] \
     [--forbid-host <pattern>]... [--require-build-marker <value>] \
     [--require-openapi-reachable] [--allow-missing-sidecar] \
     [--openapi-doc <path> --openapi-route <path> [--openapi-method <verb>]]]
python check_commit_gate.py --self-test
```

- **Flags** — `--repo` defaults to `.`. Every runtime-evidence assertion flag forwards to `check_runtime_evidence.py`; any of them passed *without* `--require-runtime-evidence` is exit 2, never a silent no-op. `--ledger` and `--allow-missing-sidecar` forward when the child script declares them. `--require-ledger-gates` requires `--ledger` (else exit 2) and demands that each named gate's latest ledger entry for this milestone record `PASS` **and** still hash the same inputs.
- **`--max-changed-files <N>`** (the `bgpdd-bugfix` fix-size bound; lane default `5`) — counts the **declared** `--changed-files` paths, the same list the staleness check already validates exist; pairing it with `--verify-tree` is what makes that count equal the real diff. `N < 1` is exit 2. Unset, the bound is not applied (`size_ok: true`, `max_changed_files: null`) and behaviour is unchanged. **`--waiver <path>`** (exit 2 without `--max-changed-files`) waives an overrun when that file carries a `## Size waiver` heading (level 2–4, outside a fence) whose body is non-empty and not a placeholder — **in either shape**: every line individually a stand-in, or one `<...>` span wrapped across several lines (the shape the shipped `rca-template.md` writes, asserted to fail by `test_the_shipped_rca_template_waiver_fails`). **Deliberately hand-typed, unlike every other evidence path in this family (convention #8)**: exceeding the bound is the *user's* decision and no script can verify a judgement call, so the gate buys durability and attributability — the decision written into `rca.md` and hashed into the ledger record — not verification.
- **Section boundaries** — ANY heading of level 2–6 closes a `## Review:` section. **Migration**: a `**Verdict:**` line must appear BEFORE any subheading inside its review section, or the section reads as no-verdict and fails closed.
- **JSON keys** — `milestone`, `review_report`, `state_file`, `review_found`, `verdict`, `ambiguous_review_section`, `stale`, `blocking`, `unscoped_blockers`, `other_milestone_blockers`, `ignored_unscoped_ids`, `rendered_evidence`, `rendered_evidence_ok`, `undeclared_changes`, `tree_verified`, `max_changed_files`, `changed_file_count`, `size_waiver` (`{path, present, section_found, body_nonempty, satisfied}`), `size_ok`, `runtime_evidence`, `runtime_evidence_ok`, `ledger`, `require_ledger_gates`, `ledger_gate_problems`, `ledger_gates_ok`, `warnings`, `committed`, `result`, `error`. **Problem codes**: `ledger_gate_problems` entries carry `ledger_missing`, `ledger_failed` or `ledger_stale`.
- **Blockers precondition** — same normalization and exact-equality scoping as `check_blockers.py` (helper duplicated). Scoped-to-this-milestone (`blocking`) or unscoped (`unscoped_blockers`) block; `--ignore-unscoped` skips unscoped and names them in `ignored_unscoped_ids`; `other_milestone_blockers` never block; `Info` never blocks (fixed floor, deliberately not caller-tunable at the last checkpoint).
- **Exit codes** — **0** gate passed (and committed, with `--commit`); **1** gate failed (`verdict` not `Approve`, `ambiguous_review_section`, `stale`, non-empty `blocking`, unignored `unscoped_blockers`, `rendered_evidence_ok: false`, `runtime_evidence_ok: false`, `ledger_gates_ok: false`, `size_ok: false`, or `tree_verified: false`); **2** usage error (including `--waiver` without `--max-changed-files`, or `--max-changed-files 0`), a `--changed-files` path that does not exist (`changed_file_missing`), unreadable artifact, invalid state JSON, git failure, or a structural failure from the delegated runtime gate.
- **Self-test** — **76** cases, including `test_pipeline_value_never_changes_the_verdict`: the verdict JSON is **byte-identical** across every `pipeline` value and with the field absent, and the report never echoes it. `bgpdd-bugfix`'s feature route shares the epic's state file and never stamps its own `pipeline`, so it cites this test rather than asserting the property in prose (convention #9). Depth (delegation rationale, parsing rules, the ledger-gate essay): `references/check_commit_gate.md`.

## check_quick_close.py

The `bgpdd-quick` Phase 3 gate, and that lane's ONLY gate — it carries alone what the heavier lanes spread across five gates and a squad. Given the lane's two artifacts (`note.md`, one `run_quiet.py --capture`) and the declared file list, it verifies the change was declared before it was made, still matches the tree, was checked *after* the edit by a command that passed, edited no frozen test, and is still small enough for a lane with no plan behind it — then, with `--commit`, commits exactly the declared files.

```bash
python check_quick_close.py --note <path> --capture <path> \
    --changed-files <p1> [<p2> ...] [--repo <dir>] \
    [--max-changed-files <N>] [--frozen <path>]... \
    [--milestone "<slug>"] [--ledger <path>] [--commit --message "<msg>"]
python check_quick_close.py --self-test
```

- **Flags** — `--note`, `--capture` and at least one `--changed-files` path are required; `--repo` defaults to `.`; `--frozen` is repeatable. `--commit` requires `--message`, and `--message` without `--commit` is exit 2, never a silent no-op. **`--max-changed-files` DEFAULTS to `3`** and must be `>= 1` — **deliberate divergence (convention #8) from `check_commit_gate.py`, where the bound is opt-in**: there it is an extra assertion, here it is the lane's definition, so a forgotten flag would silently delete it. **There is deliberately no `--waiver`** — also tighter than `check_commit_gate.py` (convention #8): an overrun in this lane has named escalation destinations, which the failure message prints, so a waiver would let the one bound that defines the lane be self-certified by whoever exceeded it.
- **Note grammar** — three labelled lines, matched case-insensitively as list items or bare lines, outside fences: `- What:`, `- Where:`, `- How verified:`. A value that is `<...>`, `TODO`, `TBD`, `N/A`, `none`, `unknown`, `???` or `...` counts as absent (same vocabulary as `check_bugfix_intake.py`). The `Where` line's paths (comma- and/or whitespace-separated, backticks stripped) must **equal** the `--changed-files` set after repo-relative normalization.
- **Freshness — deliberate divergence (convention #8) from `check_red_green.py`'s strict `>`**: the sidecar's `finished` (whole seconds) is compared `>=` against each changed file's mtime **floored to the second**. There the two captures are a fix round apart; here an edit and its check routinely land inside one second, and a strict `>` would reject honest work.
- **Frozen check** — fires only on porcelain statuses meaning an **existing tracked file changed** (`M`/`D`/`R`/`C`/`U` in either column); `??` and `A`/`AM` are new files. Adding a test passes, editing one fails — a rule that forbade the lane's own use case would be routed around rather than obeyed. Staged and unstaged edits both count.
- **JSON keys** — `note`, `capture`, `repo`, `milestone`, `note_fields`, `note_where_paths`, `changed_files`, `changed_file_count`, `max_changed_files`, `size_ok`, `capture_sidecar`, `capture_exit_code`, `capture_finished`, `newest_changed_file`, `fresh`, `undeclared_changes`, `frozen`, `frozen_modified`, `problems`, `problem_codes`, `warnings`, `committed`, `result`, `error`.
- **Problem codes**, evaluated in this order — `note_missing`, `note_incomplete`, `note_where_mismatch`, `capture_missing`, `not_a_capture`, `sidecar_missing`, `sidecar_hash_mismatch`, `capture_exit_nonzero`, `capture_stale`, `changed_file_missing`, `undeclared_tree_changes`, `frozen_path_modified`, `size_bound_exceeded`; `problems` entries are formatted `"<code>: <prose>"`. Every code is reported rather than short-circuited, so one run names every term that failed.
- **`--ledger` inputs** — the note, the capture, **its sidecar**, and every declared file, so a later re-hash catches an artifact edited after this gate passed.
- **Exit codes** — **0** every term held (and committed, with `--commit`); **1** any problem code; **2** usage error (a missing required flag, `--max-changed-files 0`, `--commit` without `--message`, `--message` without `--commit`), an unreadable artifact, or a git failure / missing git.
- **Self-test** — **33** cases, each against a real temp git repo, including an end-to-end capture written by the real `run_quiet.py`. Depth (the two divergences, the frozen status-letter rule, the copy-not-import decision, the case inventory): `references/check_quick_close.md`.

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

## review_package.py

Materializes the diff a reviewer is told to review, as ONE markdown file plus a provenance sidecar. `bgpdd-build` Phase 3 step 4 told a fresh Luna to re-review "the remediation diff itself"; she received a path list and read the amended tree, which shows the files' CURRENT state — a fix is indistinguishable from the status quo and a deletion is invisible. That prose instruction is converted here into an artifact the Orchestrator must generate and name in the brief (convention #9). It renders; it does not judge — there is no exit 1.

```bash
python review_package.py --repo <dir> --base <ref> [--head <ref>|WORKTREE] \
    [--changed-files <p1> [<p2> ...]] --out <dir>/review-package.md \
    [--context <N>] [--ledger <path>] [--milestone "<title>"]
python review_package.py --self-test
```

- **Flags** — `--base` and `--out` required; `--repo` defaults to `.`, `--head` to `HEAD`, `--context` to `10`. `--changed-files` is a git pathspec restricting `## Stat` and `## Diff` only (never `## Commits`). **`--head WORKTREE`** compares the base against the **uncommitted working tree** — that is the `bgpdd-build` Phase 3 case, where the milestone is not committed until the Phase 5 commit gate and a two-dot range would render an empty package for work that plainly exists.
- **Output** — `<out>` carries a header (repo, base, head with resolved shas, timestamp, generated-by, scope), `## Commits` (`git log --oneline base..head`), `## Stat` (`git diff --stat`) and `## Diff` (`git diff -U<context>`, fenced with a backtick run one longer than any inside the diff — these packages routinely contain diffs OF markdown).
- **Sidecar** — `<out>.meta.json` mirrors `run_quiet.py`'s shape: `argv` (the exact `git diff` argv), `cwd`, `started`, `finished`, `exit_code`, `capture_sha256` (over the finished package FILE's bytes), `tool`, `schema: 1`; plus `git_argv` (all three commands) and the resolved `base`/`head` shas.
- **JSON keys** — `written`, `out`, `sidecar`, `repo`, `base`, `head`, `context`, `changed_files`, `commit_count`, `diff_bytes`, `capture_sha256`, `result`, `error`.
- **Exit codes** — **0** package written; **2** git failed or is absent, a ref is unresolvable, `--repo` is not a git repo, a required flag is missing, `--out` cannot be written, or **the diff is empty** — an empty diff is not a package, and a review of nothing looks exactly like a review of something (a deliberate divergence from `run_quiet.py`, where empty output is a legitimate observation, per convention #8).
- **Self-test** — **19** cases in a disposable `git init` repo. Depth (the observed failure, rendering rules, sidecar meaning, scope limits): `references/review_package.md`.

## check_bugfix_intake.py

The `bgpdd-bugfix` Phase 0 intake gate. Converts the prose rule that a bugfix starts from a written report rather than chat scrollback into an artifact that has to exist on disk: it lints `{bugfix-root}/bug-report.md` (template and field rules: `bgpdd-bugfix/references/bug-report-template.md`) for present, non-placeholder sections, a re-runnable reproduction, and the two enums later phases read. No delegation in that lane happens before it exits 0.

```bash
python check_bugfix_intake.py --report <path> [--milestone "<slug>"] [--ledger <path>]
python check_bugfix_intake.py --self-test
```

- **Required sections** — Observed behaviour, Expected behaviour, Exact error text or log excerpt, Reproduction, Environment, Regression, Affected surface (headings matched case-insensitively, level 2–6, `behavior` spelling accepted).
- **Field rules** — Reproduction needs **either** a usable `- Command:` line **or** at least **two** numbered steps whose text is not a placeholder. A usable `- Command:` value is **backtick-wrapped**, non-placeholder, and command-shaped: >= 2 whitespace-separated tokens, or 1 token carrying `/`, `\`, `.` or `:`. `- Command: see chat` (unquoted) and `` `pytest` `` (one bare word) both fail; `` `./scripts/repro.sh` `` passes. **Documented residual**: `` `see chat` `` is backticked and two tokens, so it passes this text lint — `next_bugfix_route.py --red` closes it mechanically. An unusable Command line beside >= 2 usable steps is a **warning**, and the mode falls back to `steps`. `- Surface:` must be exactly `api` / `ui` / `both`; `- Runtime observable:` and `- Regression:` exactly `yes` / `no`; `- Regression: yes` additionally needs a real `- Last known good:`. A value that is `<...>`, `TODO`, `TBD`, `N/A`, `none`, `unknown`, `???` or `...` counts as absent.
- **Fenced blocks — deliberate divergence (convention #8)** from the family's blank-the-fence rule above: fenced content lines are **masked to a sentinel, not blanked**, so a pasted log excerpt still counts as section content while a heading or `- Key: value` line *inside* a fence satisfies nothing. Blanking would make an honest log paste read as an empty section.
- **JSON keys** — `report`, `sections_found`, `sections_missing`, `placeholder_sections`, `reproduction_mode` (`command` | `steps` | null), `reproduction_command` (the backticks-stripped string, or null), `surface`, `runtime_observable` (JSON boolean), `regression` (JSON boolean), `last_known_good`, `problems`, `problem_codes`, `warnings`, `result`, `error`.
- **Problem codes** — `section_missing`, `section_empty`, `section_placeholder`, `reproduction_missing`, `surface_invalid`, `runtime_observable_invalid`, `regression_invalid`, `last_known_good_missing`; `problems` entries are formatted `"<code>: <prose>"`.
- **Exit codes** — **0** every check passed; **1** any problem code; **2** missing `--report`, an unreadable file, or a file with no level-2..6 heading outside a fence (structurally not a bug report).
- **Self-test** — **33** cases, including that the **shipped template itself FAILS** the gate: a template that passes is a bypass.

## check_red_green.py

The `bgpdd-bugfix` Phase 4 gate. A post-fix green alone cannot show the check ever failed, and a RED and GREEN of *different* commands are two unrelated runs dressed as a proof. Given one RED capture and one or more GREEN captures — all written by `run_quiet.py --capture` — it verifies the pair actually constitutes a before/after.

```bash
python check_red_green.py --red <capture> --green <capture> [--green <capture>]... \
    [--green-runs <N>] [--milestone "<slug>"] [--ledger <path>]
python check_red_green.py --self-test
```

- **Checks** — every capture exists and carries a `## Captured output` section; every capture has its `<capture>.meta.json` sidecar, a JSON object whose `capture_sha256` still matches the capture FILE's bytes and whose `exit_code` is an integer; the sidecars record the **identical** child `argv`; RED's `exit_code` is **non-zero**; every GREEN's is **zero**; every GREEN `finished` **strictly later** than RED.
- **Sidecar validation is `check_runtime_evidence.py`'s, duplicated not imported** (family convention: stdlib-only, one file each). Not weakened — the only difference is that RED inverts the exit-code expectation, which is the point of a RED capture.
- **One-second resolution, fail-closed** — `finished` is stamped to the second and the ordering test is strictly `>`, so EQUAL stamps do not order two runs and are rejected (`green_not_newer`). A real RED and GREEN are a fix round apart; a pair inside one second is re-taken.
- **`--green-runs <N>`** (default `1`, `< 1` is exit 2) — for a flaky bug: at least `N` `--green` captures must be supplied **and all must pass**. **4 of 5 green is not fixed.** Supplying fewer than `N` is exit **1** (`green_runs_short`), not exit 2: short evidence is a failed gate, not a usage error.
- **JSON keys** — `red`, `green`, `green_runs`, `red_result`, `green_results`, `command`, `problems`, `problem_codes`, `warnings`, `result`, `error`. Per capture: `path`, `role`, `exists`, `is_capture`, `sidecar`, `sidecar_present`, `sidecar_capture_sha256_ok`, `exit_code`, `argv`, `finished`, `problems`, `problem_codes`.
- **Problem codes** — `capture_missing`, `not_a_capture`, `sidecar_missing`, `sidecar_hash_mismatch`, `sidecar_no_exit_code`, `sidecar_no_argv`, `red_exit_zero`, `green_exit_nonzero`, `command_mismatch`, `green_not_newer`, `timestamp_unparseable`, `green_runs_short`.
- **`--ledger` inputs** — each capture **and its sidecar**, so a later `check_commit_gate.py --require-ledger-gates check_red_green.py` re-hashes both and catches a sidecar edited after this gate passed.
- **Exit codes** — **0** every term holds; **1** any problem code; **2** missing `--red`/`--green`, or `--green-runs < 1`.
- **Self-test** — **24** cases, including an end-to-end pair produced by the real `run_quiet.py`.

## next_bugfix_route.py

Makes the `bgpdd-bugfix` FAST / FULL / PLAN fork a mechanical derivation from `bug-report.md` + `rca.md` (grammar: `bgpdd-bugfix/references/rca-template.md`) instead of a judgement call made where the Orchestrator most wants to proceed (CLAUDE.md convention #9).

```bash
python next_bugfix_route.py --report <bug-report.md> --rca <rca.md> --ledger <path> \
    [--red <capture>] [--milestone "<slug>"] [--max-changed-files <N>]
python next_bugfix_route.py --self-test
```

- **`--ledger` is REQUIRED** and doubles as an input: the gate **refuses to route** (exit 2, `intake_unbacked`) unless the ledger's latest `check_bugfix_intake.py` entry is a `PASS` whose recorded input sha256 still matches the current `bug-report.md`. Matching is on the **hash**, not the path string, because the earlier invocation legitimately recorded a different (relative vs absolute) path.
- **The report's own fields come from delegating** to `check_bugfix_intake.py` and reading its JSON — the same subprocess-reuse pattern `check_commit_gate.py` uses for `check_runtime_evidence.py`. A child re-run that disagrees with the recorded PASS over the same bytes is exit 2, never a route.
- **`--red <capture>` ties the RED to the report** — **REQUIRED** when the report carries a `- Command:` line (omitting it is exit **2**, `red_required`). The RED capture's `<capture>.meta.json` sidecar `argv` must **equal a legitimate tokenization** of the report's command (backticks stripped). The comparison is on **token lists, not strings** — `shlex.split(posix=True)`, then the same with backslashes doubled (so a backslash-separated Windows path survives), then a raw whitespace split; any match passes, and `red_match_strategy` names which did. A string compare rejected every correctly quoted command (`-d '{}'`, `-H "Content-Type: application/json"`), because the shell strips quoting before the child sees argv. Nothing fuzzier is tried: reordered tokens, case differences and a different URL all still mismatch. The `- Command:` value must be a single **argv-runnable** command (no pipes, redirects or `&&`) — `run_quiet.py` runs argv with no shell. Mismatch is exit **1** `red_command_mismatch`; an absent/unreadable/argv-less sidecar or a missing capture is exit **1** `red_sidecar_missing`. A steps-only report has no command to compare, so `--red` is optional and unchecked there (passing it warns). This check runs **before** the RCA is read, so a RED that does not back the report blocks regardless of the RCA's state.
- **Route rules** — **PLAN** (outranks all) when the RCA declares a new capability, a schema or contract change, or `- Estimated changed files:` above `--max-changed-files` (default `5`). **FAST** when *all* hold: `reproduction_mode` is `command`; **the RED capture ran that exact command**; exactly one `- Root cause file:`; surface is `api` or `ui` (not `both`); `- Baseline suite: green`. **FULL** otherwise.
- **FAST and FULL differ ONLY in user check-ins** (FAST proceeds phase to phase; FULL pauses after the RCA and before the commit). **Neither ever skips RED, GREEN, Luna, or the commit gate** — the tool prints this in its `reasons`.
- **rca.md grammar** — `- Key: value` lines read file-wide, **last mention wins**; `- Root cause file:` is the one repeatable key. Fences are blanked (family rule), so a template block asserts nothing. A missing `- Baseline suite:`, `- New capability:`, `- Schema or contract change:` or any `- Root cause file:` is `INCOMPLETE`; a missing `- Estimated changed files:` only warns.
- **JSON keys** — `report`, `rca`, `ledger`, `max_changed_files`, `intake_backed`, `surface`, `runtime_observable`, `reproduction_mode`, `reproduction_command`, `red`, `red_argv`, `red_command`, `red_match_strategy`, `red_matches_report`, `problems`, `problem_codes`, `root_cause_files`, `baseline_suite`, `new_capability`, `schema_or_contract_change`, `estimated_changed_files`, `missing_fields`, `route`, `reasons`, `warnings`, `result`, `error`.
- **Exit codes and result values** — **0** `FAST` / `FULL` / `PLAN`; **1** `INCOMPLETE` (the RCA cannot be routed as written — fill the named fields; mirrors `next_milestone.py`'s `MIXED`) or `BLOCKED` (`red_command_mismatch` / `red_sidecar_missing` — the RED does not back the report); **2** missing `--report`/`--rca`/`--ledger`, `red_required`, `--max-changed-files < 1`, an unreadable `rca.md`, `intake_unbacked`, or an unavailable/disagreeing intake gate.
- **Self-test** — **49** cases, including an intake PASS whose hash no longer matches, a later FAIL superseding an earlier PASS, a fenced RCA that routes nothing, the full `--red` set (mismatch, missing sidecar, argv-less sidecar, `` `see chat` `` refused here, steps-only unchecked), and the quoting set (single-quoted JSON body, double-quoted header, Windows path, plus reordering/case/different-URL all still mismatching).

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

Makes Dep's `ship-decision.md` GO/NO-GO machine-verifiable: an unambiguous labeled `GO` or `NO-GO`, a Rollback heading, a post-deploy checklist section. Two opt-in flags convert the two assertions a heading match never proved: `--require-rehearsal` (the rollback was performed, not planned) and `--require-baseline` (the threshold table has numbers to grade against). Used shape-only at `bgpdd-build` Phase 5 step 6 and `bgpdd-shipping` Step 0.4 (a prep decision legitimately predates a rehearsal and a baseline), and with `--require-go --require-rehearsal --require-baseline` at `bgpdd-shipping` Step 3.

```bash
python check_ship_decision.py --report <path> [--require-go] [--require-rehearsal] [--require-baseline] [--repo <dir>] [--max-rehearsal-age-days <N>] [--ledger <path>]
python check_ship_decision.py --self-test
```

- **Flags** — `--require-go` fails on `NO-GO`. `--require-rehearsal` demands one grammar-conforming `Time to Rollback:` line whose cited capture resolves under `evidence/rollback/`, is non-empty, has `## Captured output`, and has a `run_quiet` `.meta.json` sidecar with matching `capture_sha256` and `exit_code` 0. `--require-baseline` demands a `## Baseline`/`### Baseline` section with ≥3 `- <metric>: <value>` lines each citing an existing path under `evidence/baseline/`. `--repo` defaults to `.`. `--max-rehearsal-age-days` defaults to 30.
- **Rehearsal grammar** — `Time to Rollback: <N><unit> — rehearsed <YYYY-MM-DD> on <env> — evidence: <path>`; leading `#`/`>`/`-`/`*` tolerated; separators em dash, en dash or hyphen; unit ∈ `s|sec|secs|second|seconds|m|min|mins|minute|minutes` (normalized to `time_s`); the last matching line file-wide wins; fences stripped. Producer: `shipping-and-launch` → Rollback Rehearsal.
- **JSON keys** — `report_file`, `pass`, `verdict`, `require_go`, `has_rollback`, `has_checklist`, `checkbox_count`, `require_rehearsal`, `rehearsal` (`{present, time_s, rehearsed_on, env, evidence, sidecar_ok, age_days}`), `require_baseline`, `baseline` (`{present, metrics[{name,value,evidence,resolved}], evidenced_count}`), `max_rehearsal_age_days`, `problems` (`{code: [detail]}`), `failures`, `error`.
- **Problem codes** — `rehearsal_missing`, `rehearsal_unevidenced`, `rehearsal_stale`, `rehearsal_failed_exit`, `baseline_missing`, `baseline_unevidenced`.
- **Exit codes** — **0** structurally valid (and `GO` / rehearsed / baselined under the flags); **1** a gate failed; **2** usage error, missing/unreadable report, or structural non-conformance.
- **Self-test** — **47** cases. Depth (verdict grammar, last-section-wins, the rehearsal and baseline essays, fixtures): `references/check_ship_decision.md`.

## check_blockers.py

Makes the blockers-ledger gate machine-run: it reads `orchestrator-state.json`, normalizes every entry (legacy freeform string or structured object) to one shape, and exits non-zero when a blocker still stands. Used at `bgpdd-shipping` Step 0.5.

```bash
python check_blockers.py --state <path> [--milestone "<title>"] [--severity-floor Critical|Important|Info] [--ledger <path>]
python check_blockers.py --self-test
```

- **Blocker schema** — `{id, text, milestone, capability, severity, source, added, evidence}`. A legacy string normalizes to `{id: null, text, milestone: null, capability: null, severity: "Critical", source: null, added: null, evidence: null}` — unscoped and Critical, the fail-safe reading. Normalization never mutates the stored entry.
- **Flags** — `--milestone`: an entry blocks iff its `milestone` equals the title exactly (case/whitespace-insensitive) OR is `null` (unscoped still blocks — a **deliberate refinement** of the old "gate on all" rule, convention #8: exact equality on a structured field replaces a substring guess). Entries scoped elsewhere land in `other_milestone_blockers` and never block. `--severity-floor` defaults to `Important` (blocks Critical+Important, ignores Info). Without `--milestone`, legacy behavior is unchanged.
- **JSON keys** — `state_file`, `milestone`, `severity_floor`, `pass`, `blocker_count`, `blockers`, `blocking`, `other_milestone_blockers`, `pipeline`, `error`.
- **Exit codes** — **0** `blocking` is empty; **1** non-empty; **2** usage/structural failure.
- **Self-test** — **16** cases. Depth: `references/check_blockers.md`.

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
    [--add-blocker "<text>" [--blocker-milestone <title>] [--blocker-capability <name>] \
        [--blocker-severity Critical|Important|Info] [--blocker-source <name>] [--blocker-evidence <text>]] \
    [--resolve-blocker "<id-or-text-or-substring>" --evidence "<text>"] [--ledger <path>]
python update_state.py --self-test
```

- At least one action is required per invocation; any combination may be given in one call.
- **`--init --project-name <name>`**: creates the skeleton (`schema` `"1"`, `project_name`, `feature: null`, `pipeline: ""`, `branch: null`, `milestone_cursor: null`, `artifacts: {}`, `blockers: []`) if the file does not exist; a **no-op with a warning** if it does, while other actions in the same call still apply.
- **`--set-cursor` / `--set-pipeline` / `--set-branch` / `--set-feature`**: set those fields verbatim. The **literal string `null`** sets the JSON field to `null`.
- **`--set-artifact <name>=<path>`** (repeatable): merges into `artifacts`; the literal value `null` stores JSON `null`. A spec with no `=` is a usage error.
- **`--add-blocker "<text>"`** (repeatable): appends a structured entry (schema in `check_blockers.py` above) with auto id `B-<n>`, one past the highest currently present — a documented limitation: a resolved top id can be reused. The `--blocker-*` companions apply to **every** `--add-blocker` in the invocation; any of them given without `--add-blocker` is a usage error. Legacy entries are never rewritten.
- **`--resolve-blocker "<target>" --evidence "<text>"`**: matches an exact id, then exact text (removing all entries sharing it), then a unique substring (ambiguous → exit 2 with `candidates`). **`--evidence` is required and must be non-empty** — omitting it is a usage error, not a silent no-op. A target matching nothing warns and changes nothing. Every removal appends `<ts>\t<id>\t<full entry>\t<evidence>` to `blockers-resolved.log` beside the state file, and the ledger record gains `resolved_ids` and `resolved_entries`. Pipelines pass `--ledger` on this action.
- **Exit codes** — **0** the action(s) applied and the file was written; **2** usage/structural failure (missing `--state`, no action, `--init` without `--project-name`, `--resolve-blocker` without non-empty `--evidence`, an ambiguous resolve target, a `--blocker-*` companion without `--add-blocker`, a bad `--set-artifact` spec, a state file that is not a JSON object, or a missing state file without `--init`).
- **Self-test** — **29** cases. Depth (atomicity, the blocker-ledger rule this mechanizes, the schema migration): `references/update_state.md`.

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

## record_run.py

Appends one run-telemetry record per delegation completion and per state persistence to `.docs/{project-name}/implementation/run-log.jsonl`. The gate ledger records which gates fired; this records what the run cost — agent, model, duration, tokens, rounds. Orchestrator Contract §4 owns the obligation; this section owns the CLI.

```bash
python record_run.py --log <path> --pipeline <name> --phase <name> --event <delegation|gate|phase|note> \
    [--unit "<title>"] [--agent <name>] [--model <tier>] [--duration-s <float>] \
    [--tokens-in <int>] [--tokens-out <int>] [--tokens-total <int>] [--rounds <int>] \
    [--status <STATUS>] [--note "<text>"] [--from-json <file>]
python record_run.py --self-test
```

- **Flags** — `--log`, `--pipeline`, `--phase`, `--event` required. **`--model` is additionally required for `--event delegation`** (see below). `--status` ∈ `COMPLETE|PARTIAL|BLOCKED|PASS|FAIL|ERROR`. `--from-json <file>` maps a runtime completion payload; explicit flags override the payload.
- **Record** — `{"ts", "pipeline", "phase", "unit", "agent", "model", "event", "duration_s", "tokens_in", "tokens_out", "tokens_total", "rounds", "status", "note"}`.
- **`--model` is mandatory on a delegation record.** Measured finding: model choice left to prose decays — 17 dispatches in one audited wave silently inherited the most expensive tier, and the run log could not tell that apart from a deliberate choice because the field was simply null. A null there is **not** "not measured": the tier is always known at dispatch, so its absence records a decision nobody made (convention #9 — a restraint rule skipped at the moment the Orchestrator wants to proceed becomes a gate, not louder prose). Checked **after** `--from-json` merges, so a payload carrying `model` satisfies it. `gate`/`phase`/`note` events are unchanged — demanding a tier there would invite a fabrication.
- **Unknown is `null`, never `0`** (Evidence Integrity). An explicit `0` is preserved. `tokens_total` is derived only when both halves are known.
- **Exit codes** — **0** appended; **2** usage error (including a delegation with no model), a bad/unreadable `--from-json`, or an unwritable log. There is no exit 1. Unlike the best-effort ledger, a failed write is exit 2 — the record IS the artifact.
- **Self-test** — **19** cases. Depth (`--from-json` mapping table, the deliberately unmapped fields): `references/record_run.md`.

## summarize_run.py

The reader half of `record_run.py` and the mechanical form of the fired-versus-rubber-stamped metric. `--markdown` emits a paste-ready game-tape block.

```bash
python summarize_run.py --run-log <path> [--ledger <path>] [--unit "<title>"] [--markdown]
python summarize_run.py --self-test
```

- **Flags** — `--run-log` required. `--ledger` adds the gates section (omitted or unreadable → `null` + a warning, exit unchanged). `--unit` scopes records and ledger entries to one milestone/bug slug; null-milestone ledger entries fall out of a unit view by design.
- **JSON keys** — `run_log`, `ledger`, `unit_filter`, `records`, `malformed_lines`, `pipelines`, `units`, `agents`, `gates`, `warnings`, `error`. Each bucket carries `records`, `delegations`, `duration_s_total`, `duration_known_count`, `duration_unknown_count`, `tokens_total`, `tokens_unknown_count`, `rounds_max`, `rounds_recorded` (plus `duration_mean_s` for agents). `gates = {per_gate: {<name>: {runs, pass, fail, error, units}}, fired, rubber_stamped, inconclusive}`.
- **Classification** — `fired` = recorded a FAIL at least once; `rubber_stamped` = every verdict PASS; `inconclusive` = an ERROR but no FAIL. `rubber_stamped` is a **description, not a verdict** — input to the Incident Test, not its answer.
- **Exit codes** — **0** on any summary (an empty log and an absent ledger included); **2** missing `--run-log` or a file that cannot be opened. A malformed line is counted in `malformed_lines`, not fatal.
- **Self-test** — **14** cases. Depth (aggregation semantics, the third bucket's rationale, markdown shape): `references/summarize_run.md`.

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

## detect_stack.py

Walks a repository tree and reports evidence-backed technology stacks — `dotnet`, `vue3` (vue2 excluded even when other weak evidence is present), `react`, `angular`, `node`, `python`, `godot`, `powershell`, `docker`, `aws`, `azure`, `github-actions`, `playwright`, and the db stacks (`postgres`/`sqlserver`/`mysql`/`sqlite`) — so a stack-specific methodology skill's dependency-table row has a mechanical floor instead of resting solely on Iris's prose. It never guesses: a stack appears only with at least one relative evidence path (capped at 5).

```bash
python detect_stack.py --repo <dir> [--json|--markdown] [--max-depth N]
python detect_stack.py --self-test
```

- **Flags** — `--repo` required outside `--self-test`; `--json`/`--markdown` are mutually exclusive and default to JSON. `--max-depth` defaults to 6; `node_modules`, `bin`, `obj`, `.git`, `dist`, `.venv`, `__pycache__` are always skipped.
- **JSON keys** — `result`, `repo`, `stacks` (`{name, confidence: "high"|"medium", evidence}`), `skills` (dotnet→`dotnet-backend-patterns`, vue3→`vue3-spa-patterns`, godot→`godot-gdscript-patterns`, powershell→`powershell-script-patterns`, aws|azure→`cloud-deploy-patterns`, playwright→`playwright-skill`, any db→`database-migration-patterns`), `warnings`, `error`.
- **`--markdown`** prints a `## Stacks (detected)` block for `.docs/summary/context.md` (`bgpdd-discovery` Phase 1).
- **Exit codes** — **0** on a readable repo (an empty repo returns `stacks: []` plus a warning); **2** a missing or unreadable `--repo`.
- **Self-test** — **18** cases. Depth (vue3-vs-vue2 suppression, the confidence rule, db/cloud detection surfaces): `references/detect_stack.md`.
