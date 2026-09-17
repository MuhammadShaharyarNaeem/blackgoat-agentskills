#!/usr/bin/env python3
"""Classifies a security/verification report's findings across a rescan.

Given two agent reports written to `check_agent_report.py`'s grammar (an OLD
one and a NEW one -- e.g. a saved copy of Cipher's `security-report.md`
before a fix round, and the same file after Cipher re-ran), prints a table
naming which findings are:

  * RESOLVED  -- fingerprinted in OLD's gated section, absent from NEW's
  * PERSISTENT -- fingerprinted in both
  * NEW       -- fingerprinted in NEW's gated section, absent from OLD's

The fingerprint is `check_agent_report.py`'s: a short sha256 digest of the
normalized `(file, category, title)` key, with the finding's line number
EXCLUDED on purpose -- see that file's "STABLE FINDING FINGERPRINTS" section
for the exact normalization (not restated here). `normalize_finding_key()`,
`finding_fingerprint()` and `iter_findings()` below are byte-identical
copies of that file's functions of the same name (family convention: one
file each, no shared module) -- `check_agent_report.py`'s own self-test
(`test_the_fingerprint_matches_diff_findings`) compares their parsed ASTs on
every run and fails if the two scripts disagree about what "the same
finding" means.

Each report's findings are read from its GATED section only -- the last
'## ' section carrying a '**Verdict:**' line, exactly what
`check_agent_report.py --report` grades and `--emit-fingerprints` lists.
This matters because Cipher's own contract (`agents/cipher.md` § 4) APPENDS
one such section per audit round to the same file and never edits a prior
round's section -- so a finding that was fixed two rounds ago still sits,
unchanged, in an EARLIER section of that same file forever. Reading the
whole file rather than only its gated section would keep counting that
finding as "still there" until the end of time; reading only the latest
section per file is what lets a fixed finding actually resolve.

Findings are matched purely by fingerprint, never by position or order --
a finding that moved between the two reports (same file/category/title,
different line, or reworded only in whitespace/digits) is PERSISTENT, not
NEW, because the fingerprint excludes exactly those two axes of drift.

Usage:
    python diff_findings.py OLD_REPORT NEW_REPORT \
        [--fail-on-new] [--fail-on-persistent]
    python diff_findings.py --self-test

Pure standard library. See ../SKILL.md for the CLI contract.
"""
import argparse
import hashlib
import re
import sys
from pathlib import Path

READ_ENCODING = "utf-8-sig"

SECTION_HEADING_RE = re.compile(r"^##\s+(.*)$")
FENCE_RE = re.compile(r"^[ \t]*(`{3,}|~{3,})")
VERDICT_LINE_RE = re.compile(r"^\s*\*\*Verdict:\*\*(.*)$")
CHECK_LINE_RE = re.compile(
    r"^\s*-\s*(?P<name>[^:]+?):\s*(?P<status>PASS|FAIL|BLOCKED|NOT RUN)\b(?P<rest>.*)$")
FINDING_LINE_RE = re.compile(
    r"^\s*-\s*\*\*(?P<severity>Critical|Important|Suggestion|Nit|FYI)\*\*"
    r"\s+—\s+(?P<title>.+?)\s+—\s+(?P<location>\S+)\s*$")
FINDING_LOCATION_RE = re.compile(r"^(?P<file>.+):(?P<line>\d+)$")
FINGERPRINT_LENGTH = 12


class GateError(Exception):
    """Structural/usage failure — maps to exit 2."""


def read_text(path):
    """Read a UTF-8 artifact, tolerating a byte-order mark (family
    convention, byte-identical to check_agent_report.py's function of the
    same name)."""
    p = Path(path)
    if not p.is_file():
        raise GateError(f"file not found or not readable: {path}")
    return p.read_text(encoding=READ_ENCODING, errors="replace")


def strip_fenced_blocks(text):
    """Blank out every ```/~~~ fenced region, preserving the line count.

    Byte-identical to check_agent_report.py's function of the same name
    (family convention: duplicated per file, no shared module) -- a
    template finding or check line inside a fence must not be counted.
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


def parse_sections(text):
    """Return every level-2 ('## ') section as (title, [body lines]).

    Byte-identical to check_agent_report.py's function of the same name.
    """
    sections = []
    current = None
    for line in text.splitlines():
        m = SECTION_HEADING_RE.match(line)
        if m:
            current = (m.group(1).strip(), [])
            sections.append(current)
        elif current is not None:
            current[1].append(line)
    return sections


def find_gated_section(text):
    """Return (title, body) of the LAST section containing a Verdict line.

    Byte-identical to check_agent_report.py's function of the same name:
    each audit round appends a fresh section there, so the last
    verdict-bearing section is the CURRENT round -- reading anything else
    would compare a stale round instead of this one.
    """
    gated = None
    for title, body in parse_sections(text):
        if any(VERDICT_LINE_RE.match(l) for l in body):
            gated = (title, body)
    return gated


def normalize_finding_key(file_part, category, title):
    """(file, category, title) normalized into the fingerprint's key parts.

    Byte-identical to check_agent_report.py's function of the same name
    (that file's "STABLE FINDING FINGERPRINTS" section owns the rationale;
    not restated here). Guarded against drift by that file's own
    test_the_fingerprint_matches_diff_findings.
    """
    norm_file = (file_part or "").strip().replace("\\", "/")
    norm_category = re.sub(r"\s+", " ", (category or "").strip())
    norm_title = re.sub(r"\d+", "#", title or "")
    norm_title = re.sub(r"\s+", " ", norm_title).strip()
    return norm_file, norm_category, norm_title


def finding_fingerprint(file_part, category, title):
    """Short hex digest of the normalized (file, category, title) key.

    Byte-identical to check_agent_report.py's function of the same name.
    """
    norm_file, norm_category, norm_title = normalize_finding_key(
        file_part, category, title)
    key = "\x1f".join((norm_file, norm_category, norm_title))
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:FINGERPRINT_LENGTH]


def iter_findings(body):
    """Yield (fingerprint, category, file, title) for every finding line in
    a gated section's body lines.

    Byte-identical to check_agent_report.py's function of the same name:
    `category` is the nearest PRECEDING check-line name in the same
    section, or 'uncategorized' when none precedes it yet; `file` excludes
    its line number; `title` is returned RAW for display (only the
    fingerprint is computed over the normalized form).
    """
    category = "uncategorized"
    for line in body:
        check_m = CHECK_LINE_RE.match(line)
        if check_m:
            category = check_m.group("name").strip().strip("*").strip()
            continue
        find_m = FINDING_LINE_RE.match(line)
        if not find_m:
            continue
        title = find_m.group("title").strip()
        location = find_m.group("location").strip().strip("`")
        loc_m = FINDING_LOCATION_RE.match(location)
        file_part = loc_m.group("file") if loc_m else location
        fp = finding_fingerprint(file_part, category, title)
        yield fp, category, file_part.replace("\\", "/"), title


def load_findings(path):
    """(findings dict fp -> (category, file, title), fp order) for one
    report's gated section -- the same section check_agent_report.py
    grades. Raises GateError on the same structural failures that gate
    raises for (missing/empty file, no verdict-bearing section)."""
    raw = read_text(path)
    if not raw.strip():
        raise GateError(f"report file is empty: {path}")
    text = strip_fenced_blocks(raw)
    gated = find_gated_section(text)
    if gated is None:
        raise GateError(f"{path}: no '## ' section containing a "
                        "'**Verdict:**' line found — not a conforming "
                        "agent report")
    _, body = gated
    findings = {}
    order = []
    for fp, category, file_part, title in iter_findings(body):
        if fp not in findings:
            order.append(fp)
        findings[fp] = (category, file_part, title)
    return findings, order


def build_diff(old_path, new_path):
    """{old_report, new_report, resolved, persistent, new}, each of the
    three a list of (fp, category, file, title) in the SOURCE report's
    document order (old order for resolved/persistent-from-old is not used;
    persistent and new use NEW's order, resolved uses OLD's -- the order a
    reader would want: what to still worry about, in the order the current
    report raises it)."""
    old_findings, old_order = load_findings(old_path)
    new_findings, new_order = load_findings(new_path)
    old_fps, new_fps = set(old_findings), set(new_findings)
    resolved = [fp for fp in old_order if fp not in new_fps]
    persistent = [fp for fp in new_order if fp in old_fps]
    new_only = [fp for fp in new_order if fp not in old_fps]
    return {
        "old_report": str(old_path),
        "new_report": str(new_path),
        "resolved": [(fp,) + old_findings[fp] for fp in resolved],
        "persistent": [(fp,) + new_findings[fp] for fp in persistent],
        "new": [(fp,) + new_findings[fp] for fp in new_only],
    }


def render_table(diff):
    """The RESOLVED / PERSISTENT / NEW table, plus a one-line count summary."""
    lines = [f"# Findings diff: {diff['old_report']} -> {diff['new_report']}",
             ""]

    def section(title, rows):
        lines.append(f"## {title} ({len(rows)})")
        if not rows:
            lines.append("(none)")
        else:
            for fp, category, file_part, title_text in rows:
                lines.append(f"- `{fp}`  {category}  {file_part}  {title_text}")
        lines.append("")

    section("RESOLVED", diff["resolved"])
    section("PERSISTENT", diff["persistent"])
    section("NEW", diff["new"])
    lines.append(f"Counts: {len(diff['resolved'])} resolved, "
                f"{len(diff['persistent'])} persistent, "
                f"{len(diff['new'])} new.")
    return "\n".join(lines)


def build_parser():
    parser = argparse.ArgumentParser(
        prog="diff_findings.py",
        description="Classifies a security/verification report's findings "
                    "across a rescan as RESOLVED (fingerprinted in "
                    "OLD_REPORT's gated section, absent from NEW_REPORT's), "
                    "PERSISTENT (both) or NEW (NEW_REPORT only), using "
                    "check_agent_report.py's own finding fingerprint (file, "
                    "category, title -- line number excluded, so a finding "
                    "moved by an unrelated edit stays PERSISTENT rather "
                    "than reading as NEW). See that file's 'STABLE FINDING "
                    "FINGERPRINTS' section for the exact normalization; not "
                    "restated here.",
        epilog="Exit codes: 0 by default, whatever the classification; 1 "
               "under --fail-on-new with a NEW finding present, or "
               "--fail-on-persistent with a PERSISTENT one present (either "
               "message names each such fingerprint and title); 2 usage "
               "error (OLD_REPORT/NEW_REPORT missing) or a report that is "
               "missing, empty, or carries no '**Verdict:**'-bearing "
               "section. The table is printed on stdout regardless of exit "
               "code.",
    )
    parser.add_argument("old_report", nargs="?", metavar="OLD_REPORT",
                        help="the prior round's agent report (e.g. a saved "
                             "copy of security-report.md taken before the "
                             "fix round)")
    parser.add_argument("new_report", nargs="?", metavar="NEW_REPORT",
                        help="the current round's agent report")
    parser.add_argument(
        "--fail-on-new", action="store_true",
        help="exit 1 when NEW_REPORT's gated section carries a finding "
             "fingerprinted nowhere in OLD_REPORT's")
    parser.add_argument(
        "--fail-on-persistent", action="store_true",
        help="exit 1 when a finding is fingerprinted in both reports' "
             "gated sections")
    parser.add_argument("--self-test", action="store_true")
    return parser


def main(argv):
    args = build_parser().parse_args(argv)

    if args.self_test:
        return run_self_test()

    if not args.old_report or not args.new_report:
        print("diff_findings: OLD_REPORT and NEW_REPORT are both required",
              file=sys.stderr)
        return 2

    try:
        diff = build_diff(args.old_report, args.new_report)
    except GateError as exc:
        print(f"diff_findings: {exc}", file=sys.stderr)
        return 2

    print(render_table(diff))

    problems = []
    if args.fail_on_new and diff["new"]:
        problems.append(("new", diff["new"]))
    if args.fail_on_persistent and diff["persistent"]:
        problems.append(("persistent", diff["persistent"]))
    if problems:
        for kind, rows in problems:
            names = ", ".join(f"{fp} ({title})" for fp, _c, _f, title in rows)
            print(f"diff_findings: {len(rows)} {kind} finding(s) — triage "
                 f"or fix these before the verdict: {names}", file=sys.stderr)
        return 1
    return 0


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

def run_self_test():
    import shutil
    import tempfile
    import unittest

    OLD_T = (
        "## Security Audit: Shipping — 2026-09-01\n\n"
        "- Secrets scan: PASS — `git grep -n secret` — exit 1 — 0 matches\n"
        "- **Critical** — hardcoded JWT secret — src/auth/token.js:14\n\n"
        "- Rate limiting: FAIL — `curl -i /api/x` — exit 0\n"
        "- **Important** — 3 endpoints missing rate limiting — src/api/routes.js:88\n\n"
        "**Verdict:** Fail\n")

    class DiffTests(unittest.TestCase):
        def setUp(self):
            self.dir = Path(tempfile.mkdtemp())
            self.old = self.dir / "old.md"
            self.new = self.dir / "new.md"
            self.old.write_text(OLD_T, encoding="utf-8")

        def tearDown(self):
            shutil.rmtree(self.dir, ignore_errors=True)

        def test_identical_reports_are_all_persistent(self):
            self.new.write_text(OLD_T.replace("2026-09-01", "2026-09-17"),
                                encoding="utf-8")
            diff = build_diff(str(self.old), str(self.new))
            self.assertEqual(len(diff["resolved"]), 0)
            self.assertEqual(len(diff["persistent"]), 2)
            self.assertEqual(len(diff["new"]), 0)

        def test_a_moved_finding_is_persistent_not_new(self):
            """Same file/category/title, different line -> PERSISTENT."""
            moved = OLD_T.replace(
                "hardcoded JWT secret — src/auth/token.js:14",
                "hardcoded  JWT   secret — src/auth/token.js:55")
            self.new.write_text(moved, encoding="utf-8")
            diff = build_diff(str(self.old), str(self.new))
            self.assertEqual(len(diff["resolved"]), 0)
            self.assertEqual(len(diff["persistent"]), 2)
            self.assertEqual(len(diff["new"]), 0)

        def test_a_fixed_finding_is_resolved(self):
            fixed = (
                "## Security Audit: Shipping — 2026-09-17\n\n"
                "- Secrets scan: PASS — `git grep -n secret` — exit 1 — 0 matches\n\n"
                "- Rate limiting: FAIL — `curl -i /api/x` — exit 0\n"
                "- **Important** — 3 endpoints missing rate limiting — src/api/routes.js:88\n\n"
                "**Verdict:** Fail\n")
            self.new.write_text(fixed, encoding="utf-8")
            diff = build_diff(str(self.old), str(self.new))
            self.assertEqual(len(diff["resolved"]), 1)
            self.assertEqual(diff["resolved"][0][3], "hardcoded JWT secret")
            self.assertEqual(len(diff["persistent"]), 1)
            self.assertEqual(len(diff["new"]), 0)

        def test_a_fresh_finding_is_new(self):
            fresh = OLD_T.replace(
                "**Verdict:** Fail\n",
                "- **Suggestion** — missing security headers — src/mid.js:5\n\n"
                "**Verdict:** Fail\n")
            self.new.write_text(fresh, encoding="utf-8")
            diff = build_diff(str(self.old), str(self.new))
            self.assertEqual(len(diff["resolved"]), 0)
            self.assertEqual(len(diff["persistent"]), 2)
            self.assertEqual(len(diff["new"]), 1)
            self.assertEqual(diff["new"][0][3], "missing security headers")

        def test_fail_on_new_exits_1_and_names_the_finding(self):
            fresh = OLD_T.replace(
                "**Verdict:** Fail\n",
                "- **Suggestion** — missing security headers — src/mid.js:5\n\n"
                "**Verdict:** Fail\n")
            self.new.write_text(fresh, encoding="utf-8")
            rc = main(["--fail-on-new", str(self.old), str(self.new)])
            self.assertEqual(rc, 1)

        def test_fail_on_new_does_not_fire_on_persistent_only(self):
            self.new.write_text(OLD_T.replace("2026-09-01", "2026-09-17"),
                                encoding="utf-8")
            rc = main(["--fail-on-new", str(self.old), str(self.new)])
            self.assertEqual(rc, 0)

        def test_fail_on_persistent_exits_1(self):
            self.new.write_text(OLD_T.replace("2026-09-01", "2026-09-17"),
                                encoding="utf-8")
            rc = main(["--fail-on-persistent", str(self.old), str(self.new)])
            self.assertEqual(rc, 1)

        def test_default_exits_0_regardless_of_classification(self):
            self.new.write_text(OLD_T.replace("2026-09-01", "2026-09-17"),
                                encoding="utf-8")
            rc = main([str(self.old), str(self.new)])
            self.assertEqual(rc, 0)

        def test_missing_report_exits_2(self):
            rc = main([str(self.old), str(self.dir / "absent.md")])
            self.assertEqual(rc, 2)

        def test_no_gated_section_exits_2(self):
            self.new.write_text("# Report\n\n## Notes\n\nprose only\n",
                                encoding="utf-8")
            rc = main([str(self.old), str(self.new)])
            self.assertEqual(rc, 2)

        def test_missing_positional_args_is_usage_error(self):
            self.assertEqual(main([]), 2)
            self.assertEqual(main([str(self.old)]), 2)

        def test_render_table_has_three_sections_and_counts(self):
            self.new.write_text(OLD_T.replace("2026-09-01", "2026-09-17"),
                                encoding="utf-8")
            diff = build_diff(str(self.old), str(self.new))
            table = render_table(diff)
            self.assertIn("## RESOLVED", table)
            self.assertIn("## PERSISTENT", table)
            self.assertIn("## NEW", table)
            self.assertIn("2 persistent", table)

    suite = unittest.defaultTestLoader.loadTestsFromTestCase(DiffTests)
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
