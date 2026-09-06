#!/usr/bin/env python3
"""Mechanical API-contract-evolution gate: diff two OpenAPI documents.

Exit 0 only when every difference between `--base` and `--head` is additive.
Used by `api-contract-evolution/SKILL.md` (Verification), `bgpdd-build`'s
commit-gate ladder for an `[API]` milestone, and `bgpdd-shipping` Step 3.

The claim "this change is backwards compatible" is exactly the claim nobody
re-derives at the moment they most want to merge. This turns it into a
command with an exit code.

Usage:
    python check_openapi_diff.py --base <openapi.json|yaml> \
        --head <openapi.json|yaml> [--allow-breaking "<reason>"] \
        [--milestone "<title>"] [--ledger <path>]
    python check_openapi_diff.py --self-test

Pure standard library. JSON is always readable; YAML is read only when it is
the JSON-compatible block subset the minimal loader below understands --
anchors, aliases, merge keys, tags, block scalars, flow collections and
multi-document streams are refused with exit 2 rather than guessed at. No
YAML library is vendored.
"""
import argparse
import hashlib
import json
import re
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

HTTP_METHODS = ("get", "put", "post", "delete", "options", "head", "patch",
                "trace")

# Depth cap on the schema walk. `$ref` is resolved ONE level (a resolved
# schema's own `$ref`s are left alone), so a self-referential component cannot
# recurse forever -- but a deeply nested inline schema still can, and a
# contract diff that walks 9 levels down is reporting noise either way.
MAX_SCHEMA_DEPTH = 8

BREAKING_KINDS = (
    "path_removed",
    "operation_removed",
    "response_status_removed",
    "response_field_removed",
    "type_changed",
    "required_request_field_added",
    "enum_narrowed",
)


class GateError(Exception):
    """Structural/usage failure — maps to exit 2."""


class ParseError(Exception):
    """A YAML construct the minimal loader will not guess at."""


# --------------------------------------------------------------------------
# Ledger helpers. Byte-identical block in every gate in this family and in
# check_ledger.py, which verifies the chain (family convention: one file each,
# no shared module).
# --------------------------------------------------------------------------
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

    `--allow-breaking` rides in `extra`: the CLI cannot judge whether the
    reason is a real one, but with a ledger the waiver is durable and
    attributable rather than a flag nobody can see afterwards -- the same
    posture as `update_state.py --resolve-blocker`.
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


# --------------------------------------------------------------------------
# Document loading: JSON always, the JSON-compatible YAML subset on request.
# --------------------------------------------------------------------------
_KEY_START = re.compile(r"""^(?:"[^"]*"|'[^']*'|[^:#\s][^:#]*?)\s*:(?:\s|$)""")
_INT = re.compile(r"^[+-]?\d+$")
_FLOAT = re.compile(r"^[+-]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][+-]?\d+)?$")


def strip_comment(line):
    """Drop a trailing `#` comment that is outside quotes."""
    out = []
    quote = None
    prev = ""
    for ch in line:
        if quote:
            out.append(ch)
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
            out.append(ch)
        elif ch == "#" and (prev == "" or prev.isspace()):
            break
        else:
            out.append(ch)
        prev = ch
    return "".join(out).rstrip()


def yaml_scalar(text):
    """A plain YAML scalar as a Python value. Quoted strings stay strings."""
    text = text.strip()
    if len(text) >= 2 and text[0] == '"' and text[-1] == '"':
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text[1:-1]
    if len(text) >= 2 and text[0] == "'" and text[-1] == "'":
        return text[1:-1].replace("''", "'")
    if text in ("", "~", "null", "Null", "NULL"):
        return None
    if text in ("true", "True", "TRUE"):
        return True
    if text in ("false", "False", "FALSE"):
        return False
    if text == "[]":
        return []
    if text == "{}":
        return {}
    if _INT.match(text):
        return int(text)
    if _FLOAT.match(text):
        return float(text)
    return text


def split_key(content):
    """`key: value` -> (key, value_text). Raises ParseError when there is no
    key separator (a colon followed by a space or end of line)."""
    if content[0] in "\"'":
        quote = content[0]
        end = content.find(quote, 1)
        if end == -1:
            raise ParseError("unterminated quoted key")
        rest = content[end + 1:].lstrip()
        if not rest.startswith(":"):
            raise ParseError("quoted key is not followed by ':'")
        return content[1:end], rest[1:].strip()
    idx = 0
    while True:
        idx = content.find(":", idx)
        if idx == -1:
            raise ParseError(f"not a mapping entry: {content!r}")
        after = content[idx + 1:]
        if after == "" or after[0].isspace():
            return content[:idx].strip(), after.strip()
        idx += 1


def _reject_value(value):
    """Refuse the YAML constructs the minimal loader will not guess at."""
    if not value:
        return
    first = value[0]
    if first in "&*!":
        raise ParseError("anchors, aliases and tags are not supported")
    if first in "|>":
        raise ParseError("block scalars are not supported")
    if first in "{[" and value not in ("{}", "[]"):
        raise ParseError("flow collections are not supported")


def _tokenize(text):
    """(indent, content) per significant line, with `- x: y` items expanded
    into a bare `-` plus the mapping line at its real column."""
    tokens = []
    seen_doc_start = False
    for raw in text.splitlines():
        line = raw.replace("\t", "    ") if raw[:len(raw) - len(raw.lstrip())] \
            .find("\t") >= 0 else raw
        stripped = strip_comment(line)
        if not stripped.strip():
            continue
        content = stripped.strip()
        if content in ("---", "..."):
            if seen_doc_start:
                raise ParseError("multi-document streams are not supported")
            seen_doc_start = True
            continue
        indent = len(stripped) - len(stripped.lstrip())
        if content.startswith("? "):
            raise ParseError("explicit complex keys are not supported")
        if content.startswith("<<"):
            raise ParseError("merge keys are not supported")
        if content == "-" or content.startswith("- "):
            body = content[1:].lstrip()
            body_col = indent + (len(content) - len(body))
            if body and _KEY_START.match(body):
                tokens.append((indent, "-"))
                tokens.append((body_col, body))
                continue
        tokens.append((indent, content))
    return tokens


def _parse_block(tokens, i, indent):
    first = tokens[i][1]
    if first == "-" or first.startswith("- "):
        return _parse_sequence(tokens, i, indent)
    return _parse_mapping(tokens, i, indent)


def _parse_sequence(tokens, i, indent):
    items = []
    while i < len(tokens) and tokens[i][0] == indent and \
            (tokens[i][1] == "-" or tokens[i][1].startswith("- ")):
        content = tokens[i][1]
        body = content[1:].strip()
        if body == "":
            if i + 1 < len(tokens) and tokens[i + 1][0] > indent:
                value, i = _parse_block(tokens, i + 1, tokens[i + 1][0])
            else:
                value, i = None, i + 1
        else:
            _reject_value(body)
            value, i = yaml_scalar(body), i + 1
        items.append(value)
    return items, i


def _parse_mapping(tokens, i, indent):
    result = {}
    while i < len(tokens) and tokens[i][0] == indent:
        content = tokens[i][1]
        if content == "-" or content.startswith("- "):
            raise ParseError("a sequence item where a mapping key was expected")
        key, value_text = split_key(content)
        _reject_value(value_text)
        if value_text == "":
            if i + 1 < len(tokens) and tokens[i + 1][0] > indent:
                value, i = _parse_block(tokens, i + 1, tokens[i + 1][0])
            else:
                value, i = None, i + 1
        else:
            value, i = yaml_scalar(value_text), i + 1
        result[yaml_scalar(key) if key[:1] in "\"'" else key] = value
        if i < len(tokens) and tokens[i][0] > indent:
            raise ParseError(f"unexpected indent at {tokens[i][1]!r}")
    return result, i


def parse_minimal_yaml(text):
    """The JSON-compatible block subset of YAML, or ParseError."""
    tokens = _tokenize(text)
    if not tokens:
        return {}
    base_indent = tokens[0][0]
    value, i = _parse_block(tokens, 0, base_indent)
    if i < len(tokens):
        raise ParseError(f"unexpected indent at {tokens[i][1]!r}")
    return value


def load_document(path, label):
    p = Path(path)
    if not p.is_file():
        raise GateError(f"{label} contract document not found: {path}")
    try:
        text = p.read_text(encoding="utf-8-sig", errors="replace")
    except OSError as exc:
        raise GateError(f"{label} contract document unreadable: {exc}")
    suffix = p.suffix.lower()
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as exc:
        if suffix == ".json":
            raise GateError(f"{label} document is not valid JSON: {exc}")
        try:
            doc = parse_minimal_yaml(text)
        except ParseError as parse_exc:
            raise GateError(
                f"{label} document is YAML the minimal loader will not guess "
                f"at ({parse_exc}). This gate reads JSON always and only the "
                f"JSON-compatible block subset of YAML; no YAML library is "
                f"vendored. Convert the document to JSON (or to plain block "
                f"YAML) and re-run.")
    if not isinstance(doc, dict):
        raise GateError(f"{label} document is not a mapping at the top level")
    return doc


# --------------------------------------------------------------------------
# Schema walking
# --------------------------------------------------------------------------
def deref(doc, ref):
    """Resolve a local `#/...` JSON pointer, or None."""
    if not isinstance(ref, str) or not ref.startswith("#/"):
        return None
    node = doc
    for part in ref[2:].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def resolve(schema, doc):
    """One level of `$ref` resolution (`#/components/schemas/X` and any other
    local pointer). A resolved schema's OWN `$ref`s are deliberately left
    alone -- one level is what makes a cycle terminate without a seen-set."""
    if isinstance(schema, dict) and isinstance(schema.get("$ref"), str):
        target = deref(doc, schema["$ref"])
        if isinstance(target, dict):
            return target
    return schema


def flatten(schema, doc, prefix="$", depth=0, out=None):
    """`{json-path: {type, enum, required}}` for one schema.

    `required` is None on the root and on array element schemas -- only an
    object's own `required` list can say whether a named property is required.
    """
    if out is None:
        out = {}
    s = resolve(schema, doc)
    if not isinstance(s, dict):
        return out
    enum = s.get("enum")
    out[prefix] = {
        "type": s.get("type"),
        "enum": tuple(enum) if isinstance(enum, list) else None,
        "required": None,
    }
    if depth >= MAX_SCHEMA_DEPTH:
        return out
    members = [s]
    all_of = s.get("allOf")
    if isinstance(all_of, list):
        members += [resolve(m, doc) for m in all_of if isinstance(m, dict)]
    for member in members:
        if not isinstance(member, dict):
            continue
        props = member.get("properties")
        if isinstance(props, dict):
            required = set(member.get("required") or [])
            for name, sub in props.items():
                child = f"{prefix}.{name}"
                flatten(sub, doc, child, depth + 1, out)
                if child in out:
                    out[child]["required"] = name in required
        items = member.get("items")
        if isinstance(items, dict):
            flatten(items, doc, f"{prefix}[]", depth + 1, out)
    return out


def operations(doc):
    """`{(path, METHOD): operation}` over the document's `paths` object."""
    result = {}
    paths = doc.get("paths")
    if not isinstance(paths, dict):
        return result
    for path, item in paths.items():
        if not isinstance(item, dict):
            continue
        shared = item.get("parameters") if isinstance(
            item.get("parameters"), list) else []
        for method in HTTP_METHODS:
            op = item.get(method)
            if isinstance(op, dict):
                merged = dict(op)
                merged["__shared_parameters__"] = shared
                result[(path, method.upper())] = merged
    return result


def response_schemas(op):
    """`{(status, media): schema}` for one operation's responses."""
    result = {}
    responses = op.get("responses")
    if not isinstance(responses, dict):
        return result
    for status, response in responses.items():
        if not isinstance(response, dict):
            continue
        content = response.get("content")
        if not isinstance(content, dict):
            result[(str(status), None)] = {}
            continue
        for media, body in content.items():
            if isinstance(body, dict) and isinstance(body.get("schema"), dict):
                result[(str(status), media)] = body["schema"]
            else:
                result[(str(status), media)] = {}
    return result


def request_schemas(op):
    """`{media: schema}` for one operation's request body."""
    result = {}
    body = op.get("requestBody")
    if not isinstance(body, dict):
        return result
    content = body.get("content")
    if not isinstance(content, dict):
        return result
    for media, entry in content.items():
        if isinstance(entry, dict) and isinstance(entry.get("schema"), dict):
            result[media] = entry["schema"]
    return result


def parameters(op, doc):
    """`{(name, in): parameter}` for one operation, path-level params merged
    in first so an operation-level entry of the same (name, in) wins."""
    result = {}
    for source in (op.get("__shared_parameters__") or [], op.get("parameters")
                   if isinstance(op.get("parameters"), list) else []):
        for entry in source:
            param = resolve(entry, doc) if isinstance(entry, dict) else None
            if isinstance(param, dict) and param.get("name"):
                result[(param["name"], param.get("in"))] = param
    return result


def param_facets(param, doc):
    """(type, enum) for a parameter, from its `schema` or its inline fields."""
    schema = param.get("schema")
    schema = resolve(schema, doc) if isinstance(schema, dict) else {}
    if not isinstance(schema, dict):
        schema = {}
    enum = schema.get("enum")
    if enum is None:
        enum = param.get("enum")
    return (schema.get("type") or param.get("type"),
            tuple(enum) if isinstance(enum, list) else None)


# --------------------------------------------------------------------------
# The diff
# --------------------------------------------------------------------------
def compare_enum(base_enum, head_enum):
    """'narrowed' | 'widened' | None for one pair of enum tuples."""
    if base_enum is None and head_enum is None:
        return None
    if base_enum is None:
        # Any value was legal; now a fixed set is. That is a narrowing.
        return "narrowed"
    if head_enum is None:
        return "widened"
    base_set, head_set = set(base_enum), set(head_enum)
    if head_set < base_set:
        return "narrowed"
    if base_set < head_set:
        return "widened"
    if base_set - head_set:
        # Values both removed and added: the removal is what breaks a caller.
        return "narrowed"
    return None


def diff_documents(base, head):
    """(breaking, additive) — two lists of `{kind, path, detail}`."""
    breaking = []
    additive = []

    def brk(kind, path, detail):
        breaking.append({"kind": kind, "path": path, "detail": detail})

    def add(kind, path, detail):
        additive.append({"kind": kind, "path": path, "detail": detail})

    base_paths = base.get("paths") if isinstance(base.get("paths"), dict) else {}
    head_paths = head.get("paths") if isinstance(head.get("paths"), dict) else {}
    for path in sorted(set(base_paths) - set(head_paths)):
        brk("path_removed", path, "the path is absent from the head document")
    for path in sorted(set(head_paths) - set(base_paths)):
        add("path_added", path, "a new path")

    base_ops, head_ops = operations(base), operations(head)
    shared_paths = set(base_paths) & set(head_paths)
    for key in sorted(set(base_ops) - set(head_ops)):
        if key[0] in shared_paths:
            brk("operation_removed", f"{key[1]} {key[0]}",
                "the operation is absent from the head document")
    for key in sorted(set(head_ops) - set(base_ops)):
        if key[0] in shared_paths:
            add("operation_added", f"{key[1]} {key[0]}", "a new operation")

    for key in sorted(set(base_ops) & set(head_ops)):
        label = f"{key[1]} {key[0]}"
        base_op, head_op = base_ops[key], head_ops[key]
        _diff_responses(base, head, base_op, head_op, label, brk, add)
        _diff_request_body(base, head, base_op, head_op, label, brk, add)
        _diff_parameters(base, head, base_op, head_op, label, brk, add)

    return breaking, additive


def _diff_responses(base, head, base_op, head_op, label, brk, add):
    base_r, head_r = response_schemas(base_op), response_schemas(head_op)
    base_status = {k[0] for k in base_r}
    head_status = {k[0] for k in head_r}
    for status in sorted(base_status - head_status):
        brk("response_status_removed", f"{label} {status}",
            "the response status is absent from the head document")
    for status in sorted(head_status - base_status):
        add("response_status_added", f"{label} {status}",
            "a new response status")
    for key in sorted(set(base_r) & set(head_r)):
        status, media = key
        where = f"{label} {status}" + (f" {media}" if media else "")
        base_fields = flatten(base_r[key], base)
        head_fields = flatten(head_r[key], head)
        for name in sorted(set(base_fields) - set(head_fields)):
            brk("response_field_removed", f"{where} {name}",
                "the response property is absent from the head document "
                "(a rename shows here as a removal plus an addition)")
        for name in sorted(set(head_fields) - set(base_fields)):
            add("response_field_added", f"{where} {name}",
                "a new response property")
        for name in sorted(set(base_fields) & set(head_fields)):
            _diff_facets(base_fields[name], head_fields[name],
                         f"{where} {name}", brk, add)


def _diff_request_body(base, head, base_op, head_op, label, brk, add):
    base_body = base_op.get("requestBody") if isinstance(
        base_op.get("requestBody"), dict) else None
    head_body = head_op.get("requestBody") if isinstance(
        head_op.get("requestBody"), dict) else None
    if head_body is not None and head_body.get("required") is True and (
            base_body is None or base_body.get("required") is not True):
        brk("required_request_field_added", f"{label} requestBody",
            "the request body became required")
    base_s, head_s = request_schemas(base_op), request_schemas(head_op)
    for media in sorted(set(base_s) & set(head_s)):
        where = f"{label} requestBody {media}"
        base_fields = flatten(base_s[media], base)
        head_fields = flatten(head_s[media], head)
        for name in sorted(set(head_fields) - set(base_fields)):
            if head_fields[name]["required"]:
                brk("required_request_field_added", f"{where} {name}",
                    "a new REQUIRED request property")
            else:
                add("optional_request_field_added", f"{where} {name}",
                    "a new optional request property")
        for name in sorted(set(base_fields) & set(head_fields)):
            if head_fields[name]["required"] and not base_fields[name]["required"]:
                brk("required_request_field_added", f"{where} {name}",
                    "an existing request property became required")
            _diff_facets(base_fields[name], head_fields[name],
                         f"{where} {name}", brk, add)


def _diff_parameters(base, head, base_op, head_op, label, brk, add):
    base_p = parameters(base_op, base)
    head_p = parameters(head_op, head)
    for key in sorted(set(head_p) - set(base_p), key=lambda k: (k[0], k[1] or "")):
        where = f"{label} parameter {key[0]} (in: {key[1]})"
        if head_p[key].get("required") is True:
            brk("required_request_field_added", where,
                "a new REQUIRED parameter")
        else:
            add("parameter_added", where, "a new optional parameter")
    for key in sorted(set(base_p) & set(head_p), key=lambda k: (k[0], k[1] or "")):
        where = f"{label} parameter {key[0]} (in: {key[1]})"
        if head_p[key].get("required") is True and \
                base_p[key].get("required") is not True:
            brk("required_request_field_added", where,
                "an existing parameter became required")
        base_type, base_enum = param_facets(base_p[key], base)
        head_type, head_enum = param_facets(head_p[key], head)
        _diff_facets({"type": base_type, "enum": base_enum},
                     {"type": head_type, "enum": head_enum}, where, brk, add)


def _diff_facets(base_facet, head_facet, where, brk, add):
    if base_facet["type"] != head_facet["type"] and (
            base_facet["type"] is not None or head_facet["type"] is not None):
        brk("type_changed", where,
            f"{base_facet['type']!r} -> {head_facet['type']!r}")
    verdict = compare_enum(base_facet["enum"], head_facet["enum"])
    if verdict == "narrowed":
        removed = sorted(set(base_facet["enum"] or ()) -
                         set(head_facet["enum"] or ()), key=repr)
        detail = (f"values no longer accepted: {removed}" if removed
                  else "an enum was introduced where the base accepted any value")
        brk("enum_narrowed", where, detail)
    elif verdict == "widened":
        add("enum_widened", where, "the accepted value set grew")


def build_report(base_path, head_path, allow_breaking=None):
    base = load_document(base_path, "base")
    head = load_document(head_path, "head")
    breaking, additive = diff_documents(base, head)
    if breaking:
        result = "ALLOWED" if allow_breaking else "FAIL"
    else:
        result = "PASS"
    return {
        "base": str(base_path),
        "head": str(head_path),
        "result": result,
        "breaking": breaking,
        "additive": additive,
        "allowed_by": allow_breaking if breaking and allow_breaking else None,
        "error": None,
    }


def main(argv):
    parser = argparse.ArgumentParser(prog="check_openapi_diff.py")
    parser.add_argument("--base", help="the contract document as published")
    parser.add_argument("--head", help="the contract document as proposed")
    parser.add_argument("--allow-breaking", dest="allow_breaking",
                        help="waive a breaking diff with a written reason; an "
                             "empty or whitespace-only reason is exit 2")
    parser.add_argument("--milestone", help="scope recorded in the ledger")
    parser.add_argument("--ledger",
                        help="append one JSON record per run to this path")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)

    if args.self_test:
        return run_self_test()

    inputs = [p for p in (args.base, args.head) if p]

    def finish(code, verdict, extra=None):
        """One exit point: EVERY return path records a ledger line."""
        append_ledger(args.ledger, argv, args.milestone, inputs, verdict, code,
                      extra)
        return code

    def fail_usage(message):
        print(json.dumps({"base": args.base, "head": args.head,
                          "result": "ERROR", "breaking": [], "additive": [],
                          "allowed_by": None, "error": message}, indent=2))
        return finish(2, "ERROR")

    if not args.base or not args.head:
        return fail_usage("missing required arguments: --base and --head")
    if args.allow_breaking is not None and not args.allow_breaking.strip():
        return fail_usage(
            "--allow-breaking requires a non-empty reason: an unreasoned "
            "waiver is indistinguishable from an omission")

    try:
        report = build_report(args.base, args.head, args.allow_breaking)
    except GateError as exc:
        return fail_usage(str(exc))

    print(json.dumps(report, indent=2))
    if not report["breaking"]:
        return finish(0, "PASS")
    if report["allowed_by"]:
        return finish(0, "PASS",
                      {"allow_breaking_reason": report["allowed_by"],
                       "breaking_kinds": sorted({b["kind"]
                                                 for b in report["breaking"]})})
    return finish(1, "FAIL")


# --------------------------------------------------------------------------
# Self-test
# --------------------------------------------------------------------------
MINIMAL = {
    "openapi": "3.0.3",
    "info": {"title": "t", "version": "1.0.0"},
    "paths": {
        "/users": {
            "get": {
                "parameters": [
                    {"name": "page", "in": "query", "required": False,
                     "schema": {"type": "integer"}},
                ],
                "responses": {
                    "200": {"content": {"application/json": {"schema": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "name": {"type": "string"},
                        },
                    }}}},
                    "404": {"description": "missing"},
                },
            },
        },
    },
}


def run_self_test():
    import copy
    import shutil

    class OpenApiDiffTests(unittest.TestCase):
        def setUp(self):
            self.dir = Path(tempfile.mkdtemp())

        def tearDown(self):
            shutil.rmtree(self.dir, ignore_errors=True)

        def write(self, name, obj):
            path = self.dir / name
            if isinstance(obj, str):
                path.write_text(obj, encoding="utf-8")
            else:
                path.write_text(json.dumps(obj, indent=2), encoding="utf-8")
            return str(path)

        def diff(self, base, head, allow=None):
            return build_report(self.write("base.json", base),
                                self.write("head.json", head), allow)

        def kinds(self, report, bucket="breaking"):
            return sorted({e["kind"] for e in report[bucket]})

        # -- 1-3: the no-change and additive baselines --------------------
        def test_identical_documents_pass(self):
            report = self.diff(MINIMAL, copy.deepcopy(MINIMAL))
            self.assertEqual(report["result"], "PASS")
            self.assertEqual(report["breaking"], [])
            self.assertEqual(report["additive"], [])

        def test_added_optional_response_field_is_additive(self):
            head = copy.deepcopy(MINIMAL)
            (head["paths"]["/users"]["get"]["responses"]["200"]["content"]
             ["application/json"]["schema"]["properties"]["email"]) = {
                 "type": "string"}
            report = self.diff(MINIMAL, head)
            self.assertEqual(report["result"], "PASS")
            self.assertEqual(self.kinds(report, "additive"),
                             ["response_field_added"])

        def test_new_endpoint_is_additive(self):
            head = copy.deepcopy(MINIMAL)
            head["paths"]["/orders"] = {"get": {"responses": {"200": {}}}}
            report = self.diff(MINIMAL, head)
            self.assertEqual(report["result"], "PASS")
            self.assertEqual(self.kinds(report, "additive"), ["path_added"])

        def test_new_operation_on_an_existing_path_is_additive(self):
            head = copy.deepcopy(MINIMAL)
            head["paths"]["/users"]["post"] = {"responses": {"201": {}}}
            report = self.diff(MINIMAL, head)
            self.assertEqual(self.kinds(report, "additive"),
                             ["operation_added"])

        # -- 4-7: removals -------------------------------------------------
        def test_removed_path_is_breaking(self):
            head = copy.deepcopy(MINIMAL)
            del head["paths"]["/users"]
            report = self.diff(MINIMAL, head)
            self.assertEqual(report["result"], "FAIL")
            self.assertEqual(self.kinds(report), ["path_removed"])

        def test_removed_operation_is_breaking(self):
            head = copy.deepcopy(MINIMAL)
            head["paths"]["/users"] = {"post": {"responses": {"201": {}}}}
            report = self.diff(MINIMAL, head)
            self.assertIn("operation_removed", self.kinds(report))

        def test_removed_response_field_is_breaking(self):
            head = copy.deepcopy(MINIMAL)
            del (head["paths"]["/users"]["get"]["responses"]["200"]["content"]
                 ["application/json"]["schema"]["properties"]["name"])
            report = self.diff(MINIMAL, head)
            self.assertEqual(self.kinds(report), ["response_field_removed"])
            self.assertIn("$.name", report["breaking"][0]["path"])

        def test_removed_status_code_is_breaking(self):
            head = copy.deepcopy(MINIMAL)
            del head["paths"]["/users"]["get"]["responses"]["404"]
            report = self.diff(MINIMAL, head)
            self.assertEqual(self.kinds(report), ["response_status_removed"])

        def test_renamed_field_shows_as_a_removal_plus_an_addition(self):
            head = copy.deepcopy(MINIMAL)
            props = (head["paths"]["/users"]["get"]["responses"]["200"]
                     ["content"]["application/json"]["schema"]["properties"])
            props["fullName"] = props.pop("name")
            report = self.diff(MINIMAL, head)
            self.assertEqual(self.kinds(report), ["response_field_removed"])
            self.assertEqual(self.kinds(report, "additive"),
                             ["response_field_added"])

        # -- 8-10: type and enum -------------------------------------------
        def test_type_change_is_breaking(self):
            head = copy.deepcopy(MINIMAL)
            (head["paths"]["/users"]["get"]["responses"]["200"]["content"]
             ["application/json"]["schema"]["properties"]["id"]["type"]) = \
                "integer"
            report = self.diff(MINIMAL, head)
            self.assertEqual(self.kinds(report), ["type_changed"])
            self.assertIn("integer", report["breaking"][0]["detail"])

        def test_enum_narrowing_is_breaking(self):
            base = copy.deepcopy(MINIMAL)
            base["paths"]["/users"]["get"]["parameters"][0] = {
                "name": "sort", "in": "query",
                "schema": {"type": "string", "enum": ["asc", "desc", "none"]}}
            head = copy.deepcopy(base)
            head["paths"]["/users"]["get"]["parameters"][0]["schema"]["enum"] = \
                ["asc", "desc"]
            report = self.diff(base, head)
            self.assertEqual(self.kinds(report), ["enum_narrowed"])
            self.assertIn("none", report["breaking"][0]["detail"])

        def test_enum_widening_is_additive(self):
            base = copy.deepcopy(MINIMAL)
            base["paths"]["/users"]["get"]["parameters"][0] = {
                "name": "sort", "in": "query",
                "schema": {"type": "string", "enum": ["asc"]}}
            head = copy.deepcopy(base)
            head["paths"]["/users"]["get"]["parameters"][0]["schema"]["enum"] = \
                ["asc", "desc"]
            report = self.diff(base, head)
            self.assertEqual(report["result"], "PASS")
            self.assertEqual(self.kinds(report, "additive"), ["enum_widened"])

        def test_introducing_an_enum_where_any_value_was_legal_is_breaking(self):
            head = copy.deepcopy(MINIMAL)
            head["paths"]["/users"]["get"]["parameters"][0]["schema"]["enum"] = \
                [1, 2]
            report = self.diff(MINIMAL, head)
            self.assertEqual(self.kinds(report), ["enum_narrowed"])

        # -- 11-14: request side -------------------------------------------
        def test_new_required_request_property_is_breaking(self):
            base = copy.deepcopy(MINIMAL)
            base["paths"]["/users"]["post"] = {
                "requestBody": {"content": {"application/json": {"schema": {
                    "type": "object", "properties": {"a": {"type": "string"}}}}}},
                "responses": {"201": {}}}
            head = copy.deepcopy(base)
            schema = (head["paths"]["/users"]["post"]["requestBody"]["content"]
                      ["application/json"]["schema"])
            schema["properties"]["b"] = {"type": "string"}
            schema["required"] = ["b"]
            report = self.diff(base, head)
            self.assertEqual(self.kinds(report),
                             ["required_request_field_added"])

        def test_new_optional_request_property_is_additive(self):
            base = copy.deepcopy(MINIMAL)
            base["paths"]["/users"]["post"] = {
                "requestBody": {"content": {"application/json": {"schema": {
                    "type": "object", "properties": {"a": {"type": "string"}}}}}},
                "responses": {"201": {}}}
            head = copy.deepcopy(base)
            (head["paths"]["/users"]["post"]["requestBody"]["content"]
             ["application/json"]["schema"]["properties"]["b"]) = {
                 "type": "string"}
            report = self.diff(base, head)
            self.assertEqual(report["result"], "PASS")
            self.assertEqual(self.kinds(report, "additive"),
                             ["optional_request_field_added"])

        def test_existing_request_property_becoming_required_is_breaking(self):
            base = copy.deepcopy(MINIMAL)
            base["paths"]["/users"]["post"] = {
                "requestBody": {"content": {"application/json": {"schema": {
                    "type": "object", "properties": {"a": {"type": "string"}}}}}},
                "responses": {"201": {}}}
            head = copy.deepcopy(base)
            (head["paths"]["/users"]["post"]["requestBody"]["content"]
             ["application/json"]["schema"]["required"]) = ["a"]
            report = self.diff(base, head)
            self.assertEqual(self.kinds(report),
                             ["required_request_field_added"])

        def test_new_required_parameter_is_breaking(self):
            head = copy.deepcopy(MINIMAL)
            head["paths"]["/users"]["get"]["parameters"].append(
                {"name": "tenant", "in": "query", "required": True,
                 "schema": {"type": "string"}})
            report = self.diff(MINIMAL, head)
            self.assertEqual(self.kinds(report),
                             ["required_request_field_added"])
            self.assertIn("tenant", report["breaking"][0]["path"])

        def test_new_optional_parameter_is_additive(self):
            head = copy.deepcopy(MINIMAL)
            head["paths"]["/users"]["get"]["parameters"].append(
                {"name": "tenant", "in": "query",
                 "schema": {"type": "string"}})
            report = self.diff(MINIMAL, head)
            self.assertEqual(report["result"], "PASS")
            self.assertEqual(self.kinds(report, "additive"),
                             ["parameter_added"])

        def test_existing_parameter_becoming_required_is_breaking(self):
            head = copy.deepcopy(MINIMAL)
            head["paths"]["/users"]["get"]["parameters"][0]["required"] = True
            report = self.diff(MINIMAL, head)
            self.assertEqual(self.kinds(report),
                             ["required_request_field_added"])

        def test_request_body_becoming_required_is_breaking(self):
            base = copy.deepcopy(MINIMAL)
            base["paths"]["/users"]["post"] = {
                "requestBody": {"content": {"application/json": {"schema": {
                    "type": "object"}}}},
                "responses": {"201": {}}}
            head = copy.deepcopy(base)
            head["paths"]["/users"]["post"]["requestBody"]["required"] = True
            report = self.diff(base, head)
            self.assertEqual(self.kinds(report),
                             ["required_request_field_added"])

        # -- 15-17: $ref ----------------------------------------------------
        def test_ref_resolution_finds_a_removal_behind_a_component(self):
            base = {
                "openapi": "3.0.3", "info": {"title": "t", "version": "1"},
                "components": {"schemas": {"User": {
                    "type": "object",
                    "properties": {"id": {"type": "string"},
                                   "name": {"type": "string"}}}}},
                "paths": {"/users": {"get": {"responses": {"200": {"content": {
                    "application/json": {"schema": {
                        "$ref": "#/components/schemas/User"}}}}}}}}}
            head = copy.deepcopy(base)
            del head["components"]["schemas"]["User"]["properties"]["name"]
            report = self.diff(base, head)
            self.assertEqual(self.kinds(report), ["response_field_removed"])
            self.assertIn("$.name", report["breaking"][0]["path"])

        def test_ref_resolution_finds_a_type_change_behind_a_component(self):
            base = {
                "openapi": "3.0.3", "info": {"title": "t", "version": "1"},
                "components": {"schemas": {"User": {
                    "type": "object",
                    "properties": {"id": {"type": "string"}}}}},
                "paths": {"/users": {"get": {"responses": {"200": {"content": {
                    "application/json": {"schema": {
                        "$ref": "#/components/schemas/User"}}}}}}}}}
            head = copy.deepcopy(base)
            (head["components"]["schemas"]["User"]["properties"]["id"]
             ["type"]) = "integer"
            report = self.diff(base, head)
            self.assertEqual(self.kinds(report), ["type_changed"])

        def test_a_self_referential_component_terminates(self):
            doc = {
                "openapi": "3.0.3", "info": {"title": "t", "version": "1"},
                "components": {"schemas": {"Node": {
                    "type": "object",
                    "properties": {
                        "child": {"$ref": "#/components/schemas/Node"}}}}},
                "paths": {"/n": {"get": {"responses": {"200": {"content": {
                    "application/json": {"schema": {
                        "$ref": "#/components/schemas/Node"}}}}}}}}}
            report = self.diff(doc, copy.deepcopy(doc))
            self.assertEqual(report["result"], "PASS")

        def test_nested_object_property_removal_is_breaking(self):
            base = copy.deepcopy(MINIMAL)
            (base["paths"]["/users"]["get"]["responses"]["200"]["content"]
             ["application/json"]["schema"]["properties"]["meta"]) = {
                 "type": "object",
                 "properties": {"total": {"type": "integer"}}}
            head = copy.deepcopy(base)
            del (head["paths"]["/users"]["get"]["responses"]["200"]["content"]
                 ["application/json"]["schema"]["properties"]["meta"]
                 ["properties"]["total"])
            report = self.diff(base, head)
            self.assertEqual(self.kinds(report), ["response_field_removed"])
            self.assertIn("$.meta.total", report["breaking"][0]["path"])

        # -- 18-21: CLI surface ---------------------------------------------
        def test_allow_breaking_with_a_reason_exits_zero_and_records_it(self):
            head = copy.deepcopy(MINIMAL)
            del head["paths"]["/users"]
            ledger = self.dir / "gates.jsonl"
            code = main(["--base", self.write("b.json", MINIMAL),
                         "--head", self.write("h.json", head),
                         "--allow-breaking", "v2 cutover approved in plan.md",
                         "--ledger", str(ledger)])
            self.assertEqual(code, 0)
            record = json.loads(ledger.read_text(encoding="utf-8").strip())
            self.assertEqual(record["verdict"], "PASS")
            self.assertEqual(record["allow_breaking_reason"],
                             "v2 cutover approved in plan.md")
            self.assertEqual(record["breaking_kinds"], ["path_removed"])

        def test_allow_breaking_with_an_empty_reason_is_exit_two(self):
            head = copy.deepcopy(MINIMAL)
            del head["paths"]["/users"]
            code = main(["--base", self.write("b.json", MINIMAL),
                         "--head", self.write("h.json", head),
                         "--allow-breaking", ""])
            self.assertEqual(code, 2)

        def test_allow_breaking_with_a_whitespace_reason_is_exit_two(self):
            code = main(["--base", self.write("b.json", MINIMAL),
                         "--head", self.write("h.json", MINIMAL),
                         "--allow-breaking", "   "])
            self.assertEqual(code, 2)

        def test_missing_arguments_are_exit_two(self):
            self.assertEqual(main(["--base", self.write("b.json", MINIMAL)]), 2)

        def test_a_missing_document_is_exit_two(self):
            code = main(["--base", self.write("b.json", MINIMAL),
                         "--head", str(self.dir / "nope.json")])
            self.assertEqual(code, 2)

        def test_malformed_json_is_exit_two(self):
            code = main(["--base", self.write("b.json", "{ not json"),
                         "--head", self.write("h.json", MINIMAL)])
            self.assertEqual(code, 2)

        def test_exit_codes_zero_and_one(self):
            head = copy.deepcopy(MINIMAL)
            self.assertEqual(main(["--base", self.write("b.json", MINIMAL),
                                   "--head", self.write("h.json", head)]), 0)
            del head["paths"]["/users"]
            self.assertEqual(main(["--base", self.write("b.json", MINIMAL),
                                   "--head", self.write("h2.json", head)]), 1)

        # -- 22-25: the ledger and the YAML subset --------------------------
        def test_every_exit_path_writes_a_chained_ledger_record(self):
            ledger = self.dir / "gates.jsonl"
            head = copy.deepcopy(MINIMAL)
            del head["paths"]["/users"]
            main(["--base", self.write("b.json", MINIMAL), "--head",
                  self.write("h.json", MINIMAL), "--ledger", str(ledger)])
            main(["--base", self.write("b.json", MINIMAL), "--head",
                  self.write("h2.json", head), "--ledger", str(ledger)])
            main(["--base", self.write("b.json", MINIMAL), "--ledger",
                  str(ledger)])
            lines = [l for l in ledger.read_text(encoding="utf-8").splitlines()
                     if l.strip()]
            self.assertEqual(len(lines), 3)
            records = [json.loads(l) for l in lines]
            self.assertEqual([r["verdict"] for r in records],
                             ["PASS", "FAIL", "ERROR"])
            self.assertTrue(all(r["gate"] == "check_openapi_diff.py"
                                for r in records))
            self.assertEqual(records[0]["prev"], "genesis")
            for index in (1, 2):
                self.assertEqual(records[index]["prev"],
                                 ledger_line_hash(lines[index - 1].encode()))
            for record in records:
                self.assertEqual(record["self"], ledger_self_hash(record))

        def test_yaml_block_subset_parses(self):
            yaml = (
                "openapi: 3.0.3\n"
                "info:\n"
                "  title: t\n"
                "  version: '1.0.0'\n"
                "paths:\n"
                "  /users:\n"
                "    get:\n"
                "      parameters:\n"
                "        - name: page\n"
                "          in: query\n"
                "          required: false\n"
                "          schema:\n"
                "            type: integer\n"
                "      responses:\n"
                "        '200':\n"
                "          content:\n"
                "            application/json:\n"
                "              schema:\n"
                "                type: object\n"
                "                properties:\n"
                "                  id:\n"
                "                    type: string\n"
                "                  name:\n"
                "                    type: string\n"
                "        '404':\n"
                "          description: missing\n")
            base = self.write("base.yaml", yaml)
            head = self.write("head.yaml", yaml.replace(
                "                  name:\n                    type: string\n", ""))
            report = build_report(base, head)
            self.assertEqual(self.kinds(report), ["response_field_removed"])

        def test_yaml_the_loader_cannot_parse_is_exit_two(self):
            yaml = ("openapi: 3.0.3\n"
                    "defaults: &d\n"
                    "  type: string\n"
                    "paths: {}\n")
            code = main(["--base", self.write("b.yaml", yaml),
                         "--head", self.write("h.yaml", yaml)])
            self.assertEqual(code, 2)

        def test_yaml_block_scalar_is_refused(self):
            yaml = ("openapi: 3.0.3\n"
                    "info:\n"
                    "  description: |\n"
                    "    a long description\n"
                    "paths: {}\n")
            with self.assertRaises(GateError):
                load_document(self.write("b.yaml", yaml), "base")

        def test_a_json_document_named_yaml_still_loads(self):
            path = self.write("base.yaml", MINIMAL)
            self.assertEqual(load_document(path, "base")["openapi"], "3.0.3")

        def test_path_level_parameters_are_merged_into_each_operation(self):
            base = copy.deepcopy(MINIMAL)
            base["paths"]["/users"]["parameters"] = [
                {"name": "tenant", "in": "query",
                 "schema": {"type": "string"}}]
            head = copy.deepcopy(base)
            head["paths"]["/users"]["parameters"][0]["required"] = True
            report = self.diff(base, head)
            self.assertEqual(self.kinds(report),
                             ["required_request_field_added"])

        def test_allof_members_are_walked(self):
            base = {
                "openapi": "3.0.3", "info": {"title": "t", "version": "1"},
                "components": {"schemas": {"Base": {
                    "type": "object",
                    "properties": {"id": {"type": "string"}}}}},
                "paths": {"/u": {"get": {"responses": {"200": {"content": {
                    "application/json": {"schema": {"allOf": [
                        {"$ref": "#/components/schemas/Base"},
                        {"type": "object",
                         "properties": {"extra": {"type": "string"}}}]}}}}}}}}}
            head = copy.deepcopy(base)
            del head["components"]["schemas"]["Base"]["properties"]["id"]
            report = self.diff(base, head)
            self.assertEqual(self.kinds(report), ["response_field_removed"])

    suite = unittest.defaultTestLoader.loadTestsFromTestCase(OpenApiDiffTests)
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
