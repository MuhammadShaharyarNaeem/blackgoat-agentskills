#!/usr/bin/env python3
"""Validates every `§` section-anchor citation under `agents/` and `skills/`.

A citation like `` § `check_agent_report.py` `` or `` `base-persona.md` §
Evidence Integrity `` reads as a promise that the named heading still
exists. Nothing enforced that promise before this script: `{PLUGIN_ROOT}`
table paths are checked by `check_dependency_tables.py`, but a prose `§`
citation into a *section* of a file was invisible to every gate. That gap
matters right now because `skills/pipeline-tools/SKILL.md` is about to be
split -- each script's contract moving from a `## <name>.py` heading in the
spine to its own `references/<name>.md` file -- and fifteen citations
across a dozen files point into that spine by section. A move that leaves
one of them dangling is silent until a reader follows it.

Two citation forms are resolved. Everything else is `unresolved` -- counted
and, with `--verbose`/`--json`, listed, but **never a failure**: a bare
`§3` or `§ Evidence Integrity` with no file attached names no
determinable target, and a lint that failed on it would be pure noise.

  Form A -- SCRIPT ANCHOR: `` § `<name>.py` `` or `§ <name>.py` (backticks
  optional), matched wherever it appears on a line -- even right after an
  explicit `` `.../pipeline-tools/SKILL.md` `` citation, which is how most
  real instances of this form actually read (the `.py` name is more
  specific than the file that precedes it, so it wins). Resolves against
  EITHER the pre-split spine heading (`## <name>.py` in
  `pipeline-tools/SKILL.md`) OR the post-split file
  (`pipeline-tools/references/<name>.md`) -- accepting either is
  deliberate (CLAUDE.md convention #8): it is what lets the split happen
  commit by commit instead of on one flag day where every citation would
  otherwise go dangling at once. Dangling = neither exists.

  Form B -- EXPLICIT FILE ANCHOR: a backtick-quoted path ending in `.md`,
  immediately followed (same line, whitespace only in between) by `§` and
  section text -- e.g. `` `base-persona.md` § Evidence Integrity `` or
  `` `{PLUGIN_ROOT}/../agents/cipher.md` § 4 ``. The path is resolved, in
  order, as: (1) `{PLUGIN_ROOT}/...` -> under `skills/`; (2) as given,
  relative to the repo root; (3) relative to `skills/`; (4) a nested
  relative path (contains `/`) relative to the CITING file's own
  directory -- the `references/<x>.md` sibling-reference convention nearly
  every `bgpdd-*/SKILL.md` uses; (5) a bare filename (no `/` at all)
  relative to `agents/`, then searched for anywhere under `agents/` or
  `skills/` if that also misses (how a bare `base-persona.md` finds
  `skills/agent-squad/base-persona.md`). A path starting with `.`
  (`.docs/...`) is a per-project RUNTIME location -- CLAUDE.md's
  `.docs/{project-name}/` semantic-memory model, never a file in this
  static repo -- so it is not attempted at all; that citation is
  `unresolved`, not dangling. Once a file is found, the section text must
  match a `##`/`###` heading in it, case-insensitively, backticks and
  punctuation stripped, WORD-PREFIX match allowed (a citation commonly
  trims a long heading, and a numbered heading like `### 4. Security
  Report` is cited as bare `§ 4`). Dangling = file missing, or file found
  but no heading matches.

Fenced (```/~~~) code blocks are skipped throughout -- a `§` inside one is
an example being quoted, not a live citation (mirrors the
`strip_fenced_blocks` helper duplicated across this script family, e.g.
`check_agent_report.py`; no shared module by convention).

Any `fixtures/` directory segment under `skills/` (e.g.
`skills/pipeline-tools/fixtures/**`) is EXCLUDED by default. Fixture docs
are deliberately self-contained example content -- they cite each other's
fictional paths (`design/detailed-design.md`) to illustrate an annotation
format, not to reference anything real in this repo, so a dangling finding
there is permanent noise, not a stale citation anyone will ever fix. Pass
`--include-fixtures` to scan them anyway (see `is_fixture_path`).

Usage:
    python check_section_anchors.py [--repo <dir>] [--json] [--verbose]
        [--include-fixtures]
    python check_section_anchors.py --self-test
    python check_section_anchors.py --help

With no `--repo`, scans this plugin's own `agents/` and `skills/` (default:
this script's plugin root, three directories up from
`skills/pipeline-tools/scripts/`).

Exit codes: 0 no dangling anchor; 1 at least one dangling anchor; 2 usage
error (bad `--repo`, or a repo missing `agents/` or `skills/`).

Pure standard library.
"""
import argparse
import json
import re
import sys
import unittest
from pathlib import Path

READ_ENCODING = "utf-8-sig"

SECTION_MARK = "§"  # §

# Same pattern as check_agent_report.py / check_coverage.py / etc. -- a
# fence delimiter line is 3+ backticks or tildes, indent allowed.
FENCE_RE = re.compile(r"^[ \t]*(`{3,}|~{3,})")

# Form A: `§` directly followed by a script name, backticks optional.
# `.match` is anchored at the text right after the `§`, so this only fires
# when the name comes IMMEDIATELY next -- not merely somewhere later on
# the line.
FORM_A_AFTER_RE = re.compile(r"^\s*`?([A-Za-z0-9_-]+\.py)`?")

# Form B: a backtick-quoted `.md` path ending immediately (whitespace only)
# before the `§` that triggered this scan. Anchored to the END of the
# `before`-the-§ substring via `$`.
FORM_B_BEFORE_RE = re.compile(r"`([^`\n]+\.md)`\s*$")

# `##`/`###` headings, read from fence-stripped text.
HEADING_RE = re.compile(r"^(##|###)[ \t]+(.+?)[ \t]*$", re.MULTILINE)


class GateError(Exception):
    """Structural/usage failure -- maps to exit 2."""


# ---------------------------------------------------------------------------
# Text pipeline
# ---------------------------------------------------------------------------

def strip_fenced_blocks(text):
    """Blank out every ```/~~~ fenced region, preserving the line count.

    Duplicated per file: this script family has no shared module by
    convention (see check_agent_report.py's copy of the same function).
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


def read_text(path):
    try:
        return Path(path).read_text(encoding=READ_ENCODING, errors="replace")
    except OSError as exc:
        raise GateError(f"cannot read {path}: {exc}")


def rel(path, repo):
    try:
        return str(Path(path).resolve().relative_to(Path(repo).resolve())).replace("\\", "/")
    except ValueError:
        return str(path)


def find_headings(text):
    """Return [(level, heading_text), ...] for every ##/### heading."""
    stripped = strip_fenced_blocks(text)
    return [(len(m.group(1)), m.group(2)) for m in HEADING_RE.finditer(stripped)]


def normalize_anchor_text(s):
    """Lowercase, strip backticks/punctuation, collapse whitespace -- but
    keep a digit.digit run (e.g. "1.3") intact, since numbered headings are
    cited that way. Used for a case/punctuation-insensitive comparison."""
    s = s.strip("`").lower()
    s = re.sub(r"(?<=\d)\.(?=\d)", "\x01", s)  # protect "1.3" style dots
    s = re.sub(r"[^a-z0-9 \x01]", " ", s)
    s = s.replace("\x01", ".")
    return re.sub(r"\s+", " ", s).strip()


def heading_matches(citation_text, heading_text):
    """Symmetric word-prefix match between a citation and one heading.

    Matches if EITHER side's whole word list is a prefix of the other's:

    - Citation-is-prefix-of-heading (the original, intended direction): a
      short citation like "Evidence Integrity" resolves against the
      longer heading "Evidence Integrity (Verification Reporting)".
    - Heading-is-prefix-of-citation: an unquoted WORD citation is
      extracted by scanning prose with no marker for where the citation
      ends and the citing author's own gloss begins ("Rules owns the
      principle" against the heading "### Rules", or "Escalation has
      always said, in prose, ..." against a heading "### Escalation") --
      there is no punctuation boundary to catch that split, so the
      heading's (shorter) word list fully matching the citation's leading
      words is accepted too.

    A shared prefix of a single word only counts when that word is the
    ENTIRE heading or the ENTIRE citation (a short heading like "Rules"
    fully consumed, or a short citation like "Timing" fully consumed) --
    not a coincidental one-word overlap on both sides, which is what
    keeps "No Such Heading" from matching "Evidence Integrity
    (Verification Reporting)" (shared prefix length 0 there anyway). A
    shared prefix of 2+ words counts regardless of which side is longer,
    since that is no longer a coincidence (real case: "Evidence Integrity
    on not promoting a narrower artifact..." against the heading
    "Evidence Integrity (Verification Reporting)" -- neither side's full
    word list matches, but the first two words do).
    """
    c_words = normalize_anchor_text(citation_text).split()
    if not c_words:
        return False
    h_words = normalize_anchor_text(heading_text).split()
    if not h_words:
        return False
    shared = 0
    for a, b in zip(c_words, h_words):
        if a != b:
            break
        shared += 1
    return shared >= 2 or shared == len(c_words) or shared == len(h_words)


# Boundary characters for an unquoted word-based citation: closing paren,
# table pipe, backtick, em dash, opening paren (a citer's own parenthetical
# starts here, e.g. "1 (background execution...)"), both apostrophe styles
# (a possessive like "2's"), colon, semicolon, and the typographic arrow
# some prose uses in place of "->". A period is a boundary UNLESS sandwiched
# between two digits (so "1.3" survives, "Evidence Integrity." does not).
WORD_STOP_CHARS = ")|`—(’';:→"


def extract_bare_section_text(after):
    """Section text following a `§` with no immediately-preceding form
    marker consumed yet: a backtick- or asterisk-quoted span, a leading
    section NUMBER (captures only the alnum/dotted-number token itself --
    "1", "2", "8b", "1.3" -- and stops at the first character that isn't
    part of that token, which is what makes "1's narrowing", "1 (background
    ...)"  and "1 defines" all resolve to just "1"), or otherwise a
    boundary-delimited word run (see WORD_STOP_CHARS; relies on
    heading_matches' looser multi-word threshold to tolerate the prose
    that still leaks through when there is no punctuation boundary at
    all, e.g. "Evidence Integrity on not promoting..."). Returns None when
    nothing usable follows (e.g. `§` at end of line).
    """
    s = after.lstrip(" \t")
    if not s:
        return None
    if s[0] == "`":
        end = s.find("`", 1)
        return s[1:end].strip() if end != -1 else None
    if s[0] == "*":
        end = s.find("*", 1)
        return s[1:end].strip() if end != -1 else None
    if s[0].isdigit():
        i, n = 0, len(s)
        while i < n:
            c = s[i]
            if c.isalnum():
                i += 1
                continue
            if (c == "." and i + 1 < n and s[i + 1].isdigit()
                    and i > 0 and s[i - 1].isdigit()):
                i += 1
                continue
            break
        text = s[:i].strip()
        return text or None
    i, n = 0, len(s)
    while i < n:
        c = s[i]
        if c in WORD_STOP_CHARS:
            break
        if c == ".":
            prev_digit = i > 0 and s[i - 1].isdigit()
            next_digit = (i + 1 < n) and s[i + 1].isdigit()
            if not (prev_digit and next_digit):
                break
        i += 1
    text = s[:i].strip()
    return text or None


def is_placeholder_text(text):
    """True for a template slot (`<agent>`) or an elided citation (an
    ellipsis standing in for "some section", e.g. `` `x.md` §… `` in a
    piece of narrative prose) -- names no real target, so it is not
    determinable rather than dangling."""
    return text.startswith("<") or text.strip(".… ") == ""


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------

def resolve_form_a(name, skills_dir):
    """Form A target: a `## <name>.py` heading in `pipeline-tools/SKILL.md`
    OR the post-split `pipeline-tools/references/<name>.md` file. Accepting
    either is the point (see module docstring / convention #8).

    Returns (resolved: bool, target_desc: str, reason: str|None).
    """
    spine = skills_dir / "pipeline-tools" / "SKILL.md"
    if spine.is_file():
        for level, text in find_headings(read_text(spine)):
            if level == 2 and text.strip().strip("`") == name:
                return True, f"pipeline-tools/SKILL.md#{name}", None

    ref_file = skills_dir / "pipeline-tools" / "references" / (name[:-3] + ".md")
    if ref_file.is_file():
        return True, f"pipeline-tools/references/{ref_file.name}", None

    target = (f"pipeline-tools/SKILL.md#{name} or "
              f"pipeline-tools/references/{name[:-3]}.md")
    return False, target, "heading not found"


def resolve_form_b_path(path, repo, skills_dir, agents_dir, citing_file):
    """Resolve a Form B `.md` path to a real file, trying this tree's
    actual citation conventions in order (see module docstring). Returns
    the resolved Path, or None when no candidate exists (dangling: file
    missing). The caller is responsible for excluding `.`-prefixed
    (runtime) paths before calling this.
    """
    if path.startswith("{PLUGIN_ROOT}/"):
        candidate = skills_dir / path[len("{PLUGIN_ROOT}/"):]
        return candidate if candidate.is_file() else None

    candidates = [repo / path, skills_dir / path]
    if "/" in path:
        candidates.append(citing_file.parent / path)
    else:
        # A bare filename is tried against the CITING file's own directory
        # first, then its parent -- a `references/<x>.md` file citing a
        # bare `SKILL.md` almost always means its own enclosing skill's
        # spine, one directory up. Only a genuinely skill-wide/agent-wide
        # name (`base-persona.md`, `mason.md`) needs the wider fallback
        # below; trying the narrow, unambiguous case first is what keeps a
        # common bare name like `SKILL.md` from resolving to whichever
        # skill happens to sort first.
        candidates.append(citing_file.parent / path)
        candidates.append(citing_file.parent.parent / path)
        candidates.append(agents_dir / path)
    for c in candidates:
        if c.is_file():
            return c

    # Last resort: search the whole tree for a file whose path ENDS WITH
    # the cited one -- a bare `base-persona.md`, or a cross-skill relative
    # citation like `references/bugfix-rationale.md` written from a
    # DIFFERENT skill's file (a deliberate cross-skill reference; nothing
    # in the path itself says which skill). Only trusted when the suffix
    # is UNIQUE across the tree -- a bare `SKILL.md` matches ~40 files,
    # and resolving to an arbitrary one of them would be worse than
    # reporting the citation as dangling.
    suffix = "/" + path
    all_md = sorted(agents_dir.rglob("*.md")) + sorted(skills_dir.rglob("*.md"))
    matches = [p for p in all_md
               if str(p).replace("\\", "/").endswith(suffix) or p.name == path]
    if len(matches) == 1:
        return matches[0]
    return None


# ---------------------------------------------------------------------------
# Scanning
# ---------------------------------------------------------------------------

def scan_line(line, filerel, lineno, repo, skills_dir, agents_dir, citing_file, anchors):
    """Find every `§` on `line` and classify/resolve each independently."""
    start = 0
    while True:
        idx = line.find(SECTION_MARK, start)
        if idx == -1:
            return
        after = line[idx + 1:]
        before = line[:idx]

        a_match = FORM_A_AFTER_RE.match(after)
        if a_match:
            name = a_match.group(1)
            resolved, target, reason = resolve_form_a(name, skills_dir)
            anchors.append({
                "file": filerel, "line": lineno, "form": "A", "anchor": name,
                "target": target, "status": "resolved" if resolved else "dangling",
                "reason": reason,
            })
            start = idx + 1 + a_match.end()
            continue

        b_before = FORM_B_BEFORE_RE.search(before)
        if b_before:
            path = b_before.group(1)
            text = extract_bare_section_text(after)
            anchor_disp = f"`{path}`, {text}" if text else f"`{path}`, (no section text found)"
            if path.startswith("."):
                # Runtime-generated location (.docs/{project-name}/...):
                # never a file in this static repo -- not determinable.
                anchors.append({"file": filerel, "line": lineno, "form": "B",
                                 "anchor": anchor_disp, "target": None,
                                 "status": "unresolved", "reason": None})
            elif text is not None and is_placeholder_text(text):
                # A template slot (`<agent>`) or an elided reference (an
                # ellipsis standing in for "some section") names no real
                # target -- not determinable, not a broken citation.
                anchors.append({"file": filerel, "line": lineno, "form": "B",
                                 "anchor": anchor_disp, "target": path,
                                 "status": "unresolved", "reason": None})
            elif text is None:
                anchors.append({"file": filerel, "line": lineno, "form": "B",
                                 "anchor": anchor_disp, "target": path,
                                 "status": "unresolved", "reason": None})
            else:
                resolved_path = resolve_form_b_path(path, repo, skills_dir,
                                                     agents_dir, citing_file)
                if resolved_path is None:
                    anchors.append({"file": filerel, "line": lineno, "form": "B",
                                     "anchor": anchor_disp, "target": path,
                                     "status": "dangling", "reason": "file missing"})
                else:
                    target_rel = rel(resolved_path, repo)
                    found = any(heading_matches(text, h)
                                for _, h in find_headings(read_text(resolved_path)))
                    if found:
                        anchors.append({"file": filerel, "line": lineno, "form": "B",
                                         "anchor": anchor_disp,
                                         "target": f"{target_rel}#{text}",
                                         "status": "resolved", "reason": None})
                    else:
                        anchors.append({"file": filerel, "line": lineno, "form": "B",
                                         "anchor": anchor_disp, "target": target_rel,
                                         "status": "dangling", "reason": "heading not found"})
            start = idx + 1
            continue

        # Bare `§` -- no `.py` name and no preceding backticked `.md` path
        # (most commonly CLAUDE.md convention #10's same-file citation,
        # `(§ Section Name)`, which names no file at all). Out of scope by
        # design: nothing determinable to resolve. The section text is
        # still captured here for a readable --verbose listing; it plays
        # no part in resolution.
        bare_text = extract_bare_section_text(after)
        anchors.append({"file": filerel, "line": lineno, "form": None,
                         "anchor": bare_text or "(no section text found)",
                         "target": None, "status": "unresolved", "reason": None})
        start = idx + 1


def is_fixture_path(path, skills_dir):
    """True for a file under a `fixtures/` directory segment anywhere
    below `skills/` (e.g. `skills/pipeline-tools/fixtures/**`). Fixture
    docs are deliberately self-contained example content -- they cite
    each other's fictional paths (`design/detailed-design.md`) to
    illustrate an annotation format, not to reference anything real in
    this repo, so a "dangling" finding there is permanent noise, not a
    stale citation to fix."""
    try:
        parts = path.resolve().relative_to(skills_dir.resolve()).parts
    except ValueError:
        return False
    return "fixtures" in parts


def scan_repo(repo, include_fixtures=False):
    """Return (files_scanned, anchors) for every `*.md` under `agents/`
    and `skills/` (pipeline-tools' own files included -- self-citations
    count). `fixtures/` content under `skills/` is skipped by default
    (see `is_fixture_path`); pass `include_fixtures=True` to scan it too.
    """
    agents_dir = repo / "agents"
    skills_dir = repo / "skills"
    if not agents_dir.is_dir() or not skills_dir.is_dir():
        raise GateError(f"expected both agents/ and skills/ under {repo}")

    skills_files = sorted(skills_dir.rglob("*.md"))
    if not include_fixtures:
        skills_files = [p for p in skills_files if not is_fixture_path(p, skills_dir)]
    files = sorted(agents_dir.rglob("*.md")) + skills_files
    anchors = []
    for path in files:
        text_no_fence = strip_fenced_blocks(read_text(path))
        filerel = rel(path, repo)
        for lineno, line in enumerate(text_no_fence.split("\n"), start=1):
            if SECTION_MARK in line:
                scan_line(line, filerel, lineno, repo, skills_dir, agents_dir,
                          path, anchors)
    return files, anchors


def build_report(repo, include_fixtures=False):
    files, anchors = scan_repo(repo, include_fixtures=include_fixtures)
    dangling = [a for a in anchors if a["status"] == "dangling"]
    unresolved = [a for a in anchors if a["status"] == "unresolved"]
    resolved = [a for a in anchors if a["status"] == "resolved"]
    return {
        "repo": str(repo),
        "files_scanned": len(files),
        "anchors_found": len(anchors),
        "resolved": len(resolved),
        "dangling": len(dangling),
        "unresolved": len(unresolved),
        "dangling_detail": dangling,
        "unresolved_detail": unresolved,
        "result": "FAIL" if dangling else "PASS",
    }


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def format_dangling(a):
    return (f"{a['file']}:{a['line']}: § {a['anchor']} -> {a['target']} — "
            f"{a['reason']}; fix: repoint the citation or restore the section")


def print_report(report, verbose):
    print(f"Scanned {report['files_scanned']} file(s), found "
          f"{report['anchors_found']} § anchor(s): {report['resolved']} "
          f"resolved, {report['dangling']} dangling, {report['unresolved']} "
          f"unresolved")
    if report["dangling_detail"]:
        print()
        print(f"DANGLING: {report['dangling']} anchor(s):")
        for a in report["dangling_detail"]:
            print(f"  {format_dangling(a)}")
    if verbose and report["unresolved_detail"]:
        print()
        print(f"UNRESOLVED ({report['unresolved']}) -- not a failure, listed "
              f"for review:")
        for a in report["unresolved_detail"]:
            print(f"  {a['file']}:{a['line']}: § {a['anchor']}")
    print()
    print("PASS" if report["result"] == "PASS" else "FAIL")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser():
    parser = argparse.ArgumentParser(
        prog="check_section_anchors.py",
        description="Validate that every `§` section-anchor citation "
                     "under agents/ and skills/ resolves to a real heading "
                     "or file.",
        epilog="Exit codes: 0 no dangling anchor; 1 at least one dangling "
               "anchor; 2 usage error (bad --repo, or a repo missing "
               "agents/ or skills/). --json prints 'result', "
               "'dangling_detail', 'unresolved_detail', and the summary "
               "counts.")
    parser.add_argument("--repo",
                        help="plugin root containing agents/ and skills/ "
                             "(default: this script's own plugin root)")
    parser.add_argument("--json", action="store_true",
                        help="print the report as JSON instead of text")
    parser.add_argument("--verbose", action="store_true",
                        help="also list unresolved (non-file-determinable) "
                             "citations")
    parser.add_argument("--include-fixtures", action="store_true",
                        help="also scan skills/**/fixtures/**, excluded by "
                             "default (self-contained example content, not "
                             "live citations -- see is_fixture_path)")
    parser.add_argument("--self-test", action="store_true",
                        help="run the built-in test suite and exit")
    return parser


def main(argv):
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.self_test:
        return run_self_test()

    # This file lives at skills/pipeline-tools/scripts/check_section_anchors.py,
    # three directories below the plugin root -- `parents[3]`, NOT
    # `parents[2]` (that lands on skills/, a bug present in this script
    # family's `check_agent_originality.py` default; not fixed here, out
    # of scope for this change, but not repeated).
    repo = Path(args.repo) if args.repo else Path(__file__).resolve().parents[3]
    if not repo.is_dir():
        print(f"error: --repo {repo} is not a directory", file=sys.stderr)
        return 2

    try:
        report = build_report(repo, include_fixtures=args.include_fixtures)
    except GateError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print_report(report, args.verbose)
    return 1 if report["result"] == "FAIL" else 0


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

def run_self_test():
    import contextlib
    import io
    import shutil
    import tempfile

    class AnchorTests(unittest.TestCase):
        def setUp(self):
            self.root = Path(tempfile.mkdtemp())
            self.agents = self.root / "agents"
            self.skills = self.root / "skills"
            self.pt = self.skills / "pipeline-tools"
            self.pt_refs = self.pt / "references"
            self.agent_squad = self.skills / "agent-squad"
            self.agents.mkdir()
            self.pt_refs.mkdir(parents=True)
            self.agent_squad.mkdir(parents=True)
            # A spine with one real heading (check_a.py), used by the
            # Form A / spine-heading and {PLUGIN_ROOT} tests.
            (self.pt / "SKILL.md").write_text(
                "# pipeline-tools\n\n## check_a.py\n\nBody text.\n",
                encoding="utf-8",
            )
            # A post-split references file with NO matching spine heading
            # -- the "accept either" case.
            (self.pt_refs / "check_b.md").write_text(
                "# check_b.py\n\nBody text.\n", encoding="utf-8",
            )
            (self.agent_squad / "base-persona.md").write_text(
                "# Base Persona\n\n"
                "## Evidence Integrity (Verification Reporting)\n\n"
                "Body text.\n",
                encoding="utf-8",
            )

        def tearDown(self):
            shutil.rmtree(self.root, ignore_errors=True)

        def _write_agent(self, body):
            (self.agents / "a.md").write_text(body, encoding="utf-8")

        # -- Form A: spine heading --------------------------------------

        def test_form_a_resolves_to_spine_heading(self):
            self._write_agent("See § `check_a.py` for the grammar.\n")
            report = build_report(self.root)
            self.assertEqual(report["dangling"], 0)
            self.assertEqual(report["resolved"], 1)
            self.assertEqual(report["result"], "PASS")

        # -- Form A: references file only (post-split) -------------------

        def test_form_a_resolves_to_references_file_only(self):
            self._write_agent("Owned by § check_b.py.\n")
            report = build_report(self.root)
            self.assertEqual(report["dangling"], 0)
            self.assertEqual(report["resolved"], 1)

        # -- Form A: dangling ---------------------------------------------

        def test_form_a_dangling_names_file_and_line(self):
            self._write_agent(
                "line one\n§ `check_missing.py` owns nothing real.\n"
            )
            report = build_report(self.root)
            self.assertEqual(report["dangling"], 1)
            self.assertEqual(report["result"], "FAIL")
            d = report["dangling_detail"][0]
            self.assertEqual(d["file"], "agents/a.md")
            self.assertEqual(d["line"], 2)
            self.assertEqual(d["reason"], "heading not found")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = main(["--repo", str(self.root)])
            self.assertEqual(code, 1)
            self.assertIn("agents/a.md:2:", out.getvalue())

        # -- Form B: resolves with a trimmed heading -----------------------

        def test_form_b_resolves_with_trimmed_heading(self):
            self._write_agent(
                "Per `skills/agent-squad/base-persona.md` § Evidence "
                "Integrity.\n"
            )
            report = build_report(self.root)
            self.assertEqual(report["dangling"], 0)
            self.assertEqual(report["resolved"], 1)

        # -- Form B: dangling heading ---------------------------------------

        def test_form_b_dangling_heading(self):
            self._write_agent(
                "Per `skills/agent-squad/base-persona.md` § No Such "
                "Heading.\n"
            )
            report = build_report(self.root)
            self.assertEqual(report["dangling"], 1)
            self.assertEqual(report["dangling_detail"][0]["reason"],
                             "heading not found")
            self.assertEqual(main(["--repo", str(self.root)]), 1)

        # -- Form B: missing file -------------------------------------------

        def test_form_b_missing_file(self):
            self._write_agent(
                "Per `skills/agent-squad/does-not-exist.md` § Anything.\n"
            )
            report = build_report(self.root)
            self.assertEqual(report["dangling"], 1)
            self.assertEqual(report["dangling_detail"][0]["reason"], "file missing")
            self.assertEqual(main(["--repo", str(self.root)]), 1)

        # -- bare §3: unresolved, not a failure ------------------------------

        def test_bare_numeric_anchor_is_unresolved_not_a_failure(self):
            self._write_agent("See §3 for details.\n")
            report = build_report(self.root)
            self.assertEqual(report["dangling"], 0)
            self.assertEqual(report["unresolved"], 1)
            self.assertEqual(report["result"], "PASS")
            self.assertEqual(main(["--repo", str(self.root)]), 0)

        # -- {PLUGIN_ROOT} resolution ----------------------------------------

        def test_plugin_root_resolves_for_form_b(self):
            self._write_agent(
                "Per `{PLUGIN_ROOT}/agent-squad/base-persona.md` § "
                "Evidence Integrity.\n"
            )
            report = build_report(self.root)
            self.assertEqual(report["dangling"], 0)
            self.assertEqual(report["resolved"], 1)

        def test_plugin_root_form_a_still_wins_over_the_file_it_follows(self):
            # `§ \`check_a.py\`` right after a `{PLUGIN_ROOT}/.../SKILL.md`
            # citation is Form A (script anchor), not Form B against that
            # SKILL.md's own headings -- the real-world pattern this tree
            # actually uses ten-plus times.
            self._write_agent(
                "Owned by `{PLUGIN_ROOT}/pipeline-tools/SKILL.md` § "
                "`check_a.py`.\n"
            )
            report = build_report(self.root)
            self.assertEqual(report["dangling"], 0)
            self.assertEqual(report["resolved"], 1)
            self.assertEqual(report["dangling_detail"], [])

        # -- fenced code blocks are skipped -----------------------------------

        def test_fenced_anchor_is_not_counted_at_all(self):
            self._write_agent(
                "Text before.\n\n"
                "```\n"
                "§ `check_missing.py` -- just an example in a fence\n"
                "```\n\n"
                "Text after.\n"
            )
            report = build_report(self.root)
            self.assertEqual(report["anchors_found"], 0)
            self.assertEqual(report["result"], "PASS")

        # -- fixtures/ under skills/ is excluded by default, opt-in flag works --

        def test_fixtures_dir_excluded_by_default(self):
            fixtures_dir = self.skills / "some-skill" / "fixtures"
            fixtures_dir.mkdir(parents=True)
            (fixtures_dir / "example.md").write_text(
                "Per `does-not-exist.md` § Something.\n", encoding="utf-8",
            )
            report = build_report(self.root)
            self.assertEqual(report["anchors_found"], 0)
            self.assertEqual(report["dangling"], 0)
            self.assertEqual(report["result"], "PASS")

        def test_fixtures_dir_scanned_with_include_fixtures(self):
            fixtures_dir = self.skills / "some-skill" / "fixtures"
            fixtures_dir.mkdir(parents=True)
            (fixtures_dir / "example.md").write_text(
                "Per `does-not-exist.md` § Something.\n", encoding="utf-8",
            )
            report = build_report(self.root, include_fixtures=True)
            self.assertEqual(report["anchors_found"], 1)
            self.assertEqual(report["dangling"], 1)
            self.assertEqual(report["result"], "FAIL")
            self.assertEqual(main(["--repo", str(self.root)]), 0)
            self.assertEqual(
                main(["--repo", str(self.root), "--include-fixtures"]), 1)

        # -- a runtime .docs/ path is unresolved, never dangling --------------

        def test_dot_prefixed_runtime_path_is_unresolved(self):
            self._write_agent(
                "Per `.docs/summary/context.md` § Stacks (detected).\n"
            )
            report = build_report(self.root)
            self.assertEqual(report["dangling"], 0)
            self.assertEqual(report["unresolved"], 1)

        # -- a bare filename (no directory) is found by search -----------------

        def test_bare_filename_form_b_found_by_search(self):
            self._write_agent("Per `base-persona.md` § Evidence Integrity.\n")
            report = build_report(self.root)
            self.assertEqual(report["dangling"], 0)
            self.assertEqual(report["resolved"], 1)

        # -- multiple anchors on one line are each classified independently ---

        def test_two_anchors_on_one_line(self):
            self._write_agent(
                "Owned by § `check_a.py` and also "
                "`skills/agent-squad/base-persona.md` § Evidence "
                "Integrity.\n"
            )
            report = build_report(self.root)
            self.assertEqual(report["anchors_found"], 2)
            self.assertEqual(report["resolved"], 2)

        # -- heading fully consumed as a prefix of a noisy citation ------------

        def test_short_heading_resolves_against_a_noisy_citation(self):
            # No punctuation between "Rules" and the citing author's own
            # gloss -- nothing marks where the citation ends. The short
            # heading fully matching the citation's leading words is
            # still accepted (real case: `test-driven-development/SKILL.md`
            # `§ Rules owns the principle`).
            (self.skills / "tdd-like").mkdir()
            (self.skills / "tdd-like" / "SKILL.md").write_text(
                "# tdd-like\n\n### Rules\n\nBody.\n", encoding="utf-8",
            )
            self._write_agent(
                "Per `skills/tdd-like/SKILL.md` § Rules owns the "
                "principle.\n"
            )
            report = build_report(self.root)
            self.assertEqual(report["dangling"], 0)
            self.assertEqual(report["resolved"], 1)

        def test_unrelated_single_word_overlap_stays_dangling(self):
            (self.skills / "tdd-like").mkdir()
            (self.skills / "tdd-like" / "SKILL.md").write_text(
                "# tdd-like\n\n### Rules\n\nBody.\n", encoding="utf-8",
            )
            self._write_agent(
                "Per `skills/tdd-like/SKILL.md` § No Such Heading.\n"
            )
            report = build_report(self.root)
            self.assertEqual(report["dangling"], 1)

        # -- a template placeholder or an elided citation is unresolved ---------

        def test_angle_bracket_placeholder_is_unresolved_not_dangling(self):
            self._write_agent(
                "Per `skills/agent-squad/base-persona.md` § <agent>.\n"
            )
            report = build_report(self.root)
            self.assertEqual(report["dangling"], 0)
            self.assertEqual(report["unresolved"], 1)

        def test_ellipsis_citation_is_unresolved_not_dangling(self):
            self._write_agent(
                "Per `skills/agent-squad/base-persona.md` §…\n"
            )
            report = build_report(self.root)
            self.assertEqual(report["dangling"], 0)
            self.assertEqual(report["unresolved"], 1)

    class CliTests(unittest.TestCase):
        """The CLI surface itself: `--help`/`-h` work, exit codes hold."""

        def test_help_exits_zero_and_prints_usage(self):
            out = io.StringIO()
            with self.assertRaises(SystemExit) as ctx, \
                    contextlib.redirect_stdout(out):
                main(["--help"])
            self.assertEqual(ctx.exception.code, 0)
            text = out.getvalue()
            self.assertIn("check_section_anchors.py", text)
            self.assertIn("--self-test", text)

        def test_short_help_flag_also_works(self):
            out = io.StringIO()
            with self.assertRaises(SystemExit) as ctx, \
                    contextlib.redirect_stdout(out):
                main(["-h"])
            self.assertEqual(ctx.exception.code, 0)
            self.assertIn("usage:", out.getvalue())

        def test_nonexistent_repo_is_exit_2(self):
            root = Path(tempfile.mkdtemp())
            err = io.StringIO()
            try:
                with contextlib.redirect_stderr(err):
                    code = main(["--repo", str(root / "nope")])
                self.assertEqual(code, 2)
                self.assertIn("is not a directory", err.getvalue())
            finally:
                shutil.rmtree(root, ignore_errors=True)

        def test_repo_missing_agents_or_skills_is_exit_2(self):
            root = Path(tempfile.mkdtemp())
            (root / "skills").mkdir()
            err = io.StringIO()
            try:
                with contextlib.redirect_stderr(err):
                    code = main(["--repo", str(root)])
                self.assertEqual(code, 2)
                self.assertIn("expected both agents/ and skills/", err.getvalue())
            finally:
                shutil.rmtree(root, ignore_errors=True)

        def test_unknown_flag_is_exit_2(self):
            err = io.StringIO()
            with self.assertRaises(SystemExit) as ctx, \
                    contextlib.redirect_stderr(err):
                main(["--no-such-flag"])
            self.assertEqual(ctx.exception.code, 2)

        def test_json_output_is_parseable(self):
            root = Path(tempfile.mkdtemp())
            try:
                (root / "agents").mkdir()
                (root / "skills").mkdir()
                (root / "agents" / "a.md").write_text(
                    "Nothing to see here.\n", encoding="utf-8",
                )
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    code = main(["--repo", str(root), "--json"])
                self.assertEqual(code, 0)
                data = json.loads(out.getvalue())
                self.assertEqual(data["result"], "PASS")
                self.assertEqual(data["anchors_found"], 0)
            finally:
                shutil.rmtree(root, ignore_errors=True)

    loader = unittest.defaultTestLoader
    suite = unittest.TestSuite([
        loader.loadTestsFromTestCase(AnchorTests),
        loader.loadTestsFromTestCase(CliTests),
    ])
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    print(f"check_section_anchors.py self-test: {suite.countTestCases()} case(s)")
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
