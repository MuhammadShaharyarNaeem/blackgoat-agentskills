#!/usr/bin/env python3
"""Mechanical test-authenticity gate: does this test touch the product at all?

Exit 0 only when every judged test file either reaches production code or
reaches a running surface, and carries no copy of the logic it claims to test.
Used by the build, verify and bugfix lanes wherever a milestone's evidence is
"a test went green".

WHY RED/GREEN CANNOT CATCH THIS
-------------------------------
Every other test gate in this family verifies a TRANSITION -- a command that
failed before the fix and passes after it (`check_red_green.py`), a capture
whose sidecar hashes to the run that produced it
(`check_runtime_evidence.py`). A fake test satisfies all of it perfectly.

A spec that defines `getBackupItemStatus` at the top of the file and asserts
its own copy goes RED before the definition is written and GREEN the moment
it is: a real transition, a real capture, a real exit 0, and zero coupling to
the shipped function of the same name. The tautology is not a broken test; it
is a test of the test file. No amount of running it harder detects that,
because running it is precisely what it is good at. The only thing that
separates it from a real spec is STRUCTURAL: what the file imports, what it
navigates to, and whether the symbol under assertion is defined in the file
or somewhere the product also reads it from.

Hence a gate that reads the test file rather than its result. Four codes,
each a tier of the same evasion (`../references/check_test_authenticity.md`):

  * `test_no_production_import` -- the file touches NEITHER production code
    (an import that resolves under a src root) NOR a running surface (a
    `page.goto`, an HTTP request, a `WebApplicationFactory`). Whatever it
    proves, it does not prove anything about the product. Doing EITHER passes
    this check: a pure unit test imports, an end-to-end spec navigates.
  * `test_inline_reimplementation` -- the file defines a function/class/arrow
    whose body is real logic (>= 3 statements, no reference to a driving
    surface) and whose NAME is also defined somewhere under a src root. The
    test carries a transcription of production code and asserts against the
    transcription. Also fires on >= 2 such definitions in a file that touches
    neither production code nor a running surface, name match or not -- at
    that point the file is a module of its own with tests attached.
  * `test_source_eval` -- the file READS production source as TEXT (a
    `readFileSync` of a path under a src root) and executes a slice of it
    (`new Function`, `eval`, `vm.runIn`, `transpileModule`). The assertion is
    then against whatever the regex happened to slice, which drifts silently
    the moment the surrounding function is edited: a rename outside the
    sliced expression leaves the test green and the product broken.
  * `test_synthetic_dom` -- the file builds its own DOM (`page.setContent`,
    `document.body.innerHTML =`) and never navigates to the application; or
    it TRIES the application and falls back to injecting dummy HTML from the
    `catch` block, which is the same thing with a green tick when the app is
    down.

WHAT A WAIVER MEANS HERE
------------------------
`--allow <file> --reason "<text>"` clears one file's problems and records the
reason in the ledger. It buys DURABILITY, not verification: some tests
legitimately do this (a snapshot test of a template renderer, a spec pinning
a build artifact's shape). A blank reason is exit 2, on the same grounds as
`check_openapi_diff.py --allow-breaking ""` -- an unreasoned waiver is
indistinguishable from an omission.

Usage:
    python check_test_authenticity.py --repo <dir> \
        --changed-files <test file>... [--files <test file>...] \
        [--src-roots <dir>...] [--test-globs <glob>...] \
        [--allow <test file> --reason "<text>"]... \
        [--milestone "<unit>"] [--ledger <path>] [--json]
    python check_test_authenticity.py --self-test

Exit 0 PASS (or ALLOWED), 1 a problem in a non-waived file, 2 usage or an
unreadable input. Pure standard library. See ../SKILL.md for the contract and
../references/check_test_authenticity.md for the heuristics' honest limits.
"""
import argparse
import fnmatch
import hashlib
import json
import os
import re
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

TIMESTAMP_FMT = "%Y-%m-%dT%H:%M:%SZ"
READ_ENCODING = "utf-8-sig"

PROBLEM_CODES = (
    "test_no_production_import",
    "test_inline_reimplementation",
    "test_source_eval",
    "test_synthetic_dom",
)

DEFAULT_TEST_GLOBS = (
    "**/*.spec.*",
    "**/*.test.*",
    "**/tests/**",
    "**/__tests__/**",
    "**/*Tests.cs",
    "**/*Test.cs",
    "**/test_*.py",
    "**/*_test.py",
)

# Conventional main-code directories, tried under the repo root AND under
# every project manifest's directory. See discover_src_roots().
CONVENTIONAL_SRC_DIRS = ("src", "app", "lib", "Source")

MANIFEST_NAMES = ("package.json", "pyproject.toml")
MANIFEST_SUFFIXES = (".csproj",)

# Never walked when indexing src symbols, and never a src root.
NOISE_DIRS = frozenset((
    "node_modules", ".git", ".hg", ".svn", "dist", "build", "out", "bin",
    "obj", "coverage", "__pycache__", ".venv", "venv", "env", ".tox",
    ".next", ".nuxt", ".output", "vendor", "target", ".pytest_cache",
    ".mypy_cache", "site-packages", ".idea", ".vs", "TestResults",
))

CODE_SUFFIXES = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".vue",
                 ".cs", ".py")

# Resolution order for an extensionless JS/TS specifier.
RESOLVE_SUFFIXES = ("", ".ts", ".tsx", ".d.ts", ".js", ".jsx", ".mjs",
                    ".cjs", ".vue", ".json", ".py")

MAX_INDEX_FILES = 20000
MAX_INDEX_BYTES = 2 * 1024 * 1024

# A definition needs this many statements before it counts as "logic" rather
# than a one-line convenience. See count_statements().
MIN_STATEMENTS = 3

# A name shorter than this is noise in any symbol index (`id`, `fn`, `cb`).
MIN_NAME_LENGTH = 4

# Language keywords and framework lifecycle hooks. Excluded from the src
# symbol index AND from definition names, because the line-anchored
# "<name>(" method pattern matches `if (`, `for (` and `data() {` too. The
# cost of the list is documented in the reference: a production symbol
# genuinely called `render` is invisible to the name-match branch.
STOPWORDS = frozenset(w.lower() for w in (
    # control flow / declarations, every language in scope
    "if", "for", "while", "switch", "catch", "return", "function", "new",
    "typeof", "await", "do", "else", "try", "finally", "throw", "delete",
    "void", "in", "of", "with", "case", "default", "const", "let", "var",
    "class", "extends", "super", "this", "import", "export", "yield",
    "async", "get", "set", "static", "public", "private", "protected",
    "internal", "readonly", "declare", "type", "interface", "enum",
    "namespace", "module", "require", "then", "constructor", "using",
    "lock", "foreach", "elif", "except", "lambda", "pass", "raise",
    "assert", "global", "nonlocal", "def", "not", "and", "or", "is",
    # framework lifecycle and object-literal boilerplate
    "data", "render", "setup", "created", "mounted", "beforemount",
    "beforecreate", "updated", "destroyed", "unmounted", "watch",
    "computed", "methods", "props", "emits", "components", "template",
    "main", "init", "initialize", "configure", "configureservices",
    "dispose", "tostring", "valueof", "equals", "gethashcode", "clone",
    "toarray", "tolist", "run", "start", "stop", "handle", "invoke",
    # test framework surface
    "describe", "test", "it", "expect", "beforeeach", "aftereach",
    "beforeall", "afterall", "fixture", "arrange", "act", "assert",
    # builtins whose names collide with everything
    "number", "string", "boolean", "array", "object", "promise", "map",
    "set", "date", "json", "math", "error", "console", "log", "warn",
    "info", "foreach", "filter", "reduce", "push", "slice", "splice",
    "find", "some", "every", "keys", "values", "entries", "length",
))

# Referencing any of these inside a definition's body makes it a TEST
# HARNESS helper (it drives the app or asserts), never a transcription of
# production logic. This is the discriminator that keeps a real end-to-end
# spec's `login(page, ...)` / `openNavDrawer(page)` helpers out of
# `test_inline_reimplementation`. See the reference for why it is load-bearing.
DRIVER_TOKENS_RE = re.compile(
    r"\b(?:page|browser|context|locator|request|driver|client|expect|"
    r"execSync|spawnSync|spawn|exec|HttpClient|WebApplicationFactory|"
    r"TestServer|WebDriver|requests|httpx|axios|superagent)\b")

# --- running-surface signals ----------------------------------------------
GOTO_RE = re.compile(r"\b(?:page|frame|popup|newPage|tab)?\s*\.?\s*goto\s*\(")
NAV_RE = re.compile(
    r"\bpage\s*\.\s*goto\s*\(|\bbrowser_navigate\b|\.\s*goto\s*\(|"
    r"\bNavigateToUrl\b|\bdriver\s*\.\s*get\s*\(")
HTTP_CLIENT_RE = re.compile(
    r"\brequest\s*\.\s*(?:get|post|put|patch|delete|head|fetch)\s*\(|"
    r"\bHttpClient\b|\bWebApplicationFactory\b|\bTestServer\b|"
    r"\brequests\s*\.\s*(?:get|post|put|patch|delete)\s*\(|"
    r"\bhttpx\s*\.\s*(?:get|post|Client)\s*\(|"
    r"\baxios\s*\.\s*(?:get|post|put|patch|delete)\s*\(")
FETCH_RE = re.compile(r"\bfetch\s*\(")
HTTP_URL_RE = re.compile(r"https?://", re.IGNORECASE)
BASEURL_RE = re.compile(r"base_?url", re.IGNORECASE)

# --- synthetic-DOM signals -------------------------------------------------
SET_CONTENT_RE = re.compile(r"\.\s*setContent\s*\(")
INNER_HTML_RE = re.compile(
    r"\bdocument\s*\.\s*(?:body|documentElement)\s*\.\s*innerHTML\s*=")

# --- source-eval signals ---------------------------------------------------
READ_SOURCE_RE = re.compile(
    r"\breadFileSync\s*\(|\bfs\s*\.\s*readFile\s*\(|"
    r"\bfs\s*\.\s*promises\s*\.\s*readFile\s*\(|\breadFile\s*\(|"
    r"\bFile\s*\.\s*ReadAllTextAsync?\s*\(|\bFile\s*\.\s*ReadAllLines\s*\(")
EVAL_RE = re.compile(
    r"\bnew\s+Function\s*\(|\beval\s*\(|\bvm\s*\.\s*runIn|"
    r"\btranspileModule\s*\(|\bts\s*\.\s*transpile\b|"
    r"\bFunction\s*\(\s*['\"]")
PY_READ_RE = re.compile(r"\bopen\s*\(|\bread_text\s*\(|\bPath\s*\([^)]*\)\s*\.\s*read")
PY_EVAL_RE = re.compile(r"\beval\s*\(|\bexec\s*\(|\bcompile\s*\(")

# --- test entry points, for the citation line ------------------------------
TEST_ENTRY_RE = re.compile(
    r"(?m)^[^\S\n]*(?:async\s+)?(?:export\s+)?"
    r"(?:test|it|describe|suite|def\s+test_|\[Fact\]|\[Theory\]|"
    r"public\s+(?:async\s+)?(?:void|Task))\b")


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
        record["prev"] = ledger_prev_hash(p)
        record["self"] = ledger_self_hash(record)
        with open(p, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
    except OSError as exc:
        print("Warning: could not append to ledger "
              "{0}: {1}".format(ledger_path, exc), file=sys.stderr)


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

def rel_posix(path, repo):
    """`path` relative to `repo` as a POSIX string; absolute if outside it."""
    try:
        return Path(os.path.relpath(str(Path(path).resolve()),
                                    str(Path(repo).resolve()))).as_posix()
    except (OSError, ValueError):
        return Path(path).as_posix()


def key(path_str):
    """Comparison key for a path: POSIX separators, case-folded.

    Windows is case-insensitive and the pipelines pass whatever the runtime's
    diff printed, so `Tests/Foo.spec.ts` and `tests/foo.spec.ts` must be the
    same file to a waiver.
    """
    return str(path_str).replace("\\", "/").casefold()


def glob_to_regex(pattern):
    """Translate a `**`-aware glob to a regex matched against a POSIX path."""
    out = []
    i = 0
    while i < len(pattern):
        ch = pattern[i]
        if pattern.startswith("**/", i):
            out.append("(?:[^/]+/)*")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif ch == "*":
            out.append("[^/]*")
            i += 1
        elif ch == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(ch))
            i += 1
    return re.compile("^" + "".join(out) + "$", re.IGNORECASE)


def is_test_path(rel, globs):
    """True when a repo-relative POSIX path matches any test glob.

    A pattern with no `/` is also matched against the basename, so
    `--test-globs "*.spec.ts"` behaves the way a shell user expects.
    """
    base = rel.rsplit("/", 1)[-1]
    for pattern in globs:
        rx = glob_to_regex(pattern)
        if rx.match(rel):
            return True
        if "/" not in pattern and rx.match(base):
            return True
    return False


def discover_src_roots(repo, explicit=None):
    """The directories that hold production code.

    Heuristic, in order, and documented in ../references/:

      1. `--src-roots` replaces everything below when given.
      2. `src`, `app`, `lib`, `Source` under the repo root, when they exist.
      3. For every project manifest (`package.json`, `pyproject.toml`,
         `*.csproj`) at depth <= 3 from the repo root: that manifest's own
         `src`/`app`/`lib`/`Source` subdirectory when one exists, else -- for
         a `.csproj` only -- the manifest's own directory, because the C#
         convention is code beside the project file.

    Noise directories (`node_modules`, `bin`, `obj`, `dist`, ...) are never
    walked and never roots. Returns absolute Paths, deduplicated, sorted.
    """
    repo = Path(repo).resolve()
    if explicit:
        roots = []
        for raw in explicit:
            p = Path(raw)
            if not p.is_absolute():
                p = repo / raw
            roots.append(p.resolve())
        return sorted({r for r in roots if r.is_dir()}, key=lambda p: str(p))

    found = set()
    for name in CONVENTIONAL_SRC_DIRS:
        candidate = repo / name
        if candidate.is_dir():
            found.add(candidate.resolve())

    for manifest_dir in _manifest_dirs(repo, max_depth=3):
        subs = [manifest_dir / n for n in CONVENTIONAL_SRC_DIRS
                if (manifest_dir / n).is_dir()]
        if subs:
            found.update(s.resolve() for s in subs)
        elif any(c.suffix in MANIFEST_SUFFIXES
                 for c in manifest_dir.glob("*") if c.is_file()):
            found.add(manifest_dir.resolve())

    # A root inside another root is redundant; a root inside noise is wrong.
    roots = []
    for r in sorted(found, key=lambda p: len(str(p))):
        if any(part in NOISE_DIRS for part in r.parts):
            continue
        if any(_is_under(r, kept) for kept in roots):
            continue
        roots.append(r)
    return sorted(roots, key=lambda p: str(p))


def _manifest_dirs(repo, max_depth):
    """Directories holding a project manifest, walking at most `max_depth`."""
    out = []
    repo_parts = len(repo.parts)
    for root, dirs, files in os.walk(str(repo)):
        rp = Path(root)
        depth = len(rp.parts) - repo_parts
        dirs[:] = [d for d in dirs
                   if d not in NOISE_DIRS and not d.startswith(".")]
        if depth >= max_depth:
            dirs[:] = []
        for fn in files:
            if fn in MANIFEST_NAMES or Path(fn).suffix in MANIFEST_SUFFIXES:
                out.append(rp)
                break
    return out


def _is_under(child, parent):
    try:
        Path(child).resolve().relative_to(Path(parent).resolve())
        return True
    except ValueError:
        return False


def under_any_src_root(path, src_roots):
    """True when `path` is lexically inside one of the src roots.

    LEXICAL on purpose: a specifier that points at a file which has since
    moved must not make a real spec look fake. Existence is checked
    separately by resolve_specifier().
    """
    try:
        target = Path(path)
        target = target if target.is_absolute() else target.resolve()
    except (OSError, ValueError):
        return False
    for root in src_roots:
        try:
            os.path.relpath(str(target), str(root))
        except ValueError:
            continue
        rel = os.path.relpath(str(target), str(root)).replace("\\", "/")
        if rel != ".." and not rel.startswith("../"):
            return True
    return False


# ---------------------------------------------------------------------------
# Source masking: strings and comments blanked, offsets preserved
# ---------------------------------------------------------------------------

def mask_source(text, language):
    """(masked, literals) -- code with strings/comments blanked to spaces.

    `masked` is the SAME LENGTH as `text` (newlines kept), so every offset in
    it maps back to a real line. `literals` is a list of `(offset, value)`
    for every string literal, because the src-path check needs the literal
    values the masking removes.

    Deliberately a scanner, not a parser: regex/division ambiguity is
    resolved by treating `/` as division unless it opens a `//` or `/*`, so a
    regex literal's contents stay visible. That over-reports rather than
    under-reports, which is the right direction for a gate that must not
    silently pass a file it failed to read.
    """
    out = list(text)
    literals = []
    i, n = 0, len(text)
    py = language == "python"

    def blank(start, end):
        for j in range(start, min(end, n)):
            if out[j] != "\n":
                out[j] = " "

    while i < n:
        ch = text[i]
        # line comment
        if not py and text.startswith("//", i):
            j = text.find("\n", i)
            j = n if j == -1 else j
            blank(i, j)
            i = j
            continue
        if py and ch == "#":
            j = text.find("\n", i)
            j = n if j == -1 else j
            blank(i, j)
            i = j
            continue
        # block comment
        if not py and text.startswith("/*", i):
            j = text.find("*/", i + 2)
            j = n if j == -1 else j + 2
            blank(i, j)
            i = j
            continue
        # python triple-quoted
        if py and (text.startswith('"""', i) or text.startswith("'''", i)):
            q = text[i:i + 3]
            j = text.find(q, i + 3)
            j = n if j == -1 else j + 3
            literals.append((i, text[i + 3:max(i + 3, j - 3)]))
            blank(i, j)
            i = j
            continue
        # string / template literal
        if ch in ("'", '"', "`"):
            j = i + 1
            buf = []
            while j < n:
                c = text[j]
                if c == "\\":
                    j += 2
                    continue
                if c == ch:
                    break
                if c == "\n" and ch != "`":
                    break            # unterminated single-line string
                buf.append(c)
                j += 1
            end = min(j + 1, n)
            literals.append((i, "".join(buf)))
            blank(i, end)
            i = end
            continue
        i += 1
    return "".join(out), literals


def language_of(path):
    suffix = Path(path).suffix.lower()
    if suffix == ".py":
        return "python"
    if suffix == ".cs":
        return "csharp"
    return "cfamily"


def line_of(text, offset):
    return text.count("\n", 0, max(0, offset)) + 1


def excerpt_at(text, offset, limit=140):
    lines = text.splitlines()
    idx = line_of(text, offset) - 1
    if 0 <= idx < len(lines):
        return lines[idx].strip()[:limit]
    return ""


# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------
IMPORT_SPEC_RE = re.compile(
    r"""(?:\bfrom\s*|\bimport\s*|\brequire\s*\(\s*|\bimport\s*\(\s*)"""
    r"""(['"])([^'"\n]+)\1""")
PY_IMPORT_RE = re.compile(
    r"(?m)^\s*(?:from\s+([\w\.]+)\s+import\b|import\s+([\w\.]+))")
CS_USING_RE = re.compile(r"(?m)^\s*using\s+(?:static\s+)?([\w\.]+)\s*;")


def import_specifiers(text, literals, language):
    """(specifier, offset) pairs. Uses the RAW text, since masking eats them."""
    out = []
    if language == "python":
        for m in PY_IMPORT_RE.finditer(text):
            out.append(((m.group(1) or m.group(2)), m.start()))
        return out
    if language == "csharp":
        for m in CS_USING_RE.finditer(text):
            out.append((m.group(1), m.start()))
        return out
    for m in IMPORT_SPEC_RE.finditer(text):
        out.append((m.group(2), m.start()))
    return out


def resolve_specifier(spec, test_file, repo, src_roots):
    """The absolute path a JS/TS specifier points at, or None for a package.

    Relative specifiers resolve from the test file's directory. `@/x` and
    `~/x` -- the two aliases in near-universal use -- are tried against every
    src root, which is documented as a heuristic: a project that aliases `@`
    to something else gets a miss, never a false hit.
    """
    base = Path(test_file).resolve().parent
    candidates = []
    if spec.startswith("./") or spec.startswith("../") or spec == "." or spec == "..":
        candidates.append(base / spec)
    elif spec.startswith("/"):
        candidates.append(Path(repo) / spec.lstrip("/"))
    elif spec.startswith("@/") or spec.startswith("~/"):
        for root in src_roots:
            candidates.append(root / spec[2:])
    else:
        return None                     # bare package specifier
    for cand in candidates:
        for suffix in RESOLVE_SUFFIXES:
            probe = Path(str(cand) + suffix)
            if probe.is_file():
                return probe.resolve()
            index = cand / ("index" + suffix) if suffix else None
            if index is not None and index.is_file():
                return index.resolve()
    # Nothing on disk: fall back to the LEXICAL path so a moved file does not
    # turn a real spec into a fake one.
    return candidates[0].resolve() if candidates else None


def namespace_roots(src_roots):
    """Top-level names under the src roots, for C#/Python import matching."""
    names = set()
    for root in src_roots:
        names.add(root.name.casefold())
        try:
            for child in root.iterdir():
                if child.is_dir() and child.name not in NOISE_DIRS:
                    names.add(child.name.casefold())
                elif child.suffix.lower() in (".py", ".cs", ".ts", ".js"):
                    names.add(child.stem.casefold())
        except OSError:
            continue
    return names


def csproj_stems(repo):
    """Project names, so `using Project.Namespace;` reads as production."""
    stems = set()
    for manifest_dir in _manifest_dirs(Path(repo).resolve(), max_depth=3):
        try:
            for child in manifest_dir.glob("*.csproj"):
                stems.add(child.stem.casefold())
                stems.update(part.casefold()
                             for part in child.stem.split(".") if part)
        except OSError:
            continue
    return stems


def production_imports(test_file, text, literals, language, repo, src_roots,
                       ns_roots, project_stems):
    """The import lines that reach production code: [(spec, offset)]."""
    hits = []
    for spec, offset in import_specifiers(text, literals, language):
        if language == "csharp":
            first = spec.split(".")[0].casefold()
            if first in ns_roots or first in project_stems:
                hits.append((spec, offset))
            continue
        if language == "python":
            first = spec.split(".")[0].casefold()
            if first in ns_roots:
                hits.append((spec, offset))
            continue
        resolved = resolve_specifier(spec, test_file, repo, src_roots)
        if resolved is not None and under_any_src_root(resolved, src_roots):
            hits.append((spec, offset))
    return hits


# ---------------------------------------------------------------------------
# Definitions inside the test file
# ---------------------------------------------------------------------------
class Definition(object):
    def __init__(self, name, kind, offset, body, body_offset):
        self.name = name
        self.kind = kind
        self.offset = offset
        self.body = body
        self.body_offset = body_offset
        self.statements = 0
        self.drives = False

    def __repr__(self):                                  # pragma: no cover
        return "<Definition {0} {1} stmts={2}>".format(
            self.name, self.kind, self.statements)


def match_brace(masked, open_index):
    """Index just past the `}` matching the `{` at `open_index`, or None."""
    depth = 0
    for i in range(open_index, len(masked)):
        ch = masked[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i + 1
    return None


def match_paren(masked, open_index):
    """Index just past the `)` matching the `(` at `open_index`, or None."""
    depth = 0
    for i in range(open_index, len(masked)):
        ch = masked[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return i + 1
    return None


FUNC_DEF_RE = re.compile(
    r"\b(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s*\*?\s*(\w+)\s*[(<]")
CLASS_DEF_RE = re.compile(r"\b(?:export\s+)?(?:default\s+)?class\s+(\w+)\b")
BINDING_RE = re.compile(r"\b(?:const|let|var)\s+(\w+)\s*(?::[^=;\n]*)?=\s*")
PY_DEF_RE = re.compile(r"(?m)^([ \t]*)(?:async\s+)?def\s+(\w+)\s*\(")
PY_CLASS_RE = re.compile(r"(?m)^([ \t]*)class\s+(\w+)\b")
CS_METHOD_RE = re.compile(
    r"(?m)^[ \t]*(?:\[[^\]]*\][ \t]*)*"
    r"(?:public|private|protected|internal)"
    r"(?:[ \t]+(?:static|async|override|virtual|sealed|new|partial|"
    r"readonly|extern|unsafe))*"
    r"[ \t]+[\w<>\[\],\.\?]+[ \t]+(\w+)[ \t]*\(")
CS_LOCAL_FUNC_RE = re.compile(
    r"(?m)^[ \t]+(?:static[ \t]+)?[\w<>\[\],\.\?]+[ \t]+(\w+)[ \t]*\([^;{]*\)"
    r"[ \t]*\{")


def find_definitions(masked, language):
    """Every named function/class/arrow definition, at any nesting depth.

    Any depth on purpose: a tautology hides just as well inside a
    `page.evaluate(() => { function computeShowSlideData() {...} })` body as
    at the top of the file, and a `describe` callback is nesting too.
    """
    defs = []
    if language == "python":
        lines = masked.splitlines(keepends=True)
        starts = []
        pos = 0
        for line in lines:
            starts.append(pos)
            pos += len(line)
        for rx, kind in ((PY_DEF_RE, "def"), (PY_CLASS_RE, "class")):
            for m in rx.finditer(masked):
                indent = len(m.group(1).expandtabs(4))
                name = m.group(2)
                first = line_of(masked, m.start())
                body_lines = []
                for idx in range(first, len(lines)):
                    line = lines[idx]
                    if not line.strip():
                        body_lines.append(line)
                        continue
                    this_indent = len(line) - len(line.lstrip())
                    this_indent = len(line[:this_indent].expandtabs(4))
                    if this_indent <= indent:
                        break
                    body_lines.append(line)
                body = "".join(body_lines)
                defs.append(Definition(name, kind, m.start(), body,
                                       starts[min(first, len(starts) - 1)]))
        return defs

    if language == "csharp":
        for rx, kind in ((CS_METHOD_RE, "method"),
                         (CS_LOCAL_FUNC_RE, "local")):
            for m in rx.finditer(masked):
                name = m.group(1)
                brace = masked.find("{", m.end() - 1)
                if brace == -1:
                    continue
                end = match_brace(masked, brace)
                if end is None:
                    continue
                defs.append(Definition(name, kind, m.start(),
                                       masked[brace + 1:end - 1], brace + 1))
        _dedupe_definitions(defs)
        return defs

    for m in FUNC_DEF_RE.finditer(masked):
        brace = _brace_after_signature(masked, m.end() - 1)
        if brace is None:
            continue
        end = match_brace(masked, brace)
        if end is None:
            continue
        defs.append(Definition(m.group(1), "function", m.start(),
                               masked[brace + 1:end - 1], brace + 1))

    for m in CLASS_DEF_RE.finditer(masked):
        brace = masked.find("{", m.end())
        if brace == -1:
            continue
        end = match_brace(masked, brace)
        if end is None:
            continue
        defs.append(Definition(m.group(1), "class", m.start(),
                               masked[brace + 1:end - 1], brace + 1))

    for m in BINDING_RE.finditer(masked):
        name = m.group(1)
        rest = m.end()
        body_span = _arrow_or_function_body(masked, rest)
        if body_span is None:
            continue
        brace, end = body_span
        defs.append(Definition(name, "arrow", m.start(),
                               masked[brace + 1:end - 1], brace + 1))
    _dedupe_definitions(defs)
    return defs


def _dedupe_definitions(defs):
    """Drop definitions two patterns both matched (same name, same body)."""
    seen = set()
    unique = []
    for d in defs:
        k = (d.name, d.body_offset)
        if k in seen:
            continue
        seen.add(k)
        unique.append(d)
    defs[:] = unique


def _brace_after_signature(masked, open_paren_or_angle):
    """The `{` that opens a `function name(...)` / `name<T>(...)` body."""
    i = open_paren_or_angle
    if i >= len(masked):
        return None
    if masked[i] == "<":
        depth = 0
        while i < len(masked):
            if masked[i] == "<":
                depth += 1
            elif masked[i] == ">":
                depth -= 1
                if depth == 0:
                    i += 1
                    break
            i += 1
        while i < len(masked) and masked[i] in " \t\r\n":
            i += 1
        if i >= len(masked) or masked[i] != "(":
            return None
    close = match_paren(masked, i)
    if close is None:
        return None
    brace = masked.find("{", close)
    if brace == -1:
        return None
    # A `:` return type may sit between; anything with a `;` first is a
    # declaration (an overload signature or a `.d.ts` line), not a body.
    between = masked[close:brace]
    if ";" in between or "=" in between.replace("=>", ""):
        return None
    return brace


def _arrow_or_function_body(masked, start):
    """(brace, end) for `= (...) => {` / `= async function(...) {`, else None."""
    i = start
    n = len(masked)
    while i < n and masked[i] in " \t\r\n":
        i += 1
    if masked.startswith("async", i):
        i += 5
        while i < n and masked[i] in " \t\r\n":
            i += 1
    if masked.startswith("function", i):
        i += 8
        while i < n and masked[i] in " \t\r\n":
            i += 1
        while i < n and (masked[i].isalnum() or masked[i] in "_$"):
            i += 1
        while i < n and masked[i] in " \t\r\n":
            i += 1
        if i >= n or masked[i] != "(":
            return None
        close = match_paren(masked, i)
        if close is None:
            return None
        brace = masked.find("{", close)
        if brace == -1:
            return None
        end = match_brace(masked, brace)
        return None if end is None else (brace, end)
    if i < n and masked[i] == "(":
        close = match_paren(masked, i)
        if close is None:
            return None
        j = close
    else:
        j = i
        while j < n and (masked[j].isalnum() or masked[j] in "_$"):
            j += 1
        if j == i:
            return None
    # Only whitespace or a return-type annotation may sit between the
    # parameter list and the `=>`. Without this bound, `const result = await
    # page.evaluate(async () => {...})` reads as an arrow named `result`:
    # the scan walks past `await`, finds the `=>` INSIDE the call, and
    # reports the callback's body as a definition of `result`. That is how
    # `test_inline_reimplementation` came to name `result` three times.
    arrow = masked.find("=>", j)
    if arrow == -1:
        return None
    if not re.match(r"^\s*(?::[^;{()]*)?$", masked[j:arrow]):
        return None
    k = arrow + 2
    while k < n and masked[k] in " \t\r\n":
        k += 1
    if k >= n or masked[k] != "{":
        return None                    # concise body: a one-expression arrow
    end = match_brace(masked, k)
    return None if end is None else (k, end)


CONTROL_KEYWORD_RE = re.compile(
    r"\b(?:if|for|while|switch|try|do|case|foreach|elif|except|match)\b")


def count_statements(body, language):
    """A deliberately crude size proxy: is this logic or a one-liner?

    C-family: `;` terminators plus control-flow keywords, anywhere in the
    body. Python: non-blank, non-comment logical lines. Both over-count
    slightly (a `for (a; b; c)` header is three), which is the safe
    direction: the size test is a FLOOR on `test_inline_reimplementation`,
    and the discrimination comes from the name match and the driver check.
    """
    if language == "python":
        return len([ln for ln in body.splitlines()
                    if ln.strip() and not ln.strip().startswith("#")])
    return body.count(";") + len(CONTROL_KEYWORD_RE.findall(body))


def classify_definitions(defs, language):
    for d in defs:
        d.statements = count_statements(d.body, language)
        d.drives = bool(DRIVER_TOKENS_RE.search(d.body))


def reimplementation_candidates(defs):
    """Definitions that are real logic and do NOT drive the application."""
    out = []
    for d in defs:
        if d.statements < MIN_STATEMENTS or d.drives:
            continue
        if len(d.name) < MIN_NAME_LENGTH:
            continue
        low = d.name.casefold()
        if low in STOPWORDS or low.startswith("test"):
            continue
        out.append(d)
    return out


# ---------------------------------------------------------------------------
# The src symbol index
# ---------------------------------------------------------------------------
SRC_EXPORT_RE = re.compile(
    r"(?m)^[ \t]*export\s+(?:default\s+)?(?:async\s+)?"
    r"(?:function\s*\*?|class|const|let|var|interface|type|enum)\s+(\w+)")
SRC_DECL_RE = re.compile(
    r"(?m)^[ \t]*(?:export\s+)?(?:default\s+)?(?:async\s+)?"
    r"(?:function\s*\*?|class)\s+(\w+)")
SRC_METHOD_RE = re.compile(
    r"(?m)^[ \t]*(?:(?:public|private|protected|internal|static|async|get|"
    r"set|override|virtual|abstract|readonly|sealed|partial|new)[ \t]+)*"
    r"([A-Za-z_$][\w$]*)[ \t]*\(")
SRC_PY_RE = re.compile(r"(?m)^[ \t]*(?:async\s+)?(?:def|class)\s+(\w+)")
# C# needs its own pattern: `public string Classify(int total)` has a TYPE
# between the modifiers and the name, which SRC_METHOD_RE (written for
# TS/JS object and class methods) reads as the name itself.
SRC_CS_RE = re.compile(
    r"(?m)^[ \t]*(?:\[[^\]]*\][ \t]*)*"
    r"(?:public|private|protected|internal)"
    r"(?:[ \t]+(?:static|async|override|virtual|sealed|new|partial|readonly|"
    r"abstract|extern|unsafe))*"
    r"[ \t]+(?:(?:class|record|struct|interface|enum)[ \t]+(\w+)"
    r"|[\w<>\[\],\.\?]+[ \t]+(\w+)[ \t]*[\(\{])")


def build_src_index(src_roots, test_globs, repo):
    """{name.casefold(): "rel/path.ts:LINE"} for symbols defined under src.

    Definitions, not only exports: the pattern this gate was built from is a
    Vue/TS class METHOD (`getBackupItemStatus(backup: any) {`) transcribed
    into a spec, and no `export` keyword appears anywhere near it. That
    widening is what makes the keyword STOPWORDS list load-bearing rather
    than cosmetic -- see the reference.
    """
    index = {}
    walked = 0
    for root in src_roots:
        for dirpath, dirnames, filenames in os.walk(str(root)):
            dirnames[:] = [d for d in dirnames
                           if d not in NOISE_DIRS and not d.startswith(".")]
            for fn in sorted(filenames):
                if Path(fn).suffix.lower() not in CODE_SUFFIXES:
                    continue
                full = Path(dirpath) / fn
                rel = rel_posix(full, repo)
                if is_test_path(rel, test_globs):
                    continue
                walked += 1
                if walked > MAX_INDEX_FILES:
                    return index
                try:
                    if full.stat().st_size > MAX_INDEX_BYTES:
                        continue
                    text = full.read_text(encoding=READ_ENCODING,
                                          errors="replace")
                except OSError:
                    continue
                lang = language_of(full)
                masked, _ = mask_source(text, lang)
                if lang == "python":
                    patterns = (SRC_PY_RE,)
                elif lang == "csharp":
                    patterns = (SRC_CS_RE,)
                else:
                    patterns = (SRC_EXPORT_RE, SRC_DECL_RE, SRC_METHOD_RE)
                for rx in patterns:
                    for m in rx.finditer(masked):
                        name = next((g for g in m.groups() if g), None)
                        if not name:
                            continue
                        low = name.casefold()
                        if low in STOPWORDS or len(name) < MIN_NAME_LENGTH:
                            continue
                        if low not in index:
                            index[low] = "{0}:{1}".format(
                                rel, line_of(masked, m.start()))
    return index


# ---------------------------------------------------------------------------
# The four checks
# ---------------------------------------------------------------------------

def touches_running_surface(masked, literals):
    """(bool, offset|None) -- does this file reach a running application?"""
    m = NAV_RE.search(masked)
    if m:
        return True, m.start()
    if re.search(r"\bbrowser_navigate\b", masked):
        return True, re.search(r"\bbrowser_navigate\b", masked).start()
    m = HTTP_CLIENT_RE.search(masked)
    if m:
        return True, m.start()
    m = FETCH_RE.search(masked)
    if m:
        has_url = any(HTTP_URL_RE.search(v or "") for _, v in literals)
        if has_url or BASEURL_RE.search(masked):
            return True, m.start()
    return False, None


def import_literal_offsets(text):
    """Quote offsets of every `import`/`require`/`from` specifier literal.

    Excluded from src_path_literals(): an `import ... from '../src/card'` IS
    a literal naming a path under a src root, and counting it would make
    `test_source_eval` fire on any spec that legitimately imports production
    code and separately reads a JSON fixture.
    """
    return {m.start(1) for m in IMPORT_SPEC_RE.finditer(text)}


def src_path_literals(literals, src_roots, repo, test_file, skip_offsets=()):
    """Literals that name a path under a src root: [(offset, value)].

    Matched two ways, because the calls this catches build the path with
    `path.resolve(__dirname, '../../src/x.ts')` and the READ call itself sees
    only a variable: lexical resolution from the test file's directory, and a
    bare `<root>/` path segment anywhere in the literal.
    """
    root_names = {r.name.casefold() for r in src_roots}
    skip = set(skip_offsets)
    hits = []
    for offset, value in literals:
        if offset in skip:
            continue
        if not value or len(value) > 400:
            continue
        norm = value.replace("\\", "/")
        if "/" not in norm and not norm.endswith(CODE_SUFFIXES):
            continue
        segments = [s.casefold() for s in norm.split("/") if s]
        if any(s in root_names for s in segments):
            hits.append((offset, value))
            continue
        if norm.startswith("./") or norm.startswith("../"):
            probe = (Path(test_file).resolve().parent / norm)
            if under_any_src_root(probe, src_roots):
                hits.append((offset, value))
    return hits


def find_fallback_dom(masked):
    """Offset of a `catch` block that injects DOM after a `goto` was tried.

    The "fallback" shape: `try { await page.goto(...) } catch { setContent }`.
    A file with this shape has a `page.goto` and so passes the plain
    "setContent and never navigates" test, while still asserting against
    dummy HTML on every run where the app is down -- which is the run the
    author was trying to survive.
    """
    for m in re.finditer(r"\btry\b", masked):
        brace = masked.find("{", m.end())
        if brace == -1:
            continue
        try_end = match_brace(masked, brace)
        if try_end is None:
            continue
        try_body = masked[brace + 1:try_end - 1]
        if not NAV_RE.search(try_body):
            continue
        tail = masked[try_end:try_end + 200]
        cm = re.match(r"\s*catch\b", tail)
        if not cm:
            continue
        cbrace = masked.find("{", try_end + cm.end() - 1)
        if cbrace == -1:
            continue
        cend = match_brace(masked, cbrace)
        if cend is None:
            continue
        catch_body = masked[cbrace + 1:cend - 1]
        hit = SET_CONTENT_RE.search(catch_body) or re.search(
            r"\.\s*innerHTML\s*=", catch_body)
        if hit:
            return cbrace + 1 + hit.start()
    return None


def judge_file(test_file, repo, src_roots, src_index, test_globs, ns_roots,
               project_stems):
    """The problem list for ONE test file."""
    path = Path(test_file)
    try:
        text = path.read_text(encoding=READ_ENCODING, errors="replace")
    except OSError as exc:
        raise GateError("cannot read {0}: {1}".format(test_file, exc))
    language = language_of(path)
    masked, literals = mask_source(text, language)
    problems = []

    def add(code, offset, detail):
        problems.append({
            "code": code,
            "file": rel_posix(path, repo),
            "line": line_of(text, offset),
            "excerpt": excerpt_at(text, offset),
            "detail": detail,
        })

    prod_imports = production_imports(path, text, literals, language, repo,
                                      src_roots, ns_roots, project_stems)
    runs, run_offset = touches_running_surface(masked, literals)

    # --- 1. test_no_production_import --------------------------------------
    if not prod_imports and not runs:
        entry = TEST_ENTRY_RE.search(text)
        add("test_no_production_import",
            entry.start() if entry else 0,
            "no import resolves to a file under {0}, and the file never "
            "navigates to a running application (no page.goto / "
            "browser_navigate / HTTP client). Whatever this asserts, it is "
            "not the product.".format(
                " / ".join(rel_posix(r, repo) for r in src_roots) or "a src root"))

    # --- 2. test_inline_reimplementation -----------------------------------
    defs = find_definitions(masked, language)
    classify_definitions(defs, language)
    candidates = reimplementation_candidates(defs)
    # One finding per NAME, not per occurrence: a spec that redefines the
    # same transcribed helper once per `test()` block is one problem stated
    # four times, and a gate that prints it four times trains its reader to
    # skim.
    named, named_seen = [], set()
    for d in candidates:
        low = d.name.casefold()
        if low in src_index and low not in named_seen:
            named_seen.add(low)
            named.append(d)
    for d in named:
        add("test_inline_reimplementation", d.offset,
            "`{0}` ({1} statements) is also defined at {2}; the test asserts "
            "against its own copy of that logic, so it stays green when the "
            "shipped one changes.".format(
                d.name, d.statements, src_index[d.name.casefold()]))
    distinct = []
    for d in candidates:
        if d.name.casefold() not in {c.name.casefold() for c in distinct}:
            distinct.append(d)
    if not named and len(distinct) >= 2 and not prod_imports and not runs:
        add("test_inline_reimplementation", distinct[0].offset,
            "{0} distinct self-contained logic definitions ({1}) in a file "
            "that imports no production code and navigates nowhere -- it is "
            "a module of its own with tests attached.".format(
                len(distinct),
                ", ".join("`{0}`".format(c.name) for c in distinct[:4])))

    # --- 3. test_source_eval -----------------------------------------------
    read_re = PY_READ_RE if language == "python" else READ_SOURCE_RE
    eval_re = PY_EVAL_RE if language == "python" else EVAL_RE
    read_hit = read_re.search(masked)
    eval_hit = eval_re.search(masked)
    src_literal = src_path_literals(literals, src_roots, repo, path,
                                    import_literal_offsets(text))
    if read_hit and eval_hit and src_literal:
        add("test_source_eval", eval_hit.start(),
            "the file reads production source as TEXT ({0!r} at line {1}) and "
            "executes a slice of it; the assertion is against whatever the "
            "slice happened to capture, which drifts silently when the "
            "surrounding function is edited.".format(
                src_literal[0][1][:120],
                line_of(text, src_literal[0][0])))

    # --- 4. test_synthetic_dom ---------------------------------------------
    dom_hit = SET_CONTENT_RE.search(masked) or INNER_HTML_RE.search(masked)
    if dom_hit and not runs:
        add("test_synthetic_dom", dom_hit.start(),
            "the file builds its own DOM and never navigates to the "
            "application, so the markup under assertion is the test's, not "
            "the product's.")
    fallback = find_fallback_dom(masked)
    if fallback is not None:
        add("test_synthetic_dom", fallback,
            "a `catch` block injects dummy HTML after `page.goto` failed: on "
            "every run where the application is down this spec asserts "
            "against its own markup and reports green.")

    return problems


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def build_report(repo, files, src_roots=None, test_globs=None, waivers=None):
    """The full report dict. Raises GateError for exit-2 conditions."""
    repo_path = Path(repo)
    if not repo_path.is_dir():
        raise GateError("repo not found or not a directory: {0}".format(repo))
    repo_path = repo_path.resolve()
    globs = tuple(test_globs) if test_globs else DEFAULT_TEST_GLOBS
    roots = discover_src_roots(repo_path, src_roots)
    if not roots:
        raise GateError(
            "no src root found under {0} and none given: pass --src-roots "
            "explicitly. Judging a test file against an empty production "
            "index would report every file as authentic, which is worse "
            "than refusing.".format(repo))

    waiver_map = {}
    for wf, reason in (waivers or ()):
        waiver_map[key(rel_posix(Path(repo_path) / wf if not Path(wf).is_absolute()
                                 else wf, repo_path))] = reason

    src_index = build_src_index(roots, globs, repo_path)
    ns_roots = namespace_roots(roots)
    project_stems = csproj_stems(repo_path)

    judged, ignored, warnings = [], [], []
    seen = set()
    for raw in files:
        p = Path(raw)
        if not p.is_absolute():
            p = repo_path / raw
        rel = rel_posix(p, repo_path)
        if key(rel) in seen:
            continue
        seen.add(key(rel))
        if not p.is_file():
            raise GateError("file not found: {0}".format(raw))
        if not is_test_path(rel, globs):
            ignored.append({"file": rel, "reason": "not a test file under "
                                                   "--test-globs"})
            continue
        problems = judge_file(p, repo_path, roots, src_index, globs, ns_roots,
                              project_stems)
        waived_by = waiver_map.get(key(rel))
        if problems:
            verdict = "ALLOWED" if waived_by else "FAIL"
        else:
            verdict = "PASS"
        judged.append({"file": rel, "verdict": verdict, "problems": problems,
                       "waived_by": waived_by if problems else None})

    judged_keys = {key(e["file"]) for e in judged}
    for wk, reason in waiver_map.items():
        if wk not in judged_keys:
            warnings.append(
                "--allow {0} names a file that was not judged in this run; "
                "the waiver had no effect".format(wk))

    if not judged and not ignored:
        raise GateError("no files given: pass --changed-files (or --files) "
                        "with at least one path")

    failing = [e for e in judged if e["verdict"] == "FAIL"]
    allowed = [e for e in judged if e["verdict"] == "ALLOWED"]
    if failing:
        result = "FAIL"
    elif allowed:
        result = "ALLOWED"
    else:
        result = "PASS"

    codes = sorted({pr["code"] for e in judged for pr in e["problems"]})
    return {
        "repo": str(repo_path).replace("\\", "/"),
        "src_roots": [rel_posix(r, repo_path) for r in roots],
        "test_globs": list(globs),
        "src_symbols": len(src_index),
        "result": result,
        "files": judged,
        "ignored": ignored,
        "problem_codes": codes,
        "waivers": [{"file": f, "reason": r} for f, r in sorted(waiver_map.items())],
        "warnings": warnings,
        "error": None,
    }


def render_text(report):
    lines = []
    lines.append("check_test_authenticity.py: {0}".format(report["result"]))
    lines.append("  src roots: {0} ({1} symbols indexed)".format(
        ", ".join(report["src_roots"]) or "-", report["src_symbols"]))
    for entry in report["files"]:
        lines.append("  [{0}] {1}".format(entry["verdict"], entry["file"]))
        if entry["waived_by"]:
            lines.append("        waived: {0}".format(entry["waived_by"]))
        for pr in entry["problems"]:
            lines.append("        {0} at {1}:{2}".format(
                pr["code"], pr["file"], pr["line"]))
            if pr["excerpt"]:
                lines.append("          | {0}".format(pr["excerpt"]))
            lines.append("          -> {0}".format(pr["detail"]))
    for entry in report["ignored"]:
        lines.append("  [SKIP] {0} ({1})".format(entry["file"],
                                                 entry["reason"]))
    for w in report["warnings"]:
        lines.append("  warning: {0}".format(w))
    if report["error"]:
        lines.append("  error: {0}".format(report["error"]))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv):
    parser = argparse.ArgumentParser(prog="check_test_authenticity.py")
    parser.add_argument("--repo", help="the repository root")
    parser.add_argument("--files", nargs="+", default=[], dest="files",
                        help="test files to judge")
    parser.add_argument("--changed-files", nargs="+", default=[],
                        dest="changed_files",
                        help="same as --files; the spelling the pipelines use")
    parser.add_argument("--src-roots", nargs="+", default=None,
                        dest="src_roots",
                        help="override the production-code roots entirely")
    parser.add_argument("--test-globs", nargs="+", default=None,
                        dest="test_globs",
                        help="override which paths count as test files")
    parser.add_argument("--allow", action="append", default=[],
                        help="waive one test file; needs a paired --reason")
    parser.add_argument("--reason", action="append", default=[],
                        help="the written reason for the preceding --allow")
    parser.add_argument("--milestone", help="the unit, scoping ledger records")
    parser.add_argument("--ledger",
                        help="append one JSON record per run to this path")
    parser.add_argument("--json", action="store_true",
                        help="emit the report as JSON instead of text")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)

    if args.self_test:
        return run_self_test()

    files = list(args.files) + list(args.changed_files)

    def ledger_inputs():
        """The judged files as paths that actually HASH.

        The pipelines pass repo-relative paths and the gate is not run from
        the repo, so hashing the argument verbatim records `null` for every
        input -- the record would then prove a run happened over nothing.
        Resolved against `--repo` when there is one.
        """
        out = []
        for raw in files:
            p = Path(raw)
            if not p.is_absolute() and args.repo:
                p = Path(args.repo) / raw
            out.append(str(p).replace("\\", "/"))
        return out

    def finish(code, verdict, extra=None):
        """One exit point: EVERY return path records a ledger line."""
        append_ledger(args.ledger, argv, args.milestone, ledger_inputs(),
                      verdict, code, extra)
        return code

    def fail_usage(message):
        payload = {"repo": args.repo, "src_roots": [], "test_globs": [],
                   "src_symbols": 0, "result": "ERROR", "files": [],
                   "ignored": [], "problem_codes": [], "waivers": [],
                   "warnings": [], "error": message}
        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            print(render_text(payload))
        return finish(2, "ERROR")

    if not args.repo:
        return fail_usage("missing required argument: --repo")
    if not files:
        return fail_usage("missing required argument: --changed-files "
                          "(or --files)")
    if len(args.allow) != len(args.reason):
        return fail_usage(
            "each --allow needs exactly one paired --reason: got {0} "
            "--allow and {1} --reason".format(len(args.allow),
                                              len(args.reason)))
    for reason in args.reason:
        if not reason.strip():
            return fail_usage(
                "--reason requires non-empty text: an unreasoned waiver is "
                "indistinguishable from an omission")

    waivers = list(zip(args.allow, args.reason))
    try:
        report = build_report(args.repo, files, args.src_roots,
                              args.test_globs, waivers)
    except GateError as exc:
        return fail_usage(str(exc))

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(render_text(report))

    extra = {"problem_codes": report["problem_codes"],
             "judged": len(report["files"]),
             "ignored": len(report["ignored"])}
    if report["result"] == "FAIL":
        extra["failing_files"] = [e["file"] for e in report["files"]
                                  if e["verdict"] == "FAIL"]
        return finish(1, "FAIL", extra)
    if report["result"] == "ALLOWED":
        extra["allow_reasons"] = {w["file"]: w["reason"]
                                  for w in report["waivers"]}
        return finish(0, "PASS", extra)
    return finish(0, "PASS", extra)


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

def run_self_test():
    import shutil

    class TestAuthenticityTests(unittest.TestCase):
        def setUp(self):
            self.repo = Path(tempfile.mkdtemp()).resolve()
            self.write("package.json", '{"name":"app"}')
            self.write("src/backup-card.ts", SRC_BACKUP_CARD)
            self.write("src/helper/enums.ts", SRC_ENUMS)

        def tearDown(self):
            shutil.rmtree(str(self.repo), ignore_errors=True)

        # -- helpers -------------------------------------------------------
        def write(self, rel, content):
            p = self.repo / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
            return p

        def report(self, *rels, **kw):
            return build_report(self.repo, list(rels), **kw)

        def codes(self, rel, *rels, **kw):
            rep = self.report(rel, *rels, **kw)
            return sorted({pr["code"] for e in rep["files"]
                           for pr in e["problems"]})

        def codes_for(self, rep, rel):
            for e in rep["files"]:
                if key(e["file"]) == key(rel):
                    return sorted({pr["code"] for pr in e["problems"]})
            return None

        def cli(self, argv):
            import contextlib
            import io
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = main(argv)
            return code, buf.getvalue()

        # -- src roots and test globs --------------------------------------
        def test_src_root_defaults_find_src(self):
            roots = discover_src_roots(self.repo)
            self.assertEqual([r.name for r in roots], ["src"])

        def test_src_root_from_a_csproj_beside_its_code(self):
            other = Path(tempfile.mkdtemp()).resolve()
            try:
                (other / "Api").mkdir()
                (other / "Api" / "Api.csproj").write_text("<Project/>",
                                                          encoding="utf-8")
                roots = discover_src_roots(other)
                self.assertEqual([r.name for r in roots], ["Api"])
            finally:
                shutil.rmtree(str(other), ignore_errors=True)

        def test_explicit_src_roots_replace_the_defaults(self):
            self.write("engine/thing.ts", "export function widen() { }")
            roots = discover_src_roots(self.repo, ["engine"])
            self.assertEqual([r.name for r in roots], ["engine"])

        def test_noise_directories_are_never_src_roots(self):
            self.write("node_modules/pkg/package.json", "{}")
            self.write("node_modules/pkg/src/a.ts", "export const a = 1;")
            roots = discover_src_roots(self.repo)
            self.assertNotIn("node_modules",
                             {p for r in roots for p in r.parts})

        def test_non_test_files_are_ignored_not_judged(self):
            self.write("src/plain.ts", "export function alpha() { }")
            rep = self.report("src/plain.ts")
            self.assertEqual(rep["files"], [])
            self.assertEqual(len(rep["ignored"]), 1)
            self.assertEqual(rep["result"], "PASS")

        def test_test_globs_can_be_overridden(self):
            self.write("weird/thing.check.ts", REAL_IMPORTING_SPEC)
            rep = self.report("weird/thing.check.ts",
                              test_globs=["**/*.check.ts"])
            self.assertEqual(len(rep["files"]), 1)

        def test_a_tests_directory_file_is_a_test_file(self):
            self.write("tests/anything.ts", REAL_IMPORTING_SPEC)
            rep = self.report("tests/anything.ts")
            self.assertEqual(len(rep["files"]), 1)

        def test_dunder_tests_directory_is_a_test_file(self):
            self.write("__tests__/a.ts", REAL_IMPORTING_SPEC)
            self.assertEqual(len(self.report("__tests__/a.ts")["files"]), 1)

        # -- legitimate patterns must PASS ---------------------------------
        def test_a_spec_importing_from_src_passes(self):
            self.write("tests/real.spec.ts", REAL_IMPORTING_SPEC)
            self.assertEqual(self.codes("tests/real.spec.ts"), [])

        def test_a_spec_that_only_navigates_passes(self):
            self.write("tests/e2e.spec.ts", REAL_E2E_SPEC)
            self.assertEqual(self.codes("tests/e2e.spec.ts"), [])

        def test_an_e2e_spec_with_page_driving_helpers_passes(self):
            """The regression that made the driver-token rule load-bearing."""
            self.write("tests/journey.spec.ts", REAL_E2E_WITH_HELPERS)
            self.assertEqual(self.codes("tests/journey.spec.ts"), [])

        def test_a_short_helper_in_a_test_is_fine(self):
            self.write("tests/short.spec.ts", REAL_SHORT_HELPER_SPEC)
            self.assertEqual(self.codes("tests/short.spec.ts"), [])

        def test_page_evaluate_reading_the_real_dom_is_fine(self):
            self.write("tests/title.spec.ts", REAL_EVALUATE_SPEC)
            self.assertEqual(self.codes("tests/title.spec.ts"), [])

        def test_a_csharp_xunit_test_instantiating_a_handler_passes(self):
            self.write("Api/Api.csproj", "<Project/>")
            self.write("Api/Handlers/OrderHandler.cs", SRC_CSHARP_HANDLER)
            self.write("Api.Tests/OrderHandlerTests.cs", REAL_CSHARP_TEST)
            rep = self.report("Api.Tests/OrderHandlerTests.cs")
            self.assertEqual(self.codes_for(rep, "Api.Tests/OrderHandlerTests.cs"),
                             [])

        def test_a_python_test_importing_the_package_passes(self):
            self.write("src/pkg/__init__.py", "")
            self.write("src/pkg/rules.py", SRC_PYTHON_RULES)
            self.write("tests/test_rules.py", REAL_PYTHON_TEST)
            self.assertEqual(self.codes("tests/test_rules.py"), [])

        def test_an_at_alias_import_counts_as_production(self):
            self.write("tests/alias.spec.ts", REAL_ALIAS_SPEC)
            self.assertEqual(self.codes("tests/alias.spec.ts"), [])

        def test_a_request_get_against_the_api_passes(self):
            self.write("tests/api.spec.ts", REAL_REQUEST_SPEC)
            self.assertEqual(self.codes("tests/api.spec.ts"), [])

        # -- 1. test_no_production_import ----------------------------------
        def test_no_production_import_fires_on_a_hermetic_spec(self):
            self.write("tests/hermetic.spec.ts", FAKE_HERMETIC_ENUM_SPEC)
            self.assertIn("test_no_production_import",
                          self.codes("tests/hermetic.spec.ts"))

        def test_no_production_import_does_not_fire_when_only_importing(self):
            self.write("tests/imp.spec.ts", REAL_IMPORTING_SPEC)
            self.assertNotIn("test_no_production_import",
                             self.codes("tests/imp.spec.ts"))

        def test_no_production_import_does_not_fire_when_only_navigating(self):
            self.write("tests/nav.spec.ts", REAL_E2E_SPEC)
            self.assertNotIn("test_no_production_import",
                             self.codes("tests/nav.spec.ts"))

        def test_a_bare_package_import_is_not_production(self):
            self.write("tests/bare.spec.ts", FAKE_BARE_ONLY_SPEC)
            self.assertIn("test_no_production_import",
                          self.codes("tests/bare.spec.ts"))

        def test_a_commented_out_goto_does_not_count_as_navigation(self):
            self.write("tests/commented.spec.ts", FAKE_COMMENTED_GOTO_SPEC)
            self.assertIn("test_no_production_import",
                          self.codes("tests/commented.spec.ts"))

        def test_python_no_production_import(self):
            self.write("src/pkg/__init__.py", "")
            self.write("tests/test_fake.py", FAKE_PYTHON_TEST)
            self.assertIn("test_no_production_import",
                          self.codes("tests/test_fake.py"))

        def test_csharp_using_of_a_foreign_namespace_is_not_production(self):
            self.write("Api/Api.csproj", "<Project/>")
            self.write("Api/Handlers/OrderHandler.cs", SRC_CSHARP_HANDLER)
            self.write("Api.Tests/FakeTests.cs", FAKE_CSHARP_TEST)
            rep = self.report("Api.Tests/FakeTests.cs")
            self.assertIn("test_no_production_import",
                          self.codes_for(rep, "Api.Tests/FakeTests.cs"))

        # -- 2. test_inline_reimplementation -------------------------------
        def test_inline_reimplementation_on_a_name_match(self):
            self.write("tests/taut.spec.ts", FAKE_TAUTOLOGY_SPEC)
            self.assertIn("test_inline_reimplementation",
                          self.codes("tests/taut.spec.ts"))

        def test_inline_reimplementation_names_the_src_location(self):
            self.write("tests/taut.spec.ts", FAKE_TAUTOLOGY_SPEC)
            rep = self.report("tests/taut.spec.ts")
            detail = [pr["detail"] for e in rep["files"] for pr in e["problems"]
                      if pr["code"] == "test_inline_reimplementation"]
            self.assertTrue(any("src/backup-card.ts" in d for d in detail),
                            detail)

        def test_inline_reimplementation_inside_page_evaluate(self):
            self.write("tests/eval.spec.ts", FAKE_EVALUATE_REIMPL_SPEC)
            self.assertIn("test_inline_reimplementation",
                          self.codes("tests/eval.spec.ts"))

        def test_inline_reimplementation_fires_even_with_a_src_import(self):
            """The transcribed-helpers shape: real import, copied logic."""
            self.write("tests/transcribed.spec.ts", FAKE_TRANSCRIBED_SPEC)
            codes = self.codes("tests/transcribed.spec.ts")
            self.assertEqual(codes, ["test_inline_reimplementation"])

        def test_two_definitions_with_no_production_contact_fire(self):
            self.write("tests/module.spec.ts", FAKE_TWO_DEFS_SPEC)
            self.assertIn("test_inline_reimplementation",
                          self.codes("tests/module.spec.ts"))

        def test_one_unmatched_definition_alone_does_not_fire(self):
            self.write("tests/one.spec.ts", FAKE_ONE_DEF_SPEC)
            self.assertNotIn("test_inline_reimplementation",
                             self.codes("tests/one.spec.ts"))

        def test_two_definitions_in_a_navigating_spec_do_not_fire(self):
            """A real E2E spec's pure formatting helpers are not a tautology."""
            self.write("tests/format.spec.ts", REAL_E2E_TWO_PURE_HELPERS)
            self.assertEqual(self.codes("tests/format.spec.ts"), [])

        def test_a_two_statement_helper_is_below_the_floor(self):
            self.write("tests/floor.spec.ts", FAKE_TINY_NAMED_HELPER_SPEC)
            self.assertNotIn("test_inline_reimplementation",
                             self.codes("tests/floor.spec.ts"))

        def test_an_arrow_const_reimplementation_fires(self):
            self.write("tests/arrow.spec.ts", FAKE_ARROW_REIMPL_SPEC)
            self.assertIn("test_inline_reimplementation",
                          self.codes("tests/arrow.spec.ts"))

        def test_a_class_reimplementation_fires(self):
            self.write("src/policy.ts", SRC_POLICY_CLASS)
            self.write("tests/klass.spec.ts", FAKE_CLASS_REIMPL_SPEC)
            self.assertIn("test_inline_reimplementation",
                          self.codes("tests/klass.spec.ts"))

        def test_python_inline_reimplementation(self):
            self.write("src/pkg/__init__.py", "")
            self.write("src/pkg/rules.py", SRC_PYTHON_RULES)
            self.write("tests/test_copy.py", FAKE_PYTHON_REIMPL)
            self.assertIn("test_inline_reimplementation",
                          self.codes("tests/test_copy.py"))

        def test_csharp_inline_reimplementation(self):
            self.write("Api/Api.csproj", "<Project/>")
            self.write("Api/Handlers/OrderHandler.cs", SRC_CSHARP_HANDLER)
            self.write("Api.Tests/CopyTests.cs", FAKE_CSHARP_REIMPL)
            rep = self.report("Api.Tests/CopyTests.cs")
            self.assertIn("test_inline_reimplementation",
                          self.codes_for(rep, "Api.Tests/CopyTests.cs"))

        def test_an_awaited_call_is_not_an_arrow_definition(self):
            """`const result = await page.evaluate(() => {...})` is not a def."""
            self.write("tests/awaited.spec.ts", FAKE_AWAITED_EVALUATE_SPEC)
            rep = self.report("tests/awaited.spec.ts")
            details = [pr["detail"] for e in rep["files"]
                       for pr in e["problems"]]
            self.assertFalse(any("`result`" in d for d in details), details)

        def test_the_same_helper_defined_four_times_is_one_finding(self):
            self.write("tests/repeat.spec.ts", FAKE_REPEATED_HELPER_SPEC)
            rep = self.report("tests/repeat.spec.ts")
            found = [pr for e in rep["files"] for pr in e["problems"]
                     if pr["code"] == "test_inline_reimplementation"]
            self.assertEqual(len(found), 1, found)

        def test_one_name_defined_twice_is_not_two_definitions(self):
            """The >= 2 branch counts DISTINCT names, not occurrences."""
            self.write("tests/twice.spec.ts", FAKE_ONE_NAME_TWICE_SPEC)
            self.assertNotIn("test_inline_reimplementation",
                             self.codes("tests/twice.spec.ts"))

        def test_a_language_keyword_never_enters_the_src_index(self):
            index = build_src_index(discover_src_roots(self.repo),
                                    DEFAULT_TEST_GLOBS, self.repo)
            for word in ("if", "for", "while", "switch", "return", "data"):
                self.assertNotIn(word, index)

        def test_the_src_index_finds_a_class_method(self):
            index = build_src_index(discover_src_roots(self.repo),
                                    DEFAULT_TEST_GLOBS, self.repo)
            self.assertIn("getbackupitemstatus", index)

        def test_the_src_index_skips_test_files_under_a_src_root(self):
            self.write("src/thing.spec.ts",
                       "export function onlyInATestFile() { let a = 1; "
                       "let b = 2; let c = 3; }")
            index = build_src_index(discover_src_roots(self.repo),
                                    DEFAULT_TEST_GLOBS, self.repo)
            self.assertNotIn("onlyinatestfile", index)

        # -- 3. test_source_eval -------------------------------------------
        def test_source_eval_fires_on_readfilesync_plus_new_function(self):
            self.write("tests/srceval.spec.ts", FAKE_SOURCE_EVAL_SPEC)
            self.assertIn("test_source_eval",
                          self.codes("tests/srceval.spec.ts"))

        def test_source_eval_fires_on_transpile_module(self):
            self.write("tests/transpile.spec.ts", FAKE_TRANSPILE_SPEC)
            self.assertIn("test_source_eval",
                          self.codes("tests/transpile.spec.ts"))

        def test_source_eval_does_not_fire_on_reading_a_fixture(self):
            self.write("tests/fixture.json", "{}")
            self.write("tests/readfixture.spec.ts", REAL_FIXTURE_READ_SPEC)
            self.assertNotIn("test_source_eval",
                             self.codes("tests/readfixture.spec.ts"))

        def test_source_eval_does_not_fire_on_reading_src_without_eval(self):
            """Static source inspection is a different, weaker tier."""
            self.write("tests/staticread.spec.ts", FAKE_STATIC_READ_SPEC)
            self.assertNotIn("test_source_eval",
                             self.codes("tests/staticread.spec.ts"))

        def test_python_source_eval(self):
            self.write("src/pkg/__init__.py", "")
            self.write("src/pkg/rules.py", SRC_PYTHON_RULES)
            self.write("tests/test_srceval.py", FAKE_PYTHON_SOURCE_EVAL)
            self.assertIn("test_source_eval",
                          self.codes("tests/test_srceval.py"))

        def test_execsync_is_not_a_python_style_exec_call(self):
            self.write("tests/execsync.spec.ts", REAL_EXECSYNC_SPEC)
            self.assertNotIn("test_source_eval",
                             self.codes("tests/execsync.spec.ts"))

        # -- 4. test_synthetic_dom -----------------------------------------
        def test_synthetic_dom_fires_on_setcontent_without_goto(self):
            self.write("tests/dom.spec.ts", FAKE_SYNTHETIC_DOM_SPEC)
            self.assertIn("test_synthetic_dom",
                          self.codes("tests/dom.spec.ts"))

        def test_synthetic_dom_fires_on_body_innerhtml(self):
            self.write("tests/inner.spec.ts", FAKE_INNER_HTML_SPEC)
            self.assertIn("test_synthetic_dom",
                          self.codes("tests/inner.spec.ts"))

        def test_synthetic_dom_does_not_fire_when_the_app_is_navigated(self):
            self.write("tests/both.spec.ts", REAL_GOTO_THEN_SETCONTENT_SPEC)
            self.assertNotIn("test_synthetic_dom",
                             self.codes("tests/both.spec.ts"))

        def test_synthetic_dom_fires_on_the_catch_fallback_shape(self):
            self.write("tests/fallback.spec.ts", FAKE_FALLBACK_SPEC)
            codes = self.codes("tests/fallback.spec.ts")
            self.assertEqual(codes, ["test_synthetic_dom"])

        def test_the_fallback_shape_cites_the_catch_block(self):
            path = self.write("tests/fallback.spec.ts", FAKE_FALLBACK_SPEC)
            rep = self.report("tests/fallback.spec.ts")
            problem = rep["files"][0]["problems"][0]
            text = path.read_text(encoding="utf-8")
            self.assertIn("setContent",
                          text.splitlines()[problem["line"] - 1])

        # -- waivers --------------------------------------------------------
        def test_a_waiver_turns_fail_into_allowed_and_exit_0(self):
            self.write("tests/dom.spec.ts", FAKE_SYNTHETIC_DOM_SPEC)
            rep = self.report("tests/dom.spec.ts",
                              waivers=[("tests/dom.spec.ts", "PLAN-9 template")])
            self.assertEqual(rep["result"], "ALLOWED")
            self.assertEqual(rep["files"][0]["verdict"], "ALLOWED")
            self.assertEqual(rep["files"][0]["waived_by"], "PLAN-9 template")

        def test_a_waiver_keeps_the_problems_listed(self):
            self.write("tests/dom.spec.ts", FAKE_SYNTHETIC_DOM_SPEC)
            rep = self.report("tests/dom.spec.ts",
                              waivers=[("tests/dom.spec.ts", "reason")])
            self.assertTrue(rep["files"][0]["problems"])

        def test_a_waiver_for_another_file_does_not_clear_this_one(self):
            self.write("tests/dom.spec.ts", FAKE_SYNTHETIC_DOM_SPEC)
            self.write("tests/other.spec.ts", REAL_E2E_SPEC)
            rep = self.report("tests/dom.spec.ts", "tests/other.spec.ts",
                              waivers=[("tests/other.spec.ts", "n/a")])
            self.assertEqual(rep["result"], "FAIL")

        def test_a_waiver_naming_an_unjudged_file_warns(self):
            self.write("tests/e2e.spec.ts", REAL_E2E_SPEC)
            rep = self.report("tests/e2e.spec.ts",
                              waivers=[("tests/ghost.spec.ts", "why")])
            self.assertTrue(rep["warnings"])

        def test_a_blank_reason_is_exit_2(self):
            self.write("tests/dom.spec.ts", FAKE_SYNTHETIC_DOM_SPEC)
            code, out = self.cli(["--repo", str(self.repo), "--changed-files",
                                  "tests/dom.spec.ts", "--allow",
                                  "tests/dom.spec.ts", "--reason", "   ",
                                  "--json"])
            self.assertEqual(code, 2)
            self.assertEqual(json.loads(out)["result"], "ERROR")

        def test_an_allow_without_a_reason_is_exit_2(self):
            self.write("tests/dom.spec.ts", FAKE_SYNTHETIC_DOM_SPEC)
            code, out = self.cli(["--repo", str(self.repo), "--changed-files",
                                  "tests/dom.spec.ts", "--allow",
                                  "tests/dom.spec.ts", "--json"])
            self.assertEqual(code, 2)
            self.assertIn("paired --reason", json.loads(out)["error"])

        # -- CLI, paths, exits ---------------------------------------------
        def test_cli_exit_0_on_a_real_spec(self):
            self.write("tests/e2e.spec.ts", REAL_E2E_SPEC)
            code, out = self.cli(["--repo", str(self.repo), "--changed-files",
                                  "tests/e2e.spec.ts", "--json"])
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(out)["result"], "PASS")

        def test_cli_exit_1_on_a_fake_spec(self):
            self.write("tests/dom.spec.ts", FAKE_SYNTHETIC_DOM_SPEC)
            code, out = self.cli(["--repo", str(self.repo), "--changed-files",
                                  "tests/dom.spec.ts", "--json"])
            self.assertEqual(code, 1)
            self.assertEqual(json.loads(out)["result"], "FAIL")

        def test_files_and_changed_files_are_the_same_flag(self):
            self.write("tests/dom.spec.ts", FAKE_SYNTHETIC_DOM_SPEC)
            a, _ = self.cli(["--repo", str(self.repo), "--files",
                             "tests/dom.spec.ts", "--json"])
            b, _ = self.cli(["--repo", str(self.repo), "--changed-files",
                             "tests/dom.spec.ts", "--json"])
            self.assertEqual((a, b), (1, 1))

        def test_a_windows_backslash_path_is_accepted(self):
            self.write("tests/dom.spec.ts", FAKE_SYNTHETIC_DOM_SPEC)
            code, out = self.cli(["--repo", str(self.repo), "--changed-files",
                                  "tests\\dom.spec.ts", "--json"])
            self.assertEqual(code, 1)
            self.assertEqual(json.loads(out)["files"][0]["file"],
                             "tests/dom.spec.ts")

        def test_a_windows_backslash_waiver_matches_a_forward_slash_file(self):
            self.write("tests/dom.spec.ts", FAKE_SYNTHETIC_DOM_SPEC)
            code, out = self.cli(["--repo", str(self.repo), "--changed-files",
                                  "tests/dom.spec.ts", "--allow",
                                  "tests\\dom.spec.ts", "--reason", "known",
                                  "--json"])
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(out)["result"], "ALLOWED")

        def test_an_absolute_path_is_accepted(self):
            p = self.write("tests/dom.spec.ts", FAKE_SYNTHETIC_DOM_SPEC)
            code, _ = self.cli(["--repo", str(self.repo), "--changed-files",
                                str(p), "--json"])
            self.assertEqual(code, 1)

        def test_a_missing_file_is_exit_2(self):
            code, out = self.cli(["--repo", str(self.repo), "--changed-files",
                                  "tests/nope.spec.ts", "--json"])
            self.assertEqual(code, 2)
            self.assertIn("file not found", json.loads(out)["error"])

        def test_a_missing_repo_flag_is_exit_2(self):
            code, out = self.cli(["--changed-files", "a.spec.ts", "--json"])
            self.assertEqual(code, 2)
            self.assertIn("--repo", json.loads(out)["error"])

        def test_no_files_is_exit_2(self):
            code, out = self.cli(["--repo", str(self.repo), "--json"])
            self.assertEqual(code, 2)
            self.assertIn("--changed-files", json.loads(out)["error"])

        def test_a_repo_without_a_src_root_is_exit_2(self):
            empty = Path(tempfile.mkdtemp()).resolve()
            try:
                (empty / "tests").mkdir()
                (empty / "tests" / "a.spec.ts").write_text(
                    REAL_E2E_SPEC, encoding="utf-8")
                code, out = self.cli(["--repo", str(empty), "--changed-files",
                                      "tests/a.spec.ts", "--json"])
                self.assertEqual(code, 2)
                self.assertIn("no src root", json.loads(out)["error"])
            finally:
                shutil.rmtree(str(empty), ignore_errors=True)

        def test_a_duplicate_path_is_judged_once(self):
            self.write("tests/e2e.spec.ts", REAL_E2E_SPEC)
            rep = self.report("tests/e2e.spec.ts", "tests/e2e.spec.ts")
            self.assertEqual(len(rep["files"]), 1)

        def test_a_utf8_bom_file_is_read(self):
            p = self.repo / "tests" / "bom.spec.ts"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(FAKE_SYNTHETIC_DOM_SPEC, encoding="utf-8-sig")
            self.assertIn("test_synthetic_dom",
                          self.codes("tests/bom.spec.ts"))

        def test_the_text_report_names_every_code_it_found(self):
            self.write("tests/dom.spec.ts", FAKE_SYNTHETIC_DOM_SPEC)
            code, out = self.cli(["--repo", str(self.repo), "--changed-files",
                                  "tests/dom.spec.ts"])
            self.assertEqual(code, 1)
            self.assertIn("test_synthetic_dom", out)

        def test_the_report_lists_every_declared_problem_code(self):
            self.assertEqual(sorted(PROBLEM_CODES), sorted(set(PROBLEM_CODES)))
            self.assertEqual(len(PROBLEM_CODES), 4)

        def test_a_mixed_set_fails_on_the_one_bad_file(self):
            self.write("tests/e2e.spec.ts", REAL_E2E_SPEC)
            self.write("tests/dom.spec.ts", FAKE_SYNTHETIC_DOM_SPEC)
            self.write("src/plain.ts", "export function alpha() { }")
            rep = self.report("tests/e2e.spec.ts", "tests/dom.spec.ts",
                              "src/plain.ts")
            self.assertEqual(rep["result"], "FAIL")
            self.assertEqual(self.codes_for(rep, "tests/e2e.spec.ts"), [])
            self.assertEqual(len(rep["ignored"]), 1)

        # -- ledger ---------------------------------------------------------
        def _records(self, ledger):
            return [json.loads(l) for l in
                    Path(ledger).read_text(encoding="utf-8").splitlines()
                    if l.strip()]

        def test_the_ledger_records_a_chained_pass(self):
            self.write("tests/e2e.spec.ts", REAL_E2E_SPEC)
            ledger = self.repo / ".docs" / "gates.jsonl"
            code, _ = self.cli(["--repo", str(self.repo), "--changed-files",
                                "tests/e2e.spec.ts", "--milestone", "M1",
                                "--ledger", str(ledger), "--json"])
            self.assertEqual(code, 0)
            rec = self._records(ledger)[-1]
            self.assertEqual(rec["gate"], "check_test_authenticity.py")
            self.assertEqual(rec["verdict"], "PASS")
            self.assertEqual(rec["milestone"], "M1")
            self.assertEqual(rec["prev"], "genesis")
            self.assertEqual(rec["self"], ledger_self_hash(rec))

        def test_the_ledger_chains_across_runs(self):
            self.write("tests/e2e.spec.ts", REAL_E2E_SPEC)
            self.write("tests/dom.spec.ts", FAKE_SYNTHETIC_DOM_SPEC)
            ledger = self.repo / ".docs" / "gates.jsonl"
            self.cli(["--repo", str(self.repo), "--changed-files",
                      "tests/e2e.spec.ts", "--ledger", str(ledger), "--json"])
            self.cli(["--repo", str(self.repo), "--changed-files",
                      "tests/dom.spec.ts", "--ledger", str(ledger), "--json"])
            lines = [l for l in Path(ledger).read_text(
                encoding="utf-8").splitlines() if l.strip()]
            self.assertEqual(len(lines), 2)
            self.assertEqual(json.loads(lines[1])["prev"],
                             ledger_line_hash(lines[0].encode("utf-8")))
            self.assertEqual(json.loads(lines[1])["verdict"], "FAIL")

        def test_the_ledger_records_a_usage_error(self):
            ledger = self.repo / ".docs" / "gates.jsonl"
            self.cli(["--repo", str(self.repo), "--ledger", str(ledger),
                      "--json"])
            self.assertEqual(self._records(ledger)[-1]["verdict"], "ERROR")

        def test_the_ledger_carries_the_problem_codes_and_failing_files(self):
            self.write("tests/dom.spec.ts", FAKE_SYNTHETIC_DOM_SPEC)
            ledger = self.repo / ".docs" / "gates.jsonl"
            self.cli(["--repo", str(self.repo), "--changed-files",
                      "tests/dom.spec.ts", "--ledger", str(ledger), "--json"])
            rec = self._records(ledger)[-1]
            self.assertIn("test_synthetic_dom", rec["problem_codes"])
            self.assertEqual(rec["failing_files"], ["tests/dom.spec.ts"])

        def test_the_ledger_carries_the_waiver_reason(self):
            self.write("tests/dom.spec.ts", FAKE_SYNTHETIC_DOM_SPEC)
            ledger = self.repo / ".docs" / "gates.jsonl"
            self.cli(["--repo", str(self.repo), "--changed-files",
                      "tests/dom.spec.ts", "--allow", "tests/dom.spec.ts",
                      "--reason", "PLAN-12 template snapshot", "--ledger",
                      str(ledger), "--json"])
            rec = self._records(ledger)[-1]
            self.assertEqual(rec["verdict"], "PASS")
            self.assertIn("PLAN-12 template snapshot",
                          json.dumps(rec["allow_reasons"]))

        def test_the_ledger_hashes_every_input_file(self):
            p = self.write("tests/e2e.spec.ts", REAL_E2E_SPEC)
            ledger = self.repo / ".docs" / "gates.jsonl"
            self.cli(["--repo", str(self.repo), "--changed-files",
                      "tests/e2e.spec.ts", "--ledger", str(ledger), "--json"])
            rec = self._records(ledger)[-1]
            self.assertEqual(list(rec["inputs"].values()),
                             [sha256_file(p)])

        # -- masking --------------------------------------------------------
        def test_masking_blanks_comments_and_keeps_offsets(self):
            text = "const a = 1; // page.goto('x')\nconst b = 2;\n"
            masked, _ = mask_source(text, "cfamily")
            self.assertEqual(len(masked), len(text))
            self.assertNotIn("goto", masked)
            self.assertEqual(masked.count("\n"), text.count("\n"))

        def test_masking_keeps_string_literal_values(self):
            text = "const p = '../../src/a.ts';\n"
            masked, literals = mask_source(text, "cfamily")
            self.assertNotIn("src", masked)
            self.assertIn("../../src/a.ts", [v for _, v in literals])

        def test_a_glob_with_no_slash_matches_a_basename(self):
            self.assertTrue(is_test_path("deep/nested/a.spec.ts",
                                         ["*.spec.ts"]))
            self.assertFalse(is_test_path("deep/nested/a.ts", ["*.spec.ts"]))

    suite = unittest.defaultTestLoader.loadTestsFromTestCase(
        TestAuthenticityTests)
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    return 0 if result.wasSuccessful() else 1


# ---------------------------------------------------------------------------
# Self-test fixtures. Synthetic by construction: they reproduce the SHAPES
# observed in a real Playwright suite, never that suite's code.
# ---------------------------------------------------------------------------
SRC_BACKUP_CARD = """\
import { Enums } from './helper/enums';

export default class BackupCard {
    getBackupItemStatus(backup: any): string {
        if (!backup) {
            return 'unknown';
        }
        if (backup.status === Enums.BackupStatus.Done) {
            return 'success';
        }
        return 'failed';
    }

    getVerificationDisplay(status: number): string {
        if (status === 1) { return 'ok'; }
        if (status === 2) { return 'warn'; }
        return 'none';
    }
}
"""

SRC_ENUMS = """\
export const Enums = {
    BackupStatus: { Done: 1, Failing: 2 },
    AlertType: { Slide: 'Slide' },
};
"""

SRC_POLICY_CLASS = """\
export class PolicyVisibility {
    isVisible(policy: any): boolean {
        if (!policy) { return false; }
        if (policy.hidden) { return false; }
        return true;
    }
}
"""

SRC_CSHARP_HANDLER = """\
namespace Api.Handlers
{
    public class OrderHandler
    {
        public string Classify(int total)
        {
            if (total > 100) { return "large"; }
            if (total > 10) { return "medium"; }
            return "small";
        }
    }
}
"""

SRC_PYTHON_RULES = """\
def classify_total(total):
    if total > 100:
        return "large"
    if total > 10:
        return "medium"
    return "small"
"""

# --- legitimate --------------------------------------------------------------
REAL_IMPORTING_SPEC = """\
import { test, expect } from '@playwright/test';
import BackupCard from '../src/backup-card';

test('classifies a done backup as success', () => {
    const card = new BackupCard();
    expect(card.getBackupItemStatus({ status: 1 })).toBe('success');
});
"""

REAL_E2E_SPEC = """\
import { test, expect } from '@playwright/test';

test('the dashboard renders the backup card', async ({ page }) => {
    await page.goto('http://localhost:5000/dashboard');
    await expect(page.locator('#backup-card')).toBeVisible();
});
"""

REAL_E2E_WITH_HELPERS = """\
import { test, expect } from '@playwright/test';

async function login(page: any, email: string, password: string) {
    await page.fill('#email', email);
    await page.fill('#password', password);
    await page.click('button[type=submit]');
    await page.waitForURL(/dashboard/);
}

async function getBackupItemStatus(page: any) {
    const el = page.locator('#backup-status');
    await el.waitFor();
    const text = await el.innerText();
    return text.trim();
}

test('a logged-in user sees the backup status', async ({ page }) => {
    await page.goto('http://localhost:5000/');
    await login(page, 'a@b.c', 'pw');
    expect(await getBackupItemStatus(page)).toBe('success');
});
"""

REAL_SHORT_HELPER_SPEC = """\
import { test, expect } from '@playwright/test';
import BackupCard from '../src/backup-card';

function getBackupItemStatus(v: any) {
    return String(v);
}

test('short helpers are fine', () => {
    expect(getBackupItemStatus(new BackupCard())).toBeTruthy();
});
"""

REAL_EVALUATE_SPEC = """\
import { test, expect } from '@playwright/test';

test('the page title is right', async ({ page }) => {
    await page.goto('http://localhost:5000/');
    const title = await page.evaluate(() => document.title);
    expect(title).toContain('Dashboard');
});
"""

REAL_ALIAS_SPEC = """\
import { test, expect } from '@playwright/test';
import { Enums } from '@/helper/enums';

test('the enum is the shipped one', () => {
    expect(Enums.BackupStatus.Done).toBe(1);
});
"""

REAL_REQUEST_SPEC = """\
import { test, expect } from '@playwright/test';

test('the orders endpoint answers', async ({ request }) => {
    const response = await request.get('http://localhost:5000/api/orders');
    expect(response.status()).toBe(200);
});
"""

REAL_E2E_TWO_PURE_HELPERS = """\
import { test, expect } from '@playwright/test';

function renderRow(row: any): string {
    const parts = [row.id, row.name];
    const joined = parts.join(' | ');
    return joined.trim();
}

function diffRows(before: any[], after: any[]): string[] {
    const out: string[] = [];
    for (const row of after) {
        if (!before.find((b) => b.id === row.id)) { out.push(row.id); }
    }
    return out;
}

test('the grid shows the new row', async ({ page }) => {
    await page.goto('http://localhost:5000/orders');
    const rows = await page.locator('tr').allInnerTexts();
    expect(renderRow({ id: '1', name: 'a' })).toContain('1');
    expect(diffRows([], [{ id: '1' }])).toEqual(['1']);
    expect(rows.length).toBeGreaterThan(0);
});
"""

REAL_FIXTURE_READ_SPEC = """\
import { test, expect } from '@playwright/test';
import * as fs from 'fs';
import * as path from 'path';
import BackupCard from '../src/backup-card';

const fixture = JSON.parse(fs.readFileSync(
    path.resolve(__dirname, './fixture.json'), 'utf-8'));

test('the fixture drives the shipped card', () => {
    const evaluator = new Function('x', 'return x;');
    expect(evaluator(new BackupCard())).toBeTruthy();
    expect(fixture).toBeDefined();
});
"""

REAL_EXECSYNC_SPEC = """\
import { test, expect } from '@playwright/test';
import { execSync } from 'child_process';

test('the api process is up', async ({ page }) => {
    const out = execSync('curl -s http://localhost:5000/health').toString();
    await page.goto('http://localhost:5000/health');
    expect(out).toContain('ok');
});
"""

REAL_GOTO_THEN_SETCONTENT_SPEC = """\
import { test, expect } from '@playwright/test';

test('a printable view renders', async ({ page }) => {
    await page.goto('http://localhost:5000/report');
    const html = await page.content();
    await page.setContent(html);
    await expect(page.locator('#report')).toBeVisible();
});
"""

REAL_CSHARP_TEST = """\
using Xunit;
using Api.Handlers;

public class OrderHandlerTests
{
    [Fact]
    public void ClassifiesALargeOrder()
    {
        var handler = new OrderHandler();
        Assert.Equal("large", handler.Classify(500));
    }
}
"""

REAL_PYTHON_TEST = """\
from pkg.rules import classify_total


def test_classifies_a_large_total():
    assert classify_total(500) == "large"
"""

# --- fake --------------------------------------------------------------------
FAKE_TAUTOLOGY_SPEC = """\
import { test, expect } from '@playwright/test';

export function getBackupItemStatus(backup: any): string {
    if (!backup) {
        return 'unknown';
    }
    if (backup.status === 1) {
        return 'success';
    }
    return 'failed';
}

test('classifies a done backup as success', () => {
    expect(getBackupItemStatus({ status: 1 })).toBe('success');
});
"""

FAKE_TRANSCRIBED_SPEC = """\
import { test, expect } from '@playwright/test';
import { Enums } from '../src/helper/enums';

// Helpers duplicating the pure card logic for hermetic verification
// (transcribed from backup-card.ts)
function getVerificationDisplay(status: number): string {
    if (status === 1) { return 'ok'; }
    if (status === 2) { return 'warn'; }
    return 'none';
}

test('the verification display maps statuses', () => {
    expect(getVerificationDisplay(1)).toBe('ok');
    expect(Enums.BackupStatus.Done).toBe(1);
});
"""

FAKE_EVALUATE_REIMPL_SPEC = """\
import { test, expect } from '@playwright/test';

test('the card computes a status', async ({ page }) => {
    const result = await page.evaluate(() => {
        function getBackupItemStatus(backup: any): string {
            if (!backup) { return 'unknown'; }
            if (backup.status === 1) { return 'success'; }
            return 'failed';
        }
        return getBackupItemStatus({ status: 1 });
    });
    expect(result).toBe('success');
});
"""

FAKE_TWO_DEFS_SPEC = """\
import { test, expect } from '@playwright/test';

function widenTheThing(input: any) {
    const parts = String(input).split(',');
    const trimmed = parts.map((p) => p.trim());
    return trimmed.filter(Boolean);
}

function narrowTheThing(input: any[]) {
    const seen = new Set();
    for (const item of input) { seen.add(item); }
    return Array.from(seen);
}

test('the things round-trip', () => {
    expect(narrowTheThing(widenTheThing('a,b,a'))).toEqual(['a', 'b']);
});
"""

FAKE_ONE_DEF_SPEC = """\
import { test, expect } from '@playwright/test';

test('a running app answers', async ({ page }) => {
    await page.goto('http://localhost:5000/');
    function normaliseOnlyHere(input: any) {
        const s = String(input).trim();
        const lower = s.toLowerCase();
        return lower.replace(/\\s+/g, '-');
    }
    expect(normaliseOnlyHere(' A B ')).toBe('a-b');
});
"""

FAKE_TINY_NAMED_HELPER_SPEC = """\
import { test, expect } from '@playwright/test';

function getBackupItemStatus(v: any) {
    return v.status === 1 ? 'success' : 'failed';
}

test('a two-statement helper is below the floor', async ({ page }) => {
    await page.goto('http://localhost:5000/');
    expect(getBackupItemStatus({ status: 1 })).toBe('success');
});
"""

FAKE_ARROW_REIMPL_SPEC = """\
import { test, expect } from '@playwright/test';

const getVerificationDisplay = (status: number): string => {
    if (status === 1) { return 'ok'; }
    if (status === 2) { return 'warn'; }
    return 'none';
};

test('the arrow copy agrees with itself', () => {
    expect(getVerificationDisplay(2)).toBe('warn');
});
"""

FAKE_CLASS_REIMPL_SPEC = """\
import { test, expect } from '@playwright/test';

class PolicyVisibility {
    isVisible(policy: any): boolean {
        if (!policy) { return false; }
        if (policy.hidden) { return false; }
        return true;
    }
}

test('the copied class agrees with itself', () => {
    expect(new PolicyVisibility().isVisible({})).toBe(true);
});
"""

FAKE_AWAITED_EVALUATE_SPEC = """\
import { test, expect } from '@playwright/test';

test('the awaited call is not a definition', async ({ page }) => {
    const result = await page.evaluate(async () => {
        const el = document.querySelector('#app');
        const text = el ? el.textContent : '';
        return String(text).trim();
    });
    await page.setContent('<div id="app">x</div>');
    expect(result).toBe('');
});
"""

FAKE_REPEATED_HELPER_SPEC = """\
import { test, expect } from '@playwright/test';

test('first', () => {
    function getVerificationDisplay(status: number): string {
        if (status === 1) { return 'ok'; }
        if (status === 2) { return 'warn'; }
        return 'none';
    }
    expect(getVerificationDisplay(1)).toBe('ok');
});

test('second', () => {
    function getVerificationDisplay(status: number): string {
        if (status === 1) { return 'ok'; }
        if (status === 2) { return 'warn'; }
        return 'none';
    }
    expect(getVerificationDisplay(2)).toBe('warn');
});
"""

FAKE_ONE_NAME_TWICE_SPEC = """\
import { test, expect } from '@playwright/test';

test('first', () => {
    function localOnlyThing(input: any) {
        const parts = String(input).split(',');
        const trimmed = parts.map((p) => p.trim());
        return trimmed.filter(Boolean);
    }
    expect(localOnlyThing('a,b')).toEqual(['a', 'b']);
});

test('second', () => {
    function localOnlyThing(input: any) {
        const parts = String(input).split(',');
        const trimmed = parts.map((p) => p.trim());
        return trimmed.filter(Boolean);
    }
    expect(localOnlyThing('a')).toEqual(['a']);
});
"""

FAKE_HERMETIC_ENUM_SPEC = """\
import { test, expect } from '@playwright/test';

test('the task type enumeration maps correctly', () => {
    const TaskType = { Install: 0, Restart: 1, Reinstall: 3 };
    expect(TaskType.Restart).toBe(1);
    expect(TaskType.Reinstall).toBe(3);
});
"""

FAKE_BARE_ONLY_SPEC = """\
import { test, expect } from '@playwright/test';
import * as dotenv from 'dotenv';
import * as path from 'path';

test('two plus two', () => {
    expect(2 + 2).toBe(4);
});
"""

FAKE_COMMENTED_GOTO_SPEC = """\
import { test, expect } from '@playwright/test';

test('the app was going to be navigated', async ({ page }) => {
    // await page.goto('http://localhost:5000/');
    expect(1).toBe(1);
});
"""

FAKE_SOURCE_EVAL_SPEC = """\
import { test, expect } from '@playwright/test';
import * as fs from 'fs';
import * as path from 'path';

const cardPath = path.resolve(__dirname, '../src/backup-card.ts');
const cardSource = fs.existsSync(cardPath)
    ? fs.readFileSync(cardPath, 'utf-8')
    : '';

test('the sliced expression still returns success', () => {
    const match = cardSource.match(/return 'success';/);
    const evaluator = new Function('backup', "return 'success';");
    expect(match).not.toBeNull();
    expect(evaluator({ status: 1 })).toBe('success');
});
"""

FAKE_TRANSPILE_SPEC = """\
import { test, expect } from '@playwright/test';
import * as fs from 'fs';
import * as path from 'path';
import * as ts from 'typescript';

const cardPath = path.resolve(__dirname, '../src/backup-card.ts');
const cardSource = fs.readFileSync(cardPath, 'utf-8');
const transpiled = ts.transpileModule(cardSource, { compilerOptions: {} });

test('the transpiled slice runs', () => {
    expect(transpiled.outputText.length).toBeGreaterThan(0);
});
"""

FAKE_STATIC_READ_SPEC = """\
import { test, expect } from '@playwright/test';
import * as fs from 'fs';
import * as path from 'path';

const cardPath = path.resolve(__dirname, '../src/backup-card.ts');
const cardSource = fs.readFileSync(cardPath, 'utf-8');

test('the guard is declared in the source text', () => {
    expect(/getBackupItemStatus/.test(cardSource)).toBe(true);
});
"""

FAKE_SYNTHETIC_DOM_SPEC = """\
import { test, expect } from '@playwright/test';

test('the backup card renders a warning banner', async ({ page }) => {
    await page.setContent('<div id="app"><div class="banner">warn</div></div>');
    await expect(page.locator('.banner')).toHaveText('warn');
});
"""

FAKE_INNER_HTML_SPEC = """\
import { test, expect } from '@playwright/test';

test('the banner appears', async ({ page }) => {
    await page.evaluate(() => {
        document.body.innerHTML = '<div class="banner">warn</div>';
    });
    await expect(page.locator('.banner')).toHaveText('warn');
});
"""

FAKE_FALLBACK_SPEC = """\
import { test, expect } from '@playwright/test';

test('the toast renders somewhere', async ({ page }) => {
    try {
        await page.goto('http://localhost:5000/', { timeout: 3000 });
    } catch (e) {
        await page.setContent('<div id="app"><div class="toast">x</div></div>');
    }
    await expect(page.locator('.toast')).toBeVisible();
});
"""

FAKE_CSHARP_TEST = """\
using Xunit;
using System.Collections.Generic;

public class FakeTests
{
    [Fact]
    public void ClassifiesALargeOrder()
    {
        var totals = new Dictionary<int, string> { { 500, "large" } };
        Assert.Equal("large", totals[500]);
    }
}
"""

FAKE_CSHARP_REIMPL = """\
using Xunit;
using System;

public class CopyTests
{
    private string Classify(int total)
    {
        if (total > 100) { return "large"; }
        if (total > 10) { return "medium"; }
        return "small";
    }

    [Fact]
    public void ClassifiesALargeOrder()
    {
        Assert.Equal("large", Classify(500));
    }
}
"""

FAKE_PYTHON_TEST = """\
def test_classifies_a_large_total():
    table = {500: "large", 50: "medium"}
    assert table[500] == "large"
"""

FAKE_PYTHON_REIMPL = """\
def classify_total(total):
    if total > 100:
        return "large"
    if total > 10:
        return "medium"
    return "small"


def test_classifies_a_large_total():
    assert classify_total(500) == "large"
"""

FAKE_PYTHON_SOURCE_EVAL = """\
import pathlib

source = pathlib.Path("src/pkg/rules.py").read_text(encoding="utf-8")
snippet = source.split("def classify_total")[1]
namespace = {}
exec("def classify_total(total):" + snippet.split(":", 1)[1], namespace)


def test_classifies_a_large_total():
    assert namespace["classify_total"](500) == "large"
"""


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
