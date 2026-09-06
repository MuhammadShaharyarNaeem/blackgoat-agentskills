#!/usr/bin/env python3
"""Mechanical gate for `runtime-environment.md`, the Tier-1 bring-up recipe.

`bgpdd-discovery/SKILL.md` § 1: "`runtime-environment.md` is the one artifact
here a *later* pipeline depends on to start anything, so existence alone is not
enough: the file must also name at least one service start command and at least
one readiness check. A recipe with neither is a heading, and `/bgpdd-build`
Phase 0 discovers that months later with no one left to ask."

That rule asked the Orchestrator to judge its own artifact at the moment the
pipeline closes, so CLAUDE.md convention #9 makes it a command. The blocks it
looks for are the Environment Manifest's, defined by
`skills/runtime-evidence/SKILL.md` § The Environment Manifest -- this gate
restates none of them, it only asserts they are present and filled.

The one sanctioned way past it is the skip the SKILL itself names: a line
reading `Skipped — user-approved: <reason>` exits 0. The reason is required --
an unreasoned skip is exactly the "indistinguishable from an omission" case
§ 1 says to close.

Usage:
    python check_runtime_recipe.py --recipe <path> [--milestone "<title>"] \
        [--ledger <path>]
    python check_runtime_recipe.py --self-test

Exit 0 PASS, 1 FAIL (findings, missing recipe included), 2 ERROR (usage, an
unreadable path). Pure standard library.
"""
import argparse
import hashlib
import json
import re
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

# The Environment Manifest's blocks. Each entry is (canonical name, regex that
# recognizes its heading or label). Authority: runtime-evidence/SKILL.md.
MANIFEST_BLOCKS = (
    ("Bring-up sequence", r"bring[\s-]*up\s+sequence"),
    ("Services", r"services"),
    ("Repointing map", r"repointing\s+map"),
    ("Forbidden hosts", r"forbidden\s+hosts"),
    ("Test identities & fixtures", r"test\s+identities\s*(?:&|and)\s*fixtures"),
    ("Capabilities", r"capabilities"),
)

SKIP_RE = re.compile(r"^\s*>?\s*\**\s*skipped\s*[—–-]{1,2}\s*user[\s-]*approved\s*:"
                     r"\s*(?P<reason>.*)$", re.I | re.M)
HEADING_RE = re.compile(r"^\s*#{1,6}\s+(?P<text>.+?)\s*#*\s*$")
LABEL_RE = re.compile(r"^\s*[>\-*+\d.]*\s*\**\s*(?P<text>[^:|*]{1,60})\**\s*:")
TABLE_ROW_RE = re.compile(r"^\s*\|(?P<body>.+)\|\s*$")
SEPARATOR_ROW_RE = re.compile(r"^\s*\|[\s:|-]+\|\s*$")
BOLD_CELL_RE = re.compile(r"[*_`]")

START_COLUMN_RE = re.compile(r"start.*command|command.*start|^\s*start\s*$", re.I)
READY_COLUMN_RE = re.compile(r"readiness|ready\s*check|health\s*check", re.I)
START_LABEL_RE = re.compile(r"^\s*start\s+command\s*$", re.I)
READY_LABEL_RE = re.compile(r"^\s*(readiness|ready|health)\s+check\s*$", re.I)

# A cell that says nothing. A recipe whose "Start command" column reads `TBD`
# is the failure this gate exists for, not a pass with a note.
PLACEHOLDERS = {"", "-", "--", "—", "n/a", "na", "none", "tbd", "todo", "?",
                "_todo: pending_", "todo: pending", "pending", "unknown", "..."}


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
        with open(p, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
    except OSError as exc:
        print(f"Warning: could not append to ledger {ledger_path}: {exc}",
              file=sys.stderr)


def is_placeholder(cell):
    """True when a cell carries no fact -- empty, a dash, TBD, a skeleton mark."""
    stripped = BOLD_CELL_RE.sub("", cell).strip().casefold()
    return stripped in PLACEHOLDERS


def block_labels(lines):
    """Every heading text and `Label:` text in the file, lower-cased."""
    labels = []
    for line in lines:
        heading = HEADING_RE.match(line)
        if heading:
            labels.append(heading.group("text").strip().casefold())
            continue
        label = LABEL_RE.match(line)
        if label:
            labels.append(label.group("text").strip().casefold())
    return labels


def find_tables(lines):
    """Every markdown table as (header_cells, [body_row_cells])."""
    tables = []
    pending_header = None
    current = None
    for line in lines:
        match = TABLE_ROW_RE.match(line)
        if not match:
            if current:
                tables.append(current)
                current = None
            pending_header = None
            continue
        if SEPARATOR_ROW_RE.match(line):
            if pending_header is not None:
                current = (pending_header, [])
            pending_header = None
            continue
        cells = [c.strip() for c in match.group("body").split("|")]
        if current is None:
            pending_header = cells
        else:
            current[1].append(cells)
    if current:
        tables.append(current)
    return tables


def harvest_from_tables(tables):
    """(start_values, readiness_values) drawn from Services-shaped tables."""
    starts, readies = [], []
    for header, rows in tables:
        start_idx = [i for i, h in enumerate(header) if START_COLUMN_RE.search(h)]
        ready_idx = [i for i, h in enumerate(header) if READY_COLUMN_RE.search(h)]
        if not start_idx and not ready_idx:
            continue
        for row in rows:
            for i in start_idx:
                if i < len(row) and not is_placeholder(row[i]):
                    starts.append(row[i])
            for i in ready_idx:
                if i < len(row) and not is_placeholder(row[i]):
                    readies.append(row[i])
    return starts, readies


def harvest_from_labels(lines):
    """(start_values, readiness_values) drawn from `Label: value` lines."""
    starts, readies = [], []
    for line in lines:
        label = LABEL_RE.match(line)
        if not label:
            continue
        name = label.group("text").strip()
        value = line.split(":", 1)[1].strip() if ":" in line else ""
        if is_placeholder(value):
            continue
        if START_LABEL_RE.match(name):
            starts.append(value)
        elif READY_LABEL_RE.match(name):
            readies.append(value)
    return starts, readies


def build_report(recipe_path):
    path = Path(recipe_path)
    report = {
        "result": None,
        "recipe": str(recipe_path),
        "skipped": False,
        "skip_reason": None,
        "blocks_present": [],
        "blocks_missing": [],
        "start_commands": [],
        "readiness_checks": [],
        "findings": [],
        "warnings": [],
        "error": None,
    }

    def finding(code, detail, **extra):
        entry = {"code": code, "detail": detail}
        entry.update(extra)
        report["findings"].append(entry)

    if path.exists() and not path.is_file():
        raise GateError(f"--recipe is not a file: {recipe_path}")
    if not path.is_file():
        finding("recipe_missing",
                f"runtime-environment recipe does not exist: {recipe_path}")
        report["result"] = "FAIL"
        return report

    try:
        text = path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError as exc:
        raise GateError(f"cannot read --recipe: {exc}")
    lines = text.splitlines()

    skip = SKIP_RE.search(text)
    if skip:
        reason = skip.group("reason").strip().strip("*_` ")
        report["skipped"] = True
        report["skip_reason"] = reason or None
        if not reason:
            finding("skip_unreasoned",
                    "'Skipped — user-approved:' names no reason; an unreasoned "
                    "skip is indistinguishable from an omission "
                    "(bgpdd-discovery §1)")
            report["result"] = "FAIL"
        else:
            report["result"] = "PASS"
        return report

    labels = block_labels(lines)
    for canonical, pattern in MANIFEST_BLOCKS:
        matcher = re.compile(rf"^{pattern}\b", re.I)
        if any(matcher.match(label) for label in labels):
            report["blocks_present"].append(canonical)
        else:
            report["blocks_missing"].append(canonical)
            finding("block_missing",
                    f"Environment Manifest block '{canonical}' is absent "
                    "(runtime-evidence/SKILL.md § The Environment Manifest)",
                    block=canonical)

    tables = find_tables(lines)
    t_starts, t_readies = harvest_from_tables(tables)
    l_starts, l_readies = harvest_from_labels(lines)
    report["start_commands"] = t_starts + l_starts
    report["readiness_checks"] = t_readies + l_readies

    if not report["start_commands"]:
        finding("start_command_missing",
                "no service start command: no filled 'Start command' table cell "
                "and no 'Start command:' line. A recipe with none is a heading")
    if not report["readiness_checks"]:
        finding("readiness_check_missing",
                "no readiness check: no filled 'Readiness check' table cell and "
                "no 'Readiness check:' line")

    report["result"] = "FAIL" if report["findings"] else "PASS"
    return report


def main(argv):
    parser = argparse.ArgumentParser(prog="check_runtime_recipe.py")
    parser.add_argument("--recipe",
                        help="path to .docs/summary/{feature}/QA/runtime-environment.md")
    parser.add_argument("--milestone", help="recorded in the ledger line")
    parser.add_argument("--ledger", help="append one JSON record per run to this path")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)

    if args.self_test:
        return run_self_test()

    def finish(code, verdict):
        """One exit point: EVERY return path records a ledger line."""
        append_ledger(args.ledger, argv, args.milestone,
                      [args.recipe] if args.recipe else [], verdict, code)
        return code

    if not args.recipe:
        print(json.dumps({"result": "ERROR",
                          "error": "missing required argument: --recipe"}))
        return finish(2, "ERROR")

    try:
        report = build_report(args.recipe)
    except GateError as exc:
        print(json.dumps({"result": "ERROR", "error": str(exc)}))
        return finish(2, "ERROR")

    print(json.dumps(report, indent=2))
    return finish(0, "PASS") if report["result"] == "PASS" else finish(1, "FAIL")


def run_self_test():
    import shutil

    FULL = """# Runtime Environment — slide

## Bring-up sequence

1. Build the plugin project. Needed for: device surfaces.
2. Start the API. Needed for: api, ui.

## Services

| Service | Start command | Local base URL | Readiness check | Calls |
|---|---|---|---|---|
| api | `dotnet run --project src/Api` | http://localhost:5001 | `curl -s http://localhost:5001/health` | db |
| web | `npm run dev` | http://localhost:5173 | page title renders | api |

## Repointing map

| Key | Service | Ships as | Local value |
|---|---|---|---|
| Api:BaseUrl | web | https://dev.example | http://localhost:5001 |

## Forbidden hosts

- `dev.example`

## Test identities & fixtures

- login `qa@example.test`, password from the team vault entry "QA slide"

## Capabilities

- out-of-process HTTP client
- Python 3
"""

    class RecipeTests(unittest.TestCase):
        def setUp(self):
            self.dir = Path(tempfile.mkdtemp())
            self.recipe = self.dir / "runtime-environment.md"

        def tearDown(self):
            shutil.rmtree(self.dir, ignore_errors=True)

        def write(self, text):
            self.recipe.write_text(text, encoding="utf-8")
            return self.recipe

        def codes(self, report):
            return sorted({f["code"] for f in report["findings"]})

        # --- happy paths ---------------------------------------------------
        def test_full_manifest_passes(self):
            r = build_report(self.write(FULL))
            self.assertEqual(r["result"], "PASS", r["findings"])
            self.assertEqual(len(r["start_commands"]), 2)
            self.assertEqual(len(r["readiness_checks"]), 2)
            self.assertEqual(r["blocks_missing"], [])

        def test_label_style_recipe_passes(self):
            """A single-service recipe written as labels, not a table."""
            text = ("# Runtime Environment\n\n"
                    "## Bring-up sequence\n\n1. Start the API.\n\n"
                    "## Services\n\n"
                    "- Start command: `dotnet run --project src/Api`\n"
                    "- Readiness check: `curl -s localhost:5001/health`\n\n"
                    "## Repointing map\n\nnone\n\n"
                    "## Forbidden hosts\n\nnone\n\n"
                    "## Test identities & fixtures\n\nqa@example.test\n\n"
                    "## Capabilities\n\nHTTP client\n")
            r = build_report(self.write(text))
            self.assertEqual(r["result"], "PASS", r["findings"])

        def test_and_spelling_of_the_identities_block_is_accepted(self):
            r = build_report(self.write(
                FULL.replace("Test identities & fixtures",
                             "Test identities and fixtures")))
            self.assertEqual(r["result"], "PASS", r["findings"])

        # --- the two content requirements ------------------------------------
        def test_no_start_command_fails(self):
            text = FULL.replace("`dotnet run --project src/Api`", "TBD")
            text = text.replace("`npm run dev`", " - ")
            r = build_report(self.write(text))
            self.assertEqual(self.codes(r), ["start_command_missing"])

        def test_no_readiness_check_fails(self):
            text = FULL.replace("`curl -s http://localhost:5001/health`", "")
            text = text.replace("page title renders", "TODO")
            self.assertEqual(self.codes(build_report(self.write(text))),
                             ["readiness_check_missing"])

        def test_headings_only_recipe_fails_both(self):
            """The 'a recipe with neither is a heading' case, exactly."""
            text = "\n".join(f"## {name}\n" for name, _ in MANIFEST_BLOCKS)
            r = build_report(self.write("# Runtime Environment\n\n" + text))
            self.assertEqual(self.codes(r),
                             ["readiness_check_missing", "start_command_missing"])
            self.assertEqual(r["blocks_missing"], [])

        def test_placeholder_cells_do_not_count_as_facts(self):
            text = FULL.replace("`dotnet run --project src/Api`", "_TODO: pending_")
            r = build_report(self.write(text))
            self.assertEqual(r["result"], "PASS")  # web's start command remains
            self.assertEqual(r["start_commands"], ["`npm run dev`"])

        # --- manifest blocks --------------------------------------------------
        def test_missing_block_fails(self):
            text = FULL.replace("## Forbidden hosts", "## Hosts we like")
            r = build_report(self.write(text))
            self.assertEqual(self.codes(r), ["block_missing"])
            self.assertEqual(r["blocks_missing"], ["Forbidden hosts"])

        def test_every_block_missing_reports_every_block(self):
            text = ("# Runtime Environment\n\n- Start command: `run.sh`\n"
                    "- Readiness check: `curl /health`\n")
            r = build_report(self.write(text))
            self.assertEqual(len(r["blocks_missing"]), len(MANIFEST_BLOCKS))

        # --- the sanctioned skip ----------------------------------------------
        def test_user_approved_skip_exits_zero(self):
            r = build_report(self.write(
                "# Runtime Environment\n\n"
                "Skipped — user-approved: estate is documented in the team "
                "runbook; user declined to duplicate it.\n"))
            self.assertEqual(r["result"], "PASS", r["findings"])
            self.assertTrue(r["skipped"])
            self.assertIn("runbook", r["skip_reason"])

        def test_skip_with_no_reason_fails(self):
            r = build_report(self.write(
                "# Runtime Environment\n\nSkipped — user-approved:\n"))
            self.assertEqual(self.codes(r), ["skip_unreasoned"])

        def test_plain_hyphen_skip_spelling_is_accepted(self):
            r = build_report(self.write(
                "# Runtime Environment\n\nSkipped - user-approved: no local "
                "estate for this feature.\n"))
            self.assertTrue(r["skipped"])
            self.assertEqual(r["result"], "PASS")

        def test_the_word_skipped_alone_is_not_a_sanctioned_skip(self):
            """An unqualified 'Skipped' must not buy a pass."""
            r = build_report(self.write("# Runtime Environment\n\nSkipped.\n"))
            self.assertFalse(r["skipped"])
            self.assertEqual(r["result"], "FAIL")

        # --- plumbing -----------------------------------------------------------
        def test_missing_recipe_is_a_finding_not_a_pass(self):
            r = build_report(self.dir / "nope.md")
            self.assertEqual(self.codes(r), ["recipe_missing"])

        def test_directory_as_recipe_is_an_error(self):
            with self.assertRaises(GateError):
                build_report(self.dir)

        def test_ledger_records_every_exit_path(self):
            ledger = self.dir / "logs" / "gates.jsonl"
            self.write(FULL)
            self.assertEqual(main(["--recipe", str(self.recipe),
                                   "--ledger", str(ledger)]), 0)
            self.write("# Runtime Environment\n")
            self.assertEqual(main(["--recipe", str(self.recipe),
                                   "--ledger", str(ledger)]), 1)
            self.assertEqual(main(["--ledger", str(ledger)]), 2)
            records = [json.loads(l) for l in
                       ledger.read_text(encoding="utf-8").splitlines() if l.strip()]
            self.assertEqual([r["verdict"] for r in records],
                             ["PASS", "FAIL", "ERROR"])
            self.assertTrue(all(r["gate"] == "check_runtime_recipe.py"
                                for r in records))

    suite = unittest.defaultTestLoader.loadTestsFromTestCase(RecipeTests)
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
