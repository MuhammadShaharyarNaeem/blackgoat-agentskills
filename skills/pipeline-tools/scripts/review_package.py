#!/usr/bin/env python3
"""Materialize the diff a reviewer is told to review, as ONE artifact on disk.

`bgpdd-build` Phase 3 step 4 tells a fresh Luna to re-review "the remediation
diff itself". No such thing existed: she received a path list and read the
amended tree, which shows the CURRENT state of those files -- not what the
remediation changed. A reviewer reading the tree cannot distinguish "the fix
landed" from "the file always looked like this", and cannot see a deletion at
all. That is the prose rule this script converts into an artifact
(`CLAUDE.md` convention #9): the Orchestrator generates the package BEFORE
delegating, and names its path in the brief.

Writes `<out>` -- a single markdown file with:

    header      repo, base, head, timestamp, generated-by
    ## Commits  git log --oneline base..head
    ## Stat     git diff --stat base..head
    ## Diff     git diff -U<context> base..head (fenced)

plus `<out>.meta.json`, the machine-owned sidecar mirroring `run_quiet.py`'s
shape: `argv`, `cwd`, `started`, `finished`, `exit_code`, `capture_sha256`,
`tool`, `schema`. `capture_sha256` is over the finished package FILE's bytes,
so ANY later edit of the package -- including a plausible one -- invalidates
it. A reviewer's verdict can therefore be tied to a package nobody retouched.

An EMPTY diff is exit 2, not an empty package. A package with no diff in it
is indistinguishable from a review of nothing, and the remediation cycle it
exists to serve always has a diff by construction; an empty one means the
range is wrong.

`--head WORKTREE` compares the base against the **uncommitted working tree**.
That is the `bgpdd-build` Phase 3 case and the reason the sentinel exists: a
milestone's changes are not committed until the Phase 5 commit gate, so a
two-dot `base..HEAD` range there renders an empty package for work that
plainly exists.

Usage:
    python review_package.py --repo . --base <ref> [--head <ref>|WORKTREE] \
        [--changed-files <p1> [<p2> ...]] --out <dir>/review-package.md \
        [--context 10] [--ledger <path>] [--milestone "<title>"]
    python review_package.py --self-test

Exit codes: 0 package written; 2 git failed, the range is empty, or a
usage/structural failure. There is no exit 1 -- this tool renders, it does
not judge.

Pure standard library. Cross-platform (Windows/POSIX).
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

SIDECAR_SUFFIX = ".meta.json"
SIDECAR_SCHEMA = 1
TIMESTAMP_FMT = "%Y-%m-%dT%H:%M:%SZ"
DEFAULT_CONTEXT = 10
WORKTREE = "WORKTREE"
GIT_TIMEOUT = 240
TOOL = "review_package.py"

# Files a human reviewer should not be asked to read line-by-line: lockfiles,
# minified/compiled/generated output, and vendored trees. Deliberately a
# short allow-nothing-surprising list, not a taxonomy -- add a pattern only
# when a reviewer has actually been handed one of these to read.
#
# Every pattern is `**/`-prefixed so git's glob pathspec magic (fnmatch with
# FNM_PATHNAME -- a bare `*` does not cross a `/`) reaches ANY depth, not
# just the repo root: `frontend/package-lock.json` in a monorepo is exactly
# the file this list exists to hide, and a lockfile excluded at the root but
# rendered in a subfolder is a surprise, not a feature. Verified empirically
# against a throwaway repo (no local `git help pathspec` man page on this
# platform): `**/package-lock.json` matches both `package-lock.json` and
# `frontend/package-lock.json`; `**/node_modules/**` matches both a
# root-level and a nested `node_modules/` tree.
DEFAULT_EXCLUDES = [
    "**/package-lock.json",
    "**/yarn.lock",
    "**/pnpm-lock.yaml",
    "**/Cargo.lock",
    "**/poetry.lock",
    "**/Pipfile.lock",
    "**/composer.lock",
    "**/Gemfile.lock",
    "**/packages.lock.json",
    "**/*.min.js",
    "**/*.min.css",
    "**/*.map",
    "**/*.snap",
    "**/*.g.cs",
    "**/*.Designer.cs",
    "**/*.generated.*",
    "**/*.pb.go",
    "**/*.pyc",
    "**/node_modules/**",
    "**/vendor/**",
    "**/dist/**",
    "**/build/**",
    "**/bin/**",
    "**/obj/**",
    "**/__pycache__/**",
]

# A `## Size waiver` heading at any level 2-4. Its body runs to the next
# heading of level 2-6 (ANY_HEADING_RE), the same boundary rule
# check_commit_gate.py's review-section parsing uses.
#
# Duplicated from check_commit_gate.py by family convention: stdlib-only,
# one file each, no shared module.
SIZE_WAIVER_HEADING_RE = re.compile(r"^#{2,4}\s*Size\s+waiver\s*:?\s*$",
                                    re.IGNORECASE)
# A waiver body line that is only a template stand-in. The waiver is
# deliberately hand-typed -- see check_diff_size_bound() -- so the ONLY thing
# worth rejecting is a section that was never filled in.
WAIVER_PLACEHOLDER_RE = re.compile(
    r"^(?:<[^>]*>|todo|tbd|fixme|n/?a|none|\?+|\.{3,}|xxx+)[.:]?$",
    re.IGNORECASE)
# ANY level-2..6 heading closes an open '## Size waiver' section.
ANY_HEADING_RE = re.compile(r"^#{2,6}(?:\s|$)")
FENCE_RE = re.compile(r"^[ \t]*(`{3,}|~{3,})")


class PackageError(Exception):
    """Structural/usage/git failure -- maps to exit 2."""


def utc_now():
    return datetime.now(timezone.utc).strftime(TIMESTAMP_FMT)


def sha256_file(path):
    """Hex sha256 of a file's bytes, or None when it cannot be read."""
    try:
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def ledger_line_hash(raw):
    """sha256 of one ledger LINE's bytes, ignoring its terminator.

    Surrounding whitespace (CR included) is stripped so a ledger written on
    Windows chains identically to the same file read on POSIX. Byte-identical
    in every gate in this family and in check_ledger.py, which verifies the
    chain (family convention: one file each, no shared module).
    """
    return hashlib.sha256(raw.strip()).hexdigest()


def ledger_prev_hash(ledger_path):
    """The `prev` value for the next record: hash of the last line on disk.

    `"genesis"` when the ledger is missing or holds no non-blank line.
    """
    try:
        with open(ledger_path, "rb") as fh:
            data = fh.read()
    except OSError:
        return "genesis"
    last = None
    for raw in data.splitlines():
        if raw.strip():
            last = raw
    return "genesis" if last is None else ledger_line_hash(last)


def ledger_self_hash(record):
    """sha256 of the record serialized canonically WITHOUT its `self` field."""
    body = {k: v for k, v in record.items() if k != "self"}
    return hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":"))
        .encode("utf-8")).hexdigest()


def append_ledger(ledger_path, argv, milestone, inputs, verdict, exit_code,
                  extra=None):
    """Append ONE JSON line recording this run. Best-effort by design."""
    if not ledger_path:
        return
    record = {
        "ts": utc_now(),
        "gate": Path(__file__).name,
        "argv": list(argv),
        "milestone": milestone,
        "inputs": {str(p): sha256_file(p) for p in inputs if p},
        "verdict": verdict,
        "exit": exit_code,
    }
    if extra:
        record.update(extra)
    try:
        p = Path(ledger_path)
        if str(p.parent):
            p.parent.mkdir(parents=True, exist_ok=True)
        record["prev"] = ledger_prev_hash(p)
        record["self"] = ledger_self_hash(record)
        with open(p, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
    except OSError as exc:
        print(f"Warning: could not append to ledger {ledger_path}: {exc}",
              file=sys.stderr)


# ---------------------------------------------------------------------------
# git
# ---------------------------------------------------------------------------

def run_git(args, repo):
    """Run one git command. Returns (stdout_text, argv). Failure is exit 2.

    Output is decoded with `errors="replace"`: a diff can carry a filename or
    a hunk byte that is not valid UTF-8, and a rendering tool must not die on
    the content it exists to render.
    """
    argv = ["git"] + list(args)
    try:
        proc = subprocess.run(argv, cwd=repo, capture_output=True,
                              timeout=GIT_TIMEOUT)
    except FileNotFoundError:
        raise PackageError("git executable not found on PATH")
    except subprocess.TimeoutExpired:
        raise PackageError(f"git {args[0]} timed out after {GIT_TIMEOUT}s")
    except OSError as exc:
        raise PackageError(f"git {args[0]} could not be launched: {exc}")
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout).decode("utf-8", errors="replace")
        raise PackageError(f"git {args[0]} failed: {err.strip()}")
    return proc.stdout.decode("utf-8-sig", errors="replace"), argv


def resolve_repo(repo):
    p = Path(repo)
    if not p.is_dir():
        raise PackageError(f"--repo is not a directory: {repo}")
    run_git(["rev-parse", "--git-dir"], str(p))
    return str(p)


def resolve_rev(ref, repo, flag):
    """Resolve a revision to a commit sha. An unknown ref is exit 2."""
    try:
        out, _ = run_git(["rev-parse", "--verify", "%s^{commit}" % ref], repo)
    except PackageError:
        raise PackageError(f"{flag} is not a resolvable commit: {ref}")
    return out.strip()


# ---------------------------------------------------------------------------
# excludes
# ---------------------------------------------------------------------------

def exclude_pathspecs(patterns):
    """Git pathspec exclude-glob magic for each pattern, verified against a
    real repo: `:(exclude,glob)<pattern>` (order-insensitive with
    `:(glob,exclude)`) matches everything else when it is the only pathspec,
    and subtracts from a positive pathspec when combined with one."""
    return [":(exclude,glob)%s" % p for p in patterns]


# ---------------------------------------------------------------------------
# size waiver (duplicated from check_commit_gate.py by family convention:
# stdlib-only, one file each, no shared module)
# ---------------------------------------------------------------------------

def strip_fenced_blocks(text):
    """Blank out every ```/~~~ fenced region, preserving the line count.

    A `## Size waiver` pasted inside a fence is a TEMPLATE or a captured
    transcript, never a recorded decision. Line count is preserved so that
    any line-indexed diagnostic stays honest.
    """
    out, fence = [], None
    for line in text.split("\n"):
        m = FENCE_RE.match(line)
        if fence is None:
            if m:
                fence = m.group(1)
                out.append("")
                continue
            out.append(line)
        else:
            if m and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence):
                fence = None
            out.append("")
    return "\n".join(out)


def read_size_waiver(waiver_path):
    """Return (section_found, body_nonempty) for `## Size waiver`.

    Fences are stripped first, so a waiver section pasted as a TEMPLATE inside
    an example block cannot license a commit -- the same rule the verdict
    parser in check_commit_gate.py applies.

    A body is a PLACEHOLDER in either of two shapes, and the second one is the
    load-bearing addition: every line individually a stand-in, OR one `<...>`
    span WRAPPED across several lines. The shipped `rca-template.md` writes the
    second shape ("<Delete this whole section unless ...>"), and a line-by-line
    test alone accepted it -- so copying the template was a complete bypass of
    the file bound. Same fix as check_bugfix_intake.is_placeholder_body().
    """
    text = strip_fenced_blocks(read_text(waiver_path))
    found, capturing, body = False, False, []
    for line in text.splitlines():
        if SIZE_WAIVER_HEADING_RE.match(line):
            found, capturing, body = True, True, []   # LAST section wins
            continue
        if capturing and ANY_HEADING_RE.match(line):
            capturing = False
            continue
        if capturing:
            body.append(line)
    real = [l.strip() for l in body if l.strip()]
    if not real:
        return found, False
    if all(WAIVER_PLACEHOLDER_RE.match(l) for l in real):
        return found, False
    if WAIVER_PLACEHOLDER_RE.match(" ".join(real)):
        return found, False   # one `<...>` span wrapped across several lines
    return found, True


def read_text(path):
    """Read a UTF-8 artifact, tolerating a byte-order mark.

    Duplicated from check_commit_gate.py by family convention (stdlib-only,
    one file each, no shared module).
    """
    p = Path(path)
    if not p.is_file():
        raise PackageError(f"file not found or not readable: {path}")
    return p.read_text(encoding="utf-8-sig", errors="replace")


def check_diff_size_bound(diff_lines, max_diff_lines, waiver_path):
    """Return (size_waiver dict, ok, note) for the diff-size ceiling.

    **What is counted**: `diff_lines`, the count of `+`/`-` lines in the
    filtered `## Diff` text (excludes already applied, `+++`/`---` file
    headers excluded) -- see count_diff_lines().

    **Why the waiver is hand-typed.** Same rationale as
    check_commit_gate.py's check_size_bound(): the decision to exceed the
    bound is the USER's, and no script can verify a judgement call. What the
    gate buys is that the decision is durable and attributable -- written
    into a file, hashed into the ledger record -- instead of spoken once in
    chat. So the check is existence plus a non-placeholder body, and nothing
    more. This converts `code-review-and-quality/SKILL.md`'s prose escalation
    ("the change is too large to review properly -> request a split") into an
    artifact per CLAUDE.md convention #9, and is a labeled divergence
    (convention #8) of the same shape check_commit_gate.py --waiver already
    makes -- deliberately, not a new rule.
    """
    waiver = {"path": waiver_path, "present": False, "section_found": False,
              "body_nonempty": False, "satisfied": False}
    if diff_lines <= max_diff_lines:
        return waiver, True, None
    if not waiver_path:
        return waiver, False, (
            f"{diff_lines} diff line(s) exceeds --max-diff-lines "
            f"{max_diff_lines} and no --waiver was given -- the reviewable "
            "diff is too large: split the milestone (route to /bgpdd-plan) "
            "or record the user's decision under a '## Size waiver' heading")
    if not Path(waiver_path).is_file():
        return waiver, False, (
            f"{diff_lines} diff line(s) exceeds --max-diff-lines "
            f"{max_diff_lines} and the --waiver file {waiver_path} does not "
            "exist")
    waiver["present"] = True
    found, nonempty = read_size_waiver(waiver_path)
    waiver["section_found"] = found
    waiver["body_nonempty"] = nonempty
    if not found:
        return waiver, False, (
            f"{diff_lines} diff line(s) exceeds --max-diff-lines "
            f"{max_diff_lines} and {waiver_path} has no '## Size waiver' "
            "heading outside a fenced block")
    if not nonempty:
        return waiver, False, (
            f"{diff_lines} diff line(s) exceeds --max-diff-lines "
            f"{max_diff_lines} and the '## Size waiver' section in "
            f"{waiver_path} is empty or still a placeholder -- an unwritten "
            "waiver records no decision")
    waiver["satisfied"] = True
    return waiver, True, (
        f"{diff_lines} diff line(s) exceeds --max-diff-lines "
        f"{max_diff_lines}, waived by the '## Size waiver' section in "
        f"{waiver_path}")


def count_diff_lines(diff_text):
    """Added + removed lines in a unified diff, `+++`/`---` headers excluded."""
    count = 0
    for line in diff_text.split("\n"):
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("+") or line.startswith("-"):
            count += 1
    return count


# ---------------------------------------------------------------------------
# rendering
# ---------------------------------------------------------------------------

def fence_for(text):
    """A backtick fence longer than any run of backticks inside `text`.

    The packages this tool renders routinely contain diffs OF markdown, so a
    plain three-backtick fence gets closed by the content and the rest of the
    diff escapes the code block.
    """
    longest = 0
    for run in re.findall(r"`+", text or ""):
        longest = max(longest, len(run))
    return "`" * max(3, longest + 1)


def build_package(repo, base_ref, head_ref, base_sha, head_sha, commits, stat,
                  diff, changed_files, generated, excluded_files,
                  size_waiver_line=None):
    fence = fence_for(diff)
    lines = [
        "# Review package",
        "",
        f"- Repo: `{repo}`",
        f"- Base: `{base_ref}` (`{base_sha}`)",
        (f"- Head: uncommitted working tree (`{WORKTREE}`)"
         if head_sha == WORKTREE else f"- Head: `{head_ref}` (`{head_sha}`)"),
        f"- Generated: {generated}",
        f"- Generated by: `{TOOL}`",
    ]
    if changed_files:
        lines.append("- Scope: " + ", ".join(f"`{p}`" for p in changed_files))
    else:
        lines.append("- Scope: whole range (no `--changed-files` filter)")
    # A reviewer writes a `### Files reviewed` line for every declared file,
    # including excluded ones ("not reviewed: excluded from package") -- so
    # this header must tell her which those were. Never silent.
    if excluded_files:
        lines.append(
            f"- Excluded from diff ({len(excluded_files)}): "
            + ", ".join(f"`{p}`" for p in excluded_files))
    else:
        lines.append("- Excluded from diff: none")
    if size_waiver_line:
        lines.append(size_waiver_line)
    lines += [
        "",
        "## Commits",
        "",
        "```text",
        (commits.rstrip("\n") or "(no commits in range)"),
        "```",
        "",
        "## Stat",
        "",
        "```text",
        (stat.rstrip("\n") or "(no stat)"),
        "```",
        "",
        "## Diff",
        "",
        fence + "diff",
        diff.rstrip("\n"),
        fence,
        "",
    ]
    return "\n".join(lines)


def build_sidecar(out_path, diff_argv, git_argv, base_sha, head_sha,
                  started, finished, exit_code, excluded_files,
                  exclude_patterns, diff_lines, max_diff_lines,
                  size_waiver=None):
    """The machine-owned provenance record for a package.

    `argv` is the `git diff` argv that produced the load-bearing section --
    the same field name and role `run_quiet.py`'s sidecar uses for its child
    command. `git_argv` records all three commands so the whole package is
    reproducible, not just its diff.
    """
    sidecar = {
        "argv": list(diff_argv),
        "git_argv": [list(a) for a in git_argv],
        "cwd": os.getcwd(),
        "base": base_sha,
        "head": head_sha,
        "started": started,
        "finished": finished,
        "exit_code": int(exit_code),
        "capture_sha256": sha256_file(out_path),
        "tool": TOOL,
        "schema": SIDECAR_SCHEMA,
        "excluded_files": list(excluded_files),
        "exclude_patterns": list(exclude_patterns),
        "diff_lines": diff_lines,
        "max_diff_lines": max_diff_lines,
    }
    if size_waiver is not None:
        sidecar["size_waiver"] = size_waiver
    return sidecar


def write_text(path, text):
    try:
        p = Path(path)
        if str(p.parent):
            p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    except OSError as exc:
        raise PackageError(f"cannot write {path}: {exc}")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def build_parser():
    parser = argparse.ArgumentParser(prog=TOOL, add_help=True)
    parser.add_argument("--repo", default=".")
    parser.add_argument("--base")
    parser.add_argument("--head", default="HEAD",
                        help="a revision, or WORKTREE to compare the base "
                             "against the uncommitted working tree")
    parser.add_argument("--changed-files", dest="changed_files", nargs="*",
                        default=None)
    parser.add_argument("--out")
    parser.add_argument("--context", type=int, default=DEFAULT_CONTEXT)
    parser.add_argument("--ledger")
    parser.add_argument("--milestone")
    parser.add_argument("--exclude", action="append", default=None,
                        help="git pathspec glob pattern to exclude from "
                             "## Stat/## Diff, in addition to the built-in "
                             "DEFAULT_EXCLUDES. Repeatable.")
    parser.add_argument("--no-default-excludes", action="store_true",
                        help="disable the built-in DEFAULT_EXCLUDES list; "
                             "only --exclude patterns (if any) apply")
    parser.add_argument("--max-diff-lines", dest="max_diff_lines", type=int,
                        help="ceiling on +/- lines in the filtered ## Diff "
                             "(after excludes); over it with no satisfying "
                             "--waiver is exit 2")
    parser.add_argument(
        "--waiver",
        help="path to a file carrying the user's hand-typed '## Size "
             "waiver' decision to exceed --max-diff-lines (typically "
             "review/size-waiver.md or rca.md)")
    parser.add_argument("--self-test", action="store_true")
    return parser


def generate(args):
    """Render the package. Returns the stdout payload dict."""
    started = utc_now()
    repo = resolve_repo(args.repo)
    base_sha = resolve_rev(args.base, repo, "--base")
    worktree = str(args.head).upper() == WORKTREE
    if worktree:
        # `git diff <base>` (no range) is base-vs-working-tree. The commit log
        # still spans base..HEAD, which is legitimately empty mid-milestone.
        head_sha = WORKTREE
        log_range = f"{base_sha}..HEAD"
        diff_range = [base_sha]
    else:
        head_sha = resolve_rev(args.head, repo, "--head")
        log_range = f"{base_sha}..{head_sha}"
        diff_range = [log_range]
    files = [p for p in (args.changed_files or []) if p]
    base_pathspec = (["--"] + files) if files else []

    exclude_patterns = ([] if args.no_default_excludes else
                        list(DEFAULT_EXCLUDES)) + list(args.exclude or [])
    exclude_specs = exclude_pathspecs(exclude_patterns)
    full_pathspec = ((["--"] + files + exclude_specs)
                     if (files or exclude_specs) else [])

    # Excluded files must be visible, not silent: diff the SAME range with and
    # without the exclude magics and record the set difference, before ever
    # rendering the filtered ## Stat/## Diff.
    excluded_files = []
    if exclude_specs:
        unfiltered_out, _ = run_git(
            ["diff", "--name-only"] + diff_range + base_pathspec, repo)
        filtered_out, _ = run_git(
            ["diff", "--name-only"] + diff_range + full_pathspec, repo)
        unfiltered_names = [l.strip() for l in unfiltered_out.splitlines()
                            if l.strip()]
        filtered_names = set(l.strip() for l in filtered_out.splitlines()
                             if l.strip())
        excluded_files = [f for f in unfiltered_names if f not in filtered_names]
    else:
        unfiltered_names = None  # not computed -- no excludes, nothing to diff

    commits, log_argv = run_git(["log", "--oneline", log_range], repo)
    stat, stat_argv = run_git(
        ["diff", "--stat"] + diff_range + full_pathspec, repo)
    diff, diff_argv = run_git(
        ["diff", "-U%d" % max(0, args.context)] + diff_range + full_pathspec,
        repo)

    if not diff.strip():
        if exclude_specs and unfiltered_names:
            raise PackageError(
                f"every changed path was excluded by pattern; pass "
                "--no-default-excludes or narrow --exclude")
        raise PackageError(
            f"empty diff for {args.base}..{args.head}"
            + (f" restricted to {len(files)} path(s)" if files else "")
            + " -- an empty diff is not a review package")

    diff_lines = count_diff_lines(diff)
    size_waiver = None
    size_waiver_line = None
    if args.max_diff_lines is not None:
        size_waiver, size_ok, note = check_diff_size_bound(
            diff_lines, args.max_diff_lines, args.waiver)
        if not size_ok:
            raise PackageError(note)
        if size_waiver["satisfied"]:
            over_by = diff_lines - args.max_diff_lines
            size_waiver_line = (
                f"- Size waiver: `{args.waiver}` ({over_by} lines over "
                f"--max-diff-lines {args.max_diff_lines})")

    generated = utc_now()
    package = build_package(repo, args.base, args.head, base_sha, head_sha,
                            commits, stat, diff, files, generated,
                            excluded_files, size_waiver_line)
    write_text(args.out, package)
    sidecar = build_sidecar(args.out, diff_argv,
                            [log_argv, stat_argv, diff_argv],
                            base_sha, head_sha, started, utc_now(), 0,
                            excluded_files, exclude_patterns, diff_lines,
                            args.max_diff_lines, size_waiver)
    write_text(str(args.out) + SIDECAR_SUFFIX,
               json.dumps(sidecar, indent=2) + "\n")
    payload = {
        "written": True,
        "out": str(args.out),
        "sidecar": str(args.out) + SIDECAR_SUFFIX,
        "repo": repo,
        "base": base_sha,
        "head": head_sha,
        "context": max(0, args.context),
        "changed_files": files,
        "commit_count": len([l for l in commits.splitlines() if l.strip()]),
        "diff_bytes": len(diff.encode("utf-8", errors="replace")),
        "excluded_files": excluded_files,
        "exclude_patterns": exclude_patterns,
        "diff_lines": diff_lines,
        "max_diff_lines": args.max_diff_lines,
        "capture_sha256": sidecar["capture_sha256"],
        "result": "WRITTEN",
        "error": None,
    }
    if size_waiver is not None:
        payload["size_waiver"] = size_waiver
    return payload


def main(argv):
    args = build_parser().parse_args(argv)
    if args.self_test:
        return run_self_test()

    files = [p for p in (args.changed_files or []) if p]
    try:
        for name, value in (("--base", args.base), ("--out", args.out)):
            if not value:
                raise PackageError(f"missing required argument: {name}")
        if args.max_diff_lines is not None and args.max_diff_lines < 1:
            raise PackageError("--max-diff-lines must be >= 1 (a bound of 0 "
                               "can never be satisfied)")
        if args.waiver and args.max_diff_lines is None:
            raise PackageError("--waiver given without --max-diff-lines -- "
                               "there is no bound for it to waive")
        payload = generate(args)
    except PackageError as exc:
        payload = {"written": False, "out": args.out, "result": "ERROR",
                   "error": str(exc)}
        print(json.dumps(payload, indent=2))
        append_ledger(args.ledger, argv, args.milestone, files, "ERROR", 2)
        return 2

    # stdout stays ASCII-escaped (still valid JSON): a cp1252 console cannot
    # encode a non-ASCII path, and the tool must not fail on its own success
    # report. The FILE writes above are real utf-8.
    print(json.dumps(payload, indent=2))
    append_ledger(args.ledger, argv, args.milestone, files, "PASS", 0,
                  extra={"output": {str(args.out): payload["capture_sha256"]}})
    return 0


# ---------------------------------------------------------------------------
# self-test
# ---------------------------------------------------------------------------

def run_self_test():
    import shutil

    def git(repo, *args):
        subprocess.run(["git"] + list(args), cwd=repo, capture_output=True,
                       check=True, timeout=GIT_TIMEOUT)

    class ReviewPackageTests(unittest.TestCase):
        def setUp(self):
            self.dir = Path(tempfile.mkdtemp())
            self.repo = self.dir / "repo"
            self.repo.mkdir()
            self.out = self.dir / "artifacts" / "review-package.md"
            git(self.repo, "init", "-q")
            git(self.repo, "config", "user.email", "pkg@test")
            git(self.repo, "config", "user.name", "pkg")
            git(self.repo, "config", "commit.gpgsign", "false")
            self._write("src/app.py", "def a():\n    return 1\n")
            git(self.repo, "add", "-A")
            git(self.repo, "commit", "-q", "-m", "base commit")

        def tearDown(self):
            shutil.rmtree(self.dir, ignore_errors=True)

        def _write(self, rel, text, binary=False):
            p = self.repo / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            if binary:
                p.write_bytes(text)
            else:
                p.write_text(text, encoding="utf-8")

        def _commit(self, message="change"):
            git(self.repo, "add", "-A")
            git(self.repo, "commit", "-q", "-m", message)

        def _args(self, *extra):
            return ["--repo", str(self.repo), "--base", "HEAD~1",
                    "--out", str(self.out)] + list(extra)

        def _package(self):
            return self.out.read_text(encoding="utf-8-sig")

        def _sidecar(self):
            return json.loads(
                Path(str(self.out) + SIDECAR_SUFFIX).read_text(
                    encoding="utf-8-sig"))

        # -- 1: the happy path renders all three sections -------------------
        def test_writes_all_sections_and_header(self):
            self._write("src/app.py", "def a():\n    return 2\n")
            self._commit("fix the return")
            self.assertEqual(main(self._args()), 0)
            text = self._package()
            for heading in ("# Review package", "## Commits", "## Stat",
                            "## Diff"):
                self.assertIn(heading, text)
            self.assertIn("- Generated by: `review_package.py`", text)
            self.assertIn("fix the return", text)          # ## Commits
            self.assertIn("src/app.py", text)              # ## Stat
            self.assertIn("-    return 1", text)           # ## Diff
            self.assertIn("+    return 2", text)

        # -- 2: sidecar sha matches the package file's bytes ----------------
        def test_sidecar_sha_matches_written_package(self):
            self._write("src/app.py", "def a():\n    return 2\n")
            self._commit()
            self.assertEqual(main(self._args()), 0)
            meta = self._sidecar()
            self.assertEqual(meta["capture_sha256"], sha256_file(self.out))
            self.assertEqual(meta["tool"], TOOL)
            self.assertEqual(meta["schema"], SIDECAR_SCHEMA)
            self.assertEqual(meta["exit_code"], 0)
            for key in ("argv", "cwd", "started", "finished"):
                self.assertIn(key, meta)

        # -- 3: an edit to the package invalidates the sidecar sha ----------
        def test_edited_package_no_longer_matches_sidecar(self):
            self._write("src/app.py", "def a():\n    return 2\n")
            self._commit()
            self.assertEqual(main(self._args()), 0)
            before = self._sidecar()["capture_sha256"]
            self.out.write_text(self._package() + "\nplausible addition\n",
                                encoding="utf-8")
            self.assertNotEqual(before, sha256_file(self.out))

        # -- 4: the sidecar records the exact git argv ----------------------
        def test_sidecar_records_exact_git_argv(self):
            self._write("src/app.py", "def a():\n    return 2\n")
            self._commit()
            self.assertEqual(main(self._args("--context", "3")), 0)
            meta = self._sidecar()
            self.assertEqual(meta["argv"][0], "git")
            self.assertEqual(meta["argv"][1], "diff")
            self.assertIn("-U3", meta["argv"])
            self.assertEqual(len(meta["git_argv"]), 3)
            self.assertEqual(meta["git_argv"][0][1], "log")

        # -- 5: an empty range is exit 2 and writes nothing -----------------
        def test_empty_range_is_exit_2_and_writes_nothing(self):
            self.assertEqual(
                main(["--repo", str(self.repo), "--base", "HEAD",
                      "--head", "HEAD", "--out", str(self.out)]), 2)
            self.assertFalse(self.out.exists())
            self.assertFalse(Path(str(self.out) + SIDECAR_SUFFIX).exists())

        # -- 6: a binary file in the diff is handled, not crashed on -------
        def test_binary_file_in_diff_is_handled(self):
            self._write("assets/logo.png",
                        bytes([0x89, 0x50, 0x4E, 0x47, 0x00, 0xFF, 0xFE, 0x01]
                              * 24), binary=True)
            self._write("src/app.py", "def a():\n    return 3\n")
            self._commit("add a binary asset")
            self.assertEqual(main(self._args()), 0)
            text = self._package()
            self.assertIn("assets/logo.png", text)
            self.assertIn("Binary files", text)
            self.assertEqual(self._sidecar()["capture_sha256"],
                             sha256_file(self.out))

        # -- 7: --changed-files restricts the diff -------------------------
        def test_changed_files_filter_restricts_the_diff(self):
            self._write("src/app.py", "def a():\n    return 4\n")
            self._write("src/other.py", "SECRET_MARKER = 1\n")
            self._commit()
            self.assertEqual(
                main(self._args("--changed-files", "src/app.py")), 0)
            text = self._package()
            self.assertIn("return 4", text)
            self.assertNotIn("SECRET_MARKER", text)
            self.assertIn("- Scope: `src/app.py`", text)

        # -- 8: a filter that matches nothing is an empty diff, exit 2 -----
        def test_changed_files_filter_matching_nothing_is_exit_2(self):
            self._write("src/app.py", "def a():\n    return 5\n")
            self._commit()
            self.assertEqual(
                main(self._args("--changed-files", "src/untouched.py")), 2)
            self.assertFalse(self.out.exists())

        # -- 9: an unresolvable ref is exit 2 ------------------------------
        def test_bad_base_ref_is_exit_2(self):
            self._write("src/app.py", "def a():\n    return 6\n")
            self._commit()
            self.assertEqual(
                main(["--repo", str(self.repo), "--base", "no-such-ref",
                      "--out", str(self.out)]), 2)
            self.assertFalse(self.out.exists())

        # -- 10: a non-repo directory is exit 2 ---------------------------
        def test_non_git_directory_is_exit_2(self):
            plain = self.dir / "plain"
            plain.mkdir()
            self.assertEqual(
                main(["--repo", str(plain), "--base", "HEAD~1",
                      "--out", str(self.out)]), 2)
            self.assertFalse(self.out.exists())

        # -- 11: missing required flags are exit 2 ------------------------
        def test_missing_required_flags_are_exit_2(self):
            self.assertEqual(
                main(["--repo", str(self.repo), "--out", str(self.out)]), 2)
            self.assertEqual(
                main(["--repo", str(self.repo), "--base", "HEAD~1"]), 2)
            self.assertFalse(self.out.exists())

        # -- 12: --context is honoured ------------------------------------
        def test_context_flag_changes_hunk_size(self):
            body = "".join(f"line {i}\n" for i in range(1, 41))
            self._write("src/big.txt", body)
            self._commit("seed")
            self._write("src/big.txt", body.replace("line 20\n", "LINE 20\n"))
            self._commit("touch the middle")
            self.assertEqual(main(self._args("--context", "1")), 0)
            narrow = len(self._package().splitlines())
            self.assertEqual(main(self._args("--context", "10")), 0)
            wide = len(self._package().splitlines())
            self.assertGreater(wide, narrow)

        # -- 13: a diff OF markdown does not break the fence --------------
        def test_markdown_backticks_get_a_longer_fence(self):
            self._write("docs/x.md", "# Doc\n\n```bash\nold\n```\n")
            self._commit("seed doc")
            self._write("docs/x.md", "# Doc\n\n```bash\nnew\n```\n")
            self._commit("edit doc")
            self.assertEqual(main(self._args()), 0)
            text = self._package()
            self.assertIn("````diff", text)
            self.assertIn("+new", text)

        # -- 14: the ledger records one line per run, on both exit paths ---
        def test_ledger_records_pass_and_error(self):
            ledger = self.dir / "gates.jsonl"
            self._write("src/app.py", "def a():\n    return 7\n")
            self._commit()
            self.assertEqual(
                main(self._args("--ledger", str(ledger),
                                "--milestone", "M3 — Order envelope")), 0)
            self.assertEqual(
                main(["--repo", str(self.repo), "--base", "HEAD",
                      "--head", "HEAD", "--out", str(self.out),
                      "--ledger", str(ledger), "--milestone", "M3"]), 2)
            rows = [json.loads(l) for l in
                    ledger.read_text(encoding="utf-8").splitlines() if l.strip()]
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["verdict"], "PASS")
            self.assertEqual(rows[0]["gate"], "review_package.py")
            self.assertEqual(rows[0]["milestone"], "M3 — Order envelope")
            self.assertEqual(rows[1]["verdict"], "ERROR")
            self.assertEqual(rows[1]["exit"], 2)

        # -- 15: non-ASCII content round-trips through the package --------
        def test_utf8_content_round_trips(self):
            self._write("src/café.py", "VALUE = 'résumé — ünïcode'\n")
            self._commit("add a unicode file")
            self.assertEqual(main(self._args()), 0)
            self.assertIn("résumé — ünïcode",
                          self.out.read_bytes().decode("utf-8"))

        # -- 16: a deletion is visible in the package (the tree hides it) --
        def test_deletion_is_visible_in_the_package(self):
            self._write("src/gone.py", "TO_BE_DELETED = 1\n")
            self._commit("seed a file")
            (self.repo / "src" / "gone.py").unlink()
            self._commit("delete it")
            self.assertEqual(main(self._args()), 0)
            text = self._package()
            self.assertIn("-TO_BE_DELETED = 1", text)

        # -- 17: WORKTREE renders UNCOMMITTED work (the build Phase 3 case) -
        def test_worktree_head_renders_uncommitted_changes(self):
            self._write("src/app.py", "def a():\n    return 99\n")   # no commit
            self.assertEqual(
                main(["--repo", str(self.repo), "--base", "HEAD",
                      "--head", "worktree", "--out", str(self.out)]), 0)
            text = self._package()
            self.assertIn("+    return 99", text)
            self.assertIn("- Head: uncommitted working tree", text)
            self.assertIn("(no commits in range)", text)
            self.assertEqual(self._sidecar()["head"], "WORKTREE")

        # -- 18: WORKTREE on a clean tree is still exit 2 ------------------
        def test_worktree_head_on_clean_tree_is_exit_2(self):
            self.assertEqual(
                main(["--repo", str(self.repo), "--base", "HEAD",
                      "--head", "WORKTREE", "--out", str(self.out)]), 2)
            self.assertFalse(self.out.exists())

        # -- 19: an unwritable --out path is exit 2 -----------------------
        def test_unwritable_out_path_is_exit_2(self):
            blocker = self.dir / "blocker"
            blocker.write_text("not a directory", encoding="utf-8")
            self._write("src/app.py", "def a():\n    return 8\n")
            self._commit()
            self.assertEqual(
                main(["--repo", str(self.repo), "--base", "HEAD~1",
                      "--out", str(blocker / "review-package.md")]), 2)

        # -- 20: a lockfile is excluded by default: header + sidecar name it,
        #        its hunk is absent from ## Diff -----------------------
        def test_default_excludes_hide_lockfile_from_diff(self):
            self._write("package-lock.json", "LOCK_V1\n")
            self._commit("seed lockfile")
            self._write("package-lock.json", "LOCK_V2\n")
            self._write("src/app.py", "def a():\n    return 10\n")
            self._commit("bump lockfile and change app")
            self.assertEqual(main(self._args()), 0)
            text = self._package()
            self.assertIn("- Excluded from diff (1): `package-lock.json`",
                          text)
            self.assertNotIn("LOCK_V2", text)
            self.assertIn("return 10", text)
            meta = self._sidecar()
            self.assertEqual(meta["excluded_files"], ["package-lock.json"])
            self.assertIn("**/package-lock.json", meta["exclude_patterns"])

        # -- 21: --no-default-excludes brings the lockfile back ------------
        def test_no_default_excludes_flag_restores_lockfile(self):
            self._write("package-lock.json", "LOCK_V1\n")
            self._commit("seed lockfile")
            self._write("package-lock.json", "LOCK_V2\n")
            self._commit("bump lockfile only")
            self.assertEqual(main(self._args("--no-default-excludes")), 0)
            text = self._package()
            self.assertIn("LOCK_V2", text)
            self.assertIn("- Excluded from diff: none", text)

        # -- 22: --exclude "*.md" removes a markdown file -------------------
        # git's glob pathspec magic does not cross a `/` boundary (fnmatch
        # with FNM_PATHNAME) -- `*.md` matches a ROOT-level file only, never
        # `docs/notes.md`. Verified against a throwaway repo; see report.
        def test_custom_exclude_pattern_removes_markdown_file(self):
            self._write("notes.md", "old notes\n")
            self._commit("seed doc")
            self._write("notes.md", "new notes\n")
            self._write("src/app.py", "def a():\n    return 11\n")
            self._commit("edit doc and app")
            self.assertEqual(main(self._args("--exclude", "*.md")), 0)
            text = self._package()
            self.assertNotIn("new notes", text)
            self.assertIn("return 11", text)
            self.assertIn("- Excluded from diff (1): `notes.md`", text)

        # -- 23: the all-excluded case is exit 2 with the distinct message -
        def test_all_excluded_diff_is_exit_2_with_distinct_message(self):
            self._write("package-lock.json", "LOCK_V1\n")
            self._commit("seed lockfile")
            self._write("package-lock.json", "LOCK_V2\n")
            self._commit("bump lockfile only")
            self.assertEqual(main(self._args()), 2)
            self.assertFalse(self.out.exists())
            args = build_parser().parse_args(self._args())
            with self.assertRaises(PackageError) as ctx:
                generate(args)
            self.assertIn("every changed path was excluded by pattern",
                          str(ctx.exception))

        # -- 24: excludes never filter ## Commits ---------------------------
        def test_excludes_never_filter_commits_section(self):
            self._write("package-lock.json", "LOCK_V1\n")
            self._commit("seed lockfile")
            self._write("package-lock.json", "LOCK_V2\n")
            self._commit("lockfile-only bump")
            self._write("src/app.py", "def a():\n    return 13\n")
            self._commit("change app")
            self.assertEqual(
                main(["--repo", str(self.repo), "--base", "HEAD~2",
                      "--out", str(self.out)]), 0)
            text = self._package()
            self.assertIn("lockfile-only bump", text)     # ## Commits
            self.assertNotIn("LOCK_V2", text)              # ## Diff, filtered

        # -- 25: --changed-files naming ONLY an excluded file is exit 2 ----
        def test_changed_files_naming_only_excluded_file_is_exit_2(self):
            self._write("package-lock.json", "LOCK_V1\n")
            self._commit("seed lockfile")
            self._write("package-lock.json", "LOCK_V2\n")
            self._commit("bump lockfile only")
            self.assertEqual(
                main(self._args("--changed-files", "package-lock.json")), 2)
            self.assertFalse(self.out.exists())
            args = build_parser().parse_args(
                self._args("--changed-files", "package-lock.json"))
            with self.assertRaises(PackageError) as ctx:
                generate(args)
            self.assertIn("every changed path was excluded by pattern",
                          str(ctx.exception))

        # -- 26: under the ceiling passes and reports diff_lines -----------
        def test_under_ceiling_passes_and_reports_diff_lines(self):
            self._write("src/app.py", "def a():\n    return 14\n")
            self._commit("small change")
            self.assertEqual(main(self._args("--max-diff-lines", "10")), 0)
            meta = self._sidecar()
            self.assertEqual(meta["diff_lines"], 2)
            self.assertEqual(meta["max_diff_lines"], 10)

        # -- 27: over the ceiling with no waiver is exit 2, nothing written -
        def test_over_ceiling_no_waiver_is_exit_2_nothing_written(self):
            self._write("src/app.py", "def a():\n    return 15\n")
            self._commit("small change")
            self.assertEqual(main(self._args("--max-diff-lines", "1")), 2)
            self.assertFalse(self.out.exists())
            self.assertFalse(Path(str(self.out) + SIDECAR_SUFFIX).exists())
            args = build_parser().parse_args(
                self._args("--max-diff-lines", "1"))
            with self.assertRaises(PackageError) as ctx:
                generate(args)
            self.assertIn("no --waiver was given", str(ctx.exception))

        # -- 28: over the ceiling with a placeholder waiver body is exit 2 -
        def test_over_ceiling_with_placeholder_waiver_is_exit_2(self):
            self._write("src/app.py", "def a():\n    return 16\n")
            self._commit("small change")
            waiver = self.dir / "waiver.md"
            waiver.write_text("## Size waiver\n\nTODO\n", encoding="utf-8")
            self.assertEqual(
                main(self._args("--max-diff-lines", "1",
                                "--waiver", str(waiver))), 2)
            self.assertFalse(self.out.exists())

        # -- 29: over the ceiling with a real waiver body passes -----------
        def test_over_ceiling_with_real_waiver_passes_and_renders_header(self):
            self._write("src/app.py", "def a():\n    return 17\n")
            self._commit("small change")
            waiver = self.dir / "waiver.md"
            waiver.write_text(
                "## Size waiver\n\nApproved by the user: this touches only "
                "one line and the fix is not worth splitting.\n",
                encoding="utf-8")
            self.assertEqual(
                main(self._args("--max-diff-lines", "1",
                                "--waiver", str(waiver))), 0)
            text = self._package()
            self.assertIn(
                f"- Size waiver: `{waiver}` (1 lines over "
                "--max-diff-lines 1)", text)
            meta = self._sidecar()
            self.assertTrue(meta["size_waiver"]["satisfied"])

        # -- 30: --waiver without --max-diff-lines is exit 2 ---------------
        def test_waiver_without_max_diff_lines_is_exit_2(self):
            self._write("src/app.py", "def a():\n    return 18\n")
            self._commit()
            waiver = self.dir / "waiver.md"
            waiver.write_text("## Size waiver\n\nfine\n", encoding="utf-8")
            self.assertEqual(main(self._args("--waiver", str(waiver))), 2)
            self.assertFalse(self.out.exists())

        # -- 31: --max-diff-lines 0 is exit 2 -------------------------------
        def test_max_diff_lines_zero_is_exit_2(self):
            self._write("src/app.py", "def a():\n    return 19\n")
            self._commit()
            self.assertEqual(main(self._args("--max-diff-lines", "0")), 2)
            self.assertFalse(self.out.exists())

        # -- 32: the diff-line count ignores +++/--- file header lines -----
        def test_diff_line_count_ignores_file_header_lines(self):
            self._write("src/app.py", "def a():\n    return 20\n")
            self._commit("small change")
            args = build_parser().parse_args(self._args())
            payload = generate(args)
            self.assertIn("--- a/src/app.py", self._package())
            self.assertIn("+++ b/src/app.py", self._package())
            self.assertEqual(payload["diff_lines"], 2)

        # -- 33: the diff-line count is taken AFTER excludes ---------------
        def test_diff_line_count_is_taken_after_excludes(self):
            self._write("package-lock.json", "LOCK_V1\n" * 50)
            self._commit("seed big lockfile")
            self._write("package-lock.json", "LOCK_V2\n" * 50)
            self._write("src/app.py", "def a():\n    return 21\n")
            self._commit("bump big lockfile and change app")
            self.assertEqual(main(self._args("--max-diff-lines", "5")), 0)
            meta = self._sidecar()
            self.assertEqual(meta["diff_lines"], 2)

        # -- 34: default excludes reach a NESTED lockfile, not just the root
        #        (the monorepo case DEFAULT_EXCLUDES's `**/` prefix exists
        #        for) ---------------------------------------------------
        def test_default_excludes_reach_nested_lockfile(self):
            self._write("frontend/package-lock.json", "LOCK_V1\n")
            self._commit("seed nested lockfile")
            self._write("frontend/package-lock.json", "LOCK_V2\n")
            self._write("src/app.py", "def a():\n    return 22\n")
            self._commit("bump nested lockfile and change app")
            self.assertEqual(main(self._args()), 0)
            text = self._package()
            self.assertIn(
                "- Excluded from diff (1): `frontend/package-lock.json`",
                text)
            self.assertNotIn("LOCK_V2", text)
            self.assertIn("return 22", text)
            meta = self._sidecar()
            self.assertEqual(meta["excluded_files"],
                             ["frontend/package-lock.json"])

    suite = unittest.defaultTestLoader.loadTestsFromTestCase(
        ReviewPackageTests)
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
