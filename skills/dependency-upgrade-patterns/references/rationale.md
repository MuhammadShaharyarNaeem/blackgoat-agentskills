# Why This Contract Looks Like This

Read on demand. `../SKILL.md` is executable without any of this.

## Why one package per commit

The rule is not tidiness. It is the only thing that makes the rollback statement in Step 6 true.

A commit that bumps eleven packages has one revert, and that revert throws away ten upgrades that were fine to get rid of the one that was not. In practice nobody does it: they unpick the bad one by hand, on a bad afternoon, from a lockfile diff of nine thousand lines. So the "rollback plan" for a bundled bump is fiction — it is written down, it has never been rehearsed, and the first time it is needed it is not what happens.

One package per commit makes `git revert <sha>` a real, one-command, no-judgement recovery. That is the property being bought, and it is worth the extra commits.

**The coherent-group exception exists because some packages are one package.** A framework's sibling packages that validate each other's versions at install time (`@vue/*`, `Microsoft.EntityFrameworkCore.*`, `@types/x` beside `x`) cannot be moved separately — an intermediate commit where they disagree does not install. Splitting those is not caution, it is a broken commit. The test is mechanical: *would the tree at the intermediate commit install and build?* If no, they are one group. If yes, they are separate commits, however convenient it would be to bundle them.

**Why the lockfile travels in the same commit.** A lockfile committed separately from the manifest that moved it leaves an intermediate commit no clean install reproduces: the manifest asks for the new range while the lock still pins the old resolution, so `npm ci` / `dotnet restore --locked-mode` / `pip-sync` at that commit either fails or installs a tree nobody chose. That is also why `../SKILL.md` § Step 6 captures `git diff --name-only HEAD` rather than trusting the sentence — two files travelling together is exactly the kind of restraint that gets skipped at the moment of committing (convention #9).

**Why never a wildcard bump.** `npm update`, `dotnet outdated -u`, `pip install -U -r requirements.txt` all do the same thing: they produce a diff nobody read, made of decisions nobody made, with no brief possible because there is no bounded set of changelogs to read. The green suite that follows is not evidence — it is the same green suite that was passing before, run against a tree whose behaviour nobody characterized. A wildcard bump is not a fast version of this contract; it is the absence of it.

## Why the audit is captured twice

The instinct is to run the audit once, after the bump, and report that it is clean. That measurement cannot support the claim it is used for.

An audit after the bump tells you the state of the tree. It does not tell you what the bump *did*. "No high advisories" after an upgrade is equally consistent with the upgrade having fixed three, having introduced none, and having introduced one that the tool does not know about yet — and, most commonly, with there having been nothing there to fix in the first place, which makes the whole exercise a formality dressed as diligence.

The before-capture converts a state reading into a **delta**, which is the thing the upgrade is actually being judged on. It also does something the after-capture cannot: it records what was already broken. A pre-existing advisory that the bump did not touch, captured before, is a finding for the backlog. Discovered only after, it is indistinguishable from something the bump caused, and someone spends an hour proving it was not.

**Why a non-zero exit is still a valid capture.** Audit tools exit non-zero when they find something, and some exit non-zero when they cannot reach a registry. The capture is a record of what the command said, not an assertion that the tree was clean — that is why the contract says *record the exit code*, not *require exit 0*. A capture that says `exit 1, 3 moderate advisories` is a perfectly good before-capture, and comparing it to an after-capture saying `exit 0` is the strongest result this contract can produce.

**Why `run_quiet.py --capture` rather than pasting the output.** The sidecar. A hand-pasted audit result has no `.meta.json` beside it, records no argv, and cannot be checked for having run the same command twice or for having run at all. The capture body and its sidecar are cross-checked downstream; a typed one fails closed. This is convention #9 in its ordinary form: the artifact that has to be produced by running something, rather than the prose promise that something was run.

## Where the framework-major boundary comes from

The boundary is drawn at "framework major" rather than "any major" because the two behave differently.

A library major changes an API you call. The blast radius is the set of call sites, the brief can enumerate them, and Step 3's search finds them. That is a bounded change and this contract handles it.

A framework major changes the API *and* the runtime, the build, the conventions, the plugin ecosystem, and frequently the language level. Vue 2 to 3 changes the reactivity system and how components are declared. .NET major bumps move target frameworks, analyzer defaults, and sometimes the serialization behaviour of code nobody touched. EF Core majors change query translation, which alters SQL that no C# diff shows. None of that is enumerable from a call-site search, because the changes are not at call sites.

So the same contract cannot cover both. A framework major needs requirements, a plan, milestones, and a coverage gate — which is `/bgpdd-lite` at minimum. The Upgrade brief is not wasted work when this happens: it is precisely the shape mini-requirements want (a bounded scope, a numbered list of changes, each with a stated migration), which is why the contract hands it over rather than starting again.

**The boundary is about what the change is, not how big the diff looks.** A framework major whose diff is four lines is still a framework major — the small diff means the breakage is somewhere the compiler did not look, which is worse, not better.

## Why the API search precedes the run

Because a green suite is the single most convincing wrong answer available here.

The suite covers the paths it covers. A removed helper called from one error branch, one migration script, one admin endpoint, or one string-keyed plugin registration is invisible to it. Searching first turns "the tests pass" into a claim about a known set of call sites, and — importantly — it happens while you still have the changelog open and the removed identifier in front of you. Done afterwards, it degrades into re-reading whatever the test failures happened to name.

## Anti-patterns

| Anti-pattern | Why it fails | Instead |
|---|---|---|
| Bump first, read the changelog if something breaks | The changelog is being used as a debugging aid rather than a plan; the breaks that do not fail loudly are never found | Step 1, before the lockfile moves |
| Reading only the target version's notes | Removals are announced in the version that made them, not in the version you land on | *Versions crossed*, every one |
| One audit run, afterwards | Measures state, not delta; cannot distinguish a pre-existing advisory from one the bump introduced | Two captures, compared |
| Pasting the audit output into the report | No sidecar, no argv, no proof the same command ran twice | `run_quiet.py --capture` |
| Bumping the manifest and leaving the lockfile for later | An intermediate commit no clean install reproduces | Manifest and lockfile in the same commit |
| "Rollback: revert the upgrade PR" on an eleven-package commit | Throws away ten good upgrades; in practice nobody does it, so the plan is fiction | One package per commit, `git revert <sha>` |
| Widening a range instead of pinning (`^2.0.0`) | The version that ships is decided by whoever installs next, not by this change | Pin the exact version |
| Editing a test so the bump passes | The test was the thing that noticed the behaviour change | Revert and escalate |
| Treating a framework major as a big library major | Its breakage is not at call sites, so no call-site search bounds it | Route to `/bgpdd-lite` with the brief |
