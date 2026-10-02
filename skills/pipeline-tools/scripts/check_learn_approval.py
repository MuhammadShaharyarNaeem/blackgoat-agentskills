#!/usr/bin/env python3
"""Approval and close gate for the bgpdd-learn lane.

`bgpdd-learn` Step 4 says "never apply without explicit approval" and
`agents/forge.md` says Forge never edits a SKILL.md without explicit human
approval. Both were prose, and `bgpdd-learn` was the only lane with no close
gate -- the restraint bites at exactly the moment the Orchestrator most wants
to proceed (convention #9). This script converts it in two modes:

RECORD (`--record`, Step 4, after the user answers the relayed plan). The
approval is read from the SESSION TRANSCRIPT, which the runtime writes -- the
model cannot author a user-role entry. It verifies, in order:

  * the plan (Forge's saved handoff) carries at least one `Destination:`
    line (one lesson, one destination -- bgpdd-learn Step 3);
  * an ASSISTANT text entry relayed every destination to the user
    (`plan_not_relayed` otherwise -- the user cannot approve what they
    were never shown);
  * the FIRST human user entry after that relay contains the `--quote`
    (case- and whitespace-insensitive): `approval_not_found` when no human
    entry follows, `approval_quote_mismatch` when it says something else.
    A runtime-injected `<task-notification>` / `<system-reminder>` entry is
    not a human answer and is skipped.

On PASS it appends a chained record carrying the plan's sha256, the
destinations, the quote, the transcript lines, and a BASELINE: every
already-dirty watched path in each `--repo` with its content hash, so an
unrelated edit that predates the approval is not charged to this run.

CLOSE (`--close`, Step 5, after Forge applies). It refuses unless the
ledger's chain is intact, its latest `record` for `--milestone` PASSed, the
plan file still hashes to what was approved, and every DIRTY watched path in
each `--repo` -- `agents/*.md`, `skills/**/SKILL.md`, a `CLAUDE.md` or
`AGENTS.md` -- is either an approved destination or unchanged since the
baseline. `agents/blackgoat.md` is refused always (CLAUDE.md convention #7),
approved or not. Its PASS record is what closes the learn lane for
`guard_action.py` rule 9.

WATCHED SET, AND WHY IT IS NOT "EVERY FILE". The restraint is about the
rule layers Forge is allowed to write (forge.md's write boundary); the
post-apply guard in bgpdd-learn Step 5 already halts on any path outside
the plugin. Reading the working tree (`git status --porcelain`) rather than
a diff since a sha matches how Forge works: agents never commit.

RUNTIME SCOPE. The transcript reader understands the Claude Code session
JSONL shape. A runtime that keeps no transcript file cannot satisfy
`--record` (exit 2, `transcript_unreadable`): the prose rule stands there,
said plainly rather than replaced by a self-asserted string.

Pure standard library.

Usage:
    check_learn_approval.py --record --plan <forge-handoff.md>
        --transcript <session.jsonl> --quote "<the user's words>"
        [--repo <dir> ...] --milestone <learn-slug> --ledger <gates.jsonl>
    check_learn_approval.py --close --plan <forge-handoff.md>
        [--repo <dir> ...] --milestone <learn-slug> --ledger <gates.jsonl>
    check_learn_approval.py --self-test
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

TIMESTAMP_FMT = "%Y-%m-%dT%H:%M:%SZ"
DESTINATION_RE = re.compile(
    r"^\s*(?:[-*]\s*)?\**destination\**\s*:\s*\**\s*(?P<v>.+?)\s*$",
    re.IGNORECASE)
NOT_HUMAN_PREFIXES = ("<task-notification>", "<system-reminder>")
RULES_FILE_NAMES = ("claude.md", "agents.md")


class GateError(Exception):
    """Structural/usage/environment failure -- maps to exit 2."""


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


class LedgerLock:
    """Exclusive cross-process lock held around ONE ledger append.

    Without it two concurrent appenders read the same last line and both
    write the same `prev`: a chain break nobody forged (and, on Windows, a
    record overwritten). The lock is taken on the ledger file itself, so
    there is no sidecar file and no stale lock to clean up -- the OS drops
    it if the holder dies: `fcntl.flock` on POSIX; on Windows a
    `msvcrt.locking` byte far past EOF (mandatory there, so it sits where
    no read or append ever reaches). Best-effort: a wait longer than
    WAIT_SECONDS, or any lock error, warns on stderr and the append goes
    ahead unlocked: it never raises, never skips its own append and never
    changes an exit code, though an unlocked append may still collide
    with a concurrent one.
    """

    WAIT_SECONDS = 10.0
    POLL_SECONDS = 0.005
    WINDOWS_LOCK_OFFSET = 1 << 62

    def __init__(self, ledger_path):
        self.ledger_path = ledger_path
        self.fh = None

    def _lock_call(self, unlock):
        """One non-blocking lock (or unlock) attempt; OSError when busy."""
        if sys.platform == "win32":
            import msvcrt
            import os
            os.lseek(self.fh.fileno(), self.WINDOWS_LOCK_OFFSET, os.SEEK_SET)
            msvcrt.locking(self.fh.fileno(),
                           msvcrt.LK_UNLCK if unlock else msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(self.fh.fileno(), fcntl.LOCK_UN if unlock
                        else fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _acquired(self):
        """True once locked, False while another holder has it."""
        import errno
        try:
            self._lock_call(unlock=False)
            return True
        except OSError as exc:
            if exc.errno in (errno.EACCES, errno.EAGAIN, errno.EWOULDBLOCK):
                return False
            raise

    def __enter__(self):
        import time
        deadline = time.monotonic() + self.WAIT_SECONDS
        try:
            self.fh = open(self.ledger_path, "ab")
            while not self._acquired():
                if time.monotonic() >= deadline:
                    raise OSError("lock still held after {0}s".format(
                        self.WAIT_SECONDS))
                time.sleep(self.POLL_SECONDS)
        except (OSError, ImportError, ValueError) as exc:
            if self.fh is not None:
                self.fh.close()
                self.fh = None
            print("Warning: appending to ledger {0} without a lock: "
                  "{1}".format(self.ledger_path, exc), file=sys.stderr)
        return self

    def __exit__(self, *exc_info):
        if self.fh is not None:
            try:
                self._lock_call(unlock=True)
            except OSError as exc:
                print("Warning: could not release the lock on ledger "
                      "{0}: {1}".format(self.ledger_path, exc),
                      file=sys.stderr)
            self.fh.close()
            self.fh = None
        return False


def ledger_append(p, record):
    """Chain `record` onto ledger `p` and append it as one line, locked.

    `prev` is read and the line written, closed and so flushed, inside one
    LedgerLock. An OSError from the write itself propagates: each caller
    keeps its own best-effort handling of a failed append.
    """
    with LedgerLock(p):
        record["prev"] = ledger_prev_hash(p)
        record["self"] = ledger_self_hash(record)
        with open(p, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")


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
        "ts": datetime.now(timezone.utc).strftime(TIMESTAMP_FMT),
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
        ledger_append(p, record)
    except OSError as exc:
        print("Warning: could not append to ledger "
              "{0}: {1}".format(ledger_path, exc), file=sys.stderr)


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
        except ValueError:
            continue
        if isinstance(rec, dict):
            records.append(rec)
    return records


def verify_ledger_chain(ledger_path):
    """(ok, detail|None): every chained record's `self` and `prev` verify."""
    p = Path(ledger_path)
    if not p.is_file():
        return True, None
    prev_hash = "genesis"
    chained_seen = False
    for lineno, raw in enumerate(p.read_bytes().splitlines(), start=1):
        if not raw.strip():
            continue
        try:
            rec = json.loads(raw.decode("utf-8-sig", errors="replace"))
        except ValueError:
            return False, "line {0}: not parseable JSON".format(lineno)
        if not isinstance(rec, dict):
            return False, "line {0}: not a JSON object".format(lineno)
        if "prev" not in rec and "self" not in rec:
            if chained_seen:
                return False, "line {0}: unchained after chained".format(lineno)
            prev_hash = ledger_line_hash(raw)
            continue
        if rec.get("self") != ledger_self_hash(rec):
            return False, "line {0}: `self` mismatch (edited)".format(lineno)
        if rec.get("prev") != prev_hash:
            return False, "line {0}: `prev` mismatch".format(lineno)
        chained_seen = True
        prev_hash = ledger_line_hash(raw)
    return True, None


# ---------------------------------------------------------------------------
# Session transcript (shared verbatim with check_handoff.py)
# ---------------------------------------------------------------------------

def collapse_ws(text):
    """`text` with ALL whitespace removed: a runtime may re-wrap a block."""
    return "".join((text or "").split())


def _content_parts(content):
    """[(kind, text, extra)] for one message's content (str or block list)."""
    if isinstance(content, str):
        return [("text", content, {})]
    parts = []
    for block in content if isinstance(content, list) else []:
        if not isinstance(block, dict):
            continue
        kind = block.get("type")
        if kind == "text":
            parts.append(("text", block.get("text") or "", {}))
        elif kind == "tool_use":
            parts.append(("tool_use", "", {"id": block.get("id"),
                                           "name": block.get("name"),
                                           "input": block.get("input") or {}}))
        elif kind == "tool_result":
            inner = block.get("content")
            text = (inner if isinstance(inner, str) else "\n".join(
                b.get("text") or "" for b in inner or []
                if isinstance(b, dict) and b.get("type") == "text"))
            parts.append(("tool_result", text,
                          {"tool_use_id": block.get("tool_use_id")}))
    return parts


def transcript_messages(path):
    """[(line_no, role, kind, text, extra)] from a session-transcript JSONL
    (Claude Code shape: {"type", "message": {"role", "content"}}).
    Sidechain entries are skipped; `extra["meta"]` carries isMeta."""
    try:
        raw = Path(path).read_text(encoding="utf-8-sig", errors="replace")
    except OSError as exc:
        raise GateError(f"cannot read --transcript {path}: {exc}")
    out = []
    for line_no, line in enumerate(raw.splitlines(), start=1):
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if not isinstance(entry, dict) or entry.get("isSidechain"):
            continue
        message = entry.get("message")
        if not isinstance(message, dict):
            continue
        role = message.get("role") or entry.get("type")
        if role not in ("user", "assistant"):
            continue
        for kind, text, extra in _content_parts(message.get("content")):
            extra["meta"] = bool(entry.get("isMeta"))
            out.append((line_no, role, kind, text, extra))
    return out


# ---------------------------------------------------------------------------
# Plan, paths and the working tree
# ---------------------------------------------------------------------------

def parse_destinations(text):
    """Every `Destination:` value in the plan, first backticked token or word."""
    out = []
    for line in (text or "").splitlines():
        m = DESTINATION_RE.match(line)
        if not m:
            continue
        value = m.group("v")
        tick = re.search(r"`([^`]+)`", value)
        token = tick.group(1) if tick else value.split()[0]
        token = token.strip().strip("*").rstrip(".,;:")
        if token and token not in out:
            out.append(token)
    return out


def norm_path(path):
    """Lower-case, forward-slash, `{PLUGIN_ROOT}/` read as `skills/`."""
    p = (path or "").replace("\\", "/").strip().lower()
    p = p.replace("{plugin_root}/", "skills/")
    while p.startswith("./"):
        p = p[2:]
    return p


def destination_matches(rel, destinations):
    """True when repo-relative `rel` is one of the approved destinations."""
    r = norm_path(rel)
    for dest in destinations:
        d = norm_path(dest)
        if d == r or d.endswith("/" + r) or r.endswith("/" + d):
            return True
    return False


def is_watched(rel):
    """agents/*.md, skills/**/SKILL.md, or a project rules file."""
    segs = [s for s in norm_path(rel).split("/") if s]
    if not segs:
        return False
    name = segs[-1]
    if name in RULES_FILE_NAMES:
        return True
    if name == "skill.md" and "skills" in segs[:-1]:
        return True
    return len(segs) >= 2 and segs[-2] == "agents" and name.endswith(".md")


def is_blackgoat(rel):
    return norm_path(rel).endswith("agents/blackgoat.md")


def repo_toplevel(repo):
    proc = subprocess.run(["git", "-C", repo, "rev-parse", "--show-toplevel"],
                          capture_output=True, text=True, timeout=60)
    if proc.returncode != 0:
        raise GateError("--repo {0} is not a git worktree: {1}".format(
            repo, (proc.stderr or proc.stdout).strip()))
    return os.path.normpath(proc.stdout.strip())


def dirty_watched(repo):
    """{key: sha256|None} for every dirty watched path; key = top/rel."""
    top = repo_toplevel(repo)
    proc = subprocess.run(
        ["git", "-C", top, "status", "--porcelain", "-z",
         "--untracked-files=all"],
        capture_output=True, timeout=60)
    if proc.returncode != 0:
        raise GateError("git status failed in {0}".format(top))
    tokens = proc.stdout.decode("utf-8", errors="replace").split("\0")
    out, i = {}, 0
    while i < len(tokens):
        entry = tokens[i]
        i += 1
        if len(entry) < 4:
            continue
        status, rel = entry[:2], entry[3:]
        if status[0] in "RC":
            i += 1  # the rename/copy source path follows
        if is_watched(rel):
            key = Path(top).joinpath(rel).as_posix()
            out[key] = sha256_file(os.path.join(top, rel))
    return out


# ---------------------------------------------------------------------------
# The two modes
# ---------------------------------------------------------------------------

def run_record(args):
    report = {"mode": "record", "plan": args.plan, "plan_sha256": None,
              "destinations": [], "transcript": args.transcript,
              "relay_line": None, "approval_line": None,
              "approval_quote": args.quote, "baseline": {},
              "problems": [], "problem_codes": [], "result": "FAIL",
              "error": None}

    def fail(code, detail):
        report["problems"].append({"code": code, "detail": detail})
        report["problem_codes"].append(code)

    plan_text = Path(args.plan).read_text(encoding="utf-8-sig",
                                          errors="replace")
    report["plan_sha256"] = sha256_file(args.plan)
    dests = parse_destinations(plan_text)
    report["destinations"] = dests
    if not dests:
        fail("plan_has_no_destinations",
             "the plan carries no `Destination:` line -- one lesson, one "
             "destination, listed separately (bgpdd-learn Step 3); send it "
             "back to Forge for the pairing")
        return report

    messages = transcript_messages(args.transcript)
    needles = [collapse_ws(norm_path(d)) for d in dests]
    relay = None
    for line_no, role, kind, text, _e in messages:
        if role == "assistant" and kind == "text":
            hay = collapse_ws(norm_path(text))
            if all(n in hay for n in needles):
                relay = line_no
    if relay is None:
        fail("plan_not_relayed",
             "no assistant message in the transcript names every "
             "destination {0} -- relay the plan to the user before "
             "recording an approval of it".format(dests))
        return report
    report["relay_line"] = relay

    answer_line, answer = None, []
    for line_no, role, kind, text, extra in messages:
        if line_no <= relay or role != "user" or kind != "text":
            continue
        if answer_line is not None and line_no != answer_line:
            break
        if extra.get("meta") or text.lstrip().startswith(NOT_HUMAN_PREFIXES):
            continue
        answer_line = line_no
        answer.append(text)
    if answer_line is None:
        fail("approval_not_found",
             "no human message follows the relay at transcript line {0} -- "
             "halt and wait for the user's answer".format(relay))
        return report
    report["approval_line"] = answer_line
    said = " ".join(" ".join(answer).split()).casefold()
    quote = " ".join(args.quote.split()).casefold()
    if quote not in said:
        fail("approval_quote_mismatch",
             "the user's answer at transcript line {0} does not contain the "
             "quoted approval; they said: {1!r}".format(
                 answer_line, said[:160]))
        return report

    baseline = {}
    for repo in args.repo or ["."]:
        baseline.update(dirty_watched(repo))
    report["baseline"] = baseline
    report["result"] = "PASS"
    return report


def latest_approval(ledger, milestone):
    for rec in reversed(read_ledger(ledger)):
        if (rec.get("gate") == Path(__file__).name
                and rec.get("action") == "record"
                and rec.get("milestone") == milestone):
            return rec
    return None


def run_close(args):
    report = {"mode": "close", "plan": args.plan, "plan_sha256": None,
              "destinations": [], "approval": None, "changed": [],
              "problems": [], "problem_codes": [], "result": "FAIL",
              "error": None}

    def fail(code, detail):
        report["problems"].append({"code": code, "detail": detail})
        report["problem_codes"].append(code)

    ok, detail = verify_ledger_chain(args.ledger)
    if not ok:
        fail("ledger_chain_broken", "{0}: {1}".format(args.ledger, detail))
        return report
    rec = latest_approval(args.ledger, args.milestone)
    if rec is None or rec.get("verdict") != "PASS":
        fail("no_approval_record",
             "no PASS `--record` for milestone {0!r} in {1} -- Forge may not "
             "apply anything the user has not approved".format(
                 args.milestone, args.ledger))
        return report
    report["approval"] = {"approval_line": rec.get("approval_line"),
                          "approval_quote": rec.get("approval_quote")}
    dests = rec.get("destinations") or []
    report["destinations"] = dests
    report["plan_sha256"] = sha256_file(args.plan)
    if report["plan_sha256"] != rec.get("plan_sha256"):
        fail("plan_changed_since_approval",
             "{0} no longer hashes to the plan the user approved".format(
                 args.plan))
    baseline = rec.get("baseline") or {}
    for repo in args.repo or ["."]:
        for key, sha in sorted(dirty_watched(repo).items()):
            if is_blackgoat(key):
                status = "blackgoat"
                fail("blackgoat_touched",
                     "{0} changed -- CLAUDE.md convention #7: no approval "
                     "unlocks it".format(key))
            elif key in baseline and baseline[key] == sha:
                status = "preexisting"
            elif destination_matches(key, dests):
                status = "approved"
            else:
                status = "unapproved"
                fail("unapproved_change",
                     "{0} changed but is no approved destination {1}".format(
                         key, dests))
            report["changed"].append({"path": key, "status": status})
    report["result"] = "FAIL" if report["problems"] else "PASS"
    return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

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


PURPOSE = ("Decides whether a learn-lane plan was approved by the user in the "
           "transcript, and whether only approved destinations changed.")

EPILOG = """\
Reads:
  --plan        Forge's saved handoff. Each lesson carries one line
                  - Destination: `<path>`
                (list marker, bold and backticks optional; {PLUGIN_ROOT}/
                reads as skills/).
  --transcript  (--record) the session JSONL, Claude Code shape, sidechains
    skipped. An assistant text entry must name every destination; the FIRST
    human user entry after it (not isMeta, not a <task-notification> or
    <system-reminder>) must contain --quote, case/whitespace-insensitive.
  --repo        (repeatable, default .) `git status --porcelain` of each
    worktree; watched: agents/*.md, skills/**/SKILL.md, CLAUDE.md,
    AGENTS.md. --record stores them with sha256 as the baseline; --close
    accepts a dirty watched path only if it is an approved destination or
    unchanged since that baseline. agents/blackgoat.md never passes.
  --ledger      required. --close needs an intact chain and the latest
    --record for --milestone to be PASS, over a plan still hashing the same.

Writes:
  --ledger  one chained record per run, every exit path, plus "action"
    (record|close); a record PASS adds destinations, plan_sha256,
    approval_quote, approval_line, relay_line and baseline. A close PASS is
    what disarms guard_action.py rule 9 for this learn root.

Problem codes:
  plan_has_no_destinations     the plan names no Destination: line
  plan_not_relayed             no assistant entry named every destination
  approval_not_found           no human entry follows that relay
  approval_quote_mismatch      the human entry does not contain --quote
  ledger_chain_broken          --close: the ledger chain does not verify
  no_approval_record           --close: no PASS --record for --milestone
  plan_changed_since_approval  --close: the plan's sha256 moved
  unapproved_change            --close: a watched path no plan approved
  blackgoat_touched            --close: agents/blackgoat.md changed

JSON keys:
  record: mode, plan, plan_sha256, destinations, transcript, relay_line,
  approval_line, approval_quote, baseline, problems ([{code, detail}]),
  problem_codes, result, error.
  close: mode, plan, plan_sha256, destinations, approval, changed ([{path,
  status: approved|preexisting|unapproved|blackgoat}]), problems,
  problem_codes, result, error.

Exit codes:
  0  PASS
  1  any problem code
  2  usage (neither or both modes, a missing --plan/--milestone/--ledger,
     --record without --transcript or a non-empty --quote), an unreadable
     plan or transcript (transcript_unreadable), or a --repo that is not a
     git worktree

Self-test:
  python check_learn_approval.py --self-test   (13 cases)
"""


def build_parser():
    parser = PurposeFirstParser(
        prog="check_learn_approval.py",
        description=PURPOSE,
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--record", action="store_true",
                        help="Step 4: verify and record the user's approval")
    parser.add_argument("--close", action="store_true",
                        help="Step 5: verify only approved files changed")
    parser.add_argument("--plan", help="Forge's saved handoff (the plan)")
    parser.add_argument("--transcript", help="session transcript JSONL")
    parser.add_argument("--quote", help="the user's approving words, verbatim")
    parser.add_argument("--repo", action="append", default=None,
                        help="worktree whose watched files are checked")
    parser.add_argument("--milestone", help="the learn slug")
    parser.add_argument("--ledger", help="the learn root's gates.jsonl")
    parser.add_argument("--self-test", action="store_true")
    return parser


def main(argv):
    args = build_parser().parse_args(argv)
    if args.self_test:
        return run_self_test()

    mode = "record" if args.record else "close" if args.close else None

    def finish(code, verdict, report=None):
        extra = {"action": mode}
        if report and verdict == "PASS" and mode == "record":
            for key in ("destinations", "plan_sha256", "approval_quote",
                        "approval_line", "relay_line", "baseline"):
                extra[key] = report[key]
        append_ledger(args.ledger, argv, args.milestone,
                      [p for p in (args.plan, args.transcript) if p],
                      verdict, code, extra)
        return code

    def usage(message):
        print(json.dumps({"result": "ERROR", "error": message}))
        return finish(2, "ERROR")

    if args.record == args.close:
        return usage("pass exactly one of --record or --close")
    missing = [n for n, v in (("--plan", args.plan),
                              ("--milestone", args.milestone),
                              ("--ledger", args.ledger)) if not v]
    if missing:
        return usage("missing required argument(s): " + ", ".join(missing))
    if not Path(args.plan).is_file():
        return usage("--plan names no readable file: " + args.plan)
    if args.record and (not args.transcript
                        or not (args.quote or "").strip()):
        return usage("--record needs --transcript and a non-empty --quote: "
                     "an approval is the user's words, on the runtime's "
                     "record")
    try:
        report = run_record(args) if args.record else run_close(args)
    except GateError as exc:
        code = ("transcript_unreadable" if "--transcript" in str(exc)
                else "error")
        print(json.dumps({"result": "ERROR", "error": str(exc),
                          "code": code}))
        return finish(2, "ERROR")
    print(json.dumps(report, indent=2))
    passed = report["result"] == "PASS"
    return finish(0 if passed else 1, "PASS" if passed else "FAIL", report)


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

def run_self_test():
    import contextlib
    import io
    import shutil
    import tempfile
    import unittest

    PLAN = ("<handoff><status>COMPLETE</status><changed_skills>none"
            "</changed_skills><blockers>None</blockers></handoff>\n\n"
            "1. Rule: re-run the RED before routing.\n"
            "   - Destination: `{PLUGIN_ROOT}/bgpdd-bugfix/SKILL.md`\n"
            "2. Rule: name the model on every delegation.\n"
            "   - **Destination:** agents/quinn.md\n")

    def entry(role, content, **kw):
        e = {"type": role, "message": {"role": role, "content": content}}
        e.update(kw)
        return e

    RELAY = ("Forge proposes:\n1. skills/bgpdd-bugfix/SKILL.md - re-run "
             "the RED\n2. agents/quinn.md - name the model\nApprove?")

    class LearnApprovalTests(unittest.TestCase):
        def setUp(self):
            self.dir = Path(tempfile.mkdtemp())
            self.repo = self.dir / "plugin"
            for rel in ("skills/bgpdd-bugfix/SKILL.md", "agents/quinn.md",
                        "agents/mason.md", "agents/blackgoat.md",
                        "skills/x/SKILL.md", "README.md"):
                p = self.repo / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text("base\n", encoding="utf-8")
            git = ["git", "-C", str(self.repo)]
            for a in (["init", "-q"], ["add", "-A"],
                      ["-c", "user.name=t", "-c", "user.email=t@t", "commit",
                       "-q", "-m", "base"]):
                subprocess.run(git + a, check=True, capture_output=True,
                               timeout=60)
            self.root = self.dir / ".docs" / "learn" / "2026-10-02-x"
            self.root.mkdir(parents=True)
            self.plan = self.root / "forge-handoff.md"
            self.plan.write_text(PLAN, encoding="utf-8")
            self.ledger = self.root / "gates.jsonl"

        def tearDown(self):
            shutil.rmtree(self.dir, ignore_errors=True)

        def transcript(self, *entries):
            p = self.dir / "session.jsonl"
            p.write_text("\n".join(json.dumps(e) for e in entries) + "\n",
                         encoding="utf-8")
            return str(p)

        def run_main(self, *argv):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = main(list(argv))
            out = buf.getvalue()
            try:
                return code, json.loads(out)
            except ValueError:
                return code, out

        def record(self, transcript, quote="yes, apply both"):
            return self.run_main(
                "--record", "--plan", str(self.plan), "--transcript",
                transcript, "--quote", quote, "--repo", str(self.repo),
                "--milestone", "x", "--ledger", str(self.ledger))

        def close(self):
            return self.run_main(
                "--close", "--plan", str(self.plan), "--repo", str(self.repo),
                "--milestone", "x", "--ledger", str(self.ledger))

        def approved(self):
            return self.transcript(
                entry("user", "/bgpdd-learn"),
                entry("assistant", [{"type": "text", "text": RELAY}]),
                entry("user", "<system-reminder>x</system-reminder>",
                      isMeta=True),
                entry("user", "Yes, apply both please."))

        def edit(self, rel, text="changed\n"):
            (self.repo / rel).write_text(text, encoding="utf-8")

        def test_parse_destinations(self):
            self.assertEqual(parse_destinations(PLAN),
                             ["{PLUGIN_ROOT}/bgpdd-bugfix/SKILL.md",
                              "agents/quinn.md"])

        def test_record_then_close_with_approved_edits_passes(self):
            code, r = self.record(self.approved())
            self.assertEqual(code, 0, r)
            self.edit("skills/bgpdd-bugfix/SKILL.md")
            self.edit("agents/quinn.md")
            self.edit("README.md")            # not watched: not this gate's
            code, r = self.close()
            self.assertEqual(code, 0, r)
            self.assertEqual(sorted(c["status"] for c in r["changed"]),
                             ["approved", "approved"])

        def test_unapproved_watched_edit_fails_close(self):
            self.record(self.approved())
            self.edit("agents/mason.md")
            code, r = self.close()
            self.assertEqual(code, 1)
            self.assertEqual(r["problem_codes"], ["unapproved_change"])

        def test_preexisting_dirty_file_is_not_charged(self):
            self.edit("skills/x/SKILL.md", "user's own WIP\n")
            self.record(self.approved())
            code, r = self.close()
            self.assertEqual(code, 0, r)
            self.edit("skills/x/SKILL.md", "then touched during apply\n")
            code, r = self.close()
            self.assertEqual(r["problem_codes"], ["unapproved_change"])

        def test_blackgoat_never_passes(self):
            self.plan.write_text(PLAN + "   - Destination: agents/blackgoat.md\n",
                                 encoding="utf-8")
            self.record(self.transcript(
                entry("assistant", RELAY + " agents/blackgoat.md"),
                entry("user", "yes, apply both")))
            self.edit("agents/blackgoat.md")
            code, r = self.close()
            self.assertEqual(code, 1)
            self.assertIn("blackgoat_touched", r["problem_codes"])

        def test_close_without_record_fails(self):
            code, r = self.close()
            self.assertEqual((code, r["problem_codes"]),
                             (1, ["no_approval_record"]))

        def test_plan_edited_after_approval_fails(self):
            self.record(self.approved())
            self.plan.write_text(PLAN + "   - Destination: agents/mason.md\n",
                                 encoding="utf-8")
            code, r = self.close()
            self.assertIn("plan_changed_since_approval", r["problem_codes"])

        def test_approval_must_be_the_humans_words(self):
            # the model writing "the user approved" is assistant text
            code, r = self.record(self.transcript(
                entry("assistant", RELAY),
                entry("assistant", "The user said: yes, apply both")))
            self.assertEqual((code, r["problem_codes"]),
                             (1, ["approval_not_found"]))
            # a tool result echoing the words is not a human entry either
            code, r = self.record(self.transcript(
                entry("assistant", RELAY),
                entry("user", [{"type": "tool_result", "tool_use_id": "t",
                                "content": "yes, apply both"}])))
            self.assertEqual(r["problem_codes"], ["approval_not_found"])

        def test_answer_that_does_not_approve_fails(self):
            code, r = self.record(self.transcript(
                entry("assistant", RELAY), entry("user", "no, drop #2")))
            self.assertEqual((code, r["problem_codes"]),
                             (1, ["approval_quote_mismatch"]))

        def test_unrelayed_plan_fails(self):
            code, r = self.record(self.transcript(
                entry("assistant", "Forge is done. Approve?"),
                entry("user", "yes, apply both")))
            self.assertEqual(r["problem_codes"], ["plan_not_relayed"])

        def test_plan_without_destinations_fails(self):
            self.plan.write_text("<handoff>x</handoff>\n", encoding="utf-8")
            code, r = self.record(self.approved())
            self.assertEqual((code, r["problem_codes"]),
                             (1, ["plan_has_no_destinations"]))

        def test_transcript_reader_matches_check_handoff(self):
            """collapse_ws .. transcript_messages is one reader, two files."""
            def block(path):
                src = Path(path).read_text(encoding="utf-8", errors="replace")
                start = src.index("def collapse_ws(")
                end = src.index("def transcript_messages(")
                return src[start:src.index(chr(10) * 3, end) + 1]
            sibling = Path(__file__).resolve().parent / "check_handoff.py"
            if not sibling.is_file():
                self.skipTest("check_handoff.py not beside this script")
            self.assertEqual(block(__file__), block(sibling))

        def test_usage_errors_are_exit_2(self):
            self.assertEqual(self.run_main("--plan", str(self.plan))[0], 2)
            self.assertEqual(self.record(str(self.dir / "nope.jsonl"))[0], 2)
            self.assertEqual(self.record(self.approved(), quote=" ")[0], 2)

    suite = unittest.defaultTestLoader.loadTestsFromTestCase(LearnApprovalTests)
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
