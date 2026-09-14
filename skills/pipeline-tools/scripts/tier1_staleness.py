#!/usr/bin/env python3
"""Mechanical gate: WHICH Tier-1 docs went stale, not just THAT the repo drifted.

`check_tier1_provenance.py` can say "repo X drifted past its stamp" but a real
feature has ~14 Tier-1 docs under `.docs/summary/{feature}/` citing ~500
source paths between them, and drift alone does not say which docs are
affected. This gate reads the same provenance stamp, diffs each stamped repo
from the stamped sha to HEAD, extracts the source paths each doc cites, and
reports per-doc whether anything it cites actually changed -- so a refresh
re-runs only the stale docs (CLAUDE.md convention #9: a prose "the map might
be stale" warning is asked to re-read a header at the moment the phase most
wants to close; this is that check made mechanical).

**Never writes to any doc. Never re-stamps.** The stamp itself -- read at
write time by Echo, per `bgpdd-discovery/SKILL.md` section 1 -- is untouched
by design; this gate only reads it and the git history since. Runtime
neutrality (CLAUDE.md convention #5): it shells out to `git`, nothing IDE- or
LLM-specific.

Reuse, and the one deliberate non-reuse
----------------------------------------
Stamp parsing (the header, its `YYYY-MM-DD` date, and its per-repo 40-hex sha
lines) is READ exactly the way `check_tier1_provenance.py` does it: this
module imports `header_of`, `stamped_repos`, `git`, `sha_resolves`,
`GateError` and `parse_repo_arg` from it rather than re-deriving the same
regex grammar a second time.

The ledger-chaining primitives (`sha256_file`, `ledger_line_hash`,
`ledger_prev_hash`, `ledger_self_hash`, `append_ledger`) are **duplicated**
here instead of imported. `check_tier1_provenance.py`'s own docstring names
this the family convention -- "byte-identical in every gate in this family
... one file each, no shared module" -- and there is a concrete reason beyond
convention: `append_ledger` stamps each record's `"gate"` field with
`Path(__file__).name`, which binds to the *defining* module at import time.
Importing it here would silently mislabel every record this script writes as
`check_tier1_provenance.py`.

What "stale" means here
------------------------
For each doc under `.docs/summary/{feature}/` (recursively, `.md` only) plus
`.docs/summary/context.md`:

1. Read the stamp from the doc's own header (everything above its first
   `## ` heading) -- `stamp_source: "own"`. The discovery contract
   (`bgpdd-discovery/SKILL.md` section 1 and Phase 4) stamps only
   `context.md` and `{feature}/overview.md`; every per-API `{api}.md` and
   `QA/*.md` doc is NEVER stamped by design. So a doc under `{feature}/`
   with no stamp of its own INHERITS `{feature}/overview.md`'s stamp instead
   of reading as a false `unstamped` finding -- `stamp_source:
   "inherited:overview.md"` -- and its verdict computes normally from there.
   `context.md` never inherits (there is nothing above it to inherit from).
   `unstamped` remains only when `overview.md` itself carries no stamp, in
   which case every stampless sibling is `unstamped` too and the feature-level
   `warnings` says why once rather than once per doc.
2. For each repo the (own or inherited) stamp names that the caller also
   passed via `--repo`, run `git diff --name-status --diff-filter=ADMR -M
   <stamped-sha> HEAD` in that repo (renames come back as old-path/new-path
   pairs -- `--name-status` carries both; `--name-only` alone would drop the
   old path) and `git rev-list --count <stamped-sha>..HEAD` for
   `commits_behind`. A sha git cannot resolve is `stamp_unresolvable`, never
   a crash.
3. Extract cited source paths from the doc's full text, in TWO classes:
   - **Path-shaped** -- multi-segment slash-or-backslash tokens ending in a
     source extension (`.cs .ts .tsx .vue .js .py .ps1 .sql .json .yaml .yml
     .csproj .razor .cshtml`), normalised to forward slashes. Matched against
     the changed-file list by trailing path segments in EITHER direction (a
     citation may be repo-root relative and shorter than the changed path,
     e.g. `Features/X/Handler.cs` against `apis/Billing/.../Features/X/
     Handler.cs`; or it may carry a leading repo-folder prefix the diff
     output does not, e.g. `gorelo_backend/Features/X/Handler.cs`) -- so
     citation style does not matter, per the brief. Hits land in `changed` /
     `deleted_or_renamed`.
   - **Bare filename** -- a single-segment token with a source extension and
     no path separator at all (`` `AlertHelper.cs` `` -- most of Echo's
     `overview.md` citations are this shape). Matched against the
     added/modified file list by BASENAME ONLY: when exactly one changed
     file has that basename, it counts as stale under `changed_by_basename`;
     when two or more changed files share the basename, the citation cannot
     be resolved to one of them, so it is reported under
     `ambiguous_basenames` (with the collision count) and does NOT count
     toward stale. A bare name whose basename is already covered by a
     path-shaped citation in the same doc is skipped here -- the path-shaped
     rule already resolved it precisely, and path-shaped citations take
     precedence.
4. Verdict per doc: `fresh` (stamped -- own or inherited --, resolvable,
   nothing cited changed), `stale` (something cited was added/modified,
   deleted/renamed under its cited name, or uniquely matched by basename),
   `unstamped` (no own stamp and no inheritable one), `unresolvable` (a
   stamped sha this gate cannot resolve, or a stamped repo the caller did not
   pass via `--repo`).

Usage:
    python tier1_staleness.py --summary-root .docs/summary --feature <id> \
        --repo <name>=<path> [--repo ...] [--json|--markdown] \
        [--fail-on-stale] [--ledger <path>]
    python tier1_staleness.py --self-test

Exit 0 advisory report (the default -- matches `check_tier1_provenance.py`'s
own "drift is a warning" stance: a mechanical answer to "which docs" should
not itself halt a pipeline that only asked to look); 1 when `--fail-on-stale`
is given AND at least one doc is `stale`/`unstamped`/`unresolvable`; 2 usage
(bad `--summary-root`, no `--repo`, missing `--feature`, git unusable).
Pure standard library.
"""
import argparse
import hashlib
import json
import re
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from check_tier1_provenance import (
    GateError,
    git,
    header_of,
    parse_repo_arg,
    sha_resolves,
    stamped_repos,
)

SOURCE_EXTS = ("cs", "ts", "tsx", "vue", "js", "py", "ps1", "sql", "json",
               "yaml", "yml", "csproj", "razor", "cshtml")
CITED_PATH_RE = re.compile(
    r"(?<![\w/\\.-])([A-Za-z0-9_.\-]+(?:[\\/][A-Za-z0-9_.\-]+)+\.(?:%s))(?!\w)"
    % "|".join(SOURCE_EXTS), re.IGNORECASE)
# Single-segment filename, source extension, no path separator at all. The
# same left/right boundary as CITED_PATH_RE (excluding '/' and '\\' too) means
# a name immediately preceded by a separator -- i.e. the tail of a path
# CITED_PATH_RE already matched -- is NOT re-captured here.
BARE_NAME_RE = re.compile(
    r"(?<![\w/\\.-])([A-Za-z0-9_.\-]+\.(?:%s))(?!\w)" % "|".join(SOURCE_EXTS),
    re.IGNORECASE)
CONTEXT_ARTIFACT = "context.md"
OVERVIEW_ARTIFACT = "overview.md"


# --- ledger primitives: duplicated, not imported -- see module docstring ---

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
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
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


# --- citation extraction and matching --------------------------------------

def normalize_path(p):
    return p.replace("\\", "/").strip("/")


def extract_cited_paths(text):
    """Normalised, deduplicated cited source paths found anywhere in `text`."""
    return sorted({normalize_path(m.group(1))
                   for m in CITED_PATH_RE.finditer(text)})


def extract_bare_filenames(text, path_basenames=()):
    """Standalone (no-path-separator) filename citations, deduplicated.

    `path_basenames` are the basenames already covered by a path-shaped
    citation in the same doc -- excluded here so a file cited once with a
    full path and once bare is not double-classified (path-shaped takes
    precedence, per the brief).
    """
    exclude = set(path_basenames)
    return sorted({m.group(1) for m in BARE_NAME_RE.finditer(text)} - exclude)


def path_suffix_match(a, b):
    """True when the two paths' TRAILING segments agree, up to the shorter.

    Symmetric on purpose: a citation may be repo-root relative and shorter
    than the diff's path (extra leading service/module dirs), or it may carry
    a leading repo-folder prefix the diff output never has. Either way,
    "citation style does not matter" (the brief) means comparing the tail.
    """
    a_segs = [s for s in a.split("/") if s]
    b_segs = [s for s in b.split("/") if s]
    if not a_segs or not b_segs:
        return False
    n = min(len(a_segs), len(b_segs))
    return a_segs[-n:] == b_segs[-n:]


# --- git plumbing ------------------------------------------------------------

def git_diff(repo_path, sha):
    """(adds_mods, renames, deletes) via `git diff --name-status -M ADMR`.

    `renames` is a list of (old_path, new_path); `adds_mods` and `deletes`
    are flat path lists. All normalised to forward slashes.
    """
    proc = git(repo_path, "diff", "--name-status", "--diff-filter=ADMR",
              "-M", sha, "HEAD")
    adds_mods, renames, deletes = [], [], []
    if proc.returncode != 0:
        return adds_mods, renames, deletes
    for line in proc.stdout.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        status = parts[0]
        if status.startswith("R"):
            if len(parts) >= 3:
                renames.append((normalize_path(parts[1]), normalize_path(parts[2])))
        elif status.startswith("D"):
            if len(parts) >= 2:
                deletes.append(normalize_path(parts[1]))
        else:  # A or M
            if len(parts) >= 2:
                adds_mods.append(normalize_path(parts[1]))
    return adds_mods, renames, deletes


def commits_behind(repo_path, sha):
    proc = git(repo_path, "rev-list", "--count", f"{sha}..HEAD")
    if proc.returncode != 0:
        return None
    try:
        return int(proc.stdout.strip())
    except ValueError:
        return None


def classify_citation(cited, adds_mods, renames, deletes):
    """"changed" | "deleted_or_renamed" | None for one cited path."""
    for p in adds_mods:
        if path_suffix_match(cited, p):
            return "changed"
    for old, _new in renames:
        if path_suffix_match(cited, old):
            return "deleted_or_renamed"
    for p in deletes:
        if path_suffix_match(cited, p):
            return "deleted_or_renamed"
    return None


def classify_bare_filenames(bare_names, adds_mods):
    """(changed_by_basename, ambiguous_basenames) for a doc's bare citations.

    Matched against `adds_mods` ONLY (added/modified files) -- deliberately
    narrower than the path-shaped rule's adds+renames+deletes, since a bare
    name has no directory to disambiguate a rename or deletion by, and the
    brief asks only for a `changed_by_basename` class. A basename claimed by
    exactly one changed file counts toward stale; two or more is an
    unresolvable collision, reported (with its count) but never stale.
    """
    by_basename = {}
    for p in adds_mods:
        b = p.rsplit("/", 1)[-1]
        by_basename.setdefault(b, set()).add(p)
    changed, ambiguous = [], []
    for name in bare_names:
        matches = by_basename.get(name)
        if not matches:
            continue
        if len(matches) == 1:
            changed.append(name)
        else:
            ambiguous.append({"name": name, "count": len(matches)})
    return sorted(changed), sorted(ambiguous, key=lambda x: x["name"])


# --- per-doc and feature-level report ---------------------------------------

def _loose_key(s):
    """Casefolded, separator-stripped form used only to MATCH a --repo name
    against a stamped key -- never to key the reported JSON.

    `stamped_repos()` (imported) already casefolds and strips markdown
    decoration including underscores (`_backend_` reads as italics), so a
    stamped `gorelo_backend` surfaces as the key `gorelobackend`. A plain
    equality check against a --repo name typed with its natural underscore
    would then always miss. This collapses whitespace/`_`/`-` on BOTH sides
    before comparing, which is a property of this script's own repo-name
    matching, not a change to the shared parser.
    """
    return re.sub(r"[\s_\-]+", "", s.casefold())


def process_doc(doc_path, repos, inherited_stamp=None):
    """One doc's staleness report.

    `repos` is [(name, Path), ...] from --repo. `inherited_stamp` is the
    `stamped_repos()` dict read from `{feature}/overview.md`, passed in by
    `build_report` for every doc except `context.md` and `overview.md`
    itself -- used only when this doc carries no stamp of its own.
    """
    text = doc_path.read_text(encoding="utf-8-sig", errors="replace")
    header = header_of(text)
    own_stamped = stamped_repos(header)
    if own_stamped:
        stamped, stamp_source = own_stamped, "own"
    elif inherited_stamp:
        stamped, stamp_source = inherited_stamp, "inherited:overview.md"
    else:
        stamped, stamp_source = {}, None

    result = {
        "path": str(doc_path),
        "stamp_source": stamp_source,
        "stamped": {},
        "commits_behind": {},
        "cited_paths": 0,
        "cited_basenames": 0,
        "changed": [],
        "deleted_or_renamed": [],
        "changed_by_basename": [],
        "ambiguous_basenames": [],
        "verdict": None,
        "findings": [],
    }
    if not stamped:
        result["verdict"] = "unstamped"
        return result

    single = len(stamped) == 1
    repo_matches = []  # (name, path, sha)
    for name, path in repos:
        entry = None
        if single:
            entry = next(iter(stamped.values()))
        else:
            key = name.casefold()
            loose = _loose_key(name)
            for skey, e in stamped.items():
                if skey == key or _loose_key(skey) == loose:
                    entry = e
                    break
            if entry is None:
                for skey, e in stamped.items():
                    skey_loose = _loose_key(skey)
                    if loose and (loose in skey_loose or skey_loose in loose):
                        entry = e
                        break
        if entry is not None:
            repo_matches.append((name, path, entry["sha"]))

    if not repo_matches:
        result["verdict"] = "unresolvable"
        result["stamped"] = {e["name"]: e["sha"] for e in stamped.values()}
        result["findings"].append({
            "code": "repo_not_provided",
            "detail": f"{doc_path}: stamped for "
                      f"{sorted(e['name'] for e in stamped.values())} but "
                      "none of the --repo names given to this run match; "
                      "freshness cannot be determined"})
        return result

    cited = extract_cited_paths(text)
    path_basenames = {p.rsplit("/", 1)[-1] for p in cited}
    bare = extract_bare_filenames(text, path_basenames)
    result["cited_paths"] = len(cited)
    result["cited_basenames"] = len(bare)

    any_unresolvable = False
    changed_hits, deleted_hits = set(), set()
    combined_adds_mods = []

    for name, path, sha in repo_matches:
        # `path` is already known to be a directory holding a git repo --
        # `build_report` validates every --repo upfront (exit 2, not a
        # per-doc finding: an unusable repo makes the WHOLE run
        # unperformable, not just this one doc's verdict).
        result["stamped"][name] = sha
        if not sha_resolves(path, sha):
            result["commits_behind"][name] = None
            any_unresolvable = True
            result["findings"].append({
                "code": "stamp_unresolvable", "repo": name, "sha": sha,
                "detail": f"{doc_path}: stamped sha {sha[:12]} does not "
                          f"resolve to a commit in repo '{name}'"})
            continue
        result["commits_behind"][name] = commits_behind(path, sha)
        adds_mods, renames, deletes = git_diff(path, sha)
        combined_adds_mods.extend(adds_mods)
        for c in cited:
            verdict = classify_citation(c, adds_mods, renames, deletes)
            if verdict == "changed":
                changed_hits.add(c)
            elif verdict == "deleted_or_renamed":
                deleted_hits.add(c)

    result["changed"] = sorted(changed_hits)
    result["deleted_or_renamed"] = sorted(deleted_hits)
    # Basename matching is done ONCE against the combined changed-file
    # universe across every stamped repo this doc scopes -- a collision
    # between two DIFFERENT repos' same-named files is exactly the kind of
    # ambiguity `ambiguous_basenames` exists to catch, so it must not be
    # hidden by judging each repo's diff in isolation.
    result["changed_by_basename"], result["ambiguous_basenames"] = (
        classify_bare_filenames(bare, combined_adds_mods))

    if any_unresolvable:
        result["verdict"] = "unresolvable"
    elif (result["changed"] or result["deleted_or_renamed"]
          or result["changed_by_basename"]):
        result["verdict"] = "stale"
    else:
        result["verdict"] = "fresh"
    return result


def validate_repo(name, path):
    """Raise GateError unless `path` is a directory holding a git repo.

    Folder convention: anything that makes the check unperformable is exit 2,
    never a per-doc finding folded into an exit-0 report -- a bad --repo
    would otherwise read as "nothing changed" (every doc scoped to it falls
    through to `repo_not_provided`, which never fails without
    `--fail-on-stale`) instead of "this run could not check what it claims
    to have checked."
    """
    if not path.is_dir():
        raise GateError(f"--repo {name} is not a directory: {path}")
    proc = git(path, "rev-parse", "--git-dir")
    if proc.returncode != 0:
        raise GateError(f"--repo {name} is not a git repository: {path}")


def collect_docs(root, feature):
    """Docs to check, or raise -- a missing --feature directory is exit 2,
    not a warning: there is nothing to report on, so a 0-doc PASS would read
    as "everything is fresh" rather than "this feature was never checked."
    """
    docs = []
    context = root / CONTEXT_ARTIFACT
    if context.is_file():
        docs.append(context)
    feature_dir = root / feature
    if not feature_dir.is_dir():
        raise GateError(f"--feature directory does not exist: {feature_dir}")
    docs.extend(sorted(p for p in feature_dir.rglob("*.md") if p.is_file()))
    return docs


def build_report(summary_root, feature, repos):
    root = Path(summary_root)
    if not root.is_dir():
        raise GateError(f"--summary-root is not a directory: {summary_root}")
    if not repos:
        raise GateError("at least one --repo is required")
    if not feature:
        raise GateError("--feature is required")
    for name, path in repos:
        validate_repo(name, path)

    warnings = []
    if not (root / CONTEXT_ARTIFACT).is_file():
        warnings.append(f"{root / CONTEXT_ARTIFACT} not found; skipped")
    docs = collect_docs(root, feature)

    # {feature}/overview.md's own stamp, read once, so every OTHER doc under
    # {feature}/ that carries no stamp of its own can inherit it instead of
    # reporting a false `unstamped` -- the per-API {api}.md and QA/*.md docs
    # are never stamped by design (bgpdd-discovery SKILL.md section 1, Phase
    # 4). context.md is the project-wide root and never inherits.
    context_path = root / CONTEXT_ARTIFACT
    overview_path = root / feature / OVERVIEW_ARTIFACT
    overview_stamped = {}
    if overview_path.is_file():
        overview_text = overview_path.read_text(encoding="utf-8-sig",
                                                 errors="replace")
        overview_stamped = stamped_repos(header_of(overview_text))

    doc_reports = []
    for doc in docs:
        if doc in (context_path, overview_path):
            doc_reports.append(process_doc(doc, repos))
        else:
            doc_reports.append(process_doc(doc, repos, overview_stamped))

    if not overview_stamped:
        cascaded = [d["path"] for d in doc_reports
                   if d["path"] not in (str(context_path), str(overview_path))
                   and d["verdict"] == "unstamped"]
        if cascaded:
            reason = ("does not exist" if not overview_path.is_file()
                      else "carries no stamp of its own")
            warnings.append(
                f"{overview_path} {reason}, so {len(cascaded)} sibling "
                f"doc(s) under .docs/summary/{feature}/ have nothing to "
                "inherit and report unstamped too")

    counts = {"fresh": 0, "stale": 0, "unstamped": 0, "unresolvable": 0}
    for d in doc_reports:
        counts[d["verdict"]] = counts.get(d["verdict"], 0) + 1
    stale_docs = sorted(
        ({"path": d["path"],
          "changed_count": (len(d["changed"]) + len(d["deleted_or_renamed"])
                            + len(d["changed_by_basename"]))}
         for d in doc_reports if d["verdict"] == "stale"),
        key=lambda x: -x["changed_count"])

    any_finding = any(d["verdict"] in ("stale", "unstamped", "unresolvable")
                      for d in doc_reports)
    return {
        "result": "FAIL" if any_finding else "PASS",
        "summary_root": str(summary_root),
        "feature": feature,
        "repos": [{"name": n, "path": str(p)} for n, p in repos],
        "docs": doc_reports,
        "summary": {"counts": counts, "stale_docs": stale_docs},
        "warnings": warnings,
        "error": None,
    }


def render_markdown(report):
    lines = [f"### Tier-1 staleness -- feature `{report['feature']}`", ""]
    lines.append("| doc | stamp | verdict | commits behind | changed | "
                 "by basename | ambiguous | deleted/renamed |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for d in report["docs"]:
        behind = ", ".join(f"{k}:{v if v is not None else '?'}"
                           for k, v in d["commits_behind"].items()) or "-"
        stamp = d["stamp_source"] or "-"
        lines.append(f"| {d['path']} | {stamp} | {d['verdict']} | {behind} | "
                     f"{len(d['changed'])} | {len(d['changed_by_basename'])} | "
                     f"{len(d['ambiguous_basenames'])} | "
                     f"{len(d['deleted_or_renamed'])} |")
    lines.append("")
    for w in report["warnings"]:
        lines.append(f"> {w}")
    if report["warnings"]:
        lines.append("")
    stale = report["summary"]["stale_docs"]
    if stale:
        lines.append("**Stale docs (by changed citations):**")
        for s in stale:
            lines.append(f"- {s['path']} ({s['changed_count']})")
    else:
        lines.append("No stale docs.")
    return "\n".join(lines)


def main(argv):
    parser = argparse.ArgumentParser(prog="tier1_staleness.py")
    parser.add_argument("--summary-root", default=".docs/summary",
                        help="Tier-1 knowledge base root (default .docs/summary)")
    parser.add_argument("--feature", help="the feature id under --summary-root")
    parser.add_argument("--repo", action="append", default=[],
                        help="stamped repository as [<name>=]<path>; repeat "
                             "once per repo")
    parser.add_argument("--json", action="store_true",
                        help="print the full JSON report (default)")
    parser.add_argument("--markdown", action="store_true",
                        help="print a compact table instead of JSON")
    parser.add_argument("--fail-on-stale", action="store_true",
                        help="exit 1 when any doc is stale/unstamped/"
                             "unresolvable; without it the report is "
                             "advisory and always exits 0")
    parser.add_argument("--ledger", help="append one JSON record per run to this path")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)

    if args.self_test:
        return run_self_test()

    def finish(code, verdict, inputs=()):
        append_ledger(args.ledger, argv, None, list(inputs), verdict, code)
        return code

    if args.json and args.markdown:
        print(json.dumps({"result": "ERROR",
                          "error": "--json and --markdown are mutually "
                                   "exclusive"}))
        return finish(2, "ERROR")

    try:
        repos = [parse_repo_arg(raw) for raw in args.repo]
        report = build_report(args.summary_root, args.feature, repos)
    except GateError as exc:
        print(json.dumps({"result": "ERROR", "error": str(exc)}))
        return finish(2, "ERROR")

    if args.markdown:
        print(render_markdown(report))
    else:
        print(json.dumps(report, indent=2))

    inputs = [d["path"] for d in report["docs"]]
    code = 1 if (args.fail_on_stale and report["result"] == "FAIL") else 0
    return finish(code, report["result"], inputs)


def run_self_test():
    import shutil

    class StalenessTests(unittest.TestCase):
        def setUp(self):
            self.dir = Path(tempfile.mkdtemp())
            self.summary = self.dir / ".docs" / "summary"
            (self.summary / "f1").mkdir(parents=True)
            self.app = self.dir / "app"
            self.app.mkdir()
            self.web = self.dir / "web"
            self.web.mkdir()
            self.app_sha1 = self.init_repo(self.app, {
                "Features/Billing/Handler.cs": "one",
                "Features/Untouched/Nobody.cs": "one",
            })
            self.web_sha1 = self.init_repo(self.web, {
                "src/Legacy/Old.ts": "one",
                "src/Reporting/Report.ts": "one",
            })

        def tearDown(self):
            shutil.rmtree(self.dir, ignore_errors=True)

        # --- git fixture helpers ---------------------------------------
        def run_git(self, repo, *args):
            try:
                return subprocess.run(["git", "-C", str(repo)] + list(args),
                                      capture_output=True, text=True, timeout=120)
            except FileNotFoundError:
                self.skipTest("git not available")

        def init_repo(self, repo, files):
            proc = self.run_git(repo, "init", "-q")
            if proc.returncode != 0:
                self.skipTest("git init failed")
            self.run_git(repo, "config", "user.email", "t@t.t")
            self.run_git(repo, "config", "user.name", "t")
            for rel, content in files.items():
                p = repo / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(content, encoding="utf-8")
            self.run_git(repo, "add", "-A")
            self.run_git(repo, "commit", "-qm", "init")
            return self.run_git(repo, "rev-parse", "HEAD").stdout.strip()

        def advance_app(self):
            (self.app / "Features/Billing/Handler.cs").write_text(
                "two", encoding="utf-8")
            (self.app / "Features/Untouched/Nobody.cs").write_text(
                "two", encoding="utf-8")
            self.run_git(self.app, "add", "-A")
            self.run_git(self.app, "commit", "-qm", "advance app")

        def advance_web_rename(self):
            self.run_git(self.web, "mv", "src/Legacy/Old.ts",
                        "src/Legacy/New.ts")
            self.run_git(self.web, "commit", "-qm", "rename")

        # --- doc writers ---------------------------------------------------
        def stamp(self, date="2026-09-07", app_sha=None, web_sha=None):
            return (f"> Provenance -- {date}\n"
                    f"> app: `{app_sha or self.app_sha1}`\n"
                    f"> web: `{web_sha or self.web_sha1}`\n")

        def write(self, relpath, body):
            p = self.summary / relpath
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(body, encoding="utf-8")

        def write_all_docs(self):
            self.write("context.md",
                       f"# Context\n\n{self.stamp()}\n## Stacks\n\nnone\n")
            self.write("f1/overview.md",
                       f"# Overview\n\n{self.stamp()}\n## Notes\n\n"
                       f"See `src/Legacy/Old.ts` for the legacy handler.\n")
            self.write("f1/api-a.md",
                       f"# API A\n\n{self.stamp()}\n## Notes\n\n"
                       f"See `Features/Billing/Handler.cs`.\n")
            self.write("f1/api-b.md",
                       f"# API B\n\n{self.stamp()}\n## Notes\n\n"
                       f"See `src/Reporting/Report.ts`.\n")

        def report(self, feature="f1", repos=None):
            repos = repos or [("app", self.app), ("web", self.web)]
            return build_report(self.summary, feature, repos)

        def doc(self, report, name):
            for d in report["docs"]:
                if d["path"].replace("\\", "/").endswith(name):
                    return d
            self.fail(f"{name} not found in report docs")

        # --- staleness verdicts ----------------------------------------
        def test_stale_via_changed_citation(self):
            self.write_all_docs()
            self.advance_app()
            a = self.doc(self.report(), "api-a.md")
            self.assertEqual(a["verdict"], "stale")
            self.assertIn("Features/Billing/Handler.cs", a["changed"])
            self.assertEqual(a["deleted_or_renamed"], [])

        def test_stale_via_deleted_or_renamed(self):
            self.write_all_docs()
            self.advance_web_rename()
            o = self.doc(self.report(), "overview.md")
            self.assertEqual(o["verdict"], "stale")
            self.assertIn("src/Legacy/Old.ts", o["deleted_or_renamed"])

        def test_fresh_despite_commits_behind(self):
            self.write_all_docs()
            self.advance_web_rename()
            b = self.doc(self.report(), "api-b.md")
            self.assertEqual(b["verdict"], "fresh")
            self.assertEqual(b["commits_behind"]["web"], 1)

        # --- inherited stamps: a stampless doc reads overview.md's ---------
        def test_inherited_stamp_computes_fresh(self):
            """A per-API/QA doc is never stamped by design; it should
            inherit overview.md's stamp rather than read as `unstamped`."""
            self.write_all_docs()
            self.write("f1/QA/manual-testing.md",
                       "# Manual Testing\n\nNo stamp here -- QA docs never "
                       "carry one.\n\n## Cases\n\nSee "
                       "`Features/Billing/Handler.cs`.\n")
            q = self.doc(self.report(), "QA/manual-testing.md")
            self.assertEqual(q["stamp_source"], "inherited:overview.md")
            self.assertEqual(q["verdict"], "fresh")
            self.assertEqual(q["stamped"]["app"], self.app_sha1)

        def test_inherited_stamp_computes_stale(self):
            self.write_all_docs()
            self.write("f1/QA/manual-testing.md",
                       "# Manual Testing\n\nNo stamp here.\n\n## Cases\n\n"
                       "See `Features/Billing/Handler.cs`.\n")
            self.advance_app()
            q = self.doc(self.report(), "QA/manual-testing.md")
            self.assertEqual(q["stamp_source"], "inherited:overview.md")
            self.assertEqual(q["verdict"], "stale")
            self.assertIn("Features/Billing/Handler.cs", q["changed"])

        def test_unstamped_overview_cascades(self):
            """Only when overview.md ITSELF has no stamp does `unstamped`
            still apply -- and it cascades to every stampless sibling,
            explained once in `warnings` rather than once per doc."""
            self.write("context.md",
                       f"# Context\n\n{self.stamp()}\n## Stacks\n\nnone\n")
            self.write("f1/overview.md", "# Overview\n\nNo stamp here.\n\n"
                                         "## Notes\n")
            self.write("f1/QA/manual-testing.md",
                       "# Manual Testing\n\nNo stamp here.\n\n## Cases\n\n"
                       "none cited\n")
            r = self.report()
            o = self.doc(r, "overview.md")
            q = self.doc(r, "QA/manual-testing.md")
            self.assertEqual(o["verdict"], "unstamped")
            self.assertIsNone(o["stamp_source"])
            self.assertEqual(q["verdict"], "unstamped")
            self.assertIsNone(q["stamp_source"])
            self.assertTrue(any("sibling doc" in w for w in r["warnings"]),
                            r["warnings"])

        # --- bare filename citations, matched by basename -------------------
        def test_unique_basename_counts_toward_stale(self):
            (self.app / "Features/Alerts").mkdir(parents=True)
            (self.app / "Features/Alerts/AlertHelper.cs").write_text(
                "x", encoding="utf-8")
            self.run_git(self.app, "add", "-A")
            self.run_git(self.app, "commit", "-qm", "add alert helper")
            self.write("context.md",
                       f"# Context\n\n{self.stamp()}\n## Stacks\n\nnone\n")
            self.write("f1/overview.md",
                       f"# Overview\n\n{self.stamp()}\n## Notes\n")
            self.write("f1/api-a.md",
                       f"# API A\n\n{self.stamp()}\n## Notes\n\n"
                       f"See `AlertHelper.cs`.\n")
            a = self.doc(self.report(), "api-a.md")
            self.assertEqual(a["verdict"], "stale")
            self.assertIn("AlertHelper.cs", a["changed_by_basename"])
            self.assertEqual(a["ambiguous_basenames"], [])

        def test_ambiguous_basename_does_not_count_toward_stale(self):
            (self.app / "Features/Alerts").mkdir(parents=True)
            (self.app / "Features/Alerts/AlertHelper.cs").write_text(
                "x", encoding="utf-8")
            (self.app / "Features/Other").mkdir(parents=True)
            (self.app / "Features/Other/AlertHelper.cs").write_text(
                "y", encoding="utf-8")
            self.run_git(self.app, "add", "-A")
            self.run_git(self.app, "commit", "-qm", "two alert helpers")
            self.write("context.md",
                       f"# Context\n\n{self.stamp()}\n## Stacks\n\nnone\n")
            self.write("f1/overview.md",
                       f"# Overview\n\n{self.stamp()}\n## Notes\n")
            self.write("f1/api-a.md",
                       f"# API A\n\n{self.stamp()}\n## Notes\n\n"
                       f"See `AlertHelper.cs`.\n")
            a = self.doc(self.report(), "api-a.md")
            self.assertEqual(a["changed_by_basename"], [])
            self.assertEqual(a["ambiguous_basenames"],
                             [{"name": "AlertHelper.cs", "count": 2}])
            self.assertEqual(a["verdict"], "fresh")

        def test_bogus_sha_reports_unresolvable(self):
            self.write_all_docs()
            bogus = "f" * 40
            self.write("f1/api-a.md",
                       f"# API A\n\n{self.stamp(app_sha=bogus)}\n## Notes\n\n"
                       f"See `Features/Billing/Handler.cs`.\n")
            a = self.doc(self.report(), "api-a.md")
            self.assertEqual(a["verdict"], "unresolvable")
            self.assertTrue(any(f["code"] == "stamp_unresolvable"
                                for f in a["findings"]))

        def test_repo_not_provided_is_unresolvable(self):
            """A doc stamped for app+web, run with a --repo naming neither.

            Uses a real, valid repo (self.app) under an unmatched NAME --
            the path itself must be valid, since build_report now validates
            every --repo upfront; this test is about a name the stamp never
            references, not an unusable path (see the usage-error tests).
            """
            self.write_all_docs()
            r = self.report(repos=[("other", self.app)])
            b = self.doc(r, "api-b.md")
            self.assertEqual(b["verdict"], "unresolvable")
            self.assertTrue(any(f["code"] == "repo_not_provided"
                                for f in b["findings"]))

        # --- CLI: exit codes, --markdown, ledger ----------------------------
        def test_fail_on_stale_exit_codes(self):
            self.write_all_docs()
            self.advance_app()
            base = ["--summary-root", str(self.summary), "--feature", "f1",
                   "--repo", f"app={self.app}", "--repo", f"web={self.web}"]
            self.assertEqual(main(base), 0)
            self.assertEqual(main(base + ["--fail-on-stale"]), 1)

        def test_markdown_output_runs_and_exits_zero(self):
            self.write_all_docs()
            self.advance_app()
            self.assertEqual(main(["--summary-root", str(self.summary),
                                   "--feature", "f1",
                                   "--repo", f"app={self.app}",
                                   "--repo", f"web={self.web}",
                                   "--markdown"]), 0)

        def test_ledger_appended_and_chained(self):
            self.write_all_docs()
            self.advance_app()
            ledger = self.dir / "gates.jsonl"
            base = ["--summary-root", str(self.summary), "--feature", "f1",
                   "--repo", f"app={self.app}", "--repo", f"web={self.web}",
                   "--ledger", str(ledger)]
            self.assertEqual(main(base), 0)
            self.assertEqual(main(base + ["--fail-on-stale"]), 1)
            raw_lines = [l for l in
                        ledger.read_text(encoding="utf-8").splitlines()
                        if l.strip()]
            self.assertEqual(len(raw_lines), 2)
            records = [json.loads(l) for l in raw_lines]
            self.assertTrue(all(r["gate"] == "tier1_staleness.py"
                                for r in records))
            self.assertEqual(records[0]["prev"], "genesis")
            self.assertEqual(records[0]["self"], ledger_self_hash(records[0]))
            self.assertEqual(records[1]["prev"],
                             ledger_line_hash(raw_lines[0].encode("utf-8")))

        # --- usage errors ----------------------------------------------
        def test_missing_feature_or_repo_is_usage_error(self):
            self.write_all_docs()
            self.assertEqual(main(["--summary-root", str(self.summary),
                                   "--repo", f"app={self.app}"]), 2)
            self.assertEqual(main(["--summary-root", str(self.summary),
                                   "--feature", "f1"]), 2)

        def test_bad_summary_root_is_usage_error(self):
            self.assertEqual(main(["--summary-root", str(self.dir / "nope"),
                                   "--feature", "f1",
                                   "--repo", f"app={self.app}"]), 2)

        def test_missing_feature_directory_is_usage_error(self):
            """An unperformable check is never a PASS -- exit 2, not the
            0-doc PASS a silent warning would have produced."""
            self.write_all_docs()
            self.assertEqual(main(["--summary-root", str(self.summary),
                                   "--feature", "nosuchfeature",
                                   "--repo", f"app={self.app}",
                                   "--repo", f"web={self.web}"]), 2)

        def test_bad_repo_path_is_usage_error(self):
            """A --repo that cannot be checked is exit 2, not an exit-0
            report where every affected doc merely reads unresolvable."""
            self.write_all_docs()
            self.assertEqual(main(["--summary-root", str(self.summary),
                                   "--feature", "f1",
                                   "--repo", f"app={self.dir / 'nowhere'}",
                                   "--repo", f"web={self.web}"]), 2)
            not_a_repo = self.dir / "not_a_repo"
            not_a_repo.mkdir()
            self.assertEqual(main(["--summary-root", str(self.summary),
                                   "--feature", "f1",
                                   "--repo", f"app={not_a_repo}",
                                   "--repo", f"web={self.web}"]), 2)

        # --- citation extraction / matching, no git needed -----------------
        def test_citation_extractor_handles_backslash_and_prefix(self):
            text = ("See `gorelo_backend\\Features\\Billing\\Handler.cs` "
                   "and also `apis/Billing/Features/Billing/Handler.cs` "
                   "for details.")
            found = extract_cited_paths(text)
            self.assertIn("gorelo_backend/Features/Billing/Handler.cs", found)
            self.assertIn("apis/Billing/Features/Billing/Handler.cs", found)

        def test_path_suffix_match_is_bidirectional(self):
            self.assertTrue(path_suffix_match(
                "Features/Billing/Handler.cs",
                "apis/Billing/src/Features/Billing/Handler.cs"))
            self.assertTrue(path_suffix_match(
                "gorelo_backend/Features/Billing/Handler.cs",
                "Features/Billing/Handler.cs"))
            self.assertFalse(path_suffix_match(
                "Features/Other/Handler.cs",
                "Features/Billing/Handler.cs"))

    suite = unittest.defaultTestLoader.loadTestsFromTestCase(StalenessTests)
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
