# bgpdd-discovery — Rationale

Loaded on demand. Every rule this file explains lives, in its operative form, in `skills/bgpdd-discovery/SKILL.md`. Nothing here is a contract: if this file and the spine disagree, the spine wins.

---

## Why this pipeline is brownfield-only

This pipeline **reverse-engineers an existing system**. It is brownfield-only by construction: Iris scans a stack that exists, Scouts map fragments that exist, Echo derives a baseline from behavior that exists.

Pointed at an empty or greenfield repo, every agent returns a thin, confident, wrong artifact — and because those artifacts are Tier-1, they are durable, and the next three pipelines trust them. That is why Phase 0 halts rather than proceeding cautiously.

**Why the greenfield route loses nothing**: `/bgpdd-plan` already handles greenfield without a `.docs/summary/` knowledge base — its Pre-Flight Check skips straight to Phase 1 for a new project, and its Phase 3.6 authors the environment manifest on the greenfield route, which is the same manifest Phase 4b would have produced. Nothing is lost by skipping discovery; something is lost by running it.

**Why `detect_stack.py` is only a third disambiguator**: an empty detection (no evidence for any stack) supports treating the repo as greenfield but is not itself the fit-check answer — a partially-built repo can still show zero stack evidence in an empty `src/` dir.

---

## Why the Tier-1 provenance stamp exists

Tier 1 is durable and read months later by pipelines that have no way to tell a current map from a stale one. Without a stamp, a reader cannot distinguish a map derived from today's HEAD from one derived a year and four refactors ago, and there is no cheap check that would tell them.

**Why drift is a warning and never a halt**: an old map is usually still mostly right, and a hard failure would only teach people to skip Tier-1 entirely. The reader — not the pipeline — decides whether to trust the map or re-run discovery.

**Why this pipeline states the rule at all**: it produces the stamp, so the contract it offers downstream is its to declare. The consuming pipelines own their own end of it.

**Why the stamp is read at write time, never recalled**: the agent writing the file may have started its run several commits ago, and Echo may run against a later commit than Iris did — which is also why `overview.md`'s stamp is read fresh rather than copied from `context.md`.

---

## Why `runtime-environment.md` carries a content contract, not just an existence check

`runtime-environment.md` is the one artifact this pipeline produces that a *later* pipeline depends on to **start** anything. Existence alone is not enough: a recipe with no start command and no readiness check is a heading, and `/bgpdd-build` Phase 0 discovers that months later with no one left to ask.

**Why an unrecorded skip is worse than a recorded one**: an unrecorded skip is indistinguishable from an omission. A skip recorded as user-approved tells the next run that the gap is deliberate.

---

## Why Phase 4b is interactive and in the main session

Echo produced the material in Phase 4; this step turns it into a recipe *with the user*, and a delegated agent cannot pause to ask which device to test against.

**Why the recipe is durable**: recording how the feature is stood up locally, once, means no future build, verify, or bugfix run has to re-derive it at runtime. This is the brownfield entry point for the environment manifest; greenfield projects get theirs at `/bgpdd-plan` Phase 3.6, and a project with neither falls through to `/bgpdd-build` Phase 0.

**Why the smallest realistic scope is asked for explicitly**: the full-estate answer is the one people give by default, and it is the one that makes the recipe too expensive to follow. An icon fix should bring up the web app alone, not the whole estate.

**Why capabilities are inventoried but not preflighted here**: discovery is a mapping pipeline, and the estate a future run needs may not be installed on this machine today. The halt on a missing capability belongs to `/bgpdd-plan` Phase 3.6 and `/bgpdd-build` Phase 0, which know what is about to be built.

---

## Why the Scout fan-out is the canonical parallel case

One feature can span many APIs, and each Scout's assignment is genuinely independent — different files, different write target. This is the pipeline where launching in a single message matters most.

**Why Scouts never write a shared feature-level file**: several Scouts racing to write `overview.md` or `QA/code-workflow.md` lose each other's work silently. That synthesis is Echo's job in Phase 4, which serializes it by construction.

**Why incremental persistence matters acutely here**: discovery agents are research-heavy and accumulate many tool calls before they have anything to say, so a deferred first write costs the entire run.

---

## Why the detector is a floor Iris may raise but never lower

`detect_stack.py` is the mechanical floor a stack-specific methodology skill's "If the project uses X" dependency-table row checks against — a stack a scan can prove is never left to prose alone. Iris's judgment is the ceiling: she may ADD a stack she finds with her own evidence, labelled as her own finding, but removing a detected one would put prose back in charge of the decision the detector exists to make.

---

## Why `discovery-state.json` is discovery-private

It exists so a fresh session can tell which phase this run reached, not to carry state forward. This pipeline runs outside any epic and has no `orchestrator-state.json`; letting a downstream pipeline read this file would make a private resume hint into an inter-pipeline interface, which is what `orchestrator-state.json` is for.

---

## Why Phase 5 offers `/bgpdd-learn` instead of Forge

Discovery is global-tier and runs outside any epic — no `.docs/{project-name}/` exists, so there is no game tape to append to and no end-of-epic Forge run will ever see this session's evidence. The offer captures lessons while the session's evidence is still alive.
