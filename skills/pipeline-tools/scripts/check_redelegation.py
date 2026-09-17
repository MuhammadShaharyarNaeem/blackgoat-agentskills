#!/usr/bin/env python3
"""Mechanical gate the Orchestrator runs BEFORE re-delegating an agent that
has already returned on a unit (rounds >= 2).

THE PROBLEM, MEASURED
----------------------
On epic slide-s5, Quinn was delegated four times on Milestone 1 and returned
PARTIAL every time with the same blocker: no admin shell, no installed
Gorelo.Agent service, no dev token. Mason ran three rounds against the same
wall. About 1.2M tokens re-discovered one environment fact that only the
human could change. `orchestrator-contract.md` section 2, Error Recovery,
already says to halt on exactly this: "Fails to complete its objective after
3 consecutive attempts -- ACTION: Halt immediately, output a structured state
summary of what went wrong, and request explicit human intervention." That
rule was not followed under pressure, so per CLAUDE.md convention #9 it
becomes a gate the Orchestrator has to run, not a paragraph it can skip past.

This gate depends on `check_handoff.py`'s Part A addition: whenever
`<status>` is PARTIAL or BLOCKED, `<blockers>` must carry a
`blocked_on: <category> - <one-line reason>` line (category one of
environment/credentials/dependency/spec/defect). That grammar is what makes
"why did this round fail" a value this gate can act on, rather than prose it
would have to re-read.

RULES
-----
0. STANDING HALT (checked FIRST, only when `--state` is given). If
   `state["halt"]` already names this `--unit`, exit 1 immediately with
   THAT halt's own `code` and `reason` -- whatever the new handoff says.
   Rules 1-2 below are not evaluated. Red-team: after `halt_environment` was
   written for (M1, quinn), a PASSING run for (M1, luna) used to clear it --
   wrong twice over. An environment/credentials/dependency blocker is about
   the unit's WORLD, not about which agent's handoff happened to look clean,
   so nothing a delegation does changes it; and for the agent the halt was
   written against, no new handoff can even arrive to "pass" it, since the
   halt is what stops it being re-delegated in the first place. So THIS GATE
   NEVER CLEARS A HALT, for any agent, ever. Clearing is a human act:
   `update_state.py --clear-halt <unit> --reason "<what changed in the
   world>" --ledger <path>` -- `--reason` is required there (exit 2 without
   it), and the ledger records the unit, the cleared code, and the reason.

1. CATEGORY HALTS. Parse the LAST handoff's `<status>` and `<blockers>`. If
   status is PARTIAL/BLOCKED and any `blocked_on:` line names `environment`
   or `credentials`: exit 1, finding `halt_environment` -- that blocker is
   outside the agent's power, and the lane halts for the user rather than
   re-delegating into the same wall. A `dependency` category is exit 1
   `halt_dependency` UNLESS `--allow-redelegation "<reason>"` names what
   changed since (recorded in the ledger line). `spec` and `defect` do not
   halt on their own -- they are the agent's own work to redo, not a wall
   only the user can clear.

2. REPETITION. Read the run log; count prior `delegation` records for this
   exact (`--unit`, `--agent`) pair whose `status` is PARTIAL or BLOCKED.
   Both of the following are INDEPENDENT and MAY BOTH FIRE on one run:
   - ROUND BOUND (always applied, regardless of `--previous-handoff`): >= 3
     such priors is exit 1 `halt_round_bound`. This is the mechanical form
     (convention #9) of orchestrator-contract.md section 2's own bound
     quoted above ("after 3 consecutive attempts... Halt immediately"),
     deliberately tighter than NOTHING (convention #8): no mechanical form of
     that clause existed before this file, which is exactly how slide-s5
     reached a 4th round. Red-team fix: giving `--previous-handoff` must
     never let a 4th round through just because this round's blocker text
     happens to read differently -- the contract's bound is about ATTEMPT
     COUNT, not wording, so it is unconditional.
   - SIMILARITY (only with `--previous-handoff`, layered on top of the round
     bound, not a substitute for it): with `--previous-handoff <file>` given
     AND >= 2 such priors, compare this handoff's `<blockers>` text against
     the previous PARTIAL/BLOCKED handoff's, via a normalised token-set
     (Jaccard) similarity. >= 0.8 is exit 1 `halt_repeated_blocker` -- the
     SAME wall, worded almost the same way, is exactly the pattern that cost
     1.2M tokens on slide-s5, and can trip as early as round 3 (2 priors),
     before the round bound would.

3. Otherwise exit 0, reporting the round number this delegation will be and
   the prior statuses on this (unit, agent) pair.

4. `--state`, when given: on a FRESH halt (rule 1 or 2 above firing for the
   first time -- never on rule 0's standing-halt short-circuit, which
   changes nothing), merges `state["halt"] = {"unit", "agent", "code",
   "reason", "ts"}` via `update_state.py --set-halt` (its own atomic,
   schema-aware write path -- nothing is written raw here) so a future
   `guard_action.py` hook can deny delegation while it stands. On PASS, this
   gate writes nothing and clears nothing -- see rule 0.

5. `--ledger` appends one chained record per run, same shape and helper as
   the rest of this family (`check_handoff.py`, `update_state.py`).

Usage:
    python check_redelegation.py --run-log <path> --unit "<title>" \\
        --agent <name> --handoff <file> \\
        [--previous-handoff <file>] [--state <path>] [--ledger <path>] \\
        [--allow-redelegation "<reason>"]
    python check_redelegation.py --self-test

Exit 0 PASS (delegate), 1 FAIL (halt findings against this re-delegation),
2 ERROR (usage, unreadable input). Pure standard library.
"""
import argparse
import contextlib
import hashlib
import io
import json
import re
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

# --------------------------------------------------------------------------
# Ledger helpers. Byte-identical to check_handoff.py / update_state.py /
# check_blockers.py (family convention: one file each, no shared module).
# --------------------------------------------------------------------------


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


# --------------------------------------------------------------------------
# Handoff parsing: the minimum slice of check_handoff.py's grammar this gate
# needs (<status>, <blockers>, and the blocked_on: lines inside <blockers>).
# Duplicated rather than imported -- same family convention as the ledger
# helpers above. If check_handoff.py's grammar changes, this file's copy is
# the thing agent-audit's interface-alignment heuristic exists to catch.
# --------------------------------------------------------------------------

FENCE_RE = re.compile(r"^[ \t]*(```|~~~).*?^[ \t]*\1[ \t]*$", re.S | re.M)
HANDOFF_RE = re.compile(r"<handoff\s*>(.*?)</handoff\s*>", re.S | re.I)

BLOCKED_ON_CATEGORIES = ("environment", "credentials", "dependency", "spec",
                         "defect")
BLOCKED_ON_RE = re.compile(
    r"(?i)^blocked_on:\s*(?P<category>[A-Za-z_]+)\s*[—–-]\s*"
    r"(?P<reason>\S.*)$")

HALT_STATUSES = ("PARTIAL", "BLOCKED")


def strip_fenced(text):
    """Blank out fenced code blocks, preserving line count (illustration vs
    real handoff -- same reasoning as check_handoff.py's copy)."""
    def blank(match):
        return "\n" * match.group(0).count("\n")
    return FENCE_RE.sub(blank, text)


def extract_handoff_block(text):
    """The LAST well-formed <handoff>...</handoff> block outside a fence, or
    None."""
    stripped = strip_fenced(text)
    blocks = HANDOFF_RE.findall(stripped)
    return blocks[-1] if blocks else None


def extract_element(block, name):
    pattern = re.compile(rf"<{name}\s*>(.*?)</{name}\s*>", re.S | re.I)
    return [m.group(1) for m in pattern.finditer(block)]


def parse_blocked_on_lines(blockers_text):
    """[(category_lower, reason, raw_line)] for every recognized
    `blocked_on:` line, in order. See check_handoff.py's copy of this
    function for the full rationale; kept byte-similar on purpose.
    """
    out = []
    for raw in blockers_text.splitlines():
        line = re.sub(r"^[-*+]\s+", "", raw.strip()).strip()
        line = line.strip("`").strip()
        m = BLOCKED_ON_RE.match(line)
        if m:
            out.append((m.group("category").strip().lower(),
                        m.group("reason").strip(), line))
    return out


def read_handoff(path):
    """(status_or_None, blockers_text) from a handoff file.

    Raises GateError when the file is unreadable or carries no well-formed
    <handoff> block -- check_handoff.py should already have refused such a
    handoff before this gate ever runs.
    """
    p = Path(path)
    if not p.is_file():
        raise GateError(f"handoff file not found: {path}")
    try:
        text = p.read_text(encoding="utf-8-sig", errors="replace")
    except OSError as exc:
        raise GateError(f"cannot read handoff file {path}: {exc}")
    block = extract_handoff_block(text)
    if block is None:
        raise GateError(
            f"no well-formed <handoff>...</handoff> block in {path} outside "
            "fenced code -- check_handoff.py should already have refused "
            "this handoff before check_redelegation.py runs")
    statuses = [v.strip() for v in extract_element(block, "status") if v.strip()]
    status = statuses[0] if statuses else None
    blockers_text = "\n".join(extract_element(block, "blockers"))
    return status, blockers_text


# --------------------------------------------------------------------------
# Run log reading. Minimal duplicate of record_run.py's reader/normalizer.
# --------------------------------------------------------------------------


def read_log(log_path):
    """Every parseable JSON-object line of the run log, in file order. []
    when the file does not exist -- a fresh unit has no prior delegations."""
    p = Path(log_path)
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


def normalize_agent(name):
    if not isinstance(name, str):
        return None
    return name.strip().lower() or None


def prior_delegations(records, unit, agent):
    """Delegation records for this exact (unit, agent) pair, in file order."""
    agent_norm = normalize_agent(agent)
    out = []
    for rec in records:
        if rec.get("event") != "delegation":
            continue
        if rec.get("unit") != unit:
            continue
        if normalize_agent(rec.get("agent")) != agent_norm:
            continue
        out.append(rec)
    return out


# --------------------------------------------------------------------------
# Normalised token-set similarity (rule 2's --previous-handoff path).
# --------------------------------------------------------------------------

TOKEN_RE = re.compile(r"[a-z0-9]+")


def token_set(text):
    return set(TOKEN_RE.findall((text or "").lower()))


def token_set_similarity(a, b):
    """Jaccard similarity of two texts' normalized token sets.

    0.0 when both are empty (nothing in common to claim a match on) rather
    than dividing by zero.
    """
    sa, sb = token_set(a), token_set(b)
    union = sa | sb
    if not union:
        return 0.0
    return len(sa & sb) / len(union)


# --------------------------------------------------------------------------
# The report
# --------------------------------------------------------------------------


def read_state_halt(state_path, unit):
    """The standing `state["halt"]` dict for `unit`, or None.

    None covers every "nothing to enforce" case alike: no `--state`, no
    file, unreadable/malformed JSON, no `halt` key, or a halt naming a
    DIFFERENT unit -- this gate only ever short-circuits on a halt that
    actually names THIS unit. Read-only: this file never writes here (rule
    0 in the module docstring).
    """
    if not state_path:
        return None
    p = Path(state_path)
    if not p.is_file():
        return None
    try:
        state = json.loads(p.read_text(encoding="utf-8-sig", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(state, dict):
        return None
    halt = state.get("halt")
    if isinstance(halt, dict) and halt.get("unit") == unit:
        return halt
    return None


def build_report(run_log, unit, agent, handoff, previous_handoff=None,
                 allow_redelegation=None, state=None):
    status, blockers_text = read_handoff(handoff)

    report = {
        "result": None,
        "unit": unit,
        "agent": agent,
        "handoff": str(handoff),
        "previous_handoff": str(previous_handoff) if previous_handoff else None,
        "status": status,
        "round": None,
        "prior_statuses": [],
        "similarity": None,
        "allow_redelegation": None,
        "standing_halt": None,
        "findings": [],
        "warnings": [],
        "state": None,
        "error": None,
    }

    def finding(code, detail, **extra):
        entry = {"code": code, "detail": detail}
        entry.update(extra)
        report["findings"].append(entry)

    records = read_log(run_log)
    priors = prior_delegations(records, unit, agent)
    report["round"] = len(priors) + 1
    report["prior_statuses"] = [r.get("status") for r in priors]
    prior_halt_statuses = [r for r in priors
                           if (r.get("status") or "").strip().upper() in HALT_STATUSES]

    # --- rule 0: a standing halt short-circuits everything below -----------
    standing = read_state_halt(state, unit)
    if standing is not None:
        report["standing_halt"] = standing
        finding(standing.get("code") or "halt_standing",
                f"{standing.get('reason')} -- a halt already stands for "
                f"{unit!r} (set against {standing.get('agent')!r}, recorded "
                f"{standing.get('ts')}) and this gate never auto-clears it, "
                "regardless of what THIS handoff says: a human clears it, "
                "once the blocker is actually resolved, via `update_state.py "
                f"--clear-halt \"{unit}\" --reason \"<what changed in the "
                "world>\" --ledger <path>`",
                standing=True, original_agent=standing.get("agent"))
        report["result"] = "FAIL"
        return report

    # --- rule 1: category halts -------------------------------------------
    if (status or "").strip().upper() in HALT_STATUSES:
        blocked_on = parse_blocked_on_lines(blockers_text)
        env_hits = [(c, r, l) for c, r, l in blocked_on
                   if c in ("environment", "credentials")]
        if env_hits:
            cat, reason, line = env_hits[0]
            finding("halt_environment",
                    f"blocked_on: {cat} — {reason} -- this blocker is "
                    f"outside {agent}'s power (environment/credentials); the "
                    f"lane halts for the user rather than re-delegating "
                    f"{agent} on {unit!r} again (verbatim: {line!r})",
                    category=cat, reason=reason)
        else:
            dep_hits = [(c, r, l) for c, r, l in blocked_on if c == "dependency"]
            if dep_hits:
                cat, reason, line = dep_hits[0]
                if allow_redelegation and allow_redelegation.strip():
                    report["allow_redelegation"] = allow_redelegation.strip()
                    report["warnings"].append(
                        "DEPENDENCY HALT WAIVED by --allow-redelegation for "
                        f"{unit!r}/{agent}: {allow_redelegation.strip()} "
                        f"(blocked_on: {cat} — {reason})")
                else:
                    finding("halt_dependency",
                            f"blocked_on: {cat} — {reason} -- names another "
                            "team's or milestone's output; re-delegating "
                            "without --allow-redelegation \"<what changed "
                            f"since>\" would just re-discover the same wall "
                            f"(verbatim: {line!r})",
                            category=cat, reason=reason)

    # --- rule 2: repetition -------------------------------------------------
    # Independent checks -- BOTH may fire on one run. The round bound is
    # unconditional (red-team: --previous-handoff must never let a 4th round
    # through just because this round's wording differs -- the contract's
    # bound is about ATTEMPT COUNT); similarity is a finer-grained trip-wire
    # layered on top of it, active only when --previous-handoff is supplied.
    if len(prior_halt_statuses) >= 3:
        finding("halt_round_bound",
                f"{agent} has returned PARTIAL/BLOCKED "
                f"{len(prior_halt_statuses)} times already on {unit!r}. "
                "orchestrator-contract.md section 2, Error Recovery: "
                "'Fails to complete its objective after 3 consecutive "
                "attempts' -> 'ACTION: Halt immediately, output a "
                "structured state summary of what went wrong, and request "
                "explicit human intervention.' This is the mechanical form "
                "of that rule (CLAUDE.md convention #9); deliberately "
                "tighter than nothing, since no mechanical form of this "
                "bound existed before this gate (convention #8)",
                prior_count=len(prior_halt_statuses))

    if previous_handoff and len(prior_halt_statuses) >= 2:
        _, prev_blockers = read_handoff(previous_handoff)
        similarity = token_set_similarity(blockers_text, prev_blockers)
        report["similarity"] = round(similarity, 4)
        if similarity >= 0.8:
            finding("halt_repeated_blocker",
                    f"this handoff's <blockers> text is "
                    f"{similarity:.0%} similar (normalised token-set) to "
                    f"the previous PARTIAL/BLOCKED handoff's for {agent} "
                    f"on {unit!r} -- re-delegating would just "
                    "re-discover the same wall again; escalate instead",
                    similarity=report["similarity"])

    report["result"] = "FAIL" if report["findings"] else "PASS"
    return report


# --------------------------------------------------------------------------
# --state integration: WRITE a fresh halt through update_state.py's OWN
# write path (atomic, schema-aware) -- nothing is written raw here. This
# file never CLEARS a halt (rule 0 above): clearing is a human act through
# `update_state.py --clear-halt ... --reason ...` directly.
# --------------------------------------------------------------------------


def _update_state_module():
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import update_state
    return update_state


def write_state_halt(state_path, halt_payload):
    update_state = _update_state_module()
    buf = io.StringIO()
    argv = ["--state", str(state_path), "--set-halt", json.dumps(halt_payload)]
    with contextlib.redirect_stdout(buf):
        code = update_state.main(argv)
    return code == 0, buf.getvalue()


def apply_state_halt(state_path, unit, agent, report):
    """Write a FRESH halt (report["findings"][0]) to state_path.

    Only ever called for a fresh rule-1/rule-2 FAIL -- never for rule 0's
    standing-halt short-circuit (nothing changed, nothing to write) and
    never on a PASS (this file never clears; see the module docstring's
    rule 0). A write failure (e.g. no state file yet) becomes a warning on
    the report, not an error -- this gate's verdict is rules 0-2, not
    whether --state happened to be writable.
    """
    first = report["findings"][0]
    ok, detail = write_state_halt(
        state_path, {"unit": unit, "agent": agent,
                    "code": first["code"], "reason": first["detail"]})
    if not ok:
        report["warnings"].append(
            f"--state: could not write halt to {state_path}: {detail.strip()}")
    return {"action": "set-halt", "ok": ok}


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


PURPOSE = ("Decides whether re-delegating an agent that already returned on a "
           "unit should halt for the user instead.")

EPILOG = """\
Reads:
  --handoff, --previous-handoff  an agent's <handoff> block. Its <status> is
    COMPLETE / PARTIAL / BLOCKED, and on PARTIAL or BLOCKED its <blockers>
    carries at least one line in check_handoff.py's grammar
      blocked_on: <category> - <reason>
    with <category> one of environment, credentials, dependency, spec, defect
    (em dash, en dash or hyphen). Similarity compares the two handoffs'
    <blockers> as normalised token sets (Jaccard >= 0.8).
  --run-log  the JSONL run log. Prior rounds are the records with
    "event": "delegation" whose "unit" equals --unit exactly and whose "agent"
    matches --agent case-insensitively; a "status" of PARTIAL or BLOCKED
    counts toward the round bound. A missing file means a fresh unit.
  --state  orchestrator-state.json. state["halt"] = {unit, agent, code,
    reason, ts}; a standing halt naming --unit short-circuits this run with
    that halt's own code (rule 0), and a FRESH halt is merged in via
    update_state.py --set-halt. This gate NEVER clears a halt: that is
    update_state.py --clear-halt <unit> --reason "<what changed>".

Problem codes:
  halt_environment       a blocked_on: environment or credentials category
  halt_dependency        a blocked_on: dependency category, unless waived
  halt_round_bound       3 or more prior PARTIAL/BLOCKED rounds, unconditional
  halt_repeated_blocker  2+ priors and blocker similarity >= 0.8

JSON keys:
  result, unit, agent, handoff, previous_handoff, status, round,
  prior_statuses, similarity, allow_redelegation, standing_halt, findings,
  warnings, state, error

Exit codes:
  0  PASS: delegate
  1  a halt finding, fresh or standing
  2  usage, an unreadable handoff, or a blank --allow-redelegation reason

Self-test:
  python check_redelegation.py --self-test   (39 cases)
"""


def main(argv):
    parser = PurposeFirstParser(
        prog="check_redelegation.py",
        description=PURPOSE,
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--run-log", dest="run_log")
    parser.add_argument("--unit")
    parser.add_argument("--agent")
    parser.add_argument("--handoff", help="the agent's LAST handoff file")
    parser.add_argument("--previous-handoff", dest="previous_handoff",
                        help="the previous PARTIAL/BLOCKED handoff for this "
                             "(unit, agent) pair; enables the "
                             "token-similarity repetition check")
    parser.add_argument("--state", help="orchestrator-state.json; a standing "
                                        "halt for --unit short-circuits this "
                                        "run (rule 0), and a fresh halt is "
                                        "merged in on FAIL. Never cleared "
                                        "here -- see update_state.py "
                                        "--clear-halt --reason")
    parser.add_argument("--allow-redelegation", dest="allow_redelegation",
                        help="a written reason for what changed since a "
                             "dependency blocker -- waives halt_dependency "
                             "only, and only that")
    parser.add_argument("--ledger", help="append one JSON record per run to this path")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)

    if args.self_test:
        return run_self_test()

    def finish(code, verdict, extra=None):
        append_ledger(args.ledger, argv, args.unit,
                      [p for p in (args.run_log, args.handoff,
                                  args.previous_handoff) if p],
                      verdict, code, extra)
        return code

    for name, value in (("--run-log", args.run_log), ("--unit", args.unit),
                        ("--agent", args.agent), ("--handoff", args.handoff)):
        if not value:
            print(json.dumps({"result": "ERROR",
                              "error": f"missing required argument: {name}"}))
            return finish(2, "ERROR")

    if args.allow_redelegation is not None and not args.allow_redelegation.strip():
        print(json.dumps({
            "result": "ERROR",
            "error": "--allow-redelegation requires a non-empty reason: an "
                     "unreasoned waiver is indistinguishable from an "
                     "omission, and this is the one waiver that lets a "
                     "dependency blocker be re-delegated against"}))
        return finish(2, "ERROR")

    try:
        report = build_report(args.run_log, args.unit, args.agent, args.handoff,
                              previous_handoff=args.previous_handoff,
                              allow_redelegation=args.allow_redelegation,
                              state=args.state)
    except GateError as exc:
        print(json.dumps({"result": "ERROR", "error": str(exc)}))
        return finish(2, "ERROR")

    # A fresh FAIL (rule 1/2) writes a new halt. A standing-halt
    # short-circuit (rule 0) changes nothing, and a PASS clears nothing --
    # this gate never clears (see the module docstring's rule 0).
    if args.state and report["result"] == "FAIL" and not report.get("standing_halt"):
        report["state"] = apply_state_halt(args.state, args.unit, args.agent,
                                           report)

    extra = {"round": report["round"],
             "findings": [f["code"] for f in report["findings"]]}
    if report.get("allow_redelegation"):
        extra["allow_redelegation"] = report["allow_redelegation"]

    print(json.dumps(report, indent=2))
    return finish(0, "PASS", extra) if report["result"] == "PASS" else finish(1, "FAIL", extra)


def run_self_test():
    class RedelegationTests(unittest.TestCase):
        def setUp(self):
            self.dir = Path(tempfile.mkdtemp())
            self.run_log = self.dir / "run-log.jsonl"

        def tearDown(self):
            import shutil
            shutil.rmtree(self.dir, ignore_errors=True)

        # ---- fixtures ----------------------------------------------------

        def _handoff(self, path, status, blockers):
            (self.dir / path).write_text(
                f"<handoff><status>{status}</status>"
                f"<blockers>{blockers}</blockers></handoff>",
                encoding="utf-8")
            return self.dir / path

        def _log(self, *records):
            with open(self.run_log, "w", encoding="utf-8") as fh:
                for rec in records:
                    fh.write(json.dumps(rec) + "\n")

        def _rec(self, unit="M1", agent="quinn", status="PARTIAL"):
            return {"event": "delegation", "unit": unit, "agent": agent,
                    "status": status}

        def codes(self, report):
            return sorted({f["code"] for f in report["findings"]})

        # ---- round 1 / no history -----------------------------------------

        def test_no_prior_delegations_round_1_passes(self):
            h = self._handoff("h.md", "COMPLETE", "None")
            r = build_report(str(self.run_log), "M1", "quinn", str(h))
            self.assertEqual(r["result"], "PASS")
            self.assertEqual(r["round"], 1)
            self.assertEqual(r["prior_statuses"], [])

        def test_missing_run_log_file_is_round_1(self):
            h = self._handoff("h.md", "COMPLETE", "None")
            r = build_report(str(self.dir / "no-such-log.jsonl"), "M1",
                             "quinn", str(h))
            self.assertEqual(r["result"], "PASS")
            self.assertEqual(r["round"], 1)

        # ---- rule 1: category halts ----------------------------------------

        def test_category_environment_halts(self):
            self._log(self._rec())
            h = self._handoff("h.md", "PARTIAL",
                              "blocked_on: environment — no admin shell")
            r = build_report(str(self.run_log), "M1", "quinn", str(h))
            self.assertEqual(self.codes(r), ["halt_environment"])
            self.assertEqual(r["findings"][0]["category"], "environment")

        def test_category_credentials_also_halts_environment_code(self):
            self._log(self._rec())
            h = self._handoff("h.md", "BLOCKED",
                              "blocked_on: credentials — no dev token")
            r = build_report(str(self.run_log), "M1", "quinn", str(h))
            self.assertEqual(self.codes(r), ["halt_environment"])
            self.assertEqual(r["findings"][0]["category"], "credentials")

        def test_category_dependency_halts_without_allow(self):
            self._log(self._rec())
            h = self._handoff(
                "h.md", "BLOCKED",
                "blocked_on: dependency — waiting on the DB team's migration")
            r = build_report(str(self.run_log), "M1", "quinn", str(h))
            self.assertEqual(self.codes(r), ["halt_dependency"])

        def test_category_dependency_passes_with_allow_redelegation(self):
            self._log(self._rec())
            h = self._handoff(
                "h.md", "BLOCKED",
                "blocked_on: dependency — waiting on the DB team's migration")
            r = build_report(str(self.run_log), "M1", "quinn", str(h),
                             allow_redelegation="DB team shipped the migration "
                                                "this morning, PR #42")
            self.assertEqual(r["result"], "PASS", r["findings"])
            self.assertIn("DB team shipped", r["allow_redelegation"])
            self.assertTrue(any("WAIVED" in w for w in r["warnings"]))

        def test_category_spec_does_not_halt_on_its_own(self):
            self._log(self._rec())
            h = self._handoff("h.md", "PARTIAL",
                              "blocked_on: spec — ambiguous acceptance NFR")
            r = build_report(str(self.run_log), "M1", "quinn", str(h))
            self.assertEqual(r["result"], "PASS", r["findings"])

        def test_category_defect_does_not_halt_on_its_own(self):
            self._log(self._rec())
            h = self._handoff("h.md", "PARTIAL",
                              "blocked_on: defect — flaky integration test")
            r = build_report(str(self.run_log), "M1", "quinn", str(h))
            self.assertEqual(r["result"], "PASS", r["findings"])

        def test_complete_status_never_halts_via_rule_1(self):
            h = self._handoff("h.md", "COMPLETE",
                              "blocked_on: environment — irrelevant, COMPLETE")
            r = build_report(str(self.run_log), "M1", "quinn", str(h))
            self.assertEqual(r["result"], "PASS")

        def test_environment_takes_precedence_over_dependency(self):
            self._log(self._rec())
            h = self._handoff(
                "h.md", "BLOCKED",
                "blocked_on: dependency — waiting on DB team\n"
                "blocked_on: environment — no admin shell too")
            r = build_report(str(self.run_log), "M1", "quinn", str(h))
            self.assertEqual(self.codes(r), ["halt_environment"])

        def test_finding_names_category_and_reason_verbatim(self):
            self._log(self._rec())
            h = self._handoff("h.md", "PARTIAL",
                              "blocked_on: environment — no admin shell")
            r = build_report(str(self.run_log), "M1", "quinn", str(h))
            detail = r["findings"][0]["detail"]
            self.assertIn("environment", detail)
            self.assertIn("no admin shell", detail)

        def test_blocked_on_line_with_bullet_and_backticks_still_parses(self):
            self._log(self._rec())
            h = self._handoff(
                "h.md", "BLOCKED",
                "- `blocked_on: environment — no admin shell`")
            r = build_report(str(self.run_log), "M1", "quinn", str(h))
            self.assertEqual(self.codes(r), ["halt_environment"])

        # ---- allow-redelegation empty reason (CLI-level) -------------------

        def test_allow_redelegation_empty_reason_is_exit_2_via_main(self):
            self._log(self._rec())
            h = self._handoff(
                "h.md", "BLOCKED", "blocked_on: dependency — waiting on team")
            code = main(["--run-log", str(self.run_log), "--unit", "M1",
                        "--agent", "quinn", "--handoff", str(h),
                        "--allow-redelegation", "   "])
            self.assertEqual(code, 2)

        # ---- rule 2: round bound (no --previous-handoff) --------------------

        def test_round_bound_does_not_fire_at_two_prior(self):
            self._log(self._rec(), self._rec())
            h = self._handoff("h.md", "PARTIAL",
                              "blocked_on: spec — different every time")
            r = build_report(str(self.run_log), "M1", "quinn", str(h))
            self.assertEqual(r["result"], "PASS", r["findings"])
            self.assertEqual(r["round"], 3)

        def test_round_bound_fires_at_three_prior(self):
            self._log(self._rec(), self._rec(), self._rec())
            h = self._handoff("h.md", "PARTIAL",
                              "blocked_on: spec — different every time")
            r = build_report(str(self.run_log), "M1", "quinn", str(h))
            self.assertEqual(self.codes(r), ["halt_round_bound"])
            self.assertEqual(r["findings"][0]["prior_count"], 3)
            self.assertIn("3 consecutive attempts", r["findings"][0]["detail"])

        def test_round_bound_counts_only_partial_and_blocked_priors(self):
            self._log(self._rec(status="COMPLETE"), self._rec(), self._rec(),
                      self._rec())
            h = self._handoff("h.md", "PARTIAL",
                              "blocked_on: spec — different every time")
            r = build_report(str(self.run_log), "M1", "quinn", str(h))
            # 3 PARTIAL priors (the COMPLETE one doesn't count) -> fires.
            self.assertEqual(self.codes(r), ["halt_round_bound"])
            self.assertEqual(r["findings"][0]["prior_count"], 3)

        def test_round_bound_scoped_to_unit_and_agent(self):
            self._log(self._rec(unit="M1"), self._rec(unit="M1"),
                      self._rec(unit="M1"), self._rec(unit="M2"),
                      self._rec(agent="mason"), self._rec(agent="mason"),
                      self._rec(agent="mason"))
            h = self._handoff("h.md", "PARTIAL",
                              "blocked_on: spec — different every time")
            r = build_report(str(self.run_log), "M2", "quinn", str(h))
            self.assertEqual(r["result"], "PASS", r["findings"])

        def test_round_bound_agent_match_is_case_insensitive(self):
            self._log(self._rec(agent="Quinn"), self._rec(agent="QUINN"),
                      self._rec(agent="quinn"))
            h = self._handoff("h.md", "PARTIAL",
                              "blocked_on: spec — different every time")
            r = build_report(str(self.run_log), "M1", "quinn", str(h))
            self.assertEqual(self.codes(r), ["halt_round_bound"])

        def test_round_bound_fires_even_with_previous_handoff_given(self):
            """Red-team: the round bound is UNCONDITIONAL. Giving
            --previous-handoff must never let a 4th round through just
            because this round's blocker text reads differently -- the
            contract's bound is about ATTEMPT COUNT, not wording."""
            self._log(self._rec(), self._rec(), self._rec())
            prev = self._handoff("prev.md", "PARTIAL",
                                 "blocked_on: spec — totally unrelated reason")
            h = self._handoff("h.md", "PARTIAL",
                              "blocked_on: defect — something else entirely")
            r = build_report(str(self.run_log), "M1", "quinn", str(h),
                             previous_handoff=str(prev))
            self.assertEqual(self.codes(r), ["halt_round_bound"])
            self.assertLess(r["similarity"], 0.8)  # similarity ran too, just low

        def test_round_bound_and_repeated_blocker_can_both_fire(self):
            """Both rule 2 checks are independent -- both may land in
            `findings` on the same run."""
            self._log(self._rec(), self._rec(), self._rec())
            prev = self._handoff("prev.md", "PARTIAL", self.SAME_ISH_A)
            h = self._handoff("h.md", "PARTIAL", self.SAME_ISH_B)
            r = build_report(str(self.run_log), "M1", "quinn", str(h),
                             previous_handoff=str(prev))
            self.assertEqual(self.codes(r),
                             ["halt_repeated_blocker", "halt_round_bound"])

        # ---- rule 2: repeated-blocker similarity (--previous-handoff) ------

        # `defect` (not environment/credentials/dependency) so rule 1 stays
        # silent and these tests isolate rule 2's similarity path.
        SAME_ISH_A = ("blocked_on: defect — flaky integration test, no "
                      "installed Gorelo Agent stub, retried three times")
        SAME_ISH_B = ("blocked_on: defect — flaky integration test, no "
                      "installed Acme Agent stub, retried three times")
        DIFFERENT = ("blocked_on: spec — the acceptance criteria for "
                    "milestone one conflicts with milestone two contract")

        def test_repeated_blocker_similarity_above_threshold_halts(self):
            self._log(self._rec(), self._rec())
            prev = self._handoff("prev.md", "PARTIAL", self.SAME_ISH_A)
            h = self._handoff("h.md", "PARTIAL", self.SAME_ISH_B)
            r = build_report(str(self.run_log), "M1", "quinn", str(h),
                             previous_handoff=str(prev))
            self.assertEqual(self.codes(r), ["halt_repeated_blocker"])
            self.assertGreaterEqual(r["similarity"], 0.8)

        def test_repeated_blocker_similarity_below_threshold_passes(self):
            self._log(self._rec(), self._rec())
            prev = self._handoff("prev.md", "PARTIAL", self.SAME_ISH_A)
            h = self._handoff("h.md", "PARTIAL", self.DIFFERENT)
            r = build_report(str(self.run_log), "M1", "quinn", str(h),
                             previous_handoff=str(prev))
            self.assertEqual(r["result"], "PASS", r["findings"])
            self.assertLess(r["similarity"], 0.8)

        def test_repeated_blocker_requires_two_prior_halt_statuses(self):
            self._log(self._rec())  # only one prior
            prev = self._handoff("prev.md", "PARTIAL", self.SAME_ISH_A)
            h = self._handoff("h.md", "PARTIAL", self.SAME_ISH_B)
            r = build_report(str(self.run_log), "M1", "quinn", str(h),
                             previous_handoff=str(prev))
            self.assertEqual(r["result"], "PASS", r["findings"])
            self.assertIsNone(r["similarity"])

        def test_similarity_ignores_word_order(self):
            reordered = ("blocked_on: defect — retried three times, no "
                        "installed Gorelo Agent stub, flaky integration test")
            self._log(self._rec(), self._rec())
            prev = self._handoff("prev.md", "PARTIAL", self.SAME_ISH_A)
            h = self._handoff("h.md", "PARTIAL", reordered)
            r = build_report(str(self.run_log), "M1", "quinn", str(h),
                             previous_handoff=str(prev))
            self.assertEqual(r["similarity"], 1.0)

        # ---- round number / prior statuses reporting ------------------------

        def test_round_number_and_prior_statuses_are_reported(self):
            self._log(self._rec(status="PARTIAL"), self._rec(status="BLOCKED"))
            h = self._handoff("h.md", "PARTIAL",
                              "blocked_on: spec — third time")
            r = build_report(str(self.run_log), "M1", "quinn", str(h))
            self.assertEqual(r["round"], 3)
            self.assertEqual(r["prior_statuses"], ["PARTIAL", "BLOCKED"])

        # ---- errors -----------------------------------------------------

        def test_missing_handoff_file_raises(self):
            with self.assertRaises(GateError):
                build_report(str(self.run_log), "M1", "quinn",
                            str(self.dir / "nope.md"))

        def test_handoff_with_no_block_raises(self):
            bad = self.dir / "bad.md"
            bad.write_text("no handoff tags here", encoding="utf-8")
            with self.assertRaises(GateError):
                build_report(str(self.run_log), "M1", "quinn", str(bad))

        def test_missing_required_args_are_exit_2(self):
            h = self._handoff("h.md", "COMPLETE", "None")
            base = ["--run-log", str(self.run_log), "--unit", "M1",
                    "--agent", "quinn", "--handoff", str(h)]
            for i in range(0, 8, 2):
                argv = base[:i] + base[i + 2:]
                self.assertEqual(main(argv), 2, argv)

        # ---- ledger -------------------------------------------------------

        def test_ledger_records_every_exit_path(self):
            ledger = self.dir / "gates.jsonl"
            h_pass = self._handoff("pass.md", "COMPLETE", "None")
            code = main(["--run-log", str(self.run_log), "--unit", "M1",
                        "--agent", "quinn", "--handoff", str(h_pass),
                        "--ledger", str(ledger)])
            self.assertEqual(code, 0)
            self._log(self._rec())
            h_fail = self._handoff(
                "fail.md", "BLOCKED", "blocked_on: environment — no shell")
            code = main(["--run-log", str(self.run_log), "--unit", "M1",
                        "--agent", "quinn", "--handoff", str(h_fail),
                        "--ledger", str(ledger)])
            self.assertEqual(code, 1)
            code = main(["--run-log", str(self.run_log), "--unit", "M1",
                        "--agent", "quinn", "--ledger", str(ledger)])
            self.assertEqual(code, 2)
            records = [json.loads(l) for l in
                      ledger.read_text(encoding="utf-8").splitlines() if l.strip()]
            self.assertEqual([r["verdict"] for r in records],
                             ["PASS", "FAIL", "ERROR"])
            self.assertTrue(all(r["gate"] == "check_redelegation.py"
                               for r in records))
            self.assertEqual(records[1]["findings"], ["halt_environment"])

        def test_ledger_chain_is_valid(self):
            ledger = self.dir / "gates.jsonl"
            h = self._handoff("h.md", "COMPLETE", "None")
            for _ in range(3):
                main(["--run-log", str(self.run_log), "--unit", "M1",
                     "--agent", "quinn", "--handoff", str(h),
                     "--ledger", str(ledger)])
            raw_lines = [l for l in
                        ledger.read_text(encoding="utf-8").splitlines() if l.strip()]
            records = [json.loads(l) for l in raw_lines]
            prev = "genesis"
            for line, rec in zip(raw_lines, records):
                self.assertEqual(rec["prev"], prev)
                self.assertEqual(rec["self"], ledger_self_hash(rec))
                prev = ledger_line_hash(line.encode("utf-8"))

        # ---- --state integration -------------------------------------------

        def _init_state(self):
            update_state = _update_state_module()
            state_path = self.dir / "orchestrator-state.json"
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                update_state.main(["--state", str(state_path), "--init",
                                  "--project-name", "demo",
                                  "--set-pipeline", "bgpdd-build"])
            return state_path

        def test_state_halt_written_on_fail_and_merges_other_keys(self):
            state_path = self._init_state()
            self._log(self._rec())
            h = self._handoff(
                "h.md", "BLOCKED", "blocked_on: environment — no admin shell")
            r = build_report(str(self.run_log), "M1", "quinn", str(h))
            r["state"] = apply_state_halt(str(state_path), "M1", "quinn", r)
            self.assertTrue(r["state"]["ok"])
            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(state["halt"]["unit"], "M1")
            self.assertEqual(state["halt"]["agent"], "quinn")
            self.assertEqual(state["halt"]["code"], "halt_environment")
            self.assertEqual(state["pipeline"], "bgpdd-build")  # untouched

        def test_state_missing_file_is_not_a_standing_halt(self):
            self.assertIsNone(read_state_halt(
                str(self.dir / "no-such-state.json"), "M1"))

        # ---- rule 0: standing halt, never auto-cleared ----------------------

        def test_standing_halt_survives_a_passing_run_by_a_different_agent(self):
            """Red-team: after halt_environment was written for (M1, quinn),
            a PASSING run for (M1, luna) must NOT clear it -- the blocker is
            about the unit's world, not which agent's handoff looked clean."""
            state_path = self._init_state()
            write_state_halt(str(state_path),
                             {"unit": "M1", "agent": "quinn",
                              "code": "halt_environment",
                              "reason": "no admin shell"})
            h = self._handoff("h.md", "COMPLETE", "None")
            r = build_report(str(self.run_log), "M1", "luna", str(h),
                             state=str(state_path))
            self.assertEqual(r["result"], "FAIL")
            self.assertEqual(self.codes(r), ["halt_environment"])
            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(state["halt"]["agent"], "quinn")  # untouched

        def test_gate_rerun_reports_the_standing_halt_regardless_of_new_handoff(self):
            state_path = self._init_state()
            write_state_halt(str(state_path),
                             {"unit": "M1", "agent": "quinn",
                              "code": "halt_dependency",
                              "reason": "waiting on the DB team"})
            # A brand-new COMPLETE handoff -- the standing halt still wins.
            h = self._handoff("h.md", "COMPLETE", "None")
            r = build_report(str(self.run_log), "M1", "quinn", str(h),
                             state=str(state_path))
            self.assertEqual(r["result"], "FAIL")
            self.assertEqual(self.codes(r), ["halt_dependency"])
            self.assertEqual(r["standing_halt"]["reason"],
                             "waiting on the DB team")
            detail = r["findings"][0]["detail"]
            self.assertIn("--clear-halt", detail)
            self.assertIn("--reason", detail)

        def test_standing_halt_short_circuits_rule_1_and_2(self):
            """Even a fresh, DIFFERENT category (or a 3rd-round bound) on the
            new handoff is not separately reported -- rule 0 is exclusive."""
            state_path = self._init_state()
            write_state_halt(str(state_path),
                             {"unit": "M1", "agent": "quinn",
                              "code": "halt_environment", "reason": "no shell"})
            self._log(self._rec(), self._rec(), self._rec())
            h = self._handoff(
                "h.md", "BLOCKED", "blocked_on: dependency — waiting on team")
            r = build_report(str(self.run_log), "M1", "quinn", str(h),
                             state=str(state_path))
            self.assertEqual(self.codes(r), ["halt_environment"])

        def test_pass_with_state_never_writes_or_clears_anything(self):
            """A PASS never touches state, even when a DIFFERENT unit's halt
            stands -- this gate never clears (see module docstring rule 0)."""
            state_path = self._init_state()
            write_state_halt(str(state_path),
                             {"unit": "M2", "agent": "mason",
                              "code": "halt_environment", "reason": "x"})
            h = self._handoff("h.md", "COMPLETE", "None")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = main(["--run-log", str(self.run_log), "--unit", "M1",
                            "--agent", "quinn", "--handoff", str(h),
                            "--state", str(state_path)])
            self.assertEqual(code, 0)
            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(state["halt"]["unit"], "M2")  # untouched

        def test_standing_halt_flows_through_main_and_writes_nothing_new(self):
            state_path = self._init_state()
            write_state_halt(str(state_path),
                             {"unit": "M1", "agent": "quinn",
                              "code": "halt_environment", "reason": "no shell"})
            before = state_path.read_text(encoding="utf-8")
            h = self._handoff("h.md", "COMPLETE", "None")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = main(["--run-log", str(self.run_log), "--unit", "M1",
                            "--agent", "luna", "--handoff", str(h),
                            "--state", str(state_path)])
            self.assertEqual(code, 1)
            data = json.loads(buf.getvalue())
            self.assertEqual(data["standing_halt"]["agent"], "quinn")
            # update_state's own "updated" timestamp is untouched -- this
            # gate never even opened the file for writing.
            after = state_path.read_text(encoding="utf-8")
            self.assertEqual(before, after)

        def test_state_write_failure_is_a_warning_not_a_result_flip(self):
            missing_state = self.dir / "no-such-dir" / "state.json"
            self._log(self._rec())
            h = self._handoff(
                "h.md", "BLOCKED", "blocked_on: environment — no admin shell")
            r = build_report(str(self.run_log), "M1", "quinn", str(h))
            self.assertEqual(r["result"], "FAIL")
            r["state"] = apply_state_halt(str(missing_state), "M1", "quinn", r)
            self.assertFalse(r["state"]["ok"])
            self.assertEqual(r["result"], "FAIL")  # unchanged by the warning
            self.assertTrue(any("--state" in w for w in r["warnings"]))

        def test_state_flows_through_main(self):
            state_path = self._init_state()
            self._log(self._rec())
            h = self._handoff(
                "h.md", "BLOCKED", "blocked_on: environment — no admin shell")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = main(["--run-log", str(self.run_log), "--unit", "M1",
                            "--agent", "quinn", "--handoff", str(h),
                            "--state", str(state_path)])
            self.assertEqual(code, 1)
            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(state["halt"]["code"], "halt_environment")

    suite = unittest.defaultTestLoader.loadTestsFromTestCase(RedelegationTests)
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
