#!/usr/bin/env python3
"""Mechanical gate for the Tier-1 provenance stamp `/bgpdd-discovery` promises.

`bgpdd-discovery/SKILL.md` § 1 makes every Tier-1 root artifact carry, in its
own header, the date and the HEAD commit sha it was derived from, and then says
in as many words: "No mechanical gate enforces this yet ... Do not treat the
absence of a gate as licence to skip the check." This is that gate (CLAUDE.md
convention #9 -- the phase that most wants to close is the one being asked to
re-read a header).

What it asserts, and nothing more: the stamp EXISTS, carries a date, carries a
40-hex sha per in-scope repo, and each sha RESOLVES in that repo. Drift against
current HEAD is reported and never fails -- the SKILL's contract says drift is
a warning, because a hard failure would only teach people to skip Tier 1.

Stamp grammar (the gate's half of the contract; the writing agent's half is the
SKILL step). In the artifact's header -- everything above its first `## `
heading -- there must be an ISO date (YYYY-MM-DD) and, per in-scope repo, a
line carrying a 40-hex sha. On a multi-repo Target Scope that line must also
carry the repo's name, since "keyed by repo name" is the only thing that makes
several shas readable. With a single repo in scope, a bare sha line suffices.

Usage:
    python check_tier1_provenance.py --summary-root .docs/summary \
        [--feature <id>] --repo [<name>=]<path> [--repo ...] \
        [--warn-on-drift] [--milestone "<title>"] [--ledger <path>]
    python check_tier1_provenance.py --self-test

Exit 0 PASS (drift included), 1 FAIL (findings), 2 ERROR (usage, unusable
summary root, git unavailable -- an unperformable check is never a PASS).
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


def append_ledger(ledger_path, argv, milestone, inputs, verdict, exit_code):
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


def check_artifact(path, repos, findings, warnings, drift, tier):
    """Assert one Tier-1 root artifact's stamp. Appends to the given lists."""
    rel = str(path)
    if not path.is_file():
        findings.append({"code": "artifact_missing", "artifact": rel,
                         "detail": f"{tier} artifact does not exist: {rel}"})
        return
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    header = header_of(text)
    lines = stamp_lines(header)
    if not lines:
        findings.append({"code": "stamp_missing", "artifact": rel,
                         "detail": f"{rel}: no 40-hex commit sha in the header "
                                   "(everything above the first '## ' heading)"})
    if not DATE_RE.search(header):
        findings.append({"code": "date_missing", "artifact": rel,
                         "detail": f"{rel}: header carries no YYYY-MM-DD date"})

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


def build_report(summary_root, repos, feature=None):
    root = Path(summary_root)
    if not root.is_dir():
        raise GateError(f"--summary-root is not a directory: {summary_root}")
    if not repos:
        raise GateError("at least one --repo is required")

    findings, warnings, drift = [], [], []
    checked = []

    context = root / CONTEXT_ARTIFACT
    checked.append(str(context))
    check_artifact(context, repos, findings, warnings, drift, "Tier-1 root")

    if feature:
        features = [feature]
    else:
        features = sorted(p.name for p in root.iterdir()
                          if p.is_dir() and not p.name.startswith("."))
    for name in features:
        overview = root / name / FEATURE_ARTIFACT
        checked.append(str(overview))
        check_artifact(overview, repos, findings, warnings, drift,
                       f"Tier-1 feature '{name}'")

    return {
        "result": "FAIL" if findings else "PASS",
        "summary_root": str(summary_root),
        "feature": feature,
        "features_checked": features,
        "artifacts_checked": checked,
        "repos": [{"name": n, "path": str(p)} for n, p in repos],
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
    parser.add_argument("--milestone", help="recorded in the ledger line")
    parser.add_argument("--ledger", help="append one JSON record per run to this path")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)

    if args.self_test:
        return run_self_test()

    def finish(code, verdict, inputs=()):
        """One exit point: EVERY return path records a ledger line."""
        append_ledger(args.ledger, argv, args.milestone, list(inputs), verdict, code)
        return code

    try:
        repos = [parse_repo_arg(raw) for raw in (args.repo or ["."])]
        report = build_report(args.summary_root, repos, args.feature)
    except GateError as exc:
        print(json.dumps({"result": "ERROR", "error": str(exc)}))
        return finish(2, "ERROR")

    if args.warn_on_drift:
        for line in report["warnings"]:
            print(f"Warning: {line}", file=sys.stderr)

    print(json.dumps(report, indent=2))
    inputs = report["artifacts_checked"]
    return (finish(0, "PASS", inputs) if report["result"] == "PASS"
            else finish(1, "FAIL", inputs))


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

        def report(self, repos=None, feature=None):
            return build_report(self.summary, repos or [("app", self.repo)],
                                feature)

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
