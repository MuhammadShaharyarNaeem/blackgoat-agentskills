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

## Self-test inventory

`python scripts/detect_stack.py --self-test` runs **18** cases: dotnet, vue3, the vue2 suppression, godot, powershell, aws via terraform, azure via bicep, an empty repo, `node_modules` skipped, db via EF, react, node, playwright, github-actions, a missing repo (exit 2), the skills mapping, the never-guess invariant (no stack without an evidence path), and markdown rendering.
