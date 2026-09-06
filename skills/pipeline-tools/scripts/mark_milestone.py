#!/usr/bin/env python3
"""Deterministic milestone-completion writer for plan.md.

`next_milestone.py` reads completion from a `[x]` appended to a milestone
heading — and until this file existed, that `[x]` was a hand edit tied to
nothing. A milestone could be marked done by typing three characters: no
commit, no gate, no evidence. This is the write side of that convention, and
it refuses to append the marker unless the completion is backed:

  * `--require-commit` — HEAD's history must carry a commit naming the
    milestone (`git log --fixed-strings --grep`);
  * `--require-gates` — the LATEST ledger entry for each named gate, scoped
    to this milestone, must record `PASS`. **ON BY DEFAULT** (the default set
    is `check_commit_gate.py`), and it requires `--ledger`: a bare invocation
    is exit 2, not a silent pass. It used to be opt-in while the help text
    called it the default, so the closed default was a documentation claim --
    `mark_milestone.py --plan p --milestone M2` appended the `[x]` and exited
    0 with nothing behind it, which is the exact hand-edit this file replaced.

`--require-commit` stays opt-in because a plan may legitimately be marked up
before a repo exists (a docs-only milestone, a spike). The gate requirement
has an EXPLICIT opt-out for the same case -- `--require-gates none` -- so the
decision to mark an ungated milestone is one somebody makes and the ledger
records, never one a forgotten flag makes silently.

Usage:
    python mark_milestone.py --plan <path> --milestone "<title>" \
        --ledger <path> [--repo <dir>] [--require-commit] \
        [--require-gates <name>[,<name>...] | --require-gates none]
    python mark_milestone.py --self-test

Pure standard library. See ../SKILL.md for the full contract.
"""
import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# Duplicated VERBATIM from next_milestone.py: the write side must recognize
# exactly the headings the read side does, or a marked milestone would be
# invisible to the router. This script family has no shared module by
# convention (GateError is duplicated in seven files).
MILESTONE_HEADING_RE = re.compile(r"^#{2,3}\s*Milestone\b\s+\d")
COMPLETE_RE = re.compile(r"\[x\]", re.IGNORECASE)
HEADING_PREFIX_RE = re.compile(r"^#+\s*")
LINE_SPLIT_RE = re.compile(r"(\r\n|\r|\n)")

DEFAULT_REQUIRE_GATES = ("check_commit_gate.py",)


class GateError(Exception):
    """Structural/usage failure — maps to exit 2."""


def read_text(path):
    """Read a UTF-8 artifact with its line endings intact, tolerating a BOM.

    `newline=""` keeps CRLF as CRLF: this file REWRITES the plan, so
    normalizing line endings would rewrite every line of a Windows-authored
    plan and bury the one-character change in a whole-file diff.
    """
    p = Path(path)
    if not p.is_file():
        raise GateError(f"file not found or not readable: {path}")
    with open(p, "r", encoding="utf-8-sig", errors="replace", newline="") as fh:
        return fh.read()


def write_text(path, text):
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)


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


def verify_ledger_chain(ledger_path):
    """(ok, problem|None) — walk the chain and stop at the FIRST broken link.

    `problem` is `{"line", "reason", "detail"}` with reason one of
    `unparseable`, `legacy-after-chained`, `incomplete-chain-fields`,
    `self-mismatch`, `prev-mismatch`, `unreadable`. A missing ledger file is
    NOT a break here (there is no chain to break); callers that require the
    ledger to exist say so themselves.

    Byte-identical in check_ledger.py, check_commit_gate.py and
    mark_milestone.py (family convention: one file each, no shared module).
    """
    p = Path(ledger_path)
    if not p.is_file():
        return True, None
    try:
        data = p.read_bytes()
    except OSError as exc:
        return False, {"line": 0, "reason": "unreadable",
                       "detail": "cannot read {0}: {1}".format(ledger_path, exc)}
    chained_seen = False
    prev_hash = "genesis"
    for lineno, raw in enumerate(data.splitlines(), start=1):
        if not raw.strip():
            continue
        try:
            rec = json.loads(raw.decode("utf-8-sig", errors="replace"))
        except ValueError:
            return False, {"line": lineno, "reason": "unparseable",
                           "detail": "line is not parseable JSON"}
        if not isinstance(rec, dict):
            return False, {"line": lineno, "reason": "unparseable",
                           "detail": "line is not a JSON object"}
        has_prev, has_self = "prev" in rec, "self" in rec
        if not has_prev and not has_self:
            if chained_seen:
                return False, {
                    "line": lineno, "reason": "legacy-after-chained",
                    "detail": "an unchained record follows a chained one; a "
                              "ledger that has started chaining cannot revert "
                              "to unchained"}
            prev_hash = ledger_line_hash(raw)
            continue
        if not (has_prev and has_self):
            return False, {
                "line": lineno, "reason": "incomplete-chain-fields",
                "detail": "record carries only one of `prev`/`self`; a chained "
                          "record carries both"}
        if rec.get("self") != ledger_self_hash(rec):
            return False, {
                "line": lineno, "reason": "self-mismatch",
                "detail": "`self` does not hash this record's own content — "
                          "the line was edited after it was written"}
        if rec.get("prev") != prev_hash:
            return False, {
                "line": lineno, "reason": "prev-mismatch",
                "detail": "`prev` is {0} but the preceding record hashes to "
                          "{1} — a record was inserted, removed or edited "
                          "before this line".format(
                              str(rec.get("prev"))[:16], prev_hash[:16])}
        chained_seen = True
        prev_hash = ledger_line_hash(raw)
    return True, None


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


def read_ledger(ledger_path):
    """Every parseable JSON-object line of the ledger, in file order."""
    p = Path(ledger_path)
    if not p.is_file():
        return []
    records = []
    for line in p.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(rec, dict):
            records.append(rec)
    return records


def split_lines(text):
    """[(content, line_ending)] — the split that lets one line be rewritten."""
    parts = LINE_SPLIT_RE.split(text)
    lines = []
    for i in range(0, len(parts), 2):
        content = parts[i]
        ending = parts[i + 1] if i + 1 < len(parts) else ""
        if content == "" and ending == "":
            continue
        lines.append([content, ending])
    return lines


def find_milestone(lines, milestone):
    """Return (index, problems) for the ONE heading matching `milestone`.

    Matching is a case-insensitive WHOLE-TOKEN test: the given title must
    appear in the heading with no alphanumeric character glued to either end,
    so `M1` never matches `M10` — the same word-boundary rule
    check_commit_gate.py uses to scope a review section.

    Zero matches and several matches are both refusals, not guesses: marking
    the wrong milestone complete is exactly as bad as marking one that does
    not exist, and there is no safe way to pick.
    """
    needle = milestone.strip()
    if not needle:
        raise GateError("--milestone is empty")
    pattern = re.compile(rf"(?<![a-z0-9]){re.escape(needle.lower())}(?![a-z0-9])")
    matches = [i for i, (content, _e) in enumerate(lines)
               if MILESTONE_HEADING_RE.match(content)
               and pattern.search(content.lower())]
    if not matches:
        return None, [{
            "problem": "milestone_not_found",
            "detail": f"no '## Milestone <n>' heading matching {milestone!r}"}]
    if len(matches) > 1:
        titles = [HEADING_PREFIX_RE.sub("", lines[i][0]).rstrip()
                  for i in matches]
        return None, [{
            "problem": "ambiguous_milestone",
            "detail": f"{len(matches)} headings match {milestone!r} "
                      f"({'; '.join(titles)}) — name one exactly"}]
    return matches[0], []


def check_commit_exists(repo, milestone):
    """True when HEAD's history carries a commit naming the milestone.

    `--fixed-strings` deliberately: a milestone title carries em dashes and
    brackets, and treating it as a regex would either error or match
    something else.
    """
    try:
        proc = subprocess.run(
            ["git", "log", "--fixed-strings", f"--grep={milestone}",
             "--format=%H"],
            cwd=repo, capture_output=True, text=True, timeout=240)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise GateError(f"cannot run git in {repo}: {exc}")
    if proc.returncode != 0:
        raise GateError(
            "git log failed (is --repo a git repository with at least one "
            f"commit?): {(proc.stderr or proc.stdout).strip()}")
    return bool(proc.stdout.strip())


# --- the build game-tape gate (--require-game-tape) ------------------------
# `bgpdd-build` Phase 6 fires each time a milestone closes, and the closing
# write is the moment the Orchestrator most wants to move on -- so the cadence
# rule is enforced by the two scripts that perform that write, not by prose
# (CLAUDE.md convention #9). Byte-identical in mark_milestone.py and
# update_state.py (family convention: one file each, no shared module).
GAME_TAPE_HEADING_RE = re.compile(r"^#{2,4}\s*bgpdd-build\s*[\u2014\u2013-]\s*(?P<body>.+?)\s*$")
GAME_TAPE_ANY_HEADING_RE = re.compile(r"^#{1,6}\s")
GAME_TAPE_BULLET_RE = re.compile(r"^\s*[-*+]\s+\S")
GAME_TAPE_FENCE_RE = re.compile(r"^\s*(?:```|~~~)")
GAME_TAPE_TABLE_ROW_RE = re.compile(r"^\s*\|.*\|\s*$")
GAME_TAPE_MIN_BULLETS = 3
GAME_TAPE_MAX_BULLETS = 6


def game_tape_tokens(milestone):
    """The full normalized title plus its leading identifier.

    The same two tokens check_commit_gate.py matches a review heading on, for
    the same reason: a heading written by hand carries the milestone by name
    or by id, and both are the milestone.
    """
    full = re.sub(r"\s+", " ", (milestone or "").strip().lower())
    tokens = [full] if full else []
    short = re.split(r"[:\u2014\u2013-]", full, maxsplit=1)[0].strip()
    if len(short) >= 2 and short != full:
        tokens.append(short)
    return tokens


def blank_fenced_lines(lines):
    """`lines` with every fenced region (and its fences) replaced by "".

    Line count is preserved so section boundaries still line up with the raw
    text. A heading or bullet inside a fence is a TEMPLATE, and a template has
    never been a checkpoint.
    """
    out, in_fence = [], False
    for line in lines:
        if GAME_TAPE_FENCE_RE.match(line):
            in_fence = not in_fence
            out.append("")
            continue
        out.append("" if in_fence else line)
    return out


def check_game_tape(path, milestone):
    """[] when this milestone has a conforming Phase 6 checkpoint, else why not.

    Problem codes: `game-tape-missing`, `no-section`, `bullet-count`,
    `no-pasted-output`, `no-telemetry`.

    Deliberately the shape `bgpdd-build` Phase 6 states and nothing more
    (convention #8, and narrower than the skeleton's Game Tape section, which
    caps at 10 bullets once per RUN): a `## bgpdd-build - <milestone> - <date>`
    section, 3-6 bullets, at least one fenced block (the verbatim command and
    its captured output -- "no pasted output, no claim"), and either a
    `summarize_run` mention or a table row (the pasted telemetry block).
    The epic-summary heading is explicitly not a milestone checkpoint.
    """
    p = Path(path)
    if not p.is_file():
        return [{"problem": "game-tape-missing",
                 "detail": "no game tape at {0} - Phase 6 fires at the "
                           "milestone close, not at the end of the run".format(path)}]
    try:
        text = p.read_text(encoding="utf-8-sig", errors="replace")
    except OSError as exc:
        return [{"problem": "game-tape-missing",
                 "detail": "game tape {0} is unreadable: {1}".format(path, exc)}]

    raw_lines = text.splitlines()
    blanked = blank_fenced_lines(raw_lines)
    tokens = game_tape_tokens(milestone)
    patterns = [re.compile(r"(?<![a-z0-9])" + re.escape(t) + r"(?![a-z0-9])")
                for t in tokens]

    start = None
    for i, line in enumerate(blanked):
        match = GAME_TAPE_HEADING_RE.match(line)
        if not match:
            continue
        body = re.sub(r"\s+", " ", match.group("body").strip().lower())
        if "epic summary" in body:
            continue
        if not re.search(r"[\u2014\u2013-]", body):
            continue  # no `- <date>` tail: not the Phase 6 heading grammar
        if any(pat.search(body) for pat in patterns):
            start = i  # LAST matching section wins: a re-close appends

    if start is None:
        return [{"problem": "no-section",
                 "detail": "no '## bgpdd-build - <milestone> - <date>' section "
                           "in {0} naming {1!r} (an epic-summary heading is not "
                           "a milestone checkpoint; a heading inside a fenced "
                           "block is a template)".format(path, milestone)}]

    end = len(blanked)
    for j in range(start + 1, len(blanked)):
        if GAME_TAPE_ANY_HEADING_RE.match(blanked[j]):
            end = j
            break
    section_blanked = blanked[start + 1:end]
    section_raw = raw_lines[start + 1:end]

    problems = []
    bullets = [l for l in section_blanked if GAME_TAPE_BULLET_RE.match(l)]
    if not GAME_TAPE_MIN_BULLETS <= len(bullets) <= GAME_TAPE_MAX_BULLETS:
        problems.append({
            "problem": "bullet-count",
            "detail": "the section carries {0} bullet(s); Phase 6 requires "
                      "{1}-{2} per milestone".format(
                          len(bullets), GAME_TAPE_MIN_BULLETS,
                          GAME_TAPE_MAX_BULLETS)})
    fences = [l for l in section_raw if GAME_TAPE_FENCE_RE.match(l)]
    if len(fences) < 2:
        problems.append({
            "problem": "no-pasted-output",
            "detail": "the section carries no fenced block - 'no pasted "
                      "output, no claim': the runtime exit criterion is the "
                      "verbatim command plus its captured output, never a "
                      "summary of it"})
    if ("summarize_run" not in chr(10).join(section_raw)
            and not any(GAME_TAPE_TABLE_ROW_RE.match(l) for l in section_raw)):
        problems.append({
            "problem": "no-telemetry",
            "detail": "the section pastes no summarize_run.py --markdown block "
                      "(no `summarize_run` mention and no table row) - what the "
                      "milestone cost is read off the tool, not off memory"})
    return problems


def check_ledger_gates(ledger_path, gate_names, milestone):
    """Refuse unless each named gate's LATEST entry for this milestone PASSed.

    SCOPE LIMIT, and a deliberate divergence (CLAUDE.md convention #8) from
    check_commit_gate.py's `--require-ledger-gates`, which additionally
    re-hashes each recorded input: this checks the VERDICT only. Input
    freshness is the commit gate's own term, and re-asserting it here would
    refuse a legitimate mark whenever a later milestone touched a shared file.

    The chain IS checked here, and that is not a divergence: an intact chain
    is a precondition for reading any verdict out of the file at all.
    """
    chain_ok, chain = verify_ledger_chain(ledger_path)
    if not chain_ok:
        return [{
            "problem": "ledger_chain_broken",
            "detail": "the gate ledger's hash chain is broken at line "
                      "{0} ({1}): {2}. Every verdict it records is "
                      "unverifiable until the break is explained; run "
                      "check_ledger.py --ledger {3}".format(
                          chain["line"], chain["reason"], chain["detail"],
                          ledger_path)}]
    records = read_ledger(ledger_path)
    problems = []
    for name in gate_names:
        candidates = [r for r in records
                      if r.get("gate") == name
                      and r.get("milestone") == milestone]
        if not candidates:
            problems.append({
                "problem": "ledger_missing",
                "detail": f"no {name} ledger entry for milestone "
                          f"{milestone!r} in {ledger_path}"})
            continue
        latest = candidates[-1]
        if latest.get("verdict") != "PASS":
            problems.append({
                "problem": "ledger_failed",
                "detail": f"the latest {name} entry for {milestone!r} records "
                          f"verdict {latest.get('verdict')!r}"})
    return problems


def build_report(args):
    report = {
        "plan_file": args.plan,
        "milestone": args.milestone,
        "matched_heading": None,
        "require_commit": bool(args.require_commit),
        "commit_found": None,
        "ledger": args.ledger,
        "require_gates": list(args.require_gates or []),
        "require_game_tape": getattr(args, "require_game_tape", None),
        "problems": [],
        "marked": False,
        "result": "FAIL",
        "error": None,
    }
    text = read_text(args.plan)
    lines = split_lines(text)
    if not any(MILESTONE_HEADING_RE.match(c) for c, _e in lines):
        raise GateError(
            "plan has no '## Milestone <n>' or '### Milestone <n>' headings")

    index, problems = find_milestone(lines, args.milestone)
    report["problems"] += problems
    if index is None:
        return report

    heading = lines[index][0]
    report["matched_heading"] = HEADING_PREFIX_RE.sub("", heading).rstrip()

    if COMPLETE_RE.search(heading):
        report["problems"].append({
            "problem": "already_complete",
            "detail": f"heading {report['matched_heading']!r} already carries "
                      "'[x]' — completion is recorded once"})
        return report

    if args.require_commit:
        report["commit_found"] = check_commit_exists(args.repo, args.milestone)
        if not report["commit_found"]:
            report["problems"].append({
                "problem": "no_commit",
                "detail": f"no commit in HEAD's history names "
                          f"{args.milestone!r} (git log --fixed-strings "
                          f"--grep) in {args.repo}"})

    if args.require_gates:
        report["problems"] += check_ledger_gates(
            args.ledger, args.require_gates, args.milestone)

    if getattr(args, "require_game_tape", None):
        report["problems"] += check_game_tape(
            args.require_game_tape, args.milestone)

    if report["problems"]:
        return report

    content, ending = lines[index]
    lines[index][0] = content.rstrip() + " [x]"
    write_text(args.plan, "".join(c + e for c, e in lines))
    report["marked"] = True
    report["result"] = "PASS"
    return report


OPT_OUT_TOKENS = ("none", "off", "no", "-")


def parse_gate_names(values):
    """Flatten repeated and/or comma-separated --require-gates values.

    A single opt-out token (`none`) yields the sentinel `["none"]`, which
    resolve_require_gates() turns into an empty requirement -- deliberately
    NOT the same as an empty value, which means "the default set".
    """
    names = []
    for value in values or []:
        for token in value.split(","):
            token = token.strip()
            if token and token not in names:
                names.append(token)
    if len(names) == 1 and names[0].lower() in OPT_OUT_TOKENS:
        return ["none"]
    return names


def resolve_require_gates(values):
    """The gate list this run enforces. Absent flag => the DEFAULT set.

    Three cases, and the middle one is the whole point of this function:
      * flag absent            -> DEFAULT_REQUIRE_GATES (closed by default)
      * `--require-gates none` -> [] (an explicit, recorded opt-out)
      * anything else          -> the named gates (empty value => default set)
    """
    if values is None:
        return list(DEFAULT_REQUIRE_GATES)
    names = parse_gate_names(values)
    if names == ["none"]:
        return []
    return names or list(DEFAULT_REQUIRE_GATES)


def build_parser():
    parser = argparse.ArgumentParser(prog="mark_milestone.py")
    parser.add_argument("--plan")
    parser.add_argument("--milestone")
    parser.add_argument("--repo", default=".")
    parser.add_argument(
        "--require-commit", action="store_true",
        help="refuse unless HEAD's history carries a commit naming the "
             "milestone")
    parser.add_argument("--ledger",
                        help="append one JSON record per run to this path")
    parser.add_argument(
        "--require-gates", action="append", default=None,
        help="comma-separated gate script names whose LATEST ledger entry for "
             "this milestone must be PASS. ON BY DEFAULT (check_commit_gate.py) "
             "and requires --ledger; pass `none` to waive it explicitly")
    parser.add_argument(
        "--require-game-tape", dest="require_game_tape",
        help="refuse unless game-tape.md carries a conforming "
             "'## bgpdd-build - <milestone> - <date>' checkpoint for this "
             "milestone (bgpdd-build Phase 6)")
    parser.add_argument("--self-test", action="store_true")
    return parser


def main(argv):
    args = build_parser().parse_args(argv)

    if args.self_test:
        return run_self_test()

    # Gate backing is ON unless explicitly waived. Absent flag => the default
    # set; `--require-gates none` => waived and recorded in the ledger argv.
    args.require_gates = resolve_require_gates(args.require_gates)

    def finish(code, verdict):
        """One exit point: EVERY return path records a ledger line."""
        append_ledger(args.ledger, argv, args.milestone,
                      [args.plan] if args.plan else [], verdict, code)
        return code

    missing = [n for n, v in (("--plan", args.plan),
                              ("--milestone", args.milestone)) if not v]
    if missing:
        print(json.dumps({"result": "ERROR",
                          "error": f"missing required argument(s): "
                                   f"{', '.join(missing)}"}))
        return finish(2, "ERROR")
    if args.require_gates and not args.ledger:
        print(json.dumps({
            "result": "ERROR",
            "require_gates": list(args.require_gates),
            "error": "--require-gates requires --ledger (there is no ledger to "
                     "read otherwise). Gate backing is ON BY DEFAULT: pass "
                     "--ledger <path>, or waive it deliberately with "
                     "--require-gates none if this milestone legitimately has "
                     "no gate behind it (a docs-only milestone, a spike)"}))
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
    import shutil
    import tempfile
    import unittest

    PLAN = """# Demo Plan

## Milestone 1 — Setup [API] [vs:api] [x]

## Task 1: Init repo

## Milestone 2 — Persistence [API] [vs:api]

## Task 2: Add DB layer

## Milestone 10 — Reporting [API] [vs:api]

## Task 3: Add report
"""

    def git(args, repo):
        proc = subprocess.run(["git"] + args, cwd=repo, capture_output=True,
                              text=True, timeout=240)
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr or proc.stdout)
        return proc.stdout

    # ---- --require-game-tape fixtures (bgpdd-build Phase 6) -------------

    GT_HEAD = "# Game Tape" + chr(10) + chr(10)
    GT_FENCE = "```"

    def gt_section(title="Milestone 2", date="2026-09-07", bullets=4,
                   fenced=True, telemetry=True, fenced_heading=False):
        """A Phase 6 checkpoint section, with each requirement switchable."""
        heading = "## bgpdd-build \u2014 {0} \u2014 {1}".format(title, date)
        if fenced_heading:
            return chr(10).join(
                [GT_FENCE, heading, "- a", "- b", "- c", GT_FENCE]) + chr(10)
        out = [heading, ""]
        for n in range(bullets):
            out.append("- observation {0}: what actually happened".format(n + 1))
        if fenced:
            out += ["", GT_FENCE, "$ curl -s localhost:8080/health",
                    '{"status":"ok"}', "- Exit code: 0", GT_FENCE]
        if telemetry:
            out += ["", "Telemetry (summarize_run.py --markdown):", "",
                    "| gate | runs | pass |", "|---|---|---|",
                    "| check_commit_gate.py | 1 | 1 |"]
        return chr(10).join(out) + chr(10)

    class MarkMilestoneTests(unittest.TestCase):
        def setUp(self):
            self.dir = Path(tempfile.mkdtemp())
            self.plan = self.dir / "plan.md"
            self.plan.write_text(PLAN, encoding="utf-8")
            self.ledger = self.dir / "gates.jsonl"

        def tearDown(self):
            shutil.rmtree(self.dir, ignore_errors=True)

        def _args(self, milestone="Milestone 2", **kw):
            base = dict(plan=str(self.plan), milestone=milestone,
                        repo=str(self.dir), require_commit=False,
                        ledger=None, require_gates=[],
                        require_game_tape=None, self_test=False)
            base.update(kw)
            return argparse.Namespace(**base)

        def _init_repo(self):
            git(["init", "-q"], str(self.dir))
            git(["config", "user.email", "gate@test"], str(self.dir))
            git(["config", "user.name", "gate"], str(self.dir))
            (self.dir / "src.py").write_text("code\n", encoding="utf-8")
            git(["add", "-A"], str(self.dir))

        def _write_ledger(self, **over):
            """Append a fixture record the way a real gate would: CHAINED.

            A hand-written unchained line after this script has already
            appended its own record is `legacy-after-chained` — which is
            the contract, not a fixture bug, so the fixture chains.
            """
            rec = {"ts": "2026-09-02T00:00:00Z", "gate": "check_commit_gate.py",
                   "argv": [], "milestone": "Milestone 2", "inputs": {},
                   "verdict": "PASS", "exit": 0}
            rec.update(over)
            rec["prev"] = ledger_prev_hash(self.ledger)
            rec["self"] = ledger_self_hash(rec)
            with open(self.ledger, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec) + "\n")

        def _ledger_records(self, path=None):
            p = Path(path or self.ledger)
            return [json.loads(l) for l in
                    p.read_text(encoding="utf-8").splitlines() if l.strip()]

        # ---- happy path ----

        def test_marks_the_matching_heading(self):
            r = build_report(self._args())
            self.assertEqual(r["result"], "PASS")
            self.assertTrue(r["marked"])
            text = self.plan.read_text(encoding="utf-8")
            self.assertIn("## Milestone 2 — Persistence [API] [vs:api] [x]", text)
            # Nothing else moved.
            self.assertIn("## Milestone 10 — Reporting [API] [vs:api]\n", text)
            self.assertEqual(text.count("[x]"), 2)

        def test_next_milestone_agrees_the_mark_took(self):
            """The write side must be visible to the read side."""
            build_report(self._args())
            sys.path.insert(0, str(Path(__file__).parent))
            import next_milestone as nm

            report = nm.build_report(argparse.Namespace(
                plan=str(self.plan), state=None, ledger=None,
                emit_gate_args=False))
            self.assertEqual(report["completed_count"], 2)
            self.assertTrue(
                report["next_milestone"]["title"].startswith("Milestone 10"))

        def test_crlf_plan_keeps_its_line_endings(self):
            self.plan.write_bytes(PLAN.replace("\n", "\r\n").encode("utf-8"))
            build_report(self._args())
            raw = self.plan.read_bytes()
            # Every newline is still a CRLF — no bare LF was introduced.
            self.assertEqual(raw.count(b"\n"), raw.count(b"\r\n"))
            self.assertIn("Persistence [API] [vs:api] [x]\r\n",
                          raw.decode("utf-8"))

        def test_bom_prefixed_plan_still_marks(self):
            self.plan.write_bytes(b"\xef\xbb\xbf" + PLAN.encode("utf-8"))
            r = build_report(self._args())
            self.assertEqual(r["result"], "PASS")

        # ---- refusals ----

        def test_already_complete_is_refused(self):
            r = build_report(self._args(milestone="Milestone 1"))
            self.assertEqual(r["result"], "FAIL")
            self.assertEqual(r["problems"][0]["problem"], "already_complete")
            self.assertFalse(r["marked"])

        def test_unknown_milestone_is_refused(self):
            r = build_report(self._args(milestone="Milestone 42"))
            self.assertEqual(r["problems"][0]["problem"], "milestone_not_found")

        def test_ambiguous_milestone_is_refused(self):
            self.plan.write_text(
                "## Milestone 2 — Persistence [API] [vs:api]\n\n"
                "## Milestone 2 — Persistence (continued) [API] [vs:api]\n",
                encoding="utf-8")
            r = build_report(self._args())
            self.assertEqual(r["problems"][0]["problem"], "ambiguous_milestone")
            self.assertNotIn("[x]", self.plan.read_text(encoding="utf-8"))

        def test_word_boundary_m1_does_not_match_m10(self):
            self.plan.write_text(
                "## Milestone 1 — Setup [API] [vs:api]\n\n"
                "## Milestone 10 — Reporting [API] [vs:api]\n",
                encoding="utf-8")
            r = build_report(self._args(milestone="Milestone 1"))
            self.assertEqual(r["result"], "PASS")
            text = self.plan.read_text(encoding="utf-8")
            self.assertIn("Setup [API] [vs:api] [x]", text)
            self.assertNotIn("Reporting [API] [vs:api] [x]", text)

        def test_plan_without_milestone_headings_is_structural(self):
            self.plan.write_text("# Plan\n\n## Task 1: t\n", encoding="utf-8")
            with self.assertRaises(GateError):
                build_report(self._args())

        def test_missing_plan_is_structural(self):
            with self.assertRaises(GateError):
                build_report(self._args(plan=str(self.dir / "absent.md")))

        # ---- --require-commit ----

        @unittest.skipUnless(shutil.which("git"), "git not on PATH")
        def test_require_commit_refuses_without_a_commit(self):
            self._init_repo()
            git(["commit", "-m", "unrelated work"], str(self.dir))
            r = build_report(self._args(require_commit=True))
            self.assertEqual(r["result"], "FAIL")
            self.assertFalse(r["commit_found"])
            self.assertEqual(r["problems"][0]["problem"], "no_commit")
            self.assertNotIn("Persistence [API] [vs:api] [x]",
                             self.plan.read_text(encoding="utf-8"))

        @unittest.skipUnless(shutil.which("git"), "git not on PATH")
        def test_require_commit_passes_with_a_naming_commit(self):
            self._init_repo()
            git(["commit", "-m", "Milestone 2 — Persistence: add DB layer"],
                str(self.dir))
            r = build_report(self._args(require_commit=True))
            self.assertEqual(r["result"], "PASS")
            self.assertTrue(r["commit_found"])

        @unittest.skipUnless(shutil.which("git"), "git not on PATH")
        def test_require_commit_on_a_repoless_dir_is_structural(self):
            with self.assertRaises(GateError):
                build_report(self._args(require_commit=True))

        # ---- --require-gates ----

        def test_require_gates_passes_on_a_backed_milestone(self):
            self._write_ledger()
            r = build_report(self._args(
                ledger=str(self.ledger),
                require_gates=["check_commit_gate.py"]))
            self.assertEqual(r["result"], "PASS")

        def test_require_gates_refuses_a_missing_entry(self):
            self._write_ledger(milestone="Milestone 9")
            r = build_report(self._args(
                ledger=str(self.ledger),
                require_gates=["check_commit_gate.py"]))
            self.assertEqual(r["problems"][0]["problem"], "ledger_missing")
            self.assertFalse(r["marked"])

        def test_require_gates_refuses_a_failed_latest_entry(self):
            self._write_ledger()
            self._write_ledger(verdict="FAIL", exit=1)   # latest wins
            r = build_report(self._args(
                ledger=str(self.ledger),
                require_gates=["check_commit_gate.py"]))
            self.assertEqual(r["problems"][0]["problem"], "ledger_failed")

        def test_require_gates_defaults_to_the_commit_gate(self):
            self._write_ledger()
            rc = main(["--plan", str(self.plan), "--milestone", "Milestone 2",
                       "--ledger", str(self.ledger), "--require-gates", ""])
            self.assertEqual(rc, 0)

        def test_require_gates_without_ledger_is_usage_error(self):
            self.assertEqual(main([
                "--plan", str(self.plan), "--milestone", "Milestone 2",
                "--require-gates", "check_commit_gate.py"]), 2)

        # ---- the closed default (it used to be a documentation claim) ----

        def test_bare_invocation_is_exit_2_and_marks_nothing(self):
            """`--plan --milestone` alone appended the `[x]` and exited 0."""
            rc = main(["--plan", str(self.plan), "--milestone", "Milestone 2"])
            self.assertEqual(rc, 2)
            self.assertNotIn("Persistence [API] [vs:api] [x]",
                             self.plan.read_text(encoding="utf-8"))

        def test_default_gate_set_applies_without_the_flag(self):
            ledger = self.dir / "gates.jsonl"
            base = ["--plan", str(self.plan), "--milestone", "Milestone 2",
                    "--ledger", str(ledger)]
            # No ledger PASS yet -> refused, with the ledger_missing problem.
            self.assertEqual(main(base), 1)
            self.assertNotIn("Persistence [API] [vs:api] [x]",
                             self.plan.read_text(encoding="utf-8"))
            self.ledger = ledger
            self._write_ledger()
            self.assertEqual(main(base), 0)
            self.assertIn("Persistence [API] [vs:api] [x]",
                          self.plan.read_text(encoding="utf-8"))

        def test_require_gates_refuses_a_broken_ledger_chain(self):
            """A tampered ledger records no verdict this script may read."""
            self._write_ledger()
            self._write_ledger(gate="check_runtime_evidence.py")
            lines = self.ledger.read_text(encoding="utf-8").splitlines()
            rec = json.loads(lines[0])
            rec["verdict"] = "PASS"
            rec["argv"] = ["tampered"]
            lines[0] = json.dumps(rec)
            self.ledger.write_text(chr(10).join(lines) + chr(10),
                                   encoding="utf-8")
            r = build_report(self._args(
                ledger=str(self.ledger),
                require_gates=["check_commit_gate.py"]))
            self.assertEqual(r["result"], "FAIL")
            self.assertEqual(r["problems"][0]["problem"], "ledger_chain_broken")
            self.assertFalse(r["marked"])
            self.assertNotIn("Persistence [API] [vs:api] [x]",
                             self.plan.read_text(encoding="utf-8"))

        def test_require_gates_none_waives_explicitly_without_a_ledger(self):
            rc = main(["--plan", str(self.plan), "--milestone", "Milestone 2",
                       "--require-gates", "none"])
            self.assertEqual(rc, 0)
            self.assertIn("Persistence [API] [vs:api] [x]",
                          self.plan.read_text(encoding="utf-8"))

        def test_resolve_require_gates_three_cases(self):
            self.assertEqual(resolve_require_gates(None),
                             list(DEFAULT_REQUIRE_GATES))
            self.assertEqual(resolve_require_gates([""]),
                             list(DEFAULT_REQUIRE_GATES))
            self.assertEqual(resolve_require_gates(["none"]), [])
            self.assertEqual(resolve_require_gates(["a.py,b.py"]),
                             ["a.py", "b.py"])

        def test_parse_gate_names_splits_a_comma_list(self):
            self.assertEqual(parse_gate_names(["a.py,b.py", "c.py"]),
                             ["a.py", "b.py", "c.py"])

        # ---- the shared gate ledger ----

        def test_ledger_records_every_exit_path(self):
            ledger = self.dir / "logs" / "gates.jsonl"
            base = ["--plan", str(self.plan), "--ledger", str(ledger),
                    "--require-gates", "none"]
            self.assertEqual(main(base + ["--milestone", "Milestone 2"]), 0)
            self.assertEqual(main(base + ["--milestone", "Milestone 2"]), 1)
            self.assertEqual(main(base), 2)
            records = self._ledger_records(ledger)
            self.assertEqual([r["verdict"] for r in records],
                             ["PASS", "FAIL", "ERROR"])
            self.assertEqual([r["exit"] for r in records], [0, 1, 2])
            self.assertTrue(all(r["gate"] == "mark_milestone.py"
                                for r in records))
            self.assertEqual(records[0]["milestone"], "Milestone 2")
            self.assertEqual(records[1]["inputs"][str(self.plan)],
                             sha256_file(self.plan))

        def _gt_run(self, tape, milestone="Milestone 2"):
            r = build_report(self._args(milestone=milestone,
                                        require_game_tape=tape))
            return 0 if r["result"] == "PASS" else 1

        def _gt_codes(self, tape, milestone="Milestone 2"):
            r = build_report(self._args(milestone=milestone,
                                        require_game_tape=tape))
            self.assertFalse(r["marked"])
            self.assertNotIn("Persistence [API] [vs:api] [x]",
                             self.plan.read_text(encoding="utf-8"))
            return [x["problem"] for x in r["problems"]]

        # ---- --require-game-tape (bgpdd-build Phase 6 cadence) ----------

        def _tape(self, **kw):
            p = self.dir / "game-tape.md"
            p.write_text(GT_HEAD + gt_section(**kw), encoding="utf-8")
            return str(p)

        def test_game_tape_conforming_section_passes(self):
            self.assertEqual(self._gt_run(self._tape()), 0)

        def test_game_tape_missing_file_blocks(self):
            self.assertEqual(self._gt_codes(str(self.dir / "nope.md")),
                             ["game-tape-missing"])

        def test_game_tape_wrong_milestone_is_no_section(self):
            self.assertEqual(self._gt_codes(self._tape(title="Milestone 9")),
                             ["no-section"])

        def test_game_tape_epic_summary_heading_does_not_count(self):
            self.assertEqual(self._gt_codes(self._tape(title="epic summary")),
                             ["no-section"])

        def test_game_tape_heading_inside_a_fence_does_not_count(self):
            self.assertEqual(self._gt_codes(self._tape(fenced_heading=True)),
                             ["no-section"])

        def test_game_tape_too_few_bullets_blocks(self):
            self.assertEqual(self._gt_codes(self._tape(bullets=2)),
                             ["bullet-count"])

        def test_game_tape_too_many_bullets_blocks(self):
            self.assertEqual(self._gt_codes(self._tape(bullets=7)),
                             ["bullet-count"])

        def test_game_tape_without_a_fenced_block_blocks(self):
            self.assertEqual(self._gt_codes(self._tape(fenced=False)),
                             ["no-pasted-output"])

        def test_game_tape_without_telemetry_blocks(self):
            self.assertEqual(self._gt_codes(self._tape(telemetry=False)),
                             ["no-telemetry"])

        def test_game_tape_last_matching_section_wins(self):
            p = self.dir / "game-tape.md"
            p.write_text(GT_HEAD + gt_section(bullets=1, fenced=False,
                                              telemetry=False)
                         + chr(10) + gt_section(), encoding="utf-8")
            self.assertEqual(self._gt_run(str(p)), 0)

        def test_game_tape_tokens_carry_the_leading_identifier(self):
            """`M2` names the milestone `M2: Persistence` (commit-gate rule)."""
            self.assertEqual(game_tape_tokens("M2: Persistence"),
                             ["m2: persistence", "m2"])
            self.assertEqual(game_tape_tokens("Milestone 2"), ["milestone 2"])

    suite = unittest.defaultTestLoader.loadTestsFromTestCase(MarkMilestoneTests)
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
