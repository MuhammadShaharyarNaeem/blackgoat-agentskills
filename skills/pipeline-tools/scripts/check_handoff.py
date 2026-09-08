#!/usr/bin/env python3
"""Mechanical gate for the agent -> Orchestrator `<handoff>` interface.

`base-persona.md` § Output Format defines the handoff block, and six personas
refine its required elements in an inline "Base Persona Override". Until this
script existed nothing parsed any of it: a handoff missing `<changed_files>`,
naming a path that was never written, or claiming PASS beside a NOT VERIFIED
marker read exactly like a good one, and the Orchestrator acted on it.

CLAUDE.md convention #9: the restraint this asks for lands at the moment the
Orchestrator most wants to proceed (the phase is "done", the agent said
COMPLETE), so it is a command with an exit code, not a paragraph.

ADVISORY HANDOFFS (`--advisory`)
--------------------------------
Two sanctioned steps ask an agent for a RECOMMENDATION and no artifact:
Forge's propose handoff in `bgpdd-learn` (it proposes edits and waits for
approval, so nothing is written yet) and Aria's Mode 2 blast-radius advisory
in `bgpdd-build`. Both failed this gate exit 1 in every tag form, so the
Orchestrator's mandatory validation was contradicted by the pipelines twice
per epic. `--advisory` makes `<artifact>` and `<changed_skills>` OPTIONAL for
that one call and records `"advisory": true` in the ledger line, so waiving
the artifact is a written act rather than a skipped gate.

Nothing else relaxes: `<status>`, `<blockers>`, the path checks on whatever IS
declared, the honesty contradictions and the status enum all still apply, and
`<changed_files>` stays required for the personas that carry it -- an agent
that wrote code has an artifact whether or not the brief asked for one.

`--advisory` is the CALLER's declaration about the brief it wrote, so it
belongs in the pipeline step, never in the agent's output: an agent that could
set it could waive its own artifact.

STATUS IS THE DELIVERY STATE, NOT THE VERDICT
---------------------------------------------
`<status>` is COMPLETE / PARTIAL / BLOCKED: whether the agent finished the
work it was briefed for. A verification VERDICT (PASS / FAIL / BLOCKED) is a
different claim and belongs in the body, where the durable report the verdict
is about can be cited. `BLOCKED` is the one token both vocabularies share, and
it means the same thing in each.

Usage:
    python check_handoff.py --handoff <file> --persona <name> --repo <dir> \
        [--since <ref>] [--advisory] [--fix-round] [--require consumers] \
        [--milestone "<title>"] [--ledger <path>]
    ... | python check_handoff.py --persona mason --repo .      # stdin
    python check_handoff.py --self-test

`--since <ref>` is OPTIONAL to this CLI and REQUIRED by the pipelines: it is
the only term here that git can contradict (without it `<changed_files>` need
merely exist; with it, a file the agent never touched is rejected). Every
pipeline handoff step passes `--since` and `--ledger`; a call without them
checks shape only and says nothing about what was actually written.

Exit 0 PASS, 1 FAIL (findings against a readable handoff), 2 ERROR (usage,
unreadable input, unusable repo). Pure standard library.
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

# --------------------------------------------------------------------------
# The per-persona required-element table.
#
# Derived from `skills/agent-squad/base-persona.md` § Output Format (the
# default: <status>, <artifact>, <blockers>) plus each `agents/<name>.md`
# "Base Persona Override" block. It lives HERE, in the gate, on purpose: a
# table the gate reads from the persona files at runtime would be a gate whose
# verdict moves whenever a persona is reworded. When a persona's override
# changes, this table is edited in the same change -- and the mismatch is what
# `agent-audit`'s interface-alignment heuristic is for.
#
# agents/blackgoat.md is deliberately absent: it is the human author's
# psychological profile, not a delegatable persona (CLAUDE.md convention #7).
# --------------------------------------------------------------------------
DEFAULT_REQUIRED = ("status", "artifact", "blockers")

PERSONA_ELEMENTS = {
    # Builders (agents/mason.md, agents/max.md): <changed_files> INSTEAD of
    # <artifact>.
    "mason": ("status", "changed_files", "blockers"),
    "max": ("status", "changed_files", "blockers"),
    # Hybrid write boundaries (agents/dep.md, agents/quinn.md,
    # agents/nova.md): both elements, a dual handoff.
    "dep": ("status", "changed_files", "artifact", "blockers"),
    "quinn": ("status", "changed_files", "artifact", "blockers"),
    "nova": ("status", "changed_files", "artifact", "blockers"),
    # Meta (agents/forge.md): <changed_skills>.
    "forge": ("status", "changed_skills", "blockers"),
    # Everyone else reports <artifact> per base-persona unchanged.
    "alex": DEFAULT_REQUIRED,
    "aria": DEFAULT_REQUIRED,
    "cipher": DEFAULT_REQUIRED,
    "echo": DEFAULT_REQUIRED,
    "iris": DEFAULT_REQUIRED,
    "luna": DEFAULT_REQUIRED,
    "rex": DEFAULT_REQUIRED,
    "scout": DEFAULT_REQUIRED,
    "vera": DEFAULT_REQUIRED,
}

# `<consumers>` is standing-but-optional for exactly these two: their override
# says "when the brief asks for it". Any persona can be held to it with
# `--require consumers`; for the others the gate says so in a warning, because
# requiring an element no persona contract mentions is more likely a caller
# mistake than a real bar.
CONSUMERS_PERSONAS = ("mason", "nova")

# Elements whose values are file paths that must exist under --repo.
PATH_ELEMENTS = ("changed_files", "artifact", "changed_skills")

# base-persona's status enum. COMPLETE is the template value; PARTIAL is
# mandated by § Incremental Persistence ("report unfinished sections and return
# PARTIAL, never COMPLETE"); BLOCKED by § Evidence Integrity ("An honest
# BLOCKED costs one round-trip"). Nothing else is sanctioned anywhere in the
# plugin, so nothing else passes. See STATUS IS THE DELIVERY STATE above: a
# PASS/FAIL verdict is a different claim and lives in the body.
STATUSES = ("COMPLETE", "PARTIAL", "BLOCKED")

# Elements `--advisory` demotes from required to optional: the two "here is a
# recommendation, nothing is written yet" handoffs. `<changed_files>` is
# deliberately NOT here -- see ADVISORY HANDOFFS above.
ADVISORY_OPTIONAL_ELEMENTS = ("artifact", "changed_skills")

KNOWN_ELEMENTS = ("status", "artifact", "changed_files", "changed_skills",
                  "blockers", "consumers", "fix_verification")

HANDOFF_RE = re.compile(r"<handoff\s*>(.*?)</handoff\s*>", re.S | re.I)
FENCE_RE = re.compile(r"^[ \t]*(```|~~~).*?^[ \t]*\1[ \t]*$",
                      re.S | re.M)
TAG_RE = re.compile(r"</?([A-Za-z_][\w-]*)\s*>")
# `path::symbol`, split on the LAST `::` so a Windows drive letter or a
# namespace-qualified path cannot be mistaken for the separator.
CONSUMERS_LINE_RE = re.compile(r"^(?P<path>\S.*?)::(?P<symbol>[^\s:/\\]+)$")
# Uppercase-only, standalone. "1 passed, 0 failed" is lowercase and is the
# sanctioned way to report a partial result beside a NOT VERIFIED label; an
# unqualified uppercase verdict token is not.
PASS_CLAIM_RE = re.compile(r"(?<![A-Za-z])(PASS|PASSED|GREEN)(?![A-Za-z])")
MARKER_RE = re.compile(r"(?<![A-Za-z])(NOT VERIFIED|BLOCKED)(?![A-Za-z])")
NO_BLOCKER_VALUES = ("none", "n/a", "na", "-", "nil", "")


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

    `extra` merges into the record BEFORE `prev`/`self` are computed, so the
    chain covers it: `--advisory` records `"advisory": true`, which is how a
    waived artifact stays attributable after the run.
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


def strip_fenced(text):
    """Blank out fenced code blocks, preserving line count.

    A SKILL.md, a persona file or an agent's own prose routinely SHOWS a
    handoff template inside a fence. Feeding such a file to this gate must not
    read the illustration as the report -- the adversarial case is a real
    handoff that is BLOCKED, with a fenced COMPLETE example pasted beneath it.
    """
    def blank(match):
        return "\n" * match.group(0).count("\n")
    return FENCE_RE.sub(blank, text)


def extract_handoff(text):
    """Return (block_body, warnings). block_body is None when there is none."""
    warnings = []
    stripped = strip_fenced(text)
    blocks = HANDOFF_RE.findall(stripped)
    if not blocks:
        if re.search(r"<handoff\s*>", stripped, re.I):
            warnings.append("an opening <handoff> tag is present but never closed")
        return None, warnings
    if len(blocks) > 1:
        warnings.append(
            f"{len(blocks)} unfenced <handoff> blocks; validating the LAST one "
            "(the final output is what the Orchestrator acts on)")
    return blocks[-1], warnings


def parse_elements(block):
    """All `<tag>value</tag>` pairs in the block, as {tag: [values]}."""
    found = {}
    for name in KNOWN_ELEMENTS:
        pattern = re.compile(rf"<{name}\s*>(.*?)</{name}\s*>", re.S | re.I)
        values = [m.group(1) for m in pattern.finditer(block)]
        if values:
            found[name] = values
    return found


def unknown_tags(block):
    """Tag names in the block that no element contract mentions."""
    seen = []
    for name in TAG_RE.findall(block):
        low = name.lower()
        if low not in KNOWN_ELEMENTS and low != "handoff" and low not in seen:
            seen.append(low)
    return seen


def split_paths(values):
    """Flatten element values into individual path strings.

    Personas write `<changed_files>a, b</changed_files>` (mason, max, nova) and
    one-per-line lists interchangeably, so both split. Backticks, list bullets
    and surrounding whitespace are stripped; empty fragments drop out.
    """
    out = []
    for value in values:
        for chunk in re.split(r"[,\n]", value):
            item = chunk.strip().strip("`").strip()
            item = re.sub(r"^[-*+]\s+", "", item).strip()
            if item:
                out.append(item)
    return out


def normalize_path(raw):
    """A handoff path as git would spell it: posix separators, no './'."""
    p = raw.replace("\\", "/").strip()
    while p.startswith("./"):
        p = p[2:]
    return p


def path_status(repo, raw):
    """('ok'|'missing'|'outside', normalized) for one handoff path."""
    rel = normalize_path(raw)
    candidate = Path(rel)
    if candidate.is_absolute():
        resolved = candidate
    else:
        resolved = Path(repo) / rel
    try:
        resolved_abs = os.path.normpath(os.path.abspath(str(resolved)))
        repo_abs = os.path.normpath(os.path.abspath(str(repo)))
        if os.path.commonpath([resolved_abs, repo_abs]) != repo_abs:
            return "outside", rel
    except ValueError:
        # Different drives on Windows -- definitionally outside the repo.
        return "outside", rel
    if not os.path.exists(resolved_abs):
        return "missing", rel
    return "ok", rel


def git_changed_since(repo, ref):
    """Paths git reports as changed-or-committed since `ref`, plus untracked.

    `git diff --name-only <ref>` spans ref..working-tree, so a file committed
    since ref and a file edited but not yet committed both appear. Untracked
    files are added separately because diff never sees them and a new source
    file is the commonest thing a builder's <changed_files> names.
    """
    changed = set()
    for args in (["diff", "--name-only", ref],
                 ["ls-files", "--others", "--exclude-standard"]):
        try:
            proc = subprocess.run(["git", "-C", str(repo)] + args,
                                  capture_output=True, text=True, timeout=120)
        except FileNotFoundError:
            raise GateError("git executable not found; --since cannot be checked")
        except subprocess.TimeoutExpired:
            raise GateError(f"git {args[0]} timed out after 120s")
        if proc.returncode != 0:
            raise GateError(
                f"git {' '.join(args)} failed: {proc.stderr.strip() or proc.stdout.strip()}")
        changed.update(normalize_path(line) for line in proc.stdout.splitlines()
                       if line.strip())
    return changed


def check_consumers(values):
    """Lines that do not match `path::symbol`."""
    bad = []
    for value in values:
        for line in value.splitlines():
            item = line.strip().strip("`").strip()
            item = re.sub(r"^[-*+]\s+", "", item).strip()
            if not item:
                continue
            if not CONSUMERS_LINE_RE.match(item):
                bad.append(item)
    return bad


def check_honesty(elements):
    """Honesty-marker contradictions. See base-persona § Evidence Integrity."""
    problems = []
    for name, values in elements.items():
        if name == "status":
            # <status>BLOCKED</status> is the honest declaration itself, not a
            # marker buried in prose.
            continue
        for value in values:
            if MARKER_RE.search(value) and PASS_CLAIM_RE.search(value):
                problems.append({
                    "rule": "marker_beside_pass_claim",
                    "element": name,
                    "detail": " ".join(value.split())[:200],
                })
    statuses = [v.strip().upper() for v in elements.get("status", [])]
    if "BLOCKED" in statuses:
        blockers = " ".join(elements.get("blockers", [])).strip()
        if blockers.strip("`* ").casefold() in NO_BLOCKER_VALUES:
            problems.append({
                "rule": "blocked_status_names_no_blocker",
                "element": "blockers",
                "detail": blockers or "(empty)",
            })
    return problems


def build_report(text, persona, repo, since=None, fix_round=False,
                 require=(), source="<stdin>", advisory=False):
    persona_key = (persona or "").strip().lower()
    if persona_key not in PERSONA_ELEMENTS:
        known = ", ".join(sorted(PERSONA_ELEMENTS))
        raise GateError(f"unknown persona '{persona}'; expected one of: {known}")
    if not Path(repo).is_dir():
        raise GateError(f"--repo is not a directory: {repo}")

    required = list(PERSONA_ELEMENTS[persona_key])
    waived = []
    if advisory:
        waived = [e for e in required if e in ADVISORY_OPTIONAL_ELEMENTS]
        required = [e for e in required if e not in ADVISORY_OPTIONAL_ELEMENTS]
    if fix_round:
        required.append("fix_verification")
    if "consumers" in require:
        required.append("consumers")

    report = {
        "result": None,
        "source": str(source),
        "persona": persona_key,
        "repo": str(repo),
        "since": since,
        "fix_round": bool(fix_round),
        "advisory": bool(advisory),
        "advisory_waived_elements": waived,
        "required_elements": required,
        "present_elements": [],
        "findings": [],
        "warnings": [],
        "status": None,
        "changed_files": [],
        "artifacts": [],
        "error": None,
    }

    def finding(code, detail, **extra):
        entry = {"code": code, "detail": detail}
        entry.update(extra)
        report["findings"].append(entry)

    block, warnings = extract_handoff(text)
    report["warnings"].extend(warnings)
    if block is None:
        finding("handoff_missing",
                "no well-formed <handoff>...</handoff> block outside fenced code")
        report["result"] = "FAIL"
        return report

    elements = parse_elements(block)
    report["present_elements"] = sorted(elements)
    if advisory:
        report["warnings"].append(
            "--advisory: <" + ">/<".join(waived or ADVISORY_OPTIONAL_ELEMENTS)
            + "> waived for this call — the brief asked for a recommendation, "
              "not a written artifact. Every other element still applies.")
    for tag in unknown_tags(block):
        report["warnings"].append(f"unrecognized element <{tag}> in the handoff")

    for name in required:
        values = elements.get(name, [])
        if not values:
            finding("element_missing", f"<{name}> is absent", element=name)
        elif not any(v.strip() for v in values):
            finding("element_missing", f"<{name}> is present but empty", element=name)

    if "consumers" in require and persona_key not in CONSUMERS_PERSONAS:
        report["warnings"].append(
            f"--require consumers on '{persona_key}': only "
            f"{'/'.join(CONSUMERS_PERSONAS)} carry a standing <consumers> contract")

    statuses = [v.strip() for v in elements.get("status", []) if v.strip()]
    report["status"] = statuses[0] if statuses else None
    for value in statuses:
        if value.upper() not in STATUSES:
            finding("status_invalid",
                    f"<status>{value}</status> is not one of "
                    f"{'/'.join(STATUSES)} — <status> is the DELIVERY state "
                    "(did the agent finish the work it was briefed for); the "
                    "verification verdict (PASS/FAIL/BLOCKED) belongs in the "
                    "body, beside the report it is a verdict about",
                    value=value)
        elif value != value.upper():
            report["warnings"].append(
                f"<status>{value}</status> is not upper-case; read as {value.upper()}")

    declared = {}
    for name in PATH_ELEMENTS:
        if name not in elements:
            continue
        for raw in split_paths(elements[name]):
            state, rel = path_status(repo, raw)
            declared.setdefault(name, []).append(rel)
            if state == "missing":
                finding("path_missing", f"<{name}> names a path that does not "
                                        f"exist under --repo: {rel}",
                        element=name, path=rel)
            elif state == "outside":
                finding("path_missing", f"<{name}> names a path outside --repo: {rel}",
                        element=name, path=rel)
    report["changed_files"] = declared.get("changed_files", [])
    report["artifacts"] = declared.get("artifact", [])
    report["changed_skills"] = declared.get("changed_skills", [])

    if since:
        touched = git_changed_since(repo, since)
        report["git_changed_count"] = len(touched)
        for rel in report["changed_files"]:
            if rel not in touched:
                finding("changed_files_not_in_diff",
                        f"<changed_files> names {rel}, which git does not report "
                        f"as changed or committed since {since}",
                        path=rel, since=since)

    if "consumers" in elements:
        for bad in check_consumers(elements["consumers"]):
            finding("consumers_grammar",
                    f"<consumers> line is not `path::symbol`: {bad}", line=bad)

    for problem in check_honesty(elements):
        finding("honesty_contradiction",
                f"{problem['rule']} in <{problem['element']}>: {problem['detail']}",
                rule=problem["rule"], element=problem["element"])

    report["result"] = "FAIL" if report["findings"] else "PASS"
    return report


def main(argv):
    parser = argparse.ArgumentParser(prog="check_handoff.py")
    parser.add_argument("--handoff", help="file holding the agent's handoff "
                                          "(default: read stdin)")
    parser.add_argument("--persona", help="squad persona that produced it")
    parser.add_argument("--repo", default=".",
                        help="repository root the handoff's paths are relative to")
    parser.add_argument("--since", help="git ref: <changed_files> must be a "
                                        "subset of what git reports changed "
                                        "since it. Optional here, REQUIRED by "
                                        "every pipeline handoff step — it is "
                                        "the only term git can contradict")
    parser.add_argument("--advisory", action="store_true",
                        help="the brief asked for a recommendation, not a "
                             "written artifact (Forge's propose handoff, "
                             "Aria Mode 2): <artifact>/<changed_skills> "
                             "become optional and the ledger records "
                             "advisory: true. Nothing else relaxes.")
    parser.add_argument("--fix-round", action="store_true",
                        help="a remediation round: <fix_verification> is required")
    parser.add_argument("--require", action="append", choices=["consumers"],
                        default=[], help="promote an optional element to required")
    parser.add_argument("--milestone", help="recorded in the ledger line")
    parser.add_argument("--ledger", help="append one JSON record per run to this path")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)

    if args.self_test:
        return run_self_test()

    def finish(code, verdict):
        """One exit point: EVERY return path records a ledger line."""
        append_ledger(args.ledger, argv, args.milestone,
                      [args.handoff] if args.handoff else [], verdict, code,
                      {"advisory": True} if args.advisory else None)
        return code

    if not args.persona:
        print(json.dumps({"result": "ERROR",
                          "error": "missing required argument: --persona"}))
        return finish(2, "ERROR")

    if args.handoff:
        p = Path(args.handoff)
        if not p.is_file():
            print(json.dumps({"result": "ERROR",
                              "error": f"handoff file not found: {args.handoff}"}))
            return finish(2, "ERROR")
        try:
            text = p.read_text(encoding="utf-8-sig", errors="replace")
        except OSError as exc:
            print(json.dumps({"result": "ERROR",
                              "error": f"cannot read handoff file: {exc}"}))
            return finish(2, "ERROR")
        source = args.handoff
    else:
        text = sys.stdin.read()
        source = "<stdin>"
        if not text.strip():
            print(json.dumps({"result": "ERROR",
                              "error": "no --handoff given and stdin was empty"}))
            return finish(2, "ERROR")

    try:
        report = build_report(text, args.persona, args.repo, since=args.since,
                              fix_round=args.fix_round, require=args.require,
                              source=source, advisory=args.advisory)
    except GateError as exc:
        print(json.dumps({"result": "ERROR", "error": str(exc)}))
        return finish(2, "ERROR")

    print(json.dumps(report, indent=2))
    return finish(0, "PASS") if report["result"] == "PASS" else finish(1, "FAIL")


def run_self_test():
    import shutil

    GOOD_MASON = ("<handoff><status>COMPLETE</status>"
                  "<changed_files>src/a.py, src/b.py</changed_files>"
                  "<blockers>None</blockers></handoff>")

    class HandoffTests(unittest.TestCase):
        def setUp(self):
            self.dir = Path(tempfile.mkdtemp())
            (self.dir / "src").mkdir()
            (self.dir / "src" / "a.py").write_text("a", encoding="utf-8")
            (self.dir / "src" / "b.py").write_text("b", encoding="utf-8")
            (self.dir / "docs.md").write_text("d", encoding="utf-8")

        def tearDown(self):
            shutil.rmtree(self.dir, ignore_errors=True)

        def codes(self, report):
            return sorted({f["code"] for f in report["findings"]})

        def run_git(self, *args):
            return subprocess.run(["git", "-C", str(self.dir)] + list(args),
                                  capture_output=True, text=True, timeout=120)

        def make_repo(self):
            try:
                if self.run_git("init", "-q").returncode != 0:
                    self.skipTest("git init failed")
            except FileNotFoundError:
                self.skipTest("git not available")
            self.run_git("config", "user.email", "t@t.t")
            self.run_git("config", "user.name", "t")
            self.run_git("add", "-A")
            self.run_git("commit", "-qm", "base")
            return self.run_git("rev-parse", "HEAD").stdout.strip()

        # --- the happy paths, one per override shape --------------------
        def test_builder_handoff_passes(self):
            r = build_report(GOOD_MASON, "mason", self.dir)
            self.assertEqual(r["result"], "PASS", r["findings"])
            self.assertEqual(r["changed_files"], ["src/a.py", "src/b.py"])

        def test_hybrid_persona_requires_both_elements(self):
            dual = ("<handoff><status>COMPLETE</status>"
                    "<changed_files>src/a.py</changed_files>"
                    "<artifact>docs.md</artifact>"
                    "<blockers>None</blockers></handoff>")
            self.assertEqual(build_report(dual, "quinn", self.dir)["result"], "PASS")
            only_files = ("<handoff><status>COMPLETE</status>"
                          "<changed_files>src/a.py</changed_files>"
                          "<blockers>None</blockers></handoff>")
            r = build_report(only_files, "quinn", self.dir)
            self.assertEqual(self.codes(r), ["element_missing"])
            self.assertEqual(r["findings"][0]["element"], "artifact")

        def test_forge_requires_changed_skills(self):
            forge = ("<handoff><status>COMPLETE</status>"
                     "<changed_skills>docs.md</changed_skills>"
                     "<blockers>None</blockers></handoff>")
            self.assertEqual(build_report(forge, "forge", self.dir)["result"], "PASS")
            r = build_report(GOOD_MASON, "forge", self.dir)
            self.assertIn("element_missing", self.codes(r))

        def test_default_persona_requires_artifact(self):
            r = build_report(GOOD_MASON, "luna", self.dir)
            self.assertEqual(self.codes(r), ["element_missing"])

        # --- --advisory (audit3 Metric 1) -------------------------------

        FORGE_PROPOSE = ("<handoff><status>COMPLETE</status>"
                         "<blockers>None</blockers></handoff>")
        ARIA_ADVISORY = ("<handoff><status>COMPLETE</status>"
                         "<blockers>None</blockers></handoff>")

        def test_forge_propose_handoff_fails_without_advisory(self):
            """bgpdd-learn:48 — the pipeline's own step, exit 1 by design."""
            r = build_report(self.FORGE_PROPOSE, "forge", self.dir)
            self.assertEqual(r["result"], "FAIL")
            self.assertEqual(r["findings"][0]["element"], "changed_skills")

        def test_forge_propose_handoff_passes_with_advisory(self):
            r = build_report(self.FORGE_PROPOSE, "forge", self.dir,
                             advisory=True)
            self.assertEqual(r["result"], "PASS", r["findings"])
            self.assertTrue(r["advisory"])
            self.assertEqual(r["advisory_waived_elements"], ["changed_skills"])
            self.assertNotIn("changed_skills", r["required_elements"])
            self.assertTrue(any("--advisory" in w for w in r["warnings"]))

        def test_aria_mode_2_advisory_passes(self):
            """bgpdd-build:113 — a recommendation, no artifact."""
            r = build_report(self.ARIA_ADVISORY, "aria", self.dir,
                             advisory=True)
            self.assertEqual(r["result"], "PASS", r["findings"])
            self.assertEqual(r["advisory_waived_elements"], ["artifact"])

        def test_advisory_still_requires_status_and_blockers(self):
            for text in ("<handoff><blockers>None</blockers></handoff>",
                         "<handoff><status>COMPLETE</status></handoff>"):
                r = build_report(text, "forge", self.dir, advisory=True)
                self.assertEqual(r["result"], "FAIL", text)
                self.assertEqual(self.codes(r), ["element_missing"])

        def test_advisory_does_not_waive_changed_files(self):
            """A builder that wrote code has an artifact regardless."""
            text = ("<handoff><status>COMPLETE</status>"
                    "<blockers>None</blockers></handoff>")
            r = build_report(text, "mason", self.dir, advisory=True)
            self.assertEqual(r["result"], "FAIL")
            self.assertEqual(r["findings"][0]["element"], "changed_files")

        def test_advisory_does_not_waive_the_status_enum_or_honesty(self):
            text = ("<handoff><status>PASS</status>"
                    "<blockers>None</blockers></handoff>")
            r = build_report(text, "forge", self.dir, advisory=True)
            self.assertIn("status_invalid", self.codes(r))
            blocked = ("<handoff><status>BLOCKED</status>"
                       "<blockers>none</blockers></handoff>")
            r = build_report(blocked, "forge", self.dir, advisory=True)
            self.assertIn("honesty_contradiction", self.codes(r))

        def test_advisory_still_checks_a_declared_path(self):
            text = ("<handoff><status>COMPLETE</status>"
                    "<changed_skills>skills/gone/SKILL.md</changed_skills>"
                    "<blockers>None</blockers></handoff>")
            r = build_report(text, "forge", self.dir, advisory=True)
            self.assertEqual(self.codes(r), ["path_missing"])

        def test_the_status_invalid_message_names_where_a_verdict_belongs(self):
            text = ("<handoff><status>PASS</status>"
                    "<changed_files>src/a.py</changed_files>"
                    "<blockers>None</blockers></handoff>")
            r = build_report(text, "mason", self.dir)
            detail = r["findings"][0]["detail"]
            self.assertIn("delivery", detail.lower())
            self.assertIn("PASS/FAIL/BLOCKED", detail)
            self.assertIn("body", detail)

        def test_advisory_is_recorded_in_the_ledger(self):
            path = self.dir / "h.md"
            path.write_text(self.FORGE_PROPOSE, encoding="utf-8")
            ledger = self.dir / "gates.jsonl"
            code = main(["--handoff", str(path), "--persona", "forge",
                         "--repo", str(self.dir), "--advisory",
                         "--ledger", str(ledger)])
            self.assertEqual(code, 0)
            record = json.loads(
                ledger.read_text(encoding="utf-8").splitlines()[-1])
            self.assertIs(record["advisory"], True)
            # The chain must cover the extra field.
            self.assertEqual(record["self"], ledger_self_hash(record))

        def test_a_non_advisory_ledger_record_carries_no_advisory_key(self):
            path = self.dir / "h.md"
            path.write_text(GOOD_MASON, encoding="utf-8")
            ledger = self.dir / "gates.jsonl"
            self.assertEqual(main(["--handoff", str(path), "--persona",
                                   "mason", "--repo", str(self.dir),
                                   "--ledger", str(ledger)]), 0)
            record = json.loads(
                ledger.read_text(encoding="utf-8").splitlines()[-1])
            self.assertNotIn("advisory", record)

        # --- adversarial ------------------------------------------------
        def test_fenced_handoff_is_not_a_handoff(self):
            """A template shown inside a fence must not satisfy the gate."""
            text = "Here is the shape I will use:\n\n```\n" + GOOD_MASON + "\n```\n"
            r = build_report(text, "mason", self.dir)
            self.assertEqual(self.codes(r), ["handoff_missing"])

        def test_real_handoff_beside_a_fenced_example_uses_the_real_one(self):
            text = ("```\n" + GOOD_MASON + "\n```\n\n"
                    "<handoff><status>BLOCKED</status>"
                    "<changed_files>src/a.py</changed_files>"
                    "<blockers>no test DB</blockers></handoff>")
            r = build_report(text, "mason", self.dir)
            self.assertEqual(r["result"], "PASS", r["findings"])
            self.assertEqual(r["status"], "BLOCKED")

        def test_path_that_does_not_exist_fails(self):
            text = ("<handoff><status>COMPLETE</status>"
                    "<changed_files>src/a.py, src/ghost.py</changed_files>"
                    "<blockers>None</blockers></handoff>")
            r = build_report(text, "mason", self.dir)
            self.assertEqual(self.codes(r), ["path_missing"])
            self.assertEqual(r["findings"][0]["path"], "src/ghost.py")

        def test_path_escaping_the_repo_fails(self):
            text = ("<handoff><status>COMPLETE</status>"
                    "<changed_files>../outside.py</changed_files>"
                    "<blockers>None</blockers></handoff>")
            self.assertEqual(self.codes(build_report(text, "mason", self.dir)),
                             ["path_missing"])

        def test_empty_element_is_missing_not_present(self):
            text = ("<handoff><status>COMPLETE</status>"
                    "<changed_files>   </changed_files>"
                    "<blockers>None</blockers></handoff>")
            r = build_report(text, "mason", self.dir)
            self.assertEqual(self.codes(r), ["element_missing"])
            self.assertIn("empty", r["findings"][0]["detail"])

        def test_unclosed_handoff_is_missing_and_warned(self):
            r = build_report("<handoff><status>COMPLETE</status>", "mason", self.dir)
            self.assertEqual(self.codes(r), ["handoff_missing"])
            self.assertTrue(any("never closed" in w for w in r["warnings"]))

        def test_changed_files_naming_an_untouched_file_fails(self):
            ref = self.make_repo()
            (self.dir / "src" / "a.py").write_text("edited", encoding="utf-8")
            text = ("<handoff><status>COMPLETE</status>"
                    "<changed_files>src/a.py, src/b.py</changed_files>"
                    "<blockers>None</blockers></handoff>")
            r = build_report(text, "mason", self.dir, since=ref)
            self.assertEqual(self.codes(r), ["changed_files_not_in_diff"])
            self.assertEqual(r["findings"][0]["path"], "src/b.py")

        def test_changed_files_subset_of_diff_passes(self):
            ref = self.make_repo()
            (self.dir / "src" / "a.py").write_text("edited", encoding="utf-8")
            (self.dir / "src" / "new.py").write_text("new", encoding="utf-8")
            text = ("<handoff><status>COMPLETE</status>"
                    "<changed_files>src/a.py\nsrc/new.py</changed_files>"
                    "<blockers>None</blockers></handoff>")
            r = build_report(text, "mason", self.dir, since=ref)
            self.assertEqual(r["result"], "PASS", r["findings"])

        def test_bad_since_ref_is_an_error_not_a_pass(self):
            self.make_repo()
            with self.assertRaises(GateError):
                build_report(GOOD_MASON, "mason", self.dir, since="no-such-ref")

        # --- status, consumers, honesty ---------------------------------
        def test_status_outside_the_enum_fails(self):
            text = GOOD_MASON.replace("COMPLETE", "DONE")
            self.assertEqual(self.codes(build_report(text, "mason", self.dir)),
                             ["status_invalid"])

        def test_partial_and_blocked_are_valid_statuses(self):
            for value in ("PARTIAL", "BLOCKED"):
                text = GOOD_MASON.replace("COMPLETE", value).replace(
                    "<blockers>None</blockers>", "<blockers>see above</blockers>")
                self.assertEqual(build_report(text, "mason", self.dir)["result"],
                                 "PASS", value)

        def test_consumers_required_only_when_asked(self):
            self.assertEqual(build_report(GOOD_MASON, "mason", self.dir)["result"],
                             "PASS")
            r = build_report(GOOD_MASON, "mason", self.dir, require=["consumers"])
            self.assertEqual(self.codes(r), ["element_missing"])

        def test_consumers_grammar(self):
            good = GOOD_MASON.replace(
                "<blockers>", "<consumers>src/x.py::handle\nsrc/y.py::Store.load"
                              "</consumers><blockers>")
            self.assertEqual(build_report(good, "mason", self.dir,
                                          require=["consumers"])["result"], "PASS")
            bad = GOOD_MASON.replace(
                "<blockers>", "<consumers>src/x.py handle</consumers><blockers>")
            r = build_report(bad, "mason", self.dir, require=["consumers"])
            self.assertEqual(self.codes(r), ["consumers_grammar"])

        def test_fix_round_requires_fix_verification(self):
            r = build_report(GOOD_MASON, "mason", self.dir, fix_round=True)
            self.assertEqual(self.codes(r), ["element_missing"])
            ok = GOOD_MASON.replace(
                "<blockers>", "<fix_verification>re-ran tests/T::t — 1 passed, "
                              "0 failed</fix_verification><blockers>")
            self.assertEqual(build_report(ok, "mason", self.dir,
                                          fix_round=True)["result"], "PASS")

        def test_not_verified_beside_a_pass_claim_is_a_contradiction(self):
            text = GOOD_MASON.replace(
                "<blockers>", "<fix_verification>NOT VERIFIED — no runtime; "
                              "PASS</fix_verification><blockers>")
            r = build_report(text, "mason", self.dir, fix_round=True)
            self.assertEqual(self.codes(r), ["honesty_contradiction"])

        def test_lowercase_passed_beside_not_verified_is_allowed(self):
            """base-persona sanctions labelling a weaker observation beside a
            result; only an unqualified uppercase verdict token contradicts."""
            text = GOOD_MASON.replace(
                "<blockers>", "<fix_verification>NOT VERIFIED — no rendered "
                              "output; unit tier 3 passed, 0 failed"
                              "</fix_verification><blockers>")
            self.assertEqual(build_report(text, "mason", self.dir,
                                          fix_round=True)["result"], "PASS")

        def test_blocked_status_with_no_blocker_named_is_a_contradiction(self):
            text = GOOD_MASON.replace("COMPLETE", "BLOCKED")
            self.assertEqual(self.codes(build_report(text, "mason", self.dir)),
                             ["honesty_contradiction"])

        def test_unknown_persona_is_an_error(self):
            with self.assertRaises(GateError):
                build_report(GOOD_MASON, "blackgoat", self.dir)
            with self.assertRaises(GateError):
                build_report(GOOD_MASON, "nobody", self.dir)

        def test_unrecognized_element_warns_but_does_not_fail(self):
            text = GOOD_MASON.replace("<blockers>",
                                      "<changed_file>src/a.py</changed_file><blockers>")
            r = build_report(text, "mason", self.dir)
            self.assertEqual(r["result"], "PASS", r["findings"])
            self.assertTrue(any("changed_file" in w for w in r["warnings"]))

        def test_ledger_records_every_exit_path(self):
            ledger = self.dir / "logs" / "gates.jsonl"
            handoff = self.dir / "h.md"
            handoff.write_text(GOOD_MASON, encoding="utf-8")
            self.assertEqual(main(["--handoff", str(handoff), "--persona", "mason",
                                   "--repo", str(self.dir), "--ledger", str(ledger)]), 0)
            handoff.write_text(GOOD_MASON.replace("src/b.py", "src/ghost.py"),
                               encoding="utf-8")
            self.assertEqual(main(["--handoff", str(handoff), "--persona", "mason",
                                   "--repo", str(self.dir), "--ledger", str(ledger)]), 1)
            self.assertEqual(main(["--handoff", str(handoff),
                                   "--repo", str(self.dir), "--ledger", str(ledger)]), 2)
            records = [json.loads(l) for l in
                       ledger.read_text(encoding="utf-8").splitlines() if l.strip()]
            self.assertEqual([r["verdict"] for r in records], ["PASS", "FAIL", "ERROR"])
            self.assertTrue(all(r["gate"] == "check_handoff.py" for r in records))

        def test_missing_repo_directory_is_an_error(self):
            with self.assertRaises(GateError):
                build_report(GOOD_MASON, "mason", str(self.dir / "nope"))

        def test_every_persona_file_has_a_table_row(self):
            """The table above and agents/ must not drift apart."""
            agents_dir = Path(__file__).resolve().parents[3] / "agents"
            if not agents_dir.is_dir():
                self.skipTest("agents/ not resolvable from this checkout")
            on_disk = {p.stem for p in agents_dir.glob("*.md")} - {"blackgoat"}
            self.assertEqual(on_disk - set(PERSONA_ELEMENTS), set())
            self.assertEqual(set(PERSONA_ELEMENTS) - on_disk, set())

    suite = unittest.defaultTestLoader.loadTestsFromTestCase(HandoffTests)
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
