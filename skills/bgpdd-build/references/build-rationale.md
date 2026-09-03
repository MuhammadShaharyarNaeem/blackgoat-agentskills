# bgpdd-build — Rationale, Observed Failures & Examples

On-demand depth for `bgpdd-build/SKILL.md`. Nothing here is a contract: every rule this file explains is stated in the spine, and the spine wins on any apparent conflict. Read a section when you want to know *why* a rule is shaped the way it is, or when you are about to propose relaxing it.

## § Commit gate — why it is a script and not a judgement

The gate's preconditions are artifacts a script reads off disk, not a judgement you form. Phase 2 step 4 catches an evidence gap early and cheaply; the commit gate re-runs it at the moment of commit, because **that is the moment the restraint has to bind** — the same reason `--verify-tree` runs there rather than only earlier.

The ledger is what makes the re-run honest. It holds the argv and input hashes of the Phase 2 step 4 run, so a weaker commit-time re-run is *detectable* rather than silently the more permissive of the two. Without `--require-ledger-gates`, an Orchestrator that dropped `--require-key` on the second invocation would get a green that looked identical to a real one.

Exit 0 means the gate passed **and the commit exists** — the script performs the commit, so a skipped gate is loud (no commit) rather than silent.

**The observed failure this replaces.** The prose rules that should already have prevented a premature commit — Orchestrator Contract §4's *a terminal status is not evidence*, and the append-only `blockers` ledger — were in force during a run in which **three consecutive milestones were committed over standing `Request changes` verdicts**. Nobody denied the rules; they were simply never converted into a file you had to open. `check_commit_gate.py` is that conversion, completed. This is why there is no "commit now, the remaining finding is minor" path: that judgement is exactly what the gate exists to remove.

**Why blockers are scoped rather than counted.** The precondition was once "the `blockers` array must be empty". Scoping it to *this milestone plus everything unscoped* is deliberately looser (convention #8) and keeps the fail-safe exactly where it belongs: the writer who stated no scope gets the conservative reading. The alternative — guessing scope from the blocker's prose at commit time — is what writing the scope into a field at `--add-blocker` time exists to avoid.

## § `[vs:ui]` — why the two evidence gates are asymmetric

`check_runtime_evidence.py` structurally requires a `## Captured output` JSON capture. A `[vs:ui]` milestone's sanctioned evidence is **rendered** evidence — a screenshot or an accessibility-tree read, owned by `ui-design-patterns` — and that shape cannot produce a JSON capture. So the `[vs:ui]` obligation is discharged by the commit gate's `--require-rendered-evidence` instead, and forwarding `--require-runtime-evidence` to a gate that cannot accept its evidence would only manufacture an unpassable loop.

`[vs:web+api]` keeps both obligations because it genuinely has both: API captures alongside a UI surface.

The underlying rule behind `--require-rendered-evidence` is `ui-design-patterns`' *source can fail a check but never pass one* — which is why the review's cited paths must fall under `evidence/review/` (reviewer-owned) and why a builder's own self-verification screenshots under `evidence/build/` do not satisfy a reviewer's evidence duty.

## § Four separate evidence paths, and why none of them may be merged

| Path | Written by | Gated by |
| --- | --- | --- |
| `evidence/preflight/` | Orchestrator, Phase 0 step 3 | nothing — proves the estate starts, not that a requirement is met |
| `evidence/build/` | the builder, Phase 1 step 3 (self-check) | nothing — adds no gate |
| `evidence/runtime/` | Quinn, Phase 2 step 1b | `check_runtime_evidence.py` |
| `evidence/review/` | Luna, Phase 3 step 2 (design critique) | `check_commit_gate.py --require-rendered-evidence` |

Preflight captures must never be reachable by Phase 2's gate: they were produced before any requirement existed to prove. A builder's self-check must never be reachable either — a probe run by the agent being graded is not a criterion. The separation is the whole mechanism; collapsing any two of these paths silently converts a self-report into a verdict.

## § Phase 0 — why it runs once per session, not once per milestone

Its purpose is to establish that this squad can actually start and probe this system *before* a round is spent discovering it cannot. On a microservice estate that means several services up and repointed at each other locally, which no single milestone's `RUNTIME PROBE:` line describes on its own.

A capability gap is requested immediately and blocks at the **evidence boundary**, not at Phase 1 — the user can install while the builder works. What makes the deferral bounded rather than merely optimistic is §1's rule that a milestone may not be marked `[x]` while a blocker scoped to it, or scoped to nothing, still stands. The one gap that still halts immediately is one that blocks the *building* rather than the verifying (a schema you cannot inspect, a package feed you cannot reach, a compile-time credential): there is no parallel work to overlap, so nothing is gained by deferring.

`--blocker-capability` exists so the resolve step can name the same capability it requested instead of re-matching prose; resolving by **id** rather than by a substring of the text is what stops two gaps that share a word from becoming exit 2.

## § Why one builder per milestone, never parallel builders per task

Parallel builders committing to the shared working branch move HEAD under their siblings, and every verification round then re-verifies the whole moving diff instead of one task's changes — multiplying token cost for a wall-clock gain the pipeline does not need. One builder builds; one Quinn/Luna round verifies the milestone's diff once. This holds even when the tasks' `Dependencies:` fields show no ordering constraint between them.

## § Small justifications relocated out of the spine

Each of these explains a spine rule without changing it.

- **`next_milestone.py` over a full-plan read** — the script returns the pending milestone, its domain, its task block and the stale verdict, replacing a ~73k-token full-plan read with roughly 2K.
- **`mark_milestone.py` over a hand edit** — editing the `[x]` onto the heading yourself is the exact failure mode the script replaces; the `[x]` used to be three typed characters.
- **`run_quiet.py` in every builder/tester brief** — the full log lands on disk and only errors-with-context enter the agent's transcript, which is what keeps a long suite from eating the delegation's context.
- **Preflight's minimal subset** — a UI-only epic brings up the web app, not eight services.
- **Why Phase 2 must not run against a missing capability** — Phase 2 is where evidence is produced, and an unrunnable estate makes every gate lie in the same direction.
- **Why the manifest is persisted as an artifact (Phase 0 step 5b)** — shipping's Vera brief starts the application too, and re-deriving these facts in a fresh session is how one service ends up left pointing at dev.
- **Why an all-`[vs:none]` plan is recorded rather than waved through** — a plan with no verifiable surface anywhere is itself worth a second look.
- **`--require-openapi-reachable` costs nothing** — the probe already recorded the document's URL and status while it was running.
- **Blast-radius tracing** — if a `code-review-graph` MCP server happens to be available (it is not wired in this plugin's `.mcp.json`), its impact tool may be used instead of a codebase search.
- **The `<fix_verification>` precondition** — the builders' fix-round clause binds at the exact moment they want to hand back, so it is enforced by a field the Orchestrator must read rather than by prose they must remember.
- **`summarize_run.py --markdown`** — the block carries the milestone's tokens, duration, rounds and the fired-versus-rubber-stamped classification of every gate scoped to it.

## § Why `--emit-gate-args` exists

Phase 2 step 4 used to require hand-transcribing `surface`, `expect_status`, `require_keys` and `forbid_hosts` out of prose at the moment you were most impatient to run the gate. Convention #9: the transcription is now done by the script that already read the `RUNTIME PROBE:` line.

The same principle governs stack-skill resolution. Which stack contract a builder loads was decided by an `If the project uses X` row read by the agent that benefits from skipping it, so the Orchestrator resolves it mechanically and hands it over instead. A stack the detector reports and the brief names is a dependency-table row the agent can no longer decide for itself.

## § Luna's sixth axis

Phase 4 is conditional on Suggestion-level findings, and the code-simplification audit is its one guaranteed producer. Without the axis, Phase 4's trigger depends on whichever finding a reviewer happens to volunteer — which is why the sixth axis is a deliberate refinement of `code-review-and-quality`'s five (convention #8), not a miscount of them.

**Max is retired from this pipeline** for the mirror-image reason: once Luna carried the `code-simplification` audit, his conditional trigger effectively never fired (convergent redundancy). He remains available for explicit ad-hoc optimization requests via the agent-squad roster.

## § Why remediation is a cycle, not a tail

The observed failure this exists to stop is Mason → Quinn → Luna → Mason-fix → **commit**, where the fix itself was never tested and never reviewed, and where one such "fix" closed a missing-route finding by adding the placeholder route the rule forbade.

Hence: the builder's fix re-enters at Phase 2 (same spawned Quinn, as a follow-up), then Phase 3 with **a fresh Luna** reviewing the remediation diff itself. The reviewer is always fresh per the Orchestrator Contract's independent-verification exemption — a context that missed a flaw once is primed to miss it again.

## § Why the acceptance suite is a separate gate

Everything above Phase 5 step 2.5 is per-milestone: each milestone proved its own bricks. This is the only gate that proves the wall stands, because the journey is ordered and stateful and because **no milestone had a reason to exercise its own inverse** — the milestone that added mapping never unmapped, the one that added install never uninstalled.

`--changed-files` is deliberately omitted here (convention #8, refining `pipeline-tools`' freshness rule rather than contradicting it): the results file is produced by the Quinn delegation immediately before the gate, so freshness holds by construction. `bgpdd-shipping`'s later re-execution is the one call site where staleness is possible, and that is where the flag is passed.

The ship-decision shape gate runs `check_ship_decision.py` deliberately **without** `--require-go`: a prep `NO-GO` is a legitimate, useful result at this point, and the gate checks the decision's *shape*, not its content. It runs in THIS session, while the artifact can still be fixed cheaply, rather than leaving the first check to a fresh `/bgpdd-shipping` session tomorrow.

## § Phase 6 — why the checkpoint fires per milestone

A checkpoint deferred to the end of the pipeline records nothing: the context that held the evidence is long gone by then, and a run that never reaches its end leaves no record at all. **Milestones M1–M8 of a real epic ran with zero checkpoints for exactly this reason**, so the improvement run that followed had a fraction of the evidence it needed.

The 3–6 bullets *per milestone* cap is a deliberate refinement of the skeleton's default once-per-run, at-most-10 cap (convention #8): the sibling pipelines check in once, this one checks in on every milestone close, so a per-run cap would shrink an eight-milestone epic's record to the size of a single lite run's.

`summarize_run.py --markdown` is convention #9 in force on the same section: the cost sentence used to be written at the moment you were least able to check it, so the table is now produced by the tool that read the log.

## § Few-shot handoff example (non-auto mode phase transition)

When communicating with the user at a phase-transition checkpoint:

> Phase 3 (Review) is complete. Luna found no critical issues, and the report is saved to `.docs/my-app/implementation/review-report.md`.
> **Blockers**: None.
> **Next Step**: Are you ready to proceed to Phase 4 (Optimization) (builder follow-up)?

Crisp, action-oriented: what completed, where the artifact landed, what blocks, what is next.
