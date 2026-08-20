# `bgpdd-build` — Rationale & Failure History

On-demand depth for `skills/bgpdd-build/SKILL.md`. Every normative rule lives in `SKILL.md`; this
file holds only the reasoning, failure histories, and divergence arguments behind them. Nothing here
is a rule — do not enforce from this file.

---

## The commit gate is machine-run

The commit gate's preconditions are artifacts a script reads off disk, not a judgement the
Orchestrator forms. There is no "commit now, the remaining finding is minor" — that judgement is
exactly what the gate exists to remove.

The prose rules that should already have prevented it were in force and did not: Orchestrator
Contract §4's *a terminal status is not evidence* and its append-only `blockers` ledger were both
binding during an observed run in which **three consecutive milestones were committed over standing
`Request changes` verdicts**. Nobody denied the rules; they were simply never converted into a file
you had to open. `check_commit_gate.py` is that conversion, completed — convention #9 in practice.

Because the script performs the commit itself on a pass, a skipped gate is *loud* (no commit exists)
rather than silent, which is the property a reporting-only checker could never have.

## Why the runtime gate runs twice

`bgpdd-build` runs `check_runtime_evidence.py` at Phase 2 step 4 and again, forwarded through the
commit gate, at §1. Phase 2 catches the gap early and cheaply, where a fix costs one rejection
round. The commit-time re-run exists because **that is the moment the restraint has to bind** — the
same reason `--verify-tree` runs there rather than only earlier.

This is also why every assertion flag must be repeated at commit time. A commit-time run with a
weaker assertion set makes the gate that actually owns the commit the more permissive of the two,
which inverts the whole point of running it twice. The commit gate forwards the flags to
`check_runtime_evidence.py` as a subprocess and folds its verdict into the pass
(contract: `pipeline-tools/SKILL.md`, *Runtime-evidence delegation*).

## The `blockers` array must be empty

A milestone commits only when the `blockers` array holds no standing entries at all — scoped to that
milestone or not. This is deliberately tighter than a scoped-only reading. The argument is
fail-safe: `blockers` entries are freeform text, so "not obviously this milestone's" is
indistinguishable from "not this milestone's". Gating on all of them can at worst cost a round of
triage; gating on a wrong scoping decision costs a shipped defect. `--ignore-unscoped` remains the
sanctioned override for the exceptional case where the distinction is genuinely known.

## The `[vs:ui]` skip at the Runtime Evidence Gate

`check_runtime_evidence.py` structurally requires a `## Captured output` JSON capture. A `[vs:ui]`
milestone's sanctioned evidence is *rendered* evidence — a screenshot or accessibility-tree read,
owned by `ui-design-patterns` — which that shape cannot produce. Skipping the gate for `[vs:ui]` is
therefore not a hole: the obligation moves to the commit gate's `--require-rendered-evidence` path,
which is the check that can actually read that evidence. `[vs:web+api]` keeps both obligations
because it genuinely carries API captures alongside its UI surface.

## Why `--require-openapi-reachable` is nearly free

The probe already recorded the contract document's URL and status while it was running, so the flag
costs nothing to add. What it buys is the check that forces the probe at a *real application* rather
than at anything that answers on a port — the document is typically served behind the same
environment branch an in-process host never resolves.

Per the user's stated split: the document proves the surface is up and its schema is served;
whether the response **body** is what was actually wanted is the Postman/newman assertion's job, and
`--require-key` is where that lands in this pipeline. The optional `--openapi-doc` trio only diffs
declared against observed property names, and an unresolvable schema warns rather than passing or
failing — so adding it can never manufacture a green.

## Phase 0 runs once per session

Phase 0's purpose is to establish that this squad can actually start and probe this system *before*
a round is spent discovering it cannot. On a microservice estate that means several services up and
repointed at each other locally, which no single milestone's `RUNTIME PROBE:` line describes on its
own — which is why the phase is per-session rather than per-milestone.

The gap ladder (request now, block at the evidence boundary) exists because halting on detection
wastes the one resource the situation gives you: the human can install Docker while the builder
works. The deferral is bounded by mechanism rather than memory — a milestone cannot close while any
`blockers` entry stands, so an un-cleared gap eventually stops the run on its own.

Preflight captures are quarantined under `evidence/preflight/` because they prove the estate starts,
not that any requirement is met. A preflight capture reachable by Phase 2's gate would be a
well-formed, fresh, entirely irrelevant green.

## The milestone is the unit of delegation

Fanning a milestone's tasks out to parallel builder agents is forbidden even when their
`Dependencies:` fields show no ordering constraint between them. Parallel builders committing to the
shared working branch move HEAD under their siblings, and every verification round then re-verifies
the whole moving diff instead of one task's changes — multiplying token cost for a wall-clock gain
this pipeline does not need. One builder builds; one Quinn/Luna round verifies the milestone's diff
once.

## Why the builder is pointed at a probe it already holds

The pasted milestone text already carries the `[vs:<surface>]` tag and the `RUNTIME PROBE:` line.
But a builder that is not *told* to look decides for itself whether a wire or rendered check
applies — the self-judged trigger the explicit quoting exists to remove. Quoting both into the brief
adds no gate: Phase 2's Runtime Evidence Gate still runs solely against Quinn's independent capture,
and the builder's own capture stays in `evidence/build/`, which no gate reads.

## Fix-verification before re-delegation

The `<fix_verification>` precondition is convention #9 in force. The builders' fix-round clause
(Mason §7, Nova §3) binds at the exact moment they want to hand back, which is the moment prose is
least likely to be remembered — so it is enforced instead by a field the Orchestrator must read
before the handoff can move forward.

Returning to the builder for a missing element deliberately does not consume one of the three
rounds: the bound caps fix *attempts*, and spending one on a missing report field is not what it is
for. A `NOT VERIFIED — <what blocked>` element is an honest answer and proceeds; a missing one is
not an answer at all.

## Remediation is a cycle, not a tail

The observed failure this rule exists to stop is Mason → Quinn → Luna → Mason-fix → **commit**,
where the fix itself was never tested and never reviewed. In that run, one such "fix" closed a
missing-route finding by adding the placeholder route the rule forbade — and it shipped, because the
verdict on the pre-fix code was carried forward onto post-fix code.

Hence: the fix re-enters at Phase 2, a fresh Luna re-reviews the remediation diff itself, and the
cycle exits only on `Approve` against the *current* diff. The reviewer is always fresh (the
Orchestrator Contract's independent-verification exemption) because a reviewer regaining context on
their own prior finding is anchoring, not recovery.

## Max is retired from Phase 4

Once Luna carried the `code-simplification` audit, Max's conditional trigger effectively never fired
— convergent redundancy. Phase 4 routes Suggestion-level simplification and sub-critical performance
findings to the milestone's builder instead. Max remains available for explicit ad-hoc optimization
requests via the agent-squad roster.

## The acceptance suite gate proves the wall, not the bricks

Everything above Phase 5 step 2.5 is per-milestone: each milestone proved its own bricks. The
acceptance suite is the only gate that proves the wall stands, because the journey is ordered and
stateful, and because **no milestone had a reason to exercise its own inverse** — the milestone that
added mapping never unmapped; the one that added install never uninstalled.

The "do not let Quinn invent the grammar" rules across step 2.5 (the result-line format, the matrix
itself) are the same principle as the `RUNTIME PROBE:` routing rule at Phase 2 step 1b: a grammar or
criterion authored by the agent it grades is not a contract. A feature with no declared walkthrough
is a feature nobody agreed on the meaning of "works" for.

## The ship-decision shape gate runs in this session

Checking the shape of Dep's `ship-decision.md` here — rather than leaving the first check to a fresh
`/bgpdd-shipping` session tomorrow — is the cheap-fix argument: the artifact's author is still warm,
the context still exists, and the round trip costs one follow-up instead of a whole session. It runs
deliberately **without** `--require-go` because a prep `NO-GO` is a legitimate, useful result at this
stage; the gate checks the decision's *shape*, not its content.

## Game-tape checkpoints fire per milestone

Phase 6 is numbered 6 only because it is described last. It is not an end-of-run phase: per
Orchestrator Contract §4, evidence checkpoints fire at every state persistence.

A checkpoint deferred to the end of the pipeline records nothing — the context that held the
evidence is long gone by then, and a run that never reaches its end leaves no record at all.
Milestones M1–M8 of a real epic ran with **zero** checkpoints for exactly this reason, so the
improvement run that followed had a fraction of the evidence it needed.

The "no pasted output, no claim" rule follows from the same incident. An exit criterion logged as
"observed" or "passed" with nothing showing it is worth *less* than an empty entry, because it looks
like evidence and will be read as evidence by an improvement run months later. Record what actually
happened, including your own mistakes — a checkpoint that only logs successes is a checkpoint that
has learned to lie.
