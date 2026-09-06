#!/usr/bin/env python3
"""Deterministic read-modify-write CLI for orchestrator-state.json.

Replaces hand-edits of `.docs/{project}/orchestrator-state.json`, which risk
malformed JSON and silent blocker deletion. Every invocation validates the
existing file (if any), applies the requested actions, stamps "updated",
and writes atomically (temp file + os.replace) before printing the
resulting full state as JSON to stdout.

Usage:
    python update_state.py --state <path> \
        [--init --project-name <name>] \
        [--set-cursor <title|null>] [--set-pipeline <name>] \
        [--set-feature <feature|null>] [--set-branch <name>] \
        [--set-artifact <name>=<path>] \
        [--add-blocker "<text>"] \
        [--resolve-blocker "<substring>" --evidence "<text>"] \
        [--ledger <path>]
    python update_state.py --self-test

Pure standard library. See ../SKILL.md for the full contract.
"""
import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = "1"
SEVERITIES = ("Critical", "Important", "Info")
BLOCKER_ID_RE = re.compile(r"^B-(\d+)$")


class GateError(Exception):
    """Structural/usage failure — maps to exit 2."""

    def __init__(self, message, candidates=None):
        super().__init__(message)
        # Populated only for an ambiguous --resolve-blocker substring match,
        # so the caller can print the candidate entries alongside the error.
        self.candidates = candidates


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


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

    The state file's hash is taken AFTER the write, so the record describes
    the state a later gate will actually read.

    `--resolve-blocker` additionally records the action and the evidence
    string, which is the load-bearing part: the CLI cannot judge whether
    "trust me" is real evidence, but with a ledger the claim is durable,
    attributable and reviewable rather than gone the moment the array shrinks.
    """
    if not ledger_path:
        return
    record = {
        "ts": now_iso(),
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


def build_skeleton(project_name):
    return {
        "schema": SCHEMA_VERSION,
        "project_name": project_name,
        "feature": None,
        "pipeline": "",
        "branch": None,
        "milestone_cursor": None,
        "artifacts": {},
        "blockers": [],
    }


def validate_actions(args):
    """Raise GateError for any invalid CLI action combination."""
    has_action = any([
        args.init,
        args.set_cursor is not None,
        args.set_pipeline is not None,
        args.set_branch is not None,
        args.set_feature is not None,
        bool(args.set_artifact),
        bool(args.add_blocker),
        args.resolve_blocker is not None,
    ])
    if not has_action:
        raise GateError("at least one action is required (see --help)")
    if args.resolve_blocker is not None and not (args.evidence and args.evidence.strip()):
        raise GateError(
            "--resolve-blocker requires --evidence: per the ledger doctrine "
            "(orchestrator-contract §4), a blocker entry is removed only "
            "once its fix is verified")
    if args.init and not args.project_name:
        raise GateError("--init requires --project-name")
    blocker_companions_given = any([
        args.blocker_milestone is not None,
        args.blocker_capability is not None,
        args.blocker_severity is not None,
        args.blocker_source is not None,
        args.blocker_evidence is not None,
    ])
    if blocker_companions_given and not args.add_blocker:
        raise GateError(
            "--blocker-milestone/--blocker-capability/--blocker-severity/"
            "--blocker-source/--blocker-evidence require --add-blocker in "
            "the same invocation")


def normalize_blocker(entry):
    """A blocker array entry, structured-or-legacy, as one canonical shape.

    A legacy freeform string is read as `{id: null, text: <string>,
    milestone: null, capability: null, severity: "Critical", source: null,
    added: null, evidence: null}` -- unscoped and Critical, the fail-safe
    reading. This function never mutates the stored entry; callers that
    write back to `state["blockers"]` keep untouched entries in their
    original raw form (string or dict).
    """
    if isinstance(entry, str):
        return {"id": None, "text": entry, "milestone": None,
                "capability": None, "severity": "Critical",
                "source": None, "added": None, "evidence": None}
    if isinstance(entry, dict):
        severity = entry.get("severity") or "Critical"
        if severity not in SEVERITIES:
            severity = "Critical"
        return {
            "id": entry.get("id"),
            "text": entry.get("text", ""),
            "milestone": entry.get("milestone"),
            "capability": entry.get("capability"),
            "severity": severity,
            "source": entry.get("source"),
            "added": entry.get("added"),
            "evidence": entry.get("evidence"),
        }
    # Defensive: an entry that is neither -- stringify rather than crash.
    return {"id": None, "text": json.dumps(entry), "milestone": None,
            "capability": None, "severity": "Critical",
            "source": None, "added": None, "evidence": None}


def next_blocker_id(blockers):
    """The next `B-<n>` id: one past the highest structured id currently
    present in the array. Legacy string entries (id null) don't count.

    Scoped to entries currently in the array, not the file's full history --
    resolving away the highest-numbered entry and then adding a new one can
    reuse its number. Documented limitation, not prevented: see
    references/update_state.md.
    """
    max_n = 0
    for entry in blockers:
        m = BLOCKER_ID_RE.match(normalize_blocker(entry)["id"] or "")
        if m:
            max_n = max(max_n, int(m.group(1)))
    return max_n + 1


def coerce_schema(state, warnings):
    """Normalize legacy numeric schema 1 → string \"1\" (plan/README drift)."""
    schema = state.get("schema")
    if schema == 1 or schema == "1":
        if schema != SCHEMA_VERSION:
            warnings.append(
                f'coerced schema {schema!r} → {SCHEMA_VERSION!r} '
                f'(authority: SCHEMA_VERSION string)')
        state["schema"] = SCHEMA_VERSION
    elif schema is None:
        state["schema"] = SCHEMA_VERSION
        warnings.append(f'schema missing; set to {SCHEMA_VERSION!r}')
    elif schema != SCHEMA_VERSION:
        raise GateError(
            f"unsupported schema version {schema!r}; expected {SCHEMA_VERSION!r}")


def load_state(path, init, project_name):
    """Load the existing state file, or build a skeleton for --init.

    Returns (state, warnings). Raises GateError on missing/invalid file.
    """
    warnings = []
    if path.exists():
        # utf-8-sig: a BOM-prefixed state file is valid to an editor but
        # json.loads chokes on the mark.
        text = path.read_text(encoding="utf-8-sig")
        try:
            state = json.loads(text)
        except json.JSONDecodeError as exc:
            raise GateError(f"state file is not valid JSON: {exc}")
        if not isinstance(state, dict):
            raise GateError("state file does not contain a JSON object")
        coerce_schema(state, warnings)
        if init:
            warnings.append("--init is a no-op: state file already exists")
        return state, warnings
    if not init:
        raise GateError(f"state file not found: {path} (use --init to create it)")
    return build_skeleton(project_name), warnings


def parse_artifact_spec(spec):
    """Parse `name=path`. The literal value `null` stores JSON null.

    Matches --set-cursor / --set-feature. Without this, `design=null` (what
    bgpdd-lite emits when no stack contract governs) stored the truthy STRING
    "null", and bgpdd-build's "when non-null, inject artifacts.design as the
    architecture reference" rule injected it as a path.
    """
    if "=" not in spec:
        raise GateError(f"invalid --set-artifact value {spec!r}; expected name=path")
    name, _, value = spec.partition("=")
    if not name:
        raise GateError(f"invalid --set-artifact value {spec!r}; expected name=path")
    return name, (None if value == "null" else value)


def resolve_blocker(state, target, evidence, timestamp):
    """Resolve one or more blockers matching `target`, in priority order:

    1. exact `id` match ("B-3")
    2. exact `text` match (case-insensitive) -- removes every entry sharing
       that exact text, the same "resolve all duplicates" behavior this
       replaces
    3. substring match (case-insensitive) against `text` -- must be UNIQUE,
       or the call is refused (GateError, ambiguous) rather than silently
       removing more than the caller meant to name

    Returns (log_lines, warnings, removed_entries). `log_lines` are ISO
    timestamp / id / full JSON entry / evidence, appended to the sibling
    blockers-resolved.log. A target matching nothing warns and changes
    nothing.
    """
    blockers = state.get("blockers", [])
    normalized = [normalize_blocker(b) for b in blockers]

    id_idxs = [i for i, n in enumerate(normalized)
               if n["id"] is not None and n["id"] == target]
    if id_idxs:
        idxs = id_idxs
    else:
        needle = target.strip().lower()
        text_idxs = [i for i, n in enumerate(normalized)
                     if n["text"].lower() == needle]
        if text_idxs:
            idxs = text_idxs
        else:
            sub_idxs = [i for i, n in enumerate(normalized)
                        if needle in n["text"].lower()]
            if not sub_idxs:
                return [], [f"--resolve-blocker matched no entries for {target!r}; nothing removed"], []
            if len(sub_idxs) > 1:
                candidates = [normalized[i] for i in sub_idxs]
                raise GateError(
                    f"--resolve-blocker {target!r} matches {len(sub_idxs)} entries "
                    "ambiguously; be more specific (an id, or the exact text) -- "
                    f"candidates: {json.dumps(candidates)}",
                    candidates=candidates)
            idxs = sub_idxs

    idxset = set(idxs)
    removed = [normalized[i] for i in idxs]
    state["blockers"] = [b for i, b in enumerate(blockers) if i not in idxset]
    log_lines = [f"{timestamp}\t{entry['id'] or ''}\t"
                 f"{json.dumps(entry, ensure_ascii=False)}\t{evidence}"
                 for entry in removed]
    return log_lines, [], removed


def write_atomic(path, state):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".update_state-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
            f.write("\n")
        os.replace(tmp_name, str(path))
    except Exception:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def apply_updates(args):
    """Validate, load, mutate, write, and return (state, warnings)."""
    validate_actions(args)
    path = Path(args.state)
    state, warnings = load_state(path, args.init, args.project_name)
    timestamp = now_iso()

    if args.set_cursor is not None:
        state["milestone_cursor"] = None if args.set_cursor == "null" else args.set_cursor
    if args.set_pipeline is not None:
        state["pipeline"] = args.set_pipeline
    if args.set_branch is not None:
        state["branch"] = args.set_branch
    if args.set_feature is not None:
        state["feature"] = None if args.set_feature == "null" else args.set_feature
    for spec in args.set_artifact:
        name, value = parse_artifact_spec(spec)
        state.setdefault("artifacts", {})[name] = value
    if args.add_blocker:
        blockers = state.setdefault("blockers", [])
        next_n = next_blocker_id(blockers)
        severity = args.blocker_severity or "Critical"
        for text in args.add_blocker:
            blockers.append({
                "id": f"B-{next_n}",
                "text": text,
                "milestone": args.blocker_milestone,
                "capability": args.blocker_capability,
                "severity": severity,
                "source": args.blocker_source,
                "added": timestamp,
                "evidence": args.blocker_evidence,
            })
            next_n += 1

    log_lines = []
    removed_entries = []
    if args.resolve_blocker is not None:
        log_lines, resolve_warnings, removed_entries = resolve_blocker(
            state, args.resolve_blocker, args.evidence, timestamp)
        warnings += resolve_warnings
    # Stashed on the Namespace (not returned) so main()'s ledger closure can
    # cite the resolved entries without widening this function's return
    # shape -- every existing call site unpacks (state, warnings).
    args.resolved_entries = removed_entries

    state["updated"] = timestamp
    write_atomic(path, state)
    if log_lines:
        log_path = path.parent / "blockers-resolved.log"
        with open(log_path, "a", encoding="utf-8") as f:
            for line in log_lines:
                f.write(line + "\n")

    return state, warnings


def build_parser():
    parser = argparse.ArgumentParser(prog="update_state.py")
    parser.add_argument("--state")
    parser.add_argument("--init", action="store_true")
    parser.add_argument("--project-name")
    parser.add_argument("--set-cursor")
    parser.add_argument("--set-pipeline")
    parser.add_argument("--set-branch")
    parser.add_argument(
        "--set-feature",
        help='Tier-1 durable feature id, or the literal "null" for greenfield',
    )
    parser.add_argument("--set-artifact", action="append", default=[])
    parser.add_argument("--add-blocker", action="append", default=[])
    parser.add_argument("--blocker-milestone",
                        help="applies to every --add-blocker in this invocation")
    parser.add_argument("--blocker-capability",
                        help='e.g. "browser", "docker", "device"; applies to '
                             "every --add-blocker in this invocation")
    parser.add_argument("--blocker-severity", choices=list(SEVERITIES),
                        help="default Critical; applies to every --add-blocker "
                             "in this invocation")
    parser.add_argument("--blocker-source",
                        help="agent or gate that raised it; applies to every "
                             "--add-blocker in this invocation")
    parser.add_argument("--blocker-evidence",
                        help="applies to every --add-blocker in this invocation "
                             "(distinct from --evidence, which is --resolve-blocker's)")
    parser.add_argument("--resolve-blocker",
                        help="an id (\"B-3\"), exact text, or a substring that "
                             "must match exactly one entry's text")
    parser.add_argument("--evidence")
    parser.add_argument("--ledger",
                        help="append one JSON record per run to this path")
    parser.add_argument(
        "--milestone",
        help="the milestone this write is about; required by "
             "--require-game-tape and recorded in the ledger line")
    parser.add_argument(
        "--require-game-tape", dest="require_game_tape",
        help="refuse a cursor/pipeline write unless game-tape.md carries a "
             "conforming '## bgpdd-build - <milestone> - <date>' checkpoint "
             "for --milestone (bgpdd-build Phase 6)")
    parser.add_argument("--self-test", action="store_true")
    return parser


def main(argv):
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.self_test:
        return run_self_test()

    def finish(code, verdict):
        """One exit point: EVERY return path records a ledger line."""
        extra = None
        if args.resolve_blocker is not None:
            extra = {"action": "resolve-blocker",
                     "evidence": args.evidence}
            resolved = getattr(args, "resolved_entries", None)
            if resolved:
                extra["resolved_ids"] = [e.get("id") for e in resolved]
                extra["resolved_entries"] = resolved
        # The cursor names the milestone this run is about, when it names one;
        # the literal "null" clears it and is recorded as JSON null.
        milestone = args.milestone or (None if args.set_cursor in (None, "null")
                                       else args.set_cursor)
        append_ledger(args.ledger, argv, milestone,
                      [args.state] if args.state else [], verdict, code, extra)
        return code

    if not args.state:
        print(json.dumps({"error": "--state is required"}))
        return finish(2, "ERROR")

    # The Phase 6 cadence gate. Scoped to the write that CLOSES a milestone --
    # a cursor or pipeline move with --milestone -- because that is the write
    # the checkpoint is the evidence for. Any other action (a blocker add, an
    # artifact set) is untouched: demanding a checkpoint there would make the
    # gate noise, and a gate that fires when nothing closed teaches nothing.
    if args.require_game_tape:
        if not args.milestone:
            print(json.dumps({
                "error": "--require-game-tape requires --milestone (there is "
                         "no milestone whose checkpoint to look for)"}))
            return finish(2, "ERROR")
        closing = (args.set_cursor is not None or args.set_pipeline is not None)
        if not closing:
            print("Warning: --require-game-tape is inactive without "
                  "--set-cursor or --set-pipeline (no milestone is closing "
                  "in this write)", file=sys.stderr)
        else:
            problems = check_game_tape(args.require_game_tape, args.milestone)
            if problems:
                print(json.dumps({
                    "result": "FAIL",
                    "milestone": args.milestone,
                    "require_game_tape": args.require_game_tape,
                    "problems": problems,
                    "error": "the milestone is not closing over a conforming "
                             "Phase 6 game-tape checkpoint; nothing was "
                             "written"}, indent=2))
                return finish(1, "FAIL")

    try:
        state, warnings = apply_updates(args)
    except GateError as exc:
        payload = {"error": str(exc)}
        if exc.candidates is not None:
            payload["candidates"] = exc.candidates
        print(json.dumps(payload))
        return finish(2, "ERROR")

    for w in warnings:
        print(f"Warning: {w}", file=sys.stderr)
    print(json.dumps(state, indent=2))
    return finish(0, "PASS")


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

def run_self_test():
    import shutil
    import unittest

    def ns(state_path, **overrides):
        base = dict(state=str(state_path), init=False, project_name=None,
                    set_cursor=None, set_pipeline=None, set_branch=None,
                    set_feature=None, set_artifact=[], add_blocker=[],
                    blocker_milestone=None, blocker_capability=None,
                    blocker_severity=None, blocker_source=None,
                    blocker_evidence=None,
                    resolve_blocker=None, evidence=None)
        base.update(overrides)
        return argparse.Namespace(**base)

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

    class UpdateStateTests(unittest.TestCase):
        def setUp(self):
            self.dir = Path(tempfile.mkdtemp())
            self.state_path = self.dir / "orchestrator-state.json"

        def tearDown(self):
            shutil.rmtree(self.dir, ignore_errors=True)

        def test_init_creates_skeleton(self):
            state, warnings = apply_updates(ns(self.state_path, init=True,
                                              project_name="demo"))
            self.assertEqual(warnings, [])
            self.assertEqual(state["schema"], "1")
            self.assertEqual(state["project_name"], "demo")
            self.assertIsNone(state["feature"])
            self.assertEqual(state["pipeline"], "")
            self.assertIsNone(state["branch"])
            self.assertIsNone(state["milestone_cursor"])
            self.assertEqual(state["artifacts"], {})
            self.assertEqual(state["blockers"], [])
            self.assertIn("updated", state)
            on_disk = json.loads(self.state_path.read_text(encoding="utf-8"))
            self.assertEqual(on_disk, state)

        def test_init_on_existing_file_is_noop_warning(self):
            apply_updates(ns(self.state_path, init=True, project_name="demo"))
            state, warnings = apply_updates(ns(self.state_path, init=True,
                                              project_name="other",
                                              set_pipeline="bgpdd-build"))
            self.assertTrue(any("no-op" in w for w in warnings))
            self.assertEqual(state["project_name"], "demo")  # untouched
            self.assertEqual(state["pipeline"], "bgpdd-build")

        def test_combined_cursor_pipeline_branch_in_one_call(self):
            apply_updates(ns(self.state_path, init=True, project_name="demo"))
            self.state_path.write_text(
                json.dumps({**json.loads(self.state_path.read_text()),
                           "updated": "SENTINEL"}))
            state, _ = apply_updates(ns(
                self.state_path, set_cursor="M2 - Auth",
                set_pipeline="bgpdd-build", set_branch="feature/auth"))
            self.assertEqual(state["milestone_cursor"], "M2 - Auth")
            self.assertEqual(state["pipeline"], "bgpdd-build")
            self.assertEqual(state["branch"], "feature/auth")
            self.assertNotEqual(state["updated"], "SENTINEL")

        def test_set_cursor_null_sets_json_null(self):
            apply_updates(ns(self.state_path, init=True, project_name="demo",
                             set_cursor="M1"))
            state, _ = apply_updates(ns(self.state_path, set_cursor="null"))
            self.assertIsNone(state["milestone_cursor"])

        def test_set_feature_and_null(self):
            apply_updates(ns(self.state_path, init=True, project_name="demo",
                             set_feature="slide"))
            state, _ = apply_updates(ns(self.state_path, set_feature="null"))
            self.assertIsNone(state["feature"])

        def test_set_artifact_null_sets_json_null(self):
            """bgpdd-lite emits design=null when no stack contract governs."""
            state, _ = apply_updates(ns(
                self.state_path, init=True, project_name="demo",
                set_artifact=["requirements=.docs/demo/requirements.md",
                              "design=null"]))
            self.assertIsNone(state["artifacts"]["design"])
            self.assertEqual(state["artifacts"]["requirements"],
                             ".docs/demo/requirements.md")

        def test_coerces_numeric_schema_1(self):
            self.state_path.write_text(json.dumps({
                "schema": 1, "project_name": "demo", "feature": None,
                "pipeline": "", "branch": None, "milestone_cursor": None,
                "artifacts": {}, "blockers": [],
            }), encoding="utf-8")
            state, warnings = apply_updates(ns(self.state_path,
                                               set_pipeline="bgpdd-plan"))
            self.assertEqual(state["schema"], "1")
            self.assertTrue(any("coerced schema" in w for w in warnings))

        def test_add_blocker_appends_preserving_existing(self):
            apply_updates(ns(self.state_path, init=True, project_name="demo",
                             add_blocker=["first blocker"]))
            state, _ = apply_updates(ns(self.state_path,
                                       add_blocker=["second blocker"]))
            self.assertEqual([b["text"] for b in state["blockers"]],
                             ["first blocker", "second blocker"])

        def test_add_blocker_creates_structured_entry_with_defaults(self):
            """`--add-blocker` alone: auto id, Critical severity, null milestone."""
            state, warnings = apply_updates(ns(self.state_path, init=True,
                                              project_name="demo",
                                              add_blocker=["route missing auth"]))
            self.assertEqual(warnings, [])
            entry = state["blockers"][0]
            self.assertEqual(entry["id"], "B-1")
            self.assertEqual(entry["text"], "route missing auth")
            self.assertIsNone(entry["milestone"])
            self.assertIsNone(entry["capability"])
            self.assertEqual(entry["severity"], "Critical")
            self.assertIsNone(entry["source"])
            self.assertIn("added", entry)
            self.assertIsNone(entry["evidence"])

        def test_add_blocker_companions_apply_to_every_text_in_the_call(self):
            state, _ = apply_updates(ns(
                self.state_path, init=True, project_name="demo",
                add_blocker=["no docker in CI", "no docker on staging"],
                blocker_milestone="M4 — Deploy", blocker_capability="docker",
                blocker_severity="Important", blocker_source="dep",
                blocker_evidence="observed in CI log"))
            for entry in state["blockers"]:
                self.assertEqual(entry["milestone"], "M4 — Deploy")
                self.assertEqual(entry["capability"], "docker")
                self.assertEqual(entry["severity"], "Important")
                self.assertEqual(entry["source"], "dep")
                self.assertEqual(entry["evidence"], "observed in CI log")
            self.assertEqual([e["id"] for e in state["blockers"]], ["B-1", "B-2"])

        def test_blocker_companion_without_add_blocker_is_usage_error(self):
            with self.assertRaises(GateError):
                apply_updates(ns(self.state_path, init=True, project_name="demo",
                                 blocker_milestone="M1"))

        def test_add_blocker_id_increments_across_calls(self):
            apply_updates(ns(self.state_path, init=True, project_name="demo",
                             add_blocker=["a"]))
            apply_updates(ns(self.state_path, add_blocker=["b", "c"]))
            state, _ = apply_updates(ns(self.state_path, add_blocker=["d"]))
            self.assertEqual([e["id"] for e in state["blockers"]],
                             ["B-1", "B-2", "B-3", "B-4"])

        def test_add_blocker_preserves_legacy_string_entries_untouched(self):
            """Mixed array: a pre-existing legacy string is never rewritten."""
            self.state_path.write_text(json.dumps({
                "schema": "1", "project_name": "demo", "feature": None,
                "pipeline": "", "branch": None, "milestone_cursor": None,
                "artifacts": {}, "blockers": ["legacy freeform blocker"],
            }), encoding="utf-8")
            state, _ = apply_updates(ns(self.state_path,
                                        add_blocker=["new structured one"]))
            self.assertEqual(state["blockers"][0], "legacy freeform blocker")
            self.assertIsInstance(state["blockers"][1], dict)
            self.assertEqual(state["blockers"][1]["id"], "B-1")

        def test_resolve_blocker_with_evidence_removes_and_logs(self):
            apply_updates(ns(self.state_path, init=True, project_name="demo",
                             add_blocker=["M3: placeholder route open",
                                         "unrelated blocker"]))
            state, warnings = apply_updates(ns(
                self.state_path, resolve_blocker="placeholder route",
                evidence="verified via test-report.md M3 section"))
            self.assertEqual(warnings, [])
            self.assertEqual(len(state["blockers"]), 1)
            self.assertEqual(state["blockers"][0]["text"], "unrelated blocker")
            log_path = self.dir / "blockers-resolved.log"
            self.assertTrue(log_path.exists())
            log_text = log_path.read_text(encoding="utf-8")
            self.assertIn("M3: placeholder route open", log_text)
            self.assertIn("verified via test-report.md M3 section", log_text)
            self.assertIn("B-1", log_text)

        def test_resolve_blocker_without_evidence_fails_and_leaves_file(self):
            apply_updates(ns(self.state_path, init=True, project_name="demo",
                             add_blocker=["M3: placeholder route open"]))
            before = self.state_path.read_text(encoding="utf-8")
            with self.assertRaises(GateError):
                apply_updates(ns(self.state_path,
                                 resolve_blocker="placeholder route"))
            after = self.state_path.read_text(encoding="utf-8")
            self.assertEqual(before, after)
            self.assertFalse((self.dir / "blockers-resolved.log").exists())

        def test_resolve_blocker_matching_nothing_warns(self):
            apply_updates(ns(self.state_path, init=True, project_name="demo",
                             add_blocker=["unrelated blocker"]))
            state, warnings = apply_updates(ns(
                self.state_path, resolve_blocker="no such substring",
                evidence="n/a"))
            self.assertTrue(any("nothing removed" in w for w in warnings))
            self.assertEqual(len(state["blockers"]), 1)
            self.assertEqual(state["blockers"][0]["text"], "unrelated blocker")

        def test_resolve_blocker_by_exact_id(self):
            apply_updates(ns(self.state_path, init=True, project_name="demo",
                             add_blocker=["first", "second"]))
            state, _ = apply_updates(ns(self.state_path, resolve_blocker="B-1",
                                        evidence="fixed"))
            self.assertEqual(len(state["blockers"]), 1)
            self.assertEqual(state["blockers"][0]["id"], "B-2")

        def test_resolve_blocker_by_exact_text(self):
            """Exact text match wins over a broader substring reading, and
            removes every entry sharing that exact text."""
            apply_updates(ns(self.state_path, init=True, project_name="demo",
                             add_blocker=["route open", "route open extended"]))
            state, _ = apply_updates(ns(self.state_path, resolve_blocker="route open",
                                        evidence="fixed"))
            self.assertEqual(len(state["blockers"]), 1)
            self.assertEqual(state["blockers"][0]["text"], "route open extended")

        def test_resolve_blocker_ambiguous_substring_exits_2_with_candidates(self):
            apply_updates(ns(self.state_path, init=True, project_name="demo",
                             add_blocker=["auth route missing check",
                                         "billing route missing check"]))
            with self.assertRaises(GateError) as ctx:
                apply_updates(ns(self.state_path, resolve_blocker="route missing",
                                 evidence="fixed"))
            self.assertEqual(len(ctx.exception.candidates), 2)
            # Nothing removed on the refusal.
            state = json.loads(self.state_path.read_text(encoding="utf-8"))
            self.assertEqual(len(state["blockers"]), 2)

        def test_ledger_resolve_blocker_records_id_and_full_entry(self):
            import contextlib
            import io

            ledger = self.dir / "gates.jsonl"
            apply_updates(ns(self.state_path, init=True, project_name="demo",
                             add_blocker=["M3: placeholder route open"],
                             blocker_milestone="M3"))
            with contextlib.redirect_stdout(io.StringIO()):
                rc = main(["--state", str(self.state_path),
                           "--resolve-blocker", "B-1",
                           "--evidence", "retested, passes",
                           "--ledger", str(ledger)])
            self.assertEqual(rc, 0)
            rec = self._ledger_records(ledger)[-1]
            self.assertEqual(rec["resolved_ids"], ["B-1"])
            self.assertEqual(rec["resolved_entries"][0]["milestone"], "M3")
            self.assertEqual(rec["resolved_entries"][0]["text"],
                             "M3: placeholder route open")

        def test_bom_prefixed_state_still_loads(self):
            """utf-8 (not -sig) made json.loads choke on the byte-order mark."""
            self.state_path.write_bytes(b"\xef\xbb\xbf" + json.dumps({
                "schema": "1", "project_name": "demo", "feature": None,
                "pipeline": "", "branch": None, "milestone_cursor": None,
                "artifacts": {}, "blockers": [],
            }).encode("utf-8"))
            state, _ = apply_updates(ns(self.state_path,
                                        set_pipeline="bgpdd-build"))
            self.assertEqual(state["pipeline"], "bgpdd-build")

        # ---- the shared gate ledger ----

        def _ledger_records(self, path):
            return [json.loads(l) for l in
                    Path(path).read_text(encoding="utf-8").splitlines() if l.strip()]

        def test_ledger_records_success_and_usage_error(self):
            import contextlib
            import io

            ledger = self.dir / "logs" / "gates.jsonl"
            with contextlib.redirect_stdout(io.StringIO()):
                rc = main(["--state", str(self.state_path), "--init",
                           "--project-name", "demo", "--set-cursor", "M2 — Auth",
                           "--ledger", str(ledger)])
            self.assertEqual(rc, 0)
            with contextlib.redirect_stdout(io.StringIO()):
                rc = main(["--ledger", str(ledger)])
            self.assertEqual(rc, 2)
            records = self._ledger_records(ledger)
            self.assertEqual([r["verdict"] for r in records], ["PASS", "ERROR"])
            self.assertEqual(records[0]["gate"], "update_state.py")
            self.assertEqual(records[0]["milestone"], "M2 — Auth")
            self.assertEqual(records[0]["inputs"][str(self.state_path)],
                             sha256_file(self.state_path))
            self.assertNotIn("action", records[0])

        def test_ledger_records_the_resolve_blocker_evidence(self):
            """The evidence string is unjudgeable — so it must be durable."""
            import contextlib
            import io

            ledger = self.dir / "gates.jsonl"
            apply_updates(ns(self.state_path, init=True, project_name="demo",
                             add_blocker=["M3: placeholder route open"]))
            with contextlib.redirect_stdout(io.StringIO()):
                rc = main(["--state", str(self.state_path),
                           "--resolve-blocker", "placeholder route",
                           "--evidence", "trust me",
                           "--ledger", str(ledger)])
            self.assertEqual(rc, 0)
            rec = self._ledger_records(ledger)[-1]
            self.assertEqual(rec["action"], "resolve-blocker")
            self.assertEqual(rec["evidence"], "trust me")
            self.assertEqual(rec["verdict"], "PASS")

        def test_invalid_json_file_raises(self):
            self.state_path.write_text("{not valid json")
            with self.assertRaises(GateError):
                apply_updates(ns(self.state_path, set_pipeline="bgpdd-build"))

        def test_missing_file_without_init_raises(self):
            with self.assertRaises(GateError):
                apply_updates(ns(self.state_path, set_pipeline="bgpdd-build"))

        def test_init_without_project_name_raises(self):
            with self.assertRaises(GateError):
                apply_updates(ns(self.state_path, init=True))

        def test_no_action_raises(self):
            with self.assertRaises(GateError):
                apply_updates(ns(self.state_path))

        def test_set_artifact(self):
            apply_updates(ns(self.state_path, init=True, project_name="demo"))
            state, _ = apply_updates(ns(
                self.state_path,
                set_artifact=["plan=.docs/demo/plan.md", "design=.docs/demo/design.md"]))
            self.assertEqual(state["artifacts"], {
                "plan": ".docs/demo/plan.md", "design": ".docs/demo/design.md"})

        def test_main_exit_codes(self):
            import contextlib
            import io

            argv_missing_file = ["--state", str(self.state_path),
                                 "--set-pipeline", "x"]
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = main(argv_missing_file)
            self.assertEqual(rc, 2)

            argv_init = ["--state", str(self.state_path), "--init",
                        "--project-name", "demo"]
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = main(argv_init)
            self.assertEqual(rc, 0)
            self.assertEqual(json.loads(buf.getvalue())["project_name"], "demo")

            argv_no_evidence = ["--state", str(self.state_path),
                                "--add-blocker", "b1"]
            with contextlib.redirect_stdout(io.StringIO()):
                rc = main(argv_no_evidence)
            self.assertEqual(rc, 0)

            argv_resolve_no_evidence = ["--state", str(self.state_path),
                                        "--resolve-blocker", "b1"]
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = main(argv_resolve_no_evidence)
            self.assertEqual(rc, 2)
            self.assertIn("error", json.loads(buf.getvalue()))

        # ---- --require-game-tape harness --------------------------------

        def _gt_init(self):
            self.assertEqual(main(["--state", str(self.state_path), "--init",
                                   "--project-name", "demo"]), 0)

        def _gt_run(self, tape, milestone="Milestone 2"):
            self._gt_init()
            return main(["--state", str(self.state_path),
                         "--set-cursor", "Milestone 3",
                         "--milestone", milestone,
                         "--require-game-tape", tape])

        def _gt_codes(self, tape, milestone="Milestone 2"):
            """Exit 1, nothing written, and the codes the gate reported."""
            self._gt_init()
            before = self.state_path.read_text(encoding="utf-8")
            self.assertEqual(main(["--state", str(self.state_path),
                                   "--set-cursor", "Milestone 3",
                                   "--milestone", milestone,
                                   "--require-game-tape", tape]), 1)
            self.assertEqual(self.state_path.read_text(encoding="utf-8"),
                             before)
            return [x["problem"] for x in check_game_tape(tape, milestone)]

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

        def test_game_tape_short_identifier_token_matches(self):
            """`M2` names the milestone `M2: Persistence` (commit-gate rule)."""
            p = self.dir / "game-tape.md"
            p.write_text(GT_HEAD + gt_section(title="M2"), encoding="utf-8")
            self.assertEqual(self._gt_run(str(p), milestone="M2: Persistence"), 0)

        def test_game_tape_requires_milestone(self):
            self._gt_init()
            self.assertEqual(main(["--state", str(self.state_path),
                                   "--set-cursor", "M3",
                                   "--require-game-tape",
                                   str(self.dir / "game-tape.md")]), 2)

        def test_game_tape_inactive_without_a_cursor_or_pipeline_write(self):
            """Scoped to the write that CLOSES a milestone, and only that."""
            self._gt_init()
            self.assertEqual(main(["--state", str(self.state_path),
                                   "--milestone", "Milestone 2",
                                   "--set-artifact", "plan=plan.md",
                                   "--require-game-tape",
                                   str(self.dir / "absent.md")]), 0)

        def test_game_tape_blocks_a_pipeline_write_too(self):
            self._gt_init()
            self.assertEqual(main(["--state", str(self.state_path),
                                   "--set-pipeline", "bgpdd-build",
                                   "--milestone", "Milestone 2",
                                   "--require-game-tape",
                                   str(self.dir / "absent.md")]), 1)

        def test_game_tape_milestone_is_recorded_in_the_ledger_line(self):
            self._gt_init()
            ledger = self.dir / "gates.jsonl"
            main(["--state", str(self.state_path), "--set-cursor", "M3",
                  "--milestone", "Milestone 2", "--ledger", str(ledger),
                  "--require-game-tape", self._tape()])
            rec = json.loads(ledger.read_text(
                encoding="utf-8").splitlines()[-1])
            self.assertEqual(rec["milestone"], "Milestone 2")

    suite = unittest.defaultTestLoader.loadTestsFromTestCase(UpdateStateTests)
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
