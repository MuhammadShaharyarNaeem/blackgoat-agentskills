#!/usr/bin/env python3
"""Run one /bgpdd-build-agy builder (Mason, Nova or Max) headless in the
Antigravity CLI, then check what it did.

agy has no PreToolUse guard hook and runs with permissions skipped, so the
restraints a Claude subagent gets from the runtime are enforced here after
the fact: the transcript tripwire (`agy_runtime.detect_workspace_escape`),
HEAD unchanged (nothing committed), the timeout, and a `<handoff>` block
present. The --out file carries the verbatim handoff plus the facts the
Orchestrator needs (git status, escape findings) and is the builder's
handoff for `check_handoff.py`.

Pure standard library. Never starts agy from --self-test.
"""
import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import agy_runtime  # noqa: E402

PERSONAS = ("mason", "nova", "max")
DEFAULT_MODEL = "gemini-3.8-flash-high"
DEFAULT_TIMEOUT_S = 2700

BUILDER_RULES = (
    "Delegation is blocking: invoke each worker synchronously, wait for its return before "
    "doing anything else, and never end your turn while a worker or background process is "
    "outstanding; nobody is at the keyboard to resume you. Before you finish, stop every "
    "background process you started (servers, watchers).\n"
    "Do not run any git command that writes: no git commit, merge, rebase, reset, stash, "
    "checkout, or push. Leave every change uncommitted in the working tree.\n"
    "Finish by printing one <handoff> block, outside any code fence, whose <changed_files> "
    "lists every file you created or modified."
)

HANDOFF_RE = re.compile(r"<handoff>.*?</handoff>", re.S)
CHANGED_FILES_RE = re.compile(r"<changed_files>(.*?)</changed_files>", re.S)

FINDING_ORDER = ("left_workspace", "head_moved", "timeout", "no_transcript", "no_handoff")


class UsageError(Exception):
    pass


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def _git(args, cwd):
    proc = subprocess.run(["git"] + args, cwd=str(cwd), capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=60)
    return proc.returncode, proc.stdout


def git_state(workspace):
    """`(head_sha, symbolic_ref_or_None)`; raises UsageError outside a work tree."""
    rc, out = _git(["rev-parse", "--is-inside-work-tree"], workspace)
    if rc != 0 or out.strip() != "true":
        raise UsageError(f"--workspace is not a git work tree: {workspace}")
    rc, sha = _git(["rev-parse", "HEAD"], workspace)
    if rc != 0 or not sha.strip():
        raise UsageError(f"--workspace has no HEAD commit: {workspace}")
    rc, ref = _git(["symbolic-ref", "-q", "HEAD"], workspace)
    return sha.strip(), (ref.strip() if rc == 0 and ref.strip() else None)


def _unquote_porcelain(path):
    path = path.strip()
    if len(path) >= 2 and path[0] == '"' and path[-1] == '"':
        try:
            return json.loads(path)
        except ValueError:
            return path[1:-1]
    return path


def porcelain(workspace):
    """`(raw_text, [paths])` from `git status --porcelain --untracked-files=all`."""
    rc, out = _git(["status", "--porcelain", "--untracked-files=all"], workspace)
    paths = []
    for line in out.splitlines():
        if len(line) < 4:
            continue
        rest = line[3:]
        if " -> " in rest:
            rest = rest.split(" -> ", 1)[1]
        paths.append(_unquote_porcelain(rest).replace("\\", "/"))
    return out, paths


def _rel_to(path, workspace):
    try:
        return Path(path).resolve().relative_to(Path(workspace).resolve()).as_posix()
    except ValueError:
        return None


def extract_handoff(stdout):
    """The LAST `<handoff>...</handoff>` block in agy's stdout, verbatim, or None."""
    blocks = HANDOFF_RE.findall(stdout or "")
    return blocks[-1] if blocks else None


def listed_changed_files(handoff):
    m = CHANGED_FILES_RE.search(handoff or "")
    if not m:
        return []
    out = []
    for line in m.group(1).splitlines():
        item = line.strip()
        item = re.sub(r"^[-*]\s+", "", item).strip().strip("`")
        if item and not item.lower().startswith("none:"):
            out.append(item.replace("\\", "/"))
    return out


def build_prompt(workspace, brief_text):
    """Lane scope preamble, the builder rules, then the brief verbatim."""
    return agy_runtime.apply_scope_preamble(f"{BUILDER_RULES}\n\n{brief_text}", workspace,
                                            preamble=agy_runtime.lane_scope_preamble)


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _now():
    return datetime.now(timezone.utc)


def default_preflight(persona, run=None):
    """`agy agents` must list `persona` as a whole line (exact match)."""
    return agy_runtime.preflight_agy(required_agents=(persona,), run=run, exact=True)


# --------------------------------------------------------------------------
# the run
# --------------------------------------------------------------------------

def run_builder(persona, workspace, brief_file, out, model=DEFAULT_MODEL, timeout_s=DEFAULT_TIMEOUT_S,
                invoke=None, preflight=None, brain_root=None, cache_path=None, installed_plugin_path=None):
    """Returns `(exit_code, report_dict)`. Raises UsageError for exit-2 preconditions."""
    if persona not in PERSONAS:
        raise UsageError(f"--persona must be one of {', '.join(PERSONAS)}")
    workspace = Path(workspace).resolve()
    if not workspace.is_dir():
        raise UsageError(f"--workspace is not a directory: {workspace}")
    head_before, ref_before = git_state(workspace)
    brief_path = Path(brief_file)
    if not brief_path.is_file():
        raise UsageError(f"--brief-file not found: {brief_file}")
    brief_text = brief_path.read_text(encoding="utf-8-sig", errors="replace")
    if not brief_text.strip():
        raise UsageError(f"--brief-file is empty: {brief_file}")

    invoke = invoke or agy_runtime.default_invoke
    preflight = preflight or default_preflight
    brain_root = Path(brain_root) if brain_root else agy_runtime.AGY_CLI_BRAIN_ROOT
    installed_plugin_path = installed_plugin_path or agy_runtime.AGY_INSTALLED_PLUGIN_PATH

    ok, reason = preflight(persona)
    if not ok:
        raise UsageError(f"preflight failed: {reason}")

    prompt = build_prompt(workspace, brief_text)
    argv = agy_runtime.build_argv_agy(prompt, model=model, timeout_s=timeout_s, agent=persona)
    started = _now()
    proc = invoke(argv, workspace, timeout_s)
    ended = _now()

    report = {
        "persona": persona, "model": model, "workspace": str(workspace),
        "started": _iso(started), "duration_s": round(proc.duration_s or 0.0, 1),
        "agy_exit": proc.returncode, "timed_out": False, "head_before": head_before,
        "head_after": None, "ref_before": ref_before, "ref_after": None,
        "transcripts": [], "escape": None, "handoff_present": False,
        "changed_not_listed": [], "listed_not_changed": [], "findings": [],
        "infra": None, "out": str(out), "result": None,
    }

    if agy_runtime.AGY_INFRA_RE.search(proc.stdout or ""):
        report["infra"] = ("permission_denied: a tool required a permission headless mode cannot "
                           "prompt for, and it was auto-denied")

    window_start = _iso(started - timedelta(seconds=2))
    window_end = _iso(ended + timedelta(seconds=5))
    transcripts = agy_runtime.resolve_agy_transcripts(workspace, window_start, window_end,
                                                      brain_root=brain_root, cache_path=cache_path)
    convs = (transcripts or {}).get("all") or []
    report["transcripts"] = [c.get("conversation_id") for c in convs]
    fresh = any((c.get("last_ts") or "") >= window_start for c in convs)
    escape = agy_runtime.detect_workspace_escape(transcripts, workspace, installed_plugin_path, brain_root)
    report["escape"] = escape

    head_after, ref_after = git_state(workspace)
    report["head_after"], report["ref_after"] = head_after, ref_after
    report["timed_out"] = bool(proc.timed_out or (proc.duration_s or 0) >= timeout_s)

    handoff = extract_handoff(proc.stdout)
    report["handoff_present"] = handoff is not None

    status_text, changed = porcelain(workspace)
    excluded = {p for p in (_rel_to(brief_path, workspace), _rel_to(out, workspace)) if p}
    changed = [p for p in changed if p not in excluded]
    listed = listed_changed_files(handoff)
    report["changed_not_listed"] = [p for p in changed if p not in listed]
    report["listed_not_changed"] = [p for p in listed if p not in changed]

    findings = []
    if escape["escaped"]:
        findings.append("left_workspace")
    if head_after != head_before or ref_after != ref_before:
        findings.append("head_moved")
    if report["timed_out"]:
        findings.append("timeout")
    if not convs or not fresh:
        findings.append("no_transcript")
    if handoff is None:
        findings.append("no_handoff")
    report["findings"] = findings

    if report["infra"]:
        report["result"], code = "ERROR", 2
    elif findings:
        report["result"], code = "FINDING", 1
    else:
        report["result"], code = "PASS", 0

    write_out(Path(out), report, handoff, status_text)
    return code, report


def write_out(out, report, handoff, status_text):
    esc = report["escape"] or {}
    first = esc.get("first")
    lines = [
        "# agy builder run",
        "",
        f"- Persona: {report['persona']}",
        f"- Model: {report['model']}",
        f"- Workspace: {report['workspace']}",
        f"- Started: {report['started']}",
        f"- Duration: {report['duration_s']}s",
        f"- agy exit status: {report['agy_exit']}",
        f"- Timed out: {'yes' if report['timed_out'] else 'no'}",
        f"- HEAD before: {report['head_before']} ({report['ref_before'] or 'detached'})",
        f"- HEAD after: {report['head_after']} ({report['ref_after'] or 'detached'})",
        f"- Transcripts scanned: {', '.join(report['transcripts']) or 'none'}",
        f"- Result: {report['result']}",
        f"- Findings: {', '.join(report['findings']) or 'none'}",
    ]
    if report["infra"]:
        lines.append(f"- Infra: {report['infra']}")
    lines += ["", "## Workspace escape", ""]
    if first:
        lines.append(f"- First: {first['tool']} {first['argument']} at {first['created_at']} "
                     f"(conversation {first['conversation_id']})")
        lines.append(f"- Calls outside the workspace: {esc.get('count')}")
    else:
        lines.append("- none")
    lines += ["", "## Handoff (verbatim from agy stdout)", ""]
    lines.append(handoff if handoff is not None else "(no handoff block in agy stdout)")
    lines += ["", "## git status --porcelain --untracked-files=all", "", "```",
              status_text.rstrip("\n"), "```", "",
              "## Changed files against <changed_files>", "",
              f"- Changed, not listed: {', '.join(report['changed_not_listed']) or 'none'}",
              f"- Listed, not changed: {', '.join(report['listed_not_changed']) or 'none'}", ""]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

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


PURPOSE = ("Runs one builder headless in the Antigravity CLI, then checks it stayed in its "
           "workspace, committed nothing, finished in time and returned a handoff.")

EPILOG = """\
Reads:
  --workspace   a git work tree; HEAD and the branch ref are recorded before
    and after. agy runs with this as its cwd.
  --brief-file  the builder brief, non-empty. The prompt is the lane scope
    preamble (agy_runtime.lane_scope_preamble), the builder rules (blocking
    delegation, stop background processes, no git command that writes, end
    with an unfenced <handoff> whose <changed_files> lists every file
    touched), then the brief verbatim.
  agy is run as: agy -p <prompt> --mode accept-edits --print-timeout <Go
    duration of --timeout-s> --dangerously-skip-permissions --model <model>
    --agent <persona>. No --sandbox.
  After the run: ~/.gemini/antigravity-cli/cache/last_conversations.json and
    the brain transcripts it names (window fallback), scanned by
    agy_runtime.detect_workspace_escape with allowed roots = the workspace,
    the installed agy plugin, the brain root, the temp dir and Python's own.
  git status --porcelain --untracked-files=all of the workspace, minus the
    brief and --out files.

Writes:
  --out  markdown: persona, model, duration, agy exit status, result,
    findings, escape detail, the LAST <handoff> block from agy stdout
    verbatim and unfenced (check_handoff.py reads it), the porcelain, and
    changed-not-listed / listed-not-changed paths. Written on every run that
    reached agy.

JSON keys:
  persona, model, workspace, started, duration_s, agy_exit, timed_out,
  head_before, head_after, ref_before, ref_after, transcripts, escape
  ({escaped, first, count}), handoff_present, changed_not_listed,
  listed_not_changed, findings, infra, out, result (PASS|FINDING|ERROR),
  error.

Findings (exit 1; one stderr line names them):
  left_workspace  a tool call outside the allowed roots, an MCP or web call
  head_moved      HEAD or the branch ref changed
  timeout         the run hit --timeout-s
  no_transcript   no transcript attributed, or none active in the run window
  no_handoff      no <handoff> block in agy stdout

Exit codes:
  0  completed: no finding
  1  at least one finding
  2  usage or precondition (bad persona, not a git work tree, missing or
     empty brief), agy missing or preflight failed (`agy agents` must list
     the persona as a whole line), or agy reported a permission auto-deny

Self-test:
  python run_agy_builder.py --self-test   (14 cases; injected agy, temp git repos)
"""


def build_parser():
    parser = PurposeFirstParser(
        prog="run_agy_builder.py",
        description=PURPOSE,
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--persona", choices=PERSONAS, help="builder persona agy runs as")
    parser.add_argument("--workspace", help="git work tree agy runs in")
    parser.add_argument("--brief-file", help="file holding the builder brief")
    parser.add_argument("--out", help="handoff file to write")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"agy model (default {DEFAULT_MODEL})")
    parser.add_argument("--timeout-s", type=int, default=DEFAULT_TIMEOUT_S,
                        help=f"agy --print-timeout in seconds (default {DEFAULT_TIMEOUT_S})")
    parser.add_argument("--self-test", action="store_true", help="run the offline self-test")
    return parser


def main(argv=None, seams=None):
    args = build_parser().parse_args(argv)
    if args.self_test:
        return run_self_test()
    missing = [f for f in ("persona", "workspace", "brief_file", "out") if not getattr(args, f)]
    if missing:
        msg = "missing required argument(s): " + ", ".join("--" + m.replace("_", "-") for m in missing)
        print(json.dumps({"result": "ERROR", "error": msg}))
        print(f"ERROR: {msg}", file=sys.stderr)
        return 2
    try:
        code, report = run_builder(args.persona, args.workspace, args.brief_file, args.out,
                                   model=args.model, timeout_s=args.timeout_s, **(seams or {}))
    except UsageError as exc:
        print(json.dumps({"result": "ERROR", "error": str(exc)}))
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2))
    if code == 1:
        print(f"FINDING: {', '.join(report['findings'])}", file=sys.stderr)
    elif code == 2:
        print(f"ERROR: {report['infra']}", file=sys.stderr)
    return code


# --------------------------------------------------------------------------
# self-test
# --------------------------------------------------------------------------

GOOD_HANDOFF = ("<handoff>\n<status>COMPLETE</status>\n<changed_files>\nsrc/a.py\n</changed_files>\n"
                "<changed_symbols>\nsrc/a.py::foo\n</changed_symbols>\n<blockers>None</blockers>\n</handoff>")


def run_self_test():

    def git(cwd, *args):
        subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t"] + list(args), cwd=str(cwd),
                       check=True, capture_output=True)

    class RunAgyBuilderTests(unittest.TestCase):
        def setUp(self):
            self.tmp = Path(tempfile.mkdtemp(prefix="run_agy_builder_selftest_"))
            self.ws = self.tmp / "ws"
            self.ws.mkdir()
            git(self.ws, "init", "-q")
            (self.ws / "README.md").write_text("x\n", encoding="utf-8")
            git(self.ws, "add", "README.md")
            git(self.ws, "commit", "-q", "-m", "base")
            self.base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(self.ws), capture_output=True,
                                       text=True).stdout.strip()
            self.brain = self.tmp / "brain"
            self.cache = self.tmp / "last.json"
            self.brief = self.tmp / "brief.md"
            self.brief.write_text("Implement foo in src/a.py.\n", encoding="utf-8")
            self.out = self.tmp / "out" / "handoff.md"
            self.calls = []

        def tearDown(self):
            shutil.rmtree(self.tmp, ignore_errors=True)

        def fake(self, stdout=GOOD_HANDOFF, tool_calls=(), commit=False, timed_out=False, transcript=True):
            def invoke(argv, cwd, timeout_s):
                self.calls.append(argv)
                (Path(cwd) / "src").mkdir(exist_ok=True)
                (Path(cwd) / "src" / "a.py").write_text("def foo():\n    return 1\n", encoding="utf-8")
                if commit:
                    git(cwd, "add", "-A")
                    git(cwd, "commit", "-q", "-m", "agy")
                if transcript:
                    ts = _iso(_now())
                    d = self.brain / "conv-1" / ".system_generated" / "logs"
                    d.mkdir(parents=True, exist_ok=True)
                    steps = [{"step_index": 0, "type": "USER_INPUT", "content": "go", "created_at": ts},
                             {"step_index": 1, "type": "PLANNER_RESPONSE", "created_at": ts,
                              "tool_calls": list(tool_calls)}]
                    (d / "transcript.jsonl").write_text("\n".join(json.dumps(s) for s in steps),
                                                        encoding="utf-8")
                    self.cache.write_text(json.dumps({str(cwd): "conv-1"}), encoding="utf-8")
                return agy_runtime.ProcResult(stdout, "", -1 if timed_out else 0, 12.0, timed_out=timed_out)
            return invoke

        def run_it(self, persona="mason", **kw):
            seams = {"invoke": self.fake(**kw), "preflight": lambda p: (True, None),
                     "brain_root": self.brain, "cache_path": self.cache,
                     "installed_plugin_path": str(self.tmp / "plugin")}
            return run_builder(persona, self.ws, self.brief, self.out, timeout_s=600, **seams)

        def test_clean_pass(self):
            code, rep = self.run_it()
            self.assertEqual(code, 0, rep["findings"])
            self.assertEqual(rep["changed_not_listed"], [])
            self.assertIn(GOOD_HANDOFF, self.out.read_text(encoding="utf-8"))

        def test_out_passes_check_handoff(self):
            code, _ = self.run_it()
            self.assertEqual(code, 0)
            checker = Path(__file__).resolve().parent / "check_handoff.py"
            proc = subprocess.run([sys.executable, str(checker), "--handoff", str(self.out),
                                   "--persona", "mason", "--repo", str(self.ws), "--since", self.base],
                                  capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

        def test_escape_is_finding(self):
            code, rep = self.run_it(tool_calls=[{"name": "view_file", "args": {
                "AbsolutePath": json.dumps("C:\\Gorelo\\secret.cs")}}])
            self.assertEqual(code, 1)
            self.assertIn("left_workspace", rep["findings"])

        def test_head_moved_is_finding(self):
            code, rep = self.run_it(commit=True)
            self.assertEqual(code, 1)
            self.assertIn("head_moved", rep["findings"])

        def test_timeout_is_finding(self):
            code, rep = self.run_it(timed_out=True)
            self.assertEqual(code, 1)
            self.assertIn("timeout", rep["findings"])

        def test_missing_handoff_is_finding(self):
            code, rep = self.run_it(stdout="done, all good")
            self.assertEqual(code, 1)
            self.assertEqual(rep["findings"], ["no_handoff"])

        def test_no_transcript_is_finding(self):
            code, rep = self.run_it(transcript=False)
            self.assertEqual(code, 1)
            self.assertIn("no_transcript", rep["findings"])

        def test_unlisted_change_reported(self):
            stdout = GOOD_HANDOFF.replace("src/a.py\n</changed_files>", "src/b.py\n</changed_files>")
            code, rep = self.run_it(stdout=stdout)
            self.assertEqual(rep["changed_not_listed"], ["src/a.py"])
            self.assertEqual(rep["listed_not_changed"], ["src/b.py"])

        def test_bad_persona_exits_2(self):
            with self.assertRaises(SystemExit) as cm:
                build_parser().parse_args(["--persona", "luna"])
            self.assertEqual(cm.exception.code, 2)
            with self.assertRaises(UsageError):
                self.run_it(persona="luna")

        def test_preconditions_exit_2(self):
            self.brief.write_text("  \n", encoding="utf-8")
            rc = main(["--persona", "mason", "--workspace", str(self.ws), "--brief-file",
                       str(self.brief), "--out", str(self.out)],
                      seams={"preflight": lambda p: (True, None)})
            self.assertEqual(rc, 2)
            not_git = self.tmp / "plain"
            not_git.mkdir()
            with self.assertRaises(UsageError):
                git_state(not_git)

        def test_preflight_failure_exit_2(self):
            rc = main(["--persona", "nova", "--workspace", str(self.ws), "--brief-file",
                       str(self.brief), "--out", str(self.out)],
                      seams={"preflight": lambda p: (False, "agy missing"), "invoke": self.fake()})
            self.assertEqual(rc, 2)
            self.assertEqual(self.calls, [])

        def test_preflight_whole_line_match_exit_2(self):
            class P:
                returncode, stdout = 0, "alex\nmason\nmaximus\nnova\n"
            rc = main(["--persona", "max", "--workspace", str(self.ws), "--brief-file",
                       str(self.brief), "--out", str(self.out)],
                      seams={"preflight": lambda p: default_preflight(p, run=lambda *a, **k: P()),
                             "invoke": self.fake()})
            self.assertEqual(rc, 2)
            self.assertEqual(self.calls, [])
            self.assertEqual(default_preflight("mason", run=lambda *a, **k: P()), (True, None))

        def test_prompt_carries_rules(self):
            self.run_it()
            prompt = self.calls[0][2]
            for needle in ("Delegation is blocking", "never end your turn", "stop every background process",
                           "git commit, merge, rebase, reset, stash, checkout, or push", "<handoff>",
                           "<changed_files>", "Implement foo in src/a.py."):
                self.assertIn(needle, prompt)
            self.assertNotIn("evals/", prompt)
            self.assertTrue(prompt.startswith(agy_runtime.lane_scope_preamble(self.ws.resolve())))

        def test_argv_shape(self):
            self.run_it(persona="max")
            argv = self.calls[0]
            self.assertEqual(argv[:2], ["agy", "-p"])
            self.assertEqual(argv[argv.index("--agent") + 1], "max")
            self.assertEqual(argv[argv.index("--model") + 1], DEFAULT_MODEL)
            self.assertEqual(argv[argv.index("--print-timeout") + 1], "10m")
            self.assertIn("--dangerously-skip-permissions", argv)
            self.assertNotIn("--sandbox", argv)

    suite = unittest.TestLoader().loadTestsFromTestCase(RunAgyBuilderTests)
    result = unittest.TextTestRunner(stream=sys.stderr, verbosity=1).run(suite)
    total = result.testsRun
    failed = len(result.failures) + len(result.errors)
    print(f"SELF-TEST: {total - failed}/{total} passed. {'OK' if failed == 0 else 'FAIL'}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
