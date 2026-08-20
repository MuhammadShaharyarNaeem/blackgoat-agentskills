# bgpdd-shipping — Rationale

Why the pipeline's less obvious rules exist. Load on demand; `SKILL.md` carries the rules themselves.

## Tier-1 refresh exception

`SKILL.md`'s Path Model makes `.docs/summary/` read-only for this pipeline with exactly one exception: Step 6.4 folds proven acceptance results back into `.docs/summary/{feature}/QA/manual-testing.md`.

Without that write, the baseline captures only how the system behaved before the *first* feature ever shipped. Every subsequent `/bgpdd-discovery` run re-derives it from scratch, and Alex's Baseline Reconciliation duty compares against a document that is progressively more wrong.

The exception refines the read-only rule rather than breaking it, because the write is narrow by construction: one file, once, after the launch squad is green, recording only behavior that was just verified. Anything weaker than "post-proof" would put unverified cases into a document the next discovery run trusts — which is why Step 6.4 excludes every `BLOCKED`, `NOT RUN`, and never-executed scenario.

## Runtime Smoke

`Pre-Merge Local Runtime Smoke` is the only item in Vera's Stage 1 assignment that requires a *started* application; the rest are satisfied by a built and linted codebase.

It is also the section that would have caught the 2026-08 response-envelope escape — a change that passed every in-process tier and shipped a wire shape no client could consume. (The incident is traced end to end in `{PLUGIN_ROOT}/runtime-evidence/references/runtime-evidence-rationale.md`.)

Dropping the section from the paste therefore does not merely shorten Vera's list: it silently returns the whole pipeline to build-and-lint verification, with the gate still reporting green.

## Ship-decision flags differ between a fresh run and a resume

The ship-decision file is both this pipeline's entry ticket (Step 0.4) and its exit ticket (Step 3), and Stage 2 Dep rewrites it in between. So the same path holds a *prep* verdict on a fresh run and an *exit* verdict on a resume.

Applying `--require-go` on resume would mean a legitimate `NO-GO` refresh blocks re-entry to Stage 2 — the only stage that can resolve it — and the pipeline could never converge on its own output. Hence: `--require-go` on a fresh run, shape-only on a resume.

## Stage 1 runs alone

Vera runs full builds and test suites, which take file, build-output, and port locks. Cipher's scanners and Dep's infrastructure verification against the same checkout collide with those locks and produce flaky failures — most visibly on Windows. Serializing Stage 1 costs one wait; parallelizing it costs a re-run plus the time spent misdiagnosing the flake.

## Why the Runtime Evidence Gate omits `--surface` and `--expect-status`

Both flags are per-capture, per-milestone assertions: one declared surface, one expected status code. An epic's captures legitimately span several milestones with different surfaces and different statuses, so no single value passed at shipping scope could hold across every capture it claims to cover — it would be wrong for some capture and would fail a re-run that is actually correct.

`--require-key` and `--forbid-host` survive the same scope change because they assert content that is meant to hold uniformly across the epic: the response envelope's keys, and the absence of shared dev/staging hosts.
