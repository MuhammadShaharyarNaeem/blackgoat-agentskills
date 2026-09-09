#!/usr/bin/env python3
"""Zero-LLM adversarial eval: walks `check_test_authenticity.py` against a
fabricated repository holding a production module, twelve fake test files
reproducing the four tiers of fake test, and nine legitimate ones that must
stay green -- plus the waiver's two refusals and the ledger chain a later
gate reads its verdict out of.

The gate ships its own `--self-test`, which proves each predicate in-process
against synthetic fixtures. What that cannot prove is the property the
pipelines actually depend on: that the gate, invoked as a SUBPROCESS with
`--repo` and `--changed-files` the way the build and bugfix lanes invoke it,
returns the documented exit code AND names the documented problem code, per
file, on a real tree on disk -- and that the ledger line it writes is a link
a hand edit breaks.

WHY THE NEAR-MISS PAIRS ARE THE POINT
-------------------------------------
A gate that flagged every test file would pass a suite made only of fakes and
be useless in practice: nobody keeps a gate that fails the whole suite. So
every fake here is paired with a legitimate file that differs by ONE fact --

  * `synthetic-setcontent.spec.ts` builds its own DOM and never navigates;
    `real-setcontent-after-goto.spec.ts` does the same `setContent` AFTER a
    `page.goto`, round-tripping the app's own markup.
  * `source-eval-newfunction.spec.ts` reads production source as text and
    runs a slice; `real-fixture-read.spec.ts` reads a JSON FIXTURE and calls
    `new Function` on a harmless string.
  * `tautology-toplevel.spec.ts` transcribes a 20-statement production
    method; `real-tiny-helper.spec.ts` has a two-statement helper of the
    same name, below the size floor.
  * `tautology-module.spec.ts` has two distinct pure logic definitions and
    touches nothing; `real-e2e-helpers.spec.ts` has five helpers that all
    drive `page`, and `real-one-local-def.spec.ts` has one.

-- and the assertion is the EXACT problem-code set per file, not "something
failed". This gate has four codes that fire independently and routinely
co-occur; an exit code alone is right for the wrong reason constantly.

Deliberately needs no `claude -p` -- every step is a subprocess call to a
deterministic stdlib-Python CLI against fixture files this script writes, so
it is safe to run unconfirmed and is exempt from the suite's runs=5 doctrine,
which exists to average out LLM variance. There is none here.

See README.md in this directory for what this proves and when to re-run it.

Usage:
    python run.py               # run, print, record nothing
    python run.py --record      # ... and append one record to results/results.jsonl

Exit 0 only if every step passes. Prints a PASS/FAIL line per step and a
final RESULT: line; on failure the detail line shows the raw JSON the tool
produced. The script builds its own temp directory and removes it
unconditionally.

--record is OFF by default so an iteration loop on this file does not pollute
the run log, and `run-evals.ps1` passes it at the start of every confirmed
contract batch.
"""
import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

# evals/contract/test-authenticity-adversarial/run.py -> plugin root is 3 up.
PLUGIN_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = PLUGIN_ROOT / "skills" / "pipeline-tools" / "scripts"

CHECK_AUTH = SCRIPTS / "check_test_authenticity.py"
CHECK_LEDGER = SCRIPTS / "check_ledger.py"

# The shared record writer lives in evals/, two levels up from this file.
# Shared, not copied into each case, because the record shape has to match
# the one run-evals.ps1 appends to the same file.
sys.path.insert(0, str(PLUGIN_ROOT / "evals"))
from eval_record import append_script_record  # noqa: E402

MILESTONE = "M3: Slide alert stack [UI]"

results = []


def record(name, ok, detail=""):
    print("{0}  {1}".format("PASS" if ok else "FAIL", name))
    if not ok and detail:
        print("      {0}".format(detail))
    results.append((name, ok))


def run_gate(script, args, cwd):
    return subprocess.run(
        [sys.executable, str(script)] + [str(a) for a in args],
        cwd=str(cwd), capture_output=True, text=True)


def parse_json(proc, step_name):
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        record(step_name, False,
               "stdout was not JSON: {0!r} / stderr {1!r}".format(
                   proc.stdout[:400], proc.stderr[:200]))
        return None


def expect(step_name, proc, exit_code, predicate=None, why=""):
    """Assert the exit code, then a naming JSON field.

    An exit code alone can be right for the wrong reason -- this gate has
    three of them and four problem codes that co-occur.
    """
    data = parse_json(proc, step_name)
    if data is None:
        return None
    ok = proc.returncode == exit_code
    detail = ""
    if not ok:
        detail = "expected exit {0}, got {1}: {2}".format(
            exit_code, proc.returncode, json.dumps(data))
    elif predicate is not None and not predicate(data):
        ok = False
        detail = "exit {0} as expected, but {1}: {2}".format(
            exit_code, why, json.dumps(data))
    record(step_name, ok, detail)
    return data


def codes_of(data, rel):
    """The problem codes the gate named for one file, or None when absent."""
    for entry in data.get("files") or []:
        if entry["file"].replace("\\", "/").casefold() == rel.casefold():
            return sorted({pr["code"] for pr in entry["problems"]})
    return None


def verdict_of(data, rel):
    for entry in data.get("files") or []:
        if entry["file"].replace("\\", "/").casefold() == rel.casefold():
            return entry["verdict"]
    return None


# ---------------------------------------------------------------------------
# The fabricated repository
# ---------------------------------------------------------------------------
# Production code. Deliberately mixes the shapes the gate has to index: an
# EXPORTED function, a class METHOD with no `export` anywhere near it (the
# shape the real evidence transcribed), an exported class, a C# method with a
# return type between the modifiers and the name, and a Python def.
SRC = {
    "package.json": '{"name": "web", "version": "1.0.0"}\n',
    "src/asset/backup-card.ts": """\
import { Enums } from '../common/enums';

export default class BackupCard {
    getBackupItemStatus(backup: any): string {
        if (!backup) {
            return 'unknown';
        }
        if (backup.status === Enums.BackupStatus.Done) {
            return 'success';
        }
        if (backup.status === Enums.BackupStatus.Failing) {
            return 'failed';
        }
        if (backup.verifyFsStatus === 2) {
            return 'warning';
        }
        return 'in-progress';
    }

    getVerificationDisplay(status: number): string {
        if (status === 1) { return 'verified'; }
        if (status === 2) { return 'unverified'; }
        return 'unknown';
    }
}
""",
    "src/common/enums.ts": """\
export const Enums = {
    BackupStatus: { Done: 1, Failing: 2 },
    AlertType: { Slide: 'Slide' },
};
""",
    "src/asset/policy-visibility.ts": """\
export class PolicyVisibility {
    isPluginVisible(policy: any): boolean {
        if (!policy) { return false; }
        if (policy.hidden) { return false; }
        if (!policy.plugins) { return false; }
        return policy.plugins.indexOf('slide') !== -1;
    }
}
""",
    "Api/Api.csproj": "<Project Sdk=\"Microsoft.NET.Sdk\"></Project>\n",
    "Api/Handlers/OrderHandler.cs": """\
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
""",
    "src/pkg/__init__.py": "",
    "src/pkg/rules.py": """\
def classify_total(total):
    if total > 100:
        return "large"
    if total > 10:
        return "medium"
    return "small"
""",
}

# --- the thirteen fakes, and the exact code set each must produce ----------
FAKES = {}

# Tier A: tautology. The spec defines the thing it tests.
FAKES["tests/tautology-toplevel.spec.ts"] = (
    ["test_inline_reimplementation"], """\
import { test, expect } from '@playwright/test';

export function getBackupItemStatus(backup: any): string {
    if (!backup) {
        return 'unknown';
    }
    if (backup.status === 1) {
        return 'success';
    }
    if (backup.status === 2) {
        return 'failed';
    }
    if (backup.verifyFsStatus === 2) {
        return 'warning';
    }
    return 'in-progress';
}

test('the backup card classifies a done backup', async ({ page }) => {
    await page.goto('http://localhost:5000/devices/1');
    expect(getBackupItemStatus({ status: 1 })).toBe('success');
    expect(getBackupItemStatus({ status: 2 })).toBe('failed');
});
""")

FAKES["tests/tautology-evaluate.spec.ts"] = (
    ["test_inline_reimplementation"], """\
import { test, expect } from '@playwright/test';

test('the card computes visibility in the browser', async ({ page }) => {
    await page.goto('http://localhost:5000/devices/1');
    const result = await page.evaluate(() => {
        function getVerificationDisplay(status: number): string {
            if (status === 1) { return 'verified'; }
            if (status === 2) { return 'unverified'; }
            return 'unknown';
        }
        return getVerificationDisplay(2);
    });
    expect(result).toBe('unverified');
});
""")

FAKES["tests/tautology-transcribed.spec.ts"] = (
    ["test_inline_reimplementation"], """\
import { test, expect } from '@playwright/test';
import { Enums } from '../src/common/enums';

// ---------------------------------------------------------------------
// Helpers duplicating the pure card logic for hermetic verification
// (transcribed from src/asset/policy-visibility.ts)
// ---------------------------------------------------------------------
function isPluginVisible(policy: any): boolean {
    if (!policy) { return false; }
    if (policy.hidden) { return false; }
    if (!policy.plugins) { return false; }
    return policy.plugins.indexOf('slide') !== -1;
}

test('the plugin is visible for a slide policy', () => {
    expect(isPluginVisible({ plugins: ['slide'] })).toBe(true);
    expect(isPluginVisible({ hidden: true, plugins: ['slide'] })).toBe(false);
    expect(Enums.AlertType.Slide).toBe('Slide');
});
""")

FAKES["tests/tautology-module.spec.ts"] = (
    ["test_inline_reimplementation", "test_no_production_import"], """\
import { test, expect } from '@playwright/test';

function widenTheAlertSet(input: any) {
    const parts = String(input).split(',');
    const trimmed = parts.map((p) => p.trim());
    return trimmed.filter(Boolean);
}

function narrowTheAlertSet(input: any[]) {
    const seen = new Set();
    for (const item of input) {
        seen.add(item);
    }
    return Array.from(seen);
}

test('the alert set round-trips', () => {
    expect(narrowTheAlertSet(widenTheAlertSet('a,b,a'))).toEqual(['a', 'b']);
});
""")

# Tier B: source-text eval. Production code read as a string and run.
FAKES["tests/source-eval-newfunction.spec.ts"] = (
    ["test_source_eval"], """\
import { test, expect } from '@playwright/test';
import * as fs from 'fs';
import * as path from 'path';

const cardPath = path.resolve(__dirname, '../src/asset/backup-card.ts');
const cardSource = fs.existsSync(cardPath)
    ? fs.readFileSync(cardPath, 'utf-8')
    : '';

test('the sliced status expression still returns success', async ({ page }) => {
    await page.goto('http://localhost:5000/devices/1');
    const match = cardSource.match(/return 'success';/);
    expect(match).not.toBeNull();
    const evaluator = new Function('backup', "return 'success';");
    expect(evaluator({ status: 1 })).toBe('success');
});
""")

FAKES["tests/source-eval-transpile.spec.ts"] = (
    ["test_no_production_import", "test_source_eval"], """\
import { test, expect } from '@playwright/test';
import * as fs from 'fs';
import * as path from 'path';
import * as ts from 'typescript';

const cardPath = path.resolve(__dirname, '../src/asset/backup-card.ts');
const cardSource = fs.readFileSync(cardPath, 'utf-8');
const transpiled = ts.transpileModule(cardSource, { compilerOptions: {} });

test('the transpiled method body runs', () => {
    expect(transpiled.outputText.length).toBeGreaterThan(0);
});
""")

# Tier C: synthetic DOM. The markup under assertion is the test's own.
FAKES["tests/synthetic-setcontent.spec.ts"] = (
    ["test_no_production_import", "test_synthetic_dom"], """\
import { test, expect } from '@playwright/test';

test('the backup card shows a warning banner', async ({ page }) => {
    await page.setContent(`
        <div id="app">
            <div class="q-banner">Backup unverified</div>
        </div>
    `);
    await expect(page.locator('.q-banner')).toHaveText('Backup unverified');
});
""")

FAKES["tests/synthetic-innerhtml.spec.ts"] = (
    ["test_synthetic_dom"], """\
import { test, expect } from '@playwright/test';
import { Enums } from '../src/common/enums';

test('the toast markup renders', async ({ page }) => {
    await page.evaluate(() => {
        document.body.innerHTML = '<div class="toast">Slide alert</div>';
    });
    await expect(page.locator('.toast')).toHaveText('Slide alert');
    expect(Enums.AlertType.Slide).toBe('Slide');
});
""")

# Tier D: the fallback. It TRIES the app, then asserts against dummy HTML.
FAKES["tests/fallback-catch.spec.ts"] = (
    ["test_synthetic_dom"], """\
import { test, expect } from '@playwright/test';

test('the toast renders somewhere', async ({ page }) => {
    const baseUrl = process.env.TEST_BASE_URL || 'http://localhost:5000';
    try {
        await page.goto(baseUrl, { timeout: 3000 });
    } catch (e) {
        console.log('[E2E] app not reachable; testing toast rendering only');
        await page.setContent('<div id="app"><div class="toast">x</div></div>');
    }
    await expect(page.locator('.toast')).toBeVisible();
});
""")

# The floor case: nothing but inline literals. It touches nothing at all.
FAKES["tests/hermetic-enum.spec.ts"] = (
    ["test_no_production_import"], """\
import { test, expect } from '@playwright/test';

test('the slide task type enumeration maps correctly', () => {
    const SlideTaskType = {
        Install: 0,
        Restart: 1,
        ServiceHealth: 2,
        Reinstall: 3,
    };
    expect(SlideTaskType.Restart).toBe(1);
    expect(SlideTaskType.Reinstall).toBe(3);
});
""")

FAKES["Api.Tests/CopyTests.cs"] = (
    ["test_inline_reimplementation", "test_no_production_import"], """\
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
""")

FAKES["tests/test_copy.py"] = (
    ["test_inline_reimplementation", "test_no_production_import"], """\
def classify_total(total):
    if total > 100:
        return "large"
    if total > 10:
        return "medium"
    return "small"


def test_classifies_a_large_total():
    assert classify_total(500) == "large"


def test_classifies_a_small_total():
    assert classify_total(1) == "small"
""")

# --- the legitimate set, every one a near-miss of a fake above -------------
LEGIT = {}

LEGIT["tests/real-import.spec.ts"] = """\
import { test, expect } from '@playwright/test';
import BackupCard from '../src/asset/backup-card';

test('the shipped card classifies a done backup', () => {
    const card = new BackupCard();
    expect(card.getBackupItemStatus({ status: 1 })).toBe('success');
    expect(card.getBackupItemStatus({ status: 2 })).toBe('failed');
});
"""

LEGIT["tests/real-e2e.spec.ts"] = """\
import { test, expect } from '@playwright/test';

test('the device page shows the backup card', async ({ page }) => {
    await page.goto('http://localhost:5000/devices/1');
    await expect(page.locator('#backup-card')).toBeVisible();
    await expect(page.locator('#backup-card .status')).toHaveText('success');
});
"""

# The near-miss for tautology-module: five helpers, all of which DRIVE the
# app. A gate that counted definitions without the driver rule fails here.
LEGIT["tests/real-e2e-helpers.spec.ts"] = """\
import { test, expect } from '@playwright/test';

async function login(page: any, email: string, password: string) {
    await page.fill('#email', email);
    await page.fill('#password', password);
    await page.click('button[type=submit]');
    await page.waitForURL(/dashboard/);
}

async function openNavDrawer(page: any) {
    const toggle = page.locator('#nav-toggle');
    await toggle.waitFor();
    await toggle.click();
    await page.waitForSelector('#nav-drawer.open');
}

async function getBackupItemStatus(page: any) {
    const el = page.locator('#backup-card .status');
    await el.waitFor();
    const text = await el.innerText();
    return text.trim();
}

async function getVerificationDisplay(page: any) {
    const el = page.locator('#backup-card .verify');
    await el.waitFor();
    return (await el.innerText()).trim();
}

async function pollSlideIntegrationGetter(page: any) {
    for (let i = 0; i < 10; i++) {
        const ready = await page.locator('#slide-ready').count();
        if (ready > 0) { return true; }
        await page.waitForTimeout(200);
    }
    return false;
}

test('a logged-in user sees the backup status', async ({ page }) => {
    await page.goto('http://localhost:5000/');
    await login(page, 'a@b.c', 'pw');
    await openNavDrawer(page);
    expect(await pollSlideIntegrationGetter(page)).toBe(true);
    expect(await getBackupItemStatus(page)).toBe('success');
    expect(await getVerificationDisplay(page)).toBe('verified');
});
"""

# The near-miss for synthetic-setcontent: the SAME setContent call, after a
# goto, round-tripping the application's own markup.
LEGIT["tests/real-setcontent-after-goto.spec.ts"] = """\
import { test, expect } from '@playwright/test';

test('the printable report renders the same markup', async ({ page }) => {
    await page.goto('http://localhost:5000/reports/1');
    const html = await page.content();
    await page.setContent(html);
    await expect(page.locator('#report')).toBeVisible();
});
"""

# The near-miss for source-eval-newfunction: a JSON FIXTURE read, plus a
# `new Function` that touches no production text.
LEGIT["tests/real-fixture-read.spec.ts"] = """\
import { test, expect } from '@playwright/test';
import * as fs from 'fs';
import * as path from 'path';
import BackupCard from '../src/asset/backup-card';

const fixture = JSON.parse(fs.readFileSync(
    path.resolve(__dirname, './backups.fixture.json'), 'utf-8'));

test('the fixture drives the shipped card', () => {
    const identity = new Function('x', 'return x;');
    const card = new BackupCard();
    expect(identity(card.getBackupItemStatus(fixture.rows[0]))).toBe('success');
});
"""

# The near-miss for tautology-toplevel: same NAME, two statements, below the
# size floor -- a genuine convenience wrapper, not a transcription.
LEGIT["tests/real-tiny-helper.spec.ts"] = """\
import { test, expect } from '@playwright/test';
import BackupCard from '../src/asset/backup-card';

function getBackupItemStatus(backup: any) {
    return new BackupCard().getBackupItemStatus(backup);
}

test('the wrapper delegates to the shipped card', () => {
    expect(getBackupItemStatus({ status: 1 })).toBe('success');
});
"""

# The near-miss for the ">= 2 distinct definitions" branch: exactly one.
LEGIT["tests/real-one-local-def.spec.ts"] = """\
import { test, expect } from '@playwright/test';

test('the running app answers on the orders endpoint', async ({ request }) => {
    function normaliseOnlyHere(input: any) {
        const s = String(input).trim();
        const lower = s.toLowerCase();
        return lower.replace(/\\s+/g, '-');
    }
    const response = await request.get('http://localhost:5000/api/orders');
    expect(response.status()).toBe(200);
    expect(normaliseOnlyHere(' A B ')).toBe('a-b');
});
"""

LEGIT["Api.Tests/OrderHandlerTests.cs"] = """\
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

    [Fact]
    public void ClassifiesASmallOrder()
    {
        var handler = new OrderHandler();
        Assert.Equal("small", handler.Classify(1));
    }
}
"""

LEGIT["tests/test_rules.py"] = """\
from pkg.rules import classify_total


def test_classifies_a_large_total():
    assert classify_total(500) == "large"


def test_classifies_a_small_total():
    assert classify_total(1) == "small"
"""

FIXTURE_JSON = '{"rows": [{"status": 1}]}\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record", action="store_true",
                        help="append one flat record to "
                             "evals/results/results.jsonl")
    args = parser.parse_args()

    started = time.time()
    tmp = Path(tempfile.mkdtemp(prefix="eval-test-authenticity-adversarial-"))
    try:
        run_suite(tmp)
    finally:
        shutil.rmtree(str(tmp), ignore_errors=True)
    duration = round(time.time() - started, 2)

    print()
    failed = [n for n, ok in results if not ok]
    if failed:
        print("RESULT: FAIL ({0}/{1} steps failed)".format(len(failed),
                                                           len(results)))
    else:
        print("RESULT: PASS ({0}/{1} steps passed)".format(len(results),
                                                           len(results)))

    if args.record:
        detail = None
        if failed:
            detail = " | ".join("[FAIL] {0}".format(n) for n in failed)
        append_script_record(case="test-authenticity-adversarial",
                             passed=(not failed), failed_criterion=detail,
                             duration_s=duration)
    return 1 if failed else 0


def run_suite(work):
    repo = work / "web"
    ledger = work / "gates.jsonl"

    def write(rel, content):
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    for rel, content in SRC.items():
        write(rel, content)
    for rel, (_, content) in FAKES.items():
        write(rel, content)
    for rel, content in LEGIT.items():
        write(rel, content)
    write("tests/backups.fixture.json", FIXTURE_JSON)

    # Every gate invocation goes through `auth`, which counts them: step 38
    # asserts ONE ledger record per run, and a hand-maintained expected
    # count is exactly the thing that drifts the moment a step is inserted.
    gate_runs = [0]

    def auth(extra_argv):
        gate_runs[0] += 1
        return run_gate(CHECK_AUTH, extra_argv, work)

    def judge(files, extra=()):
        return auth(["--repo", str(repo), "--milestone", MILESTONE,
                     "--ledger", ledger, "--json", "--changed-files"]
                    + list(files) + list(extra))

    step = [0]

    def n():
        step[0] += 1
        return step[0]

    # --- 1. the whole legitimate set is green ------------------------------
    legit_files = sorted(LEGIT)
    expect("{0}. the {1} legitimate test files -> exit 0 (PASS, no problem "
           "of any kind)".format(n(), len(legit_files)),
           judge(legit_files), 0,
           lambda d: d.get("result") == "PASS"
           and d.get("problem_codes") == []
           and len(d.get("files") or []) == len(legit_files),
           "a legitimate test file was flagged, which is the failure mode "
           "that gets a gate deleted")

    # --- 2. the whole fake set fails, and names all four codes -------------
    fake_files = sorted(FAKES)
    data = expect("{0}. the {1} fake test files -> exit 1 (FAIL, all four "
                  "problem codes named)".format(n(), len(fake_files)),
                  judge(fake_files), 1,
                  lambda d: d.get("result") == "FAIL"
                  and set(d.get("problem_codes") or []) == {
                      "test_no_production_import",
                      "test_inline_reimplementation",
                      "test_source_eval",
                      "test_synthetic_dom"}
                  and all(e["verdict"] == "FAIL" for e in d["files"]),
                  "the fake set did not fail on all four codes with every "
                  "file marked FAIL")

    # --- 3..15. the EXACT code set, per fake file --------------------------
    # Per-file, not rolled up: the four codes co-occur, so a roll-up over the
    # whole set stays green when one detection rule regresses and another
    # fires on the same file.
    for rel in fake_files:
        wanted = sorted(FAKES[rel][0])
        got = codes_of(data, rel) if data else None
        record("{0}. {1} -> exactly {2}".format(n(), rel, wanted),
               got == wanted,
               "expected {0}, got {1}".format(wanted, got))

    # --- 16..26. every legitimate file individually PASSes ----------------
    for rel in legit_files:
        proc = judge([rel])
        expect("{0}. {1} -> exit 0 (PASS)".format(n(), rel), proc, 0,
               lambda d, r=rel: verdict_of(d, r) == "PASS",
               "a legitimate file did not pass on its own")

    # --- a non-test file in the set is REPORTED and not judged -------------
    proc = judge(["src/asset/backup-card.ts", "tests/real-e2e.spec.ts"])
    expect("{0}. a non-test file in the changed set is ignored and reported, "
           "not judged".format(n()), proc, 0,
           lambda d: len(d["files"]) == 1
           and len(d["ignored"]) == 1
           and d["ignored"][0]["file"] == "src/asset/backup-card.ts",
           "the production file was judged as a test, or silently dropped")

    # --- --files is the same flag as --changed-files ------------------------
    proc = auth(["--repo", str(repo), "--ledger", ledger, "--json",
                 "--files", "tests/synthetic-setcontent.spec.ts"])
    expect("{0}. --files is accepted as a synonym of --changed-files".format(n()),
           proc, 1,
           lambda d: codes_of(d, "tests/synthetic-setcontent.spec.ts") == [
               "test_no_production_import", "test_synthetic_dom"],
           "the --files spelling did not judge the same file the same way")

    # --- a Windows backslash path is the same file --------------------------
    proc = judge(["tests\\synthetic-setcontent.spec.ts"])
    expect("{0}. a Windows backslash path names the same file".format(n()),
           proc, 1,
           lambda d: (d["files"][0]["file"] ==
                      "tests/synthetic-setcontent.spec.ts"),
           "a backslash path was not normalised")

    # --- --src-roots override ----------------------------------------------
    # With the production tree declared as `Api` only, the TS tautology has
    # nothing to match against and drops to the untouched-product code.
    proc = auth(["--repo", str(repo), "--ledger", ledger, "--json",
                 "--src-roots", "Api", "--changed-files",
                 "tests/tautology-module.spec.ts"])
    expect("{0}. --src-roots replaces the discovered roots".format(n()),
           proc, 1,
           lambda d: d["src_roots"] == ["Api"],
           "the explicit src root was not the only one used")

    # --- --test-globs override ---------------------------------------------
    write("weird/thing.check.ts", LEGIT["tests/real-e2e.spec.ts"])
    proc = auth(["--repo", str(repo), "--ledger", ledger, "--json",
                 "--test-globs", "**/*.check.ts", "--changed-files",
                 "weird/thing.check.ts"])
    expect("{0}. --test-globs decides what counts as a test file".format(n()),
           proc, 0,
           lambda d: len(d["files"]) == 1 and not d["ignored"],
           "the overridden glob did not bring the file into scope")

    # --- the waiver: refusals first ----------------------------------------
    proc = judge(["tests/synthetic-setcontent.spec.ts"],
                 ["--allow", "tests/synthetic-setcontent.spec.ts",
                  "--reason", "   "])
    expect("{0}. --reason \"   \" -> exit 2 (a whitespace waiver is not a "
           "reason)".format(n()), proc, 2,
           lambda d: d.get("result") == "ERROR",
           "a whitespace-only waiver was accepted")

    proc = judge(["tests/synthetic-setcontent.spec.ts"],
                 ["--allow", "tests/synthetic-setcontent.spec.ts"])
    expect("{0}. --allow with no paired --reason -> exit 2".format(n()),
           proc, 2,
           lambda d: "paired --reason" in (d.get("error") or ""),
           "an unpaired --allow was accepted")

    # --- the waiver: the reasoned path -------------------------------------
    reason = "PLAN-311 - print-template snapshot; the DOM IS the artifact"
    proc = judge(["tests/synthetic-setcontent.spec.ts"],
                 ["--allow", "tests/synthetic-setcontent.spec.ts",
                  "--reason", reason])
    expect("{0}. a reasoned waiver -> exit 0 (ALLOWED, problems still "
           "listed)".format(n()), proc, 0,
           lambda d: d.get("result") == "ALLOWED"
           and verdict_of(d, "tests/synthetic-setcontent.spec.ts") == "ALLOWED"
           and codes_of(d, "tests/synthetic-setcontent.spec.ts") == [
               "test_no_production_import", "test_synthetic_dom"],
           "the waiver either failed to clear the file or erased the findings")

    lines = [l for l in ledger.read_text(encoding="utf-8").splitlines()
             if l.strip()]
    waived = json.loads(lines[-1])
    record("{0}. the waiver's reason is durable in the ledger record".format(n()),
           waived.get("verdict") == "PASS"
           and reason in json.dumps(waived.get("allow_reasons") or {})
           and waived.get("milestone") == MILESTONE,
           "the record does not carry the reason: {0}".format(
               json.dumps(waived)))

    # --- a waiver for a DIFFERENT file does not clear this one --------------
    proc = judge(["tests/synthetic-setcontent.spec.ts",
                  "tests/real-e2e.spec.ts"],
                 ["--allow", "tests/real-e2e.spec.ts",
                  "--reason", "not the failing one"])
    expect("{0}. a waiver naming another file leaves the failure standing "
           "-> exit 1".format(n()), proc, 1,
           lambda d: d.get("result") == "FAIL"
           and verdict_of(d, "tests/synthetic-setcontent.spec.ts") == "FAIL",
           "a waiver leaked onto a file it did not name")

    # --- usage refusals ----------------------------------------------------
    proc = auth(["--repo", str(repo), "--ledger", ledger, "--json"])
    expect("{0}. no --changed-files -> exit 2".format(n()), proc, 2,
           lambda d: "--changed-files" in (d.get("error") or ""),
           "an empty file set was not refused")

    proc = auth(["--ledger", ledger, "--json",
                 "--changed-files", "a.spec.ts"])
    expect("{0}. no --repo -> exit 2".format(n()), proc, 2,
           lambda d: "--repo" in (d.get("error") or ""),
           "a missing --repo was not refused")

    proc = judge(["tests/does-not-exist.spec.ts"])
    expect("{0}. a file that is not on disk -> exit 2".format(n()), proc, 2,
           lambda d: "file not found" in (d.get("error") or ""),
           "a missing input was reported as a verdict instead of an error")

    bare = work / "bare"
    (bare / "tests").mkdir(parents=True)
    (bare / "tests" / "a.spec.ts").write_text(LEGIT["tests/real-e2e.spec.ts"],
                                              encoding="utf-8")
    proc = auth(["--repo", str(bare), "--ledger", ledger, "--json",
                 "--changed-files", "tests/a.spec.ts"])
    expect("{0}. a repo with no discoverable src root -> exit 2, never a "
           "PASS".format(n()), proc, 2,
           lambda d: "no src root" in (d.get("error") or ""),
           "an empty production index produced a verdict, which would mark "
           "every test file authentic")

    # --- the ledger --------------------------------------------------------
    lines = [l for l in ledger.read_text(encoding="utf-8").splitlines()
             if l.strip()]
    record("{0}. one ledger record per run, on every exit path (0, 1 and "
           "2)".format(n()),
           len(lines) == gate_runs[0]
           and {json.loads(l)["verdict"] for l in lines} == {"PASS", "FAIL",
                                                             "ERROR"},
           "expected {0} records (one per gate invocation) covering all "
           "three verdicts, got {1}: {2}".format(gate_runs[0], len(lines),
                        sorted({json.loads(l)["verdict"] for l in lines})))

    proc = run_gate(CHECK_LEDGER, ["--ledger", ledger], work)
    expect("{0}. check_ledger.py on the ledger this gate wrote -> exit 0 "
           "(intact)".format(n()), proc, 0,
           lambda d: d.get("pass") is True and d.get("legacy_records") == 0
           and d.get("chained_records") == len(lines),
           "the records this gate wrote did not verify as a chain")

    # The forgery the chain exists to catch: flip a recorded FAIL to a PASS
    # so a downstream `--require-ledger-gates check_test_authenticity.py`
    # reads a green over a suite of fakes.
    forged = []
    edited_index = None
    for index, line in enumerate(lines):
        obj = json.loads(line)
        if obj["verdict"] == "FAIL" and edited_index is None:
            obj["verdict"] = "PASS"
            obj["exit"] = 0
            edited_index = index
            forged.append(json.dumps(obj))
        else:
            forged.append(line)
    tampered = work / "tampered.jsonl"
    tampered.write_text("\n".join(forged) + "\n", encoding="utf-8")
    proc = run_gate(CHECK_LEDGER, ["--ledger", tampered], work)
    expect("{0}. a FAIL hand-edited to PASS -> check_ledger.py exit 1 "
           "(self-mismatch on that line)".format(n()), proc, 1,
           lambda d: d.get("pass") is False
           and (d.get("problem") or {}).get("reason") == "self-mismatch"
           and (d.get("problem") or {}).get("line") == edited_index + 1,
           "the edited verdict was not caught on its own line")

    dropped = lines[:1] + lines[2:]
    thinned = work / "thinned.jsonl"
    thinned.write_text("\n".join(dropped) + "\n", encoding="utf-8")
    proc = run_gate(CHECK_LEDGER, ["--ledger", thinned], work)
    expect("{0}. a removed record -> check_ledger.py exit 1 "
           "(prev-mismatch)".format(n()), proc, 1,
           lambda d: d.get("pass") is False
           and (d.get("problem") or {}).get("reason") == "prev-mismatch",
           "removing a record did not break the following line's prev")

    # --- the ledger names the failing files, not just a verdict ------------
    fail_recs = [json.loads(l) for l in lines
                 if json.loads(l)["verdict"] == "FAIL"]
    record("{0}. every FAIL record names its problem codes AND its failing "
           "files".format(n()),
           bool(fail_recs) and all(
               r.get("problem_codes") and r.get("failing_files")
               for r in fail_recs),
           "a FAIL record carried no code or no file name: {0}".format(
               json.dumps(fail_recs[:1])))


if __name__ == "__main__":
    sys.exit(main())
