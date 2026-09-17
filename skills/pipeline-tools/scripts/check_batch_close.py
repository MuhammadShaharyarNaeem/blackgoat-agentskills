#!/usr/bin/env python3
"""The `bgpdd-bugfix-batch` Phase 4 close gate.

Converts that lane's prose-only close (a final table, a `git worktree
remove` per bug, and the promise nothing was skipped) into an artifact that
has to be run (CLAUDE.md convention #9). It reads `{batch-root}/orchestrator-
state.json` for the bug list and each bug's recorded status/worktree/root
(`bgpdd-bugfix-batch/SKILL.md` §1, written only through `update_state.py
--set-artifact`), and verifies, for every bug:

  * its status is terminal (`MERGED` or `DROPPED-PLAN` -- an `OPEN` bug, or
    one a rebase HALT left `OPEN`, blocks the close);
  * a `MERGED` bug's OWN ledger (`{bugfix-root}/gates.jsonl`) holds a
    `check_commit_gate.py` record whose latest verdict for that milestone is
    `PASS` and whose `argv` carries `--commit` -- a `DROPPED-PLAN` bug needs
    no commit;
  * its recorded worktree path no longer exists on disk (a `MERGED` bug's
    evidence was committed before the merge, `SKILL.md` Phase 3 step 2(b); a
    `DROPPED-PLAN` bug's evidence was copied out before removal, Phase 2) --
    an `OPEN` bug's worktree is expected to still be there and is not checked;
  * `--batch-md`'s `## Final` table carries a row for it, with a non-
    placeholder commit cell when it is `MERGED`.

It also verifies `{batch-root}/gates.jsonl`'s OWN hash chain
(`verify_ledger_chain`, a byte-identical copy of `check_ledger.py`'s) before
trusting anything already in it, and -- unlike `check_ledger.py`, which is
deliberately read-only (`pipeline-tools/SKILL.md`: "the subject under test,
not an append target") -- appends its OWN chained record to `--ledger` on
every exit path, exactly like every other gate in this family. That append is
this file's whole reason to exist: `{batch-root}/gates.jsonl` was claimed as
a batch-layer record with no script that ever wrote to it.

It does not touch git, commit anything, or remove a worktree -- Phase 4 steps
1-2 do that by hand, and this gate only verifies what they left behind.

Usage:
    python check_batch_close.py --state <path> --batch-md <path> \
        --repo <dir> --milestone "<batch-slug>" [--ledger <path>]
    python check_batch_close.py --self-test

Exit codes:
    0  every bug terminal, every worktree gone, the chain intact, the table
       matches -- PASS
    1  any of the above failed -- FAIL, `problem_codes` names every one
    2  usage error, unreadable state, or no `artifacts["bugs"]` list to check

Pure standard library. See ../SKILL.md for the family contract; this
script's own contract sentence lives in `bgpdd-bugfix-batch/SKILL.md` Phase 4
step 3 (owned by that skill, not restated here).
"""
import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

READ_ENCODING = "utf-8-sig"
TERMINAL_STATUSES = ("MERGED", "DROPPED-PLAN")

PLACEHOLDER_VALUE_RE = re.compile(
    r"^(?:<[^>]*>|todo|tbd|fixme|n/?a|none|unknown|\?+|\.{3,}|xxx+|-{1,3}|\u2014|\u2013)?$",
    re.IGNORECASE)
FINAL_HEADING_RE = re.compile(r"^##\s*Final\s*$", re.IGNORECASE)
ANY_HEADING_RE = re.compile(r"^#{1,6}\s")
TABLE_ROW_RE = re.compile(r"^\s*\|(.+)\|\s*$")
SEP_ROW_RE = re.compile(r"^\s*\|?[\s:\-]+\|[\s:\-|]*$")


# ---------------------------------------------------------------------------
# Ledger chain: byte-identical copy of check_handoff.py's (family convention:
# one file each, no shared module -- check_ledger.py's own self-test asserts
# this block is identical everywhere it appears).
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


def verify_ledger_chain(ledger_path):
    """(ok, problem|None) -- walk the chain, stop at the FIRST broken link.

    A missing ledger file is NOT a break (there is no chain to break).
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
                    "detail": "an unchained record follows a chained one"}
            prev_hash = ledger_line_hash(raw)
            continue
        if not (has_prev and has_self):
            return False, {
                "line": lineno, "reason": "incomplete-chain-fields",
                "detail": "record carries only one of `prev`/`self`"}
        if rec.get("self") != ledger_self_hash(rec):
            return False, {
                "line": lineno, "reason": "self-mismatch",
                "detail": "`self` does not hash this record's own content"}
        if rec.get("prev") != prev_hash:
            return False, {
                "line": lineno, "reason": "prev-mismatch",
                "detail": "`prev` does not match the preceding record"}
        chained_seen = True
        prev_hash = ledger_line_hash(raw)
    return True, None


def read_ledger_records(path):
    """Every parseable JSON-object line of a ledger, in file order."""
    p = Path(path)
    if not p.is_file():
        return []
    records = []
    for line in p.read_text(encoding=READ_ENCODING, errors="replace").splitlines():
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


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding=READ_ENCODING))
    except (OSError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Batch state
# ---------------------------------------------------------------------------

def parse_bugs(state):
    """The `artifacts["bugs"]` comma-list, or [] when absent/blank."""
    artifacts = state.get("artifacts") if isinstance(state, dict) else None
    if not isinstance(artifacts, dict):
        return []
    raw = artifacts.get("bugs")
    if not isinstance(raw, str) or not raw.strip():
        return []
    return [s.strip() for s in raw.split(",") if s.strip()]


def bug_commit_gate_pass(bugfix_root, slug):
    """(ok, detail|None) -- does that bug's OWN ledger hold a committed PASS?

    Reads `{bugfix_root}/gates.jsonl`: its chain must be intact, and the
    latest `check_commit_gate.py` entry scoped to `slug` (or unscoped) must
    carry verdict PASS and `--commit` in its argv -- the same scoping
    `pipeline_driver.py`'s `gate_state()` uses, a minimal copy per family
    convention (one file each, no shared module).
    """
    ledger = Path(bugfix_root) / "gates.jsonl"
    ok, problem = verify_ledger_chain(str(ledger))
    if not ok:
        detail = problem["detail"] if problem else "unknown break"
        return False, "that bug's own ledger chain is broken: {0}".format(detail)
    candidates = [r for r in read_ledger_records(ledger)
                  if r.get("gate") == "check_commit_gate.py"
                  and (r.get("milestone") is None or r.get("milestone") == slug)]
    if not candidates:
        return False, ("no check_commit_gate.py entry in {0} scoped to {1!r} "
                       "(or unscoped)".format(ledger, slug))
    latest = candidates[-1]
    if latest.get("verdict") != "PASS":
        return False, ("the latest check_commit_gate.py entry for {0} records "
                       "verdict {1!r}, not PASS".format(slug, latest.get("verdict")))
    argv = [str(a) for a in (latest.get("argv") or [])]
    if "--commit" not in argv:
        return False, ("the latest check_commit_gate.py PASS for {0} carries "
                       "no --commit -- that was a dry run".format(slug))
    return True, None


def parse_final_table(text):
    """{slug: commit-cell-text} from the `## Final` section, or None.

    None means no `## Final` heading at all. A present-but-empty table (no
    data rows) is `{}`, which then fails every bug as `final_table_row_missing`
    -- the honest reading of a table nobody filled in.
    """
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if FINAL_HEADING_RE.match(line.strip()):
            start = i
            break
    if start is None:
        return None
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if ANY_HEADING_RE.match(lines[j]):
            end = j
            break
    rows = [l for l in lines[start + 1:end] if TABLE_ROW_RE.match(l)]
    if not rows:
        return {}
    header_cells = [c.strip().lower()
                    for c in rows[0].strip().strip("|").split("|")]
    slug_idx = next((i for i, c in enumerate(header_cells) if "slug" in c), None)
    commit_idx = next((i for i, c in enumerate(header_cells) if "commit" in c), None)
    data = {}
    for row in rows[1:]:
        if SEP_ROW_RE.match(row):
            continue
        cells = [c.strip() for c in row.strip().strip("|").split("|")]
        if slug_idx is None or slug_idx >= len(cells):
            continue
        slug = cells[slug_idx].strip("`").strip()
        if not slug:
            continue
        commit = (cells[commit_idx].strip()
                 if commit_idx is not None and commit_idx < len(cells) else "")
        data[slug] = commit
    return data


def build_report(args):
    out = {
        "state": args.state, "batch_md": args.batch_md, "repo": args.repo,
        "milestone": args.milestone, "ledger": args.ledger,
        "bugs": [], "ledger_chain_ok": None, "final_table_present": None,
        "problems": [], "problem_codes": [], "result": None, "error": None,
    }
    if not args.state or not args.batch_md or not args.repo:
        out["error"] = ("--state, --batch-md and --repo are all required")
        return out, 2

    state = read_json(args.state)
    if not isinstance(state, dict):
        out["error"] = "state file not found or not valid JSON: {0}".format(args.state)
        return out, 2

    bugs = parse_bugs(state)
    if not bugs:
        out["error"] = ("state carries no artifacts['bugs'] list -- nothing to "
                        "close (Phase 0 must set it with update_state.py "
                        "--set-artifact \"bugs=...\")")
        return out, 2

    artifacts = state.get("artifacts") or {}
    repo = Path(args.repo)

    chain_ok, chain_problem = (True, None)
    if args.ledger:
        chain_ok, chain_problem = verify_ledger_chain(args.ledger)
    out["ledger_chain_ok"] = chain_ok
    if not chain_ok:
        detail = chain_problem["detail"] if chain_problem else "unknown break"
        out["problems"].append("batch_ledger_chain_broken: {0}".format(detail))
        out["problem_codes"].append("batch_ledger_chain_broken")

    final_table = None
    batch_md_path = Path(args.batch_md)
    if not batch_md_path.is_file():
        out["final_table_present"] = False
        out["problems"].append("batch_md_missing: no batch note at {0}"
                               .format(args.batch_md))
        out["problem_codes"].append("batch_md_missing")
    else:
        text = batch_md_path.read_text(encoding=READ_ENCODING, errors="replace")
        final_table = parse_final_table(text)
        out["final_table_present"] = final_table is not None
        if final_table is None:
            out["problems"].append("final_table_missing: {0} carries no "
                                   "'## Final' section".format(args.batch_md))
            out["problem_codes"].append("final_table_missing")

    for slug in bugs:
        status = artifacts.get("bug:{0}:status".format(slug))
        worktree = artifacts.get("bug:{0}:worktree".format(slug))
        root = artifacts.get("bug:{0}:root".format(slug))
        entry = {"slug": slug, "status": status, "worktree": worktree,
                 "root": root, "problems": []}

        def flag(code, detail):
            entry["problems"].append(code)
            out["problems"].append("{0}: {1}".format(code, detail))
            out["problem_codes"].append(code)

        if status not in TERMINAL_STATUSES:
            flag("bug_open", "{0} is not terminal (status={1!r}); every bug "
                             "must be MERGED or DROPPED-PLAN before the batch "
                             "closes".format(slug, status))
        else:
            if not worktree:
                flag("worktree_unknown",
                    "no recorded worktree path for {0} (bug:{0}:worktree was "
                    "never set)".format(slug))
            elif Path(worktree).exists():
                flag("worktree_not_removed",
                    "{0} still exists for {1} -- git worktree remove has not "
                    "run".format(worktree, slug))

            if status == "MERGED":
                bugfix_root = root or str(repo / ".docs" / "bugfix" / slug)
                ok, detail = bug_commit_gate_pass(bugfix_root, slug)
                if not ok:
                    flag("bug_not_committed", "{0} -- {1}".format(slug, detail))

        if final_table is not None:
            if slug not in final_table:
                flag("final_table_row_missing",
                    "{0} has no row in {1}'s '## Final' table"
                    .format(slug, args.batch_md))
            elif status == "MERGED" and PLACEHOLDER_VALUE_RE.match(
                    final_table[slug].strip("`").strip()):
                flag("final_table_commit_missing",
                    "{0}'s Final row names no commit sha".format(slug))

        out["bugs"].append(entry)

    out["result"] = "PASS" if not out["problems"] else "FAIL"
    return out, (0 if out["result"] == "PASS" else 1)


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


PURPOSE = ("The bgpdd-bugfix-batch Phase 4 close gate: every bug terminal, "
           "committed, its worktree gone, and named in the Final table.")

EPILOG = """\
Reads:
  --state <path>     {batch-root}/orchestrator-state.json. The bugs list and
    each bug's record are artifacts written only through
    `update_state.py --set-artifact`:
      artifacts["bugs"]                 comma-separated slugs
      artifacts["bug:<slug>:status"]    MERGED | DROPPED-PLAN | OPEN | ...
      artifacts["bug:<slug>:worktree"]  the worktree path
      artifacts["bug:<slug>:root"]      that bug's {bugfix-root}
  --batch-md <path>  the batch's batch.md. Its `## Final` section must carry
    a markdown table with one row per bug; the commit cell of a MERGED bug's
    row must be a real sha, not a placeholder:
      ## Final

      | # | Slug | Commit | Gate record |
      |---|---|---|---|
      | 1 | null-coupon-500 | 9f2c1ab | check_commit_gate.py PASS |
  Each MERGED bug's OWN ledger, {bugfix-root}/gates.jsonl: its latest
    check_commit_gate.py verdict for that milestone must be PASS with
    --commit in its argv.
  --repo <dir>       required; used ONLY to guess a MERGED bug's
    {bugfix-root} when its state carries no bug:<slug>:root artifact.
  --milestone        the batch slug, recorded on the ledger line.
  --ledger <path>    the append target AND, unlike every other reader here,
    the file whose own hash chain is verified before anything in it is
    trusted. This gate is the sole writer of {batch-root}/gates.jsonl.

  A bug's worktree is checked only when its status is terminal: an OPEN
  bug's worktree is expected to still exist. This gate never touches git,
  commits anything, or removes a worktree.

Problem codes:
  batch_ledger_chain_broken   the batch's own ledger chain is broken
  batch_md_missing            no batch.md at --batch-md
  final_table_missing         no `## Final` section in batch.md
  bug_open                    a bug is not MERGED or DROPPED-PLAN
  worktree_unknown            no recorded worktree path for the bug
  worktree_not_removed        the recorded worktree still exists on disk
  bug_not_committed           no scoped check_commit_gate.py PASS --commit
  final_table_row_missing     no Final-table row for the bug
  final_table_commit_missing  a MERGED bug's row names no commit sha

JSON keys:
  Always printed on stdout (there is no --json flag):
  state, batch_md, repo, milestone, ledger,
  bugs ([{slug, status, worktree, root, problems}]),
  ledger_chain_ok, final_table_present, problems, problem_codes,
  result, error

Exit codes:
  0  every bug terminal, every worktree gone, the batch's own ledger chain
     intact, and the Final table matches -- PASS.
  1  any of the above failed -- FAIL, every failing term in problem_codes.
  2  usage error (--state, --batch-md and --repo are all required), an
     unreadable or non-JSON state file, or a state file carrying no
     artifacts["bugs"] list to check.

Self-test:
  python check_batch_close.py --self-test   (18 cases)
"""


def build_parser():
    parser = PurposeFirstParser(
        prog="check_batch_close.py",
        description=PURPOSE,
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--state", help="the batch's orchestrator-state.json")
    parser.add_argument("--batch-md", help="the batch's batch.md")
    parser.add_argument("--repo", default=".",
                        help="the target repo root; used only to guess a "
                             "MERGED bug's {bugfix-root} when its state "
                             "carries no bug:<slug>:root artifact")
    parser.add_argument("--milestone", help="the batch slug, recorded on "
                                            "the ledger line")
    parser.add_argument("--ledger", help="append one JSON record per run to "
                                         "this path; also the file whose own "
                                         "chain is verified before trusting it")
    parser.add_argument("--self-test", action="store_true")
    return parser


def main(argv):
    args = build_parser().parse_args(argv)
    if args.self_test:
        return run_self_test()

    out, code = build_report(args)
    verdict = "ERROR" if code == 2 else out.get("result") or "ERROR"
    print(json.dumps(out, indent=2))
    inputs = [p for p in (args.state, args.batch_md) if p]
    append_ledger(args.ledger, argv, args.milestone, inputs, verdict, code)
    return code


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

def run_self_test():
    import shutil
    import tempfile
    import unittest

    def chained(ledger, gate, verdict="PASS", exit_code=0, milestone="s",
               argv=None):
        record = {"ts": "2026-09-08T00:00:00Z", "gate": gate,
                  "argv": argv if argv is not None else [], "milestone": milestone,
                  "inputs": {}, "verdict": verdict, "exit": exit_code}
        record["prev"] = ledger_prev_hash(ledger)
        record["self"] = ledger_self_hash(record)
        Path(ledger).parent.mkdir(parents=True, exist_ok=True)
        with open(ledger, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")

    FINAL_TABLE = (
        "# Bug batch: 2026-09-08-triage\n\n"
        "## Final\n\n"
        "| # | Slug | Commit | Gate record |\n"
        "|---|---|---|---|\n"
        "| 1 | null-coupon-500 | 9f2c1ab | check_commit_gate.py PASS |\n"
        "| 2 | cart-badge-stale | \u2014 | dropped to /bgpdd-plan |\n")

    class Base(unittest.TestCase):
        def setUp(self):
            self.dir = Path(tempfile.mkdtemp())
            self.repo = self.dir / "repo"
            self.batch_root = self.repo / ".docs" / "bugfix-batch" / "2026-09-08-triage"
            self.batch_root.mkdir(parents=True)
            self.state_path = self.batch_root / "orchestrator-state.json"
            self.batch_md = self.batch_root / "batch.md"
            self.ledger = self.batch_root / "gates.jsonl"

        def tearDown(self):
            shutil.rmtree(self.dir, ignore_errors=True)

        def bugfix_root(self, slug):
            return self.repo / ".docs" / "bugfix" / slug

        def stage_bug(self, slug, status, worktree_exists=True, committed=True):
            root = self.bugfix_root(slug)
            root.mkdir(parents=True, exist_ok=True)
            worktree = self.dir / "wt" / slug
            if worktree_exists:
                worktree.mkdir(parents=True, exist_ok=True)
            if status == "MERGED" and committed:
                chained(root / "gates.jsonl", "check_commit_gate.py",
                       milestone=slug, argv=["--commit", "--message", "m"])
            return str(root), str(worktree)

        def write_state(self, bugs, extra_artifacts=None):
            artifacts = {"bugs": ",".join(bugs)}
            if extra_artifacts:
                artifacts.update(extra_artifacts)
            state = {"schema": "1", "project_name": "2026-09-08-triage",
                     "feature": None, "pipeline": "bgpdd-bugfix-batch",
                     "branch": None, "milestone_cursor": None,
                     "artifacts": artifacts, "blockers": []}
            self.state_path.write_text(json.dumps(state), encoding="utf-8")

        def run_gate(self):
            ns = argparse.Namespace(
                state=str(self.state_path), batch_md=str(self.batch_md),
                repo=str(self.repo), milestone="2026-09-08-triage",
                ledger=str(self.ledger))
            return build_report(ns)

    class HappyPath(Base):
        def test_two_terminal_bugs_pass(self):
            root1, wt1 = self.stage_bug("null-coupon-500", "MERGED",
                                        worktree_exists=False)
            root2, wt2 = self.stage_bug("cart-badge-stale", "DROPPED-PLAN",
                                        worktree_exists=False)
            self.write_state(
                ["null-coupon-500", "cart-badge-stale"],
                {"bug:null-coupon-500:status": "MERGED",
                 "bug:null-coupon-500:worktree": wt1,
                 "bug:null-coupon-500:root": root1,
                 "bug:cart-badge-stale:status": "DROPPED-PLAN",
                 "bug:cart-badge-stale:worktree": wt2,
                 "bug:cart-badge-stale:root": root2})
            self.batch_md.write_text(FINAL_TABLE, encoding="utf-8")
            out, code = self.run_gate()
            self.assertEqual(code, 0, out)
            self.assertEqual(out["result"], "PASS")
            self.assertEqual(out["problems"], [])

        def test_main_end_to_end_appends_ledger_record(self):
            import contextlib
            import io
            root1, wt1 = self.stage_bug("null-coupon-500", "MERGED",
                                        worktree_exists=False)
            self.write_state(
                ["null-coupon-500"],
                {"bug:null-coupon-500:status": "MERGED",
                 "bug:null-coupon-500:worktree": wt1,
                 "bug:null-coupon-500:root": root1})
            self.batch_md.write_text(
                "## Final\n\n| Slug | Commit |\n|---|---|\n"
                "| null-coupon-500 | 9f2c1ab |\n", encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                rc = main(["--state", str(self.state_path),
                          "--batch-md", str(self.batch_md),
                          "--repo", str(self.repo),
                          "--milestone", "2026-09-08-triage",
                          "--ledger", str(self.ledger)])
            self.assertEqual(rc, 0)
            records = read_ledger_records(self.ledger)
            self.assertEqual(records[-1]["gate"], "check_batch_close.py")
            self.assertEqual(records[-1]["verdict"], "PASS")
            self.assertIn("self", records[-1])
            self.assertIn("prev", records[-1])

    class FailClosedCases(Base):
        """The three cases the brief names, each proven to fail closed."""

        def test_an_open_bug_blocks_at_exit_1(self):
            root1, wt1 = self.stage_bug("still-open-bug", "OPEN")
            self.write_state(
                ["still-open-bug"],
                {"bug:still-open-bug:status": "OPEN",
                 "bug:still-open-bug:worktree": wt1,
                 "bug:still-open-bug:root": root1})
            self.batch_md.write_text(
                "## Final\n\n| Slug | Commit |\n|---|---|\n", encoding="utf-8")
            out, code = self.run_gate()
            self.assertEqual(code, 1)
            self.assertIn("bug_open", out["problem_codes"])

        def test_a_leftover_worktree_blocks_at_exit_1(self):
            root1, wt1 = self.stage_bug("merged-but-wt-stays", "MERGED",
                                        worktree_exists=True)
            self.write_state(
                ["merged-but-wt-stays"],
                {"bug:merged-but-wt-stays:status": "MERGED",
                 "bug:merged-but-wt-stays:worktree": wt1,
                 "bug:merged-but-wt-stays:root": root1})
            self.batch_md.write_text(
                "## Final\n\n| Slug | Commit |\n|---|---|\n"
                "| merged-but-wt-stays | abc1234 |\n", encoding="utf-8")
            out, code = self.run_gate()
            self.assertEqual(code, 1)
            self.assertIn("worktree_not_removed", out["problem_codes"])

        def test_a_broken_batch_ledger_chain_blocks_at_exit_1(self):
            root1, wt1 = self.stage_bug("clean-bug", "MERGED",
                                        worktree_exists=False)
            self.write_state(
                ["clean-bug"],
                {"bug:clean-bug:status": "MERGED",
                 "bug:clean-bug:worktree": wt1,
                 "bug:clean-bug:root": root1})
            self.batch_md.write_text(
                "## Final\n\n| Slug | Commit |\n|---|---|\n"
                "| clean-bug | abc1234 |\n", encoding="utf-8")
            chained(self.ledger, "check_batch_close.py")
            # Tamper with the one record on disk -- self-hash now disagrees.
            lines = self.ledger.read_text(encoding="utf-8").splitlines()
            rec = json.loads(lines[0])
            rec["verdict"] = "FAIL"
            self.ledger.write_text(json.dumps(rec) + "\n", encoding="utf-8")
            out, code = self.run_gate()
            self.assertEqual(code, 1)
            self.assertIn("batch_ledger_chain_broken", out["problem_codes"])

        # -- the honest-input side of each of the three cases --------------

        def test_the_same_bug_once_merged_and_committed_clears_bug_open(self):
            root1, wt1 = self.stage_bug("now-fixed", "MERGED",
                                        worktree_exists=False)
            self.write_state(
                ["now-fixed"],
                {"bug:now-fixed:status": "MERGED",
                 "bug:now-fixed:worktree": wt1,
                 "bug:now-fixed:root": root1})
            self.batch_md.write_text(
                "## Final\n\n| Slug | Commit |\n|---|---|\n"
                "| now-fixed | abc1234 |\n", encoding="utf-8")
            out, code = self.run_gate()
            self.assertEqual(code, 0, out)
            self.assertNotIn("bug_open", out["problem_codes"])

        def test_the_same_bug_once_worktree_removed_clears_the_flag(self):
            root1, wt1 = self.stage_bug("wt-gone", "MERGED",
                                        worktree_exists=False)
            self.write_state(
                ["wt-gone"],
                {"bug:wt-gone:status": "MERGED",
                 "bug:wt-gone:worktree": wt1,
                 "bug:wt-gone:root": root1})
            self.batch_md.write_text(
                "## Final\n\n| Slug | Commit |\n|---|---|\n"
                "| wt-gone | abc1234 |\n", encoding="utf-8")
            out, code = self.run_gate()
            self.assertEqual(code, 0, out)
            self.assertNotIn("worktree_not_removed", out["problem_codes"])

        def test_an_intact_chain_clears_the_flag(self):
            root1, wt1 = self.stage_bug("intact", "MERGED",
                                        worktree_exists=False)
            self.write_state(
                ["intact"],
                {"bug:intact:status": "MERGED",
                 "bug:intact:worktree": wt1,
                 "bug:intact:root": root1})
            self.batch_md.write_text(
                "## Final\n\n| Slug | Commit |\n|---|---|\n"
                "| intact | abc1234 |\n", encoding="utf-8")
            chained(self.ledger, "check_batch_close.py")
            out, code = self.run_gate()
            self.assertEqual(code, 0, out)
            self.assertNotIn("batch_ledger_chain_broken", out["problem_codes"])

    class OtherProblems(Base):
        def test_merged_without_commit_gate_pass_fails(self):
            root1, wt1 = self.stage_bug("uncommitted", "MERGED",
                                        worktree_exists=False, committed=False)
            self.write_state(
                ["uncommitted"],
                {"bug:uncommitted:status": "MERGED",
                 "bug:uncommitted:worktree": wt1,
                 "bug:uncommitted:root": root1})
            self.batch_md.write_text(
                "## Final\n\n| Slug | Commit |\n|---|---|\n"
                "| uncommitted | abc1234 |\n", encoding="utf-8")
            out, code = self.run_gate()
            self.assertEqual(code, 1)
            self.assertIn("bug_not_committed", out["problem_codes"])

        def test_dropped_plan_needs_no_commit_gate(self):
            root1, wt1 = self.stage_bug("dropped", "DROPPED-PLAN",
                                        worktree_exists=False)
            self.write_state(
                ["dropped"],
                {"bug:dropped:status": "DROPPED-PLAN",
                 "bug:dropped:worktree": wt1,
                 "bug:dropped:root": root1})
            self.batch_md.write_text(
                "## Final\n\n| Slug | Commit |\n|---|---|\n"
                "| dropped | \u2014 |\n", encoding="utf-8")
            out, code = self.run_gate()
            self.assertEqual(code, 0, out)

        def test_missing_final_table_fails(self):
            root1, wt1 = self.stage_bug("no-table", "MERGED",
                                        worktree_exists=False)
            self.write_state(
                ["no-table"],
                {"bug:no-table:status": "MERGED",
                 "bug:no-table:worktree": wt1,
                 "bug:no-table:root": root1})
            self.batch_md.write_text("# Bug batch\n\nno final section\n",
                                     encoding="utf-8")
            out, code = self.run_gate()
            self.assertEqual(code, 1)
            self.assertIn("final_table_missing", out["problem_codes"])

        def test_final_table_missing_row_fails(self):
            root1, wt1 = self.stage_bug("row-missing", "MERGED",
                                        worktree_exists=False)
            self.write_state(
                ["row-missing"],
                {"bug:row-missing:status": "MERGED",
                 "bug:row-missing:worktree": wt1,
                 "bug:row-missing:root": root1})
            self.batch_md.write_text(
                "## Final\n\n| Slug | Commit |\n|---|---|\n"
                "| some-other-bug | abc1234 |\n", encoding="utf-8")
            out, code = self.run_gate()
            self.assertEqual(code, 1)
            self.assertIn("final_table_row_missing", out["problem_codes"])

        def test_final_table_placeholder_commit_fails(self):
            root1, wt1 = self.stage_bug("no-commit-named", "MERGED",
                                        worktree_exists=False)
            self.write_state(
                ["no-commit-named"],
                {"bug:no-commit-named:status": "MERGED",
                 "bug:no-commit-named:worktree": wt1,
                 "bug:no-commit-named:root": root1})
            self.batch_md.write_text(
                "## Final\n\n| Slug | Commit |\n|---|---|\n"
                "| no-commit-named | TBD |\n", encoding="utf-8")
            out, code = self.run_gate()
            self.assertEqual(code, 1)
            self.assertIn("final_table_commit_missing", out["problem_codes"])

        def test_no_bugs_list_exits_2(self):
            self.state_path.write_text(json.dumps({
                "schema": "1", "artifacts": {}, "blockers": []}),
                encoding="utf-8")
            self.batch_md.write_text("## Final\n", encoding="utf-8")
            out, code = self.run_gate()
            self.assertEqual(code, 2)
            self.assertIn("artifacts['bugs']", out["error"])

        def test_missing_state_file_exits_2(self):
            self.batch_md.write_text("## Final\n", encoding="utf-8")
            out, code = self.run_gate()
            self.assertEqual(code, 2)

        def test_missing_flags_is_exit_2(self):
            ns = argparse.Namespace(state=None, batch_md=None, repo=".",
                                    milestone=None, ledger=None)
            out, code = build_report(ns)
            self.assertEqual(code, 2)

        def test_root_derived_from_repo_when_artifact_absent(self):
            """No bug:<slug>:root recorded: falls back to <repo>/.docs/bugfix/<slug>."""
            slug = "derived-root"
            root = self.bugfix_root(slug)
            root.mkdir(parents=True)
            chained(root / "gates.jsonl", "check_commit_gate.py",
                   milestone=slug, argv=["--commit"])
            self.write_state([slug], {"bug:{0}:status".format(slug): "MERGED",
                                      "bug:{0}:worktree".format(slug):
                                          str(self.dir / "wt" / slug)})
            self.batch_md.write_text(
                "## Final\n\n| Slug | Commit |\n|---|---|\n"
                "| {0} | abc1234 |\n".format(slug), encoding="utf-8")
            out, code = self.run_gate()
            self.assertEqual(code, 0, out)

    class ChainHelperParity(unittest.TestCase):
        def test_helper_matches_check_ledger_py(self):
            """The copied block must not drift from check_ledger.py's own."""
            here = Path(__file__).resolve().parent
            sibling = here / "check_ledger.py"
            if not sibling.is_file():
                self.skipTest("check_ledger.py not present beside this script")
            src = sibling.read_text(encoding="utf-8", errors="replace")
            start = src.index("def ledger_line_hash(")
            end = src.index("def ledger_self_hash(")
            end = src.index(chr(10) * 3, end) + 1
            sibling_block = src[start:end]
            mine = Path(__file__).read_text(encoding="utf-8", errors="replace")
            mstart = mine.index("def ledger_line_hash(")
            mend = mine.index("def ledger_self_hash(")
            mend = mine.index(chr(10) * 3, mend) + 1
            mine_block = mine[mstart:mend]
            self.assertEqual(mine_block, sibling_block)

    loader = unittest.defaultTestLoader
    suite = unittest.TestSuite([
        loader.loadTestsFromTestCase(HappyPath),
        loader.loadTestsFromTestCase(FailClosedCases),
        loader.loadTestsFromTestCase(OtherProblems),
        loader.loadTestsFromTestCase(ChainHelperParity),
    ])
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
