#!/usr/bin/env python3
"""Intake gate for the bgpdd-bugfix lane's durable bug report.

Converts the prose rule that a bugfix starts from a written report rather
than from chat scrollback into an artifact that has to exist on disk. Reads
`{bugfix-root}/bug-report.md` (template:
`bgpdd-bugfix/references/bug-report-template.md`) and verifies:

  * every required section heading is present
  * every section body is non-empty AND not still the template's placeholder
  * the Reproduction section carries EITHER a `- Command:` line OR at least
    two numbered steps -- a report nobody can re-run is not a reproduction
  * `- Surface:` is one of `api` / `ui` / `both` (the enum, not the template's
    unanswered `api | ui | both` line)
  * `- Runtime observable:` is `yes` or `no` -- this is what makes the
    bugfix lane's runtime-evidence obligation a mechanical decision instead
    of a judgement call at the gate
  * `- Regression:` is `yes` or `no`, and a `yes` names a `- Last known good:`

Fenced regions (``` or ~~~) are MASKED before headings and field lines are
read, so a heading or a `- Surface: api` inside an example block cannot
satisfy the gate -- but a masked line still COUNTS AS CONTENT, because a
pasted log excerpt is exactly what the error section is supposed to hold.
That is a deliberate divergence from the family's blank-the-fence rule
(pipeline-tools/SKILL.md, "Fenced blocks and encoding"; CLAUDE.md
convention #8): blanking would make an honest log paste read as an empty
section. Every file is read as utf-8-sig, so a BOM cannot break parsing.

Pure standard library.

Usage:
    python check_bugfix_intake.py --report <path> [--milestone "<slug>"] \
        [--ledger <path>]
    python check_bugfix_intake.py --self-test
"""
import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

READ_ENCODING = "utf-8-sig"

FENCE_RE = re.compile(r"^[ \t]*(`{3,}|~{3,})")
# A fenced content line becomes this sentinel: not parseable as a heading or
# a field, but still counted as section content.
FENCED_SENTINEL = "\x00fenced\x00"
HEADING_RE = re.compile(r"^(#{2,6})\s*(.+?)\s*#*\s*$")
FIELD_RE = re.compile(r"^\s*[-*]\s*([A-Za-z][A-Za-z /_-]{1,40}?)\s*:\s*(.*)$")
NUMBERED_STEP_RE = re.compile(r"^\s*\d+[.)]\s+\S")

# A line that is only a template stand-in. `<...>` is the template's own
# shape; the word list is what an author types when skipping a section.
PLACEHOLDER_LINE_RE = re.compile(
    r"^(?:<[^>]*>|todo|tbd|fixme|n/?a|none|unknown|\?+|\.{3,}|xxx+"
    r"|_todo[^_]*_)[.:]?$", re.IGNORECASE)
# A field VALUE stand-in. `none`/`n/a` count here too: a non-answer in a
# required field is the same defect as an empty one.
PLACEHOLDER_VALUE_RE = re.compile(
    r"^(?:<[^>]*>|todo|tbd|fixme|n/?a|none|unknown|\?+|\.{3,}|xxx+)[.:]?$",
    re.IGNORECASE)

# (key, heading pattern, human name). Order is the report's own order.
REQUIRED_SECTIONS = (
    ("observed", re.compile(r"^observed behaviou?r\b"), "Observed behaviour"),
    ("expected", re.compile(r"^expected behaviou?r\b"), "Expected behaviour"),
    ("error", re.compile(r"error text|log excerpt"),
     "Exact error text or log excerpt"),
    ("reproduction", re.compile(r"^reproduction\b"), "Reproduction"),
    ("environment", re.compile(r"^environment\b"), "Environment"),
    ("regression", re.compile(r"^regression\b"), "Regression"),
    ("surface", re.compile(r"^(?:affected )?surface\b"), "Affected surface"),
)

SURFACE_VALUES = ("api", "ui", "both")
YES_NO = ("yes", "no")

# A `- Command:` value must be BACKTICK-WRAPPED. This gate's own error text
# names the shape ``- Command: `<cmd>` ``, so it has to enforce it: without
# the backticks, `- Command: see chat` satisfied the reproduction check while
# pointing at the very scrollback this gate exists to replace.
BACKTICKED_RE = re.compile(r"^`([^`]+)`$")
# ...and the wrapped text must look like a command rather than a phrase:
# >= 2 whitespace-separated tokens, or one token carrying a path/URL/extension
# character. `pytest` is one token and legitimate; `see` is not.
COMMAND_TOKENISH_RE = re.compile(r"[/\\.:]")


class GateError(Exception):
    """Structural/usage failure -- maps to exit 2."""


# ---------------------------------------------------------------------------
# Shared gate ledger (see ../SKILL.md, "Gate ledger")
# ---------------------------------------------------------------------------

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


def append_ledger(ledger_path, argv, milestone, inputs, verdict, exit_code,
                  extra=None):
    """Append ONE JSON line recording this run. Best-effort by design.

    A ledger that cannot be written must never change the gate's own verdict.
    Duplicated from check_commit_gate.py by family convention (stdlib-only,
    one file each, no shared module).
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
        with open(p, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
    except OSError as exc:
        print(f"Warning: could not append to ledger {ledger_path}: {exc}",
              file=sys.stderr)


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def read_text(path):
    p = Path(path)
    if not p.is_file():
        raise GateError(f"file not found or not readable: {path}")
    return p.read_text(encoding=READ_ENCODING, errors="replace")


def mask_fenced_lines(text):
    """Fenced content lines -> FENCED_SENTINEL; fence delimiters -> "".

    Line count is preserved so any line-indexed diagnostic stays honest.
    See the module docstring for why this masks rather than blanks.
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
            else:
                out.append(FENCED_SENTINEL)
    return out


def parse_sections(lines):
    """Return an ordered list of (heading_text, [body lines]) for level 2-6."""
    sections, current = [], None
    for line in lines:
        m = HEADING_RE.match(line)
        if m:
            current = (m.group(2).strip(), [])
            sections.append(current)
        elif current is not None:
            current[1].append(line)
    return sections


def content_lines(body):
    """Non-blank body lines. A masked fence line counts as content."""
    return [l for l in body if l.strip()]


def is_placeholder_body(body):
    """True when the section's real content is only a template stand-in.

    Two forms, because the template writes both: every line individually a
    stand-in, OR one `<...>` span WRAPPED across several lines. Checking
    line-by-line alone let a multi-line `<Explain what happens ...>` block
    read as real prose -- the single most likely way a skipped section
    reaches the gate.
    """
    real = [l.strip() for l in content_lines(body) if l != FENCED_SENTINEL]
    if not real:
        return False   # fenced-only content is real content, not placeholder
    if all(PLACEHOLDER_LINE_RE.match(l) for l in real):
        return True
    return bool(PLACEHOLDER_LINE_RE.match(" ".join(real)))


def fields_in(body):
    """`- Key: value` pairs in a section body, lower-cased keys, last wins."""
    found = {}
    for line in body:
        if line == FENCED_SENTINEL:
            continue
        m = FIELD_RE.match(line)
        if m:
            found[m.group(1).strip().lower()] = m.group(2).strip()
    return found


def clean_value(raw):
    """A field value with surrounding backticks/quotes stripped."""
    return (raw or "").strip().strip("`").strip('"').strip("'").strip()


def value_present(raw):
    v = clean_value(raw)
    return bool(v) and not PLACEHOLDER_VALUE_RE.match(v)


def usable_command(raw):
    """(command string or None, reason-when-None) for a `- Command:` value.

    Three requirements, in the order they fail most often:

      1. **Backtick-wrapped.** `- Command: see chat` used to satisfy the
         reproduction check while pointing at the scrollback this gate exists
         to replace. The gate's error text always named the backticked shape;
         now it enforces it.
      2. **Not a placeholder** (`<the single command>`, `TODO`, `N/A`, ...).
      3. **Command-shaped**: at least two whitespace-separated tokens, or one
         token carrying a `/`, `\\`, `.` or `:` (a path, a URL, an
         executable with an extension). `pytest` is one bare token and is
         deliberately REJECTED as a phrase; write `python -m pytest` or
         `pytest tests/` instead -- a one-word value is indistinguishable from
         prose, and the cost of the false negative is one word of typing.

    Documented scope limit: `` `see chat` `` has two tokens and PASSES here.
    Backticks plus two words is as far as a text lint can go. It is closed
    mechanically one phase later -- `next_bugfix_route.py --red` requires the
    RED sidecar's recorded `argv` to equal this string, and no probe ever ran
    `see chat`.
    """
    text = (raw or "").strip()
    if not text:
        return None, "the '- Command:' line has no value"
    m = BACKTICKED_RE.match(text)
    if not m:
        return None, (f"'- Command:' value {text!r} is not backtick-wrapped; "
                      "required: '- Command: `<the command>`' — an unquoted "
                      "value is prose, and prose cannot be re-run")
    inner = m.group(1).strip()
    if not inner or PLACEHOLDER_VALUE_RE.match(inner):
        return None, (f"'- Command:' value {inner!r} is a placeholder, not a "
                      "command")
    tokens = inner.split()
    if len(tokens) < 2 and not COMMAND_TOKENISH_RE.search(inner):
        return None, (f"'- Command:' value {inner!r} is a single bare word "
                      "with no path, URL or extension character — that is "
                      "indistinguishable from prose; write the full "
                      "invocation")
    return inner, None


def build_report(args):
    report = {
        "report": args.report,
        "sections_found": [],
        "sections_missing": [],
        "placeholder_sections": [],
        "reproduction_mode": None,
        "reproduction_command": None,
        "surface": None,
        "runtime_observable": None,
        "regression": None,
        "last_known_good": None,
        "problems": [],
        "problem_codes": [],
        "warnings": [],
        "result": "FAIL",
        "error": None,
    }

    def fail(code, message):
        report["problems"].append(f"{code}: {message}")
        report["problem_codes"].append(code)

    lines = mask_fenced_lines(read_text(args.report))
    sections = parse_sections(lines)
    if not sections:
        raise GateError(
            "no level-2..6 heading found outside a fenced block — this is "
            "structurally not a bug report; start from "
            "bgpdd-bugfix/references/bug-report-template.md")

    bodies = {}
    for key, pattern, name in REQUIRED_SECTIONS:
        match = next((s for s in sections
                      if pattern.search(s[0].strip().lower())), None)
        if match is None:
            report["sections_missing"].append(name)
            fail("section_missing", f"no '{name}' section")
            continue
        report["sections_found"].append(name)
        bodies[key] = match[1]
        if not content_lines(match[1]):
            report["placeholder_sections"].append(name)
            fail("section_empty", f"the '{name}' section has no content")
        elif is_placeholder_body(match[1]):
            report["placeholder_sections"].append(name)
            fail("section_placeholder",
                 f"the '{name}' section still holds the template's "
                 "placeholder text")

    # --- Reproduction: a command OR at least two numbered steps ---
    repro = bodies.get("reproduction")
    if repro is not None:
        raw_command = fields_in(repro).get("command")
        command, command_problem = (usable_command(raw_command)
                                    if raw_command is not None
                                    else (None, None))
        # A step whose text is still `<first step>` is not a step. Counting
        # placeholder steps let the shipped template satisfy this check.
        steps = [l for l in repro
                 if l != FENCED_SENTINEL and NUMBERED_STEP_RE.match(l)
                 and value_present(re.sub(r"^\s*\d+[.)]\s+", "", l))]
        if command:
            report["reproduction_mode"] = "command"
            report["reproduction_command"] = command
        elif len(steps) >= 2:
            report["reproduction_mode"] = "steps"
            # An unusable Command line beside usable steps is still a defect
            # worth naming: the route gate reads the mode, and a half-written
            # command line is the shape an author abandons mid-edit.
            if command_problem:
                report["warnings"].append(
                    f"{command_problem}; falling back to the numbered steps")
        else:
            detail = (command_problem or
                      "the 'Reproduction' section carries no '- Command:' line")
            fail("reproduction_missing",
                 f"{detail} — and there are only {len(steps)} usable numbered "
                 "step(s), fewer than the 2 required. A report nobody can "
                 "re-run cannot produce a RED capture")

    # --- Affected surface: the enum, plus the runtime-observable axis ---
    surface_body = bodies.get("surface")
    if surface_body is not None:
        f = fields_in(surface_body)
        raw_surface = clean_value(f.get("surface", "")).lower()
        if raw_surface in SURFACE_VALUES:
            report["surface"] = raw_surface
        else:
            fail("surface_invalid",
                 f"'- Surface:' is {raw_surface or '(absent)'!r}; required: "
                 "exactly one of api / ui / both (the template's unanswered "
                 "'api | ui | both' line does not count)")
        raw_ro = clean_value(f.get("runtime observable", "")).lower()
        if raw_ro in YES_NO:
            report["runtime_observable"] = raw_ro == "yes"
        else:
            fail("runtime_observable_invalid",
                 f"'- Runtime observable:' is {raw_ro or '(absent)'!r}; "
                 "required: exactly yes or no — the bugfix lane reads this to "
                 "decide whether a runtime capture gates the fix")

    # --- Regression: yes needs a last-known-good ---
    reg_body = bodies.get("regression")
    if reg_body is not None:
        f = fields_in(reg_body)
        raw_reg = clean_value(f.get("regression", "")).lower()
        if raw_reg in YES_NO:
            report["regression"] = raw_reg == "yes"
        else:
            fail("regression_invalid",
                 f"'- Regression:' is {raw_reg or '(absent)'!r}; required: "
                 "exactly yes or no")
        lkg = f.get("last known good")
        if value_present(lkg):
            report["last_known_good"] = clean_value(lkg)
        if report["regression"] and report["last_known_good"] is None:
            fail("last_known_good_missing",
                 "'- Regression: yes' with no usable '- Last known good:' "
                 "value — a regression with no last-known-good gives the "
                 "Isolate phase nothing to bisect between")

    report["result"] = "PASS" if not report["problems"] else "FAIL"
    return report


def build_parser():
    parser = argparse.ArgumentParser(prog="check_bugfix_intake.py")
    parser.add_argument("--report", help="path to bug-report.md")
    parser.add_argument("--milestone",
                        help="bug slug, to scope this run's ledger record")
    parser.add_argument("--ledger",
                        help="append one JSON record per run to this path")
    parser.add_argument("--self-test", action="store_true")
    return parser


def main(argv):
    args = build_parser().parse_args(argv)
    if args.self_test:
        return run_self_test()

    def finish(code, verdict):
        """One exit point: EVERY return path records a ledger line."""
        append_ledger(args.ledger, argv, args.milestone,
                      [args.report] if args.report else [], verdict, code)
        return code

    if not args.report:
        print(json.dumps({"result": "ERROR",
                          "error": "missing required argument(s): --report"}))
        return finish(2, "ERROR")
    try:
        report = build_report(args)
    except GateError as exc:
        print(json.dumps({"result": "ERROR", "error": str(exc)}))
        return finish(2, "ERROR")
    print(json.dumps(report, indent=2))
    passed = report["result"] == "PASS"
    return finish(0 if passed else 1, "PASS" if passed else "FAIL")


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

def run_self_test():
    import contextlib
    import io
    import shutil
    import tempfile
    import unittest

    def report_text(observed="the endpoint returns 500", expected="it returns 400",
                    error="```\nSystem.NullReferenceException\n```",
                    reproduction="- Command: `curl -sS -i http://localhost:5142/api/orders`",
                    environment="- Branch: main\n- Version: 2.1.0",
                    regression="- Regression: no",
                    surface="- Surface: api\n- Runtime observable: yes"):
        return (
            "# Bug report: coupon 500\n\n"
            f"## Observed behaviour\n\n{observed}\n\n"
            f"## Expected behaviour\n\n{expected}\n\n"
            f"## Exact error text or log excerpt\n\n{error}\n\n"
            f"## Reproduction\n\n{reproduction}\n\n"
            f"## Environment\n\n{environment}\n\n"
            f"## Regression\n\n{regression}\n\n"
            f"## Affected surface\n\n{surface}\n")

    class IntakeTests(unittest.TestCase):
        def setUp(self):
            self.dir = Path(tempfile.mkdtemp())
            self.report = self.dir / "bug-report.md"

        def tearDown(self):
            shutil.rmtree(self.dir, ignore_errors=True)

        def _run(self, text=None, extra=None, raw=None):
            if raw is not None:
                self.report.write_bytes(raw)
            else:
                self.report.write_text(text if text is not None else report_text(),
                                       encoding="utf-8")
            args = build_parser().parse_args(
                ["--report", str(self.report)] + (extra or []))
            return build_report(args)

        def _main(self, argv):
            buf, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(err):
                code = main(argv)
            return code, buf.getvalue()

        # ---- happy paths ----

        def test_command_report_passes(self):
            r = self._run()
            self.assertEqual(r["result"], "PASS", r["problems"])
            self.assertEqual(r["reproduction_mode"], "command")
            self.assertEqual(r["surface"], "api")
            self.assertTrue(r["runtime_observable"])
            self.assertFalse(r["regression"])
            self.assertEqual(len(r["sections_found"]), 7)

        def test_numbered_steps_report_passes(self):
            r = self._run(report_text(reproduction=(
                "1. Sign in as a standard user.\n"
                "2. Apply an empty coupon code at checkout.\n"
                "3. Observe the 500.")))
            self.assertEqual(r["result"], "PASS", r["problems"])
            self.assertEqual(r["reproduction_mode"], "steps")

        def test_surface_both_is_accepted(self):
            r = self._run(report_text(surface=(
                "- Surface: both\n- Runtime observable: yes")))
            self.assertEqual(r["result"], "PASS", r["problems"])
            self.assertEqual(r["surface"], "both")

        def test_runtime_observable_no_is_accepted(self):
            r = self._run(report_text(surface=(
                "- Surface: api\n- Runtime observable: no")))
            self.assertEqual(r["result"], "PASS", r["problems"])
            self.assertFalse(r["runtime_observable"])

        def test_regression_yes_with_last_known_good_passes(self):
            r = self._run(report_text(regression=(
                "- Regression: yes\n- Last known good: v2.0.4 (commit ab12cd3)")))
            self.assertEqual(r["result"], "PASS", r["problems"])
            self.assertTrue(r["regression"])
            self.assertIn("v2.0.4", r["last_known_good"])

        # ---- adversarial ----

        def test_missing_section_fails(self):
            text = report_text().replace(
                "## Environment\n\n- Branch: main\n- Version: 2.1.0\n\n", "")
            r = self._run(text)
            self.assertEqual(r["result"], "FAIL")
            self.assertIn("Environment", r["sections_missing"])
            self.assertIn("section_missing", r["problem_codes"])

        def test_placeholder_section_fails(self):
            r = self._run(report_text(observed="<what actually happens>"))
            self.assertEqual(r["result"], "FAIL")
            self.assertIn("Observed behaviour", r["placeholder_sections"])
            self.assertIn("section_placeholder", r["problem_codes"])

        def test_todo_section_fails(self):
            r = self._run(report_text(expected="TODO"))
            self.assertEqual(r["result"], "FAIL")
            self.assertIn("section_placeholder", r["problem_codes"])

        def test_empty_section_fails(self):
            r = self._run(report_text(environment=""))
            self.assertEqual(r["result"], "FAIL")
            self.assertIn("section_empty", r["problem_codes"])

        def test_unanswered_surface_enum_fails(self):
            r = self._run(report_text(surface=(
                "- Surface: api | ui | both\n- Runtime observable: yes")))
            self.assertEqual(r["result"], "FAIL")
            self.assertIn("surface_invalid", r["problem_codes"])
            self.assertIsNone(r["surface"])

        def test_unanswered_runtime_observable_fails(self):
            r = self._run(report_text(surface=(
                "- Surface: api\n- Runtime observable: yes | no")))
            self.assertEqual(r["result"], "FAIL")
            self.assertIn("runtime_observable_invalid", r["problem_codes"])

        def test_no_reproduction_fails(self):
            r = self._run(report_text(reproduction="it happens sometimes"))
            self.assertEqual(r["result"], "FAIL")
            self.assertIn("reproduction_missing", r["problem_codes"])
            self.assertIsNone(r["reproduction_mode"])

        def test_single_numbered_step_is_not_a_reproduction(self):
            r = self._run(report_text(reproduction="1. Open the app."))
            self.assertEqual(r["result"], "FAIL")
            self.assertIn("reproduction_missing", r["problem_codes"])

        def test_placeholder_command_is_not_a_reproduction(self):
            r = self._run(report_text(
                reproduction="- Command: `<the single command>`"))
            self.assertEqual(r["result"], "FAIL")
            self.assertIn("reproduction_missing", r["problem_codes"])

        # ---- the `- Command:` value contract ----

        def test_real_command_passes_and_is_reported(self):
            r = self._run(report_text(
                reproduction="- Command: `dotnet test --filter CouponTests`"))
            self.assertEqual(r["result"], "PASS", r["problems"])
            self.assertEqual(r["reproduction_mode"], "command")
            self.assertEqual(r["reproduction_command"],
                             "dotnet test --filter CouponTests")

        def test_unbackticked_see_chat_fails(self):
            """The hole: prose pointing at the scrollback this gate replaces."""
            r = self._run(report_text(reproduction="- Command: see chat"))
            self.assertEqual(r["result"], "FAIL")
            self.assertIn("reproduction_missing", r["problem_codes"])
            self.assertTrue(any("not backtick-wrapped" in p
                                for p in r["problems"]))
            self.assertIsNone(r["reproduction_command"])

        def test_unbackticked_real_command_also_fails(self):
            """The rule is the shape, not the content -- no special-casing."""
            r = self._run(report_text(
                reproduction="- Command: dotnet test --filter CouponTests"))
            self.assertEqual(r["result"], "FAIL")
            self.assertIn("reproduction_missing", r["problem_codes"])

        def test_backticked_see_chat_passes_intake_by_documented_design(self):
            """`see chat` in backticks has two tokens and PASSES here.

            Backticks plus two words is as far as a text lint can go. It is
            closed one phase later: next_bugfix_route.py --red requires the RED
            sidecar's argv to equal this string, and no probe ran `see chat`.
            """
            r = self._run(report_text(reproduction="- Command: `see chat`"))
            self.assertEqual(r["result"], "PASS", r["problems"])
            self.assertEqual(r["reproduction_command"], "see chat")

        def test_single_bare_word_command_fails(self):
            r = self._run(report_text(reproduction="- Command: `pytest`"))
            self.assertEqual(r["result"], "FAIL")
            self.assertTrue(any("single bare word" in p for p in r["problems"]))

        def test_single_token_with_a_path_character_passes(self):
            r = self._run(report_text(
                reproduction="- Command: `./scripts/repro.sh`"))
            self.assertEqual(r["result"], "PASS", r["problems"])
            self.assertEqual(r["reproduction_command"], "./scripts/repro.sh")

        def test_bad_command_beside_usable_steps_warns_and_uses_steps(self):
            r = self._run(report_text(reproduction=(
                "- Command: see chat\n\n"
                "1. Sign in as a standard user.\n"
                "2. Apply an empty coupon code at checkout.")))
            self.assertEqual(r["result"], "PASS", r["problems"])
            self.assertEqual(r["reproduction_mode"], "steps")
            self.assertTrue(any("not backtick-wrapped" in w
                                for w in r["warnings"]))

        def test_regression_yes_without_last_known_good_fails(self):
            r = self._run(report_text(regression="- Regression: yes"))
            self.assertEqual(r["result"], "FAIL")
            self.assertIn("last_known_good_missing", r["problem_codes"])

        def test_regression_yes_with_placeholder_last_known_good_fails(self):
            r = self._run(report_text(regression=(
                "- Regression: yes\n- Last known good: <commit or tag>")))
            self.assertEqual(r["result"], "FAIL")
            self.assertIn("last_known_good_missing", r["problem_codes"])

        def test_fenced_heading_does_not_satisfy_a_section(self):
            """A whole report pasted inside a fence satisfies nothing."""
            text = ("# Bug report\n\n## Observed behaviour\n\nreal text\n\n"
                    "## Example of the rest\n\n```markdown\n"
                    + report_text() + "\n```\n")
            r = self._run(text)
            self.assertEqual(r["result"], "FAIL")
            self.assertIn("Expected behaviour", r["sections_missing"])

        def test_fenced_field_does_not_satisfy_the_enum(self):
            r = self._run(report_text(surface=(
                "```\n- Surface: api\n- Runtime observable: yes\n```")))
            self.assertEqual(r["result"], "FAIL")
            self.assertIn("surface_invalid", r["problem_codes"])
            self.assertIn("runtime_observable_invalid", r["problem_codes"])

        def test_fenced_only_error_section_counts_as_content(self):
            """The load-bearing divergence: a pasted log IS the content."""
            r = self._run(report_text(
                error="```\nUnhandled exception. NullReferenceException\n"
                      "   at Api.Coupons.Apply(String code)\n```"))
            self.assertEqual(r["result"], "PASS", r["problems"])
            self.assertNotIn("Exact error text or log excerpt",
                             r["placeholder_sections"])

        def test_bom_prefixed_report_still_parses(self):
            r = self._run(raw=b"\xef\xbb\xbf" + report_text().encode("utf-8"))
            self.assertEqual(r["result"], "PASS", r["problems"])

        def test_no_headings_at_all_is_structural(self):
            with self.assertRaises(GateError):
                self._run("just a paragraph about a bug, no headings\n")

        def test_missing_file_is_exit_2(self):
            code, out = self._main(["--report", str(self.dir / "nope.md")])
            self.assertEqual(code, 2)
            self.assertIn("ERROR", out)

        def test_missing_report_flag_is_exit_2(self):
            code, out = self._main([])
            self.assertEqual(code, 2)
            self.assertIn("--report", out)

        # ---- ledger ----

        def _records(self, ledger):
            return [json.loads(l) for l in
                    Path(ledger).read_text(encoding="utf-8").splitlines()
                    if l.strip()]

        def test_ledger_records_a_pass_with_the_report_hash(self):
            self.report.write_text(report_text(), encoding="utf-8")
            ledger = self.dir / "logs" / "gates.jsonl"
            argv = ["--report", str(self.report), "--milestone", "coupon-500",
                    "--ledger", str(ledger)]
            code, _ = self._main(argv)
            self.assertEqual(code, 0)
            rec = self._records(ledger)[-1]
            self.assertEqual(rec["gate"], "check_bugfix_intake.py")
            self.assertEqual(rec["verdict"], "PASS")
            self.assertEqual(rec["exit"], 0)
            self.assertEqual(rec["milestone"], "coupon-500")
            self.assertEqual(rec["argv"], argv)
            self.assertEqual(rec["inputs"][str(self.report)],
                             sha256_file(self.report))
            self.assertTrue(rec["ts"].endswith("Z"))

        def test_ledger_records_a_fail_and_an_error(self):
            ledger = self.dir / "gates.jsonl"
            self.report.write_text(report_text(observed="TBD"), encoding="utf-8")
            self.assertEqual(
                self._main(["--report", str(self.report),
                            "--ledger", str(ledger)])[0], 1)
            self.assertEqual(self._records(ledger)[-1]["verdict"], "FAIL")
            self.assertEqual(
                self._main(["--ledger", str(ledger)])[0], 2)
            self.assertEqual(self._records(ledger)[-1]["verdict"], "ERROR")

        # ---- the shipped template must not itself pass ----

        def test_the_shipped_template_fails_the_gate(self):
            """A template that passes is a bypass: copy it, run the gate, done."""
            template = (Path(__file__).resolve().parents[2]
                        / "bgpdd-bugfix" / "references"
                        / "bug-report-template.md")
            if not template.is_file():
                self.skipTest(f"template not found at {template}")
            args = build_parser().parse_args(["--report", str(template)])
            r = build_report(args)
            self.assertEqual(r["result"], "FAIL",
                             "the template must not satisfy its own gate")

    suite = unittest.defaultTestLoader.loadTestsFromTestCase(IntakeTests)
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
