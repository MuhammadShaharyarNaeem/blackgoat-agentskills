#!/usr/bin/env python3
"""Mechanical gate for observed-runtime evidence.

Converts the prose rule that an in-process observation can fail a wire
claim but never pass one (runtime-evidence/SKILL.md) into an artifact that
has to exist on disk. Reads a durable agent report, collects its
`**Runtime evidence:**` citations, and verifies each cited capture:

  * exists, resolved against the report's directory or --repo
  * is cited under an `evidence/runtime/` directory
  * carries a run_quiet.py provenance sidecar whose `capture_sha256` still
    matches the capture file's bytes and whose `exit_code` is 0 -- a
    hand-typed capture has no sidecar, an edited one fails the hash, and a
    probe whose client exited non-zero (connection refused, DNS failure)
    observed nothing regardless of what its body says
  * carries a sidecar that AGREES with the capture's own header: `exit_code`
    equals the body's `- Exit code:` and `finished` equals its `- Captured:`.
    The hash protects the capture FILE and nothing protects the sidecar, so
    editing the sidecar alone -- exit_code 3 -> 0, or `finished` pushed forward
    past a changed file to fake freshness -- left every other check green
    (`sidecar_body_disagrees`; a capture with no header pair at all is
    `capture_header_missing` and must be re-taken)
  * was taken by a real probe CLIENT (allowlist), not by `python -c`,
    `echo`, `printf` or `cat` printing a plausible transcript
  * names an OUT-OF-PROCESS transport (an in-process test client is a
    gate failure, not a shortcut -- this is the mechanical twin of the
    "real HTTP" comment that let a missing response envelope ship)
  * probes a runtime surface, not a compile/build/search command
  * postdates every --changed-files entry (freshness)
  * carries the required top-level response keys
  * does not name a forbidden (shared dev/staging) host
  * recorded a reachable contract surface (--require-openapi-reachable)
  * agrees with the contract surface's declared success shape at the top
    level (--openapi-doc / --openapi-route / --openapi-method)

Fenced code blocks (``` or ~~~) are MASKED before headers and citations are
read, so an example block in a report or in a capture's prose preamble
cannot gate. Every file is read as utf-8-sig, so a BOM cannot break parsing.

THIS GATE NEVER OPENS A SOCKET. Both OpenAPI features read what the probe
already recorded -- the `- OpenAPI:` header field, and a saved OpenAPI JSON
document on disk. They prove the probe REPORTED a reachable contract surface
and what that document said, never that either is true right now.

Pure standard library.

Usage:
    python check_runtime_evidence.py --report <path> --milestone "<title>" \
        --changed-files <p1> [<p2> ...] [--repo <dir>] \
        [--surface <key>] [--require-key <name>]... [--expect-status <N>] \
        [--forbid-host <pattern>]... [--require-build-marker <value>] \
        [--min-captures <N>] [--require-openapi-reachable] \
        [--allow-missing-sidecar] [--ledger <path>] \
        [--openapi-doc <path> --openapi-route <path> [--openapi-method <verb>]]
    python check_runtime_evidence.py --self-test
"""
import argparse
import datetime
import hashlib
import json
import os
import re
import sys
from pathlib import Path

READ_ENCODING = "utf-8-sig"   # a BOM must not break parsing anywhere here

CITATION_RE = re.compile(r"\*\*Runtime evidence:\*\*(.*)", re.IGNORECASE)
FIELD_RE = re.compile(r"^\s*-\s*([^:]{1,60}?):\s*(.*)$")
# Horizontal whitespace only, for the same reason FENCE_RE below uses it: a
# trailing `\s*$` is greedy ACROSS lines, so against fence-masked text (where
# the body is space-filled) it swallowed every blank line after the heading
# and the body came back empty.
CAPTURED_HEADING_RE = re.compile(
    r"(?im)^##[^\S\n]+Captured[^\S\n]+output[^\S\n]*$")
# Horizontal whitespace only ([^\S\n]), never \s: a `\s*` here consumes the
# newline after the opening fence and then matches the NEXT line, silently
# eating the first line of every captured body — which is exactly the HTTP
# status line --expect-status needs.
FENCE_RE = re.compile(r"(?m)^[^\S\n]*(`{3,})[^\n]*$")
STATUS_LINE_RE = re.compile(r"HTTP/\d(?:\.\d)?\s+(\d{3})")
PATH_SHAPE_RE = re.compile(r"^[A-Za-z0-9_./\\-]+$")
PATH_EXTENSION_RE = re.compile(r"\.[A-Za-z0-9]+$")

# --- contract surface (OpenAPI/Swagger) ------------------------------------
# WHY requiring the contract surface is worth a flag of its own: a probe can
# be aimed at anything that answers on a port -- a stub, a mock, a previous
# build, another service. Demanding that the SAME probe also recorded a
# reachable OpenAPI document forces it at a real host running a real API,
# and a reachable OpenAPI document is the exact instrument that falsified the
# 2026-08 response-envelope claim by hand: the envelope was green in unit and
# integration tests and absent from local Swagger. Swagger was the falsifier,
# so the gate makes producing it mandatory.
#
# It is still only a RECORD. This gate reads the header field the probe wrote;
# it makes no request. It proves the probe REPORTED a reachable contract
# surface at capture time, not that one exists now.
OPENAPI_URL_RE = re.compile(r"https?://[^\s,;`\"'<>]+")
# Searched only AFTER the URL is cut out of the string -- otherwise a port
# (`http://localhost:200/swagger.json`) reads as a 200 status.
OPENAPI_STATUS_RE = re.compile(r"(?<![\d.])([1-5]\d{2})(?![\d.])")

# One hop, and only into components/schemas. Anything else is unresolvable.
SCHEMA_REF_RE = re.compile(r"^#/components/schemas/([^/]+)$")
JSON_MEDIA_RE = re.compile(r"^application/(?:json|[A-Za-z0-9._+-]+\+json)$|/json$", re.I)
SUCCESS_STATUS_KEY_RE = re.compile(r"^2\d{2}$")
# Compositions this gate refuses to flatten. Guessing at JSON-Schema
# composition semantics is worse than reporting that we cannot tell.
UNFLATTENABLE_KEYWORDS = ("allOf", "oneOf", "anyOf", "not", "discriminator")

# Transports that never open a socket. A capture naming one of these was
# taken inside the process it claims to have observed from outside.
# BLOCKLIST -- therefore incomplete: a new framework's in-process client
# passes until its name is added here.
IN_PROCESS_TELLS = (
    "webapplicationfactory", "createclient(", "testserver", "testclient",
    "supertest", "mockmvc", "asgitransport", "rack-test", "httptestingcontroller",
    "inmemorytransport", "app.test_client(",
    # Honest self-descriptions of an in-process probe. A framework name is the
    # strong signal; these catch the author who describes the transport in prose
    # instead ("direct handler call", "in-process HTTP"). They do nothing against
    # someone who misdescribes the transport -- but nothing here does, and the
    # list is documented as a blocklist and therefore incomplete.
    "in-process", "in process", "direct handler", "handler directly",
    "direct invocation", "invoked directly", "same process",
)

# Commands that prove the code was written, never that it runs. Word-boundary
# regexes rather than substrings, so a base URL containing "org " does not read
# as `rg`. Test-RUNNER invocations are the load-bearing entries: `dotnet test`
# executes the in-process suite, which is precisely the tier this gate exists
# to stop standing in for an observation.
NON_RUNTIME_PROBE_RES = (
    re.compile(r"\b(?:dotnet|go|cargo|mvn|gradle)\s+(?:build|restore|compile)\b"),
    re.compile(r"\b(?:dotnet|go|cargo|mvn|gradle)\s+test\b"),
    # `node --test` is flag-shaped rather than subcommand-shaped, so it slipped
    # past every pattern here and a capture declaring it passed the gate with a
    # hand-written envelope body: the same escape this file exists to stop,
    # through a different hole. Found 2026-08-12 by the eval fixture.
    re.compile(r"\bnode\s+--test\b"),
    re.compile(r"\b(?:deno|bun|swift|rails|ctest)\s+test\b"),
    re.compile(r"\b(?:rspec|phpunit|vstest|testcafe|minitest)\b"),
    re.compile(r"\b(?:npm|pnpm)\s+(?:ci|test|run\s+(?:build|test))\b"),
    re.compile(r"\byarn\s+(?:build|test)\b"),
    re.compile(r"\b(?:pytest|jest|vitest|mocha|karma|nunit|xunit)\b"),
    re.compile(r"\btsc\b|--no-?emit\b|\bmsbuild\b"),
    re.compile(r"\b(?:grep|rg|ripgrep|findstr|ack)\b"),
    re.compile(r"\bmake\s+(?:build|all)\b"),
)

REQUIRED_FIELDS = ("milestone", "transport", "probe command", "captured", "exit code")

# --- provenance sidecar ----------------------------------------------------
# run_quiet.py writes `<capture>.meta.json` next to every --capture artifact.
# It is the only thing here that distinguishes an OBSERVED capture from a
# well-formed authored one: the tool records the child argv, the real exit
# code, and a hash of the finished capture file. The gate re-hashes the file
# and compares. Nothing in the capture's own prose is trusted for any of it.
SIDECAR_SUFFIX = ".meta.json"

# --- probe client allowlist ------------------------------------------------
# An ALLOWLIST, not a blocklist -- the deliberate inverse of IN_PROCESS_TELLS
# and NON_RUNTIME_PROBE_RES below (convention #8: this refines the same rule
# they serve, in the stricter direction, because the blocklist form let
# `python -c "print('HTTP/1.1 200 OK')"` produce a conforming capture). A
# client not on this list is not assumed hostile; it is assumed unproven, and
# the author says why with `[probe-exempt: <reason>]`.
PROBE_CLIENT_ALLOWLIST = frozenset({
    "curl", "wget", "http", "https", "httpie", "newman", "k6", "hey", "ab",
    "wrk", "invoke-webrequest", "invoke-restmethod", "iwr", "irm",
    "playwright", "npx", "psql", "sqlcmd", "redis-cli", "mongosh", "grpcurl",
    "websocat", "wscat", "nc", "ncat", "openssl", "ssh", "adb",
})
# `npx` is a launcher, not a client: it only counts when it launches one.
NPX_ALLOWED_TARGETS = ("playwright", "@playwright")
# Mirrors runtime-evidence's `[no inverse: <reason>]` idiom.
PROBE_EXEMPT_RE = re.compile(r"\[probe-exempt:\s*([^\]]*)\]", re.IGNORECASE)
ENV_ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
TIMEOUT_DURATION_RE = re.compile(r"^\d+(?:\.\d+)?[smhd]?$", re.IGNORECASE)
EXE_SUFFIX_RE = re.compile(r"\.(?:exe|cmd|bat|com|ps1)$", re.IGNORECASE)
PYTHON_EXES = ("python", "python3", "py", "pythonw")
FENCE_OPEN_RE = re.compile(r"^[^\S\n]*(`{3,}|~{3,})")


class GateError(Exception):
    """Structural/usage failure — maps to exit 2.

    `code` is the machine-readable cause, surfaced as `error_code` in the
    JSON so a caller does not have to string-match the prose.
    """

    def __init__(self, message, code=None):
        super().__init__(message)
        self.code = code


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

def read_text(path):
    p = Path(path)
    if not p.is_file():
        raise GateError(f"file not found or not readable: {path}")
    return p.read_text(encoding=READ_ENCODING, errors="replace")


def sha256_file(path):
    """sha256 over a file's raw bytes. None if it cannot be read."""
    try:
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def mask_fenced_blocks(text):
    """Blank out fenced code blocks, PRESERVING every character offset.

    Same length, same line structure, fenced content replaced by spaces.
    Offsets stay valid, so a heading found in the masked text can be sliced
    out of the original -- which is what lets the capture's `## Captured
    output` body survive while a fenced example above it does not.

    Why mask rather than trust: a report carrying an EXAMPLE capture citation
    or a documentation snippet inside ``` gated exactly like a real one, and
    a capture could ship a fenced sample header block ahead of its own.
    """
    out, lines = [], text.splitlines(keepends=True)
    fence = None          # the opening marker while inside a block
    for line in lines:
        stripped = line.rstrip("\r\n")
        newline = line[len(stripped):]
        m = FENCE_OPEN_RE.match(stripped)
        if fence is None:
            if m:
                fence = m.group(1)
                out.append(" " * len(stripped) + newline)
            else:
                out.append(line)
            continue
        # inside a block: it closes on a same-character run at least as long
        out.append(" " * len(stripped) + newline)
        if m and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence):
            fence = None
    return "".join(out)


def is_path_shaped(token):
    """A bare path-like token: allowed charset plus a dot-extension."""
    return bool(PATH_SHAPE_RE.match(token)) and bool(PATH_EXTENSION_RE.search(token))


def collect_citations(report_text):
    """Every path cited on a `**Runtime evidence:**` line, file-wide.

    Collection is file-wide and scoping happens capture-side (on each
    capture's own `- Milestone:` field), because `test-report.md`'s
    `#Task [N]:` headers are documented human-only -- inventing a machine
    header there would break Quinn's append-only format.

    Fenced blocks are masked first: a citation shown as an EXAMPLE inside
    ``` is documentation, not evidence, and must not gate.
    """
    out = []
    for line in mask_fenced_blocks(report_text).splitlines():
        m = CITATION_RE.search(line)
        if not m:
            continue
        for tok in re.split(r"[,\s]+", m.group(1).strip()):
            tok = tok.strip("`<>()[]")
            if tok and is_path_shaped(tok):
                out.append(tok)
    # de-duplicate, preserving first-seen order
    seen, unique = set(), []
    for c in out:
        if c not in seen:
            seen.add(c)
            unique.append(c)
    return unique


def cited_under(candidate, *segments):
    """True if the CITED string names `segments` as consecutive path parts.

    A containment scan, not a prefix anchor: a capture is normally cited
    relative to the report, but the same path may legitimately carry a
    `.docs/{project}/implementation/` prefix.

    Rejects any `..` segment. check_commit_gate.py's older prefix-anchored
    predicate normalizes with `lstrip("./")`, which strips ANY leading run
    of `.` and `/` characters -- so `../evidence/review/x.png` collapsed to
    a passing path. Repo-escaping citations are refused here.
    """
    normalized = candidate.replace("\\", "/")
    parts = [p for p in normalized.split("/") if p and p != "."]
    if ".." in parts:
        return False
    want = [s.lower() for s in segments]
    for i in range(len(parts) - len(want)):
        if [p.lower() for p in parts[i:i + len(want)]] == want:
            return True
    return False


def resolve_path(candidate, report_path, repo):
    """Resolve a cited path against the report's dir, then --repo, then as given."""
    for base in (Path(report_path).parent, Path(repo), Path(".")):
        p = base / candidate
        if p.is_file():
            return p
    p = Path(candidate)
    return p if p.is_file() else None


def milestone_tokens(milestone):
    """Full title plus its leading identifier (text before the first ':' / '—')."""
    tokens = [milestone.strip().lower()]
    short = re.split(r"[:—-]", milestone, maxsplit=1)[0].strip().lower()
    if len(short) >= 2 and short != tokens[0]:
        tokens.append(short)
    return tokens


def milestone_token_patterns(milestone):
    """Word-boundary regex per token, so `M1` never matches `M10`."""
    return [re.compile(rf"(?<![a-z0-9]){re.escape(t)}(?![a-z0-9])")
            for t in milestone_tokens(milestone)]


def matches_milestone(patterns, haystack):
    haystack_l = (haystack or "").lower()
    return any(p.search(haystack_l) for p in patterns)


def parse_capture(text):
    """Return (fields dict keyed lowercase, captured_output str or None).

    Header fields and the `## Captured output` heading are located in the
    FENCE-MASKED text, so a fenced example header block in the capture's
    prose preamble supplies neither a field nor a false heading. The body is
    then sliced out of the ORIGINAL text at the same offset -- masking
    preserves offsets precisely so the real captured output survives.
    """
    masked = mask_fenced_blocks(text)
    m = CAPTURED_HEADING_RE.search(masked)
    head = masked[:m.start()] if m else masked
    fields = {}
    for line in head.splitlines():
        fm = FIELD_RE.match(line)
        if fm:
            fields.setdefault(fm.group(1).strip().lower(), fm.group(2).strip())
    if not m:
        return fields, None
    body = text[m.end():]
    fence = FENCE_RE.search(body)
    if not fence:
        return fields, body.strip()
    marker = fence.group(1)
    rest = body[fence.end():]
    close = rest.find("\n" + marker)
    return fields, (rest[:close] if close != -1 else rest).strip("\n")


def newest_changed_mtime(changed_files):
    """(newest mtime or None, warnings) over the declared changed files.

    A path that does not exist is a STRUCTURAL error (exit 2), never a
    warning. It used to warn and skip -- which meant one typo'd or renamed
    path silently disabled the freshness check for the whole run and a stale
    capture sailed through with a green result. A gate that cannot perform
    its check must say so in its exit code, not in prose nobody reads.
    """
    newest = None
    for f in changed_files:
        p = Path(f)
        if not p.exists():
            raise GateError(
                f"declared changed file does not exist: {f} — freshness cannot "
                "be checked against a path that is not there, and silently "
                "skipping it is how a stale capture passes",
                code="changed_file_missing")
        mt = p.stat().st_mtime
        newest = mt if newest is None else max(newest, mt)
    return newest, []


def extract_body_json(captured):
    """Parse the LAST balanced JSON object in the captured output.

    Last, not first: a probe's output routinely carries a status line and
    headers before the body, and run_quiet merges stderr into the stream.
    """
    if not captured:
        return None, "no captured output"
    depth, start, best = 0, None, None
    in_str, esc = False, False
    for i, ch in enumerate(captured):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            if depth:
                depth -= 1
                if depth == 0 and start is not None:
                    best = captured[start:i + 1]
    if best is None:
        return None, "no JSON object found in captured output"
    try:
        return json.loads(best), None
    except json.JSONDecodeError as exc:
        return None, f"captured body is not valid JSON: {exc}"


def key_scopes(doc):
    """Scopes a --require-key may be satisfied in: the document, and its `body`.

    Deliberately NOT recursive. A key named `isSuccess` buried inside a
    payload must never pass an envelope check.
    """
    scopes = []
    if isinstance(doc, dict):
        scopes.append(doc)
        if isinstance(doc.get("body"), dict):
            scopes.append(doc["body"])
    return scopes


# ---------------------------------------------------------------------------
# Provenance: the run_quiet.py sidecar
# ---------------------------------------------------------------------------

def sidecar_path_for(capture_path):
    return Path(str(capture_path) + SIDECAR_SUFFIX)


def load_sidecar(path):
    """(meta dict or None, reason-when-None). Malformed reads as absent."""
    p = Path(path)
    if not p.is_file():
        return None, "no sidecar file"
    try:
        meta = json.loads(p.read_text(encoding=READ_ENCODING, errors="replace"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"sidecar is unreadable or not valid JSON: {exc}"
    if not isinstance(meta, dict):
        return None, "sidecar is not a JSON object"
    return meta, None


# --- body-vs-sidecar agreement ---------------------------------------------
# `capture_sha256` protects the capture FILE's bytes; NOTHING protects the
# sidecar's own fields. So the hash-checked body is the witness and the sidecar
# is the claim under test. Flipping a sidecar's `exit_code` from 3 to 0, or
# pushing its `finished` forward to defeat the freshness check below, leaves
# every hash intact -- and did, until this comparison existed: a GREEN whose
# own body read `- Exit code: 3` passed.
#
# `- Captured:` is compared against `finished`, which is what run_quiet.py now
# stamps it FROM. The window is one-sided (never EARLIER than `finished`) and
# two seconds wide, solely so a capture written by the pre-2.4 build path --
# which called `now()` again while rendering, landing 0-1s after `finished` --
# is not accused of forgery. A stamp moved to fake freshness or backdate a run
# moves it far outside the window. Duplicated in the three sibling gates that
# read a sidecar, per this family's one-file convention.
CAPTURED_SKEW_SECONDS = 2
SIDECAR_TIMESTAMP_FMT = "%Y-%m-%dT%H:%M:%SZ"


def parse_utc_stamp(raw):
    """A `%Y-%m-%dT%H:%M:%SZ` string as a naive UTC datetime, or None."""
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        return datetime.datetime.strptime(raw.strip(), SIDECAR_TIMESTAMP_FMT)
    except ValueError:
        return None


def sidecar_body_disagreement(fields, meta):
    """(problem-code, detail) when the capture's header and sidecar disagree.

    `fields` is parse_capture()'s header dict (read from the FENCE-MASKED head,
    so a probe that printed `- Exit code: 0` supplied nothing). Returns
    (None, None) when they agree.
    """
    body_exit = (fields.get("exit code") or "").strip()
    body_stamp = (fields.get("captured") or "").strip()
    if not body_exit or not body_stamp:
        return ("capture_header_missing",
                "the capture carries no readable '- Exit code:' and "
                "'- Captured:' header pair, so the sidecar's exit_code and "
                "finished stamp cannot be checked against anything -- a "
                "capture predating run_quiet.py's header contract must be "
                "re-taken with `run_quiet.py --capture`")
    try:
        body_exit_n = int(body_exit.split()[0])
    except (ValueError, IndexError):
        return ("capture_header_missing",
                f"the capture's '- Exit code: {body_exit}' is not an integer, "
                "so the sidecar's exit_code cannot be checked against it")
    side_exit = meta.get("exit_code")
    if isinstance(side_exit, int) and side_exit != body_exit_n:
        return ("sidecar_body_disagrees",
                f"the sidecar records exit_code {side_exit} but the capture's "
                f"own hash-protected body records '- Exit code: {body_exit_n}' "
                "-- the sidecar was edited after the run (the capture file's "
                "hash still matches, because only the sidecar was touched)")
    body_dt = parse_utc_stamp(body_stamp)
    side_dt = parse_utc_stamp(meta.get("finished"))
    if body_dt is None:
        return ("capture_header_missing",
                f"the capture's '- Captured: {body_stamp}' is not an ISO-8601 "
                f"UTC instant ({SIDECAR_TIMESTAMP_FMT})")
    if side_dt is None:
        return ("sidecar_body_disagrees",
                "the sidecar records no parseable 'finished' instant to check "
                f"against the capture's '- Captured: {body_stamp}'")
    skew = (body_dt - side_dt).total_seconds()
    if not 0 <= skew <= CAPTURED_SKEW_SECONDS:
        return ("sidecar_body_disagrees",
                f"the sidecar records finished {meta.get('finished')!r} but the "
                f"capture's own hash-protected body records '- Captured: "
                f"{body_stamp}' ({skew:+.0f}s apart; allowed 0.."
                f"{CAPTURED_SKEW_SECONDS}s) -- run_quiet.py stamps "
                "'- Captured:' FROM 'finished', so a pair this far apart was "
                "not written by it: either the sidecar's timestamp was edited "
                "(a stale capture made to look fresh) or the capture was "
                "authored by hand")
    return None, None


# ---------------------------------------------------------------------------
# Provenance: was the probe taken by a real client?
# ---------------------------------------------------------------------------

def exe_basename(token):
    """Normalize an executable token to a bare lowercase name."""
    t = token.strip().strip("`\"'")
    t = t.replace("\\", "/").rsplit("/", 1)[-1]
    return EXE_SUFFIX_RE.sub("", t).lower()


def probe_exempt_reason(raw):
    """The `[probe-exempt: <reason>]` escape hatch, or None."""
    m = PROBE_EXEMPT_RE.search(raw or "")
    if not m:
        return None
    return m.group(1).strip() or "(no reason given)"


SPACED_PATH_START_RE = re.compile(r"^(?:[A-Za-z]:[\\/]|[\\/]{1,2}|\.{1,2}[\\/])")


def merge_spaced_exe_path(toks, i):
    """Re-join an UNQUOTED executable path that contains spaces.

    `C:\\Program Files\\Git\\mingw64\\bin\\curl.EXE -sS http://...` splits on
    whitespace into a client called "program", which the allowlist rejects --
    silently, on every Windows box where curl lives under Program Files. Only
    a token that LOOKS like a path start is considered, and tokens are joined
    only up to the first join that names an executable (an `.exe`-style suffix
    or an allowlisted client basename); a path whose first token already names
    one is left alone. A join that names a non-client (`node.exe`) is still
    merged, so it is then rejected for the right reason rather than as
    "program".
    """
    if i >= len(toks) or not SPACED_PATH_START_RE.match(toks[i]):
        return toks

    def names_exe(s):
        return bool(EXE_SUFFIX_RE.search(s)) or exe_basename(s) in PROBE_CLIENT_ALLOWLIST

    if names_exe(toks[i]):
        return toks
    for k in range(2, min(len(toks) - i, 6) + 1):
        joined = " ".join(toks[i:i + k])
        if names_exe(joined):
            return toks[:i] + [joined] + toks[i + k:]
    return toks


def probe_client(raw):
    """(client basename or None, trailing tokens) for a `Probe command:` value.

    Peels the wrappers that legitimately precede a client -- leading
    `NAME=value` env assignments, `timeout <duration>`, and a
    `python … run_quiet.py … --` prefix -- then reports the first real
    executable. `python -c` is NOT peeled: python is the client there, and
    it is not on the allowlist, which is the whole point.
    """
    text = PROBE_EXEMPT_RE.sub(" ", raw or "").strip().strip("`").strip()
    toks = text.split()
    i = 0
    while i < len(toks):
        toks = merge_spaced_exe_path(toks, i)
        tok = toks[i]
        if ENV_ASSIGN_RE.match(tok):
            i += 1
            continue
        base = exe_basename(tok)
        if base == "timeout":
            i += 1
            while i < len(toks) and toks[i].startswith("-"):
                i += 1
            if i < len(toks) and TIMEOUT_DURATION_RE.match(toks[i]):
                i += 1
            continue
        if base in PYTHON_EXES and "--" in toks[i:]:
            sep = toks.index("--", i)
            if any("run_quiet.py" in t.lower() for t in toks[i:sep]):
                i = sep + 1
                continue
        return base, toks[i + 1:]
    return None, []


def probe_client_problem(raw):
    """None if the probe names an allowed client; else the prose cause."""
    client, rest = probe_client(raw)
    if client is None:
        return "probe command names no executable"
    if client not in PROBE_CLIENT_ALLOWLIST:
        return (f"probe client {client!r} is not a runtime probe client — a "
                "capture is only an observation if a real client made the "
                "request; a general-purpose interpreter or a text command can "
                "print a plausible transcript without touching the system")
    if client == "npx":
        target = next((t for t in rest if not t.startswith("-")), "")
        if not target.lower().startswith(NPX_ALLOWED_TARGETS):
            return ("'npx' is a launcher, not a client — it counts only when it "
                    f"launches playwright, and here it launches {target or 'nothing'!r}")
    return None


# ---------------------------------------------------------------------------
# Contract surface: the recorded `- OpenAPI:` field
# ---------------------------------------------------------------------------

def parse_openapi_field(raw):
    """(url, status, error) from a recorded `- OpenAPI: <url> - <status>` field.

    NO NETWORK. This reads what the probe wrote down.
    """
    if not raw or not raw.strip():
        return None, None, ("--require-openapi-reachable set but the capture "
                            "records no 'OpenAPI' field — the probe never showed "
                            "that a contract surface was reachable")
    m = OPENAPI_URL_RE.search(raw)
    url = m.group(0).rstrip("`.,;)]") if m else None
    # Cut the URL out before hunting for the status, or its port becomes one.
    remainder = (raw[:m.start()] + " " + raw[m.end():]) if m else raw
    sm = OPENAPI_STATUS_RE.search(remainder)
    status = int(sm.group(1)) if sm else None

    if url is None:
        return None, status, (f"'OpenAPI' field {raw.strip()!r} names no http(s) "
                              "URL — it does not identify a contract surface")
    if status is None:
        return url, None, (f"'OpenAPI' field {raw.strip()!r} records no HTTP "
                           "status for the contract surface — reachability was "
                           "never observed")
    if not 200 <= status < 300:
        return url, status, (f"contract surface {url} recorded status {status} — "
                             "a non-2xx OpenAPI document is not a reachable "
                             "contract surface; the probe may have been aimed at "
                             "something that merely answers on a port")
    return url, status, None


# ---------------------------------------------------------------------------
# Contract surface: declared-vs-observed schema diff (saved document, no network)
# ---------------------------------------------------------------------------

def load_openapi_doc(path):
    """Load a SAVED OpenAPI JSON document from disk. NO NETWORK.

    JSON only -- stdlib has no YAML parser and this family takes no
    third-party dependency. A YAML document is a usage error, not a warning:
    the caller must save the JSON form the probe already fetched.
    """
    text = read_text(path)
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as exc:
        raise GateError(
            f"--openapi-doc {path} is not valid JSON: {exc} — save the JSON form "
            "of the document (this gate has no YAML parser and takes no "
            "third-party dependency)")
    if not isinstance(doc, dict):
        raise GateError(f"--openapi-doc {path} is not a JSON object")
    return doc


def find_route(paths, route):
    """Exact match, then with/without a leading slash. Returns (key, obj)."""
    stripped = route.lstrip("/")
    for candidate in (route, "/" + stripped, stripped):
        if candidate in paths and isinstance(paths[candidate], dict):
            return candidate, paths[candidate]
    return None, None


def pick_success_response(responses):
    """Lowest declared 2xx key, then the `2XX` range form. (key, obj) or (None, None)."""
    numeric = sorted(k for k in responses if SUCCESS_STATUS_KEY_RE.match(str(k)))
    for key in numeric:
        if isinstance(responses[key], dict):
            return key, responses[key]
    for key in responses:
        if str(key).lower() == "2xx" and isinstance(responses[key], dict):
            return key, responses[key]
    return None, None


def declared_success_schema(doc, route, method):
    """(schema dict or None, reason-when-None) for the declared 2xx response.

    Every miss is a REASON, never a failure: a gate that cannot find the route
    knows nothing about the response, and reporting "cannot tell" beats both
    a vacuous pass and a false failure.
    """
    paths = doc.get("paths")
    if not isinstance(paths, dict):
        return None, "the document declares no 'paths' object"
    route_key, operations = find_route(paths, route)
    if operations is None:
        return None, f"route {route!r} is not declared in the document"
    operation = operations.get(method)
    if not isinstance(operation, dict):
        return None, (f"method {method.upper()} is not declared for route "
                      f"{route_key!r} in the document")
    responses = operation.get("responses")
    if not isinstance(responses, dict):
        return None, (f"{method.upper()} {route_key} declares no 'responses' object")
    status_key, response = pick_success_response(responses)
    if response is None:
        return None, (f"{method.upper()} {route_key} declares no success (2xx) "
                      "response — there is no declared success shape to compare")
    content = response.get("content")
    if isinstance(content, dict):
        for media in sorted(content):
            if JSON_MEDIA_RE.search(media) and isinstance(content[media], dict):
                schema = content[media].get("schema")
                if isinstance(schema, dict):
                    return schema, None
                return None, (f"success response {status_key} media type {media} "
                              "declares no schema")
        return None, (f"success response {status_key} declares no JSON media type")
    # Swagger 2.0 shape: the schema hangs directly off the response.
    schema = response.get("schema")
    if isinstance(schema, dict):
        return schema, None
    return None, f"success response {status_key} declares no schema"


def resolve_declared_properties(doc, schema):
    """(sorted top-level property names or None, reason-when-None).

    Resolution rule, deliberately minimal:
      * ONE `$ref` hop, and only into `#/components/schemas/<name>`.
      * A second-level `$ref` inside the resolved object is UNRESOLVABLE.
      * `allOf` / `oneOf` / `anyOf` / `not` / `discriminator` is UNRESOLVABLE.
      * A non-object (or multi-typed) schema has no top-level property names.
      * An absent or empty `properties` object is UNRESOLVABLE, not an empty
        declared set -- an empty set makes every comparison vacuously pass.

    Unresolvable is a WARNING at the call site: never a pass, never a fail.
    A partial resolver that silently gets composition wrong is worse than one
    that says it cannot tell.
    """
    ref = schema.get("$ref")
    if ref is not None:
        if not isinstance(ref, str):
            return None, "'$ref' is not a string — unresolvable"
        m = SCHEMA_REF_RE.match(ref.strip())
        if not m:
            return None, (f"'$ref' {ref!r} does not point at "
                          "'#/components/schemas/<name>' — one hop only, "
                          "unresolvable")
        name = m.group(1)
        components = doc.get("components")
        schemas = components.get("schemas") if isinstance(components, dict) else None
        target = schemas.get(name) if isinstance(schemas, dict) else None
        if not isinstance(target, dict):
            return None, (f"'$ref' target 'components/schemas/{name}' is absent "
                          "from the document — unresolvable")
        if "$ref" in target:
            return None, (f"'components/schemas/{name}' contains a second-level "
                          "'$ref' — one hop only, unresolvable")
        schema = target
    for keyword in UNFLATTENABLE_KEYWORDS:
        if keyword in schema:
            return None, (f"schema uses {keyword!r} composition — not trivially "
                          "flattenable, unresolvable (this gate does not guess at "
                          "JSON-Schema composition semantics)")
    declared_type = schema.get("type")
    if isinstance(declared_type, list):
        return None, "schema declares multiple types — unresolvable"
    if declared_type is not None and declared_type != "object":
        return None, (f"schema type {declared_type!r} has no top-level property "
                      "names to compare (only 'object' does)")
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return None, "schema declares no 'properties' object — unresolvable"
    if not properties:
        return None, ("schema declares an empty 'properties' object — an empty "
                      "declared set would pass vacuously, so this is unresolvable")
    return sorted(properties.keys()), None


def diff_declared_observed(declared, body_doc):
    """(scope_label, declared_absent, observed_undeclared) — TOP-LEVEL NAMES ONLY.

    No nesting, no types, no required/optional logic. Scope selection mirrors
    --require-key: the document itself or its `body` object, whichever leaves
    fewer declared properties absent.
    """
    scopes = key_scopes(body_doc)
    best = None
    for label, scope in zip(("document", "body"), scopes):
        observed = set(scope.keys())
        absent = sorted(set(declared) - observed)
        if best is None or len(absent) < len(best[1]):
            best = (label, absent, sorted(observed - set(declared)))
    return best if best else ("document", sorted(declared), [])


# ---------------------------------------------------------------------------
# Per-capture evaluation
# ---------------------------------------------------------------------------

def evaluate_capture(candidate, args, patterns, newest_mtime, schema_ctx=None):
    """Return a per-capture result dict. `problems` empty => accepted."""
    schema_ctx = schema_ctx or {"active": False, "declared": None, "reason": None}
    res = {
        "path": candidate, "exists": False, "cited_under_evidence_runtime": False,
        "milestone_match": False, "fresh": None, "surface": None,
        "transport": None, "probe_command": None, "status": None,
        "body_parsed": False, "body_keys": [], "missing_keys": [],
        "build_marker": None,
        "sidecar": None, "sidecar_present": None, "sidecar_exit_code": None,
        "sidecar_capture_sha256_ok": None, "sidecar_body_agrees": None,
        "sidecar_waived": False,
        "probe_client": None, "probe_exempt_reason": None,
        "openapi_url": None, "openapi_status": None, "openapi_reachable": None,
        "schema_compared": None, "schema_skipped_reason": None,
        "observed_scope": None, "declared_absent": [], "observed_undeclared": [],
        "problems": [], "problem_codes": [],
    }

    def fail(code, message):
        """A problem carrying a machine-readable code, `code: prose`."""
        res["problems"].append(f"{code}: {message}")
        res["problem_codes"].append(code)

    res["cited_under_evidence_runtime"] = cited_under(candidate, "evidence", "runtime")
    if not res["cited_under_evidence_runtime"]:
        res["problems"].append(
            "not cited under an 'evidence/runtime/' directory (a '..' segment is "
            "also refused); builder captures under evidence/build/ do not gate")

    resolved = resolve_path(candidate, args.report, args.repo)
    if resolved is None:
        res["problems"].append("cited capture file does not exist")
        return res
    res["exists"] = True

    text = resolved.read_text(encoding=READ_ENCODING, errors="replace")
    fields, captured = parse_capture(text)
    if captured is None:
        raise GateError(
            f"cited capture {candidate} has no '## Captured output' section — "
            "structurally not a capture artifact")

    res["milestone_match"] = matches_milestone(patterns, fields.get("milestone", ""))
    if not res["milestone_match"]:
        # Not this milestone's capture — caller filters it out, not a problem.
        res["problems"].append("capture's Milestone field does not name this milestone")
        return res

    for required in REQUIRED_FIELDS:
        if not fields.get(required):
            res["problems"].append(f"capture is missing the '{required}' field")

    res["surface"] = fields.get("surface")
    res["transport"] = fields.get("transport")
    res["probe_command"] = fields.get("probe command")
    res["build_marker"] = fields.get("build marker")

    # --- provenance: the run_quiet.py sidecar ---
    # Everything else in this file reads the capture's own prose, which an
    # author writes. These three read a machine-written file and re-hash the
    # artifact, so a hand-typed capture, a later edit of a real one, and a
    # probe that never connected are each detectable without believing a word.
    side_path = sidecar_path_for(resolved)
    res["sidecar"] = str(side_path)
    meta, side_error = load_sidecar(side_path)
    res["sidecar_present"] = meta is not None
    if meta is None:
        if args.allow_missing_sidecar:
            res["sidecar_waived"] = True
        else:
            fail("sidecar_missing",
                 f"{side_error} at {side_path.name} — a capture with no "
                 "run_quiet.py provenance sidecar is indistinguishable from a "
                 "hand-typed one; re-take the probe with "
                 "`run_quiet.py --capture`, or pass --allow-missing-sidecar "
                 "if this is a legacy capture and say so in the report")
    else:
        declared_hash = meta.get("capture_sha256")
        actual_hash = sha256_file(resolved)
        res["sidecar_capture_sha256_ok"] = bool(
            declared_hash and actual_hash and declared_hash == actual_hash)
        if not res["sidecar_capture_sha256_ok"]:
            fail("sidecar_hash_mismatch",
                 f"the capture file's sha256 ({actual_hash}) does not match the "
                 f"sidecar's capture_sha256 ({declared_hash}) — the artifact was "
                 "edited after it was recorded, so its contents are authored, "
                 "not observed")
        # The sidecar's own fields are unprotected; the capture's body is not.
        # Compare them BEFORE trusting either exit_code or freshness below.
        code, detail = sidecar_body_disagreement(fields, meta)
        res["sidecar_body_agrees"] = code is None
        if code:
            fail(code, detail)
        exit_code = meta.get("exit_code")
        res["sidecar_exit_code"] = exit_code if isinstance(exit_code, int) else None
        if not isinstance(exit_code, int):
            fail("probe_failed_exit",
                 "the sidecar records no integer exit_code — the probe's outcome "
                 "was never observed")
        elif exit_code != 0:
            fail("probe_failed_exit",
                 f"the probe client exited {exit_code} — a probe whose client "
                 "failed (connection refused, DNS failure, timeout) observed "
                 "nothing, no matter what its captured body says")

    # --- provenance: was this taken by a real client? ---
    res["probe_exempt_reason"] = probe_exempt_reason(res["probe_command"])
    res["probe_client"] = probe_client(res["probe_command"])[0]
    if res["probe_exempt_reason"] is None:
        client_problem = probe_client_problem(res["probe_command"])
        if client_problem:
            fail("probe_not_client",
                 client_problem + " — if this really is a probe, declare it with "
                 "`[probe-exempt: <reason>]` on the Probe command line")

    haystack = f"{res['transport'] or ''} {res['probe_command'] or ''}".lower()
    for tell in IN_PROCESS_TELLS:
        if tell in haystack:
            res["problems"].append(
                f"declares an IN-PROCESS transport ({tell!r}) — an in-process "
                "observation can fail a wire claim but never pass one")
            break
    for pattern in NON_RUNTIME_PROBE_RES:
        m = pattern.search(haystack)
        if m:
            res["problems"].append(
                f"probe is a build/test-runner/search command ({m.group(0)!r}), not a "
                "runtime probe — it proves the code was written or that a suite is "
                "green, never that the running system emits this")
            break

    if args.surface and res["surface"] and args.surface.lower() != res["surface"].lower():
        res["problems"].append(
            f"surface {res['surface']!r} does not match the required {args.surface!r}")

    # Forbidden hosts: a capture taken against shared dev/staging proves
    # nothing about local. Scanned across the location-bearing fields.
    location = " ".join(filter(None, (
        fields.get("base url"), fields.get("environment"),
        fields.get("device"), fields.get("openapi"))))
    for pattern in args.forbid_host:
        if pattern.lower() in location.lower():
            res["problems"].append(
                f"names forbidden host {pattern!r} — this capture did not "
                "observe the local environment")

    if args.require_build_marker:
        if not res["build_marker"]:
            res["problems"].append(
                "--require-build-marker set but the capture records no 'Build marker'")
        elif args.require_build_marker not in res["build_marker"]:
            res["problems"].append(
                f"build marker {res['build_marker']!r} does not contain the "
                f"expected {args.require_build_marker!r} — the process that "
                "answered may not be running the built code")

    # Contract surface reachability, read from the record. NEVER a request.
    res["openapi_url"], res["openapi_status"], openapi_error = parse_openapi_field(
        fields.get("openapi"))
    if fields.get("openapi"):
        res["openapi_reachable"] = openapi_error is None
    if args.require_openapi_reachable and openapi_error:
        res["openapi_reachable"] = False
        res["problems"].append(
            "contract surface not proven reachable: " + openapi_error
            + " (this gate reads the recorded field; it makes no request)")

    if not captured.strip():
        res["problems"].append("captured output is empty")

    status_m = STATUS_LINE_RE.search(captured)
    observed_status = int(status_m.group(1)) if status_m else None

    if args.expect_status is not None:
        res["status"] = observed_status
        if res["status"] is None:
            res["problems"].append(
                f"--expect-status {args.expect_status} set but no HTTP status "
                "line found in the captured output")
        elif res["status"] != args.expect_status:
            res["problems"].append(
                f"observed status {res['status']} != expected {args.expect_status}")

    body_doc, body_error = None, None
    if args.require_key or schema_ctx["active"]:
        body_doc, body_error = extract_body_json(captured)
        if body_error is None:
            res["body_parsed"] = True
            scopes = key_scopes(body_doc)
            res["body_keys"] = sorted(scopes[0].keys()) if scopes else []

    if args.require_key:
        if body_error:
            res["problems"].append(body_error)
        else:
            scopes = key_scopes(body_doc)
            missing = None
            for scope in scopes:
                gaps = [k for k in args.require_key if k not in scope]
                if not gaps:
                    missing = []
                    break
                if missing is None or len(gaps) < len(missing):
                    missing = gaps
            res["missing_keys"] = missing or []
            if res["missing_keys"]:
                res["problems"].append(
                    "required response keys absent from the captured body: "
                    + ", ".join(res["missing_keys"]))

    if schema_ctx["active"]:
        if schema_ctx["declared"] is None:
            # Unresolvable / absent declaration: WARNING at the report level.
            # Never a pass and never a fail -- see resolve_declared_properties.
            res["schema_compared"] = False
            res["schema_skipped_reason"] = (
                "declared success schema not resolved: " + (schema_ctx["reason"] or ""))
        elif observed_status is not None and not 200 <= observed_status < 300:
            res["schema_compared"] = False
            res["schema_skipped_reason"] = (
                f"capture observed HTTP {observed_status}; the declared 2xx "
                "response schema does not describe a non-success body")
        elif body_error:
            res["schema_compared"] = False
            res["schema_skipped_reason"] = (
                body_error + " — cannot compare against the declared schema")
        else:
            label, absent, undeclared = diff_declared_observed(
                schema_ctx["declared"], body_doc)
            res["schema_compared"] = True
            res["observed_scope"] = label
            res["declared_absent"] = absent
            res["observed_undeclared"] = undeclared
            if absent:
                res["problems"].append(
                    "declared-but-absent response properties — the contract "
                    "surface promises them and the runtime did not send them: "
                    + ", ".join(absent))

    if newest_mtime is not None:
        res["fresh"] = resolved.stat().st_mtime >= newest_mtime
        if not res["fresh"]:
            res["problems"].append(
                "capture predates the newest declared changed file — it observed "
                "the system before this change (mtime proxy)")

    return res


# ---------------------------------------------------------------------------
# Report assembly
# ---------------------------------------------------------------------------

def validate_openapi_args(args):
    """Flag combinations that are usage errors, not evidence failures."""
    if args.openapi_doc and not args.openapi_route:
        raise GateError("--openapi-doc requires --openapi-route (the gate will not "
                        "guess which declared operation to compare against)")
    if args.openapi_route and not args.openapi_doc:
        raise GateError("--openapi-route requires --openapi-doc (a saved OpenAPI "
                        "JSON document; this gate makes no request)")
    if args.openapi_method and not args.openapi_doc:
        raise GateError("--openapi-method is only meaningful with --openapi-doc")


def resolve_schema_context(args, report):
    """Resolve the declared success shape ONCE per run, from the saved document."""
    ctx = {"active": False, "declared": None, "reason": None}
    if not args.openapi_doc:
        return ctx
    method = (args.openapi_method or "get").lower()
    report["openapi_doc"] = args.openapi_doc
    report["openapi_route"] = args.openapi_route
    report["openapi_method"] = method
    doc = load_openapi_doc(args.openapi_doc)          # GateError => exit 2
    schema, reason = declared_success_schema(doc, args.openapi_route, method)
    declared = None
    if schema is not None:
        declared, reason = resolve_declared_properties(doc, schema)
    ctx = {"active": True, "declared": declared, "reason": reason}
    report["schema_resolved"] = declared is not None
    report["schema_unresolvable_reason"] = reason
    report["declared_properties"] = declared or []
    if declared is None:
        report["warnings"].append(
            "declared-vs-observed schema comparison NOT performed: "
            + (reason or "") + " — an unresolvable or absent declaration is a "
            "warning, never a pass and never a fail")
    return ctx


def build_report(args):
    report = {
        "report": args.report, "milestone": args.milestone,
        "citations": [], "captures": [], "accepted": [], "rejected": [],
        "missing_keys": [], "stale": [], "in_process_transport": [],
        "sidecar_missing": [], "sidecar_hash_mismatch": [],
        "sidecar_body_disagrees": [], "capture_header_missing": [],
        "probe_failed_exit": [], "probe_not_client": [], "probe_exempt": [],
        "allow_missing_sidecar": bool(args.allow_missing_sidecar),
        "openapi_unreachable": [],
        "require_openapi_reachable": bool(args.require_openapi_reachable),
        "openapi_doc": None, "openapi_route": None, "openapi_method": None,
        "schema_resolved": None, "schema_unresolvable_reason": None,
        "declared_properties": [], "declared_absent": [], "observed_undeclared": [],
        "min_captures": args.min_captures, "warnings": [],
        "result": "ERROR", "error": None,
    }

    validate_openapi_args(args)
    report_text = read_text(args.report)
    report["citations"] = collect_citations(report_text)
    newest, warnings = newest_changed_mtime(args.changed_files)
    report["warnings"].extend(warnings)
    schema_ctx = resolve_schema_context(args, report)

    if not report["citations"]:
        report["result"] = "FAIL"
        report["warnings"].append(
            "no '**Runtime evidence:**' citation found in the report — a wire, "
            "device or rendered claim with no capture is unproven, not proven")
        return report

    patterns = milestone_token_patterns(args.milestone)
    for candidate in report["citations"]:
        res = evaluate_capture(candidate, args, patterns, newest, schema_ctx)
        report["captures"].append(res)
        if not res["milestone_match"]:
            continue  # another milestone's capture; not this gate's business
        if res["probe_exempt_reason"]:
            report["probe_exempt"].append(
                {"path": res["path"], "reason": res["probe_exempt_reason"]})
            report["warnings"].append(
                f"{res['path']}: probe client allowlist WAIVED by "
                f"[probe-exempt: {res['probe_exempt_reason']}] — the client was "
                "not verified, the author's reason stands in its place")
        if res["sidecar_waived"]:
            report["warnings"].append(
                f"{res['path']}: NO PROVENANCE SIDECAR, waived by "
                "--allow-missing-sidecar — this capture's contents are "
                "unverified and could have been typed by hand")
        for code in ("sidecar_missing", "sidecar_hash_mismatch",
                      "sidecar_body_disagrees", "capture_header_missing",
                      "probe_failed_exit", "probe_not_client"):
            if code in res["problem_codes"]:
                report[code].append(res["path"])
        # Informational half of the schema diff: never gates.
        report["observed_undeclared"].extend(res["observed_undeclared"])
        if res["schema_compared"] is False and res["schema_skipped_reason"]:
            report["warnings"].append(
                f"{res['path']}: schema diff not performed — "
                + res["schema_skipped_reason"])
        if res["problems"]:
            report["rejected"].append(res["path"])
            if res["missing_keys"]:
                report["missing_keys"].extend(res["missing_keys"])
            if res["declared_absent"]:
                report["declared_absent"].extend(res["declared_absent"])
            if res["fresh"] is False:
                report["stale"].append(res["path"])
            if any("IN-PROCESS" in p for p in res["problems"]):
                report["in_process_transport"].append(res["path"])
            if args.require_openapi_reachable and res["openapi_reachable"] is False:
                report["openapi_unreachable"].append(res["path"])
        else:
            report["accepted"].append(res["path"])

    scoped = [c for c in report["captures"] if c["milestone_match"]]
    if not scoped:
        report["warnings"].append(
            f"{len(report['citations'])} capture(s) cited, none naming milestone "
            f"{args.milestone!r} in its 'Milestone' field")
    report["missing_keys"] = sorted(set(report["missing_keys"]))
    report["declared_absent"] = sorted(set(report["declared_absent"]))
    report["observed_undeclared"] = sorted(set(report["observed_undeclared"]))
    if report["observed_undeclared"]:
        report["warnings"].append(
            "observed-but-undeclared top-level response properties (informational "
            "only — the runtime sends them and the contract surface does not "
            "declare them): " + ", ".join(report["observed_undeclared"]))
    report["result"] = ("PASS" if len(report["accepted"]) >= args.min_captures
                        else "FAIL")
    if report["declared_absent"]:
        # DELIBERATE DIVERGENCE (convention #8) from this gate's own pass rule
        # -- "accepted >= --min-captures", which every other check here obeys by
        # merely rejecting a capture. A declared-but-absent property is not
        # "this capture is not good enough"; it is the contract surface and the
        # runtime contradicting each other, which is the exact 2026-08 failure
        # class. No number of other accepted captures makes that untrue, so it
        # fails the run outright. Without this, a success capture that omits the
        # envelope is masked by any sibling capture the diff could not apply to
        # (a 4xx capture, for instance) whenever --min-captures is 1.
        report["result"] = "FAIL"
    return report


# ---------------------------------------------------------------------------
# Run ledger
# ---------------------------------------------------------------------------

def ledger_record(argv, milestone, inputs, verdict, exit_code):
    """The shared gate-ledger line shape. Every gate in this family writes it."""
    return {
        "ts": datetime.datetime.now(datetime.timezone.utc)
                .strftime("%Y-%m-%dT%H:%M:%SZ"),
        "gate": "check_runtime_evidence.py",
        "argv": list(argv),
        "milestone": milestone,
        "inputs": inputs,
        "verdict": verdict,
        "exit": exit_code,
    }


def ledger_inputs(args, citations):
    """{path as given: sha256 of its bytes or None} for the report + captures.

    Hashing the INPUTS is what makes the ledger an audit trail rather than a
    log: a later run over the same paths with different content is visibly a
    different run, and a rewritten report cannot quietly inherit an earlier
    line's verdict.
    """
    inputs = {}
    if args.report:
        inputs[args.report] = sha256_file(args.report)
    for cited in citations:
        resolved = resolve_path(cited, args.report or ".", args.repo)
        # Key by a path a LATER gate can re-hash from this cwd, not by the
        # citation string: a report-relative citation resolves here (against
        # the report's directory) but not from the commit gate's cwd, and
        # `check_commit_gate.py --require-ledger-gates` re-hashes the key as
        # written -- so keying by the raw citation made every report-relative
        # citation read as "missing now" at commit time.
        key = ledger_key(resolved) if resolved else cited
        if key in inputs:
            continue
        inputs[key] = sha256_file(resolved) if resolved else None
    return inputs


def ledger_key(path):
    """The path a later gate can re-hash from the same cwd.

    Relative to the cwd when the file lives under it (the normal case: every
    pipeline invocation runs from the repo root), else absolute. Forward
    slashes so the same key hashes on either OS.
    """
    p = Path(path).resolve()
    try:
        rel = p.relative_to(Path.cwd().resolve())
        return str(rel).replace("\\", "/")
    except ValueError:
        return str(p)


def append_ledger(path, record):
    """Append one JSON line. Returns a warning string on failure, else None.

    A ledger that cannot be written must not turn a real verdict into an
    error -- it degrades to a loud stderr line.
    """
    try:
        p = Path(path)
        if str(p.parent) not in ("", "."):
            p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
        return None
    except OSError as exc:
        return f"cannot append to --ledger {path}: {exc}"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def positive_int(value):
    """`--min-captures 0` asks the gate to pass with no evidence at all."""
    try:
        n = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{value!r} is not an integer")
    if n < 1:
        raise argparse.ArgumentTypeError(
            f"--min-captures must be >= 1 (got {n}); a gate that accepts zero "
            "captures is not a gate")
    return n


def build_parser():
    p = argparse.ArgumentParser(prog="check_runtime_evidence.py")
    p.add_argument("--report")
    p.add_argument("--milestone")
    p.add_argument("--changed-files", nargs="*", default=[])
    p.add_argument("--repo", default=".")
    p.add_argument("--surface")
    p.add_argument("--require-key", action="append", default=[])
    p.add_argument("--expect-status", type=int)
    p.add_argument("--forbid-host", action="append", default=[])
    p.add_argument("--require-build-marker")
    p.add_argument("--min-captures", type=positive_int, default=1)
    p.add_argument("--require-openapi-reachable", action="store_true")
    p.add_argument("--allow-missing-sidecar", action="store_true",
                    help="LEGACY ESCAPE HATCH: accept a capture with no "
                         "run_quiet.py provenance sidecar. Its contents are "
                         "then unverified.")
    p.add_argument("--ledger",
                    help="append one JSON audit line per run to this path")
    p.add_argument("--openapi-doc")
    p.add_argument("--openapi-route")
    p.add_argument("--openapi-method")
    p.add_argument("--self-test", action="store_true")
    return p


def main(argv):
    args = build_parser().parse_args(argv)

    if args.self_test:
        return run_self_test()

    if args.allow_missing_sidecar:
        print("check_runtime_evidence: WARNING — --allow-missing-sidecar is set. "
              "Captures with no run_quiet.py provenance sidecar are accepted "
              "unverified; a hand-typed capture is indistinguishable from an "
              "observed one under this flag.", file=sys.stderr)

    def emit(payload, exit_code, verdict, citations=()):
        if args.ledger:
            warn = append_ledger(args.ledger, ledger_record(
                argv, args.milestone, ledger_inputs(args, citations),
                verdict, exit_code))
            if warn:
                print(f"check_runtime_evidence: WARNING — {warn}", file=sys.stderr)
        print(json.dumps(payload, indent=2))
        return exit_code

    missing = [n for n, v in (("--report", args.report),
                              ("--milestone", args.milestone)) if not v]
    if missing:
        return emit({"result": "ERROR", "error_code": "missing_argument",
                     "error": f"missing required argument(s): {', '.join(missing)}"},
                    2, "ERROR")

    try:
        report = build_report(args)
    except GateError as exc:
        return emit({"result": "ERROR", "error_code": exc.code,
                     "error": str(exc)}, 2, "ERROR")

    exit_code = 0 if report["result"] == "PASS" else 1
    return emit(report, exit_code, report["result"], report["citations"])


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

def run_self_test():
    import contextlib
    import io
    import shutil
    import tempfile
    import unittest

    ENVELOPE = '{"statusCode":200,"isSuccess":true,"data":{"id":1},' \
               '"dataContext":null,"notifications":[]}'
    BARE = '{"id":1,"total":9}'

    def capture(milestone="M3 — Order envelope", transport="out-of-process HTTP",
                probe="curl -sS -i http://localhost:5142/api/orders",
                body=ENVELOPE, status="200 OK", base_url="http://localhost:5142",
                surface="api", extra=(), captured_section=True,
                exit_code=0, captured="2026-08-12T14:03:11Z"):
        head = [
            "# Runtime capture: POST /api/orders", "",
            f"- Milestone: {milestone}",
            f"- Surface: {surface}",
            f"- Transport: {transport}",
            f"- Base URL: {base_url}",
            f"- Probe command: `{probe}`",
            f"- Captured: {captured}",
            f"- Exit code: {exit_code}",
        ]
        head += list(extra)
        if not captured_section:
            return "\n".join(head) + "\n"
        payload = f"HTTP/1.1 {status}\ncontent-type: application/json\n\n{body}" \
            if status else body
        return "\n".join(head + ["", "## Captured output", "", "```",
                                  payload, "```", ""])

    class Tests(unittest.TestCase):
        def setUp(self):
            self.dir = Path(tempfile.mkdtemp())
            self.impl = self.dir / ".docs" / "proj" / "implementation"
            (self.impl / "evidence" / "runtime").mkdir(parents=True)
            self.report = self.impl / "test-report.md"
            self.changed = self.dir / "src" / "Api.cs"
            self.changed.parent.mkdir(parents=True, exist_ok=True)
            self.changed.write_text("// code", encoding="utf-8")

        def tearDown(self):
            shutil.rmtree(self.dir, ignore_errors=True)

        def _write(self, name="m3-orders.md", sidecar=True, sidecar_exit=0,
                    sidecar_hash=None, encoding="utf-8", **kw):
            p = self.impl / "evidence" / "runtime" / name
            # run_quiet.py writes the body's `- Exit code:` FROM the same
            # value it records in the sidecar, so a fixture keeps them in
            # sync unless the test is specifically about a flipped sidecar.
            kw.setdefault("exit_code", sidecar_exit)
            p.write_text(capture(**kw), encoding=encoding)
            if sidecar:
                self._write_sidecar(p, exit_code=sidecar_exit,
                                     capture_sha256=sidecar_hash)
            self._order(self.changed, p)
            return f"evidence/runtime/{name}"

        def _write_sidecar(self, capture_path, exit_code=0, capture_sha256=None,
                            drop=()):
            """A run_quiet.py-shaped sidecar for a fixture capture."""
            meta = {
                "argv": ["curl", "-sS", "-i", "http://localhost:5142/api/orders"],
                "cwd": str(self.dir), "host": "fixture-host", "pid": 4242,
                "started": "2026-08-12T14:03:10Z",
                "finished": "2026-08-12T14:03:11Z",
                "exit_code": exit_code,
                "body_sha256": "0" * 64,
                "capture_sha256": capture_sha256 or sha256_file(capture_path),
                "tool": "run_quiet.py", "schema": 1,
            }
            for key in drop:
                meta.pop(key, None)
            sidecar_path_for(capture_path).write_text(
                json.dumps(meta), encoding="utf-8")

        def _order(self, older, newer):
            """Synthetic mtimes — never the real clock."""
            os.utime(older, (1000, 1000))
            os.utime(newer, (2000, 2000))

        def _report(self, *cited):
            body = "#Task [1]:\n\n"
            if cited:
                body += "**Runtime evidence:** " + ", ".join(cited) + "\n"
            body += "- FR-4: PASS — EnvelopeTests.cs\n"
            self.report.write_text(body, encoding="utf-8")

        def _args(self, **kw):
            base = dict(report=str(self.report), milestone="M3 — Order envelope",
                        changed_files=[str(self.changed)], repo=str(self.dir),
                        surface=None, require_key=[], expect_status=None,
                        forbid_host=[], require_build_marker=None,
                        min_captures=1, require_openapi_reachable=False,
                        allow_missing_sidecar=False, ledger=None,
                        openapi_doc=None, openapi_route=None, openapi_method=None,
                        self_test=False)
            base.update(kw)
            return argparse.Namespace(**base)

        # ---- OpenAPI helpers ----

        def _doc(self, name="openapi.json", **doc):
            p = self.dir / name
            p.write_text(json.dumps(doc), encoding="utf-8")
            return str(p)

        def _envelope_doc(self, props=("statusCode", "isSuccess", "data",
                                        "dataContext", "notifications"),
                          method="get", route="/api/orders", ref=True,
                          schema=None):
            body = schema if schema is not None else (
                {"$ref": "#/components/schemas/OrderEnvelope"} if ref
                else {"type": "object",
                      "properties": {k: {"type": "string"} for k in props}})
            return self._doc(
                paths={route: {method: {"responses": {"200": {"content": {
                    "application/json": {"schema": body}}}}}}},
                components={"schemas": {"OrderEnvelope": {
                    "type": "object",
                    "properties": {k: {"type": "string"} for k in props}}}})

        # ---- happy path ----

        def test_happy_capture_passes(self):
            self._report(self._write())
            r = build_report(self._args(require_key=["isSuccess", "notifications"],
                                        expect_status=200))
            self.assertEqual(r["result"], "PASS", r)
            self.assertEqual(len(r["accepted"]), 1)

        # ---- the original bug ----

        def test_missing_envelope_key_fails(self):
            self._report(self._write(body=BARE))
            r = build_report(self._args(require_key=["isSuccess", "notifications"]))
            self.assertEqual(r["result"], "FAIL")
            self.assertEqual(r["missing_keys"], ["isSuccess", "notifications"])

        def test_key_nested_one_level_deeper_does_not_pass(self):
            self._report(self._write(body='{"data":{"isSuccess":true,"notifications":[]}}'))
            r = build_report(self._args(require_key=["isSuccess", "notifications"]))
            self.assertEqual(r["result"], "FAIL")

        def test_key_inside_body_scope_passes(self):
            self._report(self._write(body='{"body":{"isSuccess":true,"notifications":[]}}'))
            r = build_report(self._args(require_key=["isSuccess", "notifications"]))
            self.assertEqual(r["result"], "PASS", r)

        # ---- transport honesty ----

        def test_in_process_transport_rejected(self):
            for tell in ("WebApplicationFactory<Program>", "factory.CreateClient()",
                          "TestServer", "supertest(app)", "MockMvc"):
                self._report(self._write(transport=tell))
                r = build_report(self._args())
                self.assertEqual(r["result"], "FAIL", tell)
                self.assertEqual(len(r["in_process_transport"]), 1, tell)

        def test_test_runner_is_not_a_runtime_probe(self):
            """The whole point: a green suite is not an observation."""
            for bad in ("dotnet test --filter Envelope", "npm test", "pytest -k envelope",
                         "go test ./...", "npx jest orders",
                         # Flag-shaped rather than subcommand-shaped: these are the
                         # ones that slipped past the list. A capture declaring
                         # `node --test` with a hand-written envelope body passed
                         # the whole gate before 2026-08-12.
                         "node --test tests/orders.test.js", "pnpm test",
                         "deno test --allow-net", "bun test", "rspec spec/",
                         "phpunit --testsuite api", "rails test test/api"):
                self._report(self._write(probe=bad))
                r = build_report(self._args())
                self.assertEqual(r["result"], "FAIL", bad)

        def test_prose_described_in_process_transport_rejected(self):
            """An honest author who names no framework must still be caught.

            `Transport: direct handler call` with a well-formed envelope body
            passed outright — result PASS, zero problems — because every tell
            was a framework name. Prose is a weaker signal than a framework
            name and this stays a blocklist, but the honest case is now closed.
            """
            for prose in ("direct handler call", "in-process HTTP",
                          "invoked directly, no socket", "same process as the test",
                          "calls the handler directly"):
                self._report(self._write(transport=prose))
                r = build_report(self._args())
                self.assertEqual(r["result"], "FAIL", prose)
                self.assertEqual(len(r["in_process_transport"]), 1, prose)

        def test_build_command_probe_rejected(self):
            for bad in ("dotnet build", "npm run build", "tsc --noEmit",
                         "grep -r isSuccess src/", "msbuild /t:Rebuild"):
                self._report(self._write(probe=bad))
                r = build_report(self._args())
                self.assertEqual(r["result"], "FAIL", bad)

        def test_url_containing_rg_is_not_a_search_command(self):
            """Word boundaries: 'myorg' must not read as ripgrep."""
            self._report(self._write(
                probe="curl -sS -i http://myorg.localhost:5142/api/orders"))
            r = build_report(self._args())
            self.assertEqual(r["result"], "PASS", r)

        def test_status_line_survives_fence_parsing(self):
            """Regression: a `\\s*` fence regex ate the body's first line."""
            self._report(self._write())
            r = build_report(self._args(expect_status=200))
            self.assertEqual(r["result"], "PASS", r)
            self.assertEqual(r["captures"][0]["status"], 200)

        # ---- environment honesty ----

        def test_forbidden_host_rejected(self):
            self._report(self._write(base_url="https://api.dev.internal"))
            r = build_report(self._args(forbid_host=["dev.internal"]))
            self.assertEqual(r["result"], "FAIL")

        def test_forbidden_host_in_environment_field_rejected(self):
            self._report(self._write(
                extra=["- Environment: web=http://localhost:5173, crm=https://crm.dev.internal"]))
            r = build_report(self._args(forbid_host=["dev.internal"]))
            self.assertEqual(r["result"], "FAIL")

        def test_build_marker_mismatch_rejected(self):
            self._report(self._write(extra=["- Build marker: 1.4.1+sha.deadbee"]))
            r = build_report(self._args(require_build_marker="sha.9f2c1ab"))
            self.assertEqual(r["result"], "FAIL")

        def test_build_marker_required_but_absent_rejected(self):
            self._report(self._write())
            r = build_report(self._args(require_build_marker="sha.9f2c1ab"))
            self.assertEqual(r["result"], "FAIL")

        # ---- freshness ----

        def test_stale_capture_rejected(self):
            cited = self._write()
            p = self.impl / "evidence" / "runtime" / "m3-orders.md"
            self._order(p, self.changed)   # capture older than the diff
            self._report(cited)
            r = build_report(self._args())
            self.assertEqual(r["result"], "FAIL")
            self.assertEqual(r["stale"], [cited])

        # ---- provenance ----

        def test_evidence_build_dir_does_not_gate(self):
            p = self.impl / "evidence" / "build"
            p.mkdir(parents=True, exist_ok=True)
            (p / "m3.md").write_text(capture(), encoding="utf-8")
            self._order(self.changed, p / "m3.md")
            self._report("evidence/build/m3.md")
            r = build_report(self._args())
            self.assertEqual(r["result"], "FAIL")

        def test_parent_traversal_citation_refused(self):
            self.assertFalse(cited_under("../evidence/runtime/x.md", "evidence", "runtime"))
            self.assertTrue(cited_under("evidence/runtime/x.md", "evidence", "runtime"))
            self.assertTrue(cited_under(
                ".docs/proj/implementation/evidence/runtime/x.md", "evidence", "runtime"))
            self.assertTrue(cited_under("evidence\\runtime\\x.md", "evidence", "runtime"))

        def test_missing_file_fails(self):
            self._report("evidence/runtime/nope.md")
            r = build_report(self._args())
            self.assertEqual(r["result"], "FAIL")

        # ---- milestone scoping ----

        def test_other_milestone_capture_is_not_this_gates_business(self):
            self._report(self._write(name="m10.md", milestone="M10 — Something else"))
            r = build_report(self._args())
            self.assertEqual(r["result"], "FAIL")   # nothing accepted for M3
            self.assertEqual(r["rejected"], [])     # but not rejected either
            self.assertTrue(any("none naming milestone" in w for w in r["warnings"]))

        def test_m1_does_not_match_m10(self):
            self._report(self._write(name="m10.md", milestone="M10 — Other"))
            r = build_report(self._args(milestone="M1"))
            self.assertEqual(r["accepted"], [])

        # ---- report-level ----

        def test_no_citation_fails(self):
            self._report()
            r = build_report(self._args())
            self.assertEqual(r["result"], "FAIL")
            self.assertTrue(any("no '**Runtime evidence:**'" in w for w in r["warnings"]))

        def test_capture_without_output_section_is_exit_2(self):
            name = "broken.md"
            p = self.impl / "evidence" / "runtime" / name
            p.write_text(capture(captured_section=False), encoding="utf-8")
            self._order(self.changed, p)
            self._report(f"evidence/runtime/{name}")
            with self.assertRaises(GateError):
                build_report(self._args())

        def test_empty_captured_output_fails(self):
            self._report(self._write(body="", status=None))
            r = build_report(self._args())
            self.assertEqual(r["result"], "FAIL")

        def test_non_json_body_passes_when_no_content_assertion_asked(self):
            """Pins a deliberate scope boundary, so it stays intentional.

            The content assertions are JSON-shaped because the failure that
            motivated them was. A CSV/HTML/binary capture parses to no body and
            must still PASS on transport + freshness + status: requiring JSON
            would block every honest non-JSON surface. The cost is that such a
            claim gets no mechanical content check at all -- documented in
            pipeline-tools/SKILL.md rather than faked with --require-key.
            """
            self._report(self._write(body="id,total\n1,9"))
            r = build_report(self._args())
            self.assertEqual(r["result"], "PASS", r["captures"])
            self.assertFalse(r["captures"][0]["body_parsed"])
            self.assertEqual(r["captures"][0]["problems"], [])
            # ...but asking for a key against a body that has none still fails.
            r2 = build_report(self._args(require_key=["id"]))
            self.assertEqual(r2["result"], "FAIL")

        def test_status_mismatch_fails(self):
            self._report(self._write(status="500 Internal Server Error"))
            r = build_report(self._args(expect_status=200))
            self.assertEqual(r["result"], "FAIL")

        def test_min_captures_enforced(self):
            self._report(self._write())
            r = build_report(self._args(min_captures=2))
            self.assertEqual(r["result"], "FAIL")

        def test_missing_report_is_exit_2(self):
            with self.assertRaises(GateError):
                build_report(self._args(report=str(self.dir / "nope.md")))

        # ---- contract surface reachability (--require-openapi-reachable) ----

        OPENAPI_OK = "- OpenAPI: http://localhost:5142/swagger/v1/swagger.json — 200"

        def test_openapi_reachable_passes_when_2xx_recorded(self):
            self._report(self._write(extra=[self.OPENAPI_OK]))
            r = build_report(self._args(require_openapi_reachable=True))
            self.assertEqual(r["result"], "PASS", r)
            self.assertEqual(r["captures"][0]["openapi_status"], 200)
            self.assertTrue(r["captures"][0]["openapi_reachable"])
            self.assertEqual(r["openapi_unreachable"], [])

        def test_openapi_field_absent_rejected_when_required(self):
            self._report(self._write())
            r = build_report(self._args(require_openapi_reachable=True))
            self.assertEqual(r["result"], "FAIL")
            self.assertEqual(len(r["openapi_unreachable"]), 1)

        def test_openapi_non_2xx_status_rejected(self):
            for bad in ("404", "500", "301"):
                self._report(self._write(extra=[
                    f"- OpenAPI: http://localhost:5142/swagger/v1/swagger.json — {bad}"]))
                r = build_report(self._args(require_openapi_reachable=True))
                self.assertEqual(r["result"], "FAIL", bad)
                self.assertEqual(r["captures"][0]["openapi_status"], int(bad))
                self.assertFalse(r["captures"][0]["openapi_reachable"])

        def test_openapi_value_without_url_rejected(self):
            self._report(self._write(extra=["- OpenAPI: reachable, looked fine — 200"]))
            r = build_report(self._args(require_openapi_reachable=True))
            self.assertEqual(r["result"], "FAIL")
            self.assertIsNone(r["captures"][0]["openapi_url"])

        def test_openapi_url_without_status_rejected(self):
            self._report(self._write(extra=[
                "- OpenAPI: http://localhost:5142/swagger/v1/swagger.json"]))
            r = build_report(self._args(require_openapi_reachable=True))
            self.assertEqual(r["result"], "FAIL")
            self.assertIsNone(r["captures"][0]["openapi_status"])

        def test_openapi_port_is_not_read_as_status(self):
            """A port must never supply the status: :200 is not a 200 response."""
            self._report(self._write(extra=[
                "- OpenAPI: http://localhost:200/swagger.json — 404"]))
            r = build_report(self._args(require_openapi_reachable=True))
            self.assertEqual(r["captures"][0]["openapi_status"], 404)
            self.assertEqual(r["result"], "FAIL")

        def test_openapi_separator_is_not_load_bearing(self):
            """Em dash, hyphen, comma or plain space all work: URL + 2xx status."""
            for sep in ("—", "-", ",", "", "status"):
                self._report(self._write(extra=[
                    f"- OpenAPI: http://localhost:5142/swagger.json {sep} 200"]))
                r = build_report(self._args(require_openapi_reachable=True))
                self.assertEqual(r["result"], "PASS", sep)
                self.assertEqual(r["captures"][0]["openapi_status"], 200, sep)

        def test_openapi_field_does_not_gate_when_flag_unset(self):
            self._report(self._write(extra=[
                "- OpenAPI: http://localhost:5142/swagger.json — 404"]))
            r = build_report(self._args())
            self.assertEqual(r["result"], "PASS", r)
            self.assertFalse(r["captures"][0]["openapi_reachable"])
            self.assertEqual(r["openapi_unreachable"], [])

        def test_openapi_keys_present_when_no_field_and_no_flag(self):
            """Backward compatibility: new keys are always present, and null."""
            self._report(self._write())
            r = build_report(self._args())
            cap = r["captures"][0]
            for key in ("openapi_url", "openapi_status", "openapi_reachable",
                         "schema_compared", "schema_skipped_reason", "observed_scope"):
                self.assertIn(key, cap)
                self.assertIsNone(cap[key], key)
            self.assertEqual(cap["declared_absent"], [])
            self.assertEqual(cap["observed_undeclared"], [])
            for key in ("openapi_doc", "openapi_route", "openapi_method",
                         "schema_resolved", "schema_unresolvable_reason"):
                self.assertIsNone(r[key], key)
            self.assertEqual(r["declared_properties"], [])
            self.assertEqual(r["declared_absent"], [])
            self.assertEqual(r["observed_undeclared"], [])
            self.assertFalse(r["require_openapi_reachable"])

        # ---- declared-vs-observed schema diff ----

        def _schema_args(self, doc, route="/api/orders", method="get", **kw):
            return self._args(openapi_doc=doc, openapi_route=route,
                               openapi_method=method, **kw)

        def test_declared_schema_match_passes(self):
            self._report(self._write())
            r = build_report(self._schema_args(self._envelope_doc()))
            self.assertEqual(r["result"], "PASS", r)
            self.assertTrue(r["schema_resolved"])
            self.assertTrue(r["captures"][0]["schema_compared"])
            self.assertEqual(r["declared_absent"], [])

        def test_declared_but_absent_property_fails(self):
            """The gating case: Swagger promises the envelope, runtime omits it."""
            self._report(self._write(body='{"statusCode":200,"isSuccess":true,"data":{}}'))
            r = build_report(self._schema_args(self._envelope_doc()))
            self.assertEqual(r["result"], "FAIL")
            self.assertEqual(r["declared_absent"], ["dataContext", "notifications"])
            self.assertTrue(r["captures"][0]["schema_compared"])

        def test_declared_absent_fails_even_when_a_sibling_is_accepted(self):
            """Deliberate divergence: this ignores --min-captures entirely.

            A 4xx sibling is schema-skipped and therefore acceptable; without the
            override it would mask a success capture that omits the envelope.
            """
            good = self._write(name="m3-400.md", status="400 Bad Request",
                                body='{"statusCode":400,"errors":[]}')
            bad = self._write(body='{"statusCode":200,"isSuccess":true,"data":{}}')
            self._report(good, bad)
            r = build_report(self._schema_args(self._envelope_doc(), min_captures=1))
            self.assertEqual(len(r["accepted"]), 1)          # the 4xx sibling
            self.assertGreaterEqual(len(r["accepted"]), r["min_captures"])
            self.assertEqual(r["result"], "FAIL", r)         # and it still fails
            self.assertEqual(r["declared_absent"], ["dataContext", "notifications"])

        def test_observed_undeclared_is_informational_only(self):
            self._report(self._write(body=ENVELOPE.replace(
                '{"statusCode"', '{"traceId":"abc","statusCode"')))
            r = build_report(self._schema_args(self._envelope_doc()))
            self.assertEqual(r["result"], "PASS", r)
            self.assertEqual(r["observed_undeclared"], ["traceId"])
            self.assertEqual(r["declared_absent"], [])

        def test_inline_schema_without_ref_compared(self):
            self._report(self._write())
            r = build_report(self._schema_args(self._envelope_doc(ref=False)))
            self.assertEqual(r["result"], "PASS", r)
            self.assertTrue(r["schema_resolved"])

        def test_swagger2_style_response_schema_compared(self):
            doc = self._doc(paths={"/api/orders": {"get": {"responses": {"200": {
                "schema": {"$ref": "#/components/schemas/OrderEnvelope"}}}}}},
                components={"schemas": {"OrderEnvelope": {"type": "object",
                    "properties": {"statusCode": {}, "isSuccess": {}, "data": {},
                                    "dataContext": {}, "notifications": {}}}}})
            self._report(self._write())
            r = build_report(self._schema_args(doc))
            self.assertEqual(r["result"], "PASS", r)

        def test_body_scope_used_for_comparison(self):
            self._report(self._write(
                body='{"body":{"statusCode":1,"isSuccess":true,"data":{},'
                      '"dataContext":null,"notifications":[]}}'))
            r = build_report(self._schema_args(self._envelope_doc()))
            self.assertEqual(r["result"], "PASS", r)
            self.assertEqual(r["captures"][0]["observed_scope"], "body")

        def test_nested_properties_are_not_compared(self):
            """Top-level names only: a nested difference must not gate."""
            doc = self._doc(paths={"/api/orders": {"get": {"responses": {"200": {
                "content": {"application/json": {"schema": {"type": "object",
                    "properties": {
                        "statusCode": {}, "isSuccess": {},
                        "data": {"type": "object", "properties": {
                            "somethingNeverSent": {}}},
                        "dataContext": {}, "notifications": {}}}}}}}}}})
            self._report(self._write())
            r = build_report(self._schema_args(doc))
            self.assertEqual(r["result"], "PASS", r)
            self.assertEqual(r["declared_absent"], [])

        # ---- unresolvable => WARNING, never a pass and never a fail ----

        def _assert_warns_not_fails(self, doc, fragment):
            self._report(self._write())
            r = build_report(self._schema_args(doc))
            self.assertEqual(r["result"], "PASS", r)          # never a fail
            self.assertFalse(r["schema_resolved"])            # never a pass
            self.assertIsNotNone(r["schema_unresolvable_reason"])
            self.assertIn(fragment, r["schema_unresolvable_reason"])
            self.assertFalse(r["captures"][0]["schema_compared"])
            self.assertEqual(r["declared_properties"], [])
            self.assertTrue(any("never a pass and never a fail" in w
                                 for w in r["warnings"]))
            return r

        def test_allof_composition_warns_not_fails(self):
            self._assert_warns_not_fails(
                self._envelope_doc(schema={"allOf": [
                    {"$ref": "#/components/schemas/OrderEnvelope"},
                    {"type": "object", "properties": {"extra": {}}}]}),
                "'allOf' composition")

        def test_oneof_anyof_not_discriminator_warn_not_fail(self):
            for keyword in ("oneOf", "anyOf", "not", "discriminator"):
                self._assert_warns_not_fails(
                    self._envelope_doc(schema={keyword: [{"type": "object"}],
                                                "type": "object",
                                                "properties": {"statusCode": {}}}),
                    f"{keyword!r} composition")

        def test_second_level_ref_warns_not_fails(self):
            doc = self._doc(
                paths={"/api/orders": {"get": {"responses": {"200": {"content": {
                    "application/json": {"schema": {
                        "$ref": "#/components/schemas/Outer"}}}}}}}},
                components={"schemas": {
                    "Outer": {"$ref": "#/components/schemas/OrderEnvelope"},
                    "OrderEnvelope": {"type": "object",
                                       "properties": {"statusCode": {}}}}})
            self._assert_warns_not_fails(doc, "second-level '$ref'")

        def test_foreign_ref_target_warns_not_fails(self):
            self._assert_warns_not_fails(
                self._envelope_doc(schema={"$ref": "#/definitions/OrderEnvelope"}),
                "one hop only")

        def test_absent_ref_target_warns_not_fails(self):
            self._assert_warns_not_fails(
                self._envelope_doc(schema={"$ref": "#/components/schemas/Nope"}),
                "absent from the document")

        def test_array_schema_warns_not_fails(self):
            self._assert_warns_not_fails(
                self._envelope_doc(schema={"type": "array",
                                            "items": {"type": "object"}}),
                "no top-level property")

        def test_empty_properties_warns_not_fails(self):
            self._assert_warns_not_fails(
                self._envelope_doc(schema={"type": "object", "properties": {}}),
                "empty 'properties' object")

        def test_missing_route_warns_not_fails(self):
            self._report(self._write())
            r = build_report(self._schema_args(self._envelope_doc(),
                                                route="/api/nope"))
            self.assertEqual(r["result"], "PASS", r)
            self.assertFalse(r["schema_resolved"])
            self.assertIn("is not declared", r["schema_unresolvable_reason"])

        def test_missing_method_warns_not_fails(self):
            self._report(self._write())
            r = build_report(self._schema_args(self._envelope_doc(),
                                                method="delete"))
            self.assertEqual(r["result"], "PASS", r)
            self.assertIn("DELETE is not declared", r["schema_unresolvable_reason"])

        def test_no_success_response_warns_not_fails(self):
            doc = self._doc(paths={"/api/orders": {"get": {"responses": {
                "400": {"content": {"application/json": {"schema": {}}}},
                "default": {}}}}})
            self._assert_warns_not_fails(doc, "no success (2xx) response")

        def test_no_json_media_type_warns_not_fails(self):
            doc = self._doc(paths={"/api/orders": {"get": {"responses": {"200": {
                "content": {"text/plain": {"schema": {"type": "object"}}}}}}}})
            self._assert_warns_not_fails(doc, "no JSON media type")

        def test_route_leading_slash_normalized(self):
            self._report(self._write())
            r = build_report(self._schema_args(self._envelope_doc(),
                                                route="api/orders"))
            self.assertEqual(r["result"], "PASS", r)
            self.assertTrue(r["schema_resolved"])

        def test_schema_diff_skipped_for_non_2xx_capture(self):
            """A declared 2xx schema does not describe a 400 body."""
            self._report(self._write(status="400 Bad Request",
                                      body='{"statusCode":400,"errors":[]}'))
            r = build_report(self._schema_args(self._envelope_doc()))
            self.assertEqual(r["result"], "PASS", r)
            self.assertFalse(r["captures"][0]["schema_compared"])
            self.assertIn("observed HTTP 400",
                           r["captures"][0]["schema_skipped_reason"])

        def test_unparseable_body_under_schema_diff_warns_not_fails(self):
            self._report(self._write(body="not json at all"))
            r = build_report(self._schema_args(self._envelope_doc()))
            self.assertEqual(r["result"], "PASS", r)
            self.assertFalse(r["captures"][0]["schema_compared"])
            self.assertIn("cannot compare",
                           r["captures"][0]["schema_skipped_reason"])

        # ---- schema-diff usage errors ----

        def test_openapi_doc_without_route_is_exit_2(self):
            self._report(self._write())
            with self.assertRaises(GateError):
                build_report(self._args(openapi_doc=self._envelope_doc()))

        def test_openapi_route_without_doc_is_exit_2(self):
            self._report(self._write())
            with self.assertRaises(GateError):
                build_report(self._args(openapi_route="/api/orders"))

        def test_openapi_method_without_doc_is_exit_2(self):
            self._report(self._write())
            with self.assertRaises(GateError):
                build_report(self._args(openapi_method="post"))

        def test_missing_openapi_doc_is_exit_2(self):
            self._report(self._write())
            with self.assertRaises(GateError):
                build_report(self._schema_args(str(self.dir / "nope.json")))

        def test_invalid_json_openapi_doc_is_exit_2(self):
            p = self.dir / "bad.json"
            p.write_text("openapi: 3.0.0\npaths: {}\n", encoding="utf-8")
            self._report(self._write())
            with self.assertRaises(GateError):
                build_report(self._schema_args(str(p)))

        # ---- provenance: the run_quiet.py sidecar ----

        def test_sidecar_missing_rejects_capture(self):
            """A hand-typed capture has no sidecar. That is the whole tell."""
            cited = self._write(sidecar=False)
            self._report(cited)
            r = build_report(self._args())
            self.assertEqual(r["result"], "FAIL")
            self.assertEqual(r["sidecar_missing"], [cited])
            self.assertIn("sidecar_missing", r["captures"][0]["problem_codes"])

        def test_sidecar_hash_mismatch_rejects_capture(self):
            cited = self._write(sidecar_hash="ab" * 32)
            self._report(cited)
            r = build_report(self._args())
            self.assertEqual(r["result"], "FAIL")
            self.assertEqual(r["sidecar_hash_mismatch"], [cited])
            self.assertFalse(r["captures"][0]["sidecar_capture_sha256_ok"])

        def test_capture_edited_after_recording_is_rejected(self):
            """The realistic shape: a real probe, then a 'small correction'."""
            cited = self._write()
            p = self.impl / "evidence" / "runtime" / "m3-orders.md"
            p.write_text(p.read_text(encoding="utf-8").replace(
                '"isSuccess":true', '"isSuccess":true,"notifications":[]'),
                encoding="utf-8")
            self._order(self.changed, p)
            self._report(cited)
            r = build_report(self._args())
            self.assertEqual(r["result"], "FAIL")
            self.assertEqual(r["sidecar_hash_mismatch"], [cited])

        def test_nonzero_probe_exit_rejects_capture_whatever_the_body_says(self):
            """`Exit code: 7` is connection-refused. A body cannot outvote it."""
            cited = self._write(sidecar_exit=7)
            self._report(cited)
            r = build_report(self._args(require_key=["isSuccess", "notifications"],
                                         expect_status=200))
            self.assertEqual(r["result"], "FAIL")
            self.assertEqual(r["probe_failed_exit"], [cited])
            self.assertEqual(r["captures"][0]["sidecar_exit_code"], 7)
            self.assertEqual(r["missing_keys"], [])   # body was fine; probe was not

        # ---- the sidecar is the mutable half: it must agree with the body ----

        def test_flipped_sidecar_exit_code_is_caught_by_the_body(self):
            """The attack: sidecar exit_code 3 -> 0. The hash still matches."""
            cited = self._write(exit_code=3, sidecar_exit=3)
            p = self.impl / "evidence" / "runtime" / "m3-orders.md"
            self._write_sidecar(p, exit_code=0)   # forge only the sidecar
            self._order(self.changed, p)
            self._report(cited)
            r = build_report(self._args())
            self.assertEqual(r["result"], "FAIL")
            self.assertEqual(r["sidecar_body_disagrees"], [cited])
            self.assertEqual(r["sidecar_hash_mismatch"], [])  # hash is intact
            self.assertFalse(r["captures"][0]["sidecar_body_agrees"])

        def test_edited_sidecar_timestamp_is_caught_by_the_body(self):
            """Pushing `finished` forward is how a stale capture reads fresh."""
            cited = self._write()
            p = self.impl / "evidence" / "runtime" / "m3-orders.md"
            meta = json.loads(sidecar_path_for(p).read_text(encoding="utf-8"))
            meta["finished"] = "2026-08-19T09:00:00Z"
            sidecar_path_for(p).write_text(json.dumps(meta), encoding="utf-8")
            self._report(cited)
            r = build_report(self._args())
            self.assertEqual(r["result"], "FAIL")
            self.assertEqual(r["sidecar_body_disagrees"], [cited])

        def test_agreeing_pair_passes(self):
            cited = self._write()
            self._report(cited)
            r = build_report(self._args())
            self.assertEqual(r["result"], "PASS", r["captures"])
            self.assertTrue(r["captures"][0]["sidecar_body_agrees"])

        def test_one_second_render_skew_still_passes(self):
            """The pre-2.4 build path stamped `Captured` just after `finished`."""
            cited = self._write(captured="2026-08-12T14:03:12Z")
            self._report(cited)
            r = build_report(self._args())
            self.assertEqual(r["result"], "PASS", r["captures"])

        def test_legacy_capture_without_header_lines_fails_closed(self):
            cited = self._write(extra=("- NOTE: legacy capture",))
            p = self.impl / "evidence" / "runtime" / "m3-orders.md"
            text = p.read_text(encoding="utf-8")
            for line in ("- Captured: 2026-08-12T14:03:11Z\n",
                          "- Exit code: 0\n"):
                text = text.replace(line, "")
            p.write_text(text, encoding="utf-8")
            self._write_sidecar(p)          # re-hash: only the header is gone
            self._order(self.changed, p)
            self._report(cited)
            r = build_report(self._args())
            self.assertEqual(r["result"], "FAIL")
            self.assertEqual(r["capture_header_missing"], [cited])
            self.assertEqual(r["sidecar_body_disagrees"], [])

        def test_sidecar_without_integer_exit_code_rejected(self):
            cited = self._write()
            p = self.impl / "evidence" / "runtime" / "m3-orders.md"
            self._write_sidecar(p, drop=("exit_code",))
            self._report(cited)
            r = build_report(self._args())
            self.assertEqual(r["result"], "FAIL")
            self.assertEqual(r["probe_failed_exit"], [cited])

        def test_malformed_sidecar_reads_as_missing(self):
            cited = self._write()
            sidecar_path_for(
                self.impl / "evidence" / "runtime" / "m3-orders.md"
            ).write_text("{not json", encoding="utf-8")
            self._report(cited)
            r = build_report(self._args())
            self.assertEqual(r["result"], "FAIL")
            self.assertEqual(r["sidecar_missing"], [cited])

        def test_allow_missing_sidecar_waives_only_absence_and_warns(self):
            cited = self._write(sidecar=False)
            self._report(cited)
            r = build_report(self._args(allow_missing_sidecar=True))
            self.assertEqual(r["result"], "PASS", r)
            self.assertTrue(r["allow_missing_sidecar"])
            self.assertTrue(r["captures"][0]["sidecar_waived"])
            self.assertTrue(any("NO PROVENANCE SIDECAR" in w for w in r["warnings"]))
            # ...but a sidecar that IS there and disagrees is still fatal.
            self._report(self._write(name="m3b.md", sidecar_hash="cd" * 32))
            r2 = build_report(self._args(allow_missing_sidecar=True))
            self.assertEqual(r2["result"], "FAIL")

        # ---- provenance: was a real client used? ----

        def test_probe_client_allowlist_accepts_real_clients(self):
            for good in ("curl -sS -i http://localhost:5142/api/orders",
                          "/usr/bin/curl -sS http://localhost:5142/api/orders",
                          "C:\\\\tools\\\\curl.exe -sS http://localhost:5142/x",
                          "wget -S -O - http://localhost:5142/api/orders",
                          "http GET http://localhost:5142/api/orders",
                          "newman run postman/orders.json",
                          "k6 run script.js", "hey -n 10 http://localhost:5142/",
                          "TOKEN=abc curl -sS http://localhost:5142/api/orders",
                          "timeout 30 curl -sS http://localhost:5142/api/orders",
                          "npx playwright test orders.spec.ts",
                          "psql -h localhost -p 5432 -d app -f probe.sql",
                          "grpcurl -plaintext localhost:5000 list",
                          "redis-cli -h localhost ping",
                          "Invoke-WebRequest http://localhost:5142/api/orders",
                          "irm http://localhost:5142/api/orders",
                          "openssl s_client -connect localhost:5142",
                          "adb shell am start -a VIEW",
                          "ssh deploy@localhost curl -s localhost:5142/health"):
                self._report(self._write(probe=good))
                r = build_report(self._args())
                self.assertEqual(r["result"], "PASS", (good, r["captures"]))

        def test_python_dash_c_probe_rejected(self):
            """The red-team vector: an interpreter printing a transcript."""
            self._report(self._write(
                probe="python -c \"print('HTTP/1.1 200 OK'); print('{}')\""))
            r = build_report(self._args())
            self.assertEqual(r["result"], "FAIL")
            self.assertEqual(len(r["probe_not_client"]), 1)
            self.assertEqual(r["captures"][0]["probe_client"], "python")

        def test_text_printing_commands_rejected(self):
            for bad in ("echo '{\"isSuccess\":true}'",
                         "printf 'HTTP/1.1 200 OK\\n'",
                         "cat fixtures/response.json",
                         "type fixtures\\\\response.json",
                         "python3 probe_helper.py",
                         "./scripts/probe.sh --url http://localhost:5142"):
                self._report(self._write(probe=bad))
                r = build_report(self._args())
                self.assertEqual(r["result"], "FAIL", bad)
                self.assertEqual(len(r["probe_not_client"]), 1, bad)

        def test_run_quiet_wrapper_prefix_is_peeled(self):
            """`python … run_quiet.py … -- curl` is curl, not python."""
            self._report(self._write(
                probe="python skills/pipeline-tools/scripts/run_quiet.py "
                       "--capture evidence/runtime/m3.md -- "
                       "curl -sS -i http://localhost:5142/api/orders"))
            r = build_report(self._args())
            self.assertEqual(r["result"], "PASS", r["captures"])
            self.assertEqual(r["captures"][0]["probe_client"], "curl")

        def test_npx_counts_only_when_it_launches_playwright(self):
            self._report(self._write(probe="npx playwright test orders.spec.ts"))
            self.assertEqual(build_report(self._args())["result"], "PASS")
            self._report(self._write(probe="npx serve ./public"))
            r = build_report(self._args())
            self.assertEqual(r["result"], "FAIL")
            self.assertEqual(len(r["probe_not_client"]), 1)

        def test_probe_exempt_accepts_any_client_and_records_the_reason(self):
            self._report(self._write(
                probe="./tools/mqtt-probe --host localhost "
                       "[probe-exempt: bespoke MQTT client, no allowlisted "
                       "equivalent]"))
            r = build_report(self._args())
            self.assertEqual(r["result"], "PASS", r["captures"])
            self.assertEqual(len(r["probe_exempt"]), 1)
            self.assertIn("MQTT", r["probe_exempt"][0]["reason"])
            self.assertTrue(any("allowlist WAIVED" in w for w in r["warnings"]))

        def test_probe_exempt_does_not_waive_the_in_process_tell(self):
            """The exemption covers the allowlist only — nothing else relaxes."""
            self._report(self._write(
                transport="WebApplicationFactory<Program>",
                probe="./tools/mqtt-probe [probe-exempt: bespoke client]"))
            r = build_report(self._args())
            self.assertEqual(r["result"], "FAIL")
            self.assertEqual(len(r["in_process_transport"]), 1)

        def test_probe_exempt_does_not_waive_the_sidecar(self):
            self._report(self._write(
                sidecar=False,
                probe="./tools/mqtt-probe [probe-exempt: bespoke client]"))
            r = build_report(self._args())
            self.assertEqual(r["result"], "FAIL")
            self.assertEqual(len(r["sidecar_missing"]), 1)

        # ---- --changed-files must exist ----

        def test_missing_changed_file_is_a_structural_error(self):
            """It used to WARN and skip, silently disabling freshness."""
            self._report(self._write())
            with self.assertRaises(GateError) as ctx:
                build_report(self._args(
                    changed_files=[str(self.changed), str(self.dir / "gone.cs")]))
            self.assertEqual(ctx.exception.code, "changed_file_missing")

        # ---- fenced blocks cannot gate ----

        def test_fenced_citation_does_not_gate(self):
            """An EXAMPLE citation in a report's docs block is not evidence."""
            self._write()
            self.report.write_text(
                "#Task [1]:\n\nExample of how to cite a capture:\n\n"
                "```\n**Runtime evidence:** evidence/runtime/m3-orders.md\n```\n"
                "- FR-4: PASS — EnvelopeTests.cs\n", encoding="utf-8")
            r = build_report(self._args())
            self.assertEqual(r["citations"], [])
            self.assertEqual(r["result"], "FAIL")
            self.assertTrue(any("no '**Runtime evidence:**'" in w
                                 for w in r["warnings"]))

        def test_tilde_fenced_citation_does_not_gate(self):
            self._write()
            self.report.write_text(
                "#Task [1]:\n\n~~~\n**Runtime evidence:** "
                "evidence/runtime/m3-orders.md\n~~~\n", encoding="utf-8")
            self.assertEqual(build_report(self._args())["citations"], [])

        def test_fenced_field_in_a_capture_supplies_nothing(self):
            self._report(self._write(extra=[
                "", "```", "- Build marker: 9.9.9+sha.fabricated", "```", ""]))
            r = build_report(self._args(require_build_marker="9.9.9"))
            self.assertIsNone(r["captures"][0]["build_marker"])
            self.assertEqual(r["result"], "FAIL")

        def test_fenced_captured_output_heading_does_not_win(self):
            """A fenced fake body ahead of the real one must not be parsed."""
            self._report(self._write(body=BARE, extra=[
                "", "````", "## Captured output", "",
                '{"isSuccess":true,"notifications":[]}', "````", ""]))
            r = build_report(self._args(require_key=["isSuccess", "notifications"]))
            self.assertEqual(r["result"], "FAIL")
            self.assertEqual(r["missing_keys"], ["isSuccess", "notifications"])

        # ---- encoding ----

        def test_bom_is_tolerated_in_capture_and_report(self):
            """A BOM ahead of the first `- Field:` line broke utf-8 parsing."""
            name = "m3-bom.md"
            p = self.impl / "evidence" / "runtime" / name
            # Drop the title so a FIELD line is the file's first line.
            p.write_text(capture().split("\n", 2)[2], encoding="utf-8-sig")
            self._write_sidecar(p)
            self._order(self.changed, p)
            self.report.write_text(
                f"**Runtime evidence:** evidence/runtime/{name}\n",
                encoding="utf-8-sig")
            r = build_report(self._args(require_key=["isSuccess"],
                                         expect_status=200))
            self.assertEqual(r["result"], "PASS", r["captures"])

        # ---- CLI ----

        def _cli(self, *extra, report=None):
            argv = ["--report", report or str(self.report),
                    "--milestone", "M3 — Order envelope",
                    "--repo", str(self.dir)] + list(extra)
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = main(argv)
            return code, out.getvalue(), err.getvalue()

        def _ledger_lines(self, path):
            return [json.loads(l) for l in
                    Path(path).read_text(encoding="utf-8").splitlines() if l.strip()]

        def test_min_captures_zero_is_a_usage_error(self):
            """`--min-captures 0` passed with an in-process transport detected."""
            self._report(self._write())
            with contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as ctx:
                    main(["--report", str(self.report), "--milestone", "M3",
                          "--min-captures", "0"])
            self.assertEqual(ctx.exception.code, 2)

        def test_ledger_line_written_on_pass(self):
            cited = self._write()
            self._report(cited)
            led = self.dir / "logs" / "nested" / "gates.jsonl"
            code, _, _ = self._cli("--ledger", str(led))
            self.assertEqual(code, 0)
            self.assertTrue(led.is_file())          # parent dirs created
            rec = self._ledger_lines(led)[0]
            self.assertEqual(rec["gate"], "check_runtime_evidence.py")
            self.assertEqual(rec["verdict"], "PASS")
            self.assertEqual(rec["exit"], 0)
            self.assertEqual(rec["milestone"], "M3 — Order envelope")
            self.assertIn("--ledger", rec["argv"])
            self.assertRegex(rec["ts"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
            self.assertEqual(rec["inputs"][str(self.report)],
                              sha256_file(self.report))
            captured = self.impl / "evidence" / "runtime" / "m3-orders.md"
            self.assertEqual(rec["inputs"][ledger_key(captured)],
                             sha256_file(captured))
            self.assertNotIn(cited, rec["inputs"])   # not the raw citation

        def test_ledger_inputs_re_hash_from_cwd(self):
            """The property the commit gate relies on: every hashed key must
            re-hash to the recorded value from the invoking cwd, even when the
            report cited the capture relative to its own directory."""
            self._report(self._write())
            led = self.dir / "gates.jsonl"
            code, _, _ = self._cli("--ledger", str(led))
            self.assertEqual(code, 0)
            rec = self._ledger_lines(led)[0]
            hashed = {k: v for k, v in rec["inputs"].items() if v}
            self.assertGreaterEqual(len(hashed), 2)
            for key, recorded in hashed.items():
                self.assertEqual(sha256_file(key), recorded, key)

        def test_probe_client_unquoted_path_with_spaces_accepted(self):
            for good in ("C:\\Program Files\\Git\\mingw64\\bin\\curl.EXE -sS http://localhost:5142/x",
                         "/Applications/My Tools/curl -sS http://localhost:5142/x",
                         "TOKEN=abc C:\\Program Files\\curl\\bin\\curl.exe -sS http://localhost:5142/x"):
                self._report(self._write(probe=good))
                r = build_report(self._args())
                self.assertEqual(r["result"], "PASS", (good, r["captures"]))

        def test_probe_client_unquoted_path_with_spaces_non_client_rejected(self):
            self._report(self._write(probe="C:\\Program Files\\nodejs\\node.exe probe.js"))
            r = build_report(self._args())
            self.assertEqual(r["result"], "FAIL")
            self.assertIn("'node' is not a runtime probe client", json.dumps(r))

        def test_ledger_line_written_on_fail_and_appends(self):
            self._report(self._write(sidecar=False))
            led = self.dir / "gates.jsonl"
            code, _, _ = self._cli("--ledger", str(led))
            self.assertEqual(code, 1)
            code2, _, _ = self._cli("--ledger", str(led))
            self.assertEqual(code2, 1)
            recs = self._ledger_lines(led)
            self.assertEqual(len(recs), 2)                # appended, not replaced
            self.assertEqual([r["verdict"] for r in recs], ["FAIL", "FAIL"])
            self.assertEqual([r["exit"] for r in recs], [1, 1])

        def test_ledger_line_written_on_error(self):
            led = self.dir / "gates.jsonl"
            code, out, _ = self._cli("--ledger", str(led),
                                      report=str(self.dir / "nope.md"))
            self.assertEqual(code, 2)
            rec = self._ledger_lines(led)[0]
            self.assertEqual(rec["verdict"], "ERROR")
            self.assertEqual(rec["exit"], 2)
            self.assertIsNone(rec["inputs"][str(self.dir / "nope.md")])

        def test_missing_changed_file_exits_2_with_error_code(self):
            self._report(self._write())
            led = self.dir / "gates.jsonl"
            code, out, _ = self._cli(
                "--ledger", str(led),
                "--changed-files", str(self.changed), str(self.dir / "gone.cs"))
            self.assertEqual(code, 2)
            payload = json.loads(out)
            self.assertEqual(payload["error_code"], "changed_file_missing")
            self.assertEqual(self._ledger_lines(led)[0]["verdict"], "ERROR")

        def test_allow_missing_sidecar_is_loud_on_stderr(self):
            self._report(self._write(sidecar=False))
            code, _, err = self._cli("--allow-missing-sidecar")
            self.assertEqual(code, 0)
            self.assertIn("--allow-missing-sidecar", err)
            self.assertIn("WARNING", err)

        def test_usage_error_exits_2(self):
            self.assertEqual(main(["--milestone", "M3"]), 2)
            self.assertEqual(main(["--report", str(self.report)]), 2)

    suite = unittest.defaultTestLoader.loadTestsFromTestCase(Tests)
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
