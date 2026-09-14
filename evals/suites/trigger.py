#!/usr/bin/env python3
"""`evals/run_suite.py --suite trigger` -- start/grade a `evals/trigger/cases.jsonl`
prompt on any runtime.

Judging mirrors `run-evals.ps1`'s `Invoke-TriggerJudge` (see evals/README.md
"Trigger judging"), but the observable proxy for "the model invoked skill X"
is different per runtime: `run-evals.ps1` reads a `Skill` tool_use block out
of a `claude -p --output-format stream-json` transcript, and no other
runtime this suite targets necessarily has that tool. Antigravity's own
graders (`evals/antigravity/case_common.py`) already establish the proxy
this repo uses for "this skill got read": a `view_file` of
`skills/<name>/SKILL.md`. This module reuses that signal for routing
instead of inventing a second one.

Three rules `extract_skills_invoked` enforces, found by a 2026-09-14
red-team of `trigger-28`/`trigger-29` (the `/bg-eval`-started `/bg` router
cases -- see `rt_trigger.py`'s repro):

1. **Window-bounded.** Only a `view_file` whose OWN `created_at` falls in
   `[window_start, window_end]` counts. Before this, a step from BEFORE
   `window_start` -- e.g. the Orchestrator reading `skills/bg-eval/SKILL.md`
   itself while parsing `/bg-eval trigger <case>`, well before `start` even
   ran -- could win the whole verdict.
2. **Walks `transcripts["all"]`, not `common.ordered_conversations`
   (parent+subagents).** Per `skills/bg-eval/SKILL.md`'s own Phase 2, a
   trigger case's worker briefing is ONLY the bare prompt plus
   `"Your working copy is <ws>."` -- no `"You are <Name>, the ..."` opener --
   so `transcript_tools.is_briefing_input` is always False for it and it
   never spans the whole window either (a fresh delegate starts well after
   `window_start`). It is neither `parent` nor a `subagent`; it lives ONLY
   in `transcripts["all"]`, and the old parent-then-subagents walk never
   saw it at all.
3. **Non-parent conversations win outright; the parent is a fallback, and
   `bg-eval` never counts as a route.** When any non-parent conversation is
   attributed to the run (the actual worker(s)), routing is judged ONLY
   over those, ordered by `first_ts` -- the parent's own `view_file` calls
   (re-reading its own `bg-eval` runner skill before or during the run) are
   never consulted at all in that case. The parent is walked only when no
   other conversation is attributed. `"bg-eval"` is additionally always
   dropped from the collapsed result regardless of which conversation(s)
   were walked: it is this runner's own skill, and reading it is never
   itself a routing verdict.
"""
import json
import re
from pathlib import Path

from . import common

TRIGGER_ROOT = common.EVALS_ROOT / "trigger"
CASES_PATH = TRIGGER_ROOT / "cases.jsonl"
FIXTURE_DIR = TRIGGER_ROOT / "fixture"

SKILL_VIEW_RE = re.compile(r"^skills/([^/]+)/skill\.md$")
NEGATION_WORDS = ("not ", "n't", "never ", "instead of ", "rather than ", "avoid ", "without ", "no ")
RUNNER_SKILL_NAME = "bg-eval"


# --------------------------------------------------------------------------
# cases.jsonl
# --------------------------------------------------------------------------

def _read_lines():
    if not CASES_PATH.is_file():
        return []
    return [ln for ln in CASES_PATH.read_text(encoding="utf-8").splitlines() if ln.strip()]


def discover_cases():
    return [f"trigger-{i}" for i in range(1, len(_read_lines()) + 1)]


def load_case(case_name):
    """`case_name` is `trigger-<N>` (1-based). Returns `(obj, raw_line)`."""
    m = re.match(r"^trigger-(\d+)$", case_name)
    if not m:
        raise ValueError(f"not a trigger case name: {case_name!r}")
    n = int(m.group(1))
    lines = _read_lines()
    if n < 1 or n > len(lines):
        raise ValueError(f"trigger case {case_name} out of range (1..{len(lines)})")
    raw_line = lines[n - 1]
    obj = json.loads(raw_line)
    return obj, raw_line


# --------------------------------------------------------------------------
# start
# --------------------------------------------------------------------------

def start_one(case_name, root, ts):
    obj, raw_line = load_case(case_name)
    workspace = Path(root) / "eval-runs" / f"trigger-{case_name}-{ts}"
    common.ensure_empty_workspace(workspace)

    # No `- Copies to:` line to parse for trigger -- the fixture root IS the
    # working directory root, always (see evals/README.md "The trigger fixture").
    common.copy_tree_merge(FIXTURE_DIR, workspace)
    common.copy_plugin_agents_skills_references(workspace)

    expected_chain = list(obj.get("expected_chain") or [])
    prompt = obj["prompt"]
    common.normalize_mtimes(workspace)
    manifest = common.compute_manifest_sha256(workspace)
    started_at = common.utc_now_iso()
    record = {
        "suite": "trigger",
        "case": case_name,
        "workspace": str(workspace),
        "started_at": started_at,
        "prompt": prompt,
        "prompt_sha256": common.sha256_text(prompt),
        "handoff_to": None,
        "manifest_sha256": manifest,
        "graded_at": None,
        "last_result": None,
        "expected_skill": obj.get("expected_skill"),
        "acceptable_alternatives": list(obj.get("acceptable_alternatives") or []),
        "expected_chain": expected_chain,
        "raw_line": raw_line,
    }
    marker = common.marker_path("trigger", case_name, ts)
    common.save_marker(marker, record)
    return {"case": case_name, "workspace": workspace, "marker": marker,
            "prompt": prompt, "handoff_to": None}


def cmd_start(args):
    if bool(args.case) == bool(args.all_cases):
        common.fail("--case or --all-cases is required (exactly one)")
    root = Path(args.root).resolve() if args.root else Path.cwd()
    cases = [args.case] if args.case else discover_cases()
    if not cases:
        common.fail(f"no trigger cases found under {TRIGGER_ROOT}")
    ts = common.utc_now().strftime("%Y%m%dT%H%M%SZ")

    rows = [start_one(case, root, ts) for case in cases]

    print(f"{'suite':10} {'case':28} {'workspace':60} marker")
    for r in rows:
        print(f"{'trigger':10} {r['case']:28} {str(r['workspace']):60} {r['marker']}")
    for r in rows:
        print()
        print(f"=== PROMPT for trigger/{r['case']} (workspace {r['workspace']}) ===")
        print(r["prompt"])
        print("=== END PROMPT ===")
    return 0


# --------------------------------------------------------------------------
# judging
# --------------------------------------------------------------------------

def _conversations_to_judge(transcripts):
    """Non-parent attributed conversations (the worker(s)), ordered by
    `first_ts`, when any exist; otherwise `[parent]` (or `[]`). See the
    module docstring's rule 3 -- the parent is a fallback, never consulted
    when a real worker conversation is attributed."""
    all_convs = (transcripts or {}).get("all") or []
    parent = (transcripts or {}).get("parent")
    parent_id = parent.get("conversation_id") if parent else None
    non_parent = [c for c in all_convs if c.get("conversation_id") != parent_id]
    non_parent.sort(key=lambda c: c.get("first_ts") or "")
    if non_parent:
        return non_parent
    return [parent] if parent else []


def extract_skills_invoked(transcripts, window_start=None, window_end=None):
    """Ordered, consecutive-duplicate-collapsed list of skill names read via a
    `view_file` of `skills/<name>/SKILL.md`, per the module docstring's three
    rules: window-bounded (`created_at` in `[window_start, window_end]`),
    walking `transcripts["all"]` via `_conversations_to_judge` rather than
    `common.ordered_conversations` (parent+subagents only), and always
    excluding `RUNNER_SKILL_NAME` ("bg-eval") from the result."""
    raw = []
    for conv in _conversations_to_judge(transcripts):
        steps = common.transcript_tools.parse_transcript(conv["dir"])
        for call in common.transcript_tools.iter_tool_calls(steps):
            if call["name"] != "view_file":
                continue
            created_at = call.get("created_at") or ""
            if window_start and created_at < window_start:
                continue
            if window_end and created_at > window_end:
                continue
            path = common.transcript_tools.unwrap_arg((call.get("args") or {}).get("AbsolutePath"))
            if not path:
                continue
            suffix = common.case_common.normalize_path_suffix(path)
            m = SKILL_VIEW_RE.match(suffix)
            if m:
                raw.append(m.group(1))
    raw = [skill for skill in raw if skill != RUNNER_SKILL_NAME]
    collapsed = []
    for skill in raw:
        if not collapsed or collapsed[-1] != skill:
            collapsed.append(skill)
    return collapsed


def judge_outcome(skills_invoked, expected_chain, expected_skill, acceptable_alternatives):
    if expected_chain:
        if skills_invoked[:len(expected_chain)] == expected_chain:
            return "ROUTED_OK"
        return "NO_ROUTE" if not skills_invoked else "ROUTED_WRONG"
    if not skills_invoked:
        return "NO_ROUTE"
    acceptable = {expected_skill} | set(acceptable_alternatives or [])
    return "ROUTED_OK" if skills_invoked[0] in acceptable else "ROUTED_WRONG"


def _final_model_text(transcripts):
    parent = (transcripts or {}).get("parent")
    if not parent:
        return None
    steps = common.transcript_tools.parse_transcript(parent["dir"])
    text = None
    for step in steps:
        if step.get("source") == "MODEL" and isinstance(step.get("content"), str) and step["content"].strip():
            text = step["content"]
    return text


def compute_mentioned_only(transcripts, expected_skill, acceptable_alternatives):
    text = _final_model_text(transcripts)
    if not text:
        return False
    lowered = text.lower()
    for skill in [expected_skill] + list(acceptable_alternatives or []):
        if not skill:
            continue
        needle = skill.lower()
        start = 0
        while True:
            idx = lowered.find(needle, start)
            if idx == -1:
                break
            window = lowered[max(0, idx - 40):idx]
            if not any(neg in window for neg in NEGATION_WORDS):
                return True
            start = idx + len(needle)
    return False


# --------------------------------------------------------------------------
# grade
# --------------------------------------------------------------------------

def grade_one(marker_path, end_override=None, model="gemini-3.8-flash", brain_root=None,
              record=False, transcripts_override=None):
    """`transcripts_override` skips the internal `common.get_transcripts` call
    and uses this `{"parent", "subagents", "all"}` dict instead -- see
    `contract.grade_one`'s docstring for why (`run_suite.py run --runtime agy`)."""
    rec = common.load_marker(marker_path)
    case = rec["case"]
    workspace = Path(rec["workspace"])
    started_at = rec["started_at"]
    expected_skill = rec.get("expected_skill")
    acceptable_alternatives = rec.get("acceptable_alternatives") or []
    expected_chain = rec.get("expected_chain") or []

    current_manifest = common.compute_manifest_sha256(workspace)
    manifest_changed = current_manifest != rec.get("manifest_sha256")
    window_end = common.compute_window_end(workspace, end_override)
    transcripts = (transcripts_override if transcripts_override is not None
                   else common.get_transcripts(started_at, window_end, brain_root, workspace))
    attributed = common.transcript_attributed(transcripts)

    infra = common.is_infra(manifest_changed, transcript_judged=True, attributed=attributed)

    common.print_grade_header("trigger", case, workspace, started_at, window_end, transcripts)

    if infra:
        outcome = "INFRA"
        skills_invoked = []
        first_skill = None
        mentioned_only = False
        failed_criterion = "INFRA: nothing ran"
        passed = None
    else:
        skills_invoked = extract_skills_invoked(transcripts, window_start=started_at, window_end=window_end)
        first_skill = skills_invoked[0] if skills_invoked else None
        outcome = judge_outcome(skills_invoked, expected_chain, expected_skill, acceptable_alternatives)
        mentioned_only = compute_mentioned_only(transcripts, expected_skill, acceptable_alternatives)
        passed = (outcome == "ROUTED_OK")
        failed_criterion = None if passed else f"{outcome}: first_skill={first_skill} skills_invoked={skills_invoked}"
        print(f"    first_skill={first_skill} skills_invoked={skills_invoked} "
              f"expected_chain={expected_chain} mentioned_only={mentioned_only}")

    duration_s = common.parent_span_seconds(transcripts, started_at, window_end)
    common.print_outcome_footer(outcome, passed, failed_criterion,
                                 "nothing ran" if outcome == "INFRA" else None)

    rec["graded_at"] = common.utc_now_iso()
    rec["last_result"] = {"outcome": outcome, "pass": passed, "failed_criterion": failed_criterion}
    common.save_marker(marker_path, rec)

    if record:
        run_index = common.infer_run_index("trigger", case, marker_path)
        common.eval_record.append_runtime_trigger_record(
            case=case, run_index=run_index, outcome=outcome, first_skill=first_skill,
            skills_invoked=skills_invoked, expected_chain=expected_chain,
            mentioned_only=mentioned_only, failed_criterion=failed_criterion,
            duration_s=duration_s, runtime="antigravity", model=model,
            workspace=workspace, raw_line=rec.get("raw_line"),
        )

    return {"marker": Path(marker_path).name, "suite": "trigger", "case": case,
            "outcome": outcome, "pass": passed, "failed_criterion": failed_criterion}
