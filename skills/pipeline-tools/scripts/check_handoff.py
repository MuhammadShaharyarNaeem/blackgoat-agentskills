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

SCAFFOLDING LEFT IN A COMPLETE ARTIFACT (`artifact_scaffolding_left`)
---------------------------------------------------------------------
`base-persona.md` § Incremental Persistence: "Sweep the scaffolding before you
return COMPLETE. The skeleton, its markers, and any note explaining that the
markers exist are working apparatus for you, not content for the reader."
That is a restraint asked for at the exact moment the agent most wants to
return -- the substance is written, the sweep is bookkeeping -- so convention
#9 says it becomes a command with an exit code.

On `<status>COMPLETE</status>` every existing text file cited in `<artifact>`
or `<changed_skills>` is READ and scanned for the skeleton's own vocabulary:
the base-persona placeholder marker (an underscore joined to `TODO`, as the
template writes it), a `TODO`-colon-`pending` phrase, an HTML/markdown
`<!-- TODO` or `<!-- skeleton` comment, and any line that EXPLAINS the markers
to the reader ("Note: the placeholder sections are filled in later"). A hit is
a finding naming file:line and which marker matched.

Three deliberate scoping decisions:

* `PARTIAL` and `BLOCKED` are EXEMPT. A partial artifact is supposed to carry
  its markers -- that is how § Incremental Persistence says to hand back
  unfinished work. The rule is about the word COMPLETE, not about markers.
* `<changed_files>` is NOT scanned. Source code legitimately carries a `TODO`,
  and the base-persona rule is about the artifact a reader reads.
* A marker inside a FENCED code block in the artifact IS a hit. This is the
  opposite of how the handoff text itself is read (`strip_fenced`, below) and
  the asymmetry is the point: a fenced `<handoff>` template is an
  ILLUSTRATION, and reading it as the report would let an example satisfy the
  gate -- whereas a fence inside a delivered artifact is still ink on the
  page, and a reader who scrolls past it sees an unfinished document. The
  escape for a page that must legitimately quote the marker (this gate's own
  reference doc, a lesson that names the marker) is `--allow-scaffolding
  "<reason>"`: it waives this ONE code, requires a non-empty reason, and
  records the reason in the ledger, exactly as `--allow-drift` and
  `--allow-tier-inversion` do elsewhere in this family.

BLOCKED_ON GRAMMAR ON A PARTIAL/BLOCKED HANDOFF (`blockers_uncategorised`)
----------------------------------------------------------------------------
Measured on epic slide-s5: Quinn was delegated four times on Milestone 1 and
returned PARTIAL every time with the same blocker -- no admin shell, no
installed Gorelo.Agent service, no dev token -- an environment wall only the
human could clear. About 1.2M tokens re-discovered that one fact, because a
PARTIAL/BLOCKED `<blockers>` value was free prose: honest, but nothing
downstream could act on it. `check_redelegation.py` is the gate that now
halts re-delegation on exactly that shape of blocker, and it can only do so
if the reason is a value, not a paragraph.

Whenever `<status>` is `PARTIAL` or `BLOCKED`, `<blockers>` must therefore
carry at least one line of the form:

    blocked_on: <category> — <one-line reason>

where `<category>` is one of `environment` (missing host, service, device,
elevation), `credentials` (token, secret, account), `dependency` (another
team's or another milestone's output), `spec` (ambiguous or contradictory
requirement), or `defect` (a failing test or bug the agent could not fix in
scope). A line is recognized with its surrounding backticks and leading list
marker stripped (the same tolerance `split_paths` gives `<changed_files>`),
and either an em dash, en dash, or plain hyphen as the separator. Missing the
line entirely, or naming a category outside the five, is `blockers_uncategorised`
(exit 1); the finding's detail prints this grammar so the fix is mechanical.

`COMPLETE` is EXEMPT, the same scoping `artifact_scaffolding_left` uses: this
rule is about the words PARTIAL/BLOCKED, not about `<blockers>` in general,
and an empty or absent `<blockers>` is already `element_missing` on every
persona (all of them require it) -- this check only fires once `<blockers>`
carries SOME non-blank text, so the two findings never duplicate the same gap.

Usage:
    python check_handoff.py --handoff <file> --persona <name> --repo <dir> \
        [--repo <dir> ...] [--docs-root <dir> ...] \
        [--since <ref>] [--advisory] [--fix-round] [--require consumers] \
        [--allow-scaffolding "<reason>"] \
        [--milestone "<title>"] [--ledger <path>]
    ... | python check_handoff.py --persona mason --repo .      # stdin
    python check_handoff.py --self-test

`--since <ref>` is OPTIONAL to this CLI and REQUIRED by the pipelines: it is
the only term here that git can contradict (without it `<changed_files>` need
merely exist; with it, a file the agent never touched is rejected). Every
pipeline handoff step passes `--since` and `--ledger`; a call without them
checks shape only and says nothing about what was actually written.

MULTIPLE REPOS AND A SHARED DOCS ROOT (`--repo`, `--docs-root`)
----------------------------------------------------------------
A workspace where `.docs/` (pipeline artifacts, reports, evidence) sits ABOVE
several separate git repos, and a milestone touches more than one of them,
breaks a gate that only knows one `--repo`: the artifact is always "outside"
and the other repo's changed files always "missing". `--repo` is therefore
REPEATABLE -- a `<changed_files>` path is accepted if it resolves (relative or
absolute, either slash style, case-insensitive drive letters) under ANY listed
repo, and `--since` runs `git diff --name-only <ref>` in the specific repo
that path resolved to, not the first one.

`--docs-root` is also repeatable and OPTIONAL: `<artifact>` and
`<changed_skills>` resolve under any `--repo` OR any `--docs-root`, but
`<changed_files>` never does -- source is source, and a file sitting under the
docs root next to the reports is not a code change. When `--docs-root` is
omitted, it defaults to the nearest ancestor directory of `--handoff` named
`.docs`, if any, so the common shared-docs layout needs no extra flag.

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
    "ward": DEFAULT_REQUIRED,
}

# `<consumers>` is standing-but-optional for exactly these two: their override
# says "when the brief asks for it". Any persona can be held to it with
# `--require consumers`; for the others the gate says so in a warning, because
# requiring an element no persona contract mentions is more likely a caller
# mistake than a real bar.
CONSUMERS_PERSONAS = ("mason", "nova")

# Elements whose values are file paths that must exist under --repo.
PATH_ELEMENTS = ("changed_files", "artifact", "changed_skills")

# Elements whose files are READ and swept for scaffolding on a COMPLETE
# handoff. `changed_files` is deliberately absent: source code legitimately
# carries a TODO, and base-persona's sweep rule is about the artifact a reader
# reads. See SCAFFOLDING LEFT IN A COMPLETE ARTIFACT above.
SCAFFOLD_ELEMENTS = ("artifact", "changed_skills")

# The skeleton's own vocabulary, in the order a line is tested. Each entry is
# (marker name reported in the finding, pattern). Written as escaped
# expressions rather than pasted literals wherever possible so that this file
# and its docs are not themselves hits.
SCAFFOLD_MARKERS = (
    # base-persona's placeholder marker: an underscore joined to TODO, as in
    # the template's `_ TODO : pending _` (spaced here). `\b` so a symbol like
    # `MY_TODOS` does not match -- and neither does a bare italic marker with
    # a trailing underscore, since both sides are then word characters. A
    # documented limit: the template's own form carries a colon and matches.
    ("skeleton_marker", re.compile(r"_" + r"TODO\b")),
    # The same idea spelled out in prose.
    ("todo_pending", re.compile(r"(?i)\bTODO:\s*pending\b")),
    # An HTML/markdown comment holding the scaffolding.
    ("todo_comment", re.compile(r"(?i)<!--\s*TODO")),
    ("skeleton_comment", re.compile(r"(?i)<!--\s*skeleton")),
    # A line that EXPLAINS the markers to the reader -- the third thing
    # base-persona names, and the one a sweep most often forgets because it
    # reads like prose rather than like apparatus.
    ("scaffolding_note", re.compile(
        r"(?i)^\s*(?:>|<!--)?\s*(?:note|nb):?\s.*\b(?:_" + r"TODO|placeholder"
        r"|skeleton)\b")),
)

# A file whose first block holds a NUL byte is not text. Read in one pass and
# tested on the whole buffer: an artifact is a document, not a stream.
NUL = b"\x00"

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

# `blocked_on:` grammar required in <blockers> whenever <status> is PARTIAL or
# BLOCKED. See BLOCKED_ON GRAMMAR in the module docstring for the measured
# cost this closes: `check_redelegation.py` halts re-delegation on exactly
# this shape of category, and can only do so mechanically once the reason is
# a value here, not prose.
BLOCKED_ON_CATEGORIES = ("environment", "credentials", "dependency", "spec",
                         "defect")
BLOCKED_ON_RE = re.compile(
    r"(?i)^blocked_on:\s*(?P<category>[A-Za-z_]+)\s*[—–-]\s*"
    r"(?P<reason>\S.*)$")
BLOCKED_ON_GRAMMAR = (
    "blocked_on: <category> — <one-line reason>, where <category> is "
    "one of environment (missing host, service, device, elevation), "
    "credentials (token, secret, account), dependency (another team's or "
    "milestone's output), spec (ambiguous or contradictory requirement), or "
    "defect (a failing test or bug out of scope)")


def parse_blocked_on_lines(blockers_text):
    """[(category_lower, reason, raw_line)] for every recognized
    `blocked_on:` line in `blockers_text`, in order.

    A line's leading list marker and surrounding backticks are stripped
    first -- the same tolerance `split_paths` and `check_consumers` give
    other <blockers>/<consumers> content, so a bullet-written line is not
    penalized. `category` is returned exactly as written, lower-cased; the
    caller decides whether it is one of `BLOCKED_ON_CATEGORIES`.
    """
    out = []
    for raw in blockers_text.splitlines():
        # Bullet marker stripped BEFORE backticks -- a bulleted, backtick-
        # wrapped line ("- `blocked_on: ...`") has its backtick right after
        # the marker, not at the string's own start.
        line = re.sub(r"^[-*+]\s+", "", raw.strip()).strip()
        line = line.strip("`").strip()
        m = BLOCKED_ON_RE.match(line)
        if m:
            out.append((m.group("category").strip().lower(),
                        m.group("reason").strip(), line))
    return out


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


def path_status(roots, raw):
    """('ok'|'missing'|'outside', normalized, matched_root, resolved_path).

    Tries `roots` in order. A relative path is joined onto each root in turn;
    an absolute path (either slash style) resolves to the same place every
    time and is simply tested against each root. Comparisons go through
    `Path.resolve()` on both sides, never a string prefix, so mixed slash
    style and Windows drive-letter case both resolve correctly.

    'ok': the path lies under some root AND exists there -- `matched_root` and
    `resolved_path` (an absolute Path) are set to where it was found.
    'missing': it lies under at least one root (so `roots` is the right shape
    of answer) but exists under none.
    'outside': it escapes every root (a `..` climb, or an absolute path
    nowhere near any of them) -- existence is not even checked.
    """
    rel = normalize_path(raw)
    candidate = Path(rel)
    in_some_root = False
    for root in roots:
        resolved = candidate if candidate.is_absolute() else Path(root) / rel
        try:
            resolved_abs = resolved.resolve()
            root_abs = Path(root).resolve()
        except OSError:
            continue
        try:
            resolved_abs.relative_to(root_abs)
        except ValueError:
            continue
        in_some_root = True
        if resolved_abs.exists():
            return "ok", rel, root, resolved_abs
    if in_some_root:
        return "missing", rel, None, None
    return "outside", rel, None, None


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
                                  capture_output=True, text=True,
                                  encoding="utf-8", errors="replace", timeout=120)
        except FileNotFoundError:
            raise GateError("git executable not found; --since cannot be checked")
        except subprocess.TimeoutExpired:
            raise GateError(f"git {args[0]} timed out after 120s")
        if proc.returncode != 0:
            raise GateError(
                f"git {' '.join(args)} in {repo} failed: "
                f"{proc.stderr.strip() or proc.stdout.strip()}")
        changed.update(normalize_path(line) for line in proc.stdout.splitlines()
                       if line.strip())
    return changed


def default_docs_root(handoff_path):
    """Nearest ancestor directory of `handoff_path` named `.docs`, or None.

    This is the CLI-level default for `--docs-root`: the common shape this
    gate was built for is an agent's handoff living somewhere under a shared
    `.docs/` tree that sits above the repos it reports on, and that default
    needs no extra flag on every pipeline call.
    """
    if not handoff_path:
        return None
    try:
        here = Path(handoff_path).resolve().parent
    except OSError:
        return None
    for parent in [here, *here.parents]:
        if parent.name == ".docs":
            return parent
    return None


INLINE_CODE_RE = re.compile(r"`[^`\n]*`")


def scan_scaffolding(path):
    """(hits, warning) for one artifact file.

    `hits` is [(lineno, marker_name, line_text)] in file order, at most one
    entry per line (the first marker that matches is the one reported -- the
    finding is "this line is apparatus", not a census of patterns). `warning`
    is a string when the file could not be swept and None otherwise; an
    unreadable or binary artifact is SKIPPED, never failed, because "the gate
    could not look" is not "the agent left a marker".
    """
    try:
        data = path.read_bytes()
    except OSError as exc:
        return [], f"could not read {path} to sweep for scaffolding: {exc}"
    if NUL in data:
        return [], (f"{path} is not a text file (NUL byte); skipped the "
                    "scaffolding sweep")
    text = data.decode("utf-8-sig", errors="replace")
    hits = []
    for number, line in enumerate(text.splitlines(), start=1):
        # Inline code spans are exempt: `_TODO: pending_` inside backticks is
        # how the convention is DOCUMENTED and cited (base-persona.md, this
        # family's own pages), never how an agent leaves a placeholder in an
        # artifact -- the skeleton writes the marker bare. Fenced blocks stay
        # in scope (documented asymmetry, see the module docstring).
        scanned = INLINE_CODE_RE.sub("", line)
        for name, pattern in SCAFFOLD_MARKERS:
            if pattern.search(scanned):
                hits.append((number, name, " ".join(line.split())[:200]))
                break
    return hits, None


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


def _as_root_list(value):
    """Normalize a single path or an iterable of paths into a list.

    Callers (tests especially) pass a single directory far more often than a
    list; accepting both here avoids forcing every existing call site to wrap
    its one repo in `[...]`.
    """
    if value is None:
        return []
    if isinstance(value, (str, Path)):
        return [value]
    return list(value)


def build_report(text, persona, repo, since=None, fix_round=False,
                 require=(), source="<stdin>", advisory=False,
                 allow_scaffolding=None, docs_root=None):
    persona_key = (persona or "").strip().lower()
    if persona_key not in PERSONA_ELEMENTS:
        known = ", ".join(sorted(PERSONA_ELEMENTS))
        raise GateError(f"unknown persona '{persona}'; expected one of: {known}")

    repos = _as_root_list(repo) or ["."]
    for r in repos:
        if not Path(r).is_dir():
            raise GateError(f"--repo is not a directory: {r}")
    docs_roots = _as_root_list(docs_root)
    for d in docs_roots:
        if not Path(d).is_dir():
            raise GateError(f"--docs-root is not a directory: {d}")

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
        "repo": [str(r) for r in repos],
        "docs_root": [str(d) for d in docs_roots],
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
        "scaffolding_scanned": [],
        "allow_scaffolding": None,
        "scaffolding_waived": [],
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
    scannable = []
    # <changed_files> is source: it resolves only under a --repo. <artifact>
    # and <changed_skills> are the report ABOUT that source, so they may also
    # live under a --docs-root that sits above the repos. Blurring this would
    # let a report path under the shared docs tree count as evidence of a
    # code change, which it is not.
    changed_files_repo = {}
    for name in PATH_ELEMENTS:
        if name not in elements:
            continue
        if name == "changed_files":
            roots = list(repos)
        else:
            # A relative <artifact>/<changed_skills> path is written from
            # wherever the Orchestrator ran the gate -- usually the workspace
            # root ABOVE .docs (so the handoff reads `.docs/bugfix/x/report.md`,
            # not `bugfix/x/report.md` relative to the docs-root itself). Fall
            # back to each docs-root's own parent, then the cwd, to catch that
            # shape. <changed_files> never gets these extra roots: it stays
            # strict, repo-relative or absolute under a --repo.
            roots = list(repos) + list(docs_roots)
            roots.extend(Path(d).resolve().parent for d in docs_roots)
            roots.append(Path.cwd())
        # De-duplicate (by resolved identity) so the reported root list, and
        # the search itself, is not padded with the same directory twice --
        # the docs-root's parent is often the cwd, and sometimes a --repo.
        seen = set()
        unique_roots = []
        for r in roots:
            try:
                key = str(Path(r).resolve())
            except OSError:
                key = str(r)
            if key not in seen:
                seen.add(key)
                unique_roots.append(r)
        roots = unique_roots
        roots_label = ", ".join(str(r) for r in roots)
        for raw in split_paths(elements[name]):
            state, rel, matched_root, resolved_path = path_status(roots, raw)
            declared.setdefault(name, []).append(rel)
            if state == "ok":
                if name in SCAFFOLD_ELEMENTS:
                    scannable.append((name, rel, resolved_path))
                if name == "changed_files":
                    changed_files_repo[rel] = (matched_root, resolved_path)
            if state == "missing":
                finding("path_missing", f"<{name}> names a path that does not "
                                        f"exist under any searched root "
                                        f"({roots_label}): {rel}",
                        element=name, path=rel)
            elif state == "outside":
                finding("path_missing", f"<{name}> names a path outside every "
                                        f"searched root ({roots_label}): {rel}",
                        element=name, path=rel)
    report["changed_files"] = declared.get("changed_files", [])
    report["artifacts"] = declared.get("artifact", [])
    report["changed_skills"] = declared.get("changed_skills", [])

    # The sweep base-persona asks for, on the one status that promises it was
    # done. PARTIAL/BLOCKED artifacts are supposed to carry their markers.
    if (report["status"] or "").strip().upper() == "COMPLETE":
        for element, rel, target in scannable:
            if not target.is_file():
                continue
            hits, warning = scan_scaffolding(target)
            if warning:
                report["warnings"].append(warning)
                continue
            report["scaffolding_scanned"].append(rel)
            for number, marker, line in hits:
                finding("artifact_scaffolding_left",
                        f"<{element}> {rel}:{number} still carries the "
                        f"{marker} scaffolding marker in a COMPLETE handoff: "
                        f"{line} — base-persona § Incremental Persistence: "
                        "the skeleton, its markers and any note explaining "
                        "them are working apparatus for you, not content for "
                        "the reader. Sweep them, or return PARTIAL",
                        element=element, path=rel, line=number,
                        marker=marker, text=line)

    if since:
        # Each path is diffed in the repo IT resolved to, not the first one
        # listed -- a milestone that touches two repos needs both checked
        # against their own history. A path that never resolved (already a
        # path_missing finding above) has nothing to diff and is skipped.
        touched_cache = {}
        for rel in report["changed_files"]:
            resolution = changed_files_repo.get(rel)
            if resolution is None:
                continue
            matched_root, resolved_path = resolution
            root_key = str(Path(matched_root).resolve())
            if root_key not in touched_cache:
                touched_cache[root_key] = git_changed_since(matched_root, since)
            root_abs = Path(matched_root).resolve()
            repo_rel = normalize_path(str(resolved_path.relative_to(root_abs)))
            if repo_rel not in touched_cache[root_key]:
                finding("changed_files_not_in_diff",
                        f"<changed_files> names {rel}, which git does not "
                        f"report as changed or committed since {since} in "
                        f"{matched_root}",
                        path=rel, since=since)
        report["git_changed_count"] = sum(len(v) for v in touched_cache.values())

    if "consumers" in elements:
        for bad in check_consumers(elements["consumers"]):
            finding("consumers_grammar",
                    f"<consumers> line is not `path::symbol`: {bad}", line=bad)

    for problem in check_honesty(elements):
        finding("honesty_contradiction",
                f"{problem['rule']} in <{problem['element']}>: {problem['detail']}",
                rule=problem["rule"], element=problem["element"])

    # blocked_on: grammar (see BLOCKED_ON GRAMMAR above). COMPLETE is exempt,
    # the same scoping artifact_scaffolding_left uses for its own word. An
    # absent or all-blank <blockers> is already element_missing on every
    # persona (all of them require it) -- this only fires once <blockers>
    # carries SOME non-blank text, so the two findings never double up on the
    # same gap.
    if (report["status"] or "").strip().upper() in ("PARTIAL", "BLOCKED"):
        blockers_text = "\n".join(elements.get("blockers", []))
        if blockers_text.strip():
            categorised = parse_blocked_on_lines(blockers_text)
            if not any(cat in BLOCKED_ON_CATEGORIES for cat, _, _ in categorised):
                finding("blockers_uncategorised",
                        "<blockers> names no recognized `blocked_on:` line "
                        f"for a {report['status'].strip().upper()} handoff -- "
                        f"required grammar: {BLOCKED_ON_GRAMMAR}",
                        status=report["status"])

    # --allow-scaffolding waives this ONE code and nothing else, and only
    # after it has been computed -- so the ledger records WHAT was waived.
    if allow_scaffolding and allow_scaffolding.strip():
        waived = [f for f in report["findings"]
                  if f["code"] == "artifact_scaffolding_left"]
        if waived:
            report["findings"] = [f for f in report["findings"]
                                  if f["code"] != "artifact_scaffolding_left"]
            report["scaffolding_waived"] = waived
            report["allow_scaffolding"] = allow_scaffolding.strip()
            report["warnings"].append(
                "SCAFFOLDING WAIVED by --allow-scaffolding for {0}: {1}".format(
                    ", ".join(sorted({f["path"] for f in waived})),
                    allow_scaffolding.strip()))

    report["result"] = "FAIL" if report["findings"] else "PASS"
    return report


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


PURPOSE = ("Decides whether an agent's handoff block satisfies that persona's "
           "contract: required elements, real paths, honest status, "
           "categorised blockers.")

EPILOG = """\
Reads:
  --handoff  the agent's returned text (stdin when omitted). One
    well-formed <handoff>...</handoff> block OUTSIDE fenced code: fences are
    blanked first, so an illustration never satisfies it.
    Required elements per persona (base-persona.md plus the persona's own
    "Base Persona Override"): mason, max -> <changed_files>; dep, quinn, nova
    -> <changed_files> + <artifact>; forge -> <changed_skills>; all others ->
    <artifact>. <status> and <blockers> are always required;
    <fix_verification> is required under --fix-round, and <consumers>
    (mason, nova) under --require consumers. agents/blackgoat.md is not a
    persona here: usage error.
      <status>    COMPLETE | PARTIAL | BLOCKED -- the DELIVERY state, not a
                  verification verdict, which belongs in the body.
      <blockers>  on PARTIAL or BLOCKED, at least one line
                    blocked_on: <category> - <reason>
                  with <category> one of environment, credentials,
                  dependency, spec, defect. COMPLETE is exempt; an absent
                  <blockers> is element_missing instead, never both.
      <consumers> lines in path::symbol grammar.
    Honesty rules: an upper-case PASS/GREEN token beside a NOT VERIFIED or
    BLOCKED marker in the SAME element, and BLOCKED beside
    <blockers>None</blockers>.
  Cited files  every <changed_files>/<artifact>/<changed_skills> path must
    exist under a --repo and not escape it. <artifact> and <changed_skills>
    (never <changed_files>) also resolve under a --docs-root, its parent, and
    the cwd. With --since, <changed_files> must be a subset of
    git diff --name-only <ref> plus untracked.
  Scaffolding sweep  on COMPLETE, every existing TEXT file in
    <artifact>/<changed_skills> is read for base-persona's placeholder marker
    (an underscore joined to TODO), a TODO-colon-pending phrase, an HTML
    comment opening TODO or skeleton, and any line EXPLAINING the markers. A
    marker in an inline code span is not a hit; one in a fence IS.
    PARTIAL/BLOCKED are exempt; <changed_files> is not swept.

Problem codes:
  handoff_missing            no well-formed unfenced <handoff> block
  element_missing            a required element is absent or empty
  path_missing               a cited path does not exist, or escapes the repo
  changed_files_not_in_diff  --since only: a file the agent never touched
  status_invalid             <status> is not COMPLETE / PARTIAL / BLOCKED
  consumers_grammar          a <consumers> line is not path::symbol
  honesty_contradiction      a PASS/GREEN token beside NOT VERIFIED/BLOCKED
  artifact_scaffolding_left  a COMPLETE artifact still carries a marker
  blockers_uncategorised     PARTIAL/BLOCKED with no blocked_on: line

JSON keys:
  result, persona, since, fix_round, advisory, advisory_waived_elements,
  required_elements, present_elements, status, changed_files, artifacts,
  changed_skills, scaffolding_scanned, allow_scaffolding, scaffolding_waived,
  findings ({code, detail, ...}; a scaffolding finding adds path, line,
  marker, text), warnings, error. Ledger extras: advisory: true;
  allow_scaffolding_reason plus the waived {path, line, marker} entries.

Exit codes:
  0  PASS
  1  at least one finding
  2  usage, an unreadable handoff, an unknown persona, a --repo/--docs-root
     that is not a directory, a --since ref git cannot resolve in the repo a
     changed file resolved to, or a blank --allow-scaffolding reason

Self-test:
  python check_handoff.py --self-test   (67 cases)
"""


def main(argv):
    parser = PurposeFirstParser(
        prog="check_handoff.py",
        description=PURPOSE,
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--handoff", help="file holding the agent's handoff "
                                          "(default: read stdin)")
    parser.add_argument("--persona", help="squad persona that produced it")
    parser.add_argument("--repo", action="append", default=None,
                        help="repository root the handoff's paths are relative "
                             "to. Repeatable: a <changed_files> path is "
                             "accepted if it resolves under ANY listed repo. "
                             "Defaults to '.' when omitted.")
    parser.add_argument("--docs-root", dest="docs_root", action="append",
                        default=None,
                        help="a directory holding cross-repo artifacts/reports "
                             "(e.g. a shared .docs/ tree above several repos). "
                             "Repeatable. <artifact> and <changed_skills> "
                             "additionally resolve under any --docs-root; "
                             "<changed_files> never does. Defaults to the "
                             "nearest ancestor of --handoff named '.docs', if "
                             "any.")
    parser.add_argument("--since", help="git ref: <changed_files> must be a "
                                        "subset of what git reports changed "
                                        "since it. Optional here, REQUIRED by "
                                        "every pipeline handoff step: it is "
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
    parser.add_argument("--allow-scaffolding", dest="allow_scaffolding",
                        help="a written reason for a COMPLETE artifact that "
                             "legitimately carries a scaffolding marker (a "
                             "page that QUOTES the marker). Waives "
                             "artifact_scaffolding_left and nothing else; the "
                             "reason is recorded in the ledger. An empty "
                             "reason is exit 2.")
    parser.add_argument("--milestone", help="recorded in the ledger line")
    parser.add_argument("--ledger", help="append one JSON record per run to this path")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)

    if args.self_test:
        return run_self_test()

    extra = {}
    if args.advisory:
        extra["advisory"] = True

    def finish(code, verdict):
        """One exit point: EVERY return path records a ledger line."""
        append_ledger(args.ledger, argv, args.milestone,
                      [args.handoff] if args.handoff else [], verdict, code,
                      dict(extra) or None)
        return code

    if not args.persona:
        print(json.dumps({"result": "ERROR",
                          "error": "missing required argument: --persona"}))
        return finish(2, "ERROR")

    if args.allow_scaffolding is not None and not args.allow_scaffolding.strip():
        print(json.dumps({
            "result": "ERROR",
            "error": "--allow-scaffolding requires a non-empty reason: an "
                     "unreasoned waiver is indistinguishable from an "
                     "omission, and this is the one waiver that says a "
                     "COMPLETE artifact may keep its skeleton's vocabulary"}))
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

    repos = args.repo if args.repo else ["."]
    docs_roots = list(args.docs_root) if args.docs_root else []
    if not docs_roots and args.handoff:
        auto = default_docs_root(args.handoff)
        if auto is not None:
            docs_roots = [str(auto)]

    try:
        report = build_report(text, args.persona, repos, since=args.since,
                              fix_round=args.fix_round, require=args.require,
                              source=source, advisory=args.advisory,
                              allow_scaffolding=args.allow_scaffolding,
                              docs_root=docs_roots)
    except GateError as exc:
        print(json.dumps({"result": "ERROR", "error": str(exc)}))
        return finish(2, "ERROR")

    if report.get("allow_scaffolding"):
        extra["allow_scaffolding_reason"] = report["allow_scaffolding"]
        extra["scaffolding_waived"] = [
            {"path": f["path"], "line": f["line"], "marker": f["marker"]}
            for f in report["scaffolding_waived"]]

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
                                  capture_output=True, text=True,
                                  encoding="utf-8", errors="replace", timeout=120)

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

        # --- artifact_scaffolding_left (base-persona: sweep before COMPLETE)

        def artifact_handoff(self, status="COMPLETE", path="docs.md"):
            return (f"<handoff><status>{status}</status>"
                    f"<artifact>{path}</artifact>"
                    "<blockers>None</blockers></handoff>")

        def write_docs(self, body):
            (self.dir / "docs.md").write_text(body, encoding="utf-8")

        def test_complete_with_a_clean_artifact_passes(self):
            self.write_docs("# Report\n\nEverything is written.\n")
            r = build_report(self.artifact_handoff(), "luna", self.dir)
            self.assertEqual(r["result"], "PASS", r["findings"])
            self.assertEqual(r["scaffolding_scanned"], ["docs.md"])

        def test_complete_with_a_skeleton_marker_fails(self):
            self.write_docs("# Report\n\n## Findings\n\n_TODO: pending_\n")
            r = build_report(self.artifact_handoff(), "luna", self.dir)
            self.assertEqual(self.codes(r), ["artifact_scaffolding_left"])
            hit = r["findings"][0]
            self.assertEqual((hit["path"], hit["line"], hit["marker"]),
                             ("docs.md", 5, "skeleton_marker"))
            self.assertIn("docs.md:5", hit["detail"])

        def test_partial_and_blocked_keep_their_markers(self):
            """§ Incremental Persistence hands unfinished work back WITH the
            markers; the rule is about the word COMPLETE."""
            self.write_docs("# Report\n\n_TODO: pending_\n")
            for status in ("PARTIAL", "BLOCKED"):
                r = build_report(
                    self.artifact_handoff(status).replace(
                        "<blockers>None</blockers>",
                        "<blockers>blocked_on: dependency — section 2 needs "
                        "the DB team's migration</blockers>"),
                    "luna", self.dir)
                self.assertEqual(r["result"], "PASS", (status, r["findings"]))
                self.assertEqual(r["scaffolding_scanned"], [], status)

        def test_every_marker_shape_is_a_hit(self):
            bodies = {
                "skeleton_marker": "# R\n\n_TODO: fill in_\n",
                "todo_pending": "# R\n\nTODO: pending — fill this in\n",
                "todo_comment": "# R\n\n<!-- TODO: write section 3 -->\n",
                "skeleton_comment": "# R\n\n<!-- skeleton generated -->\n",
                "scaffolding_note": "# R\n\n> Note: the placeholder sections "
                                    "are filled in on the second pass\n",
            }
            for marker, body in bodies.items():
                self.write_docs(body)
                r = build_report(self.artifact_handoff(), "luna", self.dir)
                self.assertEqual(self.codes(r), ["artifact_scaffolding_left"],
                                 marker)
                self.assertEqual(r["findings"][0]["marker"], marker, marker)

        def test_a_marker_inside_a_fence_is_still_a_hit(self):
            """Documented asymmetry: a fenced <handoff> is an ILLUSTRATION and
            must not satisfy the gate, but a fence in a DELIVERED artifact is
            still ink the reader scrolls past."""
            self.write_docs("# R\n\nAs the convention says:\n\n```\n"
                            "_TODO: pending_\n```\n")
            r = build_report(self.artifact_handoff(), "luna", self.dir)
            self.assertEqual(self.codes(r), ["artifact_scaffolding_left"])
            self.assertEqual(r["findings"][0]["line"], 6)

        def test_a_marker_quoted_in_inline_code_is_documentation(self):
            """base-persona.md and this family's pages cite `_TODO: pending_`
            in backticks; that is how the convention is documented, not a
            placeholder left in an artifact. A bare marker on the same page
            still fires."""
            self.write_docs("# R\n\nMark gaps with `_TODO: pending_` while "
                            "drafting.\n\nAll sections complete.\n")
            r = build_report(self.artifact_handoff(), "luna", self.dir)
            self.assertEqual(r["result"], "PASS", r["findings"])
            self.write_docs("# R\n\nMark gaps with `_TODO: pending_`.\n\n"
                            "## API\n_TODO: pending_\n")
            r = build_report(self.artifact_handoff(), "luna", self.dir)
            self.assertEqual(self.codes(r), ["artifact_scaffolding_left"])
            self.assertEqual(r["findings"][0]["line"], 6)

        def test_changed_files_are_not_swept(self):
            """Source code legitimately carries a TODO."""
            (self.dir / "src" / "a.py").write_text(
                "# TODO: pending refactor\n", encoding="utf-8")
            r = build_report(GOOD_MASON, "mason", self.dir)
            self.assertEqual(r["result"], "PASS", r["findings"])
            self.assertEqual(r["scaffolding_scanned"], [])

        def test_changed_skills_are_swept(self):
            self.write_docs("# Skill\n\n<!-- skeleton -->\n")
            text = ("<handoff><status>COMPLETE</status>"
                    "<changed_skills>docs.md</changed_skills>"
                    "<blockers>None</blockers></handoff>")
            r = build_report(text, "forge", self.dir)
            self.assertEqual(self.codes(r), ["artifact_scaffolding_left"])
            self.assertEqual(r["findings"][0]["element"], "changed_skills")

        def test_advisory_handoff_with_no_artifact_is_unaffected(self):
            r = build_report(self.FORGE_PROPOSE, "forge", self.dir,
                             advisory=True)
            self.assertEqual(r["result"], "PASS", r["findings"])
            self.assertEqual(r["scaffolding_scanned"], [])

        def test_a_binary_artifact_is_skipped_with_a_warning(self):
            blob = self.dir / "cap.bin"
            blob.write_bytes(b"PNG\x00\x00_TODO: pending_")
            r = build_report(self.artifact_handoff(path="cap.bin"), "luna",
                             self.dir)
            self.assertEqual(r["result"], "PASS", r["findings"])
            self.assertEqual(r["scaffolding_scanned"], [])
            self.assertTrue(any("not a text file" in w for w in r["warnings"]))

        def test_allow_scaffolding_waives_only_this_code(self):
            self.write_docs("# R\n\n_TODO: pending_\n")
            r = build_report(self.artifact_handoff(), "luna", self.dir,
                             allow_scaffolding="the page QUOTES the marker")
            self.assertEqual(r["result"], "PASS", r["findings"])
            self.assertEqual(r["allow_scaffolding"],
                             "the page QUOTES the marker")
            self.assertEqual(len(r["scaffolding_waived"]), 1)
            self.assertTrue(any("SCAFFOLDING WAIVED" in w
                                for w in r["warnings"]))
            # ...and nothing else: a missing element still fails.
            bad = ("<handoff><status>COMPLETE</status>"
                   "<artifact>docs.md</artifact></handoff>")
            r = build_report(bad, "luna", self.dir, allow_scaffolding="quoted")
            self.assertEqual(self.codes(r), ["element_missing"])

        def test_allow_scaffolding_exit_codes_and_ledger_through_main(self):
            self.write_docs("# R\n\n_TODO: pending_\n")
            path = self.dir / "h.md"
            path.write_text(self.artifact_handoff(), encoding="utf-8")
            ledger = self.dir / "gates.jsonl"
            base = ["--handoff", str(path), "--persona", "luna",
                    "--repo", str(self.dir), "--ledger", str(ledger)]
            self.assertEqual(main(base), 1)
            self.assertEqual(main(base + ["--allow-scaffolding", "   "]), 2)
            self.assertEqual(
                main(base + ["--allow-scaffolding", "quotes the marker"]), 0)
            record = json.loads(
                ledger.read_text(encoding="utf-8").splitlines()[-1])
            self.assertEqual(record["allow_scaffolding_reason"],
                             "quotes the marker")
            self.assertEqual(record["scaffolding_waived"][0]["marker"],
                             "skeleton_marker")
            self.assertEqual(record["self"], ledger_self_hash(record))

        def test_a_clean_run_records_no_scaffolding_keys(self):
            self.write_docs("# R\n\nclean\n")
            path = self.dir / "h.md"
            path.write_text(self.artifact_handoff(), encoding="utf-8")
            ledger = self.dir / "gates.jsonl"
            self.assertEqual(main(["--handoff", str(path), "--persona", "luna",
                                   "--repo", str(self.dir),
                                   "--ledger", str(ledger),
                                   "--allow-scaffolding", "unused"]), 0)
            record = json.loads(
                ledger.read_text(encoding="utf-8").splitlines()[-1])
            self.assertNotIn("allow_scaffolding_reason", record)

        def test_every_hit_line_is_reported_once(self):
            self.write_docs("# R\n\n_TODO: a_\n\n<!-- TODO -->\n"
                            "_TODO: pending_\n")
            r = build_report(self.artifact_handoff(), "luna", self.dir)
            self.assertEqual([f["line"] for f in r["findings"]], [3, 5, 6])

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
                    "<blockers>blocked_on: environment — no test DB in this "
                    "environment</blockers></handoff>")
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

        # --- multi-repo / --docs-root (the Gorelo shape) -----------------
        # `.docs/` sits ABOVE several independent git repos, and a milestone
        # often touches more than one repo. Recreated here as a `.docs` dir
        # beside two tiny git repos, each with one commit.

        def make_multi_repo(self):
            root = self.dir / "gorelo"
            docs = root / ".docs"
            docs.mkdir(parents=True)
            repo1, repo2 = root / "repo1", root / "repo2"
            for repo, fname, body in ((repo1, "one.py", "one"),
                                      (repo2, "two.py", "two")):
                (repo / "src").mkdir(parents=True)
                (repo / "src" / fname).write_text(body, encoding="utf-8")
            refs = [self._init_repo(repo) for repo in (repo1, repo2)]
            return docs, repo1, repo2, refs[0], refs[1]

        def _init_repo(self, repo):
            def run(*args):
                return subprocess.run(["git", "-C", str(repo)] + list(args),
                                      capture_output=True, text=True,
                                      encoding="utf-8", errors="replace", timeout=120)
            try:
                if run("init", "-q").returncode != 0:
                    self.skipTest("git init failed")
            except FileNotFoundError:
                self.skipTest("git not available")
            run("config", "user.email", "t@t.t")
            run("config", "user.name", "t")
            run("add", "-A")
            run("commit", "-qm", "base")
            return run("rev-parse", "HEAD").stdout.strip()

        def test_artifact_under_docs_root_passes(self):
            docs, repo1, repo2, ref1, ref2 = self.make_multi_repo()
            (docs / "report.md").write_text("# Report\n\ndone\n", encoding="utf-8")
            text = ("<handoff><status>COMPLETE</status>"
                    f"<artifact>{docs / 'report.md'}</artifact>"
                    "<blockers>None</blockers></handoff>")
            r = build_report(text, "luna", [repo1, repo2], docs_root=[docs])
            self.assertEqual(r["result"], "PASS", r["findings"])
            self.assertEqual(r["artifacts"], [normalize_path(str(docs / "report.md"))])

        def test_changed_file_in_second_repo_passes_with_two_repo(self):
            docs, repo1, repo2, ref1, ref2 = self.make_multi_repo()
            text = ("<handoff><status>COMPLETE</status>"
                    "<changed_files>src/one.py, src/two.py</changed_files>"
                    "<blockers>None</blockers></handoff>")
            r = build_report(text, "mason", [repo1, repo2])
            self.assertEqual(r["result"], "PASS", r["findings"])
            # And confirms the non-multi-repo behavior: a single --repo can't
            # see the other repo's file.
            r_single = build_report(text, "mason", [repo1])
            self.assertEqual(self.codes(r_single), ["path_missing"])
            self.assertEqual(r_single["findings"][0]["path"], "src/two.py")

        def test_changed_file_listed_under_docs_root_fails(self):
            """<changed_files> is source, never the report -- a path under
            --docs-root does not satisfy it even though --docs-root exists."""
            docs, repo1, repo2, ref1, ref2 = self.make_multi_repo()
            (docs / "report.md").write_text("done", encoding="utf-8")
            text = ("<handoff><status>COMPLETE</status>"
                    f"<changed_files>{docs / 'report.md'}</changed_files>"
                    "<blockers>None</blockers></handoff>")
            r = build_report(text, "mason", [repo1, repo2], docs_root=[docs])
            self.assertEqual(self.codes(r), ["path_missing"])
            self.assertIn("changed_files", r["findings"][0]["element"])

        def test_since_checks_the_repo_a_file_resolved_to(self):
            docs, repo1, repo2, ref1, ref2 = self.make_multi_repo()
            (repo1 / "src" / "untouched.py").write_text("u", encoding="utf-8")
            subprocess.run(["git", "-C", str(repo1), "add", "-A"],
                           capture_output=True, text=True, timeout=120)
            subprocess.run(["git", "-C", str(repo1), "commit", "-qm", "add"],
                           capture_output=True, text=True, timeout=120)
            for repo in (repo1, repo2):
                subprocess.run(["git", "-C", str(repo), "tag", "start"],
                               capture_output=True, text=True, timeout=120)
            (repo1 / "src" / "one.py").write_text("one-edited", encoding="utf-8")
            (repo2 / "src" / "two.py").write_text("two-edited", encoding="utf-8")

            text = ("<handoff><status>COMPLETE</status>"
                    "<changed_files>src/one.py, src/two.py</changed_files>"
                    "<blockers>None</blockers></handoff>")
            r = build_report(text, "mason", [repo1, repo2], since="start")
            self.assertEqual(r["result"], "PASS", r["findings"])

            # untouched.py resolves to repo1 (it only exists there) and was
            # committed BEFORE the tag, so it never shows up in repo1's own
            # diff -- proving the diff ran against the repo it resolved to,
            # not just whichever repo happened to pass.
            bad = text.replace("src/two.py",
                               "src/two.py, src/untouched.py")
            r2 = build_report(bad, "mason", [repo1, repo2], since="start")
            self.assertEqual(self.codes(r2), ["changed_files_not_in_diff"])
            self.assertEqual(r2["findings"][0]["path"], "src/untouched.py")

        def test_default_docs_root_is_discovered_from_the_handoff_path(self):
            docs, repo1, repo2, ref1, ref2 = self.make_multi_repo()
            handoff_dir = docs / "milestone1"
            handoff_dir.mkdir()
            handoff_path = handoff_dir / "handoff.md"
            report_path = docs / "report.md"
            report_path.write_text("# Report\n\ndone\n", encoding="utf-8")
            handoff_path.write_text(
                "<handoff><status>COMPLETE</status>"
                f"<artifact>{report_path}</artifact>"
                "<blockers>None</blockers></handoff>", encoding="utf-8")
            code = main(["--handoff", str(handoff_path), "--persona", "luna",
                        "--repo", str(repo1)])
            self.assertEqual(code, 0)

        def test_relative_artifact_resolves_against_docs_root_parent_and_cwd(self):
            """The real Gorelo shape: the Orchestrator runs the gate from the
            WORKSPACE ROOT (the docs-root's own parent), and the handoff's
            <artifact> is written relative to THAT -- `.docs/bugfix/x/report.md`
            -- not relative to the docs-root itself (which would double up as
            `.docs/.docs/bugfix/x/report.md` and never resolve)."""
            docs, repo1, repo2, ref1, ref2 = self.make_multi_repo()
            workspace_root = docs.parent
            handoff_dir = docs / "bugfix" / "x"
            handoff_dir.mkdir(parents=True)
            report_path = handoff_dir / "review-report.md"
            report_path.write_text("# Report\n\ndone\n", encoding="utf-8")
            handoff_path = handoff_dir / "handoff.md"
            handoff_path.write_text(
                "<handoff><status>COMPLETE</status>"
                "<artifact>.docs/bugfix/x/review-report.md</artifact>"
                "<blockers>None</blockers></handoff>", encoding="utf-8")
            old_cwd = os.getcwd()
            try:
                os.chdir(workspace_root)
                # No --docs-root passed: discovered from --handoff, same as
                # every real pipeline call.
                code = main(["--handoff", str(handoff_path), "--persona", "luna",
                            "--repo", str(repo1), "--repo", str(repo2)])
            finally:
                os.chdir(old_cwd)
            self.assertEqual(code, 0)

        def test_relative_changed_files_under_docs_root_still_fails(self):
            """<changed_files> never gets the docs-root-parent/cwd fallback --
            it stays repo-relative or absolute under a --repo, even when the
            same relative form would resolve for <artifact>."""
            docs, repo1, repo2, ref1, ref2 = self.make_multi_repo()
            workspace_root = docs.parent
            (docs / "note.md").write_text("x", encoding="utf-8")
            text = ("<handoff><status>COMPLETE</status>"
                    "<changed_files>.docs/note.md</changed_files>"
                    "<blockers>None</blockers></handoff>")
            old_cwd = os.getcwd()
            try:
                os.chdir(workspace_root)
                r = build_report(text, "mason", [repo1, repo2],
                                 docs_root=[docs])
            finally:
                os.chdir(old_cwd)
            self.assertEqual(self.codes(r), ["path_missing"])
            self.assertEqual(r["findings"][0]["element"], "changed_files")

        # --- status, consumers, honesty ---------------------------------
        def test_status_outside_the_enum_fails(self):
            text = GOOD_MASON.replace("COMPLETE", "DONE")
            self.assertEqual(self.codes(build_report(text, "mason", self.dir)),
                             ["status_invalid"])

        def test_partial_and_blocked_are_valid_statuses(self):
            for value in ("PARTIAL", "BLOCKED"):
                text = GOOD_MASON.replace("COMPLETE", value).replace(
                    "<blockers>None</blockers>",
                    "<blockers>blocked_on: spec — see above</blockers>")
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
            # "None" is both a contradiction (BLOCKED naming no blocker) and,
            # since it carries no `blocked_on:` line either, uncategorised.
            self.assertEqual(self.codes(build_report(text, "mason", self.dir)),
                             ["blockers_uncategorised", "honesty_contradiction"])

        # --- blocked_on: grammar (blockers_uncategorised) ------------------

        def _blocked(self, status, blockers):
            return (f"<handoff><status>{status}</status>"
                    f"<changed_files>src/a.py</changed_files>"
                    f"<blockers>{blockers}</blockers></handoff>")

        def test_blocked_on_valid_category_passes_on_partial(self):
            text = self._blocked("PARTIAL",
                                 "blocked_on: environment — no admin shell")
            r = build_report(text, "mason", self.dir)
            self.assertEqual(r["result"], "PASS", r["findings"])

        def test_blocked_on_valid_category_passes_on_blocked(self):
            text = self._blocked("BLOCKED",
                                 "blocked_on: credentials — no dev token")
            r = build_report(text, "mason", self.dir)
            self.assertEqual(r["result"], "PASS", r["findings"])

        def test_blocked_on_missing_line_fails_on_partial(self):
            text = self._blocked("PARTIAL", "no admin shell, stuck")
            r = build_report(text, "mason", self.dir)
            self.assertEqual(self.codes(r), ["blockers_uncategorised"])
            self.assertIn("blocked_on:", r["findings"][0]["detail"])

        def test_blocked_on_unknown_category_fails(self):
            text = self._blocked("BLOCKED", "blocked_on: hardware — no GPU")
            r = build_report(text, "mason", self.dir)
            self.assertEqual(self.codes(r), ["blockers_uncategorised"])

        def test_blocked_on_every_known_category_is_accepted(self):
            for category in BLOCKED_ON_CATEGORIES:
                text = self._blocked(
                    "PARTIAL", f"blocked_on: {category} — reason for {category}")
                r = build_report(text, "mason", self.dir)
                self.assertEqual(r["result"], "PASS", (category, r["findings"]))

        def test_blocked_on_grammar_exempt_on_complete_status(self):
            text = self._blocked("COMPLETE", "no blocked_on line here at all")
            r = build_report(text, "mason", self.dir)
            self.assertNotIn("blockers_uncategorised", self.codes(r))

        def test_blocked_on_line_with_bullet_marker_and_backticks_still_recognized(self):
            text = self._blocked(
                "BLOCKED", "- `blocked_on: dependency — waiting on the DB team`")
            r = build_report(text, "mason", self.dir)
            self.assertEqual(r["result"], "PASS", r["findings"])

        def test_blocked_on_hyphen_separator_is_accepted(self):
            """The grammar's dash is em/en dash OR a plain hyphen."""
            text = self._blocked("PARTIAL", "blocked_on: spec - ambiguous NFR")
            r = build_report(text, "mason", self.dir)
            self.assertEqual(r["result"], "PASS", r["findings"])

        def test_blocked_on_one_valid_line_among_several_is_enough(self):
            text = self._blocked(
                "BLOCKED",
                "some prose first\nblocked_on: defect — flaky test\nmore prose")
            r = build_report(text, "mason", self.dir)
            self.assertEqual(r["result"], "PASS", r["findings"])

        def test_blocked_on_absent_blockers_element_is_only_element_missing(self):
            """An absent <blockers> is element_missing; the grammar check does
            not pile a second finding onto the same gap."""
            text = ("<handoff><status>PARTIAL</status>"
                    "<changed_files>src/a.py</changed_files></handoff>")
            r = build_report(text, "mason", self.dir)
            self.assertEqual(self.codes(r), ["element_missing"])

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
