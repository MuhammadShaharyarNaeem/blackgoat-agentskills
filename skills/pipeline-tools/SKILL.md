---
name: pipeline-tools
description: "Stdlib-Python CLIs turning the bgpdd pipelines' prose gates into commands with exit codes. Each script's own `--help` is its contract of record; `tool_registry.py` (list, show, for, --verify) routes to it. This file holds only the contracts shared across the family. Orchestrator-run, except the self-gating captures and lints an agent runs on its own output."
---

# pipeline-tools

A family of pure-stdlib Python 3 CLIs under `scripts/` that convert the bgpdd pipelines' prose gates into commands with exit codes. The Orchestrator runs them directly via a shell action, and there is no manual open-and-read substitute for any of them.

**Each script's own `--help` is its contract of record**, and `tool_registry.py` routes to it — see § Using the registry, below. This file carries only what is shared across the whole family: who may run which, the gate ledger, the capture sidecar, and the parsing rules every gate applies. Rationale, observed-failure narratives, parsing grammars, scope-limit essays and self-test inventories live in `references/<script-name>.md` and are loaded on demand.

**Who may run which — a labelled carve-out from this file's own "never delegated to an agent" rule (convention #8).** That rule was written absolutely and is false as written: `base-persona.md` § Command Timeout Discipline (Anti-Hang) instructs *every* agent to wrap its commands in `run_quiet.py --log`, `agents/cipher.md` and `agents/vera.md` instruct their agents to take each check through `run_quiet.py --capture`, and `api-contract-evolution/SKILL.md` § Verification has its loading agent run `check_openapi_diff.py`. The rule the divergence refines is the real one, which is about *authority*, not about scripts:

- **Orchestrator-only — the commit, ship and close gates.** `check_commit_gate.py`, `check_ship_decision.py`, `check_quick_close.py`, `check_batch_close.py`, `mark_milestone.py`, `update_state.py`, `next_milestone.py`. These decide whether work is done, land commits, and move pipeline state. A subagent running one is grading its own submission, and Orchestrator Contract §4 owns their invocation. The same holds for every other gate a pipeline step names as the Orchestrator's — `check_test_authenticity.py`, `check_runtime_recipe.py`, `check_coverage.py`, `check_agent_report.py`, `check_runtime_evidence.py`, `check_handoff.py`, `check_redelegation.py`, `check_ledger.py` and the rest: the reader of an agent's output is never that agent.
- **Permitted and expected — self-gating captures and lints the producing agent runs on its OWN output, before it hands anything back.** `run_quiet.py` (both `--log`, which is mandatory for every command an agent runs, and `--capture`, which is how Cipher and Vera evidence a check line) and `check_openapi_diff.py` on the contract document the agent just changed. An agent running these is doing its own work properly, not adjudicating it; the gate that reads the result still runs in the main session.

Anything not in the second list is Orchestrator-run. A persona that needs to run something else names it in its own file and says why. `tool_registry.py for --agent <name>` answers this question per agent, with the reason each carve-out exists.

## Using the registry

`tool_registry.py` is the router; each script's own `--help` is its contract of record. **Per convention #8 this deliberately refines CLAUDE.md convention #1**: for this skill the per-script contract lives in the script, not in the spine. It is not a shadow contract — there is exactly one contract per script, it is executable, and it therefore cannot describe a flag the script does not have. Depth: `references/tool_registry.md`.

The commands, run from `scripts/`:

- `python tool_registry.py list` — every tool, name and one-line purpose.
- `python tool_registry.py show check_agent_report` — the registry entry, then that script's `--help` verbatim. **This is how an agent reads a contract.** Reading the source instead is denied by `guard_action.py` rule 8 inside an active lane.
- `python tool_registry.py for --agent cipher` — the tools that agent may run, each carrying the reason its carve-out exists (the rule is § Single contract authority's, above).
- `python tool_registry.py for --lane bgpdd-quick` — the tools that lane's steps invoke.
- `python tool_registry.py --verify` — the mechanical gate over the contract's SHAPE (convention #9, replacing a prose rule about what a contract section must contain): every registered script exists, every script in `scripts/` is registered, each registry description is that help's own first line, and each help carries its mandatory headings.

## Single contract authority

The pipeline gates — `bgpdd-plan` Phase 3.5, `bgpdd-lite` Phase 2.5, `bgpdd-build` Phase 2 and Phase 5, `bgpdd-verify` Phase 3, `bgpdd-secure` Phase 1 and Phase 3, `bgpdd-shipping` Steps 0.3–3.5, and `bgpdd-bugfix`, `bgpdd-quick` — reference this file as the single source of truth for the contracts below, and each script's `--help` for its own. They do not restate the rules inline; update them here only. The file therefore stays at this path: fourteen files across the pipelines, the personas and the sibling skills cite it by name.

## Gate ledger

Every gate in this family accepts `--ledger <path>` and appends **exactly one JSON line per run, on every exit path** (creating parent directories):

```json
{"ts": "<ISO-8601 UTC>", "gate": "<script basename>", "argv": ["..."], "milestone": "<--milestone value or null>", "inputs": {"<path as given; a cited capture is keyed by its resolved path relative to the cwd>": "<sha256 hex or null>"}, "verdict": "PASS|FAIL|ERROR", "exit": 0, "prev": "<sha256 of the previous line, or \"genesis\">", "self": "<sha256 of this record without `self`>"}
```

`inputs` carries every file path argument the script read. `verdict` maps exit 0/1/2 to PASS/FAIL/ERROR. Writing the ledger is **best-effort**: a ledger that cannot be written never changes the gate's own verdict — it is an audit trail for LATER gates, not a term in this one. `update_state.py --resolve-blocker` additionally records `"action": "resolve-blocker"` and `"evidence": "<the raw --evidence value>"`, plus, once it resolves, `"evidence_resolved"` (the path, state-dir-relative) and `"evidence_sha256"`. `--evidence` must now resolve to an existing, non-empty file (state directory first, then the CWD) or the call exits 1 with nothing written — "trust me" is a syntactically valid but nonexistent path, refused like any other typo, not merely recorded as unverifiable prose. `record_run.py --allow-tier-inversion` adds `"tier_inversion_reason"` to the RUN LOG record (not the ledger — that script is not a gate).

**`run_quiet.py --capture --ledger` writes a record too, and it is not a gate verdict.** Its `verdict` is `CAPTURED` (never PASS/FAIL/ERROR), its `exit` is the CHILD command's exit code, its `inputs` are the capture and its `.meta.json` sidecar, and it carries two extra chained fields: `command_argv` (the child argv) and **`capture_sha256`** — the artifact's hash as it landed on disk. That last field is the lookup key three readers use (`--require-ledgered-captures`, below): it is what distinguishes a capture the tool RECORDED from a self-consistent pair somebody authored.

### The chain: `prev` and `self`

The ledger is the evidence four gates read a verdict out of, and until it was chained it was a text file anybody could retype. Every record therefore carries two hashes, written by the same byte-identical helper in all fourteen gates:

- **`prev`** — sha256 of the **previous line's bytes**, stripped of its terminator and surrounding whitespace (so a CRLF ledger written on Windows chains identically to the same file read on POSIX). `"genesis"` when the ledger is missing or holds no non-blank line yet.
- **`self`** — sha256 of this record **serialized canonically without its own `self`**: `json.dumps(record_without_self, sort_keys=True, separators=(",", ":"))`, UTF-8. Key order in the written line is therefore not content; the line's own bytes still feed the next record's `prev`.

Both are computed at write time, after any `extra` fields are merged, so every field in the record is covered.

**What this buys, and the limit that stays.** A single record edited, inserted or removed after the fact is now visible: the edited line fails its own `self`, and an inserted or removed one fails the following line's `prev`. What it does **not** buy — deliberately, and this limit is accepted rather than papered over — is protection against a forger who rewrites the **entire tail** consistently, recomputing every `prev` and `self` from the edit point onward. There is no external anchor (no signature, no notary), so the chain detects tampering that is *local*, not tampering that is *thorough*. Truncating trailing records is undetectable for the same reason. The change is that casual edits stop being free, not that the ledger becomes unforgeable.

**Migration.** A record written before this contract carries neither field. Such **legacy records are tolerated only before the first chained record** — a pre-chain ledger migrates forward by simply being appended to. Once a chained record exists, an unchained one after it is a refusal: reverting to unchained is exactly what deleting the chain looks like. **Any gate that appends to a shared ledger must therefore chain**; a new gate that copies the old unchained `append_ledger` will break every chained ledger it touches.

**The chain verifier is `check_ledger.py`.** It walks the chain and reports the first broken link, and — a deliberate divergence (convention #8) from "every gate carries `--ledger`" — it is the one script here that writes nothing: `--ledger` is its subject under test, not an append target, and appending its own record would extend the chain it is reporting on. Contract: `python tool_registry.py show check_ledger`. Depth: `references/check_ledger.md`. The gates that read a verdict out of a ledger — `check_commit_gate.py --require-ledger-gates`, `check_ship_decision.py --require-ledger-gates`, `mark_milestone.py --require-gates` — verify the chain **before** looking at any verdict and fail with `ledger_chain_broken`. A PASS read out of a tampered ledger is not a weaker PASS; it is no PASS.

Carrying `--ledger` (and therefore chaining): `check_commit_gate.py`, `check_quick_close.py`, `check_batch_close.py`, `check_agent_report.py`, `check_acceptance_suite.py`, `check_ship_decision.py`, `check_coverage.py`, `check_blockers.py`, `check_runtime_evidence.py`, `check_bugfix_intake.py`, `check_red_green.py`, `next_bugfix_route.py`, `update_state.py`, `mark_milestone.py`, and — a **deliberate divergence from "every gate carries `--ledger`"** (convention #8), because it is a *writer*, not a gate — `run_quiet.py --capture`. `next_milestone.py` and `summarize_run.py` READ the ledger but never write it; `next_bugfix_route.py` both reads and writes it (it refuses to route without a recorded intake PASS). `record_run.py` carries no `--ledger` flag at all — it is not a gate; it writes the other durable record, the run log. The pipelines pass `--ledger .docs/{project-name}/implementation/gates.jsonl` on every gate invocation (Orchestrator Contract §4), `check_openapi_diff.py`, `check_always_on.py`, `check_handoff.py`, `check_redelegation.py`, `check_tier1_provenance.py`, `check_runtime_recipe.py`.

## The capture sidecar, and why the body witnesses it

`run_quiet.py --capture <path>` writes two files: the capture artifact and `<path>.meta.json`, the machine-owned sidecar. Four gates read that sidecar — `check_runtime_evidence.py`, `check_red_green.py`, `check_quick_close.py`, `check_ship_decision.py` — and one more reads it per check line (`check_agent_report.py`).

**`capture_sha256` protects the capture FILE's bytes. Nothing protects the sidecar's own fields.** So the hash-checked body is the *witness* and the sidecar is the *claim under test*: editing the sidecar alone — `exit_code` 3 → 0, or `finished` pushed forward to defeat a freshness or ordering check — left every hash intact and every gate green. Every gate that reads a sidecar's `exit_code` or `finished` therefore compares them against the capture's own header lines:

- the body's `- Exit code: <N>` must equal the sidecar's `exit_code`;
- the body's `- Captured: <ts>` must equal the sidecar's `finished`, which is the instant `run_quiet.py` now stamps it **from**. The comparison allows a **one-sided 0–2 second window** (never earlier than `finished`), solely so a capture written by the pre-2.4 build path — which called `now()` again while rendering, landing 0–1s after `finished` — is not accused of forgery. A stamp moved to fake freshness or backdate a run moves it far outside the window.

Header lines are read from the region **before** `## Captured output`, with fences blanked: a probe or test runner that prints `- Exit code: 0` supplies nothing.

Problem codes, identical in every gate: **`sidecar_body_disagrees`** (they disagree) and **`capture_header_missing`** (the capture carries no readable header pair, so the sidecar is unwitnessed). `run_quiet.py` re-checks the agreement at write time, so this tool family can never be the source of a failing pair.

**Migration**: a capture written before this contract — no `- Exit code:` / `- Captured:` header pair, or a sidecar whose `finished` is more than 2s from the body — fails closed. Re-take the probe with `run_quiet.py --capture`. There is deliberately **no waiver flag** for this (convention #8, tighter than `--allow-missing-sidecar`, which waives sidecar *absence*): a present-but-disagreeing sidecar is the exact forgery this check exists for, and re-taking a capture is cheap.

### The unkeyed-sidecar limit: one forger, seven gates

The agreement check above raises the cost of editing a sidecar. It does not make a capture unforgeable, and the size of that gap is stated here rather than only in `references/check_red_green.md`, because it is a property of the FAMILY, not of one gate.

Every field `run_quiet.py` writes — `argv`, `cwd`, `host`, `pid`, `started`, `finished`, `exit_code` — is typeable, and both hashes are unkeyed SHA-256 over content anyone can produce. There is no nonce, no key and no monotonic anchor, so a ~40-line stdlib script writes a self-consistent capture + sidecar pair for a command that never ran: the body matches the header, the header matches the sidecar, the sidecar's `capture_sha256` matches the file. **The blast radius of that one script is seven gates** — `check_runtime_evidence.py`, `check_red_green.py`, `check_quick_close.py`, `check_agent_report.py`, `check_ship_decision.py`, and, through their ledger records, `check_commit_gate.py --require-ledger-gates` and `mark_milestone.py --require-gates`. A commit gate run with every hardening flag on has been shown to exit 0 and commit over a wholly fabricated evidence base built this way.

**This is accepted, not overlooked, and the honest framing is what the family buys**: a forgery is now a WRITTEN ACT rather than an omission — somebody has to author artifacts that hang together, and the ledger keeps them attributable. Closing it needs a secret the runtime does not have (a keyed MAC, or an external notary), so no flag here pretends to. Related, and equally accepted: `record_run.py`'s run log is authored too, so `check_commit_gate.py --require-agents` proves a delegation record exists, not that the delegation happened (`--require-ledger-gates` is the flag that re-hashes); and `check_ledger.py` detects a LOCAL edit, not a thoroughly rewritten tail.

### `--require-ledgered-captures`: the capture must also have been RECORDED

The gap above stayed exactly that size while no reader asked *where the pair came from*. `run_quiet.py --capture --ledger` now appends one chained record per capture, pinning that capture's `capture_sha256`, and three readers look the artifact up in it:

- **Who reads it** — `check_agent_report.py` (each cited check-line capture), `check_runtime_evidence.py` (each cited runtime capture), `check_ship_decision.py` (the rehearsal capture and every baseline reading). Each takes the flag `--require-ledgered-captures`, which **requires `--ledger`** (exit 2 otherwise).
- **The lookup** — the artifact's CURRENT sha256 must appear as the `capture_sha256` of some `gate: "run_quiet.py"` record in that ledger. Because it is the current hash, an edit after recording un-ledgers the artifact as surely as it breaks the sidecar.
- **Warn, then fail — a one-release grace, and a DELIBERATE divergence (convention #8) from this family's fail-closed default.** With `--ledger` and no `--require-ledgered-captures`, an artifact no record pins emits the warning line `unledgered_capture: <path>` and the exit code is **unchanged**. With the flag, it is problem code **`unledgered_capture`** and a failure. Without `--ledger` the lookup does not happen at all, so every existing invocation behaves exactly as before.
- **Not chain integrity** — a record inside a broken chain still counts here. `check_ledger.py` owns the chain, and `--require-ledger-gates` re-walks it at commit time; duplicating that check in five places would make one broken ledger report five different problems.
- **Migration** — captures taken before this release carry no ledger record, so every one of them warns. Re-take a check or probe with `run_quiet.py --capture <path> --ledger <the ledger> -- <command>` to earn one. The pipelines should pass `--require-ledgered-captures` once their captures are all taken with `--ledger`.
- **What it still does not buy** — the ledger is unkeyed too, so a forger who also appends a chained line still passes. It raises the cost from "write two files" to "write two files and extend a hash chain that `check_ledger.py` walks", which is a larger written act, not an impossible one.

## Fenced blocks and encoding

Every verdict/status parser blanks fenced regions (three backticks or three tildes) before parsing, preserving line count, and every file read uses `utf-8-sig`. A verdict or status token inside a fence is a TEMPLATE or a captured transcript, never an assertion — and because these parsers resolve latest-mention-wins, a pasted example silently overrode the real verdict. A BOM previously made a valid report exit 2. `check_coverage.py`'s plan and design modes are the labelled exception (convention #8) — see `references/check_coverage.md`.
