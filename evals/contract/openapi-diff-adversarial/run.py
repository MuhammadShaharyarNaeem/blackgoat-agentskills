#!/usr/bin/env python3
"""Zero-LLM adversarial eval: walks `check_openapi_diff.py` against a
fabricated base/head contract pair for every breaking class it claims to
detect, plus the additive baselines it must NOT flag, the waiver's two
refusals, and the ledger chain a later gate reads its verdict out of.

The gate ships its own `--self-test`, which proves each predicate in-process
against synthetic fixtures. What that cannot prove is the property the
pipelines actually depend on: that the gate, invoked as a SUBPROCESS the way
`build-gate-ladders.md` § 6b and `bgpdd-shipping` Step 3 invoke it, returns the
documented exit code AND names the documented `kind` on real files on disk,
and that the ledger line it writes is a link a hand edit breaks.
(Until 2.6.1 `check_openapi_diff.py` was absent from `check_ledger.py`'s
CHAINED_GATES -- a missing comma had glued its name onto `update_state.py`'s --
so nothing else in the tree asserted that its records chain. The list is fixed
and guarded now; these steps stay as the end-to-end half.)

Deliberately needs no `claude -p` -- every step is a subprocess call to a
deterministic stdlib-Python CLI against fixture files this script writes, so it
is safe to run unconfirmed and is exempt from the suite's runs=5 doctrine,
which exists to average out LLM variance. There is none here.

See README.md in this directory for what this proves and when to re-run it.

Usage:
    python run.py               # run, print, record nothing
    python run.py --record      # ... and append one record to results/results.jsonl

Exit 0 only if every step passes. Prints a PASS/FAIL line per step and a final
RESULT: line; on failure the detail line shows the raw JSON the tool produced.
The script builds its own temp directory and removes it unconditionally.

--record is OFF by default so an iteration loop on this file does not pollute the
run log, and `run-evals.ps1` passes it at the start of every confirmed contract
batch: the case is free, and until that landed it left no history at all.
"""
import argparse
import copy
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

# evals/contract/openapi-diff-adversarial/run.py -> plugin root is 3 levels up.
PLUGIN_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = PLUGIN_ROOT / "skills" / "pipeline-tools" / "scripts"

CHECK_DIFF = SCRIPTS / "check_openapi_diff.py"
CHECK_LEDGER = SCRIPTS / "check_ledger.py"

# The shared record writer lives in evals/, two levels up from this file. Shared,
# not copied into each case, because the record shape has to match the one
# run-evals.ps1 appends to the same file.
sys.path.insert(0, str(PLUGIN_ROOT / "evals"))
from eval_record import append_script_record  # noqa: E402

MILESTONE = "M4: Orders API [API]"

# The base contract. Deliberately exercises every surface the gate reads: a
# `$ref`ed component (so a removal can be hidden one level down), an inline
# enum on a parameter, a request body with a `required` list, two response
# statuses, and a nested object -- a fixture where every class had to be
# expressed on a DIFFERENT operation could not catch a cross-term regression.
BASE = {
    "openapi": "3.0.3",
    "info": {"title": "Orders", "version": "1.0.0"},
    "components": {
        "schemas": {
            "Order": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "total": {"type": "string"},
                    "customerName": {"type": "string"},
                    "meta": {
                        "type": "object",
                        "properties": {"createdAt": {"type": "string"}},
                    },
                },
            },
        },
    },
    "paths": {
        "/v1/orders": {
            "get": {
                "parameters": [
                    {"name": "status", "in": "query", "required": False,
                     "schema": {"type": "string",
                                "enum": ["pending", "active", "archived"]}},
                ],
                "responses": {
                    "200": {"content": {"application/json": {"schema": {
                        "$ref": "#/components/schemas/Order"}}}},
                    "409": {"description": "duplicate"},
                },
            },
            "post": {
                "requestBody": {"content": {"application/json": {"schema": {
                    "type": "object",
                    "properties": {"items": {"type": "string"}},
                    "required": ["items"],
                }}}},
                "responses": {"201": {"description": "created"}},
            },
        },
        "/v1/orders/{id}": {
            "get": {"responses": {"200": {"description": "one order"}}},
            "delete": {"responses": {"204": {"description": "gone"}}},
        },
    },
}

results = []


def record(name, ok, detail=""):
    print(f"{'PASS' if ok else 'FAIL'}  {name}")
    if not ok and detail:
        print(f"      {detail}")
    results.append((name, ok))


def run_gate(script, args, cwd):
    return subprocess.run([sys.executable, str(script)] + [str(a) for a in args],
                          cwd=str(cwd), capture_output=True, text=True)


def parse_json(proc, step_name):
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        record(step_name, False,
               f"stdout was not JSON: {proc.stdout[:400]!r} / "
               f"stderr {proc.stderr[:200]!r}")
        return None


def expect(step_name, proc, exit_code, predicate=None, why=""):
    """Assert the exit code, then a naming JSON field. An exit code alone can be
    right for the wrong reason -- this gate has three of them and seven kinds."""
    data = parse_json(proc, step_name)
    if data is None:
        return None
    ok = proc.returncode == exit_code
    detail = ""
    if not ok:
        detail = f"expected exit {exit_code}, got {proc.returncode}: {json.dumps(data)}"
    elif predicate is not None and not predicate(data):
        ok = False
        detail = f"exit {exit_code} as expected, but {why}: {json.dumps(data)}"
    record(step_name, ok, detail)
    return data


def kinds(data, bucket="breaking"):
    return sorted({entry["kind"] for entry in data.get(bucket) or []})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record", action="store_true",
                        help="append one flat record to evals/results/results.jsonl")
    args = parser.parse_args()

    started = time.time()
    tmp = Path(tempfile.mkdtemp(prefix="eval-openapi-diff-adversarial-"))
    try:
        run_suite(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    duration = round(time.time() - started, 2)

    print()
    failed = [n for n, ok in results if not ok]
    if failed:
        print(f"RESULT: FAIL ({len(failed)}/{len(results)} steps failed)")
    else:
        print(f"RESULT: PASS ({len(results)}/{len(results)} steps passed)")

    if args.record:
        detail = None
        if failed:
            detail = " | ".join(f"[FAIL] {name}" for name in failed)
        append_script_record(case="openapi-diff-adversarial", passed=(not failed),
                             failed_criterion=detail, duration_s=duration)

    return 1 if failed else 0


def run_suite(work):
    docs = work / "contracts"
    docs.mkdir(parents=True)
    ledger = work / "gates.jsonl"

    def write(name, doc):
        path = docs / name
        if isinstance(doc, str):
            path.write_text(doc, encoding="utf-8")
        else:
            path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
        return path

    base_path = write("base.json", BASE)

    def diff(name, head, extra=()):
        head_path = write(name, head)
        return run_gate(CHECK_DIFF,
                        ["--base", base_path, "--head", head_path,
                         "--milestone", MILESTONE, "--ledger", ledger] +
                        list(extra), work)

    def mutate(fn):
        head = copy.deepcopy(BASE)
        fn(head)
        return head

    observed = set()

    def seen(data):
        """Accumulate the kinds the gate ACTUALLY named, so step 15 is a
        roll-up over real output rather than a restatement of the list."""
        if data:
            observed.update(kinds(data))
        return data

    order_props = lambda d: d["components"]["schemas"]["Order"]["properties"]
    get_params = lambda d: d["paths"]["/v1/orders"]["get"]["parameters"]
    post_schema = lambda d: (d["paths"]["/v1/orders"]["post"]["requestBody"]
                             ["content"]["application/json"]["schema"])

    # --- 1. an identical document is not a change --------------------------
    expect("1. identical base and head -> exit 0 (PASS, nothing reported)",
           diff("identical.json", copy.deepcopy(BASE)), 0,
           lambda d: d.get("result") == "PASS" and not d["breaking"]
           and not d["additive"],
           "it reported a difference between a document and itself")

    # --- 2. an added optional response field is additive -------------------
    expect("2. added optional response field -> exit 0 (response_field_added)",
           diff("added-field.json",
                mutate(lambda d: order_props(d).update(
                    {"currency": {"type": "string"}}))), 0,
           lambda d: d.get("result") == "PASS" and not d["breaking"]
           and kinds(d, "additive") == ["response_field_added"],
           "the additive change was not classified as additive")

    # --- 3. a new endpoint is additive -------------------------------------
    expect("3. a new endpoint -> exit 0 (path_added)",
           diff("added-path.json",
                mutate(lambda d: d["paths"].update(
                    {"/v1/refunds": {"get": {"responses": {"200": {}}}}}))), 0,
           lambda d: not d["breaking"] and kinds(d, "additive") == ["path_added"],
           "a new endpoint was not classified as additive")

    # --- 4. a new OPTIONAL parameter is additive ---------------------------
    # The near-miss for step 9: same edit, `required` absent instead of true.
    expect("4. a new optional parameter -> exit 0 (parameter_added)",
           diff("added-param.json",
                mutate(lambda d: get_params(d).append(
                    {"name": "tenant", "in": "query",
                     "schema": {"type": "string"}}))), 0,
           lambda d: not d["breaking"]
           and kinds(d, "additive") == ["parameter_added"],
           "an optional parameter was treated as a required one")

    # --- 5. removed path ----------------------------------------------------
    seen(expect("5. removed path -> exit 1 (path_removed)",
           diff("removed-path.json",
                mutate(lambda d: d["paths"].pop("/v1/orders/{id}"))), 1,
           lambda d: d.get("result") == "FAIL" and kinds(d) == ["path_removed"],
           "it did not name path_removed alone"))

    # --- 6. removed operation on a surviving path ---------------------------
    seen(expect("6. removed method on a surviving path -> exit 1 (operation_removed)",
           diff("removed-op.json",
                mutate(lambda d: d["paths"]["/v1/orders/{id}"].pop("delete"))), 1,
           lambda d: kinds(d) == ["operation_removed"]
           and d["breaking"][0]["path"] == "DELETE /v1/orders/{id}",
           "it did not name operation_removed on DELETE /v1/orders/{id}"))

    # --- 7. removed response field, BEHIND A $ref ---------------------------
    # The component is referenced, not inlined: a gate that does not resolve
    # `$ref` sees two identical `{"$ref": ...}` dicts and reports nothing.
    seen(expect("7. field removed behind a $ref -> exit 1 (response_field_removed)",
           diff("removed-field.json",
                mutate(lambda d: order_props(d).pop("customerName"))), 1,
           lambda d: kinds(d) == ["response_field_removed"]
           and "$.customerName" in d["breaking"][0]["path"],
           "the removal hidden behind the $ref was not resolved and named"))

    # --- 8. a rename shows as a removal PLUS an addition --------------------
    def rename(d):
        props = order_props(d)
        props["customer"] = props.pop("customerName")

    seen(expect("8. renamed field -> exit 1 (removal + additive addition, not paired)",
           diff("renamed-field.json", mutate(rename)), 1,
           lambda d: kinds(d) == ["response_field_removed"]
           and kinds(d, "additive") == ["response_field_added"]
           and "$.customerName" in d["breaking"][0]["path"],
           "a rename was not reported as a removal plus an addition"))

    # --- 9. type change -----------------------------------------------------
    seen(expect("9. type change -> exit 1 (type_changed, both types in the detail)",
           diff("type-change.json",
                mutate(lambda d: order_props(d)["total"].update(
                    {"type": "number"}))), 1,
           lambda d: kinds(d) == ["type_changed"]
           and "'string'" in d["breaking"][0]["detail"]
           and "'number'" in d["breaking"][0]["detail"],
           "it did not name type_changed with both types"))

    # --- 10. a new REQUIRED request property --------------------------------
    def add_required(d):
        schema = post_schema(d)
        schema["properties"]["tenantId"] = {"type": "string"}
        schema["required"] = ["items", "tenantId"]

    seen(expect("10. new required request property -> exit 1 "
           "(required_request_field_added)",
           diff("required-body.json", mutate(add_required)), 1,
           lambda d: kinds(d) == ["required_request_field_added"],
           "it did not name required_request_field_added"))

    # --- 11. a new REQUIRED parameter (near-miss of step 4) -----------------
    seen(expect("11. new required parameter -> exit 1 (required_request_field_added)",
           diff("required-param.json",
                mutate(lambda d: get_params(d).append(
                    {"name": "tenant", "in": "query", "required": True,
                     "schema": {"type": "string"}}))), 1,
           lambda d: kinds(d) == ["required_request_field_added"]
           and "tenant" in d["breaking"][0]["path"],
           "it did not name the required parameter"))

    # --- 12. enum narrowing -------------------------------------------------
    seen(expect("12. enum narrowing -> exit 1 (enum_narrowed, names the lost value)",
           diff("enum-narrow.json",
                mutate(lambda d: get_params(d)[0]["schema"].update(
                    {"enum": ["pending", "active"]}))), 1,
           lambda d: kinds(d) == ["enum_narrowed"]
           and "archived" in d["breaking"][0]["detail"],
           "it did not name enum_narrowed and the value that was dropped"))

    # --- 13. enum WIDENING is the additive near-miss ------------------------
    expect("13. enum widening -> exit 0 (enum_widened)",
           diff("enum-widen.json",
                mutate(lambda d: get_params(d)[0]["schema"].update(
                    {"enum": ["pending", "active", "archived", "void"]}))), 0,
           lambda d: not d["breaking"]
           and kinds(d, "additive") == ["enum_widened"],
           "a widened enum was treated as a narrowing")

    # --- 14. removed status code --------------------------------------------
    seen(expect("14. removed status code -> exit 1 (response_status_removed)",
           diff("removed-status.json",
                mutate(lambda d: d["paths"]["/v1/orders"]["get"]["responses"]
                       .pop("409"))), 1,
           lambda d: kinds(d) == ["response_status_removed"]
           and "409" in d["breaking"][0]["path"],
           "it did not name response_status_removed for 409"))

    # --- 15. every mechanically-detectable breaking class was exercised ---
    # A roll-up over what steps 5-14 actually reported. `changed status
    # semantics` is deliberately absent -- the skill states no diff can see
    # it, and a case asserting otherwise would assert a capability the
    # contract disclaims.
    EXPECTED_KINDS = {"path_removed", "operation_removed",
                      "response_field_removed", "type_changed",
                      "required_request_field_added", "enum_narrowed",
                      "response_status_removed"}
    record("15. all seven mechanically-detectable breaking kinds were named "
           "by the gate itself",
           observed == EXPECTED_KINDS,
           f"the gate named {sorted(observed)}; the contract documents "
           f"{sorted(EXPECTED_KINDS)}")

    # --- 16. `--allow-breaking ""` is exit 2, not a silent waiver ------------
    expect('16. --allow-breaking "" -> exit 2 (an unreasoned waiver is refused)',
           diff("waive-empty.json",
                mutate(lambda d: d["paths"].pop("/v1/orders/{id}")),
                ["--allow-breaking", ""]), 2,
           lambda d: d.get("result") == "ERROR" and not d["breaking"]
           and "reason" in (d.get("error") or ""),
           "an empty waiver was not refused as a usage error")

    expect('17. --allow-breaking "   " -> exit 2 (whitespace is not a reason)',
           diff("waive-blank.json",
                mutate(lambda d: d["paths"].pop("/v1/orders/{id}")),
                ["--allow-breaking", "   "]), 2,
           lambda d: d.get("result") == "ERROR",
           "a whitespace-only waiver was accepted as a reason")

    # --- 18. a reasoned waiver passes, and the reason is in the ledger -------
    reason = "PLAN-214 - v2 major; /v1/orders/{id} sunset 2026-07-15"
    data = expect("18. --allow-breaking with a reason -> exit 0 (ALLOWED, "
                  "breaking still listed)",
                  diff("waive-ok.json",
                       mutate(lambda d: d["paths"].pop("/v1/orders/{id}")),
                       ["--allow-breaking", reason]), 0,
                  lambda d: d.get("result") == "ALLOWED"
                  and d.get("allowed_by") == reason
                  and kinds(d) == ["path_removed"],
                  "the waiver did not report ALLOWED with the breaking array intact")

    lines = [l for l in ledger.read_text(encoding="utf-8").splitlines() if l.strip()]
    waived = json.loads(lines[-1])
    record("19. the waiver's reason is durable in the ledger record",
           waived.get("verdict") == "PASS"
           and waived.get("allow_breaking_reason") == reason
           and waived.get("breaking_kinds") == ["path_removed"]
           and waived.get("milestone") == MILESTONE,
           f"the record does not carry the reason: {json.dumps(waived)}")

    # --- 20. every run so far wrote exactly one chained record --------------
    record("20. one ledger record per run, on every exit path (0, 1 and 2)",
           len(lines) == 17 and {json.loads(l)["verdict"] for l in lines} ==
           {"PASS", "FAIL", "ERROR"},
           f"expected 17 records covering all three verdicts, got {len(lines)}: "
           f"{sorted({json.loads(l)['verdict'] for l in lines})}")

    # --- 21. the ledger this gate wrote verifies as an intact chain ---------
    proc = run_gate(CHECK_LEDGER, ["--ledger", ledger], work)
    expect("21. check_ledger.py on the ledger this gate wrote -> exit 0 (intact)",
           proc, 0,
           lambda d: d.get("pass") is True and d.get("legacy_records") == 0
           and d.get("chained_records") == len(lines),
           "the records this gate wrote did not verify as a chain")

    # --- 22. a hand-edited verdict breaks the chain -------------------------
    # The forgery the chain exists to catch: flip a recorded FAIL to a PASS so a
    # downstream `--require-ledger-gates check_openapi_diff.py` reads a green.
    forged = []
    edited_index = None
    for index, line in enumerate(lines):
        record_obj = json.loads(line)
        if record_obj["verdict"] == "FAIL" and edited_index is None:
            record_obj["verdict"] = "PASS"
            record_obj["exit"] = 0
            edited_index = index
            forged.append(json.dumps(record_obj))
        else:
            forged.append(line)
    tampered = work / "tampered.jsonl"
    tampered.write_text("\n".join(forged) + "\n", encoding="utf-8")
    proc = run_gate(CHECK_LEDGER, ["--ledger", tampered], work)
    expect("22. a FAIL hand-edited to PASS -> check_ledger.py exit 1 "
           "(self-mismatch on that line)",
           proc, 1,
           lambda d: d.get("pass") is False
           and (d.get("problem") or {}).get("reason") == "self-mismatch"
           and (d.get("problem") or {}).get("line") == edited_index + 1,
           "the edited verdict was not caught on its own line")

    # --- 23. a deleted record breaks the FOLLOWING line's prev --------------
    dropped = lines[:1] + lines[2:]
    thinned = work / "thinned.jsonl"
    thinned.write_text("\n".join(dropped) + "\n", encoding="utf-8")
    proc = run_gate(CHECK_LEDGER, ["--ledger", thinned], work)
    expect("23. a removed record -> check_ledger.py exit 1 (prev-mismatch)",
           proc, 1,
           lambda d: d.get("pass") is False
           and (d.get("problem") or {}).get("reason") == "prev-mismatch",
           "removing a record did not break the following line's prev")

    # --- 24. the YAML subset, and the refusal outside it --------------------
    yaml_base = (
        "openapi: 3.0.3\n"
        "info:\n"
        "  title: Orders\n"
        "  version: '1.0.0'\n"
        "paths:\n"
        "  /v1/orders:\n"
        "    get:\n"
        "      responses:\n"
        "        '200':\n"
        "          content:\n"
        "            application/json:\n"
        "              schema:\n"
        "                type: object\n"
        "                properties:\n"
        "                  id:\n"
        "                    type: string\n"
        "                  customerName:\n"
        "                    type: string\n")
    yaml_head = yaml_base.replace(
        "                  customerName:\n                    type: string\n", "")
    yb = write("base.yaml", yaml_base)
    yh = write("head.yaml", yaml_head)
    proc = run_gate(CHECK_DIFF, ["--base", yb, "--head", yh,
                                 "--milestone", MILESTONE], work)
    expect("24. block-YAML documents in the supported subset -> exit 1 "
           "(response_field_removed)", proc, 1,
           lambda d: kinds(d) == ["response_field_removed"]
           and "$.customerName" in d["breaking"][0]["path"],
           "the YAML subset did not parse into the same finding as JSON")

    anchored = write("anchored.yaml",
                     "openapi: 3.0.3\ndefaults: &d\n  type: string\npaths: {}\n")
    proc = run_gate(CHECK_DIFF, ["--base", anchored, "--head", anchored,
                                 "--milestone", MILESTONE], work)
    expect("25. YAML with an anchor -> exit 2, naming the construct (never a "
           "guessed parse)", proc, 2,
           lambda d: d.get("result") == "ERROR"
           and "anchors" in (d.get("error") or ""),
           "an unsupported YAML construct was not refused by name")

    # --- 26 (2.6.1): a schema the walk cannot read is a REFUSAL -------------
    # The walk descends properties/items/allOf and not oneOf/anyOf/not, and
    # said nothing about that: a response wrapped in `oneOf` with a field
    # removed inside returned exit 0 PASS, breaking: [], no warning. A PASS
    # over a document the gate did not analyze is worse than a refusal.
    def wrapped(keyword, drop):
        doc = copy.deepcopy(BASE)
        inner = {"type": "object",
                 "properties": {"id": {"type": "string"},
                                "customerName": {"type": "string"}}}
        node = {"not": inner} if keyword == "not" else {keyword: [inner]}
        (doc["paths"]["/v1/orders"]["get"]["responses"]["200"]["content"]
         ["application/json"])["schema"] = node
        if drop:
            target = (node["not"] if keyword == "not" else node[keyword][0])
            del target["properties"]["customerName"]
        return doc

    def wrapped_pair(keyword, tag, extra=()):
        """Both documents wrapped, so the ONLY difference is inside the union.

        Diffing a wrapped head against the plain BASE would report the wrapper
        itself as a pile of removals, which is not the case under test.
        """
        b = write(f"{tag}-base.json", wrapped(keyword, False))
        h = write(f"{tag}-head.json", wrapped(keyword, True))
        return run_gate(CHECK_DIFF, ["--base", b, "--head", h,
                                     "--milestone", MILESTONE,
                                     "--ledger", ledger] + list(extra), work)

    proc = wrapped_pair("oneOf", "oneof")
    expect("26. a `oneOf`-wrapped removed field -> exit 2 (unanalyzable_schema), "
           "never PASS", proc, 2,
           lambda d: d.get("result") == "ERROR"
           and d.get("breaking") == []
           and len(d.get("unanalyzable") or []) == 1
           and d["unanalyzable"][0]["keyword"] == "oneOf"
           and "GET /v1/orders 200 application/json" in d["unanalyzable"][0]["where"]
           and "unanalyzable_schema" in (d.get("error") or ""),
           "the union-wrapped removal was not refused by name")

    for keyword, tag, label in (("anyOf", "anyof", "26b"), ("not", "not", "26c")):
        proc = wrapped_pair(keyword, tag)
        expect(f"{label}. a `{keyword}`-wrapped removed field -> exit 2 "
               "(unanalyzable_schema)", proc, 2,
               lambda d, k=keyword: d.get("result") == "ERROR"
               and d.get("breaking") == []
               and (d.get("unanalyzable") or [{}])[0].get("keyword") == k,
               f"{keyword} was not refused")

    # 26d: the waiver does not clear it. --allow-breaking waives a diff
    # somebody read, and there is no diff here to read.
    proc = wrapped_pair("oneOf", "oneof-waived",
                        ["--allow-breaking", "agreed with the client team"])
    expect("26d. --allow-breaking does NOT clear an unanalyzable schema -> exit 2",
           proc, 2,
           lambda d: d.get("result") == "ERROR" and d.get("allowed_by") is None,
           "a waiver cleared a schema the gate never analyzed")

    # 26e: the near-miss. allOf IS walked, so it must not be refused -- a rule
    # that refused every composition keyword would be a different bug.
    allof_doc = copy.deepcopy(BASE)
    (allof_doc["paths"]["/v1/orders"]["get"]["responses"]["200"]["content"]
     ["application/json"])["schema"] = {"allOf": [
         {"type": "object", "properties": {"id": {"type": "string"}}}]}
    allof_base = write("allof-base.json", allof_doc)
    allof_head_doc = copy.deepcopy(allof_doc)
    (allof_head_doc["paths"]["/v1/orders"]["get"]["responses"]["200"]["content"]
     ["application/json"]["schema"]["allOf"][0]["properties"]
     )["currency"] = {"type": "string"}
    allof_head = write("allof-head.json", allof_head_doc)
    proc = run_gate(CHECK_DIFF, ["--base", allof_base, "--head", allof_head,
                                 "--milestone", MILESTONE, "--ledger", ledger],
                    work)
    expect("26e. an `allOf` composition is still ANALYZED, not refused -> exit 0",
           proc, 0,
           lambda d: d.get("result") == "PASS" and d.get("unanalyzable") == []
           and kinds(d, "additive") == ["response_field_added"],
           "allOf was refused, or its additive change was missed")

    # --- 27 (2.6.1): nullable: true -> false on a response ------------------
    # Passed silently. The same component is nearly always the one accepted in
    # requests, so the flip breaks every caller that sends or round-trips null.
    nullable_base_doc = copy.deepcopy(BASE)
    nullable_base_doc["components"]["schemas"]["Order"]["properties"][
        "customerName"]["nullable"] = True
    nullable_base = write("nullable-base.json", nullable_base_doc)
    nullable_head_doc = copy.deepcopy(nullable_base_doc)
    nullable_head_doc["components"]["schemas"]["Order"]["properties"][
        "customerName"]["nullable"] = False
    nullable_head = write("nullable-head.json", nullable_head_doc)
    proc = run_gate(CHECK_DIFF, ["--base", nullable_base, "--head", nullable_head,
                                 "--milestone", MILESTONE, "--ledger", ledger],
                    work)
    expect("27. nullable true -> false on a response schema -> exit 1 "
           "(nullable_removed)", proc, 1,
           lambda d: kinds(d) == ["nullable_removed"]
           and "customerName" in d["breaking"][0]["path"],
           "the nullability narrowing was not reported as breaking")

    # 27b: the widening is additive AND warned -- a caller that never handled
    # null now has to, which is worth saying without gating on it.
    proc = run_gate(CHECK_DIFF, ["--base", nullable_head, "--head", nullable_base,
                                 "--milestone", MILESTONE, "--ledger", ledger],
                    work)
    expect("27b. nullable false -> true is additive, and warned -> exit 0",
           proc, 0,
           lambda d: d.get("result") == "PASS"
           and kinds(d, "additive") == ["nullable_widened"]
           and any("nullable" in w for w in (d.get("warnings") or [])),
           "the widening was not additive-with-a-warning")

    # 27c: unlike an unanalyzable schema, this one IS waivable -- it is a diff
    # somebody can read.
    proc = run_gate(CHECK_DIFF, ["--base", nullable_base, "--head", nullable_head,
                                 "--milestone", MILESTONE, "--ledger", ledger,
                                 "--allow-breaking", "no client ever sent null"],
                    work)
    expect("27c. nullable_removed is waivable -> exit 0 (ALLOWED)", proc, 0,
           lambda d: d.get("result") == "ALLOWED"
           and d.get("allowed_by") == "no client ever sent null",
           "the waiver did not clear a readable breaking diff")

    # --- 28 (2.6.1): every report carries a warnings list -------------------
    # There was no `warnings` key in the output at all, so a skipped branch and
    # an unresolvable $ref were indistinguishable from a clean compare.
    dangling = copy.deepcopy(BASE)
    (dangling["paths"]["/v1/orders"]["get"]["responses"]["200"]["content"]
     ["application/json"])["schema"] = {"$ref": "#/components/schemas/Missing"}
    dangling_path = write("dangling-ref.json", dangling)
    proc = run_gate(CHECK_DIFF, ["--base", dangling_path, "--head", dangling_path,
                                 "--milestone", MILESTONE, "--ledger", ledger],
                    work)
    expect("28. an unresolvable `$ref` is WARNED, not silently skipped -> exit 0",
           proc, 0,
           lambda d: d.get("result") == "PASS"
           and any("does not resolve" in w for w in (d.get("warnings") or [])),
           "a dangling $ref produced no warning")


if __name__ == "__main__":
    sys.exit(main())
