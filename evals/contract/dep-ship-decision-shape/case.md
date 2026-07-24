# Case: dep-ship-decision-shape

## Purpose
Guards against Dep producing a `ship-decision.md` the shipping pipeline can't gate on.
`bgpdd-build` Phase 5 and `bgpdd-shipping` both hinge on a single, unambiguous `GO` /
`NO-GO` verdict in this file — the Orchestrator reads it to decide whether to open the
PR and proceed with rollout, and the PR description links to it (per
`skills/bgpdd-shipping/SKILL.md` and `skills/shipping-and-launch/SKILL.md`). A decision
buried in prose, stated as both GO and NO-GO, or missing the rollback plan / launch
checklist it must accompany, forces a human to reconstruct the verdict by hand — exactly
the silent seam failure this suite exists to catch.

## Frozen Input
- Fixture dir: `fixture/` — a small already-built, already-tested `checkout-service`
  node app: `src/server.js` (an HTTP server exposing `/health` → 200), a passing
  `node:test` suite in `tests/`, `package.json` (`npm test` wired to `node --test`), and
  a stub `.docs/checkout-service/implementation/test-report.md` showing Quinn's tests
  passed. This gives Dep the finished, tested artifact his persona requires as input
  (`depends-on: mason, luna, quinn`). Dep does not implement or fix the app — he decides
  whether it is shippable and documents that decision.
- Copies to: `.` (the fixture root is copied straight onto the temp working copy's
  root, preserving its internal `.docs/checkout-service/implementation/` nesting).

## Command
Run from the temp working copy's root:

```powershell
claude -p "Act as Dep per agents/dep.md. The checkout-service app in this repo has passed tests (see .docs/checkout-service/implementation/test-report.md). Produce ONLY the shipping decision document at .docs/checkout-service/implementation/ship-decision.md — do NOT generate Dockerfiles, pipelines, or other infrastructure code for this task. The document must contain a Rollback Strategy section, a post-deploy Launch/Verification Checklist section, and end with a single explicit verdict line in the exact form 'Ship Decision: GO' or 'Ship Decision: NO-GO'." --permission-mode acceptEdits
```

## Pass Criteria (checked by `grade.ps1 -TargetDir <temp copy root>`)
1. `.docs/checkout-service/implementation/test-report.md` is present (fixture sanity
   check).
2. `.docs/checkout-service/implementation/ship-decision.md` was produced.
3. Exactly one verdict line is present resolving to `GO` or `NO-GO` (a labeled `Ship
   Decision` / `Verdict` / `Recommendation` line). Zero verdicts, or both a GO and a
   NO-GO verdict line, fails — the gate needs one unambiguous value.
4. A Rollback section is present (a heading containing "Rollback").
5. A post-deploy checklist section is present (a heading containing "Checklist", or at
   least three `- [ ]` checkbox items).

`grade.ps1` exits `0` only if all five pass; otherwise it exits `1` and prints which
criterion failed.

## Runs / Threshold
`runs=5`, pass threshold **4/5**.

## Future (not implemented)
Whether the GO/NO-GO verdict is the *correct* call for the artifact's actual readiness —
and whether the rollback steps would really work — is a judgment call outside what a
shape-checker can decide. This case only checks that the decision is present and
machine-readable, not that it is right. Not implemented here.
