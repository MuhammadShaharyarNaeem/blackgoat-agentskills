#!/usr/bin/env python3
"""Deterministic, evidence-backed stack detection for the bgpdd pipelines.

Walks a repository tree and reports which technology stacks it finds
concrete, file-based evidence for (never a guess): dotnet, vue3, react,
angular, node, python, godot, powershell, docker, aws, azure,
github-actions, playwright, and the four DB stacks (postgres, sqlserver,
mysql, sqlite). Used by `bgpdd-discovery` Phase 1 so a stack-specific
methodology skill's "If the project uses X" dependency-table row has a
mechanical floor instead of relying solely on the discovery agent's prose.
Pure standard library.

Usage:
    python detect_stack.py --repo <dir> [--json|--markdown] [--max-depth N]
    python detect_stack.py --self-test

--max-depth (default 6) bounds directory recursion depth from --repo.
node_modules, bin, obj, .git, dist, .venv, __pycache__ are always skipped.
"""
import argparse
import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

SKIP_DIRS = {"node_modules", "bin", "obj", ".git", "dist", ".venv", "__pycache__"}
MAX_EVIDENCE = 5

# Maps a detected stack name to the plugin skill that should be loaded for
# it. Stacks with no dedicated methodology skill in this plugin (react,
# angular, node, python, docker, github-actions) are omitted on purpose.
SKILL_MAP = {
    "dotnet": "dotnet-backend-patterns",
    "vue3": "vue3-spa-patterns",
    "godot": "godot-gdscript-patterns",
    "powershell": "powershell-script-patterns",
    "aws": "cloud-deploy-patterns",
    "azure": "cloud-deploy-patterns",
    "playwright": "playwright-skill",
    "postgres": "database-migration-patterns",
    "sqlserver": "database-migration-patterns",
    "mysql": "database-migration-patterns",
    "sqlite": "database-migration-patterns",
}

EF_PROVIDER_MAP = {
    "microsoft.entityframeworkcore.sqlserver": "sqlserver",
    "npgsql.entityframeworkcore.postgresql": "postgres",
    "pomelo.entityframeworkcore.mysql": "mysql",
    "mysql.entityframeworkcore": "mysql",
    "microsoft.entityframeworkcore.sqlite": "sqlite",
}


class ScanError(Exception):
    """Structural/usage failure — maps to exit 2."""


# ---------------------------------------------------------------------------
# Filesystem helpers
# ---------------------------------------------------------------------------


def iter_files(repo, max_depth):
    """Yield every file Path under repo, skipping SKIP_DIRS, bounded to max_depth."""
    for dirpath, dirnames, filenames in os.walk(repo):
        depth = len(Path(dirpath).relative_to(repo).parts)
        if depth >= max_depth:
            dirnames[:] = []
        else:
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            yield Path(dirpath) / name


def read_text(path):
    try:
        return Path(path).read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return ""


def load_json(path):
    try:
        data = json.loads(read_text(path))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def to_rel(path, repo):
    return str(Path(path).relative_to(repo)).replace(os.sep, "/")


def dedup(paths):
    seen = []
    for p in paths:
        if p not in seen:
            seen.append(p)
    return seen


def parse_major_version(spec):
    """Best-effort major-version extraction from a package.json version spec.

    Handles "^3.2.0", "~3.0.0", "3.4.21", ">=3.0.0 <4.0.0". Returns None when
    the spec carries no leading integer to read (e.g. "latest", "workspace:*").
    """
    match = re.search(r"(\d+)\.\d+\.\d+", spec)
    if match:
        return int(match.group(1))
    match = re.match(r"^[\^~>=<\s]*(\d+)", spec.strip())
    if match:
        return int(match.group(1))
    return None


# ---------------------------------------------------------------------------
# Bucketing pass — one walk, classify every file by name/location
# ---------------------------------------------------------------------------

BUCKET_NAMES = (
    "csproj", "sln", "fsproj", "global_json", "package_json", "vite_config",
    "vue_file", "pyproject", "requirements_txt", "setup_py", "project_godot",
    "gd_file", "ps1", "psm1", "dockerfile", "compose", "tf", "bicep",
    "azure_pipelines", "host_json", "workflow", "playwright_config",
    "appsettings", "cdk_json", "serverless_yml",
)

COMPOSE_RE = re.compile(r"^(docker-)?compose.*\.ya?ml$")


def scan_repo(repo, max_depth):
    buckets = {name: [] for name in BUCKET_NAMES}
    for path in iter_files(repo, max_depth):
        lower = path.name.lower()
        if lower.endswith(".csproj"):
            buckets["csproj"].append(path)
        elif lower.endswith(".sln"):
            buckets["sln"].append(path)
        elif lower.endswith(".fsproj"):
            buckets["fsproj"].append(path)
        elif lower == "global.json":
            buckets["global_json"].append(path)
        elif lower == "package.json":
            buckets["package_json"].append(path)
        elif lower.startswith("vite.config"):
            buckets["vite_config"].append(path)
        elif lower.endswith(".vue"):
            buckets["vue_file"].append(path)
        elif lower == "pyproject.toml":
            buckets["pyproject"].append(path)
        elif lower == "requirements.txt":
            buckets["requirements_txt"].append(path)
        elif lower == "setup.py":
            buckets["setup_py"].append(path)
        elif lower == "project.godot":
            buckets["project_godot"].append(path)
        elif lower.endswith(".gd"):
            buckets["gd_file"].append(path)
        elif lower.endswith(".ps1"):
            buckets["ps1"].append(path)
        elif lower.endswith(".psm1"):
            buckets["psm1"].append(path)
        elif lower == "dockerfile" or lower.startswith("dockerfile."):
            buckets["dockerfile"].append(path)
        elif COMPOSE_RE.match(lower):
            buckets["compose"].append(path)
        elif lower.endswith(".tf"):
            buckets["tf"].append(path)
        elif lower.endswith(".bicep"):
            buckets["bicep"].append(path)
        elif lower in ("azure-pipelines.yml", "azure-pipelines.yaml"):
            buckets["azure_pipelines"].append(path)
        elif lower == "host.json":
            buckets["host_json"].append(path)
        elif lower == "cdk.json":
            buckets["cdk_json"].append(path)
        elif lower in ("serverless.yml", "serverless.yaml"):
            buckets["serverless_yml"].append(path)
        elif lower.startswith("playwright.config"):
            buckets["playwright_config"].append(path)
        elif lower.startswith("appsettings") and lower.endswith(".json"):
            buckets["appsettings"].append(path)

        if (lower.endswith(".yml") or lower.endswith(".yaml")) and \
                ".github" in path.parts and "workflows" in path.parts:
            buckets["workflow"].append(path)
    return buckets


# ---------------------------------------------------------------------------
# Per-stack detectors — each returns [(name, confidence, [Path, ...]), ...]
# ---------------------------------------------------------------------------


def detect_frontend_stacks(buckets):
    results = []
    vue2_detected = False
    vue3_pkg_evidence = []
    react_evidence = []
    angular_evidence = []
    has_frontend = False

    for pkg in buckets["package_json"]:
        data = load_json(pkg)
        deps = {}
        for key in ("dependencies", "devDependencies"):
            section = data.get(key)
            if isinstance(section, dict):
                deps.update(section)
        if "vue" in deps:
            has_frontend = True
            major = parse_major_version(str(deps["vue"]))
            if major == 2:
                vue2_detected = True
            elif major == 3:
                vue3_pkg_evidence.append(pkg)
        if "react" in deps:
            has_frontend = True
            react_evidence.append(pkg)
        if "@angular/core" in deps:
            has_frontend = True
            angular_evidence.append(pkg)

    if react_evidence:
        results.append(("react", "high", react_evidence))
    if angular_evidence:
        results.append(("angular", "high", angular_evidence))

    if not vue2_detected:
        vue3_evidence = list(vue3_pkg_evidence)
        confidence = "high" if vue3_pkg_evidence else None
        for vc in buckets["vite_config"]:
            if re.search(r"plugin-vue|vue\(\)", read_text(vc), re.IGNORECASE):
                vue3_evidence.append(vc)
        if buckets["vue_file"]:
            vue3_evidence.extend(buckets["vue_file"])
        if vue3_evidence:
            results.append(("vue3", confidence or "medium", vue3_evidence))

    if buckets["package_json"] and not has_frontend:
        results.append(("node", "high", list(buckets["package_json"])))

    return results


def detect_cloud_stacks(buckets):
    tf_aws, tf_azure = [], []
    for tf in buckets["tf"]:
        text = read_text(tf)
        if re.search(r'provider\s+"aws"', text, re.IGNORECASE) or \
                re.search(r'resource\s+"aws_', text, re.IGNORECASE):
            tf_aws.append(tf)
        if re.search(r'provider\s+"azurerm"', text, re.IGNORECASE) or \
                re.search(r'resource\s+"azurerm_', text, re.IGNORECASE):
            tf_azure.append(tf)

    results = []
    aws_all = list(buckets["cdk_json"]) + list(buckets["serverless_yml"]) + tf_aws
    if aws_all:
        confidence = "high" if buckets["cdk_json"] else "medium"
        results.append(("aws", confidence, aws_all))

    azure_markers = list(buckets["bicep"]) + list(buckets["azure_pipelines"]) + list(buckets["host_json"])
    azure_all = azure_markers + tf_azure
    if azure_all:
        confidence = "high" if azure_markers else "medium"
        results.append(("azure", confidence, azure_all))

    return results


def detect_db_stacks(buckets):
    found = {}

    for csproj in buckets["csproj"]:
        text = read_text(csproj)
        for match in re.finditer(r'Include\s*=\s*"([^"]+)"', text, re.IGNORECASE):
            db = EF_PROVIDER_MAP.get(match.group(1).strip().lower())
            if db:
                found.setdefault(db, []).append(csproj)

    for cfg in buckets["appsettings"]:
        text = read_text(cfg)
        if re.search(r"npgsql", text, re.IGNORECASE) or \
                re.search(r"Host=.*Port=5432", text, re.IGNORECASE):
            found.setdefault("postgres", []).append(cfg)
        if re.search(r"mysql", text, re.IGNORECASE):
            found.setdefault("mysql", []).append(cfg)
        if re.search(r"Trusted_Connection|Initial Catalog|MultipleActiveResultSets",
                      text, re.IGNORECASE):
            found.setdefault("sqlserver", []).append(cfg)
        if re.search(r"Data Source=[^;]*\.db", text, re.IGNORECASE) or ":memory:" in text:
            found.setdefault("sqlite", []).append(cfg)

    for compose in buckets["compose"]:
        text = read_text(compose)
        for match in re.finditer(r'image:\s*["\']?([^\s"\'#]+)', text, re.IGNORECASE):
            image = match.group(1).lower()
            if "postgres" in image:
                found.setdefault("postgres", []).append(compose)
            elif "mysql" in image or "mariadb" in image:
                found.setdefault("mysql", []).append(compose)
            elif "mssql" in image or "sqlserver" in image:
                found.setdefault("sqlserver", []).append(compose)
            elif "sqlite" in image:
                found.setdefault("sqlite", []).append(compose)

    results = []
    for name, paths in found.items():
        evidence = dedup(paths)
        confidence = "high" if any(p in buckets["csproj"] for p in evidence) else "medium"
        results.append((name, confidence, evidence))
    return results


# ---------------------------------------------------------------------------
# Report assembly
# ---------------------------------------------------------------------------


def build_report(repo, max_depth):
    repo = Path(repo)
    buckets = scan_repo(repo, max_depth)
    stacks = []

    def add(name, confidence, paths):
        evidence = dedup(paths)
        if not evidence:
            return
        stacks.append({
            "name": name,
            "confidence": confidence,
            "evidence": [to_rel(p, repo) for p in evidence[:MAX_EVIDENCE]],
        })

    dotnet_paths = buckets["csproj"] + buckets["sln"] + buckets["fsproj"] + buckets["global_json"]
    if dotnet_paths:
        add("dotnet", "high", dotnet_paths)

    for name, confidence, paths in detect_frontend_stacks(buckets):
        add(name, confidence, paths)

    python_paths = buckets["pyproject"] + buckets["requirements_txt"] + buckets["setup_py"]
    if python_paths:
        add("python", "high", python_paths)

    godot_paths = buckets["project_godot"] + buckets["gd_file"]
    if godot_paths:
        add("godot", "high" if buckets["project_godot"] else "medium", godot_paths)

    if buckets["ps1"] or buckets["psm1"]:
        add("powershell", "high", buckets["ps1"] + buckets["psm1"])

    if buckets["dockerfile"] or buckets["compose"]:
        add("docker", "high", buckets["dockerfile"] + buckets["compose"])

    for name, confidence, paths in detect_cloud_stacks(buckets):
        add(name, confidence, paths)

    if buckets["workflow"]:
        add("github-actions", "high", buckets["workflow"])

    if buckets["playwright_config"]:
        add("playwright", "high", buckets["playwright_config"])

    for name, confidence, paths in detect_db_stacks(buckets):
        add(name, confidence, paths)

    stacks.sort(key=lambda s: s["name"])

    warnings = []
    if not stacks:
        warnings.append(
            "no evidence-backed stacks detected under this repo; "
            "treat as greenfield unless the brief says otherwise"
        )

    skills = sorted({SKILL_MAP[s["name"]] for s in stacks if s["name"] in SKILL_MAP})

    return {
        "result": "OK",
        "repo": str(repo),
        "stacks": stacks,
        "skills": skills,
        "warnings": warnings,
    }


def render_markdown(result):
    lines = ["## Stacks (detected)", ""]
    if not result["stacks"]:
        lines.append("_No stacks detected with evidence in this repo._")
    for stack in result["stacks"]:
        skill = SKILL_MAP.get(stack["name"])
        skill_part = f" - skill: `{skill}`" if skill else ""
        evidence = ", ".join(f"`{e}`" for e in stack["evidence"])
        lines.append(f"- **{stack['name']}** ({stack['confidence']}){skill_part} - evidence: {evidence}")
    for warning in result["warnings"]:
        lines.append("")
        lines.append(f"> Warning: {warning}")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv):
    parser = argparse.ArgumentParser(prog="detect_stack.py")
    parser.add_argument("--repo")
    output = parser.add_mutually_exclusive_group()
    output.add_argument("--json", action="store_true")
    output.add_argument("--markdown", action="store_true")
    parser.add_argument("--max-depth", type=int, default=6)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)

    if args.self_test:
        return run_self_test()

    if not args.repo:
        print(json.dumps({"result": "ERROR", "error": "missing required argument: --repo"}))
        return 2

    repo_path = Path(args.repo)
    if not repo_path.is_dir():
        print(json.dumps({"result": "ERROR", "error": f"repo not found or not a directory: {args.repo}"}))
        return 2

    result = build_report(repo_path, args.max_depth)

    if args.markdown:
        print(render_markdown(result))
    else:
        print(json.dumps(result, indent=2))
    return 0


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------


def run_self_test():
    import shutil

    class DetectStackTests(unittest.TestCase):
        def setUp(self):
            self.repo = Path(tempfile.mkdtemp())

        def tearDown(self):
            shutil.rmtree(self.repo, ignore_errors=True)

        def _write(self, rel, content=""):
            p = self.repo / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
            return p

        def _names(self, result):
            return {s["name"] for s in result["stacks"]}

        def test_dotnet_via_csproj_and_sln(self):
            self._write("App/App.csproj", "<Project></Project>")
            self._write("App.sln", "")
            result = build_report(self.repo, 6)
            self.assertIn("dotnet", self._names(result))
            dotnet = next(s for s in result["stacks"] if s["name"] == "dotnet")
            self.assertEqual(dotnet["confidence"], "high")
            self.assertTrue(1 <= len(dotnet["evidence"]) <= 5)

        def test_vue3_via_package_json(self):
            self._write("package.json", json.dumps({"dependencies": {"vue": "^3.2.0"}}))
            result = build_report(self.repo, 6)
            self.assertIn("vue3", self._names(result))
            vue3 = next(s for s in result["stacks"] if s["name"] == "vue3")
            self.assertEqual(vue3["confidence"], "high")

        def test_vue2_not_reported_as_vue3(self):
            self._write("package.json", json.dumps({"dependencies": {"vue": "^2.6.14"}}))
            self._write("src/App.vue", "<template></template>")
            result = build_report(self.repo, 6)
            self.assertNotIn("vue3", self._names(result))

        def test_godot_via_project_file(self):
            self._write("project.godot", "config_version=5")
            result = build_report(self.repo, 6)
            self.assertIn("godot", self._names(result))
            godot = next(s for s in result["stacks"] if s["name"] == "godot")
            self.assertEqual(godot["confidence"], "high")

        def test_powershell_via_scripts(self):
            self._write("scripts/deploy.ps1", "Write-Host 'hi'")
            result = build_report(self.repo, 6)
            self.assertIn("powershell", self._names(result))

        def test_aws_via_terraform_provider(self):
            self._write("infra/main.tf", 'provider "aws" {\n  region = "us-east-1"\n}\n')
            result = build_report(self.repo, 6)
            self.assertIn("aws", self._names(result))

        def test_azure_via_bicep(self):
            self._write("infra/main.bicep", "resource storage 'Microsoft.Storage/x' = {}")
            result = build_report(self.repo, 6)
            self.assertIn("azure", self._names(result))
            azure = next(s for s in result["stacks"] if s["name"] == "azure")
            self.assertEqual(azure["confidence"], "high")

        def test_empty_repo_returns_no_stacks_with_warning(self):
            result = build_report(self.repo, 6)
            self.assertEqual(result["stacks"], [])
            self.assertTrue(result["warnings"])

        def test_node_modules_is_skipped(self):
            self._write("node_modules/fakepkg/project.godot", "config_version=5")
            self._write("node_modules/fakepkg/deploy.ps1", "Write-Host 'hi'")
            result = build_report(self.repo, 6)
            self.assertEqual(result["stacks"], [])

        def test_db_via_csproj_ef_provider(self):
            self._write(
                "App/App.csproj",
                '<Project><ItemGroup>'
                '<PackageReference Include="Npgsql.EntityFrameworkCore.PostgreSQL" Version="7.0.0" />'
                '</ItemGroup></Project>'
            )
            result = build_report(self.repo, 6)
            self.assertIn("postgres", self._names(result))
            postgres = next(s for s in result["stacks"] if s["name"] == "postgres")
            self.assertEqual(postgres["confidence"], "high")

        def test_react_via_package_json(self):
            self._write("package.json", json.dumps(
                {"dependencies": {"react": "^18.2.0", "react-dom": "^18.2.0"}}))
            result = build_report(self.repo, 6)
            self.assertIn("react", self._names(result))

        def test_node_without_framework(self):
            self._write("package.json", json.dumps({"dependencies": {"express": "^4.18.0"}}))
            result = build_report(self.repo, 6)
            self.assertIn("node", self._names(result))

        def test_playwright_config_detected(self):
            self._write("playwright.config.ts", "export default {};")
            result = build_report(self.repo, 6)
            self.assertIn("playwright", self._names(result))

        def test_github_actions_workflow_detected(self):
            self._write(".github/workflows/ci.yml", "name: CI\non: [push]\n")
            result = build_report(self.repo, 6)
            self.assertIn("github-actions", self._names(result))

        def test_missing_repo_is_exit_2(self):
            self.assertEqual(main(["--repo", str(self.repo / "does-not-exist")]), 2)

        def test_skills_list_maps_detected_stacks(self):
            self._write("App/App.csproj", "<Project></Project>")
            self._write("scripts/deploy.ps1", "Write-Host 'hi'")
            result = build_report(self.repo, 6)
            self.assertIn("dotnet-backend-patterns", result["skills"])
            self.assertIn("powershell-script-patterns", result["skills"])

        def test_never_guess_every_stack_has_evidence(self):
            self._write("App/App.csproj", "<Project></Project>")
            self._write("project.godot", "config_version=5")
            result = build_report(self.repo, 6)
            for stack in result["stacks"]:
                self.assertTrue(1 <= len(stack["evidence"]) <= 5)

        def test_markdown_output_renders_heading(self):
            self._write("project.godot", "config_version=5")
            result = build_report(self.repo, 6)
            rendered = render_markdown(result)
            self.assertTrue(rendered.startswith("## Stacks (detected)"))
            self.assertIn("godot", rendered)

    suite = unittest.defaultTestLoader.loadTestsFromTestCase(DetectStackTests)
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
