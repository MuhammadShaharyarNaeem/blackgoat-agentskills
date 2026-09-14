#!/usr/bin/env python3
"""Shared helpers for the evals/antigravity/cases/*/grade.py graders.

Kept separate from transcript_tools.py because this module knows about the
PLUGIN's shape (agent persona files, detect_stack.py, run-log/gates.jsonl
conventions) while transcript_tools.py knows only about Antigravity's
transcript format -- a grader for a different runtime could reuse
transcript_tools.py without this file, but nothing here makes sense without
the plugin.

Pure standard library.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

# evals/antigravity/case_common.py -> parents[0]=antigravity, [1]=evals, [2]=plugin root
PLUGIN_ROOT = Path(__file__).resolve().parents[2]
AGENTS_DIR = PLUGIN_ROOT / "agents"
SKILLS_DIR = PLUGIN_ROOT / "skills"
DETECT_STACK = SKILLS_DIR / "pipeline-tools" / "scripts" / "detect_stack.py"

SKILL_READ_RE = re.compile(r"skills/[^/]+/skill\.md$")
BASE_PERSONA_SUFFIX = "skills/agent-squad/base-persona.md"

CLAUDE_TIERS = {"inherit", "sonnet", "opus", "haiku", "fable"}

RUNNER_PATTERNS = [
    re.compile(r"^dotnet\s+(build|test)\b", re.I),
    re.compile(r"^npm\s+test\b", re.I),
    re.compile(r"^npm\s+run\s+(build|test)\b", re.I),
    re.compile(r"^pnpm\s+test\b", re.I),
    re.compile(r"^yarn\s+test\b", re.I),
    re.compile(r"^pytest\b", re.I),
    re.compile(r"^npx\s+playwright\s+test\b", re.I),
    re.compile(r"^npx\s+vitest\b", re.I),
    re.compile(r"^npx\s+jest\b", re.I),
]


def normalize_path_suffix(path):
    """Lowercase forward-slash form of a path, for comparing across machines.

    A path read via `view_file` on the user's machine
    (`C:\\Users\\msnaeem\\.gemini\\config\\plugins\\blackgoat-agentskills\\skills\\...`)
    never matches this repo's own absolute path byte-for-byte, so every
    comparison in this module is done on the `skills/...`-relative suffix,
    not the full path.
    """
    if not path:
        return ""
    p = path.strip().strip('"').strip("'")
    p = p.replace("\\\\", "\\").replace("\\", "/").lower()
    idx = p.rfind("skills/")
    if idx != -1:
        return p[idx:]
    idx = p.rfind("agents/")
    if idx != -1:
        return p[idx:]
    return p


def is_skill_read(path_suffix):
    """True for a `skills/<name>/SKILL.md` read or the `base-persona.md` read."""
    return bool(SKILL_READ_RE.search(path_suffix)) or path_suffix.endswith(BASE_PERSONA_SUFFIX)


def strip_command_quotes(cmd):
    """Strip one layer of wrapping quotes/`powershell -NoProfile -Command` shell."""
    if not cmd:
        return ""
    s = cmd.strip()
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        s = s[1:-1]
    m = re.match(r'^powershell(?:\.exe)?\s+-NoProfile\s+-Command\s+"(.*)"$', s, re.I | re.S)
    if m:
        s = m.group(1)
    return s.strip()


def is_raw_runner_invocation(cmd):
    """True when `cmd`'s leading tokens are a build/test runner with no `run_quiet.py`."""
    stripped = strip_command_quotes(cmd)
    for pattern in RUNNER_PATTERNS:
        if pattern.match(stripped):
            return "run_quiet.py" not in cmd
    return False


def matches_any_runner(cmd):
    stripped = strip_command_quotes(cmd)
    return any(p.match(stripped) for p in RUNNER_PATTERNS)


def command_after_run_quiet(cmd):
    """The inner command after `run_quiet.py`'s own `-- <command>` separator, or None.

    `run_quiet.py --capture <log> -- <command>` is the sanctioned wrapped form
    (`skills/pipeline-tools/scripts/run_quiet.py`'s own CLI contract) --
    observed on real transcripts as `python .../run_quiet.py --capture ... --
    dotnet test ...`. Its LEADING token is `python`, not the runner, so
    `matches_any_runner`/`is_raw_runner_invocation` (which only look at a
    command's own leading tokens) never see the runner inside it at all --
    this is what lets `is_raw_runner_invocation` return False on a wrapped
    call without ever inspecting it. This helper is for the separate
    "wrapped" metric: pull out what comes after the LAST `-- ` in the string
    (run_quiet.py's own separator) and let the caller test that inner text
    against `matches_any_runner` in turn.
    """
    if "run_quiet.py" not in cmd:
        return None
    idx = cmd.rfind("-- ")
    if idx == -1:
        return None
    return cmd[idx + 3:]


def parse_methodology_table(persona):
    """Parse `agents/<persona>.md`'s Methodology Dependencies table.

    Returns a list of `{skill, path, when}` dicts (in table order), or `[]`
    if the persona file or table can't be found. `path` has `{PLUGIN_ROOT}`
    left in place (verbatim from the file) -- callers compare on
    `normalize_path_suffix` of the trailing `skills/...` portion instead of
    expanding it.
    """
    persona_file = AGENTS_DIR / f"{persona.lower()}.md"
    if not persona_file.is_file():
        return []
    text = persona_file.read_text(encoding="utf-8", errors="replace")
    m = re.search(r"## Methodology Dependencies(.*?)(?:\n## |\Z)", text, re.S)
    if not m:
        return []
    rows = []
    for line in m.group(1).splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 3:
            continue
        if cells[0].lower() in ("skill", "-------", "------"):
            continue
        if set(cells[0]) <= {"-"}:
            continue
        rows.append({"skill": cells[0], "path": cells[1], "when": cells[2]})
    return rows


def run_detect_stack(repo_dir, timeout=60):
    """Run `detect_stack.py --repo <repo_dir> --json`; return the detected stack list, or [].

    Never raises: a subprocess failure (missing python, timeout, bad repo)
    returns `[]` rather than aborting the grader that called it.
    """
    if not DETECT_STACK.is_file():
        return []
    try:
        proc = subprocess.run(
            [sys.executable, str(DETECT_STACK), "--repo", str(repo_dir), "--json"],
            capture_output=True, text=True, timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if proc.returncode != 0:
        return []
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return []
    # `stacks` is a list of {"name": ..., "confidence": ..., "evidence": [...]}
    # dicts (detect_stack.py --json shape) -- reduce to the bare name list.
    stacks = data.get("stacks") or data.get("detected") or []
    if isinstance(stacks, dict):
        return list(stacks.keys())
    names = []
    for s in stacks:
        if isinstance(s, dict):
            name = s.get("name")
            if name:
                names.append(name)
        elif isinstance(s, str):
            names.append(s)
    return names


def expected_skill_reads(persona, repo_dir):
    """`(expected_suffixes, always_suffixes)` for a persona against a workspace.

    `expected_suffixes` = Always rows + rows whose trigger names a stack
    `detect_stack.py` reports for `repo_dir` (matched via detect_stack.py's
    own `SKILL_MAP`, imported directly so this can't drift from it).
    `always_suffixes` is the subset that is `Always` -- the spec's "misses"
    metric is computed over this subset only, never the stack-triggered rows,
    since a stack trigger not firing is not a miss.
    """
    rows = parse_methodology_table(persona)
    detected = set(run_detect_stack(repo_dir))
    skill_map = _load_skill_map()
    detected_skills = {skill_map[s] for s in detected if s in skill_map}

    always = set()
    expected = set()
    for row in rows:
        suffix = _path_cell_to_suffix(row["path"])
        if not suffix:
            continue
        when = row["when"].strip().lower()
        if when == "always":
            always.add(suffix)
            expected.add(suffix)
        else:
            skill_slug = row["skill"].strip().lower()
            if skill_slug in detected_skills:
                expected.add(suffix)
    return expected, always


def _load_skill_map():
    """`detect_stack.SKILL_MAP` (stack name -> skill slug), imported directly."""
    try:
        sys.path.insert(0, str(DETECT_STACK.parent))
        import detect_stack  # noqa: E402
        return dict(getattr(detect_stack, "SKILL_MAP", {}))
    except Exception:
        return {}


def _path_cell_to_suffix(path_cell):
    """`` `{PLUGIN_ROOT}/dotnet-backend-patterns/SKILL.md` `` -> `skills/dotnet-backend-patterns/skill.md`."""
    p = path_cell.strip().strip("`")
    p = p.replace("{PLUGIN_ROOT}", "skills")
    return normalize_path_suffix(p)


def find_bugfix_roots(workspace):
    """Every `.docs/bugfix/<slug>/` dir under `workspace` that has a `bug-report.md`."""
    workspace = Path(workspace)
    out = []
    bugfix_dir = workspace / ".docs" / "bugfix"
    if not bugfix_dir.is_dir():
        return out
    for child in sorted(bugfix_dir.iterdir()):
        if child.is_dir() and (child / "bug-report.md").is_file():
            out.append(child)
    return out


def read_jsonl(path):
    """Parse a `.jsonl` file into a list of dicts; `[]` if missing/unreadable."""
    path = Path(path)
    if not path.is_file():
        return []
    out = []
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out
