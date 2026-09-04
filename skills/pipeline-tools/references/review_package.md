# review_package.py — reference

Depth for the `review_package.py` section of `../SKILL.md`: the observed failure it converts, the rendering rules, the sidecar's meaning, and the self-test inventory.

## The observed failure

`bgpdd-build` Phase 3 step 4 instructs a **fresh** Luna to re-review "the remediation diff itself" and record a new verdict. That instruction had no referent. The reviewer received a `<changed_files>` path list and read the amended working tree, which shows those files as they are **now** — not what the remediation changed. Three consequences, all silent:

1. **A fix is indistinguishable from the status quo.** A reviewer reading `OrderService.cs` cannot tell which lines the builder just wrote from the lines that were there before her first review.
2. **A deletion is invisible.** Nothing in a path list or a file read carries "this function is gone" — the strongest class of remediation regression is the one the reviewer structurally cannot see.
3. **The verdict floats.** "Approve on the CURRENT diff" is checkable only if the current diff is a thing with a hash. Without one, carrying a pre-fix verdict forward is undetectable after the fact.

Per `CLAUDE.md` convention #9, the fix is not a firmer sentence in step 4. It is an artifact that has to be generated and named: the Orchestrator runs this script **before** delegating, and passes the resulting path in the brief. The reviewer reads a file; the file's hash is in a sidecar; the two together make "she reviewed this diff" a checkable claim.

## Rendering rules

- **Range** — `base..head` in the two-dot sense (`git log`/`git diff` with an explicit range). Both refs are resolved to commit shas up front via `rev-parse --verify <ref>^{commit}`; an unresolvable ref is exit 2, never a silently empty package.
- **`--head WORKTREE`** — the sentinel that makes this tool usable where it is actually needed. In `bgpdd-build`, a milestone's changes stay **uncommitted** until the Phase 5 commit gate, so `base..HEAD` there renders an empty package for work that plainly exists. `WORKTREE` (case-insensitive) runs `git diff <base>` with no range — base against the working tree — while `## Commits` still spans `base..HEAD` and is legitimately empty mid-milestone. The typical build invocation is therefore `--base HEAD --head WORKTREE`: the last commit is the previous milestone's, so the package is exactly the current milestone's uncommitted work. The sidecar records `head: "WORKTREE"` rather than a sha, because there is no commit to name.
- **`--changed-files`** — passed to git as a pathspec after `--`, restricting `## Stat` and `## Diff` (never `## Commits`: the commit list is the range's, and hiding commits would misrepresent what produced the diff). The header's `Scope:` line records the filter so a reader knows the package is partial.
- **The fence** — `## Diff` is fenced with a backtick run **one longer than the longest backtick run inside the diff**, minimum three. These packages routinely contain diffs *of markdown*; a fixed three-backtick fence gets closed by the content and the rest of the diff escapes the code block, which is exactly the corruption that would make the artifact worse than no artifact.
- **Binary files** — no `--binary` flag, so git emits its own `Binary files a/… and b/… differ` notice. Git output is decoded with `errors="replace"` throughout: a rendering tool must not die on the content it exists to render.
- **Encoding** — the package and sidecar are written UTF-8; git output is decoded `utf-8-sig`-tolerantly; stdout JSON is ASCII-escaped for cp1252 console safety, mirroring `record_run.py`.

## An empty diff is exit 2

An empty package is not a cheap package — it is a review of nothing that looks exactly like a review of something. The cycle this tool serves always has a diff by construction (a remediation that changed nothing is itself the finding), so an empty range means the `--base` is wrong. Failing loudly at generation time is strictly cheaper than a reviewer approving an empty file. This is a deliberate divergence (convention #8) from `run_quiet.py`, which happily captures an empty stdout: there, emptiness is a legitimate observation; here it is a broken input.

## The sidecar

`<out>.meta.json` mirrors `run_quiet.py`'s shape — `argv`, `cwd`, `started`, `finished`, `exit_code`, `capture_sha256`, `tool`, `schema` — so a downstream reader already knows how to read it.

- `capture_sha256` is computed over the **finished package file's bytes**, so any later edit of the package invalidates it, including a plausible one.
- `argv` is the exact `git diff` argv that produced the load-bearing `## Diff` section — the same field name and role `run_quiet.py` gives its child command.
- `git_argv` additionally records all three commands (`log`, `diff --stat`, `diff`) as argv lists, so the whole package is reproducible rather than just its diff. This is the one field beyond the mirrored shape.
- `base` / `head` carry the resolved shas, not the refs as typed — `HEAD~1` means nothing a week later.

The sidecar is provenance, not a gate: nothing currently re-hashes it. Its value is that a review verdict can cite a package hash, and a mismatch is then detectable.

## Scope limits

- **It renders; it does not judge.** There is no exit 1. Whether the diff is good is Luna's job.
- **No merge-base handling.** `--base` is whatever revision the caller names; if a three-dot merge-base range is wanted, resolve it with `git merge-base` and pass the sha.
- **No renames-follow, no `--find-copies`.** Git's defaults apply.
- **The ledger line is best-effort**, per the shared gate-ledger contract in `../SKILL.md`, even though this script is a renderer rather than a gate. It carries `--ledger`/`--milestone` so the lane-parity sweep (agent-audit Metric 20) sees a scripted step, and so a package generation is attributable next to the gates that follow it.

## Self-test inventory

`python scripts/review_package.py --self-test` runs **19** cases in a disposable `git init` repo: all three sections plus the header render; the sidecar sha matches the written package; an edit to the package invalidates that sha; the sidecar records the exact git argv (including `-U<context>` and all three commands); an empty range is exit 2 with nothing written; a binary file in the diff is handled rather than crashed on; `--changed-files` restricts the diff and is recorded in the header; a filter matching nothing is exit 2; an unresolvable `--base` is exit 2; a non-git directory is exit 2; missing `--base` and missing `--out` are each exit 2; `--context` visibly changes hunk size; a diff of markdown gets a longer fence; the ledger records one line on both the PASS and the ERROR path; UTF-8 content round-trips; a deletion is visible in the package (the case the tree read cannot show); `--head WORKTREE` renders uncommitted changes and records `head: "WORKTREE"`; `WORKTREE` on a clean tree is still exit 2; and an unwritable `--out` is exit 2.
