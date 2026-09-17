#!/usr/bin/env python3
"""Router over skills/pipeline-tools/registry.json.

The script's own --help is the contract of record; this file answers
"which tool, and how do I call it?" and verifies that the registry and the
helps still agree. Pure stdlib.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PURPOSE = (
    "Routes an agent or the Orchestrator to the right pipeline-tools script, "
    "and verifies the registry against each script's own --help."
)

EPILOG = """
Reads:
  registry.json (default: the sibling of this script's own directory), whose
  `tools` array carries one object per script:
    {"name", "script", "description", "kind", "runner", "agents", "lanes",
     "reads", "writes", "reason" (optional, used by `for --agent`)}
  Each registered script's own `--help` output, which must carry, in order:
    a one-line purpose (<= 25 words, ending in a period, equal to the entry's
    `description`), the argparse usage and arguments, then an epilog whose
    headings each sit on their own line:
      Reads:
      Writes:             (optional; only a script that writes)
      Problem codes:      (gates only)
      JSON keys:          (whenever a machine report is printed, with or
                           without a --json flag)
      Exit codes:         (mandatory)
      Self-test:          (mandatory)
  Each registered script's source, for the `PurposeFirstParser` family block.

Problem codes:
  script_missing         registry entry names a file that does not exist
  unregistered_script    scripts/*.py file with no registry entry
  help_failed            the script's --help exited non-zero
  description_mismatch   registry description != the help's first line
  description_too_long   registry description is over 25 words
  help_missing_heading   a mandatory epilog heading is absent from --help
  help_too_long          --help output is over 700 words
  no_self_test_flag      --help never mentions --self-test
  duplicate_name         two entries share one name
  bad_enum               kind or runner outside the allowed set
  class_drift            this script's PurposeFirstParser block differs

JSON keys:
  list:   registry, count, tools[{name, description, kind, runner, agents, lanes}]
  show:   registry, entry, help, help_exit, help_error
  for:    registry, mode, agent|lane, phase, count, tools[], note
  verify: registry, root, entries, scripts_checked, problems[{code, name,
          detail, fix}], problem_codes, result

Exit codes:
  0  the command answered (a clean --verify included)
  1  --verify found at least one problem
  2  usage error, an unreadable or malformed registry, or an unknown name

Self-test:
  python tool_registry.py --self-test  (35 cases)
"""

KINDS = ("gate", "writer", "detector", "lint", "driver", "hook")
RUNNERS = ("orchestrator", "self-gating", "either")
EXCEPTED_SCRIPTS = ("test_check_coverage.py",)
MAX_DESCRIPTION_WORDS = 25
MAX_HELP_WORDS = 700
MANDATORY_HEADINGS = ("Exit codes:", "Self-test:")
GATE_HEADINGS = ("Problem codes:",)
PARSER_CLASS_MARKER = "class PurposeFirstParser("

RUNNER_REASON = {
    "self-gating": (
        "self-gating: the producing agent runs it on its OWN output before handing "
        "anything back (pipeline-tools/SKILL.md carve-out)."
    ),
    "either": (
        "self-gating: the producing agent runs it on its OWN output before handing "
        "anything back; the Orchestrator also runs it "
        "(pipeline-tools/SKILL.md carve-out)."
    ),
    "orchestrator": "Orchestrator-run: the reader of an agent's output is never that agent.",
}


def default_registry_path():
    return Path(__file__).resolve().parent.parent / "registry.json"


class RegistryError(Exception):
    pass


def load_registry(path):
    path = Path(path)
    if not path.is_file():
        raise RegistryError("registry not found: %s" % path)
    try:
        with open(path, "r", encoding="utf-8-sig") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as exc:
        raise RegistryError("registry unreadable: %s: %s" % (path, exc))
    if not isinstance(data, dict) or not isinstance(data.get("tools"), list):
        raise RegistryError("registry has no `tools` array: %s" % path)
    return data, path.resolve()


def run_help(script_path):
    """Return (exit_code, text, error). text is stdout, or stderr when stdout is empty."""
    try:
        proc = subprocess.run(
            [sys.executable, str(script_path), "--help"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
        )
    except Exception as exc:  # noqa: BLE001 - a launch failure is a help_failed
        return 127, "", str(exc)
    text = proc.stdout or proc.stderr or ""
    return proc.returncode, text, ""


def first_help_line(text):
    for line in text.splitlines():
        if line.strip():
            return line.strip()
    return ""


def has_heading(text, heading):
    return any(line.strip() == heading for line in text.splitlines())


def word_count(text):
    return len(text.split())


def purpose_parser_block(source):
    """The `PurposeFirstParser` class block, or None when there is none.

    One file each, no shared module -- so drift is what to test, exactly as
    check_ledger.py guards the chain helper it shares by copy. The block runs
    from the class statement to the blank-line pair that ends it; a copy that
    is not byte-identical prints a --help the registry cannot compare.
    """
    # Only a definition at column 0 counts: the marker also appears inside
    # this file's own self-test fixture string, which defines nothing.
    if source.startswith(PARSER_CLASS_MARKER):
        start = 0
    else:
        found = source.find("\n" + PARSER_CLASS_MARKER)
        if found == -1:
            return None
        start = found + 1
    end = source.find("\n\n\n", start)
    if end == -1:
        return None
    return source[start:end + 1]


# ---------------------------------------------------------------- verify


def verify_registry(registry_path):
    data, resolved = load_registry(registry_path)
    root = resolved.parent
    tools = data["tools"]
    problems = []

    def add(code, name, detail, fix):
        problems.append({"code": code, "name": name, "detail": detail, "fix": fix})

    seen = {}
    for entry in tools:
        name = entry.get("name", "<unnamed>")
        if name in seen:
            add(
                "duplicate_name",
                name,
                "two entries share the name %r" % name,
                "give one entry a distinct `name`, or delete the duplicate entry",
            )
        seen[name] = entry

        kind = entry.get("kind")
        if kind not in KINDS:
            add(
                "bad_enum",
                name,
                "kind %r is not one of %s" % (kind, ", ".join(KINDS)),
                "set `kind` to one of: %s" % ", ".join(KINDS),
            )
        runner = entry.get("runner")
        if runner not in RUNNERS:
            add(
                "bad_enum",
                name,
                "runner %r is not one of %s" % (runner, ", ".join(RUNNERS)),
                "set `runner` to one of: %s" % ", ".join(RUNNERS),
            )

        description = entry.get("description", "")
        if word_count(description) > MAX_DESCRIPTION_WORDS:
            add(
                "description_too_long",
                name,
                "description is %d words (max %d)"
                % (word_count(description), MAX_DESCRIPTION_WORDS),
                "shorten the registry `description` (and the script's --help first line to match)",
            )

        script_rel = entry.get("script", "")
        script_path = root / script_rel
        if not script_path.is_file():
            add(
                "script_missing",
                name,
                "entry names %s, which does not exist" % script_rel,
                "create the script, fix `script`, or delete the entry",
            )
            continue

        code, text, err = run_help(script_path)
        if code != 0 or not text.strip():
            add(
                "help_failed",
                name,
                "`%s --help` exited %d%s" % (script_rel, code, (": " + err) if err else ""),
                "make --help exit 0 and print the pinned help contract",
            )
            continue

        actual_first = first_help_line(text)
        if actual_first != description:
            add(
                "description_mismatch",
                name,
                "help first line is %r; registry description is %r"
                % (actual_first, description),
                "make the script's --help print the registry description as its FIRST line",
            )
        for heading in MANDATORY_HEADINGS + (GATE_HEADINGS if kind == "gate" else ()):
            if not has_heading(text, heading):
                add(
                    "help_missing_heading",
                    name,
                    "--help carries no %r heading on its own line" % heading,
                    "add a %r section to the script's --help epilog" % heading,
                )
        if word_count(text) > MAX_HELP_WORDS:
            add(
                "help_too_long",
                name,
                "--help is %d words (max %d)" % (word_count(text), MAX_HELP_WORDS),
                "cut the --help epilog to %d words or fewer" % MAX_HELP_WORDS,
            )
        if "--self-test" not in text:
            add(
                "no_self_test_flag",
                name,
                "--help never mentions --self-test",
                "add a --self-test flag and name it under the `Self-test:` heading",
            )

    # class_drift: the PurposeFirstParser block is copied into every script
    # that has one (no shared module), so the only thing that can be checked
    # is that the copies agree. The largest group is taken as canonical.
    blocks = {}
    for entry in tools:
        script_path = root / entry.get("script", "")
        if not script_path.is_file():
            continue
        try:
            source = script_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        block = purpose_parser_block(source)
        if block is not None:
            blocks.setdefault(block, []).append(
                entry.get("name", script_path.stem))
    if len(blocks) > 1:
        groups = sorted(blocks.values(), key=lambda g: (-len(g), g[0]))
        canonical = groups[0][0]
        for group in groups[1:]:
            for name in group:
                add(
                    "class_drift",
                    name,
                    "its `PurposeFirstParser` block is not byte-identical to "
                    "%s's, which %d script(s) share"
                    % (canonical, len(groups[0])),
                    "copy the `PurposeFirstParser` class verbatim from %s"
                    % canonical,
                )

    registered = set()
    for entry in tools:
        script_rel = entry.get("script", "")
        if script_rel:
            registered.add(Path(script_rel).name)
    scripts_dir = root / "scripts"
    if scripts_dir.is_dir():
        for path in sorted(scripts_dir.glob("*.py")):
            if path.name in EXCEPTED_SCRIPTS or path.name in registered:
                continue
            add(
                "unregistered_script",
                path.stem,
                "scripts/%s has no registry entry" % path.name,
                "add an entry for it to registry.json, or except it deliberately",
            )

    report = {
        "registry": str(resolved),
        "root": str(root),
        "entries": len(tools),
        "scripts_checked": len(
            [e for e in tools if (root / e.get("script", "")).is_file()]
        ),
        "problems": problems,
        "problem_codes": sorted({p["code"] for p in problems}),
        "result": "PASS" if not problems else "FAIL",
    }
    return report


def render_verify(report):
    lines = ["registry: %s" % report["registry"],
             "entries: %d  scripts present: %d" % (report["entries"], report["scripts_checked"])]
    if not report["problems"]:
        lines.append("result: PASS - every entry resolves and every help matches.")
        return "\n".join(lines)
    lines.append("result: FAIL - %d problem(s)" % len(report["problems"]))
    lines.append("")
    for problem in report["problems"]:
        lines.append("%s  %s" % (problem["code"], problem["name"]))
        lines.append("    %s" % problem["detail"])
        lines.append("    fix: %s" % problem["fix"])
    lines.append("")
    counts = {}
    for problem in report["problems"]:
        counts[problem["code"]] = counts.get(problem["code"], 0) + 1
    lines.append("by code: " + ", ".join("%s=%d" % kv for kv in sorted(counts.items())))
    return "\n".join(lines)


# ---------------------------------------------------------------- commands


def cmd_list(registry_path, kind=None, runner=None, as_json=False):
    data, resolved = load_registry(registry_path)
    tools = data["tools"]
    if kind:
        tools = [t for t in tools if t.get("kind") == kind]
    if runner:
        tools = [t for t in tools if t.get("runner") == runner]
    tools = sorted(tools, key=lambda t: t.get("name", ""))
    if as_json:
        payload = {
            "registry": str(resolved),
            "count": len(tools),
            "tools": [
                {
                    "name": t.get("name"),
                    "description": t.get("description"),
                    "kind": t.get("kind"),
                    "runner": t.get("runner"),
                    "agents": t.get("agents", []),
                    "lanes": t.get("lanes", []),
                }
                for t in tools
            ],
        }
        return 0, json.dumps(payload, indent=2)
    if not tools:
        return 0, "no tools match that filter."
    width = max(len(t.get("name", "")) for t in tools)
    lines = ["%-*s  %s" % (width, t.get("name", ""), t.get("description", "")) for t in tools]
    return 0, "\n".join(lines)


def render_entry(entry):
    lines = []
    for key in ("name", "script", "kind", "runner", "description"):
        lines.append("%-12s %s" % (key + ":", entry.get(key, "")))
    for key in ("agents", "lanes", "reads", "writes"):
        value = entry.get(key, [])
        lines.append("%-12s %s" % (key + ":", ", ".join(str(v) for v in value) if value else "(none)"))
    if entry.get("reason"):
        lines.append("%-12s %s" % ("reason:", entry["reason"]))
    return "\n".join(lines)


def cmd_show(registry_path, name, as_json=False):
    data, resolved = load_registry(registry_path)
    root = resolved.parent
    match = None
    for entry in data["tools"]:
        if entry.get("name") == name or entry.get("script", "").endswith("/" + name):
            match = entry
            break
    if match is None:
        raise RegistryError(
            "unknown tool %r - run `tool_registry.py list` for the registered names" % name
        )
    script_path = root / match.get("script", "")
    if script_path.is_file():
        help_exit, help_text, help_error = run_help(script_path)
    else:
        help_exit, help_text, help_error = 2, "", "script not found: %s" % script_path
    if as_json:
        payload = {
            "registry": str(resolved),
            "entry": match,
            "help": help_text,
            "help_exit": help_exit,
            "help_error": help_error,
        }
        return 0, json.dumps(payload, indent=2)
    out = [render_entry(match), "", "--- %s --help (the contract of record) ---" % match.get("script", ""), ""]
    out.append(help_text.rstrip() if help_text.strip() else "(no help: %s)" % help_error)
    return 0, "\n".join(out)


def _lane_matches(lanes, lane, phase):
    for item in lanes:
        if isinstance(item, dict):
            if item.get("lane") != lane:
                continue
            if phase is None or str(item.get("phase")) == str(phase):
                return True
        elif item == lane:
            if phase is None:
                return True
    return False


def cmd_for(registry_path, agent=None, lane=None, phase=None, as_json=False):
    data, resolved = load_registry(registry_path)
    tools = data["tools"]
    note = ""
    if agent:
        matched = [t for t in tools if agent in (t.get("agents") or [])]
        mode = "agent"
        subject = agent
        if not matched:
            note = (
                "no tool is carved out for %r - everything else in this registry is "
                "Orchestrator-run (pipeline-tools/SKILL.md carve-out)." % agent
            )
    else:
        matched = [t for t in tools if _lane_matches(t.get("lanes") or [], lane, phase)]
        mode = "lane"
        subject = lane
        if not matched:
            note = (
                "no tool declares a lane yet: `lanes` is empty for every entry today. "
                "Step B of the pipeline-tools split fills it from the pipeline SKILL.md files."
            )
    matched = sorted(matched, key=lambda t: t.get("name", ""))
    if as_json:
        payload = {
            "registry": str(resolved),
            "mode": mode,
            mode: subject,
            "phase": phase,
            "count": len(matched),
            "tools": matched,
            "note": note,
        }
        return 0, json.dumps(payload, indent=2)
    lines = []
    for entry in matched:
        lines.append("%s  %s" % (entry.get("name"), entry.get("description")))
        reason = entry.get("reason") or RUNNER_REASON.get(entry.get("runner"), "")
        if mode == "agent" and reason:
            lines.append("    reason: %s" % reason)
    if note:
        if lines:
            lines.append("")
        lines.append(note)
    return 0, "\n".join(lines)


# ---------------------------------------------------------------- self-test

COMPLIANT_TEMPLATE = '''import sys
HELP = """%(purpose)s

usage: %(name)s [-h] [--self-test]

options:
  -h, --help   show this help message and exit
  --self-test  run the built-in test suite and exit

Reads:
  nothing

Problem codes:
  demo_problem  a demonstration problem code

Exit codes:
  0  ok
  1  a problem
  2  usage error

Self-test:
  python %(name)s --self-test  (1 case)
"""
if "--help" in sys.argv or "-h" in sys.argv:
    print(HELP)
    raise SystemExit(0)
raise SystemExit(0)
'''


def _fixture(tmp, tools, scripts):
    """Build a registry root under tmp. `scripts` maps filename -> source text."""
    root = Path(tmp)
    (root / "scripts").mkdir(parents=True, exist_ok=True)
    for filename, source in scripts.items():
        (root / "scripts" / filename).write_text(source, encoding="utf-8")
    registry = root / "registry.json"
    registry.write_text(json.dumps({"schema": 1, "tools": tools}, indent=2), encoding="utf-8")
    return registry


PARSER_BLOCK = '''class PurposeFirstParser(argparse.ArgumentParser):
    """A fixture stand-in for the family's real block."""

    def format_help(self):
        return super().format_help()
'''


def _compliant(name, purpose):
    return COMPLIANT_TEMPLATE % {"purpose": purpose, "name": name}


def _compliant_with_parser(name, purpose, block=PARSER_BLOCK):
    """A compliant script that also carries a PurposeFirstParser copy."""
    return "import argparse\n\n\n" + block + "\n\n" + _compliant(name, purpose)


def _entry(**kw):
    base = {
        "name": "demo",
        "script": "scripts/demo.py",
        "description": "Does one demonstration thing for the caller.",
        "kind": "gate",
        "runner": "orchestrator",
        "agents": [],
        "lanes": [],
        "reads": [],
        "writes": [],
    }
    base.update(kw)
    return base


def self_test():
    cases = []

    def check(label, condition, detail=""):
        cases.append((label, bool(condition), detail))

    desc = "Does one demonstration thing for the caller."
    tmp = tempfile.mkdtemp(prefix="tool_registry_selftest_")
    try:
        # 1. clean pass
        d = Path(tmp) / "clean"
        reg = _fixture(d, [_entry()], {"demo.py": _compliant("demo.py", desc)})
        report = verify_registry(reg)
        check("clean fixture passes verify", report["result"] == "PASS", str(report["problems"]))
        check("clean fixture counts its script", report["scripts_checked"] == 1)

        # 2. script_missing
        d = Path(tmp) / "missing"
        reg = _fixture(d, [_entry()], {})
        report = verify_registry(reg)
        check("script_missing fires", report["problem_codes"] == ["script_missing"], str(report["problem_codes"]))

        # 3. unregistered_script
        d = Path(tmp) / "unregistered"
        reg = _fixture(
            d,
            [_entry()],
            {"demo.py": _compliant("demo.py", desc), "stray.py": "print(1)\n"},
        )
        report = verify_registry(reg)
        check("unregistered_script fires", "unregistered_script" in report["problem_codes"])

        # 4. test_check_coverage.py is excepted
        d = Path(tmp) / "excepted"
        reg = _fixture(
            d,
            [_entry()],
            {"demo.py": _compliant("demo.py", desc), "test_check_coverage.py": "print(1)\n"},
        )
        report = verify_registry(reg)
        check("test_check_coverage.py excepted", report["result"] == "PASS", str(report["problems"]))

        # 5. help_failed
        d = Path(tmp) / "helpfail"
        reg = _fixture(d, [_entry()], {"demo.py": "import sys\nsys.exit(3)\n"})
        report = verify_registry(reg)
        check("help_failed fires", report["problem_codes"] == ["help_failed"], str(report["problem_codes"]))

        # 6. description_mismatch
        d = Path(tmp) / "mismatch"
        reg = _fixture(
            d,
            [_entry(description="Does something else entirely for the caller.")],
            {"demo.py": _compliant("demo.py", desc)},
        )
        report = verify_registry(reg)
        check("description_mismatch fires", report["problem_codes"] == ["description_mismatch"], str(report["problem_codes"]))

        # 7. description_too_long
        long_desc = " ".join(["word"] * 26) + "."
        d = Path(tmp) / "toolong"
        reg = _fixture(
            d,
            [_entry(description=long_desc)],
            {"demo.py": _compliant("demo.py", long_desc)},
        )
        report = verify_registry(reg)
        check("description_too_long fires", "description_too_long" in report["problem_codes"])
        check("a 26-word description is the only length problem",
              "help_too_long" not in report["problem_codes"])

        # 8. help_missing_heading (Exit codes:)
        d = Path(tmp) / "noexit"
        source = _compliant("demo.py", desc).replace("Exit codes:\n", "Exit statuses:\n")
        reg = _fixture(d, [_entry()], {"demo.py": source})
        report = verify_registry(reg)
        check("help_missing_heading fires for Exit codes:", "help_missing_heading" in report["problem_codes"])

        # 9. help_missing_heading (Problem codes: on a gate)
        d = Path(tmp) / "noproblem"
        source = _compliant("demo.py", desc).replace("Problem codes:\n", "Codes:\n")
        reg = _fixture(d, [_entry(kind="gate")], {"demo.py": source})
        report = verify_registry(reg)
        check("Problem codes: required for a gate", "help_missing_heading" in report["problem_codes"])

        # 10. the same help passes for a non-gate kind
        d = Path(tmp) / "noproblem_writer"
        reg = _fixture(d, [_entry(kind="writer")], {"demo.py": source})
        report = verify_registry(reg)
        check("Problem codes: not required for a writer", report["result"] == "PASS", str(report["problems"]))

        # 11. help_too_long
        d = Path(tmp) / "helplong"
        padded = _compliant("demo.py", desc).replace(
            "Reads:\n  nothing", "Reads:\n  " + " ".join(["filler"] * 750)
        )
        reg = _fixture(d, [_entry()], {"demo.py": padded})
        report = verify_registry(reg)
        check("help_too_long fires", "help_too_long" in report["problem_codes"])

        # 12. no_self_test_flag
        d = Path(tmp) / "noselftest"
        stripped = _compliant("demo.py", desc).replace("--self-test", "--selfcheck")
        reg = _fixture(d, [_entry()], {"demo.py": stripped})
        report = verify_registry(reg)
        check("no_self_test_flag fires", "no_self_test_flag" in report["problem_codes"])

        # 13. duplicate_name
        d = Path(tmp) / "dupe"
        reg = _fixture(
            d,
            [_entry(), _entry(script="scripts/demo2.py")],
            {"demo.py": _compliant("demo.py", desc), "demo2.py": _compliant("demo2.py", desc)},
        )
        report = verify_registry(reg)
        check("duplicate_name fires", "duplicate_name" in report["problem_codes"])

        # 14/15. bad_enum
        d = Path(tmp) / "badkind"
        reg = _fixture(d, [_entry(kind="checker")], {"demo.py": _compliant("demo.py", desc)})
        report = verify_registry(reg)
        check("bad_enum fires on kind", "bad_enum" in report["problem_codes"])
        d = Path(tmp) / "badrunner"
        reg = _fixture(d, [_entry(runner="anyone")], {"demo.py": _compliant("demo.py", desc)})
        report = verify_registry(reg)
        check("bad_enum fires on runner", "bad_enum" in report["problem_codes"])

        # 16a/16b. class_drift, both ways. The block is copied per file, so
        # the only checkable property is that the copies agree byte for byte.
        two = [_entry(name="one", script="scripts/demo.py"),
               _entry(name="two", script="scripts/demo2.py")]
        d = Path(tmp) / "classsame"
        reg = _fixture(
            d, two,
            {"demo.py": _compliant_with_parser("demo.py", desc),
             "demo2.py": _compliant_with_parser("demo2.py", desc)},
        )
        report = verify_registry(reg)
        check("identical PurposeFirstParser copies pass",
              report["result"] == "PASS", str(report["problems"]))

        d = Path(tmp) / "classdrift"
        drifted = PARSER_BLOCK.replace("A fixture stand-in",
                                       "A DRIFTED fixture stand-in")
        reg = _fixture(
            d, two,
            {"demo.py": _compliant_with_parser("demo.py", desc),
             "demo2.py": _compliant_with_parser("demo2.py", desc,
                                                block=drifted)},
        )
        report = verify_registry(reg)
        check("class_drift fires on a diverged copy",
              report["problem_codes"] == ["class_drift"],
              str(report["problem_codes"]))
        check("class_drift names the drifted entry, not the canonical one",
              [p["name"] for p in report["problems"]] == ["two"],
              str([p["name"] for p in report["problems"]]))

        # 17. verify --json lists every problem
        d = Path(tmp) / "jsonverify"
        reg = _fixture(
            d,
            [_entry(kind="checker", description="Does something else entirely for the caller.")],
            {"demo.py": _compliant("demo.py", desc), "stray.py": "print(1)\n"},
        )
        report = verify_registry(reg)
        payload = json.loads(json.dumps(report))
        check(
            "verify --json carries every problem",
            set(payload["problem_codes"]) == {"bad_enum", "description_mismatch", "unregistered_script"},
            str(payload["problem_codes"]),
        )
        check("every problem names its entry and a fix",
              all(p.get("name") and p.get("fix") for p in payload["problems"]))

        # 17-19. for --agent honours `agents`
        d = Path(tmp) / "agents"
        reg = _fixture(
            d,
            [
                _entry(name="self_gated", script="scripts/demo.py", runner="either",
                       agents=["cipher", "vera"], reason="carve-out reason here"),
                _entry(name="orchestrated", script="scripts/demo2.py"),
            ],
            {"demo.py": _compliant("demo.py", desc), "demo2.py": _compliant("demo2.py", desc)},
        )
        code, out = cmd_for(reg, agent="cipher")
        check("for --agent returns the carved-out tool", code == 0 and "self_gated" in out)
        check("for --agent excludes Orchestrator-only tools", "orchestrated" not in out)
        check("for --agent prints the carve-out reason", "carve-out reason here" in out)
        code, out = cmd_for(reg, agent="mason")
        check("for --agent with no carve-out says so", code == 0 and "no tool is carved out" in out)
        code, out = cmd_for(reg, agent="cipher", as_json=True)
        check("for --agent --json is parseable", json.loads(out)["count"] == 1)

        # 20. for --lane says step B fills it
        code, out = cmd_for(reg, lane="bgpdd-build")
        check("for --lane reports the empty schema", code == 0 and "Step B" in out)
        code, out = cmd_for(reg, lane="bgpdd-build", phase="2", as_json=True)
        check("for --lane --phase is accepted", json.loads(out)["count"] == 0)

        # 21. show concatenates the entry and the help
        code, out = cmd_show(reg, "self_gated")
        check(
            "show prints the entry then the verbatim help",
            code == 0
            and "self_gated" in out
            and "contract of record" in out
            and desc in out
            and "Exit codes:" in out,
        )
        code, out = cmd_show(reg, "self_gated", as_json=True)
        payload = json.loads(out)
        check("show --json carries entry and help", payload["entry"]["name"] == "self_gated" and "Exit codes:" in payload["help"])
        try:
            cmd_show(reg, "nope")
            check("show on an unknown name raises", False)
        except RegistryError:
            check("show on an unknown name raises", True)

        # 22. list filters
        code, out = cmd_list(reg, kind="gate")
        check("list --kind filters", code == 0 and "self_gated" in out)
        code, out = cmd_list(reg, runner="either", as_json=True)
        check("list --runner filters", json.loads(out)["count"] == 1)

        # 23. a malformed registry is a usage error
        bad = Path(tmp) / "bad.json"
        bad.write_text("{not json", encoding="utf-8")
        try:
            load_registry(bad)
            check("a malformed registry raises", False)
        except RegistryError:
            check("a malformed registry raises", True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    failed = [c for c in cases if not c[1]]
    for label, ok, detail in cases:
        if not ok:
            print("FAIL %s%s" % (label, (" - " + detail) if detail else ""))
    print("%d/%d cases passed" % (len(cases) - len(failed), len(cases)))
    return 1 if failed else 0


# ---------------------------------------------------------------- CLI


class _Parser(argparse.ArgumentParser):
    def format_help(self):
        return PURPOSE + "\n\n" + super().format_help()


def build_parser():
    parser = _Parser(
        prog="tool_registry.py",
        description=argparse.SUPPRESS,
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--registry", default=None, help="path to registry.json (default: ../registry.json)")
    parser.add_argument("--json", action="store_true", help="print the machine report")
    parser.add_argument("--verify", action="store_true", help="check the registry against every script's --help")
    parser.add_argument("--self-test", action="store_true", dest="self_test", help="run the built-in test suite and exit")
    sub = parser.add_subparsers(dest="command")

    suppress = argparse.SUPPRESS

    p_list = sub.add_parser("list", help="name + description, one line each")
    p_list.add_argument("--kind", choices=KINDS)
    p_list.add_argument("--runner", choices=RUNNERS)
    p_list.add_argument("--registry", default=suppress)
    p_list.add_argument("--json", action="store_true", default=suppress)

    p_show = sub.add_parser("show", help="the entry, then the script's --help verbatim")
    p_show.add_argument("name")
    p_show.add_argument("--registry", default=suppress)
    p_show.add_argument("--json", action="store_true", default=suppress)

    p_for = sub.add_parser("for", help="tools for an agent (carve-out) or a lane")
    p_for.add_argument("--agent")
    p_for.add_argument("--lane")
    p_for.add_argument("--phase")
    p_for.add_argument("--registry", default=suppress)
    p_for.add_argument("--json", action="store_true", default=suppress)
    return parser


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--self-test" in argv:
        return self_test()

    parser = build_parser()
    args = parser.parse_args(argv)
    registry = args.registry or os.environ.get("PIPELINE_TOOLS_REGISTRY") or default_registry_path()

    try:
        if args.verify:
            report = verify_registry(registry)
            print(json.dumps(report, indent=2) if args.json else render_verify(report))
            return 1 if report["problems"] else 0
        if args.command == "list":
            code, out = cmd_list(registry, args.kind, args.runner, args.json)
        elif args.command == "show":
            code, out = cmd_show(registry, args.name, args.json)
        elif args.command == "for":
            if bool(args.agent) == bool(args.lane):
                print("usage error: `for` takes exactly one of --agent or --lane", file=sys.stderr)
                return 2
            if args.phase and not args.lane:
                print("usage error: --phase belongs with --lane", file=sys.stderr)
                return 2
            code, out = cmd_for(registry, args.agent, args.lane, args.phase, args.json)
        else:
            parser.print_help()
            return 2
    except RegistryError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 2
    print(out)
    return code


if __name__ == "__main__":
    sys.exit(main())
