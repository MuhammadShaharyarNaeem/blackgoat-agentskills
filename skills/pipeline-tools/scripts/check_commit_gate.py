#!/usr/bin/env python3
"""Deterministic commit-gate CLI for the bgpdd-build pipeline.

Enforces the milestone commit gate mechanically: the latest review for the
milestone must be a machine-readable `**Verdict:** Approve` that postdates
the newest change, and the orchestrator-state blockers ledger must hold no
standing entry. On a pass, `--commit` performs the commit itself, so a
skipped gate is loud (no commit exists) rather than silent.

Usage:
    python check_commit_gate.py --review-report <path> --state <path> \
        --milestone "<title>" --changed-files <p1> [<p2> ...] \
        [--commit --message "<msg>"] [--repo <dir>] [--ignore-unscoped] \
        [--require-rendered-evidence] [--verify-tree] \
        [--max-changed-files <N> [--waiver <path>]] \
        [--ledger <path>] [--require-ledger-gates <name>[,<name>...]]
    python check_commit_gate.py --self-test

Pure standard library. See ../SKILL.md for the full contract (JSON shape,
exit codes, parsing rules).
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

REVIEW_HEADING_RE = re.compile(r"^##\s*Review:\s*(.*)$")
# ANY level-2..6 heading closes an open '## Review:' section. Anchoring only on
# '## ' let a '### Addendum' subsection carrying '**Verdict:** Approve' be read
# as part of a review whose real verdict was 'Request Changes' — and because the
# LAST verdict line in the section wins, the subsection overrode it.
ANY_HEADING_RE = re.compile(r"^#{2,6}(?:\s|$)")
VERDICT_LINE_RE = re.compile(r"^\s*\*\*Verdict:\*\*(.*)$")
VERDICT_TOKEN_RE = re.compile(r"^\s*(Approve|Request Changes)\s*$")
PATH_SHAPE_RE = re.compile(r"^[A-Za-z0-9_./\\-]+$")
PATH_EXTENSION_RE = re.compile(r"\.[A-Za-z0-9]+$")
MD_IMAGE_RE = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")
FENCE_RE = re.compile(r"^[ \t]*(`{3,}|~{3,})")
# A milestone identifier inside a review-section title: `M3`, `Milestone 3`.
# Used ONLY to detect a section title that serves several milestones at once.
MILESTONE_ID_RE = re.compile(r"\b(?:milestones?\s*|m)(\d{1,3})\b", re.IGNORECASE)
# Magic bytes per raster extension. A zero-byte `.png` satisfied
# --require-rendered-evidence before this: `touch evidence/review/m3.png` was a
# complete bypass of the "source can fail a check but never pass one" rule.
IMAGE_MAGIC = {
    "png": (b"\x89PNG\r\n\x1a\n",),
    "jpg": (b"\xff\xd8\xff",),
    "jpeg": (b"\xff\xd8\xff",),
    "gif": (b"GIF87a", b"GIF89a"),
}
BLOCKER_SEVERITIES = ("Critical", "Important", "Info")
BLOCKER_SEVERITY_RANK = {"Critical": 3, "Important": 2, "Info": 1}
# Info-severity blockers never gate here. Not a --severity-floor flag (unlike
# check_blockers.py) -- this gate has one fixed floor, not a caller-tunable
# one, because the commit gate is the last mechanical checkpoint before a
# milestone lands and letting a caller loosen it defeats the point.
BLOCKER_FLOOR_RANK = BLOCKER_SEVERITY_RANK["Important"]


class GateError(Exception):
    """Structural/usage failure — maps to exit 2."""


def normalize_blocker(entry):
    """A blocker array entry, structured-or-legacy, as one canonical shape.

    Duplicated from update_state.py / check_blockers.py by family convention
    (stdlib-only, one file each, no shared module). A legacy freeform string
    reads as unscoped (milestone null) and Critical -- the fail-safe reading.
    """
    if isinstance(entry, str):
        return {"id": None, "text": entry, "milestone": None,
                "capability": None, "severity": "Critical",
                "source": None, "added": None, "evidence": None}
    if isinstance(entry, dict):
        severity = entry.get("severity") or "Critical"
        if severity not in BLOCKER_SEVERITIES:
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
    return {"id": None, "text": json.dumps(entry), "milestone": None,
            "capability": None, "severity": "Critical",
            "source": None, "added": None, "evidence": None}


def blocker_milestone_equal(a, b):
    """Exact, case/whitespace-insensitive equality on the structured
    `milestone` field -- see check_blockers.py's `milestone_equal` for why
    this is exact equality rather than the word-boundary substring match
    `milestone_token_patterns` uses against review-section headings below
    (CLAUDE.md convention #8: a deliberate, labeled divergence -- a review
    heading is free prose with nothing structured to compare against, while
    a blocker's `milestone` field is a value someone wrote on purpose)."""
    return a.strip().casefold() == b.strip().casefold()


def read_text(path):
    """Read a UTF-8 artifact, tolerating a byte-order mark.

    `utf-8` (not `-sig`) left a BOM glued to the first character, so a report
    whose very first line was a heading or a verdict parsed as prose.
    """
    p = Path(path)
    if not p.is_file():
        raise GateError(f"file not found or not readable: {path}")
    return p.read_text(encoding="utf-8-sig", errors="replace")


def strip_fenced_blocks(text):
    """Blank out every ```/~~~ fenced region, preserving the line count.

    A `**Verdict:** Approve` inside a fence is a TEMPLATE or a captured
    transcript, never an assertion — but the parser read it as one, and since
    the last verdict line in a section wins, a pasted example silently
    overrode the real verdict. Line count is preserved so that any
    line-indexed diagnostic stays honest.

    Duplicated per file: this script family has no shared module by
    convention (GateError is duplicated in seven files).
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
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Shared gate ledger (see ../SKILL.md, "The gate ledger")
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
    """Append ONE JSON line recording this run. Best-effort by design.

    A ledger that cannot be written must never change the gate's own verdict —
    the ledger is an audit trail for LATER gates, not a term in this one.
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


def milestone_tokens(milestone):
    """Full title plus its leading identifier (text before the first ':' / '—')."""
    tokens = [milestone.strip().lower()]
    short = re.split(r"[:—-]", milestone, maxsplit=1)[0].strip().lower()
    if len(short) >= 2 and short != tokens[0]:
        tokens.append(short)
    return tokens


def milestone_token_patterns(milestone):
    """Compile each milestone token into a word-boundary regex.

    A bare substring test (e.g. "m1" `in` "## Review: M10 — ...") false-
    matches: "m1" is a substring of "m10". Requiring the token not be
    preceded/followed by an alphanumeric character makes it match only as a
    whole word, so "M1" no longer matches "M10" (or vice versa).
    """
    return [re.compile(rf"(?<![a-z0-9]){re.escape(t)}(?![a-z0-9])")
            for t in milestone_tokens(milestone)]


def _matches_milestone(patterns, haystack):
    haystack_l = haystack.lower()
    return any(p.search(haystack_l) for p in patterns)


def parse_review_sections(text):
    """Return every '## Review: ...' section as (title, [body lines]).

    ANY heading of level 2-6 closes an open section. Closing only on '## '
    meant a '### Addendum' (or any deeper subsection) stayed INSIDE the review
    body, so a `**Verdict:** Approve` written under it became the section's
    latest verdict line and overrode the real `Request Changes` above.
    """
    sections = []
    current = None
    for line in text.splitlines():
        m = REVIEW_HEADING_RE.match(line)
        if m:
            current = (m.group(1).strip(), [])
            sections.append(current)
        elif ANY_HEADING_RE.match(line):
            current = None
        elif current is not None:
            current[1].append(line)
    return sections


def section_milestone_ids(title):
    """Distinct milestone identifiers named by a review-section title.

    `## Review: M1 M2 M3` is one section serving three milestones: whichever
    milestone is gated finds a matching section, so a single `Approve` written
    once counted as three independent reviews. More than one distinct id here
    is `ambiguous_review_section` and the gate refuses it.
    """
    return sorted({m.group(1) for m in MILESTONE_ID_RE.finditer(title)},
                  key=lambda s: (len(s), s))


def find_matching_section(text, milestone):
    """Return (title, body_lines) for the LAST section matching the milestone."""
    patterns = milestone_token_patterns(milestone)
    matching = [s for s in parse_review_sections(text)
                if _matches_milestone(patterns, s[0])]
    return matching[-1] if matching else None


def find_latest_review(text, milestone):
    """Return (found, verdict_or_None, warnings) for the LAST matching section."""
    warnings = []
    section = find_matching_section(text, milestone)
    if section is None:
        return False, None, warnings
    title, body = section
    verdict_lines = [m.group(1) for m in
                     (VERDICT_LINE_RE.match(l) for l in body) if m]
    if not verdict_lines:
        warnings.append(f"review section '{title}' has no **Verdict:** line")
        return True, None, warnings
    token = VERDICT_TOKEN_RE.match(verdict_lines[-1])
    if not token:
        # Latest expression of intent is unreadable — fail-safe: no verdict.
        warnings.append(
            f"review section '{title}': latest Verdict line is not a "
            f"machine-readable token (got: {verdict_lines[-1].strip()!r}); "
            "required: 'Approve' or 'Request Changes' exactly")
        return True, None, warnings
    return True, token.group(1), warnings


def is_path_shaped(token):
    """A bare path-like token: allowed charset plus a dot-extension."""
    return bool(PATH_SHAPE_RE.match(token)) and bool(PATH_EXTENSION_RE.search(token))


def collect_rendered_evidence(body):
    """Gather evidence-path candidates from a matched review section's body.

    Sources: 'Rendered evidence: <paths>' lines (comma/whitespace-separated,
    path-shaped tokens only) and markdown image refs '![...](path)'.
    """
    candidates = []
    for line in body:
        if "Rendered evidence:" in line:
            after = line.split("Rendered evidence:", 1)[1]
            for tok in re.split(r"[,\s]+", after.strip()):
                if tok and is_path_shaped(tok):
                    candidates.append(tok)
        for m in MD_IMAGE_RE.finditer(line):
            candidates.append(m.group(1).strip())
    return candidates


def _cited_under_evidence_review(candidate):
    """True if the cited path names 'evidence/review/...' as a prefix.

    Tolerates backslash separators (a Windows-style citation) and a leading
    './'. This is a check on the CITED string itself -- the same string
    resolved against the review dir or --repo for existence -- so it applies
    regardless of which of the two bases resolved it.

    Rejects any '..' segment. Fixed 2026-08-12: the previous normalization
    was `lstrip("./")`, which strips ANY leading run of '.' and '/'
    characters rather than a single './' -- so '../evidence/review/x.png'
    collapsed to 'evidence/review/x.png' and satisfied provenance from
    outside the repo. `check_runtime_evidence.py` refuses traversal the same
    way; the two predicates differ only in anchoring (prefix here,
    containment there), deliberately and for documented reasons.
    """
    normalized = candidate.replace("\\", "/")
    parts = [p for p in normalized.split("/") if p and p != "."]
    if ".." in parts:
        return False
    return (len(parts) >= 3 and parts[0].lower() == "evidence"
            and parts[1].lower() == "review")


def _image_magic_problem(path):
    """None if the file's leading bytes match its raster extension, else why not.

    A rendered-evidence citation is the mechanical half of "source can fail a
    check but never pass one". A file that is not actually an image cannot
    depict a rendered result, so a `.png` that is empty, a text file, or a
    stub does not satisfy the gate.
    """
    ext = path.suffix.lower().lstrip(".")
    if ext not in IMAGE_MAGIC and ext != "webp":
        return None
    try:
        head = path.open("rb").read(16)
    except OSError as exc:
        return f"cannot be read ({exc})"
    if ext == "webp":
        if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
            return None
        return "does not start with the RIFF/WEBP magic bytes for a .webp"
    if any(head.startswith(sig) for sig in IMAGE_MAGIC[ext]):
        return None
    return f"does not start with the magic bytes for a .{ext} image"


def check_rendered_evidence(candidates, review_report, repo, newest_changed=None):
    """Return (ok, problems) for the cited rendered-evidence candidates.

    A candidate satisfies the gate only when ALL of these hold: it is cited
    under an `evidence/review/` directory; it resolves to an existing file
    against the review report's directory or --repo; the file is NON-EMPTY;
    when its extension is a raster one its leading bytes are that format's
    magic; and its mtime is at least the newest declared changed file's.

    Builder evidence (`evidence/build/...`) or any other existing path
    satisfies existence but not provenance -- only reviewer evidence gates.
    """
    review_dir = Path(review_report).parent
    repo_dir = Path(repo)
    problems = []
    ok = False
    for c in candidates:
        if not _cited_under_evidence_review(c):
            problems.append(f"{c}: not cited under an 'evidence/review/' directory")
            continue
        resolved = next((p for p in (review_dir / c, repo_dir / c) if p.is_file()),
                        None)
        if resolved is None:
            problems.append(f"{c}: no such file under the review report's "
                            f"directory or --repo ({repo})")
            continue
        try:
            stat = resolved.stat()
        except OSError as exc:
            problems.append(f"{c}: cannot be read ({exc})")
            continue
        if stat.st_size == 0:
            problems.append(f"{c}: is zero bytes — an empty file depicts nothing")
            continue
        magic_problem = _image_magic_problem(resolved)
        if magic_problem:
            problems.append(f"{c}: {magic_problem}")
            continue
        if newest_changed is not None and stat.st_mtime < newest_changed:
            problems.append(
                f"{c}: predates the newest declared changed file — the "
                "rendered evidence does not depict the current diff")
            continue
        ok = True
    return ok, problems


def check_staleness(review_report, changed_files):
    """Review file must be at least as new as the newest changed file.

    A `--changed-files` path that does not exist is a STRUCTURAL failure
    (exit 2), not a warning: an unresolvable path contributes no mtime, so a
    typo'd or absent path silently removed the diff from the staleness
    comparison — the whole check disabled itself and still reported PASS.
    """
    review_mtime = Path(review_report).stat().st_mtime
    newest = None
    missing = [f for f in changed_files if not Path(f).exists()]
    if missing:
        raise GateError(
            "changed_file_missing: --changed-files names path(s) that do not "
            "exist on disk, which would silently disable the staleness check: "
            + ", ".join(str(m) for m in missing))
    for f in changed_files:
        mt = Path(f).stat().st_mtime
        if newest is None or mt > newest:
            newest = mt
    stale = newest is not None and newest > review_mtime
    return stale, review_mtime, newest, []


def check_blockers(state_path, milestone, ignore_unscoped):
    """Split standing ledger entries into scoped / unscoped / other-milestone,
    using the same normalization and exact-equality scoping as
    check_blockers.py (the small helper is duplicated, not imported, per
    family convention).

    - scoped to THIS milestone (`milestone` field equals the gate's
      `--milestone` exactly): always blocks.
    - unscoped (`milestone` is null): blocks by default -- the fail-safe
      refinement of the old "gate on all" rule (CLAUDE.md convention #8) --
      unless `--ignore-unscoped` skips it.
    - scoped to a DIFFERENT milestone: never blocks; reported separately so
      it stays visible without gating a commit it was never about.
    - Info severity: never blocks, regardless of scope.
    """
    warnings = []
    try:
        state = json.loads(read_text(state_path))
    except json.JSONDecodeError as exc:
        raise GateError(f"state file is not valid JSON: {exc}")
    entries = state.get("blockers")
    if entries is None:
        raise GateError("state file has no 'blockers' field")
    if not isinstance(entries, list):
        raise GateError("'blockers' is not an array")

    scoped, unscoped, other = [], [], []
    for raw in entries:
        n = normalize_blocker(raw)
        if BLOCKER_SEVERITY_RANK[n["severity"]] < BLOCKER_FLOOR_RANK:
            continue  # Info never blocks
        m = n["milestone"]
        if m is None:
            unscoped.append(n)
        elif blocker_milestone_equal(m, milestone):
            scoped.append(n)
        else:
            other.append(n)

    skipped_ids = []
    if ignore_unscoped and unscoped:
        skipped_ids = [n["id"] for n in unscoped]
        warnings.append(
            f"{len(unscoped)} unscoped blocker entr{'y' if len(unscoped)==1 else 'ies'} "
            f"ignored via --ignore-unscoped (ids: {', '.join(repr(i) for i in skipped_ids)}); "
            "verify none belongs to this milestone")
    return scoped, unscoped, other, skipped_ids, warnings


def run_git(args, repo):
    proc = subprocess.run(["git"] + args, cwd=repo, capture_output=True,
                          text=True, timeout=240)
    if proc.returncode != 0:
        raise GateError(f"git {' '.join(args[:1])} failed: "
                        f"{(proc.stderr or proc.stdout).strip()}")
    return proc.stdout


def declared_files_uncommitted(changed_files, repo):
    """Declared paths that still differ from HEAD (staged or unstaged) or are untracked.

    The gate's promise is that the commit exists only because the gate ran. A
    fix its author already committed (observed: a builder committing his own
    change in Phase 3 of the bugfix lane) leaves the declared files clean, so
    `--commit` would either commit nothing or commit around the gate. Ignored
    files never appear in porcelain output, so a harness artifact under an
    ignore rule does not count.
    """
    if not changed_files:
        return []
    out = run_git(["status", "--porcelain", "--untracked-files=all", "--"]
                  + list(changed_files), repo)
    return [parse_porcelain_line(l) for l in out.splitlines() if l.strip()]


def perform_commit(changed_files, message, repo):
    run_git(["add", "--"] + list(changed_files), repo)
    run_git(["commit", "-m", message], repo)


def parse_porcelain_line(line):
    """Return the path a `git status --porcelain` line refers to.

    Two status chars then a space then the path; rename/copy lines read
    `R  old -> new` (or `C  ...`) — take the new path. Paths git quotes for
    special characters have their surrounding double quotes stripped.
    """
    path = line[3:]
    if " -> " in path:
        path = path.split(" -> ", 1)[1]
    if path.startswith('"') and path.endswith('"'):
        path = path[1:-1]
    return path


def normalize_repo_path(path, repo):
    """Repo-relative, forward-slash, case-folded-on-Windows form for comparison."""
    p = Path(path)
    if not p.is_absolute():
        p = Path(repo) / p
    p = p.resolve()
    try:
        rel = p.relative_to(Path(repo).resolve())
    except ValueError:
        rel = p
    normalized = os.path.normcase(str(rel).replace("\\", "/"))
    return normalized.replace("\\", "/")


def check_undeclared_tree(changed_files, repo):
    """Return repo-relative paths dirty in the working tree but not declared.

    Anything under `.docs/` is allowed regardless of declaration — pipeline
    artifacts (test reports, review reports, state, evidence) legitimately
    change during a milestone without being a builder code change.

    `git status --porcelain` collapses an entirely-untracked directory into a
    single `?? <dir>/` line rather than listing the files inside it. A
    porcelain path ending in `/` is therefore a DIRECTORY entry, not a file,
    and is normalized/compared as one: it is allowed iff its normalized form
    (trailing slash restored) is `.docs/` or begins with `.docs/`, or at
    least one declared `--changed-files` path lies under that directory
    prefix (a declared file's own never-before-tracked directory collapses
    the same way). Otherwise it is undeclared, reported WITH its trailing
    slash so the report is honest about it naming a directory, not a file.
    """
    output = run_git(["status", "--porcelain"], repo)
    declared = {normalize_repo_path(f, repo) for f in changed_files}
    undeclared = []
    for line in output.splitlines():
        if not line:
            continue
        raw_path = parse_porcelain_line(line)
        if raw_path.endswith("/"):
            norm_dir = normalize_repo_path(raw_path, repo) + "/"
            if norm_dir.startswith(".docs/"):
                continue
            if any(d == norm_dir or d.startswith(norm_dir) for d in declared):
                continue
            undeclared.append(norm_dir)
            continue
        norm = normalize_repo_path(raw_path, repo)
        if norm in declared or norm.startswith(".docs/"):
            continue
        undeclared.append(norm)
    return undeclared


def read_run_log(log_path):
    """Every parseable JSON-object line of record_run.py's run log.

    (path_missing, records). Duplicated from summarize_run.py by family
    convention (stdlib-only, one file each, no shared module).
    """
    p = Path(log_path)
    if not p.is_file():
        return True, []
    records = []
    try:
        text = p.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return True, []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(rec, dict):
            records.append(rec)
    return False, records


def normalize_unit(value):
    """A unit/milestone title as a comparable token, or None."""
    if not isinstance(value, str):
        return None
    return re.sub(r"\s+", " ", value.strip()).casefold() or None


def check_run_log_agents(log_path, agent_names, milestone):
    """Verify each named agent has a recorded delegation for this milestone.

    The commit gate already refuses to commit over an unapproved review. What
    it could not see is whether the review HAPPENED: a milestone whose Quinn
    or Luna round was skipped outright leaves a green report and an empty run
    log, and the gate passed on the report alone. Convention #9 -- the
    Orchestrator Contract's "record the delegation" rule became a file this
    gate has to read.

    `--model` must be present on each named agent's record: `record_run.py`
    already refuses a delegation without one (and, since 2.6.1, refuses a
    model string that resolves to no tier), so a record missing it was
    hand-written, and a hand-written delegation record is not evidence that a
    delegation occurred.

    WHAT THIS FLAG PROVES, AND WHAT IT DOES NOT -- a scope limit documented
    here because the 2026-09-07 audit found it documented nowhere. The run log
    is AUTHORED, not tool-provenanced: `record_run.py` writes nothing a person
    cannot type. Its records carry no hash of anything observed, no capture
    and no chain -- unlike `gates.jsonl`, whose entries this gate verifies by
    RE-HASHING every input the recorded run read (`ledger_stale`). So
    `--require-agents` proves that a delegation record EXISTS, is scoped to
    this milestone and names a tier; it does not prove the delegation
    happened. Its value is the one the ledger's own accepted limit has:
    skipping a round becomes an omission somebody has to notice, and faking
    one becomes a written act rather than a silence. Anyone who fabricates the
    run log satisfies this flag, and that is accepted rather than papered
    over -- closing it needs a provenance the runtime does not offer for its
    own dispatches. The terms with teeth beside it are
    `--require-ledger-gates` (re-hashes) and `--require-rendered-evidence`.

    Scoping is EXACT on the record's `unit` -- a deliberate divergence from
    `--require-ledger-gates`, which also accepts an unscoped entry (convention
    #8, tighter on purpose): a gate ledger line legitimately covers the whole
    epic, but a delegation with no unit does not say which milestone it built.

    Returns [{"agent", "problem", "detail"}]. Codes: `run_log_missing`,
    `run_log_agent_missing`, `run_log_model_missing`.
    """
    missing, records = read_run_log(log_path)
    if missing:
        return [{"agent": None, "problem": "run_log_missing",
                 "detail": "no readable run log at {0}; --require-agents has "
                           "nothing to read (Orchestrator Contract "
                           "\u00a74 records every delegation via "
                           "record_run.py)".format(log_path)}]
    unit = normalize_unit(milestone)
    problems = []
    for name in agent_names:
        wanted = name.strip().casefold()
        matches = [r for r in records
                   if r.get("event") == "delegation"
                   and isinstance(r.get("agent"), str)
                   and r["agent"].strip().casefold() == wanted
                   and normalize_unit(r.get("unit")) == unit]
        if not matches:
            problems.append({
                "agent": name, "problem": "run_log_agent_missing",
                "detail": "no delegation record for {0!r} scoped to unit {1!r} "
                          "in {2} -- the phase that agent owns has no evidence "
                          "it ran".format(name, milestone, log_path)})
            continue
        if not any(isinstance(r.get("model"), str) and r["model"].strip()
                   for r in matches):
            problems.append({
                "agent": name, "problem": "run_log_model_missing",
                "detail": "every delegation record for {0!r} on {1!r} carries a "
                          "null model; record_run.py refuses to write one, so "
                          "this record was hand-written".format(name, milestone)})
    return problems


def parse_agent_names(values):
    """Flatten repeated and/or comma-separated --require-agents values."""
    names = []
    for value in values or []:
        for token in value.split(","):
            token = token.strip()
            if token and token not in names:
                names.append(token)
    return names


def check_ledger_gates(ledger_path, gate_names, milestone):
    """Verify that each named gate LAST recorded a PASS for this milestone.

    Reads the shared ledger, takes the LATEST entry whose `gate` is the named
    script and whose `milestone` is this one or null, and requires (a) verdict
    PASS and (b) every input the entry hashed to still hash the same on disk.

    Why: a green sibling gate is only evidence while its inputs are unchanged.
    Re-running the commit gate after editing the very report a passing gate
    read is exactly how a stale PASS reaches a commit.

    Returns a list of {"gate", "problem", "detail"} — empty means every named
    gate is backed. Problem codes: `ledger_chain_broken`, `ledger_missing`,
    `ledger_failed`, `ledger_stale`.

    The chain is checked FIRST and short-circuits: a PASS read out of a ledger
    whose hash chain is broken is not evidence of anything, so there is no
    point naming which gate recorded it.
    """
    chain_ok, chain = verify_ledger_chain(ledger_path)
    if not chain_ok:
        return [{
            "gate": ledger_path, "problem": "ledger_chain_broken",
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
                      and (r.get("milestone") is None
                           or r.get("milestone") == milestone)]
        if not candidates:
            problems.append({
                "gate": name, "problem": "ledger_missing",
                "detail": f"no ledger entry for {name} scoped to milestone "
                          f"{milestone!r} (or unscoped) in {ledger_path}"})
            continue
        latest = candidates[-1]
        if latest.get("verdict") != "PASS":
            problems.append({
                "gate": name, "problem": "ledger_failed",
                "detail": f"the latest {name} ledger entry records verdict "
                          f"{latest.get('verdict')!r} (exit {latest.get('exit')})"})
            continue
        stale = []
        for path, recorded in (latest.get("inputs") or {}).items():
            if recorded is None:
                continue  # nothing was hashed; there is nothing to compare
            current = sha256_file(path)
            if current is None:
                stale.append(f"{path} (missing now)")
            elif current != recorded:
                stale.append(f"{path} (content changed since that run)")
        if stale:
            problems.append({
                "gate": name, "problem": "ledger_stale",
                "detail": f"the latest {name} ledger entry passed over inputs "
                          "that no longer match on disk: " + ", ".join(stale)})
    return problems


# A `## Size waiver` heading at any level 2-4. Its body runs to the next
# heading of level 2-6 (ANY_HEADING_RE), the same boundary rule the review
# sections use.
SIZE_WAIVER_HEADING_RE = re.compile(r"^#{2,4}\s*Size\s+waiver\s*:?\s*$",
                                    re.IGNORECASE)
# A waiver body line that is only a template stand-in. The waiver is
# deliberately hand-typed -- see check_size_bound() -- so the ONLY thing worth
# rejecting is a section that was never filled in.
WAIVER_PLACEHOLDER_RE = re.compile(
    r"^(?:<[^>]*>|todo|tbd|fixme|n/?a|none|\?+|\.{3,}|xxx+)[.:]?$",
    re.IGNORECASE)


def read_size_waiver(waiver_path):
    """Return (section_found, body_nonempty) for `## Size waiver`.

    Fences are stripped first, so a waiver section pasted as a TEMPLATE inside
    an example block cannot license a commit -- the same rule the verdict
    parser applies above.

    A body is a PLACEHOLDER in either of two shapes, and the second one is the
    load-bearing addition: every line individually a stand-in, OR one `<...>`
    span WRAPPED across several lines. The shipped `rca-template.md` writes the
    second shape ("<Delete this whole section unless ...>"), and a line-by-line
    test alone accepted it -- so copying the template was a complete bypass of
    the file bound. Same fix as check_bugfix_intake.is_placeholder_body().
    """
    text = strip_fenced_blocks(read_text(waiver_path))
    found, capturing, body = False, False, []
    for line in text.splitlines():
        if SIZE_WAIVER_HEADING_RE.match(line):
            found, capturing, body = True, True, []   # LAST section wins
            continue
        if capturing and ANY_HEADING_RE.match(line):
            capturing = False
            continue
        if capturing:
            body.append(line)
    real = [l.strip() for l in body if l.strip()]
    if not real:
        return found, False
    if all(WAIVER_PLACEHOLDER_RE.match(l) for l in real):
        return found, False
    if WAIVER_PLACEHOLDER_RE.match(" ".join(real)):
        return found, False   # one `<...>` span wrapped across several lines
    return found, True


def check_size_bound(args):
    """Return the `size_waiver` sub-report plus whether the bound is satisfied.

    **What is counted**: `len(--changed-files)` -- the paths the caller
    DECLARED, which this gate already validates exist on disk
    (`changed_file_missing`) and already uses for the staleness comparison.
    It deliberately does not re-derive the list from git: pairing this with
    `--verify-tree` is what makes the declared list equal the real diff, and
    that pairing is the bugfix lane's Phase 5 invocation.

    **Why the waiver is hand-typed.** Every other evidence path in this family
    refuses author-written proof. A size waiver is the documented exception:
    the decision to exceed the bound is the USER's, and no script can verify a
    judgement call. What the gate buys is that the decision is durable and
    attributable -- written into `rca.md`, hashed into the ledger record --
    instead of spoken once in chat. So the check is existence plus a
    non-placeholder body, and nothing more.
    """
    waiver = {"path": args.waiver, "present": False, "section_found": False,
              "body_nonempty": False, "satisfied": False}
    count = len(args.changed_files or [])
    if count <= args.max_changed_files:
        return count, waiver, True, None
    if not args.waiver:
        return count, waiver, False, (
            f"{count} changed file(s) exceeds --max-changed-files "
            f"{args.max_changed_files} and no --waiver was given — a fix this "
            "wide is either not localized (route it to /bgpdd-plan) or needs "
            "the user's recorded decision under a '## Size waiver' heading")
    if not Path(args.waiver).is_file():
        return count, waiver, False, (
            f"{count} changed file(s) exceeds --max-changed-files "
            f"{args.max_changed_files} and the --waiver file {args.waiver} does "
            "not exist")
    waiver["present"] = True
    found, nonempty = read_size_waiver(args.waiver)
    waiver["section_found"] = found
    waiver["body_nonempty"] = nonempty
    if not found:
        return count, waiver, False, (
            f"{count} changed file(s) exceeds --max-changed-files "
            f"{args.max_changed_files} and {args.waiver} has no '## Size "
            "waiver' heading outside a fenced block")
    if not nonempty:
        return count, waiver, False, (
            f"{count} changed file(s) exceeds --max-changed-files "
            f"{args.max_changed_files} and the '## Size waiver' section in "
            f"{args.waiver} is empty or still a placeholder — an unwritten "
            "waiver records no decision")
    waiver["satisfied"] = True
    return count, waiver, True, (
        f"{count} changed file(s) exceeds --max-changed-files "
        f"{args.max_changed_files}, waived by the '## Size waiver' section in "
        f"{args.waiver}")


RUNTIME_GATE = Path(__file__).parent / "check_runtime_evidence.py"


def _runtime_gate_supports(flag):
    """True when the delegated gate's source mentions `flag`.

    A capability probe rather than an assumption: `--ledger` and
    `--allow-missing-sidecar` are forwarded only when the child actually
    accepts them, so this file does not break the moment the two scripts are
    at different revisions (argparse would reject an unknown flag with exit 2
    and unparseable output, turning a green run into a structural failure).
    """
    try:
        return flag in RUNTIME_GATE.read_text(encoding="utf-8-sig",
                                              errors="replace")
    except OSError:
        return False


def run_runtime_gate(args):
    """Delegate to check_runtime_evidence.py. Returns (ok, its JSON payload).

    Subprocess rather than import: this family has no shared module by
    convention, and duplicating existence/provenance/freshness/content logic
    into a second file is the worse cost. `sys.executable` keeps the child on
    the same interpreter, and the file already shells out for git.
    """
    if not RUNTIME_GATE.is_file():
        raise GateError(f"runtime-evidence gate not found at {RUNTIME_GATE}")
    cmd = [sys.executable, str(RUNTIME_GATE),
           "--report", args.runtime_report,
           "--milestone", args.milestone,
           "--repo", args.repo]
    if args.changed_files:
        cmd += ["--changed-files"] + [str(p) for p in args.changed_files]
    if args.surface:
        cmd += ["--surface", args.surface]
    for key in args.require_key:
        cmd += ["--require-key", key]
    for host in args.forbid_host:
        cmd += ["--forbid-host", host]
    if args.expect_status is not None:
        cmd += ["--expect-status", str(args.expect_status)]
    if args.require_build_marker:
        cmd += ["--require-build-marker", args.require_build_marker]
    # The OpenAPI assertions must forward too, or the commit-time re-run is
    # strictly weaker than the earlier build-phase run — and this gate is the
    # one that owns the commit, so it is the one where the restraint has to
    # bind. Same reasoning as --verify-tree running here rather than only
    # earlier.
    if args.require_openapi_reachable:
        cmd += ["--require-openapi-reachable"]
    if args.openapi_doc:
        cmd += ["--openapi-doc", args.openapi_doc,
                "--openapi-route", args.openapi_route]
        if args.openapi_method:
            cmd += ["--openapi-method", args.openapi_method]
    # The child writes its own ledger record, so a later gate can require that
    # THIS run's runtime check passed over unchanged inputs.
    if args.ledger and _runtime_gate_supports("--ledger"):
        cmd += ["--ledger", args.ledger]
    if args.allow_missing_sidecar and _runtime_gate_supports("--allow-missing-sidecar"):
        cmd += ["--allow-missing-sidecar"]

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=240)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise GateError(f"cannot run the runtime-evidence gate: {exc}")
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        raise GateError(
            f"runtime-evidence gate emitted unparseable output "
            f"(exit {proc.returncode}): {proc.stdout[:400]!r}")
    if proc.returncode == 2:
        # Its structural failure is our structural failure -- an artifact or
        # environment defect, never a silently-passed gate.
        raise GateError(
            f"runtime-evidence gate structural failure: {payload.get('error')}")
    return proc.returncode == 0, payload


def build_report(args):
    report = {
        "milestone": args.milestone,
        "review_report": args.review_report,
        "state_file": args.state,
        "review_found": False,
        "verdict": None,
        "ambiguous_review_section": False,
        "stale": False,
        "blocking": [],
        "unscoped_blockers": [],
        "other_milestone_blockers": [],
        "ignored_unscoped_ids": [],
        "rendered_evidence": [],
        "rendered_evidence_ok": not args.require_rendered_evidence,
        "runtime_evidence": None,
        "runtime_evidence_ok": not args.require_runtime_evidence,
        "ledger": args.ledger,
        "require_ledger_gates": list(args.require_ledger_gates or []),
        "ledger_gate_problems": [],
        "ledger_gates_ok": True,
        "run_log": args.require_run_log,
        "require_agents": parse_agent_names(args.require_agents),
        "run_log_problems": [],
        "run_log_ok": True,
        "undeclared_changes": [],
        "tree_verified": True,
        "max_changed_files": args.max_changed_files,
        "changed_file_count": len(args.changed_files or []),
        "size_waiver": None,
        "size_ok": args.max_changed_files is None,
        "warnings": [],
        "committed": False,
        "already_committed": False,
        "result": "FAIL",
        "error": None,
    }
    # Fences are stripped ONCE, here: every downstream reader (verdict lines,
    # rendered-evidence citations) then sees a document with no example blocks
    # in it.
    text = strip_fenced_blocks(read_text(args.review_report))
    found, verdict, w = find_latest_review(text, args.milestone)
    report["review_found"] = found
    report["verdict"] = verdict
    report["warnings"] += w
    if not found:
        report["warnings"].append(
            f"no '## Review:' section matching milestone {args.milestone!r}")

    stale, _, newest_changed, w = check_staleness(args.review_report,
                                                  args.changed_files)
    report["stale"] = stale
    report["warnings"] += w
    if stale:
        report["warnings"].append(
            "a changed file is newer than the review report — the latest "
            "review predates the current diff and does not count")

    scoped, unscoped, other, skipped_unscoped_ids, w = check_blockers(
        args.state, args.milestone, args.ignore_unscoped)
    report["blocking"] = scoped
    report["unscoped_blockers"] = unscoped
    report["other_milestone_blockers"] = other
    report["ignored_unscoped_ids"] = skipped_unscoped_ids
    report["warnings"] += w

    section = find_matching_section(text, args.milestone)
    if section is not None:
        named = section_milestone_ids(section[0])
        if len(named) > 1:
            report["ambiguous_review_section"] = True
            report["warnings"].append(
                f"ambiguous_review_section: review section {section[0]!r} names "
                f"{len(named)} milestones ({', '.join('M' + n for n in named)}) "
                "— one verdict cannot review several milestones. Split it into "
                "one '## Review:' section per milestone")

    candidates = collect_rendered_evidence(section[1] if section else [])
    report["rendered_evidence"] = candidates
    if args.require_rendered_evidence:
        evidence_ok, evidence_problems = check_rendered_evidence(
            candidates, args.review_report, args.repo, newest_changed)
        report["rendered_evidence_ok"] = evidence_ok
        if not evidence_ok:
            report["warnings"].append(
                "--require-rendered-evidence set but the matched review "
                "section cites no usable evidence file under an "
                "'evidence/review/' directory; expected a "
                "'Rendered evidence: <path>' line or a markdown image ref "
                "'![...](path)' naming a NON-EMPTY file under evidence/review/ "
                "(a raster extension must carry that format's magic bytes) "
                "that resolves under the review report's directory or --repo "
                f"({args.repo}) and is no older than the newest changed file "
                "— evidence under evidence/build/ or elsewhere does not "
                "satisfy this gate"
                + ("; per citation: " + "; ".join(evidence_problems)
                   if evidence_problems else ""))

    if args.require_ledger_gates:
        report["ledger_gate_problems"] = check_ledger_gates(
            args.ledger, args.require_ledger_gates, args.milestone)
        report["ledger_gates_ok"] = not report["ledger_gate_problems"]
        for problem in report["ledger_gate_problems"]:
            report["warnings"].append(
                f"{problem['problem']}: {problem['detail']}")

    if args.require_agents:
        # Normalized HERE as well as in main(): build_report is called
        # directly by the self-test with raw argv, and a comma list that only
        # main() splits is a flag the tests never really exercise.
        report["run_log_problems"] = check_run_log_agents(
            args.require_run_log, report["require_agents"], args.milestone)
        report["run_log_ok"] = not report["run_log_problems"]
        for problem in report["run_log_problems"]:
            report["warnings"].append(
                "{0}: {1}".format(problem["problem"], problem["detail"]))

    if args.require_runtime_evidence:
        runtime_ok, payload = run_runtime_gate(args)
        report["runtime_evidence_ok"] = runtime_ok
        report["runtime_evidence"] = payload
        if not runtime_ok:
            accepted = payload.get("accepted") or []
            report["warnings"].append(
                "--require-runtime-evidence set but the runtime-evidence gate "
                f"failed for this milestone ({len(accepted)} accepted "
                "capture(s)); see the 'runtime_evidence' object for the "
                "per-capture cause. An in-process suite cannot pass a claim "
                "about observed behavior")

    if args.max_changed_files is not None:
        count, waiver, size_ok, note = check_size_bound(args)
        report["changed_file_count"] = count
        report["size_waiver"] = waiver
        report["size_ok"] = size_ok
        if note:
            report["warnings"].append(note)

    if args.verify_tree:
        undeclared = check_undeclared_tree(args.changed_files, args.repo)
        report["undeclared_changes"] = undeclared
        report["tree_verified"] = not undeclared
        for path in undeclared:
            report["warnings"].append(
                f"--verify-tree set but the working tree has an undeclared "
                f"change outside --changed-files and .docs/: {path}")

    if args.commit and args.changed_files:
        pending = declared_files_uncommitted(args.changed_files, args.repo)
        if not pending:
            report["already_committed"] = True
            report["warnings"].append(
                "--commit set but no declared --changed-files path differs from "
                "HEAD: the change was committed outside this gate (a builder "
                "committing its own fix, or a hand commit). The commit must be "
                "the gate's; reset the outside commit (keep the tree) and re-run")

    gate_ok = (found and verdict == "Approve" and not stale and not scoped
               and not report["ambiguous_review_section"]
               and (args.ignore_unscoped or not unscoped)
               and report["rendered_evidence_ok"]
               and report["runtime_evidence_ok"]
               and report["ledger_gates_ok"]
               and report["run_log_ok"]
               and report["size_ok"]
               and report["tree_verified"]
               and not report["already_committed"])
    report["result"] = "PASS" if gate_ok else "FAIL"

    if gate_ok and args.commit:
        perform_commit(args.changed_files, args.message, args.repo)
        report["committed"] = True
    return report


def build_parser():
    """Single source of truth for the CLI surface.

    Extracted from main() so the self-test parses real argv instead of
    hand-building argparse.Namespace objects -- every hand-built namespace is
    a place a newly-added flag raises AttributeError instead of being tested.
    """
    parser = argparse.ArgumentParser(prog="check_commit_gate.py")
    parser.add_argument("--review-report")
    parser.add_argument("--state")
    parser.add_argument("--milestone")
    parser.add_argument("--changed-files", nargs="+", default=[])
    parser.add_argument("--commit", action="store_true")
    parser.add_argument("--message")
    parser.add_argument("--repo", default=".")
    parser.add_argument("--ignore-unscoped", action="store_true")
    parser.add_argument("--require-rendered-evidence", action="store_true")
    parser.add_argument("--verify-tree", action="store_true")
    # Fix-size bound (bgpdd-bugfix Phase 5; lane default 5). Counts the
    # DECLARED --changed-files paths -- see check_size_bound().
    parser.add_argument("--max-changed-files", type=int)
    parser.add_argument(
        "--waiver",
        help="a document whose '## Size waiver' section records the user's "
             "decision to exceed --max-changed-files (typically rca.md)")
    # Runtime-evidence delegation. This gate owns the commit, so the restraint
    # has to live here -- but the checking logic lives once, in
    # check_runtime_evidence.py, rather than being duplicated across two files.
    parser.add_argument("--require-runtime-evidence", action="store_true")
    parser.add_argument("--runtime-report")
    parser.add_argument("--surface")
    parser.add_argument("--require-key", action="append", default=[])
    parser.add_argument("--expect-status", type=int)
    parser.add_argument("--forbid-host", action="append", default=[])
    parser.add_argument("--require-build-marker")
    parser.add_argument("--require-openapi-reachable", action="store_true")
    parser.add_argument("--openapi-doc")
    parser.add_argument("--openapi-route")
    parser.add_argument("--openapi-method")
    # Forwarded verbatim to check_runtime_evidence.py, which owns its meaning.
    parser.add_argument("--allow-missing-sidecar", action="store_true")
    # The shared gate ledger.
    parser.add_argument("--ledger",
                        help="append one JSON record per run to this path")
    parser.add_argument(
        "--require-ledger-gates", action="append", default=[],
        help="comma-separated gate script names whose LATEST ledger entry for "
             "this milestone must be PASS over unchanged inputs")
    # Did the delegation the review report claims actually happen?
    parser.add_argument(
        "--require-run-log", dest="require_run_log",
        help="record_run.py's run log; the source --require-agents reads. The "
             "run log is AUTHORED, not tool-provenanced: this pair proves a "
             "delegation record exists, is scoped to the milestone and names "
             "a tier — not that the delegation happened. --require-ledger-"
             "gates is the flag that re-hashes what it read.")
    parser.add_argument(
        "--require-agents", action="append", default=[],
        help="comma-separated agent names that must each carry a delegation "
             "record for this milestone, with a model, in --require-run-log")
    parser.add_argument("--self-test", action="store_true")
    return parser


def parse_gate_names(values):
    """Flatten repeated and/or comma-separated --require-ledger-gates values."""
    names = []
    for value in values or []:
        for token in value.split(","):
            token = token.strip()
            if token and token not in names:
                names.append(token)
    return names


def ledger_inputs(args):
    """Every file path this gate READ, in the order it was declared."""
    paths = [args.review_report, args.state] + list(args.changed_files or [])
    for extra in (args.runtime_report, args.openapi_doc, args.waiver,
                  args.require_run_log):
        if extra:
            paths.append(extra)
    return [p for p in paths if p]


def main(argv):
    args = build_parser().parse_args(argv)

    if args.self_test:
        return run_self_test()

    args.require_ledger_gates = parse_gate_names(args.require_ledger_gates)
    args.require_agents = parse_agent_names(args.require_agents)

    def finish(code, verdict):
        """One exit point: EVERY return path records a ledger line."""
        append_ledger(args.ledger, argv, args.milestone, ledger_inputs(args),
                      verdict, code)
        return code

    missing = [n for n, v in (("--review-report", args.review_report),
                              ("--state", args.state),
                              ("--milestone", args.milestone)) if not v]
    if missing:
        print(json.dumps({"result": "ERROR",
                          "error": f"missing required argument(s): {', '.join(missing)}"}))
        return finish(2, "ERROR")
    if args.commit and not args.message:
        print(json.dumps({"result": "ERROR",
                          "error": "--commit requires --message"}))
        return finish(2, "ERROR")
    if not args.changed_files:
        print(json.dumps({"result": "ERROR",
                          "error": "--changed-files requires at least one path"}))
        return finish(2, "ERROR")
    if args.require_runtime_evidence and not args.runtime_report:
        print(json.dumps({"result": "ERROR",
                          "error": "--require-runtime-evidence requires --runtime-report "
                                    "(the test or verification report carrying the "
                                    "**Runtime evidence:** citations)"}))
        return finish(2, "ERROR")
    if args.max_changed_files is not None and args.max_changed_files < 1:
        print(json.dumps({"result": "ERROR",
                          "error": "--max-changed-files must be >= 1 (a bound "
                                    "of 0 can never be satisfied)"}))
        return finish(2, "ERROR")
    if args.waiver and args.max_changed_files is None:
        print(json.dumps({"result": "ERROR",
                          "error": "--waiver given without "
                                    "--max-changed-files — there is no bound "
                                    "for it to waive"}))
        return finish(2, "ERROR")
    if args.require_ledger_gates and not args.ledger:
        print(json.dumps({"result": "ERROR",
                          "error": "--require-ledger-gates requires --ledger "
                                    "(there is no ledger to read otherwise)"}))
        return finish(2, "ERROR")
    if args.require_agents and not args.require_run_log:
        print(json.dumps({"result": "ERROR",
                          "error": "--require-agents requires --require-run-log "
                                    "(there is no run log to read otherwise)"}))
        return finish(2, "ERROR")
    if args.require_run_log and not args.require_agents:
        print(json.dumps({"result": "ERROR",
                          "error": "--require-run-log given without "
                                    "--require-agents \u2014 a run log nobody "
                                    "names an agent in asserts nothing"}))
        return finish(2, "ERROR")
    forwarded = [n for n, v in (("--runtime-report", args.runtime_report),
                                 ("--surface", args.surface),
                                 ("--require-key", args.require_key),
                                 ("--expect-status", args.expect_status),
                                 ("--forbid-host", args.forbid_host),
                                 ("--require-build-marker", args.require_build_marker),
                                 ("--require-openapi-reachable",
                                  args.require_openapi_reachable),
                                 ("--openapi-doc", args.openapi_doc),
                                 ("--openapi-route", args.openapi_route),
                                 ("--openapi-method", args.openapi_method),
                                 ("--allow-missing-sidecar",
                                  args.allow_missing_sidecar))
                 if v and not args.require_runtime_evidence]
    if forwarded:
        print(json.dumps({"result": "ERROR",
                          "error": f"{', '.join(forwarded)} given without "
                                    "--require-runtime-evidence"}))
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
    import os
    import platform
    import shutil
    import tempfile
    import unittest

    # A minimal but REAL png header — a zero-byte `.png` used to satisfy
    # --require-rendered-evidence.
    PNG = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x0dIHDR"

    REVIEW_OK = ("## Review: M3 — Auth endpoints\n\nfindings...\n\n"
                 "**Verdict:** Approve\n")
    REVIEW_RC = ("## Review: M3 — Auth endpoints\n\n"
                 "**Verdict:** Request Changes\n")
    # The observed evasion: a deeper subsection under a Request-Changes review
    # carrying its own Approve. `### Addendum` must CLOSE the review section.
    REVIEW_RC_ADDENDUM = (
        "## Review: M3 — Auth endpoints\n\n"
        "**Verdict:** Request Changes\n\n"
        "### Addendum\n\n"
        "Fixed the nit in review.\n\n"
        "**Verdict:** Approve\n")
    # A fenced TEMPLATE block is not an assertion.
    REVIEW_RC_FENCED_APPROVE = (
        "## Review: M3 — Auth endpoints\n\n"
        "**Verdict:** Request Changes\n\n"
        "For the next round, use this template:\n\n"
        "```markdown\n"
        "**Verdict:** Approve\n"
        "```\n")
    REVIEW_MULTI_MILESTONE = (
        "## Review: M1 M2 M3 — batch review\n\nfindings...\n\n"
        "**Verdict:** Approve\n")
    REVIEW_EVIDENCE_LINE = ("## Review: M3 — Auth endpoints\n\nfindings...\n\n"
                            "Rendered evidence: evidence/review/m3-table.png\n\n"
                            "**Verdict:** Approve\n")
    REVIEW_EVIDENCE_IMAGE = ("## Review: M3 — Auth endpoints\n\nfindings...\n\n"
                             "![screenshot](evidence/review/m3-shot.png)\n\n"
                             "**Verdict:** Approve\n")
    REVIEW_EVIDENCE_BUILD_ONLY = ("## Review: M3 — Auth endpoints\n\nfindings...\n\n"
                                  "Rendered evidence: evidence/build/m3-table.png\n\n"
                                  "**Verdict:** Approve\n")

    class GateTests(unittest.TestCase):
        def setUp(self):
            self.dir = Path(tempfile.mkdtemp())
            self.changed = self.dir / "src_file.py"
            self.changed.write_text("code\n")
            self.review = self.dir / "review-report.md"
            self.state = self.dir / "orchestrator-state.json"
            self.state.write_text(json.dumps({"blockers": []}))

        def tearDown(self):
            shutil.rmtree(self.dir, ignore_errors=True)

        def _order(self, older, newer):
            os.utime(older, (1000, 1000))
            os.utime(newer, (2000, 2000))

        def _evidence(self, name="m3-table.png", data=None, under="review"):
            """Write a real, non-empty evidence file and return its path."""
            d = self.dir / "evidence" / under
            d.mkdir(parents=True, exist_ok=True)
            p = d / name
            p.write_bytes(PNG if data is None else data)
            return p

        def _ns(self, milestone="M3", changed=None, repo=None, extra=None,
                commit=False, message=None):
            """Parse real argv -- never hand-build a Namespace.

            A hand-built Namespace silently lacks any newly-added flag and
            raises AttributeError instead of exercising it, which is how a new
            gate term can ship untested.
            """
            argv = ["--review-report", str(self.review),
                    "--state", str(self.state),
                    "--milestone", milestone,
                    "--changed-files"] + (changed or [str(self.changed)]) + [
                    "--repo", repo or str(self.dir)]
            if commit:
                argv += ["--commit", "--message", message or "m"]
            return build_parser().parse_args(argv + (extra or []))

        def _run(self, extra=None):
            return build_report(self._ns(extra=extra))

        def test_happy_path_passes(self):
            self.review.write_text(REVIEW_OK)
            self._order(self.changed, self.review)
            self.assertEqual(self._run()["result"], "PASS")

        def test_request_changes_fails(self):
            self.review.write_text(REVIEW_RC)
            self._order(self.changed, self.review)
            r = self._run()
            self.assertEqual(r["result"], "FAIL")
            self.assertEqual(r["verdict"], "Request Changes")

        def test_stale_review_fails(self):
            self.review.write_text(REVIEW_OK)
            self._order(self.review, self.changed)  # change is newer
            r = self._run()
            self.assertEqual(r["result"], "FAIL")
            self.assertTrue(r["stale"])

        def test_scoped_blocker_fails(self):
            # Scoped now means an explicit `milestone` field match -- the
            # structured schema replaces the old substring guess against
            # freeform text.
            self.review.write_text(REVIEW_OK)
            self._order(self.changed, self.review)
            self.state.write_text(json.dumps(
                {"blockers": [{"id": "B-1", "text": "placeholder route finding open",
                                "milestone": "M3"}]}))
            r = self._run()
            self.assertEqual(r["result"], "FAIL")
            self.assertEqual(len(r["blocking"]), 1)
            self.assertEqual(r["blocking"][0]["id"], "B-1")

        def test_unscoped_blocker_fails_by_default(self):
            # A legacy freeform string normalizes to milestone: null --
            # unscoped, and unscoped still blocks by default (fail-safe).
            self.review.write_text(REVIEW_OK)
            self._order(self.changed, self.review)
            self.state.write_text(json.dumps(
                {"blockers": ["proxy substitution in test env"]}))
            r = self._run()
            self.assertEqual(r["result"], "FAIL")
            self.assertEqual(r["blocking"], [])
            self.assertEqual(len(r["unscoped_blockers"]), 1)

        def test_unscoped_blocker_ignorable(self):
            self.review.write_text(REVIEW_OK)
            self._order(self.changed, self.review)
            self.state.write_text(json.dumps(
                {"blockers": ["proxy substitution in test env"]}))
            r = self._run(["--ignore-unscoped"])
            self.assertEqual(r["result"], "PASS")
            self.assertEqual(len(r["unscoped_blockers"]), 1)

        def test_ignore_unscoped_names_the_skipped_ids(self):
            self.review.write_text(REVIEW_OK)
            self._order(self.changed, self.review)
            self.state.write_text(json.dumps(
                {"blockers": [{"id": "B-7", "text": "proxy substitution",
                                "milestone": None}]}))
            r = self._run(["--ignore-unscoped"])
            self.assertEqual(r["result"], "PASS")
            self.assertEqual(r["ignored_unscoped_ids"], ["B-7"])

        def test_other_milestone_scoped_blocker_does_not_gate_this_one(self):
            # A blocker explicitly scoped to a DIFFERENT milestone must not
            # gate this one at all -- no --ignore-unscoped override needed,
            # since the scoping is now exact-match on the structured
            # `milestone` field rather than a substring guess against
            # freeform text. Replaces the old word-boundary
            # "M10 does not gate M1" case, which tested the same guarantee
            # against the pre-schema substring heuristic.
            self.review.write_text(
                "## Review: M1 — Setup\n\n**Verdict:** Approve\n")
            self._order(self.changed, self.review)
            self.state.write_text(json.dumps(
                {"blockers": [{"id": "B-9", "text": "unrelated finding open",
                                "milestone": "M10"}]}))
            ns = self._ns(milestone="M1")
            r = build_report(ns)
            self.assertEqual(r["blocking"], [])
            self.assertEqual(r["unscoped_blockers"], [])
            self.assertEqual(len(r["other_milestone_blockers"]), 1)
            self.assertEqual(r["other_milestone_blockers"][0]["id"], "B-9")
            self.assertEqual(r["result"], "PASS")

        def test_milestone_field_match_is_case_and_whitespace_insensitive(self):
            self.review.write_text(REVIEW_OK)
            self._order(self.changed, self.review)
            self.state.write_text(json.dumps(
                {"blockers": [{"id": "B-1", "text": "x", "milestone": " m3 "}]}))
            r = self._run()
            self.assertEqual(len(r["blocking"]), 1)

        def test_info_severity_blocker_never_blocks(self):
            self.review.write_text(REVIEW_OK)
            self._order(self.changed, self.review)
            self.state.write_text(json.dumps(
                {"blockers": [{"id": "B-1", "text": "cosmetic nit",
                                "milestone": "M3", "severity": "Info"}]}))
            r = self._run()
            self.assertEqual(r["result"], "PASS")
            self.assertEqual(r["blocking"], [])

        def test_mixed_legacy_and_structured_blockers(self):
            self.review.write_text(REVIEW_OK)
            self._order(self.changed, self.review)
            self.state.write_text(json.dumps(
                {"blockers": [
                    "legacy freeform blocker",
                    {"id": "B-1", "text": "scoped to this one", "milestone": "M3"},
                    {"id": "B-2", "text": "scoped elsewhere", "milestone": "M9"},
                ]}))
            r = self._run()
            self.assertEqual(r["result"], "FAIL")
            self.assertEqual(len(r["blocking"]), 1)
            self.assertEqual(len(r["unscoped_blockers"]), 1)
            self.assertEqual(len(r["other_milestone_blockers"]), 1)

        def test_missing_review_section_fails(self):
            self.review.write_text("## Review: M7 — other milestone\n"
                                   "**Verdict:** Approve\n")
            self._order(self.changed, self.review)
            r = self._run()
            self.assertEqual(r["result"], "FAIL")
            self.assertFalse(r["review_found"])

        def test_latest_matching_section_wins(self):
            self.review.write_text(REVIEW_RC + "\n" + REVIEW_OK)
            self._order(self.changed, self.review)
            self.assertEqual(self._run()["result"], "PASS")

        def test_word_boundary_m1_does_not_match_m10_section(self):
            # Gating M1 must NOT match a report whose only section is "M10".
            self.review.write_text(
                "## Review: M10 — Unrelated milestone\n\n**Verdict:** Approve\n")
            self._order(self.changed, self.review)
            ns = self._ns(milestone="M1")
            r = build_report(ns)
            self.assertFalse(r["review_found"])
            self.assertEqual(r["result"], "FAIL")

        def test_word_boundary_m1_matches_m1_section(self):
            # Existing behavior preserved: M1 matches a section titled M1.
            self.review.write_text(
                "## Review: M1 — Setup\n\n**Verdict:** Approve\n")
            changed = self.dir / "m1_file.py"
            changed.write_text("code\n")
            self._order(changed, self.review)
            ns = self._ns(milestone="M1", changed=[str(changed)])
            r = build_report(ns)
            self.assertTrue(r["review_found"])
            self.assertEqual(r["result"], "PASS")

        def test_legacy_string_blocker_is_unscoped_regardless_of_its_text(self):
            # A legacy freeform string normalizes to milestone: null no
            # matter what it says -- scoping is now the structured
            # `milestone` field, never a guess against the text (that
            # guess is what test_other_milestone_scoped_blocker_... above
            # replaces). So this lands in unscoped, not blocking, and still
            # gates M1 by default via the unscoped fail-safe;
            # --ignore-unscoped remains the override.
            self.review.write_text(
                "## Review: M1 — Setup\n\n**Verdict:** Approve\n")
            self._order(self.changed, self.review)
            self.state.write_text(json.dumps(
                {"blockers": ["M10: unrelated finding open"]}))
            ns = self._ns(milestone="M1")
            r = build_report(ns)
            self.assertEqual(r["blocking"], [])
            self.assertEqual(len(r["unscoped_blockers"]), 1)
            self.assertEqual(r["result"], "FAIL")  # unscoped gates by default

            ns.ignore_unscoped = True
            r2 = build_report(ns)
            self.assertEqual(r2["result"], "PASS")

        # ---- --require-runtime-evidence (delegates to check_runtime_evidence) ----

        def _runtime_fixtures(self, body, openapi=None):
            """A test-report citing one capture with the given response body.

            The capture is written WITH the `<capture>.meta.json` provenance
            sidecar check_runtime_evidence.py requires, and its probe token is
            `curl` (a known HTTP client), so these cases keep passing once that
            gate starts demanding both.
            """
            impl = self.dir / ".docs" / "p" / "implementation"
            (impl / "evidence" / "runtime").mkdir(parents=True, exist_ok=True)
            cap = impl / "evidence" / "runtime" / "m3.md"
            probe = ["curl", "-sS", "-i", "http://localhost:5142/api/auth"]
            fenced = "HTTP/1.1 200 OK\n\n" + body
            cap.write_text(
                "# Runtime capture\n\n"
                "- Milestone: M3 — auth endpoints [API] [vs:api]\n"
                "- Surface: api\n"
                "- Transport: out-of-process HTTP\n"
                + (f"- OpenAPI: {openapi}\n" if openapi else "")
                + "- Base URL: http://localhost:5142\n"
                "- Probe command: `" + " ".join(probe) + "`\n"
                "- Captured: 2026-08-12T14:03:11Z\n"
                "- Exit code: 0\n\n"
                "## Captured output\n\n```\n" + fenced + "\n```\n",
                encoding="utf-8")
            meta = {
                "argv": probe,
                "cwd": str(self.dir),
                "host": platform.node(),
                "pid": os.getpid(),
                "started": "2026-08-12T14:03:10Z",
                "finished": "2026-08-12T14:03:11Z",
                "exit_code": 0,
                "body_sha256": hashlib.sha256(
                    fenced.encode("utf-8")).hexdigest(),
                "capture_sha256": hashlib.sha256(cap.read_bytes()).hexdigest(),
                "tool": "run_quiet.py",
                "schema": 1,
            }
            sidecars = [cap.with_name(cap.name + ".meta.json"),
                        cap.with_suffix(".meta.json")]
            for sidecar in sidecars:
                sidecar.write_text(json.dumps(meta, indent=2), encoding="utf-8")
            report = impl / "test-report.md"
            report.write_text(
                "#Task [1]:\n\n**Runtime evidence:** evidence/runtime/m3.md\n"
                "- FR-1: PASS — exit 0 — AuthTests.cs::returns 200\n",
                encoding="utf-8")
            # capture must postdate the diff
            os.utime(self.changed, (1000, 1000))
            os.utime(cap, (3000, 3000))
            for sidecar in sidecars:
                os.utime(sidecar, (3000, 3000))
            os.utime(report, (3000, 3000))
            return str(report)

        def test_runtime_evidence_envelope_present_passes(self):
            self.review.write_text(REVIEW_OK)
            self._order(self.changed, self.review)
            rep = self._runtime_fixtures('{"isSuccess":true,"notifications":[]}')
            r = build_report(self._ns(extra=[
                "--require-runtime-evidence", "--runtime-report", rep,
                "--require-key", "isSuccess", "--require-key", "notifications"]))
            self.assertTrue(r["runtime_evidence_ok"], r["runtime_evidence"])
            self.assertEqual(r["result"], "PASS")

        @unittest.skipUnless(shutil.which("git"), "git not on PATH")
        def test_runtime_evidence_missing_envelope_blocks_the_commit(self):
            """The load-bearing case: everything else green, no commit exists."""
            run_git(["init", "-q"], str(self.dir))
            run_git(["config", "user.email", "gate@test"], str(self.dir))
            run_git(["config", "user.name", "gate"], str(self.dir))
            self.review.write_text(REVIEW_OK)
            self._order(self.changed, self.review)
            rep = self._runtime_fixtures('{"id":1,"total":9}')   # bare payload
            r = build_report(self._ns(
                milestone="M3", commit=True, message="M3: auth endpoints",
                extra=["--require-runtime-evidence", "--runtime-report", rep,
                       "--require-key", "isSuccess", "--require-key", "notifications"]))
            self.assertFalse(r["runtime_evidence_ok"])
            self.assertEqual(r["verdict"], "Approve")      # review was fine
            self.assertEqual(r["result"], "FAIL")
            self.assertFalse(r["committed"])
            # `git log` ERRORS on a repo with no commits, so count instead --
            # zero commits is the proof the gate blocked rather than reported.
            self.assertEqual(
                run_git(["rev-list", "--all", "--count"], str(self.dir)).strip(), "0")

        def test_openapi_flag_forwards_to_the_child_gate(self):
            """A commit-time re-run must not be weaker than the earlier run.

            The flag has to reach the child process, so the assertion is that
            the SAME capture passes without it and fails with it.
            """
            self.review.write_text(REVIEW_OK)
            self._order(self.changed, self.review)
            rep = self._runtime_fixtures('{"isSuccess":true,"notifications":[]}')
            base = ["--require-runtime-evidence", "--runtime-report", rep]
            r = build_report(self._ns(extra=base))
            self.assertTrue(r["runtime_evidence_ok"], r["runtime_evidence"])
            r2 = build_report(self._ns(extra=base + ["--require-openapi-reachable"]))
            self.assertFalse(r2["runtime_evidence_ok"])
            self.assertEqual(r2["result"], "FAIL")

        def test_openapi_flag_passes_when_the_capture_records_it(self):
            """The forwarded assertion is satisfiable, not a dead end."""
            self.review.write_text(REVIEW_OK)
            self._order(self.changed, self.review)
            rep = self._runtime_fixtures(
                '{"isSuccess":true,"notifications":[]}',
                openapi="http://localhost:5142/swagger/v1/swagger.json — 200")
            r = build_report(self._ns(extra=[
                "--require-runtime-evidence", "--runtime-report", rep,
                "--require-openapi-reachable"]))
            self.assertTrue(r["runtime_evidence_ok"], r["runtime_evidence"])
            self.assertEqual(r["result"], "PASS")

        def test_runtime_evidence_flag_unset_is_backcompat(self):
            self.review.write_text(REVIEW_OK)
            self._order(self.changed, self.review)
            r = self._run()
            self.assertTrue(r["runtime_evidence_ok"])
            self.assertIsNone(r["runtime_evidence"])
            self.assertEqual(r["result"], "PASS")

        def test_runtime_report_missing_is_exit_2_not_a_pass(self):
            self.review.write_text(REVIEW_OK)
            self._order(self.changed, self.review)
            with self.assertRaises(GateError):
                build_report(self._ns(extra=[
                    "--require-runtime-evidence",
                    "--runtime-report", str(self.dir / "nope.md")]))

        def test_usage_errors_for_the_delegating_flags(self):
            base = ["--review-report", str(self.review), "--state", str(self.state),
                    "--milestone", "M3", "--changed-files", str(self.changed)]
            # --require-runtime-evidence without --runtime-report
            self.assertEqual(main(base + ["--require-runtime-evidence"]), 2)
            # forwarded flags without the gate flag
            self.assertEqual(main(base + ["--require-key", "isSuccess"]), 2)
            self.assertEqual(main(base + ["--expect-status", "200"]), 2)
            self.assertEqual(main(base + ["--require-openapi-reachable"]), 2)
            self.assertEqual(main(base + ["--openapi-doc", "x.json",
                                          "--openapi-route", "/a"]), 2)
            self.assertEqual(main(base + ["--openapi-method", "post"]), 2)
            self.assertEqual(main(base + ["--allow-missing-sidecar"]), 2)

        # ---- section boundaries, fences, encoding ----

        def test_addendum_subsection_cannot_override_the_verdict(self):
            """`### Addendum` closes the review section; the RC verdict stands."""
            self.review.write_text(REVIEW_RC_ADDENDUM, encoding="utf-8")
            self._order(self.changed, self.review)
            r = self._run()
            self.assertEqual(r["verdict"], "Request Changes")
            self.assertEqual(r["result"], "FAIL")

        def test_fenced_approve_template_does_not_count(self):
            self.review.write_text(REVIEW_RC_FENCED_APPROVE, encoding="utf-8")
            self._order(self.changed, self.review)
            r = self._run()
            self.assertEqual(r["verdict"], "Request Changes")
            self.assertEqual(r["result"], "FAIL")

        def test_fenced_approve_alone_is_not_a_verdict(self):
            """A section whose ONLY Approve is fenced has no verdict at all."""
            self.review.write_text(
                "## Review: M3 — Auth endpoints\n\n"
                "~~~\n**Verdict:** Approve\n~~~\n", encoding="utf-8")
            self._order(self.changed, self.review)
            r = self._run()
            self.assertIsNone(r["verdict"])
            self.assertEqual(r["result"], "FAIL")

        def test_strip_fenced_blocks_preserves_line_count(self):
            text = "a\n```\nb\nc\n```\nd\n"
            self.assertEqual(len(strip_fenced_blocks(text).split("\n")),
                             len(text.split("\n")))
            self.assertNotIn("b", strip_fenced_blocks(text))

        def test_bom_prefixed_review_report_still_parses(self):
            """utf-8 (not -sig) glued the BOM to the first heading character."""
            self.review.write_bytes(b"\xef\xbb\xbf" + REVIEW_OK.encode("utf-8"))
            self._order(self.changed, self.review)
            r = self._run()
            self.assertTrue(r["review_found"])
            self.assertEqual(r["result"], "PASS")

        def test_multi_milestone_review_section_is_ambiguous(self):
            """One '## Review: M1 M2 M3' cannot review three milestones."""
            self.review.write_text(REVIEW_MULTI_MILESTONE, encoding="utf-8")
            self._order(self.changed, self.review)
            r = self._run()
            self.assertTrue(r["ambiguous_review_section"])
            self.assertEqual(r["verdict"], "Approve")   # verdict itself parses
            self.assertEqual(r["result"], "FAIL")
            self.assertTrue(any("ambiguous_review_section" in w
                                for w in r["warnings"]))

        def test_single_milestone_section_is_not_ambiguous(self):
            self.review.write_text(REVIEW_OK)
            self._order(self.changed, self.review)
            r = self._run()
            self.assertFalse(r["ambiguous_review_section"])
            self.assertEqual(r["result"], "PASS")
            self.assertEqual(section_milestone_ids("Milestone 3 — M3 auth"), ["3"])

        def test_missing_changed_file_is_structural(self):
            """An absent --changed-files path silently disabled staleness."""
            self.review.write_text(REVIEW_OK)
            self._order(self.changed, self.review)
            with self.assertRaises(GateError) as ctx:
                build_report(self._ns(
                    changed=[str(self.changed), str(self.dir / "gone.py")]))
            self.assertIn("changed_file_missing", str(ctx.exception))

        # ---- the shared gate ledger ----

        def _ledger_records(self, path):
            return [json.loads(l) for l in
                    Path(path).read_text(encoding="utf-8").splitlines() if l.strip()]

        def test_ledger_records_a_pass_run(self):
            self.review.write_text(REVIEW_OK)
            self._order(self.changed, self.review)
            ledger = self.dir / "logs" / "gates.jsonl"
            argv = ["--review-report", str(self.review), "--state", str(self.state),
                    "--milestone", "M3", "--changed-files", str(self.changed),
                    "--repo", str(self.dir), "--ledger", str(ledger)]
            self.assertEqual(main(argv), 0)
            rec = self._ledger_records(ledger)[-1]
            self.assertEqual(rec["gate"], "check_commit_gate.py")
            self.assertEqual(rec["verdict"], "PASS")
            self.assertEqual(rec["exit"], 0)
            self.assertEqual(rec["milestone"], "M3")
            self.assertEqual(rec["argv"], argv)
            self.assertEqual(rec["inputs"][str(self.changed)],
                             sha256_file(self.changed))
            self.assertTrue(rec["ts"].endswith("Z"))

        def test_ledger_records_a_usage_error_too(self):
            ledger = self.dir / "gates.jsonl"
            rc = main(["--milestone", "M3", "--ledger", str(ledger)])
            self.assertEqual(rc, 2)
            rec = self._ledger_records(ledger)[-1]
            self.assertEqual(rec["verdict"], "ERROR")
            self.assertEqual(rec["exit"], 2)

        def test_ledger_records_a_failing_run(self):
            self.review.write_text(REVIEW_RC)
            self._order(self.changed, self.review)
            ledger = self.dir / "gates.jsonl"
            rc = main(["--review-report", str(self.review), "--state",
                       str(self.state), "--milestone", "M3", "--changed-files",
                       str(self.changed), "--repo", str(self.dir),
                       "--ledger", str(ledger)])
            self.assertEqual(rc, 1)
            self.assertEqual(self._ledger_records(ledger)[-1]["verdict"], "FAIL")

        def _write_ledger(self, ledger, **over):
            rec = {"ts": "2026-09-02T00:00:00Z", "gate": "check_agent_report.py",
                   "argv": [], "milestone": "M3",
                   "inputs": {str(self.changed): sha256_file(self.changed)},
                   "verdict": "PASS", "exit": 0}
            rec.update(over)
            # Chained exactly as a real gate writes it -- a hand-written
            # unchained line is `legacy-after-chained` once anything has
            # chained, which is the contract, not a fixture bug.
            rec["prev"] = ledger_prev_hash(ledger)
            rec["self"] = ledger_self_hash(rec)
            with open(ledger, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec) + "\n")

        def test_require_ledger_gates_passes_on_a_backed_gate(self):
            self.review.write_text(REVIEW_OK)
            self._order(self.changed, self.review)
            ledger = self.dir / "gates.jsonl"
            self._write_ledger(ledger)
            r = build_report(self._ns(extra=[
                "--ledger", str(ledger),
                "--require-ledger-gates", "check_agent_report.py"]))
            self.assertEqual(r["ledger_gate_problems"], [])
            self.assertEqual(r["result"], "PASS")

        def test_require_ledger_gates_missing_entry_blocks(self):
            self.review.write_text(REVIEW_OK)
            self._order(self.changed, self.review)
            ledger = self.dir / "gates.jsonl"
            self._write_ledger(ledger, milestone="M9")
            r = build_report(self._ns(extra=[
                "--ledger", str(ledger),
                "--require-ledger-gates", "check_agent_report.py"]))
            self.assertEqual(r["result"], "FAIL")
            self.assertEqual(r["ledger_gate_problems"][0]["problem"],
                             "ledger_missing")

        def test_require_ledger_gates_failed_entry_blocks(self):
            self.review.write_text(REVIEW_OK)
            self._order(self.changed, self.review)
            ledger = self.dir / "gates.jsonl"
            self._write_ledger(ledger)
            self._write_ledger(ledger, verdict="FAIL", exit=1)  # latest wins
            r = build_report(self._ns(extra=[
                "--ledger", str(ledger),
                "--require-ledger-gates", "check_agent_report.py"]))
            self.assertEqual(r["result"], "FAIL")
            self.assertEqual(r["ledger_gate_problems"][0]["problem"],
                             "ledger_failed")

        def test_require_ledger_gates_stale_inputs_block(self):
            """A PASS is only evidence while the file it read is unchanged."""
            self.review.write_text(REVIEW_OK)
            ledger = self.dir / "gates.jsonl"
            self._write_ledger(ledger)
            self.changed.write_text("code edited after that gate ran\n")
            self._order(self.changed, self.review)
            r = build_report(self._ns(extra=[
                "--ledger", str(ledger),
                "--require-ledger-gates", "check_agent_report.py"]))
            self.assertEqual(r["result"], "FAIL")
            self.assertEqual(r["ledger_gate_problems"][0]["problem"],
                             "ledger_stale")

        def test_require_ledger_gates_accepts_an_unscoped_entry(self):
            self.review.write_text(REVIEW_OK)
            self._order(self.changed, self.review)
            ledger = self.dir / "gates.jsonl"
            self._write_ledger(ledger, milestone=None)
            r = build_report(self._ns(extra=[
                "--ledger", str(ledger),
                "--require-ledger-gates", "check_agent_report.py"]))
            self.assertEqual(r["result"], "PASS", r["warnings"])

        def test_require_ledger_gates_refuses_a_broken_chain(self):
            """An edited ledger record is not a weaker PASS; it is no PASS."""
            self.review.write_text(REVIEW_OK)
            self._order(self.changed, self.review)
            ledger = self.dir / "gates.jsonl"
            self._write_ledger(ledger)
            self._write_ledger(ledger, gate="check_runtime_evidence.py")
            lines = ledger.read_text(encoding="utf-8").splitlines()
            rec = json.loads(lines[0])
            rec["verdict"] = "PASS"
            rec["exit"] = 0
            rec["argv"] = ["tampered"]
            lines[0] = json.dumps(rec)
            ledger.write_text(chr(10).join(lines) + chr(10), encoding="utf-8")
            r = build_report(self._ns(extra=[
                "--ledger", str(ledger),
                "--require-ledger-gates", "check_agent_report.py"]))
            self.assertEqual(r["result"], "FAIL")
            self.assertEqual(r["ledger_gate_problems"][0]["problem"],
                             "ledger_chain_broken")
            self.assertIn("line 1", r["ledger_gate_problems"][0]["detail"])

        def test_require_ledger_gates_refuses_an_unchained_record_appended_after(self):
            self.review.write_text(REVIEW_OK)
            self._order(self.changed, self.review)
            ledger = self.dir / "gates.jsonl"
            self._write_ledger(ledger)
            with open(ledger, "a", encoding="utf-8") as fh:
                fh.write(json.dumps({
                    "ts": "2026-09-02T00:00:01Z", "gate": "check_agent_report.py",
                    "argv": [], "milestone": "M3", "inputs": {},
                    "verdict": "PASS", "exit": 0}) + chr(10))
            r = build_report(self._ns(extra=[
                "--ledger", str(ledger),
                "--require-ledger-gates", "check_agent_report.py"]))
            self.assertEqual(r["ledger_gate_problems"][0]["problem"],
                             "ledger_chain_broken")

        def test_require_ledger_gates_splits_a_comma_list(self):
            self.assertEqual(parse_gate_names(["a.py,b.py", "c.py"]),
                             ["a.py", "b.py", "c.py"])

        def test_require_ledger_gates_without_ledger_is_usage_error(self):
            self.assertEqual(main([
                "--review-report", str(self.review), "--state", str(self.state),
                "--milestone", "M3", "--changed-files", str(self.changed),
                "--require-ledger-gates", "check_agent_report.py"]), 2)

        # ---- --require-run-log / --require-agents ----------------------

        def _run_log(self, *entries):
            """A record_run.py-shaped run log; each entry is a kwargs dict."""
            log = self.dir / "run-log.jsonl"
            with open(log, "a", encoding="utf-8") as fh:
                for entry in entries:
                    rec = {"ts": "2026-09-05T00:00:00Z",
                           "pipeline": "bgpdd-build", "phase": "Phase 2",
                           "unit": "M3", "agent": None, "model": "sonnet",
                           "event": "delegation", "duration_s": None,
                           "tokens_in": None, "tokens_out": None,
                           "tokens_total": None, "rounds": None,
                           "status": "COMPLETE", "note": None}
                    rec.update(entry)
                    fh.write(json.dumps(rec) + chr(10))
            return log

        def _rl_report(self, log, agents="quinn,luna"):
            self.review.write_text(REVIEW_OK)
            self._order(self.changed, self.review)
            return build_report(self._ns(extra=[
                "--require-run-log", str(log), "--require-agents", agents]))

        def test_require_agents_passes_when_each_delegation_is_recorded(self):
            log = self._run_log({"agent": "quinn"}, {"agent": "luna"},
                                {"agent": "mason"})
            r = self._rl_report(log, "quinn,luna,mason")
            self.assertEqual(r["run_log_problems"], [])
            self.assertEqual(r["result"], "PASS")

        def test_require_agents_blocks_a_skipped_reviewer(self):
            """The hole: a green report with no Luna delegation behind it."""
            log = self._run_log({"agent": "quinn"})
            r = self._rl_report(log)
            self.assertEqual(r["result"], "FAIL")
            self.assertEqual(r["run_log_problems"][0]["problem"],
                             "run_log_agent_missing")
            self.assertEqual(r["run_log_problems"][0]["agent"], "luna")

        def test_require_agents_blocks_a_missing_run_log(self):
            r = self._rl_report(self.dir / "nope.jsonl")
            self.assertEqual(r["result"], "FAIL")
            self.assertEqual(r["run_log_problems"][0]["problem"],
                             "run_log_missing")

        def test_require_agents_blocks_a_hand_written_record_with_no_model(self):
            log = self._run_log({"agent": "quinn"},
                                {"agent": "luna", "model": None})
            r = self._rl_report(log)
            self.assertEqual(r["run_log_problems"][0]["problem"],
                             "run_log_model_missing")

        def test_require_agents_ignores_another_milestones_delegation(self):
            log = self._run_log({"agent": "quinn"},
                                {"agent": "luna", "unit": "M9"})
            r = self._rl_report(log)
            self.assertEqual(r["run_log_problems"][0]["problem"],
                             "run_log_agent_missing")

        def test_require_agents_does_not_accept_an_unscoped_delegation(self):
            """Tighter than --require-ledger-gates, on purpose (#8)."""
            log = self._run_log({"agent": "quinn"},
                                {"agent": "luna", "unit": None})
            r = self._rl_report(log)
            self.assertEqual(r["run_log_problems"][0]["problem"],
                             "run_log_agent_missing")

        def test_require_agents_ignores_non_delegation_events(self):
            log = self._run_log({"agent": "quinn"},
                                {"agent": "luna", "event": "note"})
            r = self._rl_report(log)
            self.assertEqual(r["run_log_problems"][0]["problem"],
                             "run_log_agent_missing")

        def test_require_agents_is_case_and_whitespace_insensitive(self):
            log = self._run_log({"agent": "Quinn"},
                                {"agent": "luna", "unit": " m3 "})
            self.assertEqual(self._rl_report(log)["run_log_problems"], [])

        def test_require_agents_accepts_a_later_record_carrying_the_model(self):
            """A round-1 record without a model is covered by round 2's."""
            log = self._run_log({"agent": "quinn", "model": None},
                                {"agent": "quinn", "model": "sonnet"},
                                {"agent": "luna"})
            self.assertEqual(self._rl_report(log)["run_log_problems"], [])

        def test_require_agents_without_a_run_log_is_usage_error(self):
            self.assertEqual(main([
                "--review-report", str(self.review), "--state", str(self.state),
                "--milestone", "M3", "--changed-files", str(self.changed),
                "--require-agents", "quinn,luna"]), 2)

        def test_require_run_log_without_agents_is_usage_error(self):
            log = self._run_log({"agent": "quinn"})
            self.assertEqual(main([
                "--review-report", str(self.review), "--state", str(self.state),
                "--milestone", "M3", "--changed-files", str(self.changed),
                "--require-run-log", str(log)]), 2)

        def test_run_log_is_hashed_into_this_runs_ledger_line(self):
            log = self._run_log({"agent": "quinn"}, {"agent": "luna"})
            ledger = self.dir / "gates.jsonl"
            self.review.write_text(REVIEW_OK)
            self._order(self.changed, self.review)
            main(["--review-report", str(self.review), "--state", str(self.state),
                  "--milestone", "M3", "--changed-files", str(self.changed),
                  "--repo", str(self.dir), "--ledger", str(ledger),
                  "--require-run-log", str(log), "--require-agents", "quinn,luna"])
            rec = self._ledger_records(ledger)[-1]
            self.assertEqual(rec["inputs"][str(log)], sha256_file(log))

        def test_parse_agent_names_splits_a_comma_list(self):
            self.assertEqual(parse_agent_names(["quinn,luna", "mason"]),
                             ["quinn", "luna", "mason"])

        # ---- --max-changed-files (the bugfix lane's fix-size bound) ----

        def _n_changed(self, n):
            """n existing source paths, all older than the review report."""
            paths = []
            for i in range(n):
                p = self.dir / f"src_{i}.py"
                p.write_text(f"code {i}\n")
                os.utime(p, (1000, 1000))
                paths.append(str(p))
            return paths

        def _waiver_doc(self, body="Approved by the user 2026-09-03: the null "
                                   "guard touches 7 call sites."):
            p = self.dir / "rca.md"
            p.write_text("# RCA: coupon-500\n\n## Root cause\n\nmissing guard\n\n"
                          f"## Size waiver\n\n{body}\n", encoding="utf-8")
            return str(p)

        def test_size_bound_under_the_limit_passes(self):
            self.review.write_text(REVIEW_OK)
            changed = self._n_changed(3)
            os.utime(self.review, (2000, 2000))
            r = build_report(self._ns(changed=changed,
                                       extra=["--max-changed-files", "5"]))
            self.assertEqual(r["result"], "PASS", r["warnings"])
            self.assertTrue(r["size_ok"])
            self.assertEqual(r["changed_file_count"], 3)

        def test_size_bound_exactly_at_the_limit_passes(self):
            self.review.write_text(REVIEW_OK)
            changed = self._n_changed(5)
            os.utime(self.review, (2000, 2000))
            r = build_report(self._ns(changed=changed,
                                       extra=["--max-changed-files", "5"]))
            self.assertEqual(r["result"], "PASS", r["warnings"])
            self.assertTrue(r["size_ok"])

        def test_size_bound_exceeded_without_waiver_fails(self):
            self.review.write_text(REVIEW_OK)
            changed = self._n_changed(7)
            os.utime(self.review, (2000, 2000))
            r = build_report(self._ns(changed=changed,
                                       extra=["--max-changed-files", "5"]))
            self.assertEqual(r["result"], "FAIL")
            self.assertFalse(r["size_ok"])
            self.assertEqual(r["changed_file_count"], 7)
            self.assertTrue(any("no --waiver was given" in w
                                for w in r["warnings"]))

        def test_size_bound_exceeded_with_waiver_passes(self):
            self.review.write_text(REVIEW_OK)
            changed = self._n_changed(7)
            waiver = self._waiver_doc()
            os.utime(self.review, (2000, 2000))
            r = build_report(self._ns(
                changed=changed,
                extra=["--max-changed-files", "5", "--waiver", waiver]))
            self.assertEqual(r["result"], "PASS", r["warnings"])
            self.assertTrue(r["size_ok"])
            self.assertTrue(r["size_waiver"]["satisfied"])
            self.assertTrue(any("waived by" in w for w in r["warnings"]))

        def test_size_bound_waiver_with_no_such_section_fails(self):
            self.review.write_text(REVIEW_OK)
            changed = self._n_changed(7)
            p = self.dir / "rca.md"
            p.write_text("# RCA\n\n## Root cause\n\nmissing guard\n",
                          encoding="utf-8")
            os.utime(self.review, (2000, 2000))
            r = build_report(self._ns(
                changed=changed,
                extra=["--max-changed-files", "5", "--waiver", str(p)]))
            self.assertEqual(r["result"], "FAIL")
            self.assertFalse(r["size_waiver"]["section_found"])

        def test_size_bound_empty_waiver_section_fails(self):
            self.review.write_text(REVIEW_OK)
            changed = self._n_changed(7)
            waiver = self._waiver_doc(body="")
            os.utime(self.review, (2000, 2000))
            r = build_report(self._ns(
                changed=changed,
                extra=["--max-changed-files", "5", "--waiver", waiver]))
            self.assertEqual(r["result"], "FAIL")
            self.assertTrue(r["size_waiver"]["section_found"])
            self.assertFalse(r["size_waiver"]["body_nonempty"])

        def test_size_bound_placeholder_waiver_section_fails(self):
            self.review.write_text(REVIEW_OK)
            changed = self._n_changed(7)
            waiver = self._waiver_doc(body="<one or two sentences>")
            os.utime(self.review, (2000, 2000))
            r = build_report(self._ns(
                changed=changed,
                extra=["--max-changed-files", "5", "--waiver", waiver]))
            self.assertEqual(r["result"], "FAIL")
            self.assertFalse(r["size_waiver"]["body_nonempty"])

        def test_size_bound_fenced_waiver_section_does_not_count(self):
            """A waiver pasted as a template inside a fence licenses nothing."""
            self.review.write_text(REVIEW_OK)
            changed = self._n_changed(7)
            p = self.dir / "rca.md"
            p.write_text("# RCA\n\nUse this shape:\n\n```markdown\n"
                          "## Size waiver\n\nApproved by the user.\n```\n",
                          encoding="utf-8")
            os.utime(self.review, (2000, 2000))
            r = build_report(self._ns(
                changed=changed,
                extra=["--max-changed-files", "5", "--waiver", str(p)]))
            self.assertEqual(r["result"], "FAIL")
            self.assertFalse(r["size_waiver"]["section_found"])

        # ---- the `pipeline` field is not an input to this gate ------------

        def test_pipeline_value_never_changes_the_verdict(self):
            """This gate MUST ignore `pipeline` entirely.

            `bgpdd-bugfix` depends on it: on its feature route the lane shares
            the epic's state file and deliberately never stamps its own
            `pipeline` value, so `/bgpdd-build` and `/bgpdd-shipping`
            re-hydrate the epic exactly as they would have before the fix.
            That design is only safe while this gate's verdict is independent
            of the field. The claim used to live as prose in that pipeline's
            spine; this test is the mechanical guard the spine now cites
            (CLAUDE.md convention #9).

            Byte-identical JSON is the assertion, not merely an equal
            `result`: a future term that only *reported* `pipeline` would
            still change what a caller reads.
            """
            self.review.write_text(REVIEW_OK)
            self._order(self.changed, self.review)
            base = {"blockers": [{"id": "B-1", "text": "unrelated open item",
                                   "milestone": "M9"}],
                    "project_name": "coupons",
                    "milestone_cursor": None}

            def verdict_json(pipeline_value):
                state = dict(base)
                if pipeline_value is not None:
                    state["pipeline"] = pipeline_value
                self.state.write_text(json.dumps(state))
                return json.dumps(build_report(self._ns()),
                                   indent=2, sort_keys=True)

            reference = verdict_json("bgpdd-build")
            for value in ("bgpdd-bugfix", "bgpdd-shipping", "bgpdd-plan",
                          "bgpdd-lite", "", "not-a-pipeline", None):
                self.assertEqual(
                    verdict_json(value), reference,
                    f"the gate's verdict changed for pipeline={value!r} — "
                    "bgpdd-bugfix's shared-state design depends on this field "
                    "being ignored here")
            self.assertNotIn('"pipeline"', reference,
                              "the gate must not echo `pipeline` into its "
                              "report either")

        def test_size_bound_multiline_placeholder_waiver_fails(self):
            """One `<...>` span wrapped across lines is still a placeholder."""
            self.review.write_text(REVIEW_OK)
            changed = self._n_changed(7)
            waiver = self._waiver_doc(body=(
                "<Delete this whole section unless the fix exceeds the file\n"
                "bound. When it does: one or two sentences naming how many\n"
                "files and that the user approved proceeding.>"))
            os.utime(self.review, (2000, 2000))
            r = build_report(self._ns(
                changed=changed,
                extra=["--max-changed-files", "5", "--waiver", waiver]))
            self.assertEqual(r["result"], "FAIL")
            self.assertTrue(r["size_waiver"]["section_found"])
            self.assertFalse(r["size_waiver"]["body_nonempty"])

        def test_the_shipped_rca_template_waiver_fails(self):
            """Copying the template must not license a wide fix.

            Mirror of check_bugfix_intake's template test: a template whose
            waiver section satisfies the gate is a complete bypass of the
            file bound.
            """
            template = (Path(__file__).resolve().parents[2]
                        / "bgpdd-bugfix" / "references" / "rca-template.md")
            if not template.is_file():
                self.skipTest(f"template not found at {template}")
            found, nonempty = read_size_waiver(str(template))
            self.assertTrue(found, "the template should carry the heading")
            self.assertFalse(
                nonempty,
                "the shipped rca-template.md '## Size waiver' body must NOT "
                "satisfy the gate")
            # ...and end to end, through the gate itself.
            self.review.write_text(REVIEW_OK)
            changed = self._n_changed(7)
            os.utime(self.review, (2000, 2000))
            r = build_report(self._ns(
                changed=changed,
                extra=["--max-changed-files", "5", "--waiver", str(template)]))
            self.assertEqual(r["result"], "FAIL")
            self.assertFalse(r["size_ok"])

        def test_size_bound_missing_waiver_file_fails(self):
            self.review.write_text(REVIEW_OK)
            changed = self._n_changed(7)
            os.utime(self.review, (2000, 2000))
            r = build_report(self._ns(
                changed=changed,
                extra=["--max-changed-files", "5",
                       "--waiver", str(self.dir / "nope.md")]))
            self.assertEqual(r["result"], "FAIL")
            self.assertFalse(r["size_waiver"]["present"])

        def test_size_bound_flag_unset_is_backcompat(self):
            self.review.write_text(REVIEW_OK)
            changed = self._n_changed(30)
            os.utime(self.review, (2000, 2000))
            r = build_report(self._ns(changed=changed))
            self.assertEqual(r["result"], "PASS")
            self.assertTrue(r["size_ok"])
            self.assertIsNone(r["max_changed_files"])
            self.assertIsNone(r["size_waiver"])

        def test_size_bound_usage_errors(self):
            base = ["--review-report", str(self.review), "--state",
                    str(self.state), "--milestone", "M3",
                    "--changed-files", str(self.changed)]
            self.assertEqual(main(base + ["--max-changed-files", "0"]), 2)
            self.assertEqual(main(base + ["--waiver", str(self.dir / "r.md")]), 2)

        def test_nonstandard_verdict_token_fails(self):
            self.review.write_text("## Review: M3\n\n**Verdict:** Approved\n")
            self._order(self.changed, self.review)
            r = self._run()
            self.assertEqual(r["result"], "FAIL")
            self.assertIsNone(r["verdict"])

        def test_verdict_after_earlier_valid_wins(self):
            self.review.write_text("## Review: M3\n\n**Verdict:** Approve\n"
                                   "**Verdict:** LGTM\n")
            self._order(self.changed, self.review)
            self.assertEqual(self._run()["result"], "FAIL")

        def test_missing_state_raises(self):
            self.review.write_text(REVIEW_OK)
            self.state.unlink()
            with self.assertRaises(GateError):
                self._run()

        def test_rendered_evidence_line_present_passes(self):
            self.review.write_text(REVIEW_EVIDENCE_LINE)
            self._order(self.changed, self.review)
            self._evidence()
            r = self._run(["--require-rendered-evidence"])
            self.assertEqual(r["result"], "PASS")
            self.assertTrue(r["rendered_evidence_ok"])
            self.assertIn("evidence/review/m3-table.png", r["rendered_evidence"])

        def test_zero_byte_rendered_evidence_fails(self):
            """`touch evidence/review/m3.png` was a complete bypass."""
            self.review.write_text(REVIEW_EVIDENCE_LINE)
            self._order(self.changed, self.review)
            self._evidence(data=b"")
            r = self._run(["--require-rendered-evidence"])
            self.assertEqual(r["result"], "FAIL")
            self.assertFalse(r["rendered_evidence_ok"])
            self.assertTrue(any("zero bytes" in w for w in r["warnings"]))

        def test_rendered_evidence_wrong_magic_bytes_fails(self):
            """A non-empty text file named `.png` depicts nothing either."""
            self.review.write_text(REVIEW_EVIDENCE_LINE)
            self._order(self.changed, self.review)
            self._evidence(data=b"not really a png at all")
            r = self._run(["--require-rendered-evidence"])
            self.assertEqual(r["result"], "FAIL")
            self.assertTrue(any("magic bytes" in w for w in r["warnings"]))

        def test_rendered_evidence_older_than_the_diff_fails(self):
            """Evidence that predates the change cannot depict the change."""
            self.review.write_text(REVIEW_EVIDENCE_LINE)
            evidence = self._evidence()
            os.utime(evidence, (500, 500))
            self._order(self.changed, self.review)   # changed=1000, review=2000
            r = self._run(["--require-rendered-evidence"])
            self.assertEqual(r["result"], "FAIL")
            self.assertFalse(r["rendered_evidence_ok"])
            self.assertTrue(any("predates" in w for w in r["warnings"]))

        def test_non_image_rendered_evidence_only_needs_to_be_non_empty(self):
            """The magic-byte rule applies to raster extensions only."""
            self.review.write_text(
                "## Review: M3 — Auth endpoints\n\n"
                "Rendered evidence: evidence/review/m3-table.md\n\n"
                "**Verdict:** Approve\n")
            self._order(self.changed, self.review)
            self._evidence(name="m3-table.md", data=b"| col |\n|---|\n")
            r = self._run(["--require-rendered-evidence"])
            self.assertEqual(r["result"], "PASS", r["warnings"])

        def test_rendered_evidence_missing_fails(self):
            self.review.write_text(REVIEW_EVIDENCE_LINE)  # path cited, not on disk
            self._order(self.changed, self.review)
            r = self._run(["--require-rendered-evidence"])
            self.assertEqual(r["result"], "FAIL")
            self.assertFalse(r["rendered_evidence_ok"])

        def test_rendered_evidence_markdown_image_passes(self):
            self.review.write_text(REVIEW_EVIDENCE_IMAGE)
            self._order(self.changed, self.review)
            self._evidence(name="m3-shot.png")
            r = self._run(["--require-rendered-evidence"])
            self.assertEqual(r["result"], "PASS")
            self.assertTrue(r["rendered_evidence_ok"])

        def test_rendered_evidence_flag_unset_is_backcompat(self):
            self.review.write_text(REVIEW_OK)  # no evidence cited anywhere
            self._order(self.changed, self.review)
            r = self._run()
            self.assertEqual(r["result"], "PASS")
            self.assertTrue(r["rendered_evidence_ok"])

        def test_rendered_evidence_build_dir_only_fails(self):
            # Existing evidence file, but cited under evidence/build/ (a
            # builder-produced artifact) rather than evidence/review/ (a
            # reviewer-produced one) -- must not satisfy the gate.
            self.review.write_text(REVIEW_EVIDENCE_BUILD_ONLY)
            self._order(self.changed, self.review)
            self._evidence(under="build")
            r = self._run(["--require-rendered-evidence"])
            self.assertEqual(r["result"], "FAIL")
            self.assertFalse(r["rendered_evidence_ok"])
            self.assertIn("evidence/build/m3-table.png", r["rendered_evidence"])

        def test_rendered_evidence_none_cited_fails(self):
            self.review.write_text(REVIEW_OK)  # no evidence citation at all
            self._order(self.changed, self.review)
            r = self._run(["--require-rendered-evidence"])
            self.assertEqual(r["result"], "FAIL")
            self.assertFalse(r["rendered_evidence_ok"])
            self.assertEqual(r["rendered_evidence"], [])

        def test_provenance_refuses_parent_traversal(self):
            """`lstrip("./")` collapsed '../evidence/review/x' to a passing path."""
            self.assertFalse(_cited_under_evidence_review("../evidence/review/x.png"))
            self.assertFalse(_cited_under_evidence_review("../../evidence/review/x.png"))
            # unchanged acceptances
            self.assertTrue(_cited_under_evidence_review("evidence/review/x.png"))
            self.assertTrue(_cited_under_evidence_review("./evidence/review/x.png"))
            self.assertTrue(_cited_under_evidence_review("/evidence/review/x.png"))
            self.assertTrue(_cited_under_evidence_review("evidence\\review\\x.png"))
            # still prefix-anchored: a nested prefix does NOT satisfy this
            # predicate (deliberate; check_runtime_evidence.py scans instead)
            self.assertFalse(_cited_under_evidence_review(
                ".docs/p/implementation/evidence/review/x.png"))

        @unittest.skipUnless(shutil.which("git"), "git not on PATH")
        def test_commit_on_pass(self):
            run_git(["init", "-q"], str(self.dir))
            run_git(["config", "user.email", "gate@test"], str(self.dir))
            run_git(["config", "user.name", "gate"], str(self.dir))
            self.review.write_text(REVIEW_OK)
            self._order(self.changed, self.review)
            ns = self._ns(milestone="M3", commit=True,
                           message="M3: auth endpoints (FR-1, FR-2)")
            r = build_report(ns)
            self.assertEqual(r["result"], "PASS")
            self.assertTrue(r["committed"])
            log = run_git(["log", "--oneline"], str(self.dir))
            self.assertIn("M3: auth endpoints", log)

        @unittest.skipUnless(shutil.which("git"), "git not on PATH")
        def test_commit_refused_when_fix_already_committed(self):
            """A builder committed the fix itself: the declared file is clean
            against HEAD, so the gate has nothing of its own to commit and must
            say so instead of passing around the outside commit."""
            run_git(["init", "-q"], str(self.dir))
            run_git(["config", "user.email", "gate@test"], str(self.dir))
            run_git(["config", "user.name", "gate"], str(self.dir))
            run_git(["add", "--", str(self.changed)], str(self.dir))
            run_git(["commit", "-q", "-m", "builder committed the fix"], str(self.dir))
            self.review.write_text(REVIEW_OK)
            self._order(self.changed, self.review)
            ns = self._ns(milestone="M3", commit=True,
                           message="M3: auth endpoints (FR-1, FR-2)")
            r = build_report(ns)
            self.assertEqual(r["result"], "FAIL")
            self.assertTrue(r["already_committed"])
            self.assertFalse(r["committed"])
            self.assertTrue(any("committed outside this gate" in w for w in r["warnings"]))
            log = run_git(["log", "--oneline"], str(self.dir))
            self.assertNotIn("M3: auth endpoints", log)

        @unittest.skipUnless(shutil.which("git"), "git not on PATH")
        def test_already_committed_not_checked_without_commit_flag(self):
            run_git(["init", "-q"], str(self.dir))
            run_git(["config", "user.email", "gate@test"], str(self.dir))
            run_git(["config", "user.name", "gate"], str(self.dir))
            run_git(["add", "--", str(self.changed)], str(self.dir))
            run_git(["commit", "-q", "-m", "already in"], str(self.dir))
            self.review.write_text(REVIEW_OK)
            self._order(self.changed, self.review)
            r = build_report(self._ns(milestone="M3"))
            self.assertEqual(r["result"], "PASS")
            self.assertFalse(r["already_committed"])

        @unittest.skipUnless(shutil.which("git"), "git not on PATH")
        def test_partial_prior_commit_still_commits_the_rest(self):
            """A context-checkpoint commit of PART of the work is legitimate:
            one declared file is already in HEAD, another is still dirty."""
            run_git(["init", "-q"], str(self.dir))
            run_git(["config", "user.email", "gate@test"], str(self.dir))
            run_git(["config", "user.name", "gate"], str(self.dir))
            run_git(["add", "--", str(self.changed)], str(self.dir))
            run_git(["commit", "-q", "-m", "checkpoint"], str(self.dir))
            other = self.dir / "src" / "Other.cs"
            other.parent.mkdir(parents=True, exist_ok=True)
            other.write_text("// more", encoding="utf-8")
            self.review.write_text(REVIEW_OK)
            self._order(self.changed, self.review)
            self._order(other, self.review)
            ns = self._ns(milestone="M3", commit=True,
                           changed=[str(self.changed), str(other)],
                           message="M3: auth endpoints (FR-1, FR-2)")
            r = build_report(ns)
            self.assertEqual(r["result"], "PASS", r["warnings"])
            self.assertTrue(r["committed"])

        def _init_repo_for_tree_check(self):
            run_git(["init", "-q"], str(self.dir))
            run_git(["config", "user.email", "gate@test"], str(self.dir))
            run_git(["config", "user.name", "gate"], str(self.dir))
            (self.dir / ".gitignore").write_text(
                "review-report.md\norchestrator-state.json\n")
            docs_dir = self.dir / ".docs"
            docs_dir.mkdir()
            self.docs_file = docs_dir / "state.md"
            self.docs_file.write_text("initial\n")
            run_git(["add", "-A"], str(self.dir))
            run_git(["commit", "-m", "init"], str(self.dir))

        @unittest.skipUnless(shutil.which("git"), "git not on PATH")
        def test_verify_tree_declared_and_docs_change_passes(self):
            self._init_repo_for_tree_check()
            self.changed.write_text("code changed\n")
            self.docs_file.write_text("updated\n")
            self.review.write_text(REVIEW_OK)
            self._order(self.changed, self.review)
            r = self._run(["--verify-tree"])
            self.assertEqual(r["result"], "PASS")
            self.assertTrue(r["tree_verified"])
            self.assertEqual(r["undeclared_changes"], [])

        @unittest.skipUnless(shutil.which("git"), "git not on PATH")
        def test_verify_tree_undeclared_tracked_change_fails(self):
            self._init_repo_for_tree_check()
            other = self.dir / "other_file.py"
            other.write_text("v1\n")
            run_git(["add", "-A"], str(self.dir))
            run_git(["commit", "-m", "add other"], str(self.dir))
            other.write_text("v2\n")
            self.review.write_text(REVIEW_OK)
            self._order(self.changed, self.review)
            r = self._run(["--verify-tree"])
            self.assertEqual(r["result"], "FAIL")
            self.assertFalse(r["tree_verified"])
            self.assertIn("other_file.py", r["undeclared_changes"])

        @unittest.skipUnless(shutil.which("git"), "git not on PATH")
        def test_verify_tree_undeclared_untracked_file_fails(self):
            self._init_repo_for_tree_check()
            stray = self.dir / "stray.py"
            stray.write_text("surprise\n")
            self.review.write_text(REVIEW_OK)
            self._order(self.changed, self.review)
            r = self._run(["--verify-tree"])
            self.assertEqual(r["result"], "FAIL")
            self.assertIn("stray.py", r["undeclared_changes"])

        @unittest.skipUnless(shutil.which("git"), "git not on PATH")
        def test_verify_tree_flag_unset_is_backcompat(self):
            self._init_repo_for_tree_check()
            stray = self.dir / "stray.py"
            stray.write_text("surprise\n")
            self.review.write_text(REVIEW_OK)
            self._order(self.changed, self.review)
            r = self._run()
            self.assertEqual(r["result"], "PASS")
            self.assertTrue(r["tree_verified"])
            self.assertEqual(r["undeclared_changes"], [])

        # -- Directory-entry porcelain lines (no scaffold commit at all) -----
        # `git status --porcelain` collapses an entirely-untracked directory
        # into one `?? <dir>/` line. These run against a FRESH `git init`
        # repo with zero commits (everything untracked), which is exactly
        # when that collapse happens -- unlike _init_repo_for_tree_check's
        # repos, which pre-track `.docs/` and `src/` via a scaffold commit.
        # review-report.md/orchestrator-state.json live outside the repo dir
        # so they never pollute `git status` for it.

        @unittest.skipUnless(shutil.which("git"), "git not on PATH")
        def test_verify_tree_fresh_repo_declared_file_in_untracked_dir_and_docs_pass(self):
            repo_dir = Path(tempfile.mkdtemp())
            try:
                run_git(["init", "-q"], str(repo_dir))
                run_git(["config", "user.email", "gate@test"], str(repo_dir))
                run_git(["config", "user.name", "gate"], str(repo_dir))
                src_dir = repo_dir / "src"
                src_dir.mkdir()
                declared_file = src_dir / "api.cs"
                declared_file.write_text("code\n")
                docs_dir = repo_dir / ".docs"
                docs_dir.mkdir()
                (docs_dir / "state.md").write_text("state\n")
                self.review.write_text(REVIEW_OK)
                self._order(self.changed, declared_file)
                self._order(declared_file, self.review)
                ns = self._ns(milestone="M3",
                              changed=[str(self.changed), str(declared_file)],
                              repo=str(repo_dir), extra=["--verify-tree"])
                r = build_report(ns)
                self.assertEqual(r["result"], "PASS")
                self.assertTrue(r["tree_verified"])
                self.assertEqual(r["undeclared_changes"], [])
            finally:
                shutil.rmtree(repo_dir, ignore_errors=True)

        @unittest.skipUnless(shutil.which("git"), "git not on PATH")
        def test_verify_tree_fresh_repo_untracked_dir_with_only_undeclared_files_fails(self):
            repo_dir = Path(tempfile.mkdtemp())
            try:
                run_git(["init", "-q"], str(repo_dir))
                run_git(["config", "user.email", "gate@test"], str(repo_dir))
                run_git(["config", "user.name", "gate"], str(repo_dir))
                stray_dir = repo_dir / "stray"
                stray_dir.mkdir()
                (stray_dir / "file.py").write_text("surprise\n")
                self.review.write_text(REVIEW_OK)
                self._order(self.changed, self.review)
                ns = self._ns(milestone="M3",
                              changed=[str(self.changed)],
                              repo=str(repo_dir), extra=["--verify-tree"])
                r = build_report(ns)
                self.assertEqual(r["result"], "FAIL")
                self.assertFalse(r["tree_verified"])
                self.assertIn("stray/", r["undeclared_changes"])
            finally:
                shutil.rmtree(repo_dir, ignore_errors=True)

    suite = unittest.defaultTestLoader.loadTestsFromTestCase(GateTests)
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
