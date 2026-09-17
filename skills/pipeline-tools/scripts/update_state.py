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
        [--resolve-blocker "<substring>" --evidence <path>] \
        [--set-halt '{"unit":...,"agent":...,"code":...,"reason":...}'] \
        [--clear-halt <unit>] \
        [--set-status <active|escalated|closed> [--reason "<text>"]] \
        [--ledger <path>]
    python update_state.py --self-test

`--resolve-blocker`/`--evidence`: the ledger doctrine (orchestrator-contract
§4) says a blocker entry is removed only once its fix is VERIFIED, so
`--evidence` is a path, not a sentence. It must resolve to an existing,
non-empty file -- tried relative to the state file's own directory first
(the docs root most evidence lives under, e.g. `evidence/none.md` next to
`orchestrator-state.json`), then relative to the CWD, mirroring
`mark_milestone.py --evidence`'s own rule of reading the path as given. A
path that does not resolve (missing, empty, or a directory) fails the call
closed at exit 1 with a `problems` entry, same shape as `--require-game-tape`
below, and nothing is written. On success the resolved path (relative to the
state file's directory when possible) and its sha256 are recorded on the
matching ledger line next to the removed blocker entries, so a later reader
can verify the file that was actually checked.

`--set-halt`/`--clear-halt`: `state["halt"]` is a single standing entry so a
future `guard_action.py` hook can deny delegation while it stands
(`check_redelegation.py` is the gate that writes it -- see that file).
`--set-halt` takes a JSON object with `unit`/`agent`/`code`/`reason` string
keys, all required; a `ts` stamp is added here, the same way `--add-blocker`
stamps `added`. `--clear-halt <unit>` removes `state["halt"]` only when it
exists AND its `unit` matches; a halt for a different unit, or no halt at
all, is left untouched (a warning, not an error -- clearing what one unit's
gate run does not own must never silently erase another unit's standing halt).

`--set-status`: merges `state["status"] = STATUS` plus a `status_updated`
timestamp, the same way `--set-halt` stamps `ts`. `STATUS` is validated
against a small closed set (`active`, `escalated`, `closed`) via argparse
`choices`, so an unknown value exits 2 before anything is read or written,
same failure shape as every other usage error in this file. `--reason` is
optional here (unlike `--clear-halt`, which requires it) and, when given, is
recorded on the ledger line alongside the new status and the status this
call overwrote. Written by `bgpdd-bugfix` Phase 2 step 5 and Phase 5 step 4
(standalone route) when a lane HALTs and escalates to another pipeline, so
`guard_action.py`'s `lane_is_closed()`/`unfixed_bugfix_lanes()` can treat the
lane as closed without waiting on the 12h freshness window to age it out.

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
STATUSES = ("active", "escalated", "closed")
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

    `--resolve-blocker` additionally records the action, the evidence path
    and its sha256, which is the load-bearing part: the CLI cannot judge
    whether the file's CONTENTS are honest, but main()'s evidence gate does
    require the file exist and be non-empty before the blocker is removed,
    and with a ledger the claim is durable, attributable and reviewable
    rather than gone the moment the array shrinks.
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


# --- the lane game-tape gate (--require-game-tape) -------------------------
# A pipeline's game-tape phase fires each time a milestone closes, and the
# closing write is the moment the Orchestrator most wants to move on -- so the
# cadence rule is enforced by the two scripts that perform that write, not by
# prose (CLAUDE.md convention #9). Byte-identical in mark_milestone.py and
# update_state.py (family convention: one file each, no shared module).
#
# The heading names ITS OWN LANE (`bgpdd-<lane>`). It was hard-coded to
# `bgpdd-build`, which made the flag unusable from every other lane:
# `bgpdd-bugfix`'s Phase 5 tape is written under a `## bgpdd-bugfix - `
# heading and could never satisfy a gate that only looked for one word, so
# that lane's tape was unenforceable. Build is unchanged -- `bgpdd-build` is
# one value of `<lane>` -- and the SHAPE requirements below (3-6 bullets, a
# fenced block, a telemetry line) are identical for every lane.
GAME_TAPE_HEADING_RE = re.compile(
    r"^#{2,4}\s*(?P<lane>bgpdd-[a-z]+)\s*[\u2014\u2013-]\s*(?P<body>.+?)\s*$")
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

    Deliberately the shape a lane's game-tape phase states and nothing more
    (convention #8, and narrower than the skeleton's Game Tape section, which
    caps at 10 bullets once per RUN): a
    `## bgpdd-<lane> - <milestone> - <date>` section (`bgpdd-build`,
    `bgpdd-bugfix`, ... -- the lane writing the tape names itself),
    3-6 bullets, at least one fenced block (the verbatim command and
    its captured output -- "no pasted output, no claim"), and either a
    `summarize_run` mention or a table row (the pasted telemetry block).
    The epic-summary heading is explicitly not a milestone checkpoint.
    """
    p = Path(path)
    if not p.is_file():
        return [{"problem": "game-tape-missing",
                 "detail": "no game tape at {0} - the lane's game-tape "
                           "phase fires at the milestone close, not at the "
                           "end of the run".format(path)}]
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
                 "detail": "no '## bgpdd-<lane> - <milestone> - <date>' section "
                           "in {0} naming {1!r} (any lane name matches: "
                           "bgpdd-build, bgpdd-bugfix, ...; an epic-summary "
                           "heading is not a milestone checkpoint; a heading "
                           "inside a fenced block is a template)".format(
                               path, milestone)}]

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
        args.set_halt is not None,
        args.clear_halt is not None,
        args.set_status is not None,
    ])
    if not has_action:
        raise GateError("at least one action is required (see --help)")
    if args.resolve_blocker is not None and not (args.evidence and args.evidence.strip()):
        raise GateError(
            "--resolve-blocker requires --evidence: per the ledger doctrine "
            "(orchestrator-contract §4), a blocker entry is removed only "
            "once its fix is verified")
    if args.clear_halt is not None and not (args.reason and args.reason.strip()):
        raise GateError(
            "--clear-halt requires --reason: check_redelegation.py never "
            "clears a halt itself, so this is the one place a halt is "
            "removed -- a human's recorded word for what changed in the "
            "world, not a re-run passing")
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


def resolve_evidence_path(state_path, evidence):
    """Resolve --resolve-blocker's --evidence to an existing, non-empty file.

    Tried in order: relative to the state file's own directory first (the
    docs root most evidence lives under), then relative to the CWD --
    `mark_milestone.py`'s own --evidence rule of reading the path as given.
    An absolute path is tried once, as given.

    Returns (path, problems): on success `path` is the resolved `Path` and
    `problems` is `[]`; on failure `path` is None and `problems` is a
    check_game_tape()-shaped list with one `evidence_not_found` /
    `evidence_is_directory` / `evidence_empty` entry. A prose string like
    "trust me" is a syntactically valid, simply nonexistent path, so it
    falls out as `evidence_not_found` like any other typo -- the gate does
    not need to tell prose apart from a bad filename to refuse both.
    """
    ev = Path(evidence)
    candidates = [ev] if ev.is_absolute() else [Path(state_path).parent / ev, ev]
    first_dir = None
    for cand in candidates:
        if cand.is_file():
            if cand.stat().st_size == 0:
                return None, [{
                    "problem": "evidence_empty",
                    "detail": f"--evidence {evidence!r} resolves to {cand}, "
                              "which is empty"}]
            return cand, []
        if first_dir is None and cand.is_dir():
            first_dir = cand
    if first_dir is not None:
        return None, [{
            "problem": "evidence_is_directory",
            "detail": f"--evidence {evidence!r} resolves to {first_dir}, "
                      "which is a directory, not a file"}]
    tried = "; ".join(str(c) for c in candidates)
    return None, [{
        "problem": "evidence_not_found",
        "detail": f"--evidence {evidence!r} does not resolve to an existing "
                  f"file (tried: {tried})"}]


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
    # Stashed on the Namespace (not returned) so main()'s ledger closure can
    # record what status this call overwrote, the same pattern --clear-halt
    # uses above for the halt it removed.
    args.previous_status = None
    if args.set_status is not None:
        args.previous_status = state.get("status")
        state["status"] = args.set_status
        state["status_updated"] = timestamp
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

    if args.set_halt is not None:
        try:
            halt = json.loads(args.set_halt)
        except json.JSONDecodeError as exc:
            raise GateError(f"--set-halt is not valid JSON: {exc}")
        if not isinstance(halt, dict):
            raise GateError("--set-halt must be a JSON object")
        required = ("unit", "agent", "code", "reason")
        missing = [k for k in required
                  if not (isinstance(halt.get(k), str) and halt.get(k).strip())]
        if missing:
            raise GateError(
                "--set-halt is missing required non-empty string key(s): "
                f"{', '.join(missing)} (expected unit/agent/code/reason)")
        state["halt"] = {"unit": halt["unit"], "agent": halt["agent"],
                         "code": halt["code"], "reason": halt["reason"],
                         "ts": timestamp}
    # Stashed on the Namespace (not returned) so main()'s ledger closure can
    # record what was actually cleared, the same pattern --resolve-blocker
    # uses below for its removed entries.
    args.cleared_halt = None
    if args.clear_halt is not None:
        existing = state.get("halt")
        if existing is None:
            warnings.append(
                f"--clear-halt {args.clear_halt!r}: no halt is set; nothing "
                "to clear")
        elif not isinstance(existing, dict) or existing.get("unit") != args.clear_halt:
            current_unit = existing.get("unit") if isinstance(existing, dict) else existing
            warnings.append(
                f"--clear-halt {args.clear_halt!r}: current halt is for unit "
                f"{current_unit!r}, not {args.clear_halt!r}; left untouched")
        else:
            args.cleared_halt = existing
            del state["halt"]

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


PURPOSE = ("The sanctioned read-modify-write path for "
           "orchestrator-state.json: cursor, artifacts, blockers, halts and "
           "status, gated by evidence.")

EPILOG = """Reads:
  --state -- orchestrator-state.json; must be a JSON OBJECT. --init writes
    the skeleton
    {"schema": "1", "project_name": <--project-name>, "feature": null,
     "pipeline": "", "branch": null, "milestone_cursor": null,
     "artifacts": {}, "blockers": []}; on an existing file it is a no-op
    warning while the call's other actions still apply.
  --resolve-blocker <target> -- matched against "blockers" in this order:
    exact id, exact text (removing every entry sharing it), unique
    substring (ambiguous prints "candidates"). Matching nothing only warns.
  --evidence <path> -- resolved against the STATE FILE's directory first,
    then the CWD (an absolute path once, as given); must exist, non-empty.
  --require-game-tape <path> -- shared byte-for-byte with mark_milestone.py.
    Fences blanked, it demands a "## bgpdd-<lane> - <milestone> - <date>"
    heading (ANY lane name) matching --milestone by whole token (full title
    or its leading identifier; the epic-summary heading never counts, last
    section wins), 3-6 bullets, one or more fenced blocks, and either a
    summarize_run mention or a table row. ACTIVE ONLY on a --set-cursor /
    --set-pipeline write with --milestone; any other action warns.

Writes:
  --state -- ATOMICALLY, "updated" stamped on every successful call.
    --set-cursor / -pipeline / -branch / -feature set those fields
    verbatim and --set-artifact <name>=<path> (repeatable) merges into
    "artifacts"; in all of these the LITERAL STRING "null" stores JSON
    null. --add-blocker (repeatable) appends an entry with auto id "B-<n>",
    one past the highest present (a resolved top id can be reused); legacy
    entries are never rewritten, and the --blocker-* companions apply to
    EVERY --add-blocker in the invocation. --set-status merges "status"
    plus a "status_updated" stamp. --set-halt takes a JSON object with
    non-empty string "unit"/"agent"/"code"/"reason", stamps "added", and
    REPLACES any standing halt (one entry, never a list); --clear-halt
    <unit> removes it only for that exact unit, and a mismatch or absence
    is a no-op warning.
  blockers-resolved.log, beside the state file -- one appended line per
    removal: "<ts>\\t<id>\\t<full entry>\\t<evidence>".
  --ledger -- one chained record per run. --resolve-blocker adds
    "action": "resolve-blocker", "evidence" (raw), "resolved_ids",
    "resolved_entries" and, once it resolves, "evidence_resolved"
    (state-dir-relative) and "evidence_sha256"; --clear-halt adds
    "action": "clear-halt", the unit, the halt's "code" and the reason;
    --set-status records "previous_status" and any --reason. --milestone
    is this run's ledger milestone, overriding the --set-cursor fallback.

Problem codes:
  evidence_not_found     --evidence resolves to no such file
  evidence_empty         --evidence resolves to a zero-byte file
  evidence_is_directory  --evidence resolves to a directory
  game-tape-missing      --require-game-tape path absent or unreadable
  no-section             no conforming ## bgpdd-<lane> heading for it
  bullet-count           the section does not carry 3-6 bullets
  no-pasted-output       the section carries no fenced block
  no-telemetry           no summarize_run mention and no table row

JSON keys:
  the full resulting state object.

Exit codes:
  0  the action(s) applied and the file was written
  1  the game-tape gate refused, or --resolve-blocker's --evidence did not
     resolve to an existing, non-empty file -- nothing is written
  2  usage/structural failure: missing --state, no action, --init without
     --project-name, --resolve-blocker without a non-empty --evidence, an
     ambiguous resolve target, a --blocker-* companion without
     --add-blocker, a bad --set-artifact spec, a --state that is not a
     JSON object, a missing --state without --init, --require-game-tape
     without --milestone, a malformed / non-object / missing-key
     --set-halt, or --clear-halt without a non-empty --reason

Self-test:
  python update_state.py --self-test   (69 cases)
"""


class PurposeFirstParser(argparse.ArgumentParser):
    """`--help` whose FIRST line is the one-line purpose, then usage/args/epilog.

    argparse prints usage before the description; the registry's
    `description` must equal help line 1 verbatim, so the description is
    lifted out and re-emitted ahead of the standard body.
    """

    def format_help(self):
        purpose = (self.description or "").strip()
        saved, self.description = self.description, None
        try:
            body = super().format_help()
        finally:
            self.description = saved
        return purpose + "\n\n" + body if purpose else body


def build_parser():
    parser = PurposeFirstParser(
        prog="update_state.py",
        description=PURPOSE,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=EPILOG,
    )
    parser.add_argument("--state")
    parser.add_argument("--init", action="store_true")
    parser.add_argument("--project-name")
    parser.add_argument("--set-cursor")
    parser.add_argument("--set-pipeline")
    parser.add_argument("--set-branch")
    parser.add_argument("--set-feature")
    parser.add_argument("--set-artifact", action="append", default=[])
    parser.add_argument("--add-blocker", action="append", default=[])
    parser.add_argument("--blocker-milestone")
    parser.add_argument("--blocker-capability",
                        help='e.g. "browser", "docker"')
    parser.add_argument("--blocker-severity", choices=list(SEVERITIES),
                        help="default Critical")
    parser.add_argument("--blocker-source",
                        help="agent or gate that raised it")
    parser.add_argument("--blocker-evidence")
    parser.add_argument("--resolve-blocker",
                        help="an id, exact text, or a substring")
    parser.add_argument("--evidence",
                        help="--resolve-blocker only (see Reads)")
    parser.add_argument("--set-halt", dest="set_halt",
                        help="JSON object for the standing halt")
    parser.add_argument("--clear-halt", dest="clear_halt",
                        help="clear this unit's halt; needs --reason")
    parser.add_argument("--reason",
                        help="required with --clear-halt")
    parser.add_argument("--set-status", dest="set_status",
                        choices=list(STATUSES))
    parser.add_argument("--ledger",
                        help="append one JSON record per run to this path")
    parser.add_argument("--milestone",
                        help="required by --require-game-tape; scopes the "
                             "ledger record")
    parser.add_argument(
        "--require-game-tape", dest="require_game_tape",
        help="game-tape file that must carry this milestone's checkpoint")
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
            if getattr(args, "evidence_resolved", None):
                extra["evidence_resolved"] = args.evidence_resolved
                extra["evidence_sha256"] = args.evidence_sha256
            resolved = getattr(args, "resolved_entries", None)
            if resolved:
                extra["resolved_ids"] = [e.get("id") for e in resolved]
                extra["resolved_entries"] = resolved
        elif args.clear_halt is not None:
            extra = {"action": "clear-halt", "unit": args.clear_halt,
                     "reason": args.reason}
            cleared = getattr(args, "cleared_halt", None)
            if cleared:
                extra["cleared_code"] = cleared.get("code")
                extra["cleared_halt"] = cleared
        elif args.set_status is not None:
            extra = {"action": "set-status", "status": args.set_status}
            if args.reason:
                extra["reason"] = args.reason
            previous = getattr(args, "previous_status", None)
            if previous is not None:
                extra["previous_status"] = previous
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

    # The evidence gate for --resolve-blocker (CLAUDE.md convention #9 /
    # audit Metric 19.1): a blank --evidence is a usage error caught by
    # validate_actions() below (exit 2); a non-blank --evidence that does not
    # resolve to a real file is a FAILED gate, not a usage error, so it is
    # checked here -- same FAIL-before-any-write shape as --require-game-tape
    # above -- and exits 1 with nothing written.
    args.evidence_resolved = None
    args.evidence_sha256 = None
    if args.resolve_blocker is not None and args.evidence and args.evidence.strip():
        resolved, problems = resolve_evidence_path(args.state, args.evidence)
        if problems:
            print(json.dumps({
                "result": "FAIL",
                "resolve_blocker": args.resolve_blocker,
                "evidence": args.evidence,
                "problems": problems,
                "error": "--resolve-blocker's evidence does not resolve to "
                         "an existing, non-empty file; nothing was written"},
                indent=2))
            return finish(1, "FAIL")
        args.evidence_sha256 = sha256_file(resolved)
        state_dir = Path(args.state).parent
        try:
            args.evidence_resolved = str(resolved.relative_to(state_dir))
        except ValueError:
            args.evidence_resolved = str(resolved)

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
                    resolve_blocker=None, evidence=None,
                    set_halt=None, clear_halt=None, reason=None,
                    set_status=None)
        base.update(overrides)
        return argparse.Namespace(**base)

    # ---- --require-game-tape fixtures (bgpdd-build Phase 6) -------------

    GT_HEAD = "# Game Tape" + chr(10) + chr(10)
    GT_FENCE = "```"

    def gt_section(title="Milestone 2", date="2026-09-07", bullets=4,
                   fenced=True, telemetry=True, fenced_heading=False,
                   lane="bgpdd-build"):
        """A game-tape checkpoint section, each requirement switchable."""
        heading = "## {0} \u2014 {1} \u2014 {2}".format(lane, title, date)
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
            evidence = self.dir / "evidence.md"
            evidence.write_text("retested, passes\n", encoding="utf-8")
            apply_updates(ns(self.state_path, init=True, project_name="demo",
                             add_blocker=["M3: placeholder route open"],
                             blocker_milestone="M3"))
            with contextlib.redirect_stdout(io.StringIO()):
                rc = main(["--state", str(self.state_path),
                           "--resolve-blocker", "B-1",
                           "--evidence", str(evidence),
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

        def test_resolve_blocker_evidence_prose_string_fails_closed(self):
            """Metric 19.1: a typed sentence used to pass as evidence and
            silently remove a Critical blocker. It must now resolve to an
            existing, non-empty file -- "trust me" does not, so the call
            fails closed at exit 1 and nothing is written or removed."""
            import contextlib
            import io

            ledger = self.dir / "gates.jsonl"
            apply_updates(ns(self.state_path, init=True, project_name="demo",
                             add_blocker=["M3: placeholder route open"]))
            before = self.state_path.read_text(encoding="utf-8")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = main(["--state", str(self.state_path),
                           "--resolve-blocker", "placeholder route",
                           "--evidence", "trust me",
                           "--ledger", str(ledger)])
            self.assertEqual(rc, 1)
            self.assertEqual(self.state_path.read_text(encoding="utf-8"), before)
            payload = json.loads(buf.getvalue())
            self.assertEqual(payload["result"], "FAIL")
            self.assertEqual(payload["problems"][0]["problem"],
                             "evidence_not_found")
            rec = self._ledger_records(ledger)[-1]
            self.assertEqual(rec["verdict"], "FAIL")

        def test_resolve_blocker_evidence_nonexistent_path_fails_closed(self):
            apply_updates(ns(self.state_path, init=True, project_name="demo",
                             add_blocker=["M3: placeholder route open"]))
            before = self.state_path.read_text(encoding="utf-8")
            import contextlib
            import io

            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = main(["--state", str(self.state_path),
                           "--resolve-blocker", "B-1",
                           "--evidence", str(self.dir / "no-such-file.md")])
            self.assertEqual(rc, 1)
            self.assertEqual(self.state_path.read_text(encoding="utf-8"), before)
            self.assertEqual(json.loads(buf.getvalue())["problems"][0]["problem"],
                             "evidence_not_found")

        def test_resolve_blocker_evidence_empty_file_fails_closed(self):
            evidence = self.dir / "empty.md"
            evidence.write_text("", encoding="utf-8")
            apply_updates(ns(self.state_path, init=True, project_name="demo",
                             add_blocker=["M3: placeholder route open"]))
            import contextlib
            import io

            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = main(["--state", str(self.state_path),
                           "--resolve-blocker", "B-1",
                           "--evidence", str(evidence)])
            self.assertEqual(rc, 1)
            self.assertEqual(json.loads(buf.getvalue())["problems"][0]["problem"],
                             "evidence_empty")

        def test_resolve_blocker_evidence_directory_fails_closed(self):
            apply_updates(ns(self.state_path, init=True, project_name="demo",
                             add_blocker=["M3: placeholder route open"]))
            import contextlib
            import io

            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = main(["--state", str(self.state_path),
                           "--resolve-blocker", "B-1",
                           "--evidence", str(self.dir)])
            self.assertEqual(rc, 1)
            self.assertEqual(json.loads(buf.getvalue())["problems"][0]["problem"],
                             "evidence_is_directory")

        def test_resolve_blocker_evidence_relative_to_state_dir(self):
            """A relative --evidence resolves against the state file's own
            directory first (the docs root), not just the CWD -- and the
            resolved path plus its sha256 are recorded so a later reader can
            verify the file that was actually checked."""
            evidence = self.dir / "evidence" / "none.md"
            evidence.parent.mkdir(parents=True, exist_ok=True)
            evidence.write_text("verified\n", encoding="utf-8")
            apply_updates(ns(self.state_path, init=True, project_name="demo",
                             add_blocker=["M3: placeholder route open"]))
            ledger = self.dir / "gates.jsonl"
            import contextlib
            import io

            with contextlib.redirect_stdout(io.StringIO()):
                rc = main(["--state", str(self.state_path),
                           "--resolve-blocker", "B-1",
                           "--evidence", "evidence/none.md",
                           "--ledger", str(ledger)])
            self.assertEqual(rc, 0)
            rec = self._ledger_records(ledger)[-1]
            self.assertEqual(rec["evidence_resolved"],
                             str(Path("evidence") / "none.md"))
            self.assertEqual(rec["evidence_sha256"], sha256_file(evidence))

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

        # ---- --set-halt / --clear-halt (check_redelegation.py) -----------

        def _halt_json(self, **overrides):
            base = {"unit": "M1: Auth", "agent": "quinn",
                    "code": "halt_environment", "reason": "no admin shell"}
            base.update(overrides)
            return json.dumps(base)

        def test_set_halt_merges_without_touching_other_keys(self):
            apply_updates(ns(self.state_path, init=True, project_name="demo",
                             set_pipeline="bgpdd-build", set_branch="feature/x"))
            state, warnings = apply_updates(ns(self.state_path,
                                              set_halt=self._halt_json()))
            self.assertEqual(warnings, [])
            self.assertEqual(state["halt"]["unit"], "M1: Auth")
            self.assertEqual(state["halt"]["agent"], "quinn")
            self.assertEqual(state["halt"]["code"], "halt_environment")
            self.assertEqual(state["halt"]["reason"], "no admin shell")
            self.assertIn("ts", state["halt"])
            # Untouched.
            self.assertEqual(state["pipeline"], "bgpdd-build")
            self.assertEqual(state["branch"], "feature/x")

        def test_set_halt_not_json_raises(self):
            apply_updates(ns(self.state_path, init=True, project_name="demo"))
            with self.assertRaises(GateError):
                apply_updates(ns(self.state_path, set_halt="{not json"))

        def test_set_halt_not_an_object_raises(self):
            apply_updates(ns(self.state_path, init=True, project_name="demo"))
            with self.assertRaises(GateError):
                apply_updates(ns(self.state_path, set_halt="[1, 2]"))

        def test_set_halt_missing_key_raises_and_writes_nothing(self):
            apply_updates(ns(self.state_path, init=True, project_name="demo"))
            before = self.state_path.read_text(encoding="utf-8")
            with self.assertRaises(GateError):
                apply_updates(ns(self.state_path,
                                 set_halt=self._halt_json(reason="")))
            after = self.state_path.read_text(encoding="utf-8")
            self.assertEqual(before, after)

        def test_clear_halt_without_reason_raises_and_writes_nothing(self):
            """check_redelegation.py never clears a halt itself -- this is
            the one place a halt is removed, and it requires a human's
            recorded word for what changed."""
            apply_updates(ns(self.state_path, init=True, project_name="demo",
                             set_halt=self._halt_json()))
            before = self.state_path.read_text(encoding="utf-8")
            with self.assertRaises(GateError):
                apply_updates(ns(self.state_path, clear_halt="M1: Auth"))
            after = self.state_path.read_text(encoding="utf-8")
            self.assertEqual(before, after)

        def test_clear_halt_blank_reason_raises(self):
            apply_updates(ns(self.state_path, init=True, project_name="demo",
                             set_halt=self._halt_json()))
            with self.assertRaises(GateError):
                apply_updates(ns(self.state_path, clear_halt="M1: Auth",
                                 reason="   "))

        def test_clear_halt_matching_unit_removes(self):
            apply_updates(ns(self.state_path, init=True, project_name="demo",
                             set_halt=self._halt_json()))
            state, warnings = apply_updates(ns(
                self.state_path, clear_halt="M1: Auth",
                reason="admin shell provisioned by IT ticket #123"))
            self.assertEqual(warnings, [])
            self.assertNotIn("halt", state)

        def test_clear_halt_mismatched_unit_leaves_untouched(self):
            apply_updates(ns(self.state_path, init=True, project_name="demo",
                             set_halt=self._halt_json(unit="M2: Billing")))
            state, warnings = apply_updates(ns(
                self.state_path, clear_halt="M1: Auth", reason="n/a"))
            self.assertTrue(any("left untouched" in w for w in warnings))
            self.assertEqual(state["halt"]["unit"], "M2: Billing")

        def test_clear_halt_when_absent_is_a_noop_warning(self):
            apply_updates(ns(self.state_path, init=True, project_name="demo"))
            state, warnings = apply_updates(ns(
                self.state_path, clear_halt="M1: Auth", reason="n/a"))
            self.assertTrue(any("nothing to clear" in w for w in warnings))
            self.assertNotIn("halt", state)

        def test_set_halt_then_clear_halt_round_trips_through_main(self):
            import contextlib
            import io

            self.assertEqual(main(["--state", str(self.state_path), "--init",
                                   "--project-name", "demo"]), 0)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = main(["--state", str(self.state_path),
                           "--set-halt", self._halt_json()])
            self.assertEqual(rc, 0)
            self.assertIn("halt", json.loads(buf.getvalue()))
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = main(["--state", str(self.state_path),
                           "--clear-halt", "M1: Auth", "--reason",
                           "admin shell provisioned by IT ticket #123"])
            self.assertEqual(rc, 0)
            self.assertNotIn("halt", json.loads(buf.getvalue()))

        def test_clear_halt_without_reason_is_exit_2_through_main(self):
            import contextlib
            import io

            self.assertEqual(main(["--state", str(self.state_path), "--init",
                                   "--project-name", "demo",
                                   "--set-halt", self._halt_json()]), 0)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = main(["--state", str(self.state_path),
                           "--clear-halt", "M1: Auth"])
            self.assertEqual(rc, 2)
            self.assertIn("error", json.loads(buf.getvalue()))
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = main(["--state", str(self.state_path),
                           "--clear-halt", "M1: Auth", "--reason", "   "])
            self.assertEqual(rc, 2)

        def test_clear_halt_ledger_records_unit_code_and_reason(self):
            ledger = self.dir / "gates.jsonl"
            apply_updates(ns(self.state_path, init=True, project_name="demo",
                             set_halt=self._halt_json()))
            import contextlib
            import io
            with contextlib.redirect_stdout(io.StringIO()):
                rc = main(["--state", str(self.state_path),
                           "--clear-halt", "M1: Auth", "--reason",
                           "admin shell provisioned by IT ticket #123",
                           "--ledger", str(ledger)])
            self.assertEqual(rc, 0)
            rec = self._ledger_records(ledger)[-1]
            self.assertEqual(rec["action"], "clear-halt")
            self.assertEqual(rec["unit"], "M1: Auth")
            self.assertEqual(rec["reason"],
                             "admin shell provisioned by IT ticket #123")
            self.assertEqual(rec["cleared_code"], "halt_environment")
            self.assertEqual(rec["cleared_halt"]["agent"], "quinn")

        def test_clear_halt_mismatch_ledger_carries_no_cleared_code(self):
            """Nothing was actually cleared -- the ledger line says so."""
            ledger = self.dir / "gates.jsonl"
            apply_updates(ns(self.state_path, init=True, project_name="demo",
                             set_halt=self._halt_json(unit="M2: Billing")))
            import contextlib
            import io
            with contextlib.redirect_stdout(io.StringIO()):
                rc = main(["--state", str(self.state_path),
                           "--clear-halt", "M1: Auth", "--reason", "n/a",
                           "--ledger", str(ledger)])
            self.assertEqual(rc, 0)
            rec = self._ledger_records(ledger)[-1]
            self.assertEqual(rec["action"], "clear-halt")
            self.assertNotIn("cleared_code", rec)

        # ---- --set-status (bgpdd-bugfix escalation close) ----------------

        def test_set_status_updates_state_and_stamps_timestamp(self):
            apply_updates(ns(self.state_path, init=True, project_name="demo"))
            state, warnings = apply_updates(ns(self.state_path,
                                              set_status="escalated"))
            self.assertEqual(warnings, [])
            self.assertEqual(state["status"], "escalated")
            self.assertIn("status_updated", state)

        def test_set_status_without_reason_is_allowed(self):
            """--reason is optional with --set-status, unlike --clear-halt."""
            state, warnings = apply_updates(ns(self.state_path, init=True,
                                              project_name="demo",
                                              set_status="closed"))
            self.assertEqual(warnings, [])
            self.assertEqual(state["status"], "closed")

        def test_set_status_invalid_value_exits_2(self):
            """STATUS is validated against a closed set via argparse choices."""
            import contextlib
            import io

            apply_updates(ns(self.state_path, init=True, project_name="demo"))
            with contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as ctx:
                    main(["--state", str(self.state_path),
                          "--set-status", "bogus"])
            self.assertEqual(ctx.exception.code, 2)

        def test_set_status_ledger_omits_previous_status_when_none(self):
            ledger = self.dir / "gates.jsonl"
            apply_updates(ns(self.state_path, init=True, project_name="demo"))
            import contextlib
            import io

            with contextlib.redirect_stdout(io.StringIO()):
                rc = main(["--state", str(self.state_path),
                           "--set-status", "active",
                           "--ledger", str(ledger)])
            self.assertEqual(rc, 0)
            rec = self._ledger_records(ledger)[-1]
            self.assertEqual(rec["action"], "set-status")
            self.assertEqual(rec["status"], "active")
            self.assertNotIn("previous_status", rec)
            self.assertNotIn("reason", rec)

        def test_set_status_ledger_records_reason_and_previous_status(self):
            ledger = self.dir / "gates.jsonl"
            apply_updates(ns(self.state_path, init=True, project_name="demo",
                             set_status="active"))
            import contextlib
            import io

            with contextlib.redirect_stdout(io.StringIO()):
                rc = main(["--state", str(self.state_path),
                           "--set-status", "escalated",
                           "--reason", "blast radius: shared DTO",
                           "--milestone", "fix-null-ptr",
                           "--ledger", str(ledger)])
            self.assertEqual(rc, 0)
            rec = self._ledger_records(ledger)[-1]
            self.assertEqual(rec["action"], "set-status")
            self.assertEqual(rec["status"], "escalated")
            self.assertEqual(rec["reason"], "blast radius: shared DTO")
            self.assertEqual(rec["previous_status"], "active")
            self.assertEqual(rec["milestone"], "fix-null-ptr")

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

        # ---- any lane's tape satisfies it (audit3 Metric 20) ------------

        def test_game_tape_accepts_every_lane_heading(self):
            for lane in ("bgpdd-build", "bgpdd-bugfix", "bgpdd-quick",
                         "bgpdd-lite", "bgpdd-verify", "bgpdd-shipping"):
                self.assertEqual(self._gt_run(self._tape(lane=lane)), 0, lane)

        def test_game_tape_rejects_a_heading_that_names_no_lane(self):
            for lane in ("bgpdd", "build", "pdd-build", "BGPDD-BUILD"):
                self.assertEqual(self._gt_codes(self._tape(lane=lane)),
                                 ["no-section"], lane)

        def test_game_tape_shape_rules_are_identical_for_every_lane(self):
            self.assertEqual(
                self._gt_codes(self._tape(lane="bgpdd-bugfix", bullets=2)),
                ["bullet-count"])
            self.assertEqual(
                self._gt_codes(self._tape(lane="bgpdd-quick", telemetry=False)),
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
