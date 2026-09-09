#!/usr/bin/env python3
"""Mechanical gate for the Tier-1 provenance stamp `/bgpdd-discovery` promises.

`bgpdd-discovery/SKILL.md` § 1 makes every Tier-1 root artifact carry, in its
own header, the date and the HEAD commit sha it was derived from, and then says
in as many words: "No mechanical gate enforces this yet ... Do not treat the
absence of a gate as licence to skip the check." This is that gate (CLAUDE.md
convention #9 -- the phase that most wants to close is the one being asked to
re-read a header).

What it asserts by default, and nothing more: the stamp EXISTS, carries a date
that is not in the future, carries a 40-hex sha per in-scope repo, and each sha
RESOLVES in that repo. Drift against current HEAD is reported and never fails
-- the SKILL's contract says drift is a warning, because a hard failure would
only teach people to skip Tier 1.

A FUTURE DATE IS NOT A DATE (`stamp_date_future`)
-------------------------------------------------
The date was checked for SHAPE only, so `2031-01-01` passed. A stamp says
"this map was derived from the tree on this day"; a date that has not happened
records nothing that happened, and it defeats every downstream freshness
comparison in the direction that keeps a stale map looking new. Today (UTC) is
allowed -- a stamp written this morning is the normal case, and a machine one
timezone ahead must not be accused of forgery, so the bound is the LATEST date
in the header against today plus one day.

`--verify-current`: DRIFT AS A GATE, ON DEMAND (`tier1_drift`)
--------------------------------------------------------------
Drift stays a warning in the default run, exactly as `bgpdd-discovery` § 1
says. `--verify-current` is the opt-in inversion for the CONSUMER end -- the
plan/build/lite/verify/shipping Pre-Flight that is about to brief agents from
this map: with it, a stamped sha that is not the repo's current HEAD is
`tier1_drift`, exit 1, naming the repo, the stamped sha and HEAD. The producer
(discovery) writes the stamp and never passes it; the consumer decides whether
a map derived from a different tree is good enough, and `--allow-drift
"<reason>"` (exit 2 on an empty or whitespace-only reason, matching
`--allow-breaking` and `--allow-tier-inversion` elsewhere in this family)
records that decision in the ledger rather than leaving it to a flag nobody
passed. `--allow-drift` without `--verify-current` is exit 2: it would
otherwise read as a waiver of something that was never checked.

`--previous`: A CUMULATIVE FILE IS NOT A REWRITE (`tier1_repo_dropped`)
-----------------------------------------------------------------------
`bgpdd-discovery/SKILL.md` § 1: "Tier-1 `context.md` is cumulative and
project-wide; a run's Target Scope is a subset view recorded inside it, never
the file's whole content." Sessions in one workspace are each scoped to their
own repos, so a whole-file rewrite silently deletes every repo the previous
run recorded -- last write wins, no diff, no conflict marker, and `.docs/`
carries no version history to recover from. The SKILL therefore tells the
Orchestrator to back the file up before re-running Phase 1 and to confirm
afterwards that every previously recorded repo still appears.

That confirmation is asked for at the moment the phase most wants to close --
this run's own repos all check out -- so convention #9 makes it a command.
`--previous <path>` is that backup, and every repo stamped in it must still be
stamped in the current artifact: a repo that vanished is `tier1_repo_dropped`,
exit 1, naming the repo and BOTH files. Restore from the backup, merge the two
scopes, re-delegate.

What it does NOT fail: a repo present in both with a DIFFERENT sha (that is
this run's refresh, which is the whole point of re-running Phase 1), or a repo
the current artifact adds (that is this run's scope). Only removal fails, and
it fails whether or not the current run was ever scoped to the vanished repo
-- a user's "yes, update it" authorizes adding this run's scope, never
removing another's.

A repo counts as "still stamped" when its key OR its sha reappears, so a
single-repo header that grew a repo name, and a repo whose line was reworded,
are refreshes rather than drops. `--previous` may be a FILE (compared against
`context.md`, the one cumulative artifact) or a DIRECTORY mirroring
`--summary-root` (each checked artifact compared against its counterpart
there; a counterpart that does not exist is a warning, since there is nothing
to compare). A `--previous` path that does not exist at all is exit 2 -- an
unperformable check is never a PASS.

Stamp grammar (the gate's half of the contract; the writing agent's half is the
SKILL step). In the artifact's header -- everything above its first `## `
heading -- there must be an ISO date (YYYY-MM-DD) and, per in-scope repo, a
line carrying a 40-hex sha. On a multi-repo Target Scope that line must also
carry the repo's name, since "keyed by repo name" is the only thing that makes
several shas readable. With a single repo in scope, a bare sha line suffices.

Usage:
    python check_tier1_provenance.py --summary-root .docs/summary \
        [--feature <id>] --repo [<name>=]<path> [--repo ...] \
        [--warn-on-drift] [--verify-current [--allow-drift "<reason>"]] \
        [--previous <path>] \
        [--milestone "<title>"] [--ledger <path>]
    python check_tier1_provenance.py --self-test

Exit 0 PASS (drift included, unless `--verify-current`), 1 FAIL (findings),
2 ERROR (usage, unusable summary root, git unavailable -- an unperformable
check is never a PASS).
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
from datetime import datetime, timedelta, timezone
from pathlib import Path

SHA_RE = re.compile(r"(?<![0-9a-fA-F])([0-9a-fA-F]{40})(?![0-9a-fA-F])")
DATE_RE = re.compile(r"(?<!\d)(20\d{2})-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])(?!\d)")
HEADING_RE = re.compile(r"^##\s", re.M)
CONTEXT_ARTIFACT = "context.md"
FEATURE_ARTIFACT = "overview.md"


class GateError(Exception):
    """Structural/usage failure -- maps to exit 2."""


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
    """Append ONE JSON line recording this run. Best-effort by design.

    `extra` merges in BEFORE `prev`/`self` are computed, so the chain covers
    it: `--allow-drift` records the reason, which is what makes accepting a
    stale map a written act rather than a flag nobody noticed.
    """
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


def parse_repo_arg(raw):
    """`name=path` or `path` -> (name, Path). Bare paths key on the basename."""
    if "=" in raw:
        name, _, path = raw.partition("=")
        name, path = name.strip(), path.strip()
        if not name or not path:
            raise GateError(f"--repo needs both sides of '=': {raw!r}")
        return name, Path(path)
    path = Path(raw.strip())
    name = path.resolve().name or str(path)
    return name, path


def git(repo, *args):
    """Run git in `repo`; raise GateError when git itself is unusable."""
    try:
        return subprocess.run(["git", "-C", str(repo)] + list(args),
                              capture_output=True, text=True, timeout=120)
    except FileNotFoundError:
        raise GateError("git executable not found; provenance cannot be checked")
    except subprocess.TimeoutExpired:
        raise GateError(f"git {args[0] if args else ''} timed out after 120s")


def head_sha(repo):
    proc = git(repo, "rev-parse", "HEAD")
    return proc.stdout.strip() if proc.returncode == 0 else None


def sha_resolves(repo, sha):
    """True when `sha` names a commit object that exists in `repo`."""
    return git(repo, "cat-file", "-e", f"{sha}^{{commit}}").returncode == 0


def header_of(text):
    """The artifact's header: everything above its first `## ` heading."""
    match = HEADING_RE.search(text)
    return text[:match.start()] if match else text


def stamp_lines(header):
    """Header lines that carry at least one 40-hex token."""
    return [line for line in header.splitlines() if SHA_RE.search(line)]


# Words that decorate a stamp line without naming a repo. Stripped so
# `> commit: <sha>` and `> <sha>` key alike -- the key only has to be
# DETERMINISTIC and applied identically to both copies for the comparison to
# be sound; a wording change between the copies falls back to the sha match.
STAMP_NOISE_RE = re.compile(
    r"(?i)\b(provenance|derived|from|commit|sha|head|stamp(?:ed)?|as of|at|on|"
    r"repo(?:sitory)?)\b")
STAMP_SPLIT_SEPARATORS = ("—", "–", "|", "--")


def stamp_key(prefix):
    """The repo name a stamp line keys its sha to, normalized, or "".

    `prefix` is the part of the line BEFORE the sha. `> app: ` -> "app";
    `> ` -> "" (the bare single-repo form). Markdown decoration, blockquote
    markers, dates and the noise words above are removed.
    """
    text = prefix
    for sep in STAMP_SPLIT_SEPARATORS:
        if sep in text:
            text = text.rsplit(sep, 1)[-1]
    text = re.sub(r"^[\s>*+\-#]+", "", text)
    text = DATE_RE.sub(" ", text)
    text = STAMP_NOISE_RE.sub(" ", text)
    text = re.sub(r"[`*_]", "", text)
    text = re.sub(r"[\s:=,\-]+$", "", text)
    return re.sub(r"\s+", " ", text).strip().casefold()


def stamped_repos(header):
    """{key: {"name": <as written>, "sha": <sha>}} for a header's stamps.

    Keyed on `stamp_key` of everything left of each sha, so the SAME parse is
    applied to the previous copy and the current one. The first line to claim
    a key wins; the display name is the key or "(unnamed)" for the bare form.
    """
    found = {}
    for line in header.splitlines():
        match = SHA_RE.search(line)
        if not match:
            continue
        key = stamp_key(line[:match.start()])
        found.setdefault(key, {"name": key or "(unnamed)",
                               "sha": match.group(1)})
    return found


def check_previous_scope(path, previous_path, findings, warnings):
    """Assert every repo stamped in `previous_path` is still stamped in `path`.

    A repo survives when its KEY or its SHA reappears -- a reworded or newly
    named line is a refresh, not a drop. Appends `tier1_repo_dropped` findings.
    """
    try:
        previous_text = previous_path.read_text(encoding="utf-8-sig",
                                                errors="replace")
    except OSError as exc:
        warnings.append(f"could not read --previous {previous_path}: {exc}")
        return
    previous = stamped_repos(header_of(previous_text))
    if not previous:
        warnings.append(
            f"--previous {previous_path} carries no stamped repo in its "
            "header; there is nothing to compare against")
        return
    try:
        current_text = path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError as exc:
        warnings.append(f"could not re-read {path}: {exc}")
        return
    current = stamped_repos(header_of(current_text))
    current_shas = {entry["sha"].lower() for entry in current.values()}
    for key, entry in previous.items():
        if key in current or entry["sha"].lower() in current_shas:
            continue
        findings.append({
            "code": "tier1_repo_dropped", "artifact": str(path),
            "previous": str(previous_path), "repo": entry["name"],
            "stamped": entry["sha"],
            "detail": f"repo '{entry['name']}' is stamped in the previous "
                      f"copy {previous_path} (as {entry['sha'][:12]}) but "
                      f"appears in neither the repo keys nor the shas of "
                      f"{path}. Tier-1 context.md is CUMULATIVE and "
                      "project-wide: a whole-file rewrite deletes another "
                      "session's scope with no diff and no version history "
                      "to recover from (bgpdd-discovery section 1). Restore "
                      "from the backup, merge the two scopes, and "
                      "re-delegate — never accept the shrunk file because "
                      "this run's own repos all check out"})


def latest_header_date(header):
    """The newest YYYY-MM-DD in the header as a date, or None if there is none.

    The LATEST, not the first: a header may legitimately mention an earlier
    date in prose ("supersedes the 2026-01-04 map"), and the stamp's claim is
    the most recent one it makes.
    """
    found = []
    for match in DATE_RE.finditer(header):
        try:
            found.append(datetime(int(match.group(1)), int(match.group(2)),
                                  int(match.group(3)), tzinfo=timezone.utc)
                         .date())
        except ValueError:      # 2026-02-31 and friends
            continue
    return max(found) if found else None


def check_artifact(path, repos, findings, warnings, drift, tier,
                   today=None, verify_current=False, previous=None):
    """Assert one Tier-1 root artifact's stamp. Appends to the given lists."""
    rel = str(path)
    if not path.is_file():
        findings.append({"code": "artifact_missing", "artifact": rel,
                         "detail": f"{tier} artifact does not exist: {rel}"})
        return
    if previous is not None:
        check_previous_scope(path, previous, findings, warnings)
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    header = header_of(text)
    lines = stamp_lines(header)
    if not lines:
        findings.append({"code": "stamp_missing", "artifact": rel,
                         "detail": f"{rel}: no 40-hex commit sha in the header "
                                   "(everything above the first '## ' heading)"})
    stamped_date = latest_header_date(header)
    if stamped_date is None:
        findings.append({"code": "date_missing", "artifact": rel,
                         "detail": f"{rel}: header carries no YYYY-MM-DD date"})
    else:
        # One day of slack for a machine running ahead of UTC; see the
        # docstring. Anything beyond that records a day that has not happened.
        limit = (today or datetime.now(timezone.utc).date()) + timedelta(days=1)
        if stamped_date > limit:
            findings.append({
                "code": "stamp_date_future", "artifact": rel,
                "date": stamped_date.isoformat(),
                "detail": f"{rel}: the stamp is dated {stamped_date}, which "
                          f"is after today ({limit - timedelta(days=1)}). A "
                          "stamp records the day the map was derived from the "
                          "tree; a future date records nothing that happened "
                          "and makes a stale map read as fresh to every "
                          "downstream freshness check"})

    single = len(repos) == 1
    for name, repo_path in repos:
        matched = None
        for line in lines:
            if single or name.casefold() in line.casefold():
                matched = SHA_RE.search(line).group(1)
                break
        if matched is None:
            if lines:
                findings.append({
                    "code": "sha_missing", "artifact": rel, "repo": name,
                    "detail": f"{rel}: no header line keys a sha to repo "
                              f"'{name}' (multi-repo scope requires the repo "
                              "name beside its sha)"})
            continue
        if not repo_path.is_dir():
            findings.append({
                "code": "sha_unknown", "artifact": rel, "repo": name,
                "sha": matched,
                "detail": f"--repo {name} path does not exist: {repo_path}"})
            continue
        if not sha_resolves(repo_path, matched):
            findings.append({
                "code": "sha_unknown", "artifact": rel, "repo": name,
                "sha": matched,
                "detail": f"{rel}: stamped sha {matched[:12]} does not resolve "
                          f"to a commit in repo '{name}'"})
            continue
        current = head_sha(repo_path)
        if current and current != matched:
            entry = {"artifact": rel, "repo": name, "stamped": matched,
                     "head": current}
            drift.append(entry)
            # ASCII only: this line is printed to stderr under --warn-on-drift,
            # and a Windows console on a legacy codepage mangles non-ASCII.
            warnings.append(
                f"{rel}: repo '{name}' stamped {matched[:12]} but HEAD is now "
                f"{current[:12]} - the map may be stale (warning, never a "
                "failure: bgpdd-discovery section 1)")
            if verify_current:
                findings.append({
                    "code": "tier1_drift", "artifact": rel, "repo": name,
                    "stamped": matched, "head": current,
                    "detail": f"{rel}: repo '{name}' is stamped {matched} but "
                              f"HEAD is now {current} - --verify-current was "
                              "asked for, so this map was derived from a "
                              "different tree than the one about to be worked "
                              "in. Re-run /bgpdd-discovery for this feature, "
                              "or accept the staleness in writing with "
                              "--allow-drift \"<reason>\""})


def previous_for(previous, root, artifact, warnings):
    """The prior copy of `artifact`, or None when there is nothing to compare.

    A FILE `--previous` is the backup of `context.md` -- the one cumulative,
    project-wide artifact the lesson is about -- and applies to nothing else.
    A DIRECTORY is a mirror of `--summary-root`, applied per artifact.
    """
    if previous is None:
        return None
    if previous.is_dir():
        try:
            counterpart = previous / artifact.relative_to(root)
        except ValueError:              # not under the root; nothing to map
            return None
        if counterpart.is_file():
            return counterpart
        warnings.append(
            f"--previous {previous} holds no counterpart for {artifact}; "
            "nothing to compare for this artifact")
        return None
    return previous if artifact.name == CONTEXT_ARTIFACT else None


def build_report(summary_root, repos, feature=None, today=None,
                 verify_current=False, allow_drift=None, previous=None):
    root = Path(summary_root)
    if not root.is_dir():
        raise GateError(f"--summary-root is not a directory: {summary_root}")
    if not repos:
        raise GateError("at least one --repo is required")
    previous_path = Path(previous) if previous else None
    if previous_path is not None and not previous_path.exists():
        raise GateError(f"--previous does not exist: {previous}")

    findings, warnings, drift = [], [], []
    checked = []

    context = root / CONTEXT_ARTIFACT
    checked.append(str(context))
    check_artifact(context, repos, findings, warnings, drift, "Tier-1 root",
                   today, verify_current,
                   previous_for(previous_path, root, context, warnings))

    if feature:
        features = [feature]
    else:
        features = sorted(p.name for p in root.iterdir()
                          if p.is_dir() and not p.name.startswith("."))
    for name in features:
        overview = root / name / FEATURE_ARTIFACT
        checked.append(str(overview))
        check_artifact(overview, repos, findings, warnings, drift,
                       f"Tier-1 feature '{name}'", today, verify_current,
                       previous_for(previous_path, root, overview, warnings))

    waived = []
    if verify_current and allow_drift:
        waived = [f for f in findings if f["code"] == "tier1_drift"]
        findings = [f for f in findings if f["code"] != "tier1_drift"]
        if waived:
            warnings.append(
                "DRIFT WAIVED by --allow-drift for {0}: {1}".format(
                    ", ".join(sorted({f["repo"] for f in waived})),
                    allow_drift.strip()))

    return {
        "result": "FAIL" if findings else "PASS",
        "summary_root": str(summary_root),
        "feature": feature,
        "features_checked": features,
        "artifacts_checked": checked,
        "previous": str(previous_path) if previous_path else None,
        "repos": [{"name": n, "path": str(p)} for n, p in repos],
        "verify_current": bool(verify_current),
        "allow_drift": allow_drift.strip() if (verify_current and allow_drift
                                               and waived) else None,
        "drift_waived": waived,
        "findings": findings,
        "drift": drift,
        "warnings": warnings,
        "error": None,
    }


def main(argv):
    parser = argparse.ArgumentParser(prog="check_tier1_provenance.py")
    parser.add_argument("--summary-root", default=".docs/summary",
                        help="Tier-1 knowledge base root (default .docs/summary)")
    parser.add_argument("--feature", help="check only this feature's overview.md")
    parser.add_argument("--repo", action="append", default=[],
                        help="in-scope repository as [<name>=]<path>; repeat "
                             "once per repo on a multi-repo Target Scope")
    parser.add_argument("--warn-on-drift", action="store_true",
                        help="also print drift warnings to stderr; drift NEVER "
                             "changes the exit code (bgpdd-discovery §1)")
    parser.add_argument("--verify-current", action="store_true",
                        help="CONSUMER mode: a stamped sha that is not the "
                             "repo's current HEAD is tier1_drift, exit 1. "
                             "Opt-in — the default run keeps drift a warning.")
    parser.add_argument("--allow-drift", dest="allow_drift",
                        help="--verify-current only: accept the drift with a "
                             "written reason, recorded in the ledger. An "
                             "empty reason is exit 2.")
    parser.add_argument("--previous",
                        help="the prior copy of this Tier-1 artifact (the "
                             "backup discovery takes before re-running Phase "
                             "1): a FILE compares against context.md, a "
                             "DIRECTORY mirrors --summary-root. Every repo "
                             "stamped there must still be stamped here "
                             "(tier1_repo_dropped). A path that does not "
                             "exist is exit 2.")
    parser.add_argument("--milestone", help="recorded in the ledger line")
    parser.add_argument("--ledger", help="append one JSON record per run to this path")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)

    if args.self_test:
        return run_self_test()

    def finish(code, verdict, inputs=(), extra=None):
        """One exit point: EVERY return path records a ledger line."""
        append_ledger(args.ledger, argv, args.milestone, list(inputs), verdict,
                      code, extra)
        return code

    if args.allow_drift is not None:
        if not args.verify_current:
            print(json.dumps({
                "result": "ERROR",
                "error": "--allow-drift requires --verify-current: waiving a "
                         "check that never ran records a decision nobody had "
                         "to make"}))
            return finish(2, "ERROR")
        if not args.allow_drift.strip():
            print(json.dumps({
                "result": "ERROR",
                "error": "--allow-drift requires a non-empty reason: an "
                         "unreasoned waiver is indistinguishable from an "
                         "omission"}))
            return finish(2, "ERROR")

    try:
        repos = [parse_repo_arg(raw) for raw in (args.repo or ["."])]
        report = build_report(args.summary_root, repos, args.feature,
                              verify_current=args.verify_current,
                              allow_drift=args.allow_drift,
                              previous=args.previous)
    except GateError as exc:
        print(json.dumps({"result": "ERROR", "error": str(exc)}))
        return finish(2, "ERROR")

    if args.warn_on_drift:
        for line in report["warnings"]:
            print(f"Warning: {line}", file=sys.stderr)

    print(json.dumps(report, indent=2))
    inputs = report["artifacts_checked"]
    extra = ({"allow_drift_reason": report["allow_drift"],
              "drift_waived": [{"repo": f["repo"], "stamped": f["stamped"],
                                "head": f["head"]}
                               for f in report["drift_waived"]]}
             if report.get("allow_drift") else None)
    return (finish(0, "PASS", inputs, extra) if report["result"] == "PASS"
            else finish(1, "FAIL", inputs, extra))


def run_self_test():
    import shutil

    class ProvenanceTests(unittest.TestCase):
        def setUp(self):
            self.dir = Path(tempfile.mkdtemp())
            self.repo = self.dir / "app"
            self.repo.mkdir()
            self.summary = self.dir / ".docs" / "summary"
            (self.summary / "slide" / "QA").mkdir(parents=True)
            self.sha = self.init_repo(self.repo)

        def tearDown(self):
            shutil.rmtree(self.dir, ignore_errors=True)

        def init_repo(self, path):
            try:
                proc = subprocess.run(["git", "-C", str(path), "init", "-q"],
                                      capture_output=True, text=True, timeout=120)
            except FileNotFoundError:
                self.skipTest("git not available")
            if proc.returncode != 0:
                self.skipTest("git init failed")
            for args in (["config", "user.email", "t@t.t"],
                         ["config", "user.name", "t"]):
                subprocess.run(["git", "-C", str(path)] + args,
                               capture_output=True, timeout=120)
            # Content keyed on the repo name so two repos created in the same
            # second by the same author do not produce the SAME commit sha --
            # which would make the mis-keyed-sha case below undetectable.
            (path / "f.txt").write_text(f"one {path.name}", encoding="utf-8")
            subprocess.run(["git", "-C", str(path), "add", "-A"],
                           capture_output=True, timeout=120)
            subprocess.run(["git", "-C", str(path), "commit", "-qm",
                            f"one {path.name}"], capture_output=True, timeout=120)
            return subprocess.run(["git", "-C", str(path), "rev-parse", "HEAD"],
                                  capture_output=True, text=True,
                                  timeout=120).stdout.strip()

        def advance(self, path):
            (path / "f.txt").write_text("two", encoding="utf-8")
            subprocess.run(["git", "-C", str(path), "add", "-A"],
                           capture_output=True, timeout=120)
            subprocess.run(["git", "-C", str(path), "commit", "-qm", "two"],
                           capture_output=True, timeout=120)

        def stamp(self, sha=None, date="2026-09-07", name=None):
            sha = sha or self.sha
            key = f"{name}: " if name else ""
            return (f"# Context\n\n> Provenance — {date}\n"
                    f"> {key}`{sha}`\n\n## Stacks (detected)\n\nnone\n")

        def write_context(self, body=None):
            (self.summary / "context.md").write_text(
                body if body is not None else self.stamp(), encoding="utf-8")

        def write_overview(self, body=None):
            (self.summary / "slide" / "overview.md").write_text(
                body if body is not None else self.stamp(), encoding="utf-8")

        def report(self, repos=None, feature=None, **kw):
            return build_report(self.summary, repos or [("app", self.repo)],
                                feature, **kw)

        def codes(self, report):
            return sorted({f["code"] for f in report["findings"]})

        # --- happy paths -------------------------------------------------
        def test_stamped_context_and_overview_pass(self):
            self.write_context()
            self.write_overview()
            r = self.report()
            self.assertEqual(r["result"], "PASS", r["findings"])
            self.assertEqual(r["drift"], [])

        def test_feature_scoped_run_checks_only_that_overview(self):
            self.write_context()
            self.write_overview()
            (self.summary / "other").mkdir()
            r = self.report(feature="slide")
            self.assertEqual(r["result"], "PASS", r["findings"])
            self.assertEqual(r["features_checked"], ["slide"])

        # --- the stamp itself ---------------------------------------------
        def test_missing_sha_fails(self):
            """No sha anywhere in the header reports stamp_missing once, not
            stamp_missing plus one sha_missing per in-scope repo."""
            self.write_context("# Context\n\n> Discovered 2026-09-07\n\n## Stacks\n")
            self.write_overview()
            self.assertEqual(self.codes(self.report()), ["stamp_missing"])

        def test_missing_date_fails(self):
            self.write_context(f"# Context\n\n> `{self.sha}`\n\n## Stacks\n")
            self.write_overview()
            self.assertEqual(self.codes(self.report()), ["date_missing"])

        def test_sha_below_the_first_heading_is_not_a_header_stamp(self):
            """The contract says 'in its own header' -- a sha buried in the
            body is not a stamp a reader finds before trusting the map."""
            self.write_context(f"# Context\n\n## Stacks\n\nDerived from "
                               f"`{self.sha}` on 2026-09-07.\n")
            self.write_overview()
            self.assertIn("stamp_missing", self.codes(self.report()))

        def test_unresolvable_sha_fails(self):
            self.write_context(self.stamp(sha="0" * 40))
            self.write_overview()
            r = self.report()
            self.assertEqual(self.codes(r), ["sha_unknown"])
            self.assertEqual(r["findings"][0]["repo"], "app")

        def test_missing_artifact_fails(self):
            self.write_overview()
            self.assertEqual(self.codes(self.report()), ["artifact_missing"])

        def test_feature_dir_without_overview_fails(self):
            self.write_context()
            self.assertEqual(self.codes(self.report()), ["artifact_missing"])

        # --- drift is a warning, never a failure ---------------------------
        def test_drift_warns_and_still_passes(self):
            self.write_context()
            self.write_overview()
            self.advance(self.repo)
            r = self.report()
            self.assertEqual(r["result"], "PASS", r["findings"])
            self.assertEqual(len(r["drift"]), 2)
            self.assertEqual(r["drift"][0]["stamped"], self.sha)
            self.assertNotEqual(r["drift"][0]["head"], self.sha)
            self.assertTrue(r["warnings"])

        def test_drift_exit_code_is_zero_through_main(self):
            self.write_context()
            self.write_overview()
            self.advance(self.repo)
            self.assertEqual(main(["--summary-root", str(self.summary),
                                   "--repo", f"app={self.repo}",
                                   "--warn-on-drift"]), 0)

        # --- stamp_date_future (audit3 F: the date gap) --------------------
        def test_a_future_dated_stamp_fails(self):
            future = (datetime.now(timezone.utc).date()
                      + timedelta(days=30)).isoformat()
            self.write_context(self.stamp(date=future))
            self.write_overview()
            r = self.report()
            self.assertEqual(r["result"], "FAIL")
            self.assertEqual(self.codes(r), ["stamp_date_future"])
            self.assertEqual(r["findings"][0]["date"], future)

        def test_todays_date_and_one_day_of_slack_pass(self):
            today = datetime.now(timezone.utc).date()
            for offset in (0, 1, -1, -400):
                stamp_date = (today + timedelta(days=offset)).isoformat()
                self.write_context(self.stamp(date=stamp_date))
                self.write_overview(self.stamp(date=stamp_date))
                r = self.report()
                self.assertEqual(r["result"], "PASS", (offset, r["findings"]))

        def test_the_latest_header_date_is_the_one_judged(self):
            future = (datetime.now(timezone.utc).date()
                      + timedelta(days=30)).isoformat()
            body = (f"# Context\n\n> Provenance — 2026-01-04\n"
                    f"> supersedes the {future} draft\n"
                    f"> `{self.sha}`\n\n## Stacks\n")
            self.write_context(body)
            self.write_overview()
            self.assertEqual(self.codes(self.report()), ["stamp_date_future"])

        def test_an_impossible_date_is_date_missing_not_a_crash(self):
            body = (f"# Context\n\n> Provenance — 2026-02-31\n"
                    f"> `{self.sha}`\n\n## Stacks\n")
            self.write_context(body)
            self.write_overview()
            # 2026-02-31 never matches DATE_RE's day alternation as a real
            # date; the point is that nothing raises.
            self.assertNotIn("stamp_date_future", self.codes(self.report()))

        def test_the_future_date_exit_code_is_one_through_main(self):
            future = (datetime.now(timezone.utc).date()
                      + timedelta(days=30)).isoformat()
            self.write_context(self.stamp(date=future))
            self.write_overview()
            self.assertEqual(main(["--summary-root", str(self.summary),
                                   "--repo", f"app={self.repo}"]), 1)

        # --- --verify-current / --allow-drift ------------------------------
        def test_verify_current_turns_drift_into_a_finding(self):
            self.write_context()
            self.write_overview()
            self.advance(self.repo)
            r = self.report(verify_current=True)
            self.assertEqual(r["result"], "FAIL")
            self.assertEqual(self.codes(r), ["tier1_drift"])
            finding = r["findings"][0]
            self.assertEqual(finding["repo"], "app")
            self.assertEqual(finding["stamped"], self.sha)
            self.assertNotEqual(finding["head"], self.sha)
            self.assertIn(self.sha, finding["detail"])
            self.assertIn(finding["head"], finding["detail"])

        def test_verify_current_passes_when_head_still_matches(self):
            self.write_context()
            self.write_overview()
            r = self.report(verify_current=True)
            self.assertEqual(r["result"], "PASS", r["findings"])
            self.assertEqual(r["drift"], [])

        def test_allow_drift_waives_the_finding_and_records_the_reason(self):
            self.write_context()
            self.write_overview()
            self.advance(self.repo)
            r = self.report(verify_current=True,
                            allow_drift="canary only touches the CDN config")
            self.assertEqual(r["result"], "PASS", r["findings"])
            self.assertEqual(r["allow_drift"],
                             "canary only touches the CDN config")
            self.assertEqual(len(r["drift_waived"]), 2)
            self.assertTrue(any("DRIFT WAIVED" in w for w in r["warnings"]))

        def test_allow_drift_does_not_waive_a_real_finding(self):
            self.write_context("# Context\n\n> Provenance — 2026-09-07\n\n## S\n")
            self.write_overview()
            self.advance(self.repo)
            r = self.report(verify_current=True, allow_drift="known stale")
            self.assertEqual(r["result"], "FAIL")
            self.assertIn("stamp_missing", self.codes(r))

        def test_verify_current_exit_codes_and_ledger_through_main(self):
            self.write_context()
            self.write_overview()
            self.advance(self.repo)
            ledger = self.dir / "gates.jsonl"
            base = ["--summary-root", str(self.summary),
                    "--repo", f"app={self.repo}", "--ledger", str(ledger)]
            self.assertEqual(main(base), 0)                      # warning only
            self.assertEqual(main(base + ["--verify-current"]), 1)
            self.assertEqual(main(base + ["--verify-current",
                                          "--allow-drift", "accepted"]), 0)
            record = json.loads(
                ledger.read_text(encoding="utf-8").splitlines()[-1])
            self.assertEqual(record["allow_drift_reason"], "accepted")
            self.assertEqual(record["self"], ledger_self_hash(record))

        def test_allow_drift_needs_verify_current_and_a_reason(self):
            self.write_context()
            self.write_overview()
            base = ["--summary-root", str(self.summary),
                    "--repo", f"app={self.repo}"]
            self.assertEqual(main(base + ["--allow-drift", "x"]), 2)
            self.assertEqual(main(base + ["--verify-current",
                                          "--allow-drift", ""]), 2)
            self.assertEqual(main(base + ["--verify-current",
                                          "--allow-drift", "   "]), 2)

        # --- multi-repo ----------------------------------------------------
        def test_multi_repo_requires_a_sha_keyed_per_repo(self):
            second = self.dir / "web"
            second.mkdir()
            sha2 = self.init_repo(second)
            self.write_context(self.stamp(name="app"))
            self.write_overview(self.stamp(name="app"))
            repos = [("app", self.repo), ("web", second)]
            self.assertEqual(self.codes(self.report(repos)), ["sha_missing"])

            both = (f"# Context\n\n> Provenance — 2026-09-07\n"
                    f"> app: `{self.sha}`\n> web: `{sha2}`\n\n## Stacks\n")
            self.write_context(both)
            self.write_overview(both)
            r = self.report(repos)
            self.assertEqual(r["result"], "PASS", r["findings"])

        def test_multi_repo_keys_the_right_sha_to_the_right_repo(self):
            second = self.dir / "web"
            second.mkdir()
            sha2 = self.init_repo(second)
            swapped = (f"# Context\n\n> Provenance — 2026-09-07\n"
                       f"> app: `{sha2}`\n> web: `{self.sha}`\n\n## Stacks\n")
            self.write_context(swapped)
            self.write_overview(swapped)
            r = self.report([("app", self.repo), ("web", second)])
            self.assertEqual(self.codes(r), ["sha_unknown"])

        def test_repo_path_that_does_not_exist_fails(self):
            self.write_context()
            self.write_overview()
            r = self.report([("app", self.dir / "gone")])
            self.assertEqual(self.codes(r), ["sha_unknown"])

        # --- --previous: a cumulative file is not a rewrite -----------------

        def two_repo_stamp(self, first, second, date="2026-09-07"):
            return (f"# Context\n\n> Provenance — {date}\n"
                    f"> app: `{first}`\n> web: `{second}`\n\n## Stacks\n")

        def backup(self, body):
            path = self.dir / "context.2026-09-07T0900.md"
            path.write_text(body, encoding="utf-8")
            return path

        def test_previous_with_the_same_repos_passes(self):
            body = self.two_repo_stamp(self.sha, self.sha)
            prior = self.backup(body)
            self.write_context(body)
            self.write_overview()
            r = self.report(previous=str(prior))
            self.assertEqual(r["result"], "PASS", r["findings"])
            self.assertEqual(r["previous"], str(prior))

        def test_a_dropped_repo_fails_and_names_both_files(self):
            """The lesson's exact shape: this run is scoped to `app` only, so
            every check passes -- and `web` is silently gone."""
            prior = self.backup(self.two_repo_stamp(self.sha, "b" * 40))
            self.write_context(self.stamp(name="app"))
            self.write_overview()
            r = self.report(previous=str(prior))
            self.assertEqual(r["result"], "FAIL")
            self.assertEqual(self.codes(r), ["tier1_repo_dropped"])
            finding = r["findings"][0]
            self.assertEqual(finding["repo"], "web")
            self.assertEqual(finding["previous"], str(prior))
            self.assertIn("context.md", finding["artifact"])
            self.assertIn("cumulative", finding["detail"].lower())

        def test_a_refreshed_sha_for_the_same_repo_is_not_a_drop(self):
            prior = self.backup(self.two_repo_stamp("a" * 40, "b" * 40))
            self.write_context(self.two_repo_stamp(self.sha, self.sha))
            self.write_overview()
            r = self.report(previous=str(prior))
            self.assertEqual(self.codes(r), [])

        def test_a_newly_added_repo_is_not_a_drop(self):
            prior = self.backup(self.stamp(name="app"))
            self.write_context(self.two_repo_stamp(self.sha, self.sha))
            self.write_overview()
            r = self.report(previous=str(prior))
            self.assertEqual(self.codes(r), [])

        def test_a_bare_previous_stamp_that_gained_a_name_is_not_a_drop(self):
            """Key OR sha: an unnamed single-repo stamp survives being keyed."""
            prior = self.backup(self.stamp())
            self.write_context(self.stamp(name="app"))
            self.write_overview()
            self.assertEqual(self.codes(self.report(previous=str(prior))), [])

        def test_previous_applies_to_context_not_to_a_feature_overview(self):
            """A FILE --previous is context.md's backup and nothing else's."""
            prior = self.backup(self.two_repo_stamp(self.sha, "b" * 40))
            self.write_context(self.two_repo_stamp(self.sha, "b" * 40))
            self.write_overview(self.stamp(name="app"))
            r = self.report(previous=str(prior))
            self.assertEqual(self.codes(r), [])

        def test_a_previous_directory_is_compared_per_artifact(self):
            mirror = self.dir / "backup"
            (mirror / "slide").mkdir(parents=True)
            (mirror / "context.md").write_text(
                self.two_repo_stamp(self.sha, "b" * 40), encoding="utf-8")
            (mirror / "slide" / "overview.md").write_text(
                self.two_repo_stamp(self.sha, "b" * 40), encoding="utf-8")
            self.write_context(self.stamp(name="app"))
            self.write_overview(self.stamp(name="app"))
            r = self.report(previous=str(mirror))
            self.assertEqual(self.codes(r), ["tier1_repo_dropped"])
            self.assertEqual(len(r["findings"]), 2)   # both artifacts shrank

        def test_a_previous_directory_without_a_counterpart_only_warns(self):
            mirror = self.dir / "backup"
            mirror.mkdir()
            (mirror / "context.md").write_text(self.stamp(name="app"),
                                               encoding="utf-8")
            self.write_context(self.stamp(name="app"))
            self.write_overview()
            r = self.report(previous=str(mirror))
            self.assertEqual(r["result"], "PASS", r["findings"])
            self.assertTrue(any("no counterpart" in w for w in r["warnings"]))

        def test_a_previous_with_no_stamp_warns_rather_than_failing(self):
            prior = self.backup("# Context\n\nnothing stamped yet\n")
            self.write_context()
            self.write_overview()
            r = self.report(previous=str(prior))
            self.assertEqual(r["result"], "PASS", r["findings"])
            self.assertTrue(any("nothing to compare" in w
                                for w in r["warnings"]))

        def test_a_missing_previous_path_is_exit_2(self):
            self.write_context()
            self.write_overview()
            with self.assertRaises(GateError):
                self.report(previous=str(self.dir / "no-such-backup.md"))
            self.assertEqual(main(["--summary-root", str(self.summary),
                                   "--repo", f"app={self.repo}",
                                   "--previous",
                                   str(self.dir / "no-such-backup.md")]), 2)

        def test_the_dropped_repo_exit_code_is_one_through_main(self):
            prior = self.backup(self.two_repo_stamp(self.sha, "b" * 40))
            self.write_context(self.stamp(name="app"))
            self.write_overview()
            self.assertEqual(main(["--summary-root", str(self.summary),
                                   "--repo", f"app={self.repo}",
                                   "--previous", str(prior)]), 1)

        def test_stamp_key_parsing(self):
            self.assertEqual(stamp_key("> app: "), "app")
            self.assertEqual(stamp_key("> "), "")
            self.assertEqual(stamp_key("- web-frontend = "), "web-frontend")
            self.assertEqual(stamp_key("> Provenance — 2026-09-07 "), "")
            self.assertEqual(stamp_key("> commit: "), "")

        # --- plumbing -------------------------------------------------------
        def test_bad_summary_root_and_no_repo_are_errors(self):
            with self.assertRaises(GateError):
                build_report(self.dir / "nope", [("app", self.repo)])
            with self.assertRaises(GateError):
                build_report(self.summary, [])

        def test_repo_arg_parsing(self):
            self.assertEqual(parse_repo_arg("app=/x/y")[0], "app")
            self.assertEqual(parse_repo_arg("app=/x/y")[1], Path("/x/y"))
            with self.assertRaises(GateError):
                parse_repo_arg("=/x/y")

        def test_ledger_records_every_exit_path(self):
            ledger = self.dir / "logs" / "gates.jsonl"
            self.write_context()
            self.write_overview()
            self.assertEqual(main(["--summary-root", str(self.summary),
                                   "--repo", f"app={self.repo}",
                                   "--ledger", str(ledger)]), 0)
            self.write_context("# Context\n\nno stamp\n")
            self.assertEqual(main(["--summary-root", str(self.summary),
                                   "--repo", f"app={self.repo}",
                                   "--ledger", str(ledger)]), 1)
            self.assertEqual(main(["--summary-root", str(self.dir / "nope"),
                                   "--repo", f"app={self.repo}",
                                   "--ledger", str(ledger)]), 2)
            records = [json.loads(l) for l in
                       ledger.read_text(encoding="utf-8").splitlines() if l.strip()]
            self.assertEqual([r["verdict"] for r in records],
                             ["PASS", "FAIL", "ERROR"])
            self.assertTrue(all(r["gate"] == "check_tier1_provenance.py"
                                for r in records))

    suite = unittest.defaultTestLoader.loadTestsFromTestCase(ProvenanceTests)
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
