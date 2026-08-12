#!/usr/bin/env python3
"""Mechanical gate for observed-runtime evidence.

Converts the prose rule that an in-process observation can fail a wire
claim but never pass one (runtime-evidence/SKILL.md) into an artifact that
has to exist on disk. Reads a durable agent report, collects its
`**Runtime evidence:**` citations, and verifies each cited capture:

  * exists, resolved against the report's directory or --repo
  * is cited under an `evidence/runtime/` directory
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
        [--openapi-doc <path> --openapi-route <path> [--openapi-method <verb>]]
    python check_runtime_evidence.py --self-test
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

CITATION_RE = re.compile(r"\*\*Runtime evidence:\*\*(.*)", re.IGNORECASE)
FIELD_RE = re.compile(r"^\s*-\s*([^:]{1,60}?):\s*(.*)$")
CAPTURED_HEADING_RE = re.compile(r"(?im)^##\s+Captured\s+output\s*$")
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


class GateError(Exception):
    """Structural/usage failure — maps to exit 2."""


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

def read_text(path):
    p = Path(path)
    if not p.is_file():
        raise GateError(f"file not found or not readable: {path}")
    return p.read_text(encoding="utf-8", errors="replace")


def is_path_shaped(token):
    """A bare path-like token: allowed charset plus a dot-extension."""
    return bool(PATH_SHAPE_RE.match(token)) and bool(PATH_EXTENSION_RE.search(token))


def collect_citations(report_text):
    """Every path cited on a `**Runtime evidence:**` line, file-wide.

    Collection is file-wide and scoping happens capture-side (on each
    capture's own `- Milestone:` field), because `test-report.md`'s
    `#Task [N]:` headers are documented human-only -- inventing a machine
    header there would break Quinn's append-only format.
    """
    out = []
    for line in report_text.splitlines():
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
    """Return (fields dict keyed lowercase, captured_output str or None)."""
    m = CAPTURED_HEADING_RE.search(text)
    head = text[:m.start()] if m else text
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
    """(newest mtime or None, warnings) over the declared changed files."""
    warnings, newest = [], None
    for f in changed_files:
        p = Path(f)
        if not p.exists():
            warnings.append(f"declared changed file does not exist: {f}")
            continue
        mt = p.stat().st_mtime
        newest = mt if newest is None else max(newest, mt)
    return newest, warnings


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
        "openapi_url": None, "openapi_status": None, "openapi_reachable": None,
        "schema_compared": None, "schema_skipped_reason": None,
        "observed_scope": None, "declared_absent": [], "observed_undeclared": [],
        "problems": [],
    }

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

    text = resolved.read_text(encoding="utf-8", errors="replace")
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
# CLI
# ---------------------------------------------------------------------------

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
    p.add_argument("--min-captures", type=int, default=1)
    p.add_argument("--require-openapi-reachable", action="store_true")
    p.add_argument("--openapi-doc")
    p.add_argument("--openapi-route")
    p.add_argument("--openapi-method")
    p.add_argument("--self-test", action="store_true")
    return p


def main(argv):
    args = build_parser().parse_args(argv)

    if args.self_test:
        return run_self_test()

    missing = [n for n, v in (("--report", args.report),
                              ("--milestone", args.milestone)) if not v]
    if missing:
        print(json.dumps({"result": "ERROR",
                           "error": f"missing required argument(s): {', '.join(missing)}"}))
        return 2

    try:
        report = build_report(args)
    except GateError as exc:
        print(json.dumps({"result": "ERROR", "error": str(exc)}))
        return 2

    print(json.dumps(report, indent=2))
    return 0 if report["result"] == "PASS" else 1


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

def run_self_test():
    import shutil
    import tempfile
    import unittest

    ENVELOPE = '{"statusCode":200,"isSuccess":true,"data":{"id":1},' \
               '"dataContext":null,"notifications":[]}'
    BARE = '{"id":1,"total":9}'

    def capture(milestone="M3 — Order envelope", transport="out-of-process HTTP",
                probe="curl -sS -i http://localhost:5142/api/orders",
                body=ENVELOPE, status="200 OK", base_url="http://localhost:5142",
                surface="api", extra=(), captured_section=True):
        head = [
            "# Runtime capture: POST /api/orders", "",
            f"- Milestone: {milestone}",
            f"- Surface: {surface}",
            f"- Transport: {transport}",
            f"- Base URL: {base_url}",
            f"- Probe command: `{probe}`",
            "- Captured: 2026-08-12T14:03:11Z",
            "- Exit code: 0",
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

        def _write(self, name="m3-orders.md", **kw):
            p = self.impl / "evidence" / "runtime" / name
            p.write_text(capture(**kw), encoding="utf-8")
            self._order(self.changed, p)
            return f"evidence/runtime/{name}"

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

        # ---- CLI ----

        def test_usage_error_exits_2(self):
            self.assertEqual(main(["--milestone", "M3"]), 2)
            self.assertEqual(main(["--report", str(self.report)]), 2)

    suite = unittest.defaultTestLoader.loadTestsFromTestCase(Tests)
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
