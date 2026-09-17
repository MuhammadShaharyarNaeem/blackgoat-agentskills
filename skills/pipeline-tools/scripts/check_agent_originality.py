#!/usr/bin/env python3
"""Flags near-duplicate agent personas or methodology skills.

Ported from agency-agents' `check-agent-originality.sh`: a new agent or
skill should be genuinely new. A find-replace "re-skin" of an existing one
(swap an agent name or a stack word and little else) is easy to miss in
review because it is well-formed and mergeable, but it bloats the library
with duplicates. This compares every pair WITHIN each of two groups --
`agents/*.md` and `skills/*/SKILL.md` -- using entity-neutralized 8-word
shingle overlap, so a swapped proper noun can't hide the copy. The two
groups are never compared against each other: an agent persona and a
methodology skill are different content types, and a false match across
them would just be noise.

Algorithm (identical to the shell original): strip YAML frontmatter,
neutralize this tree's entity words and boilerplate (below), lowercase,
strip punctuation, tokenize on whitespace, build the set of 8-word
shingles, and score each pair by Jaccard overlap of their shingle sets.

Neutralized before scoring, so none of it can manufacture or hide overlap:
  * this tree's agent names (rex, aria, alex, iris, scout, echo, mason,
    nova, max, quinn, luna, cipher, ward, dep, vera, forge, blackgoat) and
    stack words (dotnet, csharp, vue, vue3, godot, gdscript, powershell,
    playwright, aws, azure) -- a find-replace re-skin swaps exactly these;
  * the CLAUDE.md convention #10 `## Quick card` disclaimer line and the
    three-bullet inline mapping, which are DELIBERATELY verbatim across 17
    skills and must never be scored as duplication;
  * the standard `## Worker Execution Contract` heading text, present in
    (nearly) every methodology skill by convention #1.

`agents/blackgoat.md` (CLAUDE.md convention #7: the author's psychological
profile, exempt from every agent-audit finding) IS compared like any other
file -- excluding it would hide a real problem if it ever legitimately
converged with another persona -- but a pair involving it can never FAIL or
WARN this gate: its tag reads `N/A` and its detail says so, citing #7.

CALIBRATE, don't guess (see the shell original's header): run this script
against the real tree first, read the full distribution it prints, and set
--fail/--warn defaults with a wide margin above the worst genuine pair.

Usage:
    python check_agent_originality.py [path ...] [--repo <dir>]
        [--fail N] [--warn N] [--top N] [--json]
    python check_agent_originality.py --self-test

With no paths, compares the plugin's own `agents/*.md` and
`skills/*/SKILL.md` under --repo (default: two levels up from this
script, i.e. the plugin root). Explicit paths are re-grouped by shape --
a file named `SKILL.md` joins the skills group, anything else joins the
agents group -- so a CI job can pass only the files a change touched.

Pure standard library. Every file is read as utf-8-sig, so a BOM cannot
break parsing. All output is ASCII except the entity/boilerplate text
embedded in the source, which never reaches stdout.
"""
import argparse
import glob
import json
import os
import re
import sys
import unittest
from pathlib import Path

READ_ENCODING = "utf-8-sig"

# This tree's agent names and stack words -- what a find-replace re-skin
# would swap. Extend as new agents or stacks are added (CLAUDE.md #1/#5).
ENTITY_WORDS = (
    "rex", "aria", "alex", "iris", "scout", "echo", "mason", "nova", "max",
    "quinn", "luna", "cipher", "ward", "dep", "vera", "forge", "blackgoat",
    "dotnet", "csharp", "vue3", "vue", "godot", "gdscript", "powershell",
    "playwright", "aws", "azure",
)
ENTITY_RE = re.compile(r"\b(" + "|".join(ENTITY_WORDS) + r")\b")

# CLAUDE.md convention #10's fixed Quick card disclaimer line. The trailing
# parenthetical varies ("(convention #8)" vs "(convention #8 -- ...)"), so
# only the aside is left open; the rest is the byte-identical text every
# card carries.
DISCLAIMER_RE = re.compile(
    r"Derived from the contract below for a ≤ 3-file change; no new "
    r"rules \(convention #8[^)]*\)\.")

# Convention #10's three-bullet inline mapping, verbatim in every Quick
# card. A plain string, not a regex: it is byte-identical across all 17
# skills that carry it, so there is nothing to make optional.
QUICK_MAPPING = (
    "- Brief → the quick note (What / Where / How verified)\n"
    "- Artifact → the capture at `{quick-root}/evidence/check.md`\n"
    "- Handoff → the `## Result` bullet in `note.md`"
)

# Convention #1's spine heading, present near-verbatim in every methodology
# SKILL.md.
CONTRACT_HEADING = "## Worker Execution Contract"

GROUP_AGENTS = "agents"
GROUP_SKILLS = "skills"

BLACKGOAT_BASENAME = "blackgoat.md"
BLACKGOAT_NOTE = "N/A by design, see CLAUDE.md #7"

DEFAULT_FAIL = 45.0
DEFAULT_WARN = 25.0
DEFAULT_TOP = 15


class GateError(Exception):
    """Structural/usage failure -- maps to exit 2."""


# ---------------------------------------------------------------------------
# Text pipeline
# ---------------------------------------------------------------------------

def strip_frontmatter(text):
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            return parts[2]
    return text


def neutralize_boilerplate(text):
    """Blank the convention #10 card text and the convention #1 heading.

    Done BEFORE lowercasing, on the original text, because the mapping
    block and heading are matched as exact (case-sensitive) strings -- a
    file that varies their case is not carrying the fixed boilerplate.
    """
    text = DISCLAIMER_RE.sub(" ", text)
    text = text.replace(QUICK_MAPPING, " ")
    text = text.replace(CONTRACT_HEADING, " ")
    return text


def tokens(text):
    text = neutralize_boilerplate(strip_frontmatter(text)).lower()
    text = ENTITY_RE.sub(" ", text)
    text = re.sub(r"[^a-z0-9 ]", " ", text)
    return text.split()


def shingles(words, k=8):
    return set(" ".join(words[i:i + k]) for i in range(max(0, len(words) - k + 1)))


def jaccard(a, b):
    return len(a & b) / len(a | b) if a and b else 0.0


# ---------------------------------------------------------------------------
# File discovery and grouping
# ---------------------------------------------------------------------------

def classify(path):
    """Which group a file belongs to: a `SKILL.md` basename, or an agent."""
    return GROUP_SKILLS if Path(path).name == "SKILL.md" else GROUP_AGENTS


def default_paths(repo):
    agents = sorted(glob.glob(os.path.join(repo, "agents", "*.md")))
    skills = sorted(glob.glob(os.path.join(repo, "skills", "*", "SKILL.md")))
    return agents + skills


def rel(path, repo):
    try:
        return os.path.relpath(path, repo).replace(os.sep, "/")
    except ValueError:
        return str(path)


def load_shingle_sets(paths):
    out = {}
    for p in paths:
        try:
            text = Path(p).read_text(encoding=READ_ENCODING, errors="replace")
        except OSError as exc:
            raise GateError("cannot read {0}: {1}".format(p, exc))
        out[p] = shingles(tokens(text))
    return out


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def is_blackgoat(path):
    return Path(path).name == BLACKGOAT_BASENAME


def compute_pairs(paths, repo, fail, warn):
    """Every WITHIN-GROUP pair, each `{a, b, group, pct, tag, detail}`,
    sorted by `pct` descending. A pair naming `agents/blackgoat.md` is
    always tagged `N/A` (CLAUDE.md #7) regardless of `pct`, and never
    counted toward `fails`/`warns`.
    """
    groups = {}
    for p in paths:
        groups.setdefault(classify(p), []).append(p)
    sh = load_shingle_sets(paths)

    pairs = []
    for members in groups.values():
        members = sorted(members)
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                a, b = members[i], members[j]
                pct = jaccard(sh[a], sh[b]) * 100
                entry = {"a": rel(a, repo), "b": rel(b, repo),
                         "group": classify(a), "pct": pct}
                if is_blackgoat(a) or is_blackgoat(b):
                    entry["tag"] = "N/A"
                    entry["detail"] = BLACKGOAT_NOTE
                elif pct >= fail:
                    entry["tag"] = "FAIL"
                    entry["detail"] = None
                elif pct >= warn:
                    entry["tag"] = "WARN"
                    entry["detail"] = None
                else:
                    entry["tag"] = "OK"
                    entry["detail"] = None
                pairs.append(entry)
    pairs.sort(key=lambda e: -e["pct"])
    return pairs


def group_stats(pairs, group):
    pcts = sorted((p["pct"] for p in pairs if p["group"] == group), reverse=True)
    if not pcts:
        return {"count": 0, "worst": 0.0, "median": 0.0}
    mid = len(pcts) // 2
    median = pcts[mid] if len(pcts) % 2 else (pcts[mid - 1] + pcts[mid]) / 2
    return {"count": len(pcts), "worst": pcts[0], "median": median}


def build_report(paths, repo, fail, warn, top):
    if not paths:
        raise GateError("no files to check -- neither agents/*.md nor "
                        "skills/*/SKILL.md was found under {0}".format(repo))
    pairs = compute_pairs(paths, repo, fail, warn)
    fails = [p for p in pairs if p["tag"] == "FAIL"]
    warns = [p for p in pairs if p["tag"] == "WARN"]
    report = {
        "repo": repo,
        "files_checked": len(paths),
        "fail_threshold": fail,
        "warn_threshold": warn,
        "pairs_total": len(pairs),
        "top_pairs": pairs[:top],
        "stats": {GROUP_AGENTS: group_stats(pairs, GROUP_AGENTS),
                 GROUP_SKILLS: group_stats(pairs, GROUP_SKILLS)},
        "fails": fails,
        "warns": warns,
        "result": "FAIL" if fails else "PASS",
    }
    return report


def print_report(report):
    print("Checked {0} file(s), {1} within-group pair(s) "
          "(fail>={2:.0f}%, warn>={3:.0f}%)".format(
              report["files_checked"], report["pairs_total"],
              report["fail_threshold"], report["warn_threshold"]))
    for group in (GROUP_AGENTS, GROUP_SKILLS):
        st = report["stats"][group]
        print("  {0}: {1} pair(s), worst {2:.1f}%, median {3:.1f}%".format(
            group, st["count"], st["worst"], st["median"]))
    print()
    print("Top {0} most similar pair(s):".format(len(report["top_pairs"])))
    for p in report["top_pairs"]:
        line = "  [{0:4}] {1:5.1f}%  {2}  vs  {3}".format(
            p["tag"], p["pct"], p["a"], p["b"])
        print(line)
        if p["detail"]:
            print("           {0}".format(p["detail"]))
    if report["fails"]:
        print()
        print("FAILED: {0} pair(s) at/above the FAIL threshold:".format(
            len(report["fails"])))
        for p in report["fails"]:
            print("  - {0}  ~{1:.0f}% like  {2}".format(p["a"], p["pct"], p["b"]))
        print()
        print("A new agent or skill should be genuinely new. If this is "
              "intended specialization, make the body distinct (different "
              "rules, examples, references) rather than a find-replace of "
              "an existing one.")
    elif report["warns"]:
        print()
        print("{0} warning(s) -- review for overlap, but not "
              "blocking.".format(len(report["warns"])))
    print()
    print("PASSED" if not report["fails"] else "FAILED")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser():
    parser = argparse.ArgumentParser(
        prog="check_agent_originality.py",
        description="Flag near-duplicate agents/*.md or skills/*/SKILL.md "
                    "pairs via entity-neutralized 8-word shingle overlap.",
        epilog="Exit codes: 0 no pair at/above --fail; 1 at least one pair "
               "at/above --fail; 2 usage error (bad --repo, no files found, "
               "an unreadable file). Machine-readable detail with --json: "
               "'result', 'fails', 'warns', 'top_pairs', 'stats'.")
    parser.add_argument("paths", nargs="*",
                        help="files to check (default: this plugin's own "
                             "agents/*.md and skills/*/SKILL.md under "
                             "--repo). A path named SKILL.md joins the "
                             "skills group; anything else joins the agents "
                             "group. Only pairs WITHIN a group are scored.")
    parser.add_argument("--repo",
                        help="plugin root (default: two levels up from "
                             "this script). Used to locate the default "
                             "file sets and to render relative paths in "
                             "the report.")
    parser.add_argument("--fail", type=float, default=DEFAULT_FAIL,
                        help="percent at/above which a pair FAILs "
                             "(default {0:.0f})".format(DEFAULT_FAIL))
    parser.add_argument("--warn", type=float, default=DEFAULT_WARN,
                        help="percent at/above which a pair WARNs "
                             "(default {0:.0f})".format(DEFAULT_WARN))
    parser.add_argument("--top", type=int, default=DEFAULT_TOP,
                        help="how many of the most-similar pairs to print "
                             "(default {0})".format(DEFAULT_TOP))
    parser.add_argument("--json", action="store_true",
                        help="print the report as JSON instead of text")
    parser.add_argument("--self-test", action="store_true",
                        help="run the built-in test suite and exit")
    return parser


def main(argv):
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.self_test:
        return run_self_test()

    repo = args.repo or str(Path(__file__).resolve().parents[2])
    if not Path(repo).is_dir():
        print("error: --repo {0} is not a directory".format(repo),
              file=sys.stderr)
        return 2
    if args.fail < args.warn:
        print("error: --fail ({0}) must be >= --warn ({1})".format(
            args.fail, args.warn), file=sys.stderr)
        return 2
    if args.top < 1:
        print("error: --top must be >= 1", file=sys.stderr)
        return 2

    paths = list(args.paths) if args.paths else default_paths(repo)
    missing = [p for p in paths if not Path(p).is_file()]
    if missing:
        print("error: path(s) not found: {0}".format(", ".join(missing)),
              file=sys.stderr)
        return 2

    try:
        report = build_report(paths, repo, args.fail, args.warn, args.top)
    except GateError as exc:
        print("error: {0}".format(exc), file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print_report(report)
    return 1 if report["result"] == "FAIL" else 0


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

def run_self_test():
    import contextlib
    import io
    import shutil
    import tempfile

    class OriginalityTests(unittest.TestCase):
        def setUp(self):
            self.root = Path(tempfile.mkdtemp())
            self.agents = self.root / "agents"
            self.skills = self.root / "skills"
            self.agents.mkdir()
            self.skills.mkdir()

        def tearDown(self):
            shutil.rmtree(self.root, ignore_errors=True)

        def _agent(self, name, body, dirname=None):
            path = self.agents / name
            fm = "---\nname: {0}\n---\n".format(dirname or name)
            path.write_text(fm + body, encoding="utf-8")
            return path

        def _skill(self, dirname, body):
            d = self.skills / dirname
            d.mkdir()
            path = d / "SKILL.md"
            path.write_text("---\nname: {0}\n---\n".format(dirname) + body,
                            encoding="utf-8")
            return path

        LONG_BODY = (
            "This persona owns the {0} workflow end to end. It reads the "
            "brief, plans the change, writes the {0} code, runs the checks "
            "that prove it, and reports back with a durable handoff block "
            "naming every file it touched and why the change was safe to "
            "make in the first place, start to finish, every single time."
        )

        # -- two near-duplicates differing only by an entity word -> FAIL --

        def test_entity_only_reskin_fails(self):
            a = self._agent("rex.md", self.LONG_BODY.format("rex"))
            b = self._agent("aria.md", self.LONG_BODY.format("aria"))
            report = build_report([str(a), str(b)], str(self.root),
                                  DEFAULT_FAIL, DEFAULT_WARN, DEFAULT_TOP)
            self.assertEqual(report["result"], "FAIL")
            self.assertEqual(len(report["fails"]), 1)
            self.assertAlmostEqual(report["fails"][0]["pct"], 100.0, places=3)

        def test_stack_word_only_reskin_fails(self):
            a = self._skill("dotnet-x", self.LONG_BODY.format("dotnet"))
            b = self._skill("vue3-x", self.LONG_BODY.format("vue3"))
            report = build_report([str(a), str(b)], str(self.root),
                                  DEFAULT_FAIL, DEFAULT_WARN, DEFAULT_TOP)
            self.assertEqual(report["result"], "FAIL")
            named = report["fails"][0]["a"] + " " + report["fails"][0]["b"]
            self.assertIn("dotnet-x/SKILL.md", named)

        # -- two unrelated texts -> pass -------------------------------

        def test_unrelated_texts_pass(self):
            a = self._agent("rex.md",
                            "Rex translates rough ideas into a precise "
                            "specification with numbered requirements and "
                            "explicit open questions for the user to "
                            "resolve before any planning begins at all.")
            b = self._agent("dep.md",
                            "Dep configures the deployment pipeline, writes "
                            "the container manifests, wires the health "
                            "checks, and never touches application code or "
                            "any business logic whatsoever, ever, at all.")
            report = build_report([str(a), str(b)], str(self.root),
                                  DEFAULT_FAIL, DEFAULT_WARN, DEFAULT_TOP)
            self.assertEqual(report["result"], "PASS")
            self.assertEqual(report["fails"], [])

        # -- shared Quick-card boilerplate must not count -----------------

        def test_shared_quick_card_boilerplate_does_not_count(self):
            disclaimer = (
                "## Quick card\n\n"
                "Derived from the contract below for a ≤ 3-file "
                "change; no new rules (convention #8).\n\n"
            )
            mapping = (
                "- Brief → the quick note (What / Where / How "
                "verified)\n"
                "- Artifact → the capture at "
                "`{quick-root}/evidence/check.md`\n"
                "- Handoff → the `## Result` bullet in `note.md`\n\n"
            )
            a = self._skill(
                "skill-one",
                disclaimer +
                "1. Never retry a charge already marked settled "
                "(§ Settlement Guard).\n"
                "2. Ledger writes are append-only (§ Ledger Rules).\n" +
                mapping + "## Worker Execution Contract\n\n" +
                "This skill reviews payment retry logic for correctness "
                "against the ledger before any charge is retried a second "
                "time by the job that owns retries for the whole queue.")
            b = self._skill(
                "skill-two",
                disclaimer +
                "1. The export runs after the nightly close job finishes "
                "(§ Timing).\n"
                "2. A failed upload retries three times, then pages "
                "on-call (§ Delivery).\n" +
                mapping + "## Worker Execution Contract\n\n" +
                "This skill renders the nightly export as a spreadsheet "
                "for finance and uploads it to the shared drive folder "
                "every morning at six sharp, rain or shine, without fail.")
            report = build_report([str(a), str(b)], str(self.root),
                                  DEFAULT_FAIL, DEFAULT_WARN, DEFAULT_TOP)
            self.assertEqual(report["result"], "PASS", report["fails"])
            pair = report["top_pairs"][0]
            self.assertLess(pair["pct"], DEFAULT_WARN)

        # -- agents vs skills are never compared to each other -----------

        def test_agents_and_skills_are_separate_groups(self):
            a = self._agent("rex.md", self.LONG_BODY.format("rex"))
            b = self._skill("rex-skill", self.LONG_BODY.format("rex"))
            report = build_report([str(a), str(b)], str(self.root),
                                  DEFAULT_FAIL, DEFAULT_WARN, DEFAULT_TOP)
            self.assertEqual(report["pairs_total"], 0)
            self.assertEqual(report["result"], "PASS")

        # -- blackgoat.md is compared but never fails/warns this gate ----

        def test_blackgoat_pair_is_na_not_fail(self):
            a = self._agent("blackgoat.md", self.LONG_BODY.format("rex"))
            b = self._agent("rex.md", self.LONG_BODY.format("rex"))
            report = build_report([str(a), str(b)], str(self.root),
                                  DEFAULT_FAIL, DEFAULT_WARN, DEFAULT_TOP)
            self.assertEqual(report["result"], "PASS")
            self.assertEqual(report["fails"], [])
            self.assertEqual(report["warns"], [])
            self.assertEqual(report["top_pairs"][0]["tag"], "N/A")
            self.assertIn("CLAUDE.md #7", report["top_pairs"][0]["detail"])

        # -- WARN sits between the thresholds and never fails the gate ---

        def test_warn_band_does_not_fail(self):
            a = self._agent("rex.md", self.LONG_BODY.format("rex") + " x")
            b = self._agent(
                "aria.md",
                self.LONG_BODY.format("aria") +
                " Aria also keeps a running log of every architectural "
                "decision so the rest of the squad can see why a boundary "
                "was drawn where it was drawn, in plain prose, always.")
            report = build_report([str(a), str(b)], str(self.root),
                                  fail=90.0, warn=1.0, top=DEFAULT_TOP)
            self.assertEqual(report["warns"], report["top_pairs"][:1])
            self.assertEqual(report["result"], "PASS")

    class CliTests(unittest.TestCase):
        """The CLI surface itself: `--help`/`-h` work, exit codes hold."""

        def test_help_exits_zero_and_prints_usage(self):
            out = io.StringIO()
            with self.assertRaises(SystemExit) as ctx, \
                    contextlib.redirect_stdout(out):
                main(["--help"])
            self.assertEqual(ctx.exception.code, 0)
            text = out.getvalue()
            self.assertIn("check_agent_originality.py", text)
            self.assertIn("--self-test", text)

        def test_short_help_flag_also_works(self):
            out = io.StringIO()
            with self.assertRaises(SystemExit) as ctx, \
                    contextlib.redirect_stdout(out):
                main(["-h"])
            self.assertEqual(ctx.exception.code, 0)
            self.assertIn("usage:", out.getvalue())

        def test_fail_below_warn_is_exit_2(self):
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                code = main(["--repo", ".", "--fail", "10", "--warn", "20"])
            self.assertEqual(code, 2)
            self.assertIn("must be >=", err.getvalue())

        def test_nonexistent_repo_is_exit_2(self):
            root = Path(tempfile.mkdtemp())
            err = io.StringIO()
            try:
                with contextlib.redirect_stderr(err):
                    code = main(["--repo", str(root / "nope")])
                self.assertEqual(code, 2)
                self.assertIn("is not a directory", err.getvalue())
            finally:
                shutil.rmtree(root, ignore_errors=True)

        def test_explicit_missing_path_is_exit_2(self):
            root = Path(tempfile.mkdtemp())
            err = io.StringIO()
            try:
                with contextlib.redirect_stderr(err):
                    code = main(["--repo", str(root),
                                str(root / "nope.md")])
                self.assertEqual(code, 2)
                self.assertIn("not found", err.getvalue())
            finally:
                shutil.rmtree(root, ignore_errors=True)

        def test_unknown_flag_is_exit_2(self):
            err = io.StringIO()
            with self.assertRaises(SystemExit) as ctx, \
                    contextlib.redirect_stderr(err):
                main(["--no-such-flag"])
            self.assertEqual(ctx.exception.code, 2)

        def test_json_output_is_parseable(self):
            root = Path(tempfile.mkdtemp())
            try:
                (root / "agents").mkdir()
                (root / "agents" / "a.md").write_text(
                    "---\nname: a\n---\nAlpha does one thing only, calmly.",
                    encoding="utf-8")
                (root / "agents" / "b.md").write_text(
                    "---\nname: b\n---\nBeta does a different thing badly.",
                    encoding="utf-8")
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    code = main(["--repo", str(root), "--json"])
                self.assertEqual(code, 0)
                data = json.loads(out.getvalue())
                self.assertEqual(data["result"], "PASS")
            finally:
                shutil.rmtree(root, ignore_errors=True)

    loader = unittest.defaultTestLoader
    suite = unittest.TestSuite([
        loader.loadTestsFromTestCase(OriginalityTests),
        loader.loadTestsFromTestCase(CliTests),
    ])
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    print("check_agent_originality.py self-test: {0} case(s)".format(
        suite.countTestCases()))
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
