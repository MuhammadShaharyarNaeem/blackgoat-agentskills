# Case: openapi-diff-adversarial

## What this proves

An adversarial eval for `check_openapi_diff.py`, the gate that makes
`api-contract-evolution`'s central rule — additive-only inside a major version —
something that has to be *run* rather than asserted (convention #9).

The gate ships a 38-case `--self-test` which proves each predicate in-process
against synthetic fixtures. This case proves the four things that self-test
structurally cannot:

- **It refuses a fabricated contract change when invoked as a SUBPROCESS**, the way
  `bgpdd-build/references/build-gate-ladders.md` § 6b and `bgpdd-shipping` Step 3
  invoke it: real files on disk, a real ledger, and the exit code plus the naming
  `kind` read back off stdout. A self-test asserting `build_report()` in-process
  proves the predicate, not the CLI contract the pipelines call.
- **Every additive near-miss stays green.** Four steps (1–4, 13) pair with a breaking
  step that differs by one field: an optional parameter against a required one, a
  widened enum against a narrowed one, an added field against a removed one. A gate
  that flags everything passes a suite of only-breaking cases and is useless in
  practice — those pairs are what makes the seven positives mean something.
- **The waiver's floor holds.** `--allow-breaking ""` and `--allow-breaking "   "`
  are exit 2, not silent passes, and a *reasoned* waiver's text lands in the ledger
  record as `allow_breaking_reason` alongside `breaking_kinds`. The flag buys
  durability, not verification (`skills/pipeline-tools/SKILL.md`), so the only thing
  worth asserting about it is that the reason survives to the record — step 19.
- **Its ledger records are a chain a hand edit breaks.** Until 2.6.1
  `check_openapi_diff.py` was absent from `check_ledger.py`'s `CHAINED_GATES`
  drift-guard list -- a missing comma had concatenated its name onto
  `update_state.py`'s, silently dropping both -- so nothing else in the tree
  asserted that its `append_ledger` actually chains. The list is fixed and two
  new `check_ledger.py` cases guard it; these steps remain the end-to-end half.
  Steps 21–23 do it end to end: the 17 records it wrote verify intact; a recorded
  `FAIL` hand-edited to `PASS` — the exact forgery that would make a downstream
  `--require-ledger-gates check_openapi_diff.py` read a green — fails `self-mismatch`
  **on that line**; and a removed record fails the following line's `prev`.

The `$ref` case (step 7) is the one that most justifies the fixture's shape. The
removed field lives in `#/components/schemas/Order`, which the operation references
rather than inlining, so a gate that does not resolve `$ref` compares two identical
`{"$ref": …}` dicts and reports nothing. A fixture with only inline schemas would
pass against a gate with the resolution ripped out.

**Changed status semantics is deliberately absent.** It is one of the seven breaking
classes `api-contract-evolution` names, and the skill states plainly that no diff
can see it. A step asserting the gate catches it would be asserting a capability the
contract disclaims; step 15 rolls up the seven *mechanically-detectable* kinds the
gate actually named during steps 5–14 — computed from its own output, not restated
from a list — and that count is what would drop if a detection rule regressed.

## Why this needs no `claude -p` and is exempt from runs=5

This is a **zero-LLM** case: every step is a subprocess call to a deterministic
stdlib-Python CLI against fixture files this script writes. There is no persona
invocation and no output-shape judgement call — every assertion is an exact exit code
plus a naming JSON field, compared against a value that follows mechanically from the
tool's documented contract (`skills/pipeline-tools/SKILL.md` § `check_openapi_diff.py`).
The suite's `runs=5` / threshold `4/5` doctrine (see `evals/README.md`) exists to
average out **LLM output variance** across repeated persona runs; there is no variance
source here. A single run is a legitimate final verdict.

That is also why this case does not follow the `case.md` + `fixture/` + `grade.ps1`
shape `run-evals.ps1` expects, and is therefore **not dispatchable** by it —
`Get-ContractCases` discovers a contract case by the presence of *both* `case.md` and
`grade.ps1`, and this directory has neither, exactly like
`contract/mechanical-pipeline/` and `contract/bugfix-gates-adversarial/`. Run it as a
plain script. It costs nothing and needs no `-Confirm` gate.

**Every assertion checks the exit code AND a naming JSON field.** This gate has three
exit codes and fourteen `kind` values, so an exit code alone is routinely right for
the wrong reason — a `1` produced by the wrong detection rule, or a `2` that should
have been a `1`. Steps 8 and 11 are the clearest examples: step 8 asserts that a
rename produces `response_field_removed` **and** an additive `response_field_added`
(the gate must not pair them into one compatible edit), and step 11 asserts the new
parameter's *name* reaches `breaking[0].path`, not merely that something failed.

Unlike `bugfix-gates-adversarial`, this case needs **no git repository and no
`run_quiet.py` capture** — the gate reads two files and writes one ledger line, so
the fixture is two JSON documents and a temp directory.

## When to re-run it

- Any change to `skills/pipeline-tools/scripts/check_openapi_diff.py`.
- Any change to the breaking-class table in `skills/api-contract-evolution/SKILL.md`
  or `references/breaking-change-classes.md` — the `kind` strings asserted here are
  that table's mechanical half, and a renamed `kind` must break this case rather than
  silently orphan a wiring line.
- Any change to the shared ledger-chain helper (steps 21–23 are this gate's
  end-to-end chain coverage; `check_ledger.py`'s drift guard covers the helper).
- Any change to the wiring in `bgpdd-build/references/build-gate-ladders.md` § 6b or
  `bgpdd-shipping` Step 3 that alters how the gate is invoked.

## Running it

```bash
python evals/contract/openapi-diff-adversarial/run.py            # print only
python evals/contract/openapi-diff-adversarial/run.py --record   # + results.jsonl
```

Exit 0 only if all 25 steps pass. The script creates and removes its own temp
directory; it writes nothing under the repository except the `--record` line.

## Added in 2.6.1 (the audit-fix wave)

Steps 26-28 close the 2026-09-07 audit's F5, whose finding was not a missed
breaking class but a **PASS over a document the gate never analyzed**: a
response schema wrapped in `oneOf` with a field removed inside returned exit 0,
`breaking: []`, and no warning of any kind.

- **26/26b/26c** — `oneOf`, `anyOf` and `not` are `unanalyzable_schema`, exit
  2, naming the operation, the JSON path and the keyword. Both documents are
  wrapped so the only difference is inside the union; diffing a wrapped head
  against a plain base would report the wrapper itself and prove nothing.
- **26d** — `--allow-breaking` does not clear it. A waiver waives a diff
  somebody read, and there is no diff here to read.
- **26e** — the near-miss: `allOf` IS walked, so it must still be analyzed
  rather than refused. A rule that refused every composition keyword would be
  a different bug.
- **27/27b/27c** — `nullable: true -> false` on a response schema is
  `nullable_removed` (breaking); the widening is `nullable_widened` (additive)
  and also warned; and unlike an unanalyzable schema this one IS waivable,
  because it is a diff a person can read.
- **28** — every report now carries a `warnings` list, and an unresolvable
  `$ref` lands in it instead of comparing symmetrically and reporting nothing.
