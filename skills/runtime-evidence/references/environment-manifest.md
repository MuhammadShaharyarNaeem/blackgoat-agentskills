# The Environment Manifest — authoring contract

This is the **authoring** half of `SKILL.md` § *The Environment Manifest*: the block-by-block
format, the three entry points and their precedence, how to select the minimal bring-up subset,
and the ledger mechanics of a missing-capability blocker.

**Audience: the Orchestrator, in the main session.** Three pipeline steps cite this file as their
format authority — `/bgpdd-discovery` Phase 4b, `/bgpdd-plan` Phase 3.6, and `/bgpdd-build`
Phase 0 — and each of them writes the manifest *with the user*. **No delegated agent authors this
file or fills a gap in it**; that rule is in the spine, and it is why this half lives here rather
than on every verifying agent's wake-up path.

## The blocks

The facts that make a probe runnable are **caller-supplied**. A manifest carries these six blocks,
under these headings — `check_runtime_recipe.py` asserts all six are present and that *Services*
is filled with at least one start command and one readiness check:

| Block | What it records |
|-------|-----------------|
| **Bring-up sequence** | The **ordered** steps that take this feature from a clean checkout to a probeable system — and not only "start service X". A step is any action the sequence depends on: build a plugin project, copy its output into a host's plugin directory, install or register an agent, run a one-off function, connect one service to another. Number them; a step that must follow another is why this block is a list and the others are tables. Each step also declares **`Needed for`** — the surfaces or change-scopes that require it (see *The minimal subset* below) |
| **Services** | Per service: name, start command, local base URL, the readiness check that proves it answers, and which other services it calls |
| **Repointing map** | Every config key that must move off a shared host onto a local URL — the file or env var, the owning service, the value it ships with, the value it must hold locally |
| **Forbidden hosts** | The shared dev/staging host patterns that must never appear in a capture (these become the gate's `--forbid-host` arguments) |
| **Test identities & fixtures** | The concrete subjects a run acts on: the login username and where its password comes from, the target device/machine names as they appear in the product's own list (e.g. a device `auriga-90`), tenant/account/org ids, seeded records. **Never the password itself** — name its source |
| **Capabilities** | What the verifying agent must actually possess for the surfaces in play: an out-of-process HTTP client, browser automation, a DB/queue/cache client, device or agent access, a Python 3 interpreter |

## Three entry points, one grammar, explicit precedence

The blocks are written by whoever first has the facts. Exactly one file is authoritative for a run:

| Written by | Path | When |
|------------|------|------|
| `/bgpdd-discovery` Phase 4b (Orchestrator + user) | `.docs/summary/{feature}/QA/runtime-environment.md` | **Brownfield.** Tier 1, durable, per feature — a recipe that was true last month and will be true next month. **Prefer it whenever it exists** |
| `/bgpdd-plan` Phase 3.6 (Orchestrator + user) | `.docs/{project-name}/implementation/environment-manifest.md` | **Greenfield.** Nothing exists to discover, so the Orchestrator **derives** the intended estate from the design and plan it just produced — it knows what services it is about to build and what surfaces it tagged — presents that as a proposal, and asks the user only for what the artifacts cannot say: credentials' source, machine and device names, anything local to this developer |
| `/bgpdd-build` Phase 0 (Orchestrator + user) | same Tier-2 path | Neither ran (e.g. a `/bgpdd-lite` epic), or a run-local delta must be recorded against a Tier-1 recipe |

A Tier-2 file standing alongside a Tier-1 recipe carries **deltas only** — each naming what it
overrides. Never a silent second copy.

## The minimal subset

**Run the minimal subset, and record which subset you ran.** The manifest describes the *whole*
estate a feature can need; a given change almost never needs all of it. An icon fix needs the web
app. An API fix needs the API and whatever exercises it. A device-agent change needs the
build → copy → run → pair chain and a target machine. Select the smallest set of bring-up steps
whose `Needed for` covers the milestone's `[vs:<surface>]` tag, run those, and **name the subset in
the capture's `Environment` field** — the reviewer needs to know a claim was made against three
services and not eight. A step you skipped is a scoping decision; a step you skipped silently is an
unstated assumption about what the claim covers.

## Ledger mechanics of a missing capability

The spine states the rule: ask now, keep working, and stop at the first step that needs it. These
are the mechanics that keep the deferral honest.

1. **Record the request as a blocker in the same breath** (`update_state.py --add-blocker`). The
   request is what parallelizes the wait; the blocker is what keeps the deferral honest. Never one
   without the other — a request with no blocker is a note that gets forgotten by the third
   milestone.
2. **The blocker clears only on evidence** that the capability now works — `--resolve-blocker`
   requires it, and the exercise-it-once check is what to cite. Since a milestone cannot close while
   any blocker stands, the deferral is bounded by a mechanism rather than by anyone remembering it.

What each stage checks differs, and the divergence is deliberate (**convention #8**): planning
checks *capabilities* only — greenfield services do not exist yet and brownfield ones are build's to
start — while build checks capabilities **and** starts the services, because by then they are real.
Neither stage halts on detection; both route through the ledger above.
