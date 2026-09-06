# detect_stack.py — reference

Depth for the `detect_stack.py` section of `../SKILL.md`: why the script exists at all, and the detection rules the spine only names.

## Why a script instead of Iris's prose

Six methodology skills gate on an "If the project uses X" row in an agent's dependency table. Until this script existed that condition was decided by Iris's prose, so a stack could silently fail to load its skill — the same class of failure convention #9 converts: a load-time judgment made by the party who benefits from skipping it. The script is the mechanical floor. `bgpdd-discovery` Phase 1 runs it before delegating Iris and pastes the block into her brief; she records it verbatim in `context.md` and **may only add, never subtract** (conventions #8/#9). `bgpdd-build`'s hydration runs it once and injects the `skills` list into every builder/Quinn/Luna brief, with Tier-1's recorded block winning when it exists.

## Detection notes

- **vue3 vs vue2**: a `package.json` `"vue"` dependency with a parseable major `2` suppresses `vue3` entirely; an unparseable version counts as "has a framework" but contributes no vue3 evidence.
- **Confidence** — `high` = a definitive marker (`.csproj`/`.sln`, `project.godot`, vue major 3, bicep/`azure-pipelines`/`host.json`, `cdk.json`, an EF provider `PackageReference`); `medium` = a grep-based signal (a bare `.gd` file, a terraform provider block, a compose image, an `appsettings` connection string).
- **DB detection** unions three surfaces: EF provider packages in a `.csproj`, `appsettings` connection-string substrings, and compose image names.
- **Cloud detection** greps `*.tf` for provider/resource blocks alongside the definitive markers.
- `--max-depth` bounds `os.walk`; `SKIP_DIRS` is fixed, not caller-tunable.
- **Windows encoding**: markdown output uses ASCII punctuation only — a cp1252 stdout would corrupt an em dash when redirected into a UTF-8 `context.md`.

## The stack-defaults table

`STACK_DEFAULTS` maps a stack name to `suggested_check_commands` and
`test_path_globs`. It exists because `bgpdd-quick` Phase 0 was asking the user
for two things they should not have to type: the command that checks this repo,
and the test paths the close gate must freeze. Both are properties of the stack,
and the stack is already detected here — being asked twice was the friction, not
the detection.

Three rules keep it honest:

- **Only detected stacks contribute.** The table is looked up per emitted stack,
  so a suggestion inherits the evidence of the detection under it. A repo with
  no `package.json` never sees `npm test`.
- **A stack whose runner is not knowable from the tree gets no row.** docker,
  aws, azure, github-actions and the four db stacks carry empty lists. A wrong
  default is worse than a blank one: a proposal is read faster than it is
  audited, and the reflex answer to a plausible-looking command is yes.
- **Nothing here is ever run by this script**, and the quick lane is required to
  *offer* the command rather than adopt it. That is what stops a table entry
  quietly becoming this repo's definition of "verified".

`godot` is the one judgement call. Godot ships no test runner, so the row names
GUT's headless invocation — the de facto convention — knowing it is wrong in a
project that does not use GUT. It is listed rather than omitted because a named
command the user corrects costs less than a blank line they must fill; if that
proves wrong in practice, deleting the row is a one-line change.

The report-level `suggested_check_commands` / `test_path_globs` are the per-stack
lists concatenated in `stacks` order (name-sorted) and deduped. Ordering matters
only because two callers say "the first suggested command": quick Phase 0 and
`pipeline_driver.py`. Name-sorted is arbitrary but deterministic — a .NET repo
with a SPA in it proposes `dotnet test` first, and the user is the one who
decides whether that was the right half of the repo.

## Self-test inventory

`python scripts/detect_stack.py --self-test` runs **26** cases: dotnet, vue3, the vue2 suppression, godot, powershell, aws via terraform, azure via bicep, an empty repo, `node_modules` skipped, db via EF, react, node, playwright, github-actions, a missing repo (exit 2), the skills mapping, the never-guess invariant (no stack without an evidence path), and markdown rendering; then eight for the defaults — node's command and globs, the dotnet/python/powershell/vue3 first commands, defaults only for detected stacks, the deduped rollup ordering, a stack with no row carrying empty lists, an empty repo's empty rollup, the markdown block (ASCII-only), and the invariant that every table key is a name the detector can actually emit and carries both lists non-empty.
