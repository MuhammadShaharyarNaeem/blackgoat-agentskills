# check_tier1_provenance.py — reference

Depth for the `check_tier1_provenance.py` section of `../SKILL.md`.

## The gate the SKILL asked for by name

`bgpdd-discovery/SKILL.md` § 1 states the Tier-1 provenance contract and then says, in as many words: *"No mechanical gate enforces this yet. Until one exists, the stamp is prose the writing agent must honor and you must check by reading the header of each Tier-1 root artifact before closing the phase that produced it."* This is that gate, and the SKILL's "a gate spec is filed under this repo's open work" line is now discharged.

Convention #9 applies with unusual force here. Tier-1 artifacts are read *months later*, by pipelines with no way to distinguish a current map from a stale one — so the cost of the missing check is paid by someone who was not in the room, and the person asked to pay it is the Orchestrator closing a phase that is otherwise done.

## The stamp grammar

The SKILL states the obligation ("the repository HEAD commit sha it was derived from and the date, in its own header, one sha per repo on a multi-repo Target Scope, keyed by repo name") without pinning a syntax. This gate pins the least it can:

- **Header** = everything above the artifact's first `## ` heading. A sha buried in the body is not a stamp: the point is that a reader sees provenance *before* trusting the map, and `test_sha_below_the_first_heading_is_not_a_header_stamp` holds that line.
- **Date** = any `YYYY-MM-DD` in the header (validated month and day, so a version string cannot pass as a date).
- **Sha** = a 40-hex token, word-bounded so a longer hash cannot be sliced into one.
- **Keying** = with one `--repo` in scope, any header line carrying a sha is that repo's. With two or more, the sha's line must also carry the repo's name (case-insensitive substring). Nothing else makes several shas readable, and the alternative — positional order — is unreviewable.

A stamp shaped like this satisfies it:

```markdown
# Feature Overview — slide

> Provenance — 2026-09-07
> app: `9f1c…` · web: `44ab…`

## Owning services
```

## Drift is a warning. That is the contract, not a softness.

The SKILL is explicit: *"Drift is a warning, never a halt: an old map is usually still mostly right, and a hard failure would only teach people to skip Tier-1 entirely."* So drift is always computed and always reported in the JSON `drift` array, and it never touches the exit code. `--warn-on-drift` only adds human-readable stderr lines for an interactive run — it is a presentation flag by design, and `test_drift_exit_code_is_zero_through_main` pins that a drifted tree still exits 0.

What is *not* soft: a sha that does not resolve in its repo (`sha_unknown`). A stamp naming a commit the repo has never contained is not an old map, it is a fabricated one — a recalled or invented value, which is exactly what base-persona § Evidence Integrity forbids and what "read from the repo at write time, never recalled" was written to prevent. A `--repo` path that does not exist reports the same code, because the claim is equally uncheckable and an uncheckable claim is never a pass.

## Scope

`--summary-root` defaults to `.docs/summary`. `context.md` is always checked. With `--feature X`, only `X/overview.md` joins it — that is the Phase 4 invocation. Without it, every feature directory under the root is checked, and a feature directory holding no `overview.md` is `artifact_missing`: the lint runs *after* the phase that writes it, so an absent overview means the phase did not finish.

At Phase 1 there are no feature directories yet, so the unscoped run checks `context.md` alone and passes — no special-casing needed.

## Exit codes and codes

**0** every stamp present, dated and resolvable (drift included); **1** at least one finding; **2** `--summary-root` is not a directory, no `--repo` given, a malformed `--repo` argument, or git is unusable. Codes: `artifact_missing`, `stamp_missing`, `date_missing`, `sha_missing`, `sha_unknown`.

`stamp_missing` and `sha_missing` do not double-report: a header with no sha at all reports `stamp_missing` once rather than one `sha_missing` per in-scope repo, so the finding list reads as the one defect it is.

## Self-test

`python scripts/check_tier1_provenance.py --self-test` runs 16 in-process cases against real temp git repos (skipped, never faked, when git is absent): both artifacts stamped and passing, a feature-scoped run, a missing sha, a missing date, a sha below the first heading not counting, an unresolvable sha, each artifact missing, drift warning while still passing, drift exiting 0 through `main`, a multi-repo scope demanding a keyed sha per repo, a multi-repo scope with the two shas *swapped* between repos being caught, a `--repo` path that does not exist, bad-argument errors, `--repo` parsing, and the ledger recording all three exit paths.

The swapped-sha case is the reason the fixture repos are seeded with content keyed on their own directory name: two repos initialized in the same second by the same author from identical content produce the *same* commit sha, and the mis-keying would have been invisible.

## `stamp_date_future` and `--verify-current` (2.6.1)

**A future date is not a date.** The date was checked for SHAPE only -- a
`YYYY-MM-DD` anywhere in the header -- so `2031-01-01` passed, and the
2026-09-07 audit recorded this gate as BITES-with-a-date-gap for exactly that.
A stamp's claim is "this map was derived from the tree on this day"; a day
that has not happened records nothing that happened, and it fails in the
direction that keeps a stale map reading as fresh to every downstream
freshness comparison.

Only the LATEST date in the header is judged -- a header may legitimately
mention an earlier one in prose ("supersedes the 2026-01-04 map") -- against
today plus one day. The day of slack is for a machine running ahead of UTC; a
stamp written this morning is the normal case and must not be accused of
forgery. An impossible date (`2026-02-31`) never matches the day alternation
in `DATE_RE`, so it reads as no date rather than raising.

**`--verify-current` inverts the drift rule for the CONSUMER end.**
`bgpdd-discovery` section 1 says drift is a warning, and the default run still
obeys that: a hard failure at the producer would only teach people to skip
Tier 1. But the audit's Metric-13 finding was the other half -- the stamp had
**zero consumers**: plan, build, lite, verify and shipping all read a Tier-1
map without any of them checking that it describes the tree they are about to
work in, while discovery's section 1 hands the consumer half to them.

So the flag exists for the Pre-Flight that is about to brief agents from the
map. With it, a stamped sha that is not the repo's current HEAD is
`tier1_drift`, exit 1, naming repo, stamped sha and HEAD. `--allow-drift
"<reason>"` records the consumer's decision to proceed anyway -- the reason
and the waived entries land in the chained ledger record. Two refusals keep
the waiver honest: an empty or whitespace-only reason is exit 2 (matching
`--allow-breaking` and `--allow-tier-inversion`), and `--allow-drift` without
`--verify-current` is exit 2, because waiving a check that never ran records a
decision nobody had to make. It waives `tier1_drift` and nothing else -- a
missing stamp beside a waived drift still fails.

The self-test grew to **27**: five date cases (a future stamp, today and one
day of slack, the latest header date being the one judged, an impossible date
not raising, and the exit code through `main`) and six `--verify-current` /
`--allow-drift` cases (drift as a finding with all three values in the detail,
HEAD still matching, the waiver, the waiver not covering a real finding, all
three exit codes with the ledger record, and both misuse refusals).

## `--previous` — a cumulative file is not a rewrite (2.6.2)

`bgpdd-discovery/SKILL.md` section 1: *"Tier-1 `context.md` is cumulative and
project-wide; a run's Target Scope is a subset view recorded inside it, never
the file's whole content."* Sessions in one workspace run days or minutes
apart and each is scoped to its own repos, so a whole-file rewrite silently
deletes every repo the previous run recorded — last write wins, no diff, no
conflict marker, and `.docs/` carries no version history to recover from.

The SKILL therefore tells the Orchestrator to (a) copy the file to a
timestamped sibling backup before delegating Phase 1, (b) record its repo
inventory, and (c) confirm after Iris returns that every previously recorded
repo still appears. Step (c) is convention #9's shape precisely: it is asked
for at the moment the phase most wants to close, and the reason it feels safe
to skip is the trap — *this* run's own repos all check out.

`--previous <path>` is that backup, and the confirmation becomes a command.

### What fails, and what deliberately does not

**Fails (`tier1_repo_dropped`, exit 1):** a repo stamped in the previous copy
that appears in neither the repo keys nor the shas of the current artifact.
The finding names the repo, its previous sha, **both** file paths, and the
remedy the SKILL gives: restore from the backup, merge the two scopes,
re-delegate.

**Does not fail:**

- **A different sha for the same repo.** That is this run's refresh, which is
  the whole point of re-running Phase 1.
- **A repo the current artifact adds.** That is this run's scope.
- **A repo whose line was reworded, or a bare single-repo stamp that gained a
  repo name.** A repo counts as still stamped when its **key or its sha**
  reappears, so a re-keyed line is a refresh rather than a drop.

Removal fails **whether or not this run was ever scoped to the vanished
repo**. That asymmetry is the lesson: a user's "yes, update it" authorizes
adding this run's scope, never removing another's.

### How a repo key is read

`stamped_repos()` takes every header line carrying a 40-hex sha and keys it on
`stamp_key()` of everything to the left of that sha: heavy separators split
(the last segment wins), blockquote and list markers, markdown decoration, ISO
dates and a short noise list (`provenance`, `derived`, `from`, `commit`,
`sha`, `head`, `stamped`, `as of`, `at`, `on`, `repo`) are stripped, and a
trailing separator run is trimmed. A line reading `> app:` before its sha keys
as `app`; a bare `>` before its sha keys as the empty string, the single-repo
form.

The parse only has to be **deterministic and identical on both copies** for
the comparison to be sound: a repo whose line is untouched yields the same key
in both files, so it cannot produce a false drop. A repo whose wording changed
falls back to the sha match. And a false positive here says "check the merge",
which is the conservative direction for a rule about silent data loss.

### File or directory

`--previous` may be:

- a **file** — the timestamped backup of `context.md`, the one cumulative,
  project-wide artifact the lesson is about. It applies to `context.md` and to
  nothing else, so a feature `overview.md` (which is not cumulative across
  sessions) is untouched by it;
- a **directory** mirroring `--summary-root` — each checked artifact is
  compared against its counterpart there, which is how a run that backed up
  the whole tree gets the same check per artifact. A counterpart that does not
  exist is a warning, not a finding: there is nothing to compare.

A `--previous` path that does not exist at all is **exit 2**, and a previous
copy carrying no stamp is a warning — an unperformable check is never a PASS
and never a silent one.

The self-test grew to **39**: twelve `--previous` cases — same repos passing,
one dropped failing with both files named, a refreshed sha, a newly added
repo, a bare stamp that gained a name, a file `--previous` not applying to a
feature overview, a directory mirror finding the drop in both artifacts, a
missing counterpart warning only, an unstamped previous warning only, the
missing path as exit 2 through both `build_report` and `main`, the exit code
through `main`, and the `stamp_key` parser itself.
