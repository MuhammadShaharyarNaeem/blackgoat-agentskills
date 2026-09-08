# The Upgrade Brief, Field by Field

The brief is the artifact that proves the reading happened. It is written **before** the lockfile moves, and it is what a reviewer reads instead of taking your word for what the changelog said. Step 1 of `../SKILL.md` owns the rule; this file is the detail.

## The template

```
## Upgrade brief
- Package: <name>, <current> -> <target>
- Versions crossed: <every version between, inclusive of the target>
- Breaking changes: <one line each, or "none stated in the notes">
  - <removed or renamed API> -> <replacement>; migration: <doc section or link>
- Call sites in this repo: <path::symbol, one per line, or "none">
- Audit command: <the exact command this stack uses>
```

## Field by field

### `Package`

One name, and both versions as they appear in the manifest — not "latest", not a range. If the manifest currently carries a range (`^1.4.0`), record the version the lockfile actually resolved to; the range is what you are leaving, the resolved version is what you are actually crossing from.

### `Versions crossed`

Every release between current and target, inclusive of the target and exclusive of the current. `1.4.2 -> 2.1.0` crosses `1.5.0, 2.0.0, 2.1.0` — three sets of release notes, not one.

This is the field that most often gets shortened to just the target, and it is the field that most often hides the break: a removal announced in `2.0.0` does not appear in `2.1.0`'s notes at all, because from the maintainer's point of view it was already announced.

A version whose notes you could not find goes in this list annotated `unknown`, and triggers the escalation in the contract's *Escalate When* table. Silence in a changelog is not a statement that nothing broke; it is the absence of a statement.

### `Breaking changes`

One line per change, each carrying three things:

1. **What is gone or different** — the exact identifier, not a paraphrase. `parseOptions(opts, strict)` beats "the options parser changed".
2. **The replacement** — the exact identifier that takes over, or `no replacement` when the feature is simply gone.
3. **The migration** — the doc section, changelog heading, or upgrade-guide link that describes the move.

A line with (1) and no (3) is the escalation trigger, not a line you can write and proceed past. Guessing the replacement API from its name is the failure mode this field exists to catch: the plausible-looking replacement with different default behaviour ships green and misbehaves in production.

Deprecations that still work belong here too, marked as such. They are not blockers, but they are the next upgrade's breaking changes, and recording them now is what makes that upgrade cheap.

### `Call sites in this repo`

The output of Step 3's search, in `path::symbol` grammar — the same shape the Builder personas use for `<consumers>`, so a reviewer reads one grammar and not two.

Search source, tests, scripts, config, generated clients, and any string-based invocation (a CLI name in a `scripts` block, a plugin name in a config file). `none` is a legitimate value and a meaningful one: it says the search ran and found nothing, which is different from the field being absent.

### `Audit command`

The literal command, as it will be captured — so the after-run can be checked against the before-run for having used the same one. Recording `npm audit` and then running `npm audit --production` produces two captures that are not comparable and a delta that means nothing.

## A filled example

```
## Upgrade brief
- Package: slugmaker, 1.4.2 -> 2.0.0
- Versions crossed: 1.5.0, 2.0.0
- Breaking changes:
  - makeSlug(text, opts) -> toSlug(text, opts); migration: CHANGELOG 2.0.0 "Renames"
  - default separator changed from "_" to "-"; migration: CHANGELOG 2.0.0 "Defaults",
    pass { separator: "_" } to keep the old behaviour
  - 1.5.0: deprecated makeSlug (still functional, warns) - superseded by the 2.0.0 removal
- Call sites in this repo:
  scripts/build-report.js::buildReport
- Audit command: npm run audit
```

Note what the example does that a hurried brief does not: it records the `1.5.0` deprecation even though `2.0.0` supersedes it, because that deprecation warning is what a reader will see in the before-capture and wonder about; and it records the changed default separator, which no test in the repo would have caught, because the tests assert on a slug the new default happens to produce identically for their input.

## Where the brief lives

Wherever the lane already asks you to report:

| Lane | The brief goes in |
|---|---|
| `/bgpdd-build`, `/bgpdd-bugfix` | the unit's block in `test-report.md`, above the `**Runtime evidence:**` line |
| `/bgpdd-quick` | `{quick-root}/note.md`, under the three declared lines |
| `/bgpdd-lite` (framework major, routed) | the mini-requirements document itself — the brief **is** the requirements |
| Direct invocation | the reply, before the diff |

Never a new file invented for the purpose. The brief is a section, not an artifact class.
