# The Flag Lifecycle

Read on demand. `../SKILL.md` is executable without any of this.

## Five stages, and where each one usually fails

| Stage | What happens | Where it fails |
|---|---|---|
| 1. Declare | The flag is added to the committed config with owner, kind, expiry, removal-task, `default: off` | Declared with three of the five fields; the two missing ones are always `expiry` and `removal-task` |
| 2. Plan the removal | The deletion task is written into the plan in the same pass | Deferred to "a ticket after launch", which is where flags go to become permanent |
| 3. Roll out | The default is flipped per environment, deliberately, each flip recorded | Flipped in production only, by hand, with the config file left saying `off` |
| 4. Settle | The feature is confirmed shipped or killed; `code-simplification`'s *settled feature flag* signal fires | Nobody is watching for the signal because nobody owns the flag |
| 5. Remove | The removal task runs: branch collapsed, flag deleted from config, tests for the dead branch deleted | Half-done — the branch is collapsed but the declaration stays, so the config accumulates flags that gate nothing |

Stage 5's half-done form is worth naming, because it looks like completion. A config entry that no code reads is worse than one that does: it advertises a control that does not exist, and the first person to flip it in an incident learns that the hard way. The removal task's acceptance criteria must assert the *absence* of both — no reader in code, no entry in config.

## Release flags versus kill switches

These are the only two kinds. Anything that is neither is a configuration setting and should be named and treated as one.

|  | Release flag | Kill switch |
|---|---|---|
| Purpose | Decouple deploy from release while a change rolls out | Turn a working feature off fast, in production, during an incident |
| Lifetime | Weeks. It is scaffolding | Indefinite. It is a control |
| Clock | `expiry: <date>` — a blocker when passed | `review: <date>` — re-confirmed, not removed |
| Removal task | Written at creation, executed at settle | None; the review confirms it is still wanted and still works |
| Read cadence | Per process is acceptable | **Per request**, always |
| Failure mode of the read | Off | Off — the safe branch, which for a kill switch means the feature is disabled |
| Tested | Both branches | Both branches, plus the flip itself exercised at least once per review |

The distinction matters because the two are governed by opposite instincts. A release flag that survives is a defect. A kill switch that survives is doing its job. Recording `kind` at declaration time is what stops each being judged by the other's rule — and stops "it's really a kill switch" being discovered, conveniently, on the day a release flag expires.

**A kill switch that has never been flipped is a claim, not a control.** The review is the place to exercise it: flip it in a non-production environment, observe the safe branch, flip it back, and record that you did. A switch nobody has pulled since it was written is exactly as reliable as a rollback nobody has rehearsed.

## Writing the removal task

The removal task is an ordinary task under `{PLUGIN_ROOT}/planning-and-task-breakdown/SKILL.md`'s grammar. The parts that are specific to flags:

**Named identifiers** — list the config entry and every file holding a reader, gathered when the flag is created and the call sites are known, not rediscovered later by grep.

**Boundary contracts** — `provides: checkout-v2; consumes: flag.checkout-v2`. Reading that literally: the task consumes the live flag and provides the behaviour unconditionally. Every task that was gated by the flag has already consumed `flag.checkout-v2`, so the lint's lower-numbered rule places this task after all of them, which is exactly the ordering you want and did not have to remember.

**Acceptance criteria** — observable effects, per the planning skill's rule 1, which for a removal means the *absence* of the branch and not the absence of the code:

- [ ] The gated behaviour happens for every request, with no configuration present at all
- [ ] The flag name appears nowhere in the repository — not in config, not in code, not in tests
- [ ] The suite is green with the off-branch tests deleted rather than skipped

**Do NOT** — the fence that matters here is *do not change the surviving branch's behaviour while collapsing*. Removing a flag is a `code-simplification` change: same output, same error behaviour, same ordering. Bundling a behaviour tweak into the collapse is how a "cleanup" commit causes an incident, and it is why that skill's Rules forbid mixing kinds of change in one pass.

## The flag-debt review

Flags rot in aggregate, not one at a time. A standing review — at each shipping run, or on a fixed cadence — reads the whole config and asks three questions per entry:

1. Is it past its `expiry` or `review` date? (A blocker, per the contract.)
2. Does anything still read it? (If not, stage 5 was left half-done.)
3. Is its owner still here, and do they still know what it gates? (An orphaned flag is an expired flag whose date has not arrived yet.)

The output is findings, not fixes. A flag removed in the middle of a review is a behaviour change made without a plan task — the review's job is to raise them so the removals get planned.

## Anti-patterns

| Anti-pattern | Why it fails | Instead |
|---|---|---|
| `// TODO: remove this flag after launch` | Not a task, not scheduled, not owned; the comment outlives the feature | A numbered removal task at creation time |
| No expiry, "it'll be short-lived" | Every long-lived flag was short-lived once; the intent is only known at creation | `expiry` chosen when the flag is created |
| Default on, "so we can see it working" | Makes the untested state the shipped state, and makes off the untried path | `default: off`, flipped deliberately |
| Flipping the flag by editing a production row | A behaviour change with no diff, no author, no revert, invisible to every gate | Config as code |
| Flag read once at startup, called a kill switch | Cannot be flipped during the incident it exists for | Read per request |
| One flag gating several unrelated behaviours | Cannot be turned off for the one that is broken | One flag, one decision |
| On-branch tested, off-branch not | The rollback path has never been executed | Both branches |
| Collapsing the branch and tweaking behaviour in the same commit | Two kinds of change in one diff; the incident is attributed to the wrong half | Collapse only, per `code-simplification`'s Rules |
| Branch collapsed, config entry left behind | Advertises a control that does nothing | The removal task asserts the flag name is gone repo-wide |
| Extending the expiry silently when it passes | Converts a blocker into a habit | The owner decides and records it, or it is removed |
